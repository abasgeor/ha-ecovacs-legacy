"""Controller: Ecovacs cloud session, MQTT channel and legacy devices."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from deebot_client.api_client import ApiClient
from deebot_client.authentication import Authenticator, create_rest_config
from deebot_client.device import Device
from deebot_client.exceptions import (
    DeebotError,
    DeviceVerificationRequiredError,
    InvalidAuthenticationError,
)
from deebot_client.models import ApiDeviceInfo, DeviceInfo
from deebot_client.mqtt_client import MqttClient, create_mqtt_config
from deebot_client.util import md5

from homeassistant.const import CONF_COUNTRY, CONF_DEVICE_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client

from .const import CONF_DEVICES
from .hardware import LEGACY_CLASSES, get_static_device_info

_LOGGER = logging.getLogger(__name__)


def create_authenticator(
    hass: HomeAssistant, config: Mapping[str, Any]
) -> Authenticator:
    """Create an authenticator for the given config."""
    return Authenticator(
        create_rest_config(
            aiohttp_client.async_get_clientsession(hass),
            device_id=config[CONF_DEVICE_ID],
            alpha_2_country=config[CONF_COUNTRY],
        ),
        config[CONF_USERNAME],
        md5(config[CONF_PASSWORD]),
    )


async def async_get_legacy_devices(authenticator: Authenticator) -> list[ApiDeviceInfo]:
    """Return the devices of the account that only this integration handles.

    The core integration takes everything deebot-client knows (MQTT/JSON and
    MQTT/XML classes with a hardware file) plus the XMPP ones; we only take the
    legacy classes it reports as "not supported".
    """
    devices = await ApiClient(authenticator).get_devices()
    return [d for d in devices.not_supported if d.get("class") in LEGACY_CLASSES]


class EcovacsLegacyController:
    """Holds the cloud session and the Device objects."""

    def __init__(self, hass: HomeAssistant, config: Mapping[str, Any]) -> None:
        """Initialize."""
        self._hass = hass
        self._config = config
        self._authenticator = create_authenticator(hass, config)
        self._mqtt: MqttClient | None = None
        self.devices: list[Device] = []

    async def initialize(self) -> None:
        """Log in, find the selected devices and subscribe them to MQTT."""
        wanted: set[str] = set(self._config.get(CONF_DEVICES, []))
        try:
            legacy = await async_get_legacy_devices(self._authenticator)
            selected = [d for d in legacy if not wanted or d["did"] in wanted]
            if wanted and not selected:
                _LOGGER.warning(
                    "None of the configured devices were returned by the Ecovacs cloud"
                )
            if selected:
                config = await self._hass.async_add_executor_job(
                    lambda: create_mqtt_config(
                        device_id=self._config[CONF_DEVICE_ID],
                        country=self._config[CONF_COUNTRY],
                    )
                )
                self._mqtt = MqttClient(config, self._authenticator)
                await self._mqtt.verify_config()
            for api_info in selected:
                static = get_static_device_info(api_info["class"])
                if static is None:  # pragma: no cover - filtered above
                    continue
                device = Device(DeviceInfo(api_info, static), self._authenticator)
                await device.initialize(self._mqtt)
                self.devices.append(device)
        except DeviceVerificationRequiredError as ex:
            raise ConfigEntryAuthFailed("Device verification required") from ex
        except InvalidAuthenticationError as ex:
            raise ConfigEntryAuthFailed("Invalid credentials") from ex
        except DeebotError as ex:
            raise ConfigEntryNotReady(f"Error during setup: {ex}") from ex

    async def teardown(self) -> None:
        """Disconnect everything."""
        for device in self.devices:
            await device.teardown()
        if self._mqtt is not None:
            await self._mqtt.disconnect()
        await self._authenticator.teardown()
