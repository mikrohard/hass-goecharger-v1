"""Base entity for the go-eCharger (API v1) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import GoeChargerCoordinator
from .util import get_str


class GoeChargerEntity(CoordinatorEntity[GoeChargerCoordinator]):
    """Common base for all go-eCharger entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoeChargerCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        serial = coordinator.serial
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"go-eCharger {serial}",
            sw_version=get_str(coordinator.data, "fwv"),
            serial_number=serial,
            configuration_url=coordinator.api.base_url,
        )

    @property
    def available(self) -> bool:
        """Stay available as long as any status has ever been received.

        Connection problems are reported through the connectivity binary
        sensor instead of making every entity unavailable.
        """
        return self.coordinator.data is not None
