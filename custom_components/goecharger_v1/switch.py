"""Switch entities for the go-eCharger (API v1) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator
from .entity import GoeChargerEntity
from .util import get_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoeChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    async_add_entities([GoeChargerAllowChargingSwitch(entry.runtime_data)])


class GoeChargerAllowChargingSwitch(GoeChargerEntity, SwitchEntity):
    """Allow / disallow charging (alw)."""

    _attr_translation_key = "allow_charging"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: GoeChargerCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, "alw")

    @property
    def is_on(self) -> bool | None:
        """Return True when charging is allowed."""
        alw = get_int(self.coordinator.data, "alw")
        return None if alw is None else alw == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow charging."""
        await self.coordinator.async_set_allow_charging(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forbid charging."""
        await self.coordinator.async_set_allow_charging(False)
