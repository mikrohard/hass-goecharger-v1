"""Config flow for the go-eCharger (API v1) integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .api import GoeChargerApi, GoeChargerError, normalize_host
from .const import (
    CONF_AUTO_REBOOT_NO_GROUND,
    DEFAULT_AUTO_REBOOT_NO_GROUND,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .util import StatusData


def _build_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Schema shared by the user, reconfigure and options steps."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
            ),
            vol.Required(
                CONF_AUTO_REBOOT_NO_GROUND,
                default=defaults.get(
                    CONF_AUTO_REBOOT_NO_GROUND, DEFAULT_AUTO_REBOOT_NO_GROUND
                ),
            ): BooleanSelector(),
        }
    )


async def _async_try_connect(hass: HomeAssistant, host: str) -> StatusData:
    """Fetch the status once to validate the host. Raises GoeChargerError."""
    api = GoeChargerApi(async_get_clientsession(hass), host, retries=2)
    return await api.get_status()


def _clean_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise user input into the data stored on the config entry."""
    return {
        CONF_HOST: normalize_host(user_input[CONF_HOST]),
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
        CONF_AUTO_REBOOT_NO_GROUND: bool(
            user_input.get(CONF_AUTO_REBOOT_NO_GROUND, DEFAULT_AUTO_REBOOT_NO_GROUND)
        ),
    }


class GoeChargerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration and reconfiguration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GoeChargerOptionsFlow:
        """Return the options flow handler."""
        return GoeChargerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean_input(user_input)
            if not data[CONF_HOST]:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    status = await _async_try_connect(self.hass, data[CONF_HOST])
                except GoeChargerError as err:
                    LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
                    errors["base"] = "cannot_connect"
                else:
                    serial = str(status.get("sse") or "").strip()
                    if serial:
                        await self.async_set_unique_id(serial)
                        self._abort_if_unique_id_configured(updates=data)
                    return self.async_create_entry(
                        title=f"go-eCharger {serial or data[CONF_HOST]}", data=data
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host and/or refresh interval of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean_input(user_input)
            if not data[CONF_HOST]:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    status = await _async_try_connect(self.hass, data[CONF_HOST])
                except GoeChargerError as err:
                    LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
                    errors["base"] = "cannot_connect"
                else:
                    serial = str(status.get("sse") or "").strip()
                    if entry.unique_id and serial and serial != entry.unique_id:
                        errors["base"] = "wrong_device"
                    else:
                        return self.async_update_reload_and_abort(
                            entry, data_updates=data
                        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_schema(user_input or entry.data),
            errors=errors,
        )


class GoeChargerOptionsFlow(OptionsFlow):
    """Options flow exposing the same host / interval settings.

    Both values live in `entry.data`, so this flow updates the entry data
    and reloads the integration rather than writing separate options.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean_input(user_input)
            if not data[CONF_HOST]:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    status = await _async_try_connect(self.hass, data[CONF_HOST])
                except GoeChargerError as err:
                    LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
                    errors["base"] = "cannot_connect"
                else:
                    serial = str(status.get("sse") or "").strip()
                    if entry.unique_id and serial and serial != entry.unique_id:
                        errors["base"] = "wrong_device"
                    else:
                        if self.hass.config_entries.async_update_entry(
                            entry, data={**entry.data, **data}
                        ):
                            self.hass.config_entries.async_schedule_reload(entry.entry_id)
                        return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(user_input or entry.data),
            errors=errors,
        )
