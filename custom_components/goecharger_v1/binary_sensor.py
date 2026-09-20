"""Binary sensor entities for the go-eCharger (API v1) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator
from .entity import GoeChargerEntity
from .util import StatusData, get_int


@dataclass(frozen=True, kw_only=True)
class GoeChargerBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a go-eCharger binary sensor."""

    is_on_fn: Callable[[StatusData], bool | None]
    source_key: str | None = None


def _car_is(*codes: int) -> Callable[[StatusData], bool | None]:
    def is_on_fn(data: StatusData) -> bool | None:
        car = get_int(data, "car")
        return None if car is None else car in codes

    return is_on_fn


BINARY_SENSORS: tuple[GoeChargerBinarySensorDescription, ...] = (
    GoeChargerBinarySensorDescription(
        key="vehicle_connected",
        source_key="car",
        translation_key="vehicle_connected",
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=_car_is(2, 3, 4),
    ),
    GoeChargerBinarySensorDescription(
        key="charging",
        source_key="car",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=_car_is(2),
    ),
    GoeChargerBinarySensorDescription(
        key="alw",
        translation_key="charging_allowed",
        entity_registry_enabled_default=False,
        is_on_fn=lambda data: (v := get_int(data, "alw")) is not None and v == 1,
    ),
    GoeChargerBinarySensorDescription(
        key="adi",
        translation_key="adapter_in",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda data: (v := get_int(data, "adi")) is not None and v == 1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoeChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    entities: list[BinarySensorEntity] = [GoeChargerConnectionSensor(coordinator)]
    entities.extend(
        GoeChargerBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if (description.source_key or description.key) in data
    )
    async_add_entities(entities)


class GoeChargerBinarySensor(GoeChargerEntity, BinarySensorEntity):
    """A binary sensor backed by the status object."""

    entity_description: GoeChargerBinarySensorDescription

    def __init__(
        self,
        coordinator: GoeChargerCoordinator,
        description: GoeChargerBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state from the last known status."""
        return self.entity_description.is_on_fn(self.coordinator.data)


class GoeChargerConnectionSensor(GoeChargerEntity, BinarySensorEntity):
    """Whether Home Assistant can currently talk to the charger.

    This is the only entity that reflects connection problems; all other
    entities keep their last known values while the charger is unreachable.
    """

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GoeChargerCoordinator) -> None:
        """Initialise the connectivity sensor."""
        super().__init__(coordinator, "connection")

    @property
    def available(self) -> bool:
        """This sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the last request to the charger succeeded."""
        return self.coordinator.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose details useful for troubleshooting flaky Wi-Fi."""
        return {
            "host": self.coordinator.api.host,
            "last_success": self.coordinator.last_success,
            "consecutive_failures": self.coordinator.consecutive_failures,
            "last_error": self.coordinator.last_error,
        }
