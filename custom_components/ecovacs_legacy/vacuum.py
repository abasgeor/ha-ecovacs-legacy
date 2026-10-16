"""Vacuum platform for Ecovacs Legacy."""

from __future__ import annotations

from typing import Any

from deebot_client.events import FanSpeedEvent, FanSpeedLevel, StateEvent
from deebot_client.models import CleanAction, State

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    StateVacuumEntityDescription,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcovacsLegacyConfigEntry
from .entity import EcovacsLegacyEntity

_STATE_TO_ACTIVITY = {
    State.IDLE: VacuumActivity.IDLE,
    State.CLEANING: VacuumActivity.CLEANING,
    State.RETURNING: VacuumActivity.RETURNING,
    State.DOCKED: VacuumActivity.DOCKED,
    State.ERROR: VacuumActivity.ERROR,
    State.PAUSED: VacuumActivity.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcovacsLegacyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the vacuum entities."""
    async_add_entities(EcovacsLegacyVacuum(d) for d in entry.runtime_data.devices)


class EcovacsLegacyVacuum(EcovacsLegacyEntity, StateVacuumEntity):
    """DEEBOT 710/711 vacuum."""

    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
    )

    def __init__(self, device) -> None:
        """Initialize."""
        super().__init__(device, StateVacuumEntityDescription(key="vacuum", name=None))
        self._caps = device.capabilities
        self._attr_fan_speed_list = [lvl.name.lower() for lvl in self._caps.fan_speed.types]

    async def async_added_to_hass(self) -> None:
        """Subscribe to state and fan speed."""
        await super().async_added_to_hass()

        async def on_state(event: StateEvent) -> None:
            self._attr_activity = _STATE_TO_ACTIVITY.get(event.state)
            self.async_write_ha_state()

        async def on_fan(event: FanSpeedEvent) -> None:
            self._attr_fan_speed = event.speed.name.lower()
            self.async_write_ha_state()

        self._subscribe(StateEvent, on_state)
        self._subscribe(FanSpeedEvent, on_fan)

    async def _clean(self, action: CleanAction) -> None:
        await self._device.execute_command(self._caps.clean.action.command(action))

    async def async_start(self) -> None:
        """Start (or resume) cleaning."""
        action = CleanAction.RESUME if self.activity == VacuumActivity.PAUSED else CleanAction.START
        await self._clean(action)

    async def async_pause(self) -> None:
        """Pause."""
        await self._clean(CleanAction.PAUSE)

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop."""
        await self._clean(CleanAction.STOP)

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Go back to the dock."""
        await self._device.execute_command(self._caps.charge.execute())

    async def async_locate(self, **kwargs: Any) -> None:
        """Play the 'I am here' sound."""
        await self._device.execute_command(self._caps.play_sound.execute())

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set suction power (normal / max)."""
        level = FanSpeedLevel[fan_speed.upper()]
        await self._device.execute_command(self._caps.fan_speed.set(level))
        self._device.events.request_refresh(FanSpeedEvent)

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        """Send a raw XML command (args as dict -> ctl attributes)."""
        from deebot_client.commands.xml.common import ExecuteCommand

        class _Raw(ExecuteCommand):
            NAME = command

        await self._device.execute_command(_Raw(params if isinstance(params, dict) else {}))
