"""Capabilities for the legacy DEEBOT 710 family (MQTT/XML "non-950" protocol).

These robots report `company: eco-ng` in the Ecovacs device list, talk XML over
the same REST endpoint (`iot/devmanager.do`, payloadType "x") and push XML on the
MQTT topic `iot/atr/<event>/<did>/<class>/<resource>/x`. deebot-client already
implements that transport for the OZMO 900 family; it only lacks a hardware
definition for these classes, which is why the core integration lists them as
"not supported".

Model knowledge comes from mrbungle64/ecovacs-deebot.js (0.9.6, `uv242z` and its
`deviceClassLink`s): main brush, side brush, filter, voice report, clean speed;
no map, no spot areas, no mopping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    CapabilityLifeSpan,
    CapabilitySettings,
    CapabilitySetTypes,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.xml import (
    Charge,
    Clean,
    GetBatteryInfo,
    GetChargeState,
    GetCleanSpeed,
    GetCleanState,
    GetCleanSum,
    GetError,
    GetLifeSpan,
    PlaySound,
    ResetLifeSpan,
    SetCleanSpeed,
)
from deebot_client.const import ERROR_CODES, DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CustomCommandEvent,
    ErrorEvent,
    FanSpeedEvent,
    FanSpeedLevel,
    LifeSpan,
    LifeSpanEvent,
    NetworkInfoEvent,
    ReportStatsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.message import HandlingResult
from deebot_client.models import State, StaticDeviceInfo

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    from deebot_client.event_bus import EventBus

# class -> marketing name. All of them link to the DEEBOT 710 (uv242z) profile.
LEGACY_CLASSES: dict[str, str] = {
    "uv242z": "DEEBOT 710",
    "jr3pqa": "DEEBOT 711",
    "d0cnel": "DEEBOT 711s",
    "eyi9jv": "DEEBOT 715",
}

LIFE_SPANS: tuple[LifeSpan, ...] = (
    LifeSpan.BRUSH,
    LifeSpan.SIDE_BRUSH,
    LifeSpan.DUST_CASE_HEAP,
)


def _merged_attrib(xml: Element) -> dict[str, str]:
    """Root attributes plus the attributes of every child (root wins)."""
    merged: dict[str, str] = {}
    for child in xml.iter():
        if child is xml:
            continue
        for key, value in child.attrib.items():
            merged.setdefault(key, value)
    merged.update(xml.attrib)
    return merged


class GetBatteryInfoLegacy(GetBatteryInfo):
    """GetBatteryInfo accepting `power` on the root or on a <battery> child."""

    @classmethod
    def _handle_xml(cls, event_bus: EventBus, xml: Element) -> HandlingResult:
        attrib = _merged_attrib(xml)
        power = attrib.get("power")
        if attrib.get("ret", "ok") != "ok" or power is None:
            return HandlingResult.analyse()
        try:
            value = int(float(power))
        except ValueError:
            return HandlingResult.analyse()
        if value < 0:
            return HandlingResult.analyse()
        event_bus.notify(BatteryEvent(min(value, 100)))
        return HandlingResult.success()


class GetLifeSpanLegacy(GetLifeSpan):
    """GetLifeSpan accepting every variant seen on non-950 models.

    left/total (OZMO 930), val/total (710 family), val only (per-mille), left only
    (minutes, Deebot 900/901). `type` may carry trailing spaces (Deebot M88).
    """

    @classmethod
    def _handle_xml(cls, event_bus: EventBus, xml: Element) -> HandlingResult:
        attrib = _merged_attrib(xml)
        if attrib.get("ret", "ok") != "ok" or not (raw := attrib.get("type")):
            return HandlingResult.analyse()
        try:
            component = LifeSpan.from_xml(raw.strip())
        except (ValueError, KeyError):
            return HandlingResult.analyse()

        def _int(key: str) -> int | None:
            try:
                return int(float(attrib[key]))
            except (KeyError, ValueError):
                return None

        left, val, total = _int("left"), _int("val"), _int("total")
        percent: float | None = None
        remaining = 0
        if val is not None and total:
            percent = val / total * 100
        elif left is not None and total:
            percent = left / total * 100
            remaining = left
        elif val is not None:
            percent = val / 100
        elif left is not None:
            percent = left / 60
            remaining = left
        if percent is None:
            return HandlingResult.analyse()
        event_bus.notify(
            LifeSpanEvent(component, round(max(0.0, min(percent, 100.0)), 2), remaining)
        )
        return HandlingResult.success()


class GetErrorLegacy(GetError):
    """GetError tolerant to a missing `errs` attribute; 100 means no error."""

    @classmethod
    def _handle_xml(cls, event_bus: EventBus, xml: Element) -> HandlingResult:
        attrib = _merged_attrib(xml)
        raw = ""
        for key in ("errs", "code", "errno", "error", "new"):
            if attrib.get(key):
                raw = attrib[key]
                break
        try:
            code = int(raw.split(",")[0]) if raw else 0
        except ValueError:
            return HandlingResult.analyse()
        if code == 100:
            code = 0
        if code != 0:
            event_bus.notify(StateEvent(State.ERROR))
        event_bus.notify(ErrorEvent(code, ERROR_CODES.get(code)))
        return HandlingResult.success()


def get_static_device_info(device_class: str) -> StaticDeviceInfo | None:
    """Return the static device info for a legacy class, or None."""
    if device_class not in LEGACY_CLASSES:
        return None
    return StaticDeviceInfo(
        DataType.XML,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, [GetBatteryInfoLegacy()]),
            charge=CapabilityExecute(Charge),
            clean=CapabilityClean(action=CapabilityCleanAction(command=Clean)),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=CustomCommand
            ),
            error=CapabilityEvent(ErrorEvent, [GetErrorLegacy()]),
            fan_speed=CapabilitySetTypes(
                event=FanSpeedEvent,
                get=[GetCleanSpeed()],
                set=SetCleanSpeed,
                types=(FanSpeedLevel.NORMAL, FanSpeedLevel.MAX),
            ),
            life_span=CapabilityLifeSpan(
                types=LIFE_SPANS,
                event=LifeSpanEvent,
                get=[GetLifeSpanLegacy(life_span) for life_span in LIFE_SPANS],
                reset=ResetLifeSpan,
            ),
            network=CapabilityEvent(NetworkInfoEvent, []),
            play_sound=CapabilityExecute(PlaySound),
            settings=CapabilitySettings(),
            state=CapabilityEvent(StateEvent, [GetChargeState(), GetCleanState()]),
            stats=CapabilityStats(
                clean=CapabilityEvent(StatsEvent, []),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, [GetCleanSum()]),
            ),
        ),
    )
