"""Diagnostics support for the go-eCharger (API v1) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import GoeChargerConfigEntry

# Wi-Fi key and hotspot password.
TO_REDACT = {"wke", "wak"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoeChargerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
        },
        "connection": {
            "connected": coordinator.connected,
            "last_success": coordinator.last_success,
            "last_error": coordinator.last_error,
            "consecutive_failures": coordinator.consecutive_failures,
            "requested_max_current": coordinator.requested_max_current,
            "pending_max_current": coordinator.pending_max_current,
            "pending_since": coordinator.pending_since,
            "amx_workaround_applied": coordinator.amx_workaround_applied,
            "amx_last_error": coordinator.amx_last_error,
            "auto_reboot_no_ground": coordinator.auto_reboot_no_ground,
            "auto_reboot_armed": coordinator.auto_reboot_armed,
            "last_auto_reboot": coordinator.last_auto_reboot,
        },
        "status": async_redact_data(coordinator.data or {}, TO_REDACT),
    }
