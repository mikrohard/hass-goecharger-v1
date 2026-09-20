"""Select entities for the go-eCharger (API v1) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_CURRENT, MIN_CURRENT
from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator
from .entity import GoeChargerEntity
from .util import get_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoeChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select entities."""
    async_add_entities([GoeChargerMaxCurrentSelect(entry.runtime_data)])


class GoeChargerMaxCurrentSelect(GoeChargerEntity, SelectEntity):
    """Max charging current for dynamic charging, written through amx.

    amx is memory only on the charger, so it can be changed as often as
    needed (PV surplus charging) without wearing out the flash. The charger
    does not mirror amx into `amp`, so the shown value is the last value
    this integration set (or `amx` from the status object when the firmware
    reports it). After a charger reboot the effective value falls back to
    the flash value `amp`.
    """

    _attr_translation_key = "max_current"

    def __init__(self, coordinator: GoeChargerCoordinator) -> None:
        """Initialise the select entity."""
        super().__init__(coordinator, "amx")

    @property
    def options(self) -> list[str]:
        """Whole amperes from 6 A up to the charger's absolute maximum (ama)."""
        ama = get_int(self.coordinator.data, "ama")
        upper = ama if ama is not None and MIN_CURRENT <= ama <= MAX_CURRENT else MAX_CURRENT
        return [str(amps) for amps in range(MIN_CURRENT, upper + 1)]

    @property
    def current_option(self) -> str | None:
        """Return the effective max current, if known."""
        current = self.coordinator.effective_max_current
        if current is None:
            return None
        option = str(current)
        return option if option in self.options else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose details useful for troubleshooting."""
        coordinator = self.coordinator
        return {
            "flash_current": get_int(coordinator.data, "amp"),
            "reported_by_charger": "amx" in (coordinator.data or {}),
            "pending_value": coordinator.pending_max_current,
            "pending_since": coordinator.pending_since,
            "workaround_applied": coordinator.amx_workaround_applied,
            "last_error": coordinator.amx_last_error,
        }

    async def async_select_option(self, option: str) -> None:
        """Set the max current via amx."""
        await self.coordinator.async_set_max_current(int(option))
