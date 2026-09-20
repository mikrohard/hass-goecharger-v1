"""Data update coordinator for the go-eCharger (API v1) integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GoeChargerApi, GoeChargerError
from .const import AMX_CONFIRM_TIMEOUT, DOMAIN, LOGGER, MIN_CURRENT
from .util import StatusData, get_int


class GoeChargerCoordinator(DataUpdateCoordinator[StatusData]):
    """Poll the charger and keep the last known status on failures.

    A failed poll never raises UpdateFailed once a first status has been
    received, so entities keep their last values instead of turning
    unavailable. The connection state is tracked separately and exposed
    through the connectivity binary sensor.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: GoeChargerApi,
        scan_interval: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {api.host}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.connected: bool = False
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.consecutive_failures: int = 0

        # Last max current confirmed (or, on firmwares without amx in the
        # status, simply requested) through amx. amx lives in RAM on the
        # charger and is not mirrored into `amp`.
        self.requested_max_current: int | None = None
        # An amx write the charger has not reflected in its status yet.
        self.pending_max_current: int | None = None
        self.pending_since: datetime | None = None
        self.amx_workaround_applied: bool = False
        self.amx_last_error: str | None = None
        self._cancel_amx_check: callback | None = None
        # Reboot counter seen in the last status, used to detect reboots.
        self._last_reboot_counter: int | None = None

    @property
    def serial(self) -> str:
        """Return the serial number used to identify the device."""
        serial = self.config_entry.unique_id
        if not serial and self.data:
            serial = str(self.data.get("sse") or "")
        return serial or self.api.host

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> StatusData:
        """Fetch the status object, keeping old data on failure."""
        try:
            status = await self.api.get_status()
        except GoeChargerError as err:
            self._record_failure(err)
            if self.data is None:
                # No data yet: let Home Assistant retry the setup.
                raise UpdateFailed(str(err)) from err
            return self.data
        self._record_success()
        self._process_status(status)
        return status

    def _record_failure(self, err: Exception) -> None:
        """Bookkeeping for a failed request."""
        self.consecutive_failures += 1
        self.last_error = str(err) or type(err).__name__
        if self.connected or self.consecutive_failures == 1:
            LOGGER.warning(
                "Lost connection to go-eCharger at %s, keeping last known values: %s",
                self.api.host,
                self.last_error,
            )
        else:
            LOGGER.debug(
                "go-eCharger at %s still unreachable (%d consecutive failures): %s",
                self.api.host,
                self.consecutive_failures,
                self.last_error,
            )
        self.connected = False

    def _record_success(self) -> None:
        """Bookkeeping for a successful request."""
        if not self.connected and self.consecutive_failures:
            LOGGER.info(
                "Connection to go-eCharger at %s restored after %d failed attempt(s)",
                self.api.host,
                self.consecutive_failures,
            )
        self.connected = True
        self.consecutive_failures = 0
        self.last_error = None
        self.last_success = dt_util.utcnow()

    def _process_status(self, status: StatusData) -> None:
        """Run the checks that look at every fresh status object."""
        self._check_reboot(status)
        self._check_pending_max_current(status)

    def _check_reboot(self, status: StatusData) -> None:
        """Detect a charger reboot from the reboot counter."""
        counter = get_int(status, "rbc")
        if counter is None:
            return
        previous = self._last_reboot_counter
        self._last_reboot_counter = counter
        if previous is None or counter == previous:
            return
        LOGGER.info(
            "go-eCharger at %s rebooted (reboot counter %d -> %d); amx fell back "
            "to amp=%s",
            self.api.host,
            previous,
            counter,
            status.get("amp"),
        )
        # After a reboot the charger charges with the flash value again.
        self.requested_max_current = get_int(status, "amp")

    # -------------------------------------------------------------- commands

    async def async_send_command(
        self, key: str, value: Any, *, expected: Any | None = None
    ) -> StatusData:
        """Send a command, apply the returned status and optionally verify it."""
        try:
            status = await self.api.set_value(key, value)
        except GoeChargerError as err:
            self._record_failure(err)
            # Let the connectivity sensor reflect the failure right away.
            self.async_update_listeners()
            raise HomeAssistantError(
                f"Failed to send {key}={value} to go-eCharger at {self.api.host}: {err}"
            ) from err

        self._record_success()
        self._process_status(status)
        self.async_set_updated_data(status)

        if expected is not None and str(status.get(key)) != str(expected):
            raise HomeAssistantError(
                f"go-eCharger did not accept {key}={value} "
                f"(charger reports {key}={status.get(key)!r})"
            )
        return status

    async def async_set_allow_charging(self, allow: bool) -> None:
        """Allow or forbid charging (alw)."""
        value = 1 if allow else 0
        await self.async_send_command("alw", value, expected=value)

    # ------------------------------------------------------------ max current

    @property
    def effective_max_current(self) -> int | None:
        """Return the max current the charger is believed to use.

        While a write is pending the requested value is shown. Otherwise the
        `amx` reported by the charger is used, falling back to the last value
        written by this integration on firmwares that do not report amx.
        """
        if self.pending_max_current is not None:
            return self.pending_max_current
        reported = get_int(self.data, "amx")
        if reported is not None:
            return reported
        return self.requested_max_current

    async def async_set_max_current(self, amps: int) -> None:
        """Set the max charging current for dynamic charging via amx.

        amx is not written to flash and is therefore the recommended way to
        adjust the current frequently (PV surplus charging). The charger
        reports amx in its status, but only a few seconds after the write, so
        the value is not verified here. Instead the write is tracked as
        pending and checked against every fresh status (see
        _check_pending_max_current) until it is confirmed or times out.
        """
        self._cancel_pending_check()
        self.amx_last_error = None
        await self.async_send_command("amx", amps)

        if get_int(self.data, "amx") is None:
            # Firmware without amx in the status: nothing to verify against.
            self.requested_max_current = amps
            self.pending_max_current = None
            self.async_update_listeners()
            return

        self.pending_max_current = amps
        self.pending_since = dt_util.utcnow()
        self.amx_workaround_applied = False
        # The command response itself may already confirm the value.
        self._check_pending_max_current(self.data)
        if self.pending_max_current is not None:
            self._schedule_pending_check()
        self.async_update_listeners()

    def _check_pending_max_current(self, status: StatusData) -> None:
        """Confirm a pending amx write or, after the timeout, work around it."""
        amps = self.pending_max_current
        if amps is None or self.pending_since is None:
            return
        reported = get_int(status, "amx")
        if reported == amps:
            LOGGER.debug("go-eCharger at %s confirmed amx=%d", self.api.host, amps)
            self.requested_max_current = amps
            self._clear_pending()
            return

        elapsed = (dt_util.utcnow() - self.pending_since).total_seconds()
        if elapsed < AMX_CONFIRM_TIMEOUT:
            return

        if not self.amx_workaround_applied:
            LOGGER.warning(
                "go-eCharger at %s still reports amx=%s %.0f s after requesting "
                "%d A; applying the firmware 0.42.0 workaround (amp=6, amp=<max>, "
                "amx=%d)",
                self.api.host,
                reported,
                elapsed,
                amps,
                amps,
            )
            self.amx_workaround_applied = True
            self.pending_since = dt_util.utcnow()
            self._cancel_pending_check()
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_run_amx_workaround(amps),
                name=f"{DOMAIN} amx workaround",
            )
            return

        self.amx_last_error = (
            f"Charger did not apply max current {amps} A within "
            f"{AMX_CONFIRM_TIMEOUT} s even after the amp workaround "
            f"(charger reports amx={reported})"
        )
        LOGGER.error("go-eCharger at %s: %s", self.api.host, self.amx_last_error)
        self._clear_pending()

    async def _async_run_amx_workaround(self, amps: int) -> None:
        """Send amp=6, amp=<flash value>, then amx again."""
        flash_amp = get_int(self.data, "amp")
        # Restore the flash value (e.g. 16 A) but never less than what is
        # being requested, and never above the absolute maximum.
        restore_amp = max(flash_amp or 0, amps, MIN_CURRENT)
        absolute_max = get_int(self.data, "ama")
        if absolute_max and absolute_max >= MIN_CURRENT:
            restore_amp = min(restore_amp, absolute_max)
        try:
            await self.async_send_command("amp", MIN_CURRENT, expected=MIN_CURRENT)
            await self.async_send_command("amp", restore_amp, expected=restore_amp)
            await self.async_send_command("amx", amps)
        except HomeAssistantError as err:
            self.amx_last_error = f"amx workaround failed: {err}"
            LOGGER.error("go-eCharger at %s: %s", self.api.host, self.amx_last_error)
            self._clear_pending()
            self.async_update_listeners()
            return
        if self.pending_max_current is not None:
            self._schedule_pending_check()

    def _schedule_pending_check(self) -> None:
        """Make sure a status is fetched once the confirmation timeout is over."""
        self._cancel_pending_check()

        @callback
        def _due(_now: datetime) -> None:
            self._cancel_amx_check = None
            if self.pending_max_current is not None:
                self.hass.async_create_task(self.async_request_refresh())

        self._cancel_amx_check = async_call_later(
            self.hass, AMX_CONFIRM_TIMEOUT + 1, _due
        )

    def _cancel_pending_check(self) -> None:
        if self._cancel_amx_check is not None:
            self._cancel_amx_check()
            self._cancel_amx_check = None

    def _clear_pending(self) -> None:
        self.pending_max_current = None
        self.pending_since = None
        self._cancel_pending_check()


type GoeChargerConfigEntry = ConfigEntry[GoeChargerCoordinator]
