"""The go-eCharger (API v1) integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GoeChargerApi
from .const import (
    CONF_AUTO_REBOOT_NO_GROUND,
    DEFAULT_AUTO_REBOOT_NO_GROUND,
    DEFAULT_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: GoeChargerConfigEntry) -> bool:
    """Set up go-eCharger from a config entry."""
    api = GoeChargerApi(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = GoeChargerCoordinator(
        hass,
        entry,
        api,
        int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        auto_reboot_no_ground=bool(
            entry.data.get(CONF_AUTO_REBOOT_NO_GROUND, DEFAULT_AUTO_REBOOT_NO_GROUND)
        ),
    )
    # Raises ConfigEntryNotReady if the charger cannot be reached at all,
    # which makes Home Assistant retry the setup in the background.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoeChargerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
