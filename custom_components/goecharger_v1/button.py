"""Button entities for the go-eCharger (API v1) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator
from .entity import GoeChargerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoeChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_entities([GoeChargerRebootButton(entry.runtime_data)])


class GoeChargerRebootButton(GoeChargerEntity, ButtonEntity):
    """Reboot the charger using the undocumented `rst=1` command."""

    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GoeChargerCoordinator) -> None:
        """Initialise the button."""
        super().__init__(coordinator, "reboot")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the state of the automatic "No ground" reboot rule."""
        return {
            "auto_reboot_on_no_ground": self.coordinator.auto_reboot_no_ground,
            "auto_reboot_armed": self.coordinator.auto_reboot_armed,
            "last_auto_reboot": self.coordinator.last_auto_reboot,
        }

    async def async_press(self) -> None:
        """Reboot the charger."""
        await self.coordinator.async_reboot()
