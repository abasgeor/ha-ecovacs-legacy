"""Base entity for Ecovacs Legacy."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from deebot_client.device import Device
from deebot_client.events import AvailabilityEvent
from deebot_client.events.base import Event

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN
from .hardware import LEGACY_CLASSES


class EcovacsLegacyEntity(Entity):
    """Entity bound to a deebot-client Device, updated by events."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: Device, description: EntityDescription) -> None:
        """Initialize."""
        self.entity_description = description
        self._device = device
        self._attr_unique_id = f"{device.device_info['did']}_{description.key}"
        self._subscribed: set[type[Event]] = set()
        api = device.device_info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, api["did"])},
            manufacturer="Ecovacs",
            model=api.get("deviceName") or LEGACY_CLASSES.get(api["class"]),
            model_id=api["class"],
            name=api.get("nick") or api.get("deviceName") or api["did"],
            serial_number=api.get("name"),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability."""
        await super().async_added_to_hass()

        async def on_available(event: AvailabilityEvent) -> None:
            self._attr_available = event.available
            self.async_write_ha_state()

        self._subscribe(AvailabilityEvent, on_available)

    def _subscribe[EventT: Event](
        self,
        event_type: type[EventT],
        callback: Callable[[EventT], Coroutine[Any, Any, None]],
    ) -> None:
        self._subscribed.add(event_type)
        self.async_on_remove(self._device.events.subscribe(event_type, callback))

    async def async_update(self) -> None:
        """Used by homeassistant.update_entity: ask the robot again."""
        for event_type in self._subscribed:
            self._device.events.request_refresh(event_type)
