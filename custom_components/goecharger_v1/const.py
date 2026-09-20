"""Constants for the go-eCharger (API v1) integration."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "goecharger_v1"
LOGGER = logging.getLogger(__package__)

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

MANUFACTURER: Final = "go-e"
MODEL: Final = "go-eCharger (API v1)"

# Polling. The API documentation recommends at least a 5 second delay.
DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 3600

# HTTP behaviour. Every request is tried up to DEFAULT_RETRIES times with a
# linear back-off of RETRY_BACKOFF * attempt seconds between attempts.
DEFAULT_TIMEOUT: Final = 10.0
DEFAULT_RETRIES: Final = 3
RETRY_BACKOFF: Final = 1.0

# Seconds to wait for the charger to reflect a new amx value in its status
# before the firmware 0.42.0 workaround (amp=6, amp=<max>, amx again) runs.
AMX_CONFIRM_TIMEOUT: Final = 30

# Charging current limits of the charger (whole amperes).
MIN_CURRENT: Final = 6
MAX_CURRENT: Final = 32
