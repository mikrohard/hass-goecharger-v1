"""Sensor entities for the go-eCharger (API v1) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GoeChargerConfigEntry, GoeChargerCoordinator
from .entity import GoeChargerEntity
from .util import StatusData, get_array, get_float, get_int, get_nrg, get_str

CAR_STATES = {
    1: "ready",
    2: "charging",
    3: "waiting_for_vehicle",
    4: "charge_finished",
}
ERROR_STATES = {
    0: "none",
    1: "rccb",
    3: "phase",
    8: "no_ground",
    10: "internal",
}
ACCESS_STATES = {
    0: "open",
    1: "rfid_app",
    2: "electricity_price",
}
STOP_STATES = {
    0: "deactivated",
    2: "kwh_limit",
}
UNLOCK_STATES = {
    0: "locked_while_connected",
    1: "unlock_after_charging",
    2: "always_locked",
}


def _enum(key: str, mapping: dict[int, str], default: str | None = None):
    """Build a value function translating an integer code into an enum option."""

    def value_fn(data: StatusData) -> str | None:
        code = get_int(data, key)
        if code is None:
            return None
        return mapping.get(code, default)

    return value_fn


def _phase_bits(data: StatusData, shift: int) -> tuple[bool, bool, bool] | None:
    """Return (L1, L2, L3) flags from the pha bit field at the given offset."""
    pha = get_int(data, "pha")
    if pha is None:
        return None
    bits = pha >> shift
    return bool(bits & 0b001), bool(bits & 0b010), bool(bits & 0b100)


def _phase_count(shift: int):
    def value_fn(data: StatusData) -> int | None:
        flags = _phase_bits(data, shift)
        return None if flags is None else sum(flags)

    return value_fn


def _phase_attributes(shift: int):
    def attributes_fn(data: StatusData) -> dict[str, Any]:
        flags = _phase_bits(data, shift)
        if flags is None:
            return {}
        return {"l1": flags[0], "l2": flags[1], "l3": flags[2], "raw": data.get("pha")}

    return attributes_fn


@dataclass(frozen=True, kw_only=True)
class GoeChargerSensorDescription(SensorEntityDescription):
    """Describe a go-eCharger sensor."""

    value_fn: Callable[[StatusData], StateType]
    # Status key that must be present for the entity to be created. Defaults
    # to `key`; the nrg based sensors all depend on the "nrg" array.
    source_key: str | None = None
    attributes_fn: Callable[[StatusData], dict[str, Any]] | None = None


SENSORS: tuple[GoeChargerSensorDescription, ...] = (
    GoeChargerSensorDescription(
        key="car",
        translation_key="car_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(CAR_STATES.values()),
        value_fn=_enum("car", CAR_STATES),
    ),
    GoeChargerSensorDescription(
        key="amp",
        translation_key="charging_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_int(data, "amp"),
    ),
    GoeChargerSensorDescription(
        key="amx",
        translation_key="reported_max_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_int(data, "amx"),
    ),
    GoeChargerSensorDescription(
        key="err",
        translation_key="error",
        device_class=SensorDeviceClass.ENUM,
        options=list(ERROR_STATES.values()),
        value_fn=_enum("err", ERROR_STATES, default="internal"),
    ),
    GoeChargerSensorDescription(
        key="ast",
        translation_key="access_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(ACCESS_STATES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_enum("ast", ACCESS_STATES),
    ),
    GoeChargerSensorDescription(
        key="stp",
        translation_key="stop_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(STOP_STATES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_enum("stp", STOP_STATES),
    ),
    GoeChargerSensorDescription(
        key="ust",
        translation_key="unlock_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(UNLOCK_STATES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_enum("ust", UNLOCK_STATES),
    ),
    GoeChargerSensorDescription(
        key="cbl",
        translation_key="cable_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_int(data, "cbl"),
    ),
    GoeChargerSensorDescription(
        key="ama",
        translation_key="absolute_max_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_int(data, "ama"),
    ),
    GoeChargerSensorDescription(
        key="phases_available",
        source_key="pha",
        translation_key="phases_available",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_phase_count(3),
        attributes_fn=_phase_attributes(3),
    ),
    GoeChargerSensorDescription(
        key="phases_active",
        source_key="pha",
        translation_key="phases_active",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_phase_count(0),
        attributes_fn=_phase_attributes(0),
    ),
    GoeChargerSensorDescription(
        key="tmp",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        # Firmware 042.0 reports a bogus value here (6 while the tma array
        # shows ~25 °C), so the tma sensors are the ones enabled by default.
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_int(data, "tmp"),
    ),
    GoeChargerSensorDescription(
        key="dws",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        # deca-watt-seconds -> kWh: x * 10 Ws / 3'600'000
        value_fn=lambda data: get_float(data, "dws", 1 / 360000),
    ),
    GoeChargerSensorDescription(
        key="eto",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: get_float(data, "eto", 0.1),
    ),
    GoeChargerSensorDescription(
        key="dwo",
        translation_key="energy_limit",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda data: get_float(data, "dwo", 0.1),
    ),
    GoeChargerSensorDescription(
        key="uby",
        translation_key="unlocked_by",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_int(data, "uby"),
    ),
    *(
        GoeChargerSensorDescription(
            key=f"temperature_{index + 1}",
            source_key="tma",
            translation_key=f"temperature_{index + 1}",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            value_fn=lambda data, index=index: get_array(data, "tma", index),
        )
        for index in range(6)
    ),
    # nrg[] sensor array
    GoeChargerSensorDescription(
        key="voltage_l1",
        source_key="nrg",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 0),
    ),
    GoeChargerSensorDescription(
        key="voltage_l2",
        source_key="nrg",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 1),
    ),
    GoeChargerSensorDescription(
        key="voltage_l3",
        source_key="nrg",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 2),
    ),
    GoeChargerSensorDescription(
        key="voltage_n",
        source_key="nrg",
        translation_key="voltage_n",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_nrg(data, 3),
    ),
    GoeChargerSensorDescription(
        key="current_l1",
        source_key="nrg",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: get_nrg(data, 4, 0.1),
    ),
    GoeChargerSensorDescription(
        key="current_l2",
        source_key="nrg",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: get_nrg(data, 5, 0.1),
    ),
    GoeChargerSensorDescription(
        key="current_l3",
        source_key="nrg",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: get_nrg(data, 6, 0.1),
    ),
    GoeChargerSensorDescription(
        key="power_l1",
        source_key="nrg",
        translation_key="power_l1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 7, 100),
    ),
    GoeChargerSensorDescription(
        key="power_l2",
        source_key="nrg",
        translation_key="power_l2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 8, 100),
    ),
    GoeChargerSensorDescription(
        key="power_l3",
        source_key="nrg",
        translation_key="power_l3",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 9, 100),
    ),
    GoeChargerSensorDescription(
        key="power_n",
        source_key="nrg",
        translation_key="power_n",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_nrg(data, 10, 100),
    ),
    GoeChargerSensorDescription(
        key="power_total",
        source_key="nrg",
        translation_key="power_total",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: get_nrg(data, 11, 10),
    ),
    GoeChargerSensorDescription(
        key="power_factor_l1",
        source_key="nrg",
        translation_key="power_factor_l1",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_nrg(data, 12),
    ),
    GoeChargerSensorDescription(
        key="power_factor_l2",
        source_key="nrg",
        translation_key="power_factor_l2",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_nrg(data, 13),
    ),
    GoeChargerSensorDescription(
        key="power_factor_l3",
        source_key="nrg",
        translation_key="power_factor_l3",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_nrg(data, 14),
    ),
    # Diagnostics
    GoeChargerSensorDescription(
        key="fwv",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_str(data, "fwv"),
    ),
    GoeChargerSensorDescription(
        key="rbc",
        translation_key="reboot_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_int(data, "rbc"),
    ),
    GoeChargerSensorDescription(
        key="rbt",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: get_float(data, "rbt", 0.001),
    ),
    GoeChargerSensorDescription(
        key="loa",
        translation_key="load_balancing_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: get_int(data, "loa"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoeChargerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors that the charger's status object supports."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    async_add_entities(
        GoeChargerSensor(coordinator, description)
        for description in SENSORS
        if (description.source_key or description.key) in data
        and description.value_fn(data) is not None
    )


class GoeChargerSensor(GoeChargerEntity, SensorEntity):
    """A sensor backed by a value in the status object."""

    entity_description: GoeChargerSensorDescription

    def __init__(
        self,
        coordinator: GoeChargerCoordinator,
        description: GoeChargerSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the sensor value from the last known status."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes, if the description defines any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
