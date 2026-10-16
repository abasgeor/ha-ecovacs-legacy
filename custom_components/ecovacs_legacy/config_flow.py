"""Config flow for Ecovacs Legacy."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import random
import string
from typing import Any

from aiohttp import ClientError
from deebot_client.authentication import Authenticator
from deebot_client.exceptions import (
    DeviceVerificationRequiredError,
    InvalidAuthenticationError,
    InvalidVerificationCodeError,
)

try:  # Home Assistant >= 2026.10 ships probatio (voluptuous-compatible)
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_COUNTRY, CONF_DEVICE_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .const import CONF_DEVICES, CONF_VERIFICATION_CODE, DOMAIN
from .controller import async_get_legacy_devices, create_authenticator
from .hardware import LEGACY_CLASSES

_LOGGER = logging.getLogger(__name__)


def _new_device_id() -> str:
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))


class EcovacsLegacyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._input: dict[str, Any] = {}
        self._authenticator: Authenticator | None = None
        self._devices: dict[str, str] = {}

    async def _teardown(self) -> None:
        if self._authenticator is not None:
            await self._authenticator.teardown()
            self._authenticator = None

    async def _login(self) -> dict[str, str]:
        """Try to log in and list legacy devices. Returns errors (empty = ok).

        Raises DeviceVerificationRequiredError so the caller can ask for a code.
        """
        await self._teardown()
        self._authenticator = create_authenticator(self.hass, self._input)
        try:
            await self._authenticator.authenticate()
            return await self._load_devices()
        except DeviceVerificationRequiredError:
            raise
        except InvalidAuthenticationError:
            return {"base": "invalid_auth"}
        except ClientError:
            _LOGGER.debug("Cannot connect", exc_info=True)
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected exception during login")
            return {"base": "unknown"}

    async def _load_devices(self) -> dict[str, str]:
        assert self._authenticator is not None
        devices = await async_get_legacy_devices(self._authenticator)
        self._devices = {
            d["did"]: f"{d.get('nick') or d.get('deviceName') or d['did']} "
            f"({LEGACY_CLASSES.get(d['class'], d['class'])})"
            for d in devices
        }
        return {}

    async def _request_code(self) -> dict[str, str]:
        assert self._authenticator is not None
        try:
            await self._authenticator.request_device_verification_code()
        except ClientError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected exception requesting verification code")
            return {"base": "unknown"}
        return {}

    async def _after_login(self) -> ConfigFlowResult:
        if self.source == SOURCE_REAUTH:
            await self._teardown()
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=self._input
            )
        if not self._devices:
            await self._teardown()
            return self.async_abort(reason="no_devices")
        return await self.async_step_devices()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the Ecovacs account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].strip().lower())
            self._abort_if_unique_id_configured()
            self._input = {**user_input, CONF_DEVICE_ID: _new_device_id()}
            try:
                errors = await self._login()
            except DeviceVerificationRequiredError:
                errors = await self._request_code()
                if not errors:
                    return await self.async_step_device_verification()
            if not errors:
                return await self._after_login()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): selector.TextSelector(),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_COUNTRY): selector.CountrySelector(),
            }
        )
        suggested = user_input or {CONF_COUNTRY: self.hass.config.country or "MX"}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_device_verification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the e-mailed code that verifies this client device id."""
        errors: dict[str, str] = {}
        if user_input is not None and self._authenticator is not None:
            try:
                await self._authenticator.verify_device(
                    str(user_input[CONF_VERIFICATION_CODE]).strip()
                )
                errors = await self._load_devices()
            except InvalidVerificationCodeError:
                errors = {"base": "invalid_verification_code"}
            except ClientError:
                errors = {"base": "cannot_connect"}
            except Exception:
                _LOGGER.exception("Unexpected exception verifying device")
                errors = {"base": "unknown"}
            if not errors:
                return await self._after_login()

        return self.async_show_form(
            step_id="device_verification",
            data_schema=vol.Schema({vol.Required(CONF_VERIFICATION_CODE): str}),
            errors=errors,
            description_placeholders={"username": self._input.get(CONF_USERNAME, "")},
        )

    async def async_step_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick which legacy robots this Home Assistant should expose."""
        if user_input is not None and user_input.get(CONF_DEVICES):
            await self._teardown()
            return self.async_create_entry(
                title=self._input[CONF_USERNAME],
                data={**self._input, CONF_DEVICES: list(user_input[CONF_DEVICES])},
            )
        options = [
            selector.SelectOptionDict(value=did, label=label)
            for did, label in self._devices.items()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICES, default=list(self._devices)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="devices", data_schema=schema)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Re-authenticate (password change or new device verification)."""
        self._input = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the password and log in again with the stored device id."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._input[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            try:
                errors = await self._login()
            except DeviceVerificationRequiredError:
                errors = await self._request_code()
                if not errors:
                    return await self.async_step_device_verification()
            if not errors:
                return await self._after_login()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"username": self._input.get(CONF_USERNAME, "")},
        )
