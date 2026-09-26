"""Tests for setup, entities, connection handling and commands."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.goecharger_v1.const import DOMAIN

from .conftest import SERIAL, FakeCharger

PREFIX = f"go_echarger_{SERIAL}"
CONNECTION = f"binary_sensor.{PREFIX}_connection"
CAR_STATUS = f"sensor.{PREFIX}_car_status"
POWER = f"sensor.{PREFIX}_power"
SWITCH = f"switch.{PREFIX}_allow_charging"
SELECT = f"select.{PREFIX}_max_current"


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 5) -> None:
    """Advance time past the scan interval and let the coordinator poll."""
    freezer.tick(timedelta(seconds=seconds + 1))
    async_fire_time_changed(hass)
    # The coordinator refresh runs as a background task doing real HTTP I/O.
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_entities_created_with_values(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Status values are converted and exposed correctly."""
    assert setup_entry.state is ConfigEntryState.LOADED

    assert hass.states.get(CAR_STATUS).state == "charging"
    assert hass.states.get(f"sensor.{PREFIX}_stored_charging_current").state == "16"
    assert hass.states.get(f"sensor.{PREFIX}_error").state == "none"
    assert hass.states.get(f"sensor.{PREFIX}_temperature") is None  # disabled by default
    assert float(hass.states.get(f"sensor.{PREFIX}_session_energy").state) == pytest.approx(1.0)
    assert float(hass.states.get(f"sensor.{PREFIX}_total_energy").state) == pytest.approx(123.4)
    assert hass.states.get(POWER).state == "6900.0"
    assert hass.states.get(f"sensor.{PREFIX}_voltage_l1").state == "230.0"
    assert hass.states.get(f"sensor.{PREFIX}_current_l2").state == "10.1"
    assert hass.states.get(f"sensor.{PREFIX}_power_l3").state == "2300.0"

    phases = hass.states.get(f"sensor.{PREFIX}_phases_available")
    assert phases.state == "3"
    assert phases.attributes["l1"] is True
    assert hass.states.get(f"sensor.{PREFIX}_phases_active").state == "0"

    assert hass.states.get(f"binary_sensor.{PREFIX}_vehicle_connected").state == STATE_ON
    assert hass.states.get(f"binary_sensor.{PREFIX}_charging").state == STATE_ON
    assert hass.states.get(CONNECTION).state == STATE_ON

    assert hass.states.get(SWITCH).state == STATE_ON
    select = hass.states.get(SELECT)
    assert select.state == "16"  # amx reported by the charger
    assert select.attributes["options"] == [str(a) for a in range(6, 17)]  # up to ama
    assert select.attributes["flash_current"] == 16
    assert select.attributes["reported_by_charger"] is True
    assert select.attributes["pending_value"] is None
    assert hass.states.get(f"sensor.{PREFIX}_reported_max_current").state == "16"


async def test_real_firmware_042_status(
    hass: HomeAssistant, charger: FakeCharger, real_status: dict
) -> None:
    """The captured status of a real charger on firmware 042.0 sets up fine."""
    charger.status = real_status
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=real_status["sse"],
        data={CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 5},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    prefix = f"go_echarger_{real_status['sse']}"
    assert hass.states.get(f"sensor.{prefix}_firmware_version").state == "042.0"
    assert hass.states.get(f"sensor.{prefix}_car_status").state == "ready"
    assert hass.states.get(f"sensor.{prefix}_stored_charging_current").state == "16"
    select = hass.states.get(f"select.{prefix}_max_current")
    assert select.state == "10"
    assert hass.states.get(f"sensor.{prefix}_reported_max_current").state == "10"
    assert select.attributes["options"] == [str(a) for a in range(6, 33)]  # ama = 32
    assert hass.states.get(f"sensor.{prefix}_total_energy").state == "1983.0"
    assert hass.states.get(f"sensor.{prefix}_temperature_1").state == "24.75"
    assert hass.states.get(f"sensor.{prefix}_temperature_6").state == "27.63"
    assert hass.states.get(f"sensor.{prefix}_phases_available").state == "3"
    assert hass.states.get(f"sensor.{prefix}_voltage_l1").state == "224.0"
    assert hass.states.get(f"sensor.{prefix}_power").state == "0.0"
    assert hass.states.get(f"switch.{prefix}_allow_charging").state == STATE_ON
    for state in hass.states.async_all():
        assert state.state != STATE_UNAVAILABLE, state.entity_id


async def test_firmware_without_amx_in_status(
    hass: HomeAssistant, charger: FakeCharger, mock_entry: MockConfigEntry
) -> None:
    """Without amx in the status the select shows the last value it set."""
    charger.report_amx = False
    charger.status.pop("amx")
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    select = hass.states.get(SELECT)
    assert select.state == STATE_UNKNOWN
    assert select.attributes["reported_by_charger"] is False
    await _select(hass, "10")
    assert hass.states.get(SELECT).state == "10"


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant, charger: FakeCharger, mock_entry: MockConfigEntry
) -> None:
    """With no status ever received the entry goes into setup retry."""
    charger.offline = True
    mock_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_connection_loss_keeps_values(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities keep their last values while the charger is unreachable."""
    charger.offline = True
    await _poll(hass, freezer)

    connection = hass.states.get(CONNECTION)
    assert connection.state == STATE_OFF
    assert connection.attributes["consecutive_failures"] == 1
    assert connection.attributes["last_error"]

    # Old values survive and nothing became unavailable.
    assert hass.states.get(CAR_STATUS).state == "charging"
    assert hass.states.get(POWER).state == "6900.0"
    assert hass.states.get(SWITCH).state == STATE_ON
    for state in hass.states.async_all():
        assert state.state != STATE_UNAVAILABLE, state.entity_id

    # Still offline on the next poll.
    await _poll(hass, freezer)
    assert hass.states.get(CONNECTION).attributes["consecutive_failures"] == 2

    # Recovery with a changed status.
    charger.offline = False
    charger.status["car"] = "4"
    await _poll(hass, freezer)
    assert hass.states.get(CONNECTION).state == STATE_ON
    assert hass.states.get(CONNECTION).attributes["consecutive_failures"] == 0
    assert hass.states.get(CAR_STATUS).state == "charge_finished"


async def test_transient_failure_is_retried_within_poll(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Two failed attempts followed by success never show as disconnected."""
    charger.fail_next = 2
    charger.status["car"] = "3"
    await _poll(hass, freezer)
    assert hass.states.get(CONNECTION).state == STATE_ON
    assert hass.states.get(CAR_STATUS).state == "waiting_for_vehicle"


async def test_allow_charging_switch(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """The switch sends alw=0 / alw=1 and applies the returned status."""
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert charger.commands() == ["alw=0"]
    assert hass.states.get(SWITCH).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert charger.commands() == ["alw=0", "alw=1"]
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_switch_error_when_offline(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """Commands to an unreachable charger raise and flip the connection sensor."""
    charger.offline = True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH}, blocking=True
        )
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(CONNECTION).state == STATE_OFF


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: SELECT, ATTR_OPTION: option},
        blocking=True,
    )


async def test_set_max_current_confirmed_by_later_status(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A single amx write; the delayed confirmation clears the pending state."""
    await _select(hass, "10")
    assert charger.commands() == ["amx=10"]
    assert charger.effective_amp == 10
    select = hass.states.get(SELECT)
    assert select.state == "10"  # requested value shown while pending
    assert select.attributes["pending_value"] == 10
    assert hass.states.get(f"sensor.{PREFIX}_reported_max_current").state == "16"
    # amp (flash) is untouched by amx.
    assert hass.states.get(f"sensor.{PREFIX}_stored_charging_current").state == "16"

    await _poll(hass, freezer)  # charger now reports amx=10
    select = hass.states.get(SELECT)
    assert select.state == "10"
    assert select.attributes["pending_value"] is None
    assert select.attributes["workaround_applied"] is False
    assert hass.states.get(f"sensor.{PREFIX}_reported_max_current").state == "10"

    # Wait well past the timeout: still no workaround.
    await _poll(hass, freezer, seconds=60)
    assert charger.commands() == ["amx=10"]


async def test_workaround_after_30s_without_effect(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The amp=6/amp=16 cycle only runs once amx had no effect for 30 s."""
    charger.amx_bug = True  # freshly rebooted charger: amx clamped to 6 A
    await _select(hass, "10")
    assert charger.commands() == ["amx=10"]

    # 6 s and 12 s later the charger reports amx=6: too early to intervene.
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert charger.commands() == ["amx=10"]
    assert hass.states.get(SELECT).state == "10"
    assert hass.states.get(f"sensor.{PREFIX}_reported_max_current").state == "6"

    # Past 30 s without effect: workaround runs and amx is resent.
    await _poll(hass, freezer, seconds=20)
    assert charger.commands() == ["amx=10", "amp=6", "amp=16", "amx=10"]
    assert charger.effective_amp == 10
    assert hass.states.get(SELECT).attributes["workaround_applied"] is True
    assert hass.states.get(f"sensor.{PREFIX}_stored_charging_current").state == "16"

    # The next status confirms it.
    await _poll(hass, freezer)
    select = hass.states.get(SELECT)
    assert select.state == "10"
    assert select.attributes["pending_value"] is None
    assert select.attributes["last_error"] is None
    assert hass.states.get(f"sensor.{PREFIX}_reported_max_current").state == "10"


async def test_workaround_gives_up_after_second_timeout(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """If the workaround has no effect either, an error is logged once."""
    charger.amx_bug = True
    original_apply = charger.apply

    def sticky_bug(key: str, value: str) -> None:
        original_apply(key, value)
        charger.amx_bug = True

    charger.apply = sticky_bug  # type: ignore[method-assign]

    await _select(hass, "10")
    await _poll(hass, freezer, seconds=31)  # workaround
    assert charger.commands() == ["amx=10", "amp=6", "amp=16", "amx=10"]
    await _poll(hass, freezer, seconds=31)  # give up
    select = hass.states.get(SELECT)
    assert select.state == "6"  # what the charger really uses
    assert select.attributes["pending_value"] is None
    assert "even after the amp workaround" in select.attributes["last_error"]

    # No further attempts.
    await _poll(hass, freezer, seconds=60)
    assert charger.commands() == ["amx=10", "amp=6", "amp=16", "amx=10"]


async def test_new_request_replaces_pending_one(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Changing the value again while pending restarts the wait."""
    charger.amx_bug = True
    await _select(hass, "10")
    await _poll(hass, freezer, seconds=20)
    await _select(hass, "12")
    await _poll(hass, freezer, seconds=20)  # 40 s after first, 20 s after second
    assert charger.commands() == ["amx=10", "amx=12"]
    assert hass.states.get(SELECT).state == "12"


async def test_reboot_falls_back_to_flash_value(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After a reboot the charger reports amx=amp again and nothing is sent."""
    await _select(hass, "10")
    await _poll(hass, freezer)
    assert hass.states.get(SELECT).state == "10"

    charger.reboot()
    charger.requests.clear()
    await _poll(hass, freezer)
    assert hass.states.get(SELECT).state == "16"
    assert hass.states.get(f"sensor.{PREFIX}_reboot_counter").state == "252"
    assert charger.commands() == []


async def test_reboot_button(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The reboot button sends rst=1 and tolerates the dropped connection."""
    await _select(hass, "10")
    assert hass.states.get(SELECT).attributes["pending_value"] == 10

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.{PREFIX}_reboot"},
        blocking=True,
    )
    # aiohttp may transparently retry the GET once when the pooled connection
    # is dropped, so allow more than one rst=1 but nothing else.
    assert "rst=1" in charger.commands()
    assert [c for c in charger.commands() if c != "rst=1"] == ["amx=10"]
    # Pending amx write dropped, no workaround attempted later.
    assert hass.states.get(SELECT).attributes["pending_value"] is None

    await _poll(hass, freezer)
    assert hass.states.get(f"sensor.{PREFIX}_reboot_counter").state != "251"
    assert hass.states.get(SELECT).state == "16"
    await _poll(hass, freezer, seconds=60)
    assert [c for c in charger.commands() if c != "rst=1"] == ["amx=10"]


async def test_auto_reboot_on_no_ground_once(
    hass: HomeAssistant,
    charger: FakeCharger,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No ground triggers one reboot; re-armed only after a No error status."""
    button = f"button.{PREFIX}_reboot"
    assert hass.states.get(button).attributes["auto_reboot_armed"] is True
    charger.reboot_mode = "reply"  # no dropped connection, so no aiohttp retry

    charger.status["err"] = "8"
    await _poll(hass, freezer)
    assert charger.reboot_calls == 1
    assert hass.states.get(f"sensor.{PREFIX}_error").state == "no_ground"
    attrs = hass.states.get(button).attributes
    assert attrs["auto_reboot_armed"] is False
    assert attrs["last_auto_reboot"] is not None

    # Error persists after the reboot: no further reboots.
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert charger.reboot_calls == 1

    # A different error does not re-arm either.
    charger.status["err"] = "1"
    await _poll(hass, freezer)
    charger.status["err"] = "8"
    await _poll(hass, freezer)
    assert charger.reboot_calls == 1

    # No error seen -> re-armed -> next No ground reboots again.
    charger.status["err"] = "0"
    await _poll(hass, freezer)
    assert hass.states.get(button).attributes["auto_reboot_armed"] is True
    charger.status["err"] = "8"
    await _poll(hass, freezer)
    assert charger.reboot_calls == 2


async def test_auto_reboot_disabled(
    hass: HomeAssistant, charger: FakeCharger, freezer: FrozenDateTimeFactory
) -> None:
    """With the option off the error is only logged."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={
            CONF_HOST: charger.host,
            CONF_SCAN_INTERVAL: 5,
            "auto_reboot_no_ground": False,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    charger.status["err"] = "8"
    await _poll(hass, freezer)
    assert charger.reboot_calls == 0
    assert hass.states.get(f"button.{PREFIX}_reboot").attributes["auto_reboot_on_no_ground"] is False


async def test_reboot_button_http_error(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """An HTTP error reply to rst=1 is reported to the user."""
    charger.reboot_mode = "error"
    with pytest.raises(HomeAssistantError, match="rejected the reboot"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: f"button.{PREFIX}_reboot"},
            blocking=True,
        )


async def test_unload_entry(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """The entry unloads cleanly."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(CAR_STATUS).state == STATE_UNAVAILABLE
