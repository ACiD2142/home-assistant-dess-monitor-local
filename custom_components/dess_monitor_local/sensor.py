"""Sensor platform for DESS Monitor Local."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from time import monotonic
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LocalConfigEntry
from .const import DOMAIN
from .coordinator import LocalCoordinator, LocalInverterHub
from .protocols.enums import (
    ACInputVoltageRange,
    BatteryType,
    ChargerSourcePriority,
    OperatingMode,
    OutputSourcePriority,
    ParallelMode,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SensorDef:
    """One entity, described declaratively."""

    section: str
    key: str
    name: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    category: EntityCategory | None = None
    precision: int | None = None
    enum_class: type[Enum] | None = None
    compute: Callable[[dict[str, Any]], Any] | None = None


def _pv2_power(data: dict[str, Any]) -> Any:
    try:
        pv2 = data["qpigs2"]
        return float(pv2["pv_current"]) * float(pv2["pv_voltage"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Live data (QPIGS / QPIGS2)
# ---------------------------------------------------------------------------
QPIGS_SENSORS: tuple[SensorDef, ...] = (
    SensorDef("qpigs", "grid_voltage", "Grid Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs", "grid_frequency", "Grid Frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    SensorDef("qpigs", "ac_output_voltage", "AC Output Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs", "ac_output_frequency", "AC Output Frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    SensorDef("qpigs", "output_apparent_power", "Output Apparent Power", UnitOfApparentPower.VOLT_AMPERE, SensorDeviceClass.APPARENT_POWER),
    SensorDef("qpigs", "output_active_power", "Output Active Power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    SensorDef("qpigs", "load_percent", "Load", PERCENTAGE, precision=0),
    SensorDef("qpigs", "bus_voltage", "Bus Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs", "battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs", "battery_charging_current", "Battery Charging Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    SensorDef("qpigs", "battery_discharge_current", "Battery Discharge Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    SensorDef("qpigs", "battery_capacity", "Battery Capacity", PERCENTAGE, SensorDeviceClass.BATTERY),
    SensorDef("qpigs", "inverter_heat_sink_temperature", "Inverter Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpigs", "inverter_dcdc_module_temperature", "DC/DC Module Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpigs", "pv_input_voltage", "PV Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs", "pv_input_current", "PV Input Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    SensorDef("qpigs", "pv_charging_power", "PV Power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    SensorDef("qpigs", "scc_battery_voltage", "SCC Battery Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpigs", "grid_ac_in_power", "Grid Input Power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    SensorDef("qpigs2", "pv_voltage", "PV2 Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    SensorDef("qpigs2", "pv_current", "PV2 Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    SensorDef("qpigs2", "pv_daily_energy", "PV Daily Energy", UnitOfEnergy.WATT_HOUR, SensorDeviceClass.ENERGY),
    SensorDef("", "", "PV2 Power", UnitOfPower.WATT, SensorDeviceClass.POWER, compute=_pv2_power),
)

# ---------------------------------------------------------------------------
# Ratings / settings (QPIRI) — mostly diagnostic
# ---------------------------------------------------------------------------
QPIRI_SENSORS: tuple[SensorDef, ...] = (
    SensorDef("qpiri", "rated_grid_voltage", "Rated Grid Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "rated_ac_output_voltage", "Rated AC Output Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "rated_output_frequency", "Rated Output Frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "rated_output_apparent_power", "Rated Output Apparent Power", UnitOfApparentPower.VOLT_AMPERE, SensorDeviceClass.APPARENT_POWER, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "rated_battery_voltage", "Rated Battery Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "low_battery_to_ac_bypass_voltage", "Low Battery → AC Bypass Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "shut_down_battery_voltage", "Battery Shut-down Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "bulk_charging_voltage", "Bulk Charging Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "float_charging_voltage", "Float Charging Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "high_battery_voltage_to_battery_mode", "Battery Mode Return Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "max_charging_current", "Max Charging Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "max_utility_charging_current", "Max Utility Charging Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "battery_type", "Battery Type", enum_class=BatteryType, category=EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "ac_input_voltage_range", "AC Input Voltage Range", enum_class=ACInputVoltageRange, category=EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "output_source_priority", "Output Source Priority", enum_class=OutputSourcePriority, category=EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "charger_source_priority", "Charger Source Priority", enum_class=ChargerSourcePriority, category=EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "parallel_mode", "Parallel Mode", enum_class=ParallelMode, category=EntityCategory.DIAGNOSTIC),
    SensorDef("qpiri", "rated_battery_capacity", "Rated Battery Capacity", "Ah", category=EntityCategory.DIAGNOSTIC),
)

# ---------------------------------------------------------------------------
# Operating mode (QMOD)
# ---------------------------------------------------------------------------
QMOD_SENSORS: tuple[SensorDef, ...] = (
    SensorDef("qmod", "operating_mode", "Operating Mode", enum_class=OperatingMode),
)

ALL_SENSOR_DEFS = QPIGS_SENSORS + QPIRI_SENSORS + QMOD_SENSORS


class LocalSensor(CoordinatorEntity[LocalCoordinator], SensorEntity):
    """A sensor backed by one decoded protocol field."""

    def __init__(
        self,
        hub: LocalInverterHub,
        coordinator: LocalCoordinator,
        definition: SensorDef,
    ) -> None:
        super().__init__(coordinator)
        self._hub = hub
        self._def = definition
        suffix = definition.compute.__name__ if definition.compute else definition.key
        self._attr_unique_id = f"{DOMAIN}_{hub.device_id}_{definition.section or 'derived'}_{suffix}"
        self._attr_name = f"{hub.name} {definition.name}"
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_class = definition.device_class
        self._attr_entity_category = definition.category
        if definition.precision is not None:
            self._attr_suggested_display_precision = definition.precision

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._hub.device_id)},
            name=self._hub.name,
            manufacturer=self._hub.manufacturer,
            model=self._hub.protocol or "auto-detect pending",
            configuration_url=f"http://{self._hub.host}",
        )

    @property
    def available(self) -> bool:
        # Follow the coordinator only. A single failed command (e.g. an
        # unsupported QPIGS2) blanks its own fields but must not take every
        # other sensor offline — the error is visible on the diagnostic entity.
        return super().available

    @property
    def options(self) -> list[str] | None:
        if self._def.enum_class is None:
            return None
        return [member.name for member in self._def.enum_class]

    @callback
    def _handle_coordinator_update(self) -> None:
        data = (self.coordinator.data or {}).get(self._hub.device_id, {})
        defn = self._def

        if defn.compute is not None:
            raw = defn.compute(data)
        else:
            raw = data.get(defn.section, {}).get(defn.key)

        if raw is None:
            self._attr_native_value = None
        elif defn.enum_class is not None:
            self._attr_native_value = raw if raw in (self.options or []) else None
        else:
            try:
                self._attr_native_value = float(raw)
            except (TypeError, ValueError):
                self._attr_native_value = None
        self.async_write_ha_state()


class LocalDiagnosticSensor(CoordinatorEntity[LocalCoordinator], SensorEntity):
    """Connection-level diagnostic sensors (protocol, port, last contact)."""

    def __init__(self, hub: LocalInverterHub, coordinator: LocalCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._hub = hub
        self._key = key
        names = {
            "protocol": "Detected Protocol",
            "port": "Device Port",
            "last_success": "Last Successful Poll",
            "last_error": "Last Poll Error",
        }
        self._attr_name = f"{hub.name} {names[key]}"
        self._attr_unique_id = f"{DOMAIN}_{hub.device_id}_diagnostic_{key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key == "last_success":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if key == "port":
            self._attr_suggested_display_precision = 0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._hub.device_id)},
            name=self._hub.name,
            manufacturer=self._hub.manufacturer,
            model=self._hub.protocol or "auto-detect pending",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._key == "protocol":
            self._attr_native_value = (
                f"{self._hub.protocol} / {self._hub.framing}" if self._hub.detected else None
            )
        elif self._key == "port":
            self._attr_native_value = self._hub.port
        elif self._key == "last_error":
            self._attr_native_value = self._hub.last_error
        elif self._key == "last_success":
            last = self._hub.last_success_at
            if last is None:
                self._attr_native_value = None
            else:
                self._attr_native_value = datetime.now(timezone.utc) - timedelta(
                    seconds=monotonic() - last
                )
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LocalConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up local sensors from a config entry."""
    hub = entry.runtime_data.hub
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        LocalSensor(hub, coordinator, defn) for defn in ALL_SENSOR_DEFS
    ]
    entities.extend(
        LocalDiagnosticSensor(hub, coordinator, key)
        for key in ("protocol", "port", "last_success", "last_error")
    )
    async_add_entities(entities)
