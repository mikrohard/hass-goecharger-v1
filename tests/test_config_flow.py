"""Tests for the config, reconfigure and options flows."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.goecharger_v1.const import DOMAIN

from .conftest import SERIAL, FakeCharger


async def test_user_flow_creates_entry(hass: HomeAssistant, charger: FakeCharger) -> None:
    """Happy path: host + interval are stored, serial becomes the unique id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: f"http://{charger.host}/", CONF_SCAN_INTERVAL: 7},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"go-eCharger {SERIAL}"
    assert result["data"] == {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 7}
    assert result["result"].unique_id == SERIAL


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """An unreachable host shows an error and keeps the form open."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1:1", CONF_SCAN_INTERVAL: 10}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """The same charger cannot be added twice."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 10}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_flow(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """Reconfigure updates the entry data and reloads."""
    result = await setup_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_entry.data[CONF_SCAN_INTERVAL] == 30
    assert setup_entry.runtime_data.update_interval.total_seconds() == 30


async def test_reconfigure_wrong_device(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """Pointing the entry at a different charger is rejected."""
    charger.status["sse"] = "999999"
    result = await setup_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 10}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_device"}


async def test_options_flow(
    hass: HomeAssistant, charger: FakeCharger, setup_entry: MockConfigEntry
) -> None:
    """The options flow edits the same data and reloads the entry."""
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.data == {CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 15}
    assert setup_entry.state is config_entries.ConfigEntryState.LOADED
    assert setup_entry.runtime_data.update_interval.total_seconds() == 15
