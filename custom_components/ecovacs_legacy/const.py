"""Constants for the Ecovacs Legacy integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ecovacs_legacy"

CONF_DEVICES: Final = "devices"
CONF_VERIFICATION_CODE: Final = "verification_code"

# Periodic refresh on top of the MQTT push channel. The DEEBOT 710 family does
# not push every change (battery, consumables), so we ask for it from time to time.
REFRESH_INTERVAL: Final = timedelta(minutes=5)
SLOW_REFRESH_EVERY: Final = 12  # x REFRESH_INTERVAL -> life span / totals hourly

PLATFORMS: Final = ["sensor", "vacuum"]
