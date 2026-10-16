"""Ecovacs Legacy: DEEBOT 710/711 family (MQTT/XML) for Home Assistant."""

from __future__ import annotations

from datetime import datetime

from deebot_client.events import (
    BatteryEvent,
    ErrorEvent,
    FanSpeedEvent,
    LifeSpanEvent,
    StateEvent,
    TotalStatsEvent,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import PLATFORMS, REFRESH_INTERVAL, SLOW_REFRESH_EVERY
from .controller import EcovacsLegacyController

type EcovacsLegacyConfigEntry = ConfigEntry[EcovacsLegacyController]

_FAST_EVENTS = (StateEvent, BatteryEvent, ErrorEvent, FanSpeedEvent)
_SLOW_EVENTS = (LifeSpanEvent, TotalStatsEvent)


async def async_setup_entry(hass: HomeAssistant, entry: EcovacsLegacyConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    controller = EcovacsLegacyController(hass, entry.data)
    await controller.initialize()

    async def _teardown() -> None:
        await controller.teardown()

    entry.async_on_unload(_teardown)
    entry.runtime_data = controller

    ticks = 0

    def _refresh(_: datetime) -> None:
        nonlocal ticks
        ticks += 1
        events = _FAST_EVENTS + (_SLOW_EVENTS if ticks % SLOW_REFRESH_EVERY == 0 else ())
        for device in controller.devices:
            for event in events:
                device.events.request_refresh(event)

    entry.async_on_unload(async_track_time_interval(hass, _refresh, REFRESH_INTERVAL))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EcovacsLegacyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
