"""Sensor platform for Ecovacs Legacy: battery, consumables, error, totals."""

from __future__ import annotations

from deebot_client.events import BatteryEvent, ErrorEvent, LifeSpan, LifeSpanEvent, TotalStatsEvent

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcovacsLegacyConfigEntry
from .entity import EcovacsLegacyEntity

_LIFE_SPAN_KEYS = {
    LifeSpan.BRUSH: "lifespan_brush",
    LifeSpan.SIDE_BRUSH: "lifespan_side_brush",
    LifeSpan.DUST_CASE_HEAP: "lifespan_filter",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcovacsLegacyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors."""
    entities: list[SensorEntity] = []
    for device in entry.runtime_data.devices:
        entities.append(BatterySensor(device))
        entities.append(ErrorSensor(device))
        entities.extend(LifeSpanSensor(device, ls) for ls in device.capabilities.life_span.types)
        entities.extend(TotalStatsSensor(device, field) for field in ("area", "time", "cleanings"))
    async_add_entities(entities)


class BatterySensor(EcovacsLegacyEntity, SensorEntity):
    """Battery level."""

    def __init__(self, device) -> None:
        """Initialize."""
        super().__init__(
            device,
            SensorEntityDescription(
                key="battery",
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe."""
        await super().async_added_to_hass()

        async def on_event(event: BatteryEvent) -> None:
            self._attr_native_value = event.value
            self.async_write_ha_state()

        self._subscribe(BatteryEvent, on_event)


class LifeSpanSensor(EcovacsLegacyEntity, SensorEntity):
    """Remaining life of a consumable (%)."""

    def __init__(self, device, life_span: LifeSpan) -> None:
        """Initialize."""
        key = _LIFE_SPAN_KEYS.get(life_span, f"lifespan_{life_span.name.lower()}")
        super().__init__(
            device,
            SensorEntityDescription(
                key=key,
                translation_key=key,
                native_unit_of_measurement=PERCENTAGE,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )
        self._life_span = life_span

    async def async_added_to_hass(self) -> None:
        """Subscribe."""
        await super().async_added_to_hass()

        async def on_event(event: LifeSpanEvent) -> None:
            if event.type == self._life_span:
                self._attr_native_value = event.percent
                self.async_write_ha_state()

        self._subscribe(LifeSpanEvent, on_event)


class ErrorSensor(EcovacsLegacyEntity, SensorEntity):
    """Last error code reported by the robot (0 = none)."""

    def __init__(self, device) -> None:
        """Initialize."""
        super().__init__(
            device,
            SensorEntityDescription(
                key="error", translation_key="error", entity_category=EntityCategory.DIAGNOSTIC
            ),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe."""
        await super().async_added_to_hass()

        async def on_event(event: ErrorEvent) -> None:
            self._attr_native_value = event.code
            self._attr_extra_state_attributes = {"description": event.description}
            self.async_write_ha_state()

        self._subscribe(ErrorEvent, on_event)


class TotalStatsSensor(EcovacsLegacyEntity, SensorEntity):
    """Lifetime totals (disabled by default: not every 710-family firmware answers)."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, device, field: str) -> None:
        """Initialize."""
        unit = {"area": UnitOfArea.SQUARE_METERS, "time": UnitOfTime.MINUTES, "cleanings": None}[field]
        super().__init__(
            device,
            SensorEntityDescription(
                key=f"total_stats_{field}",
                translation_key=f"total_stats_{field}",
                native_unit_of_measurement=unit,
                state_class=SensorStateClass.TOTAL_INCREASING,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )
        self._field = field

    async def async_added_to_hass(self) -> None:
        """Subscribe."""
        await super().async_added_to_hass()

        async def on_event(event: TotalStatsEvent) -> None:
            value = getattr(event, self._field)
            self._attr_native_value = round(value / 60) if self._field == "time" else value
            self.async_write_ha_state()

        self._subscribe(TotalStatsEvent, on_event)
