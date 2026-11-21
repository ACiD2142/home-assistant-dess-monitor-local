"""Diagnostics for DESS Monitor Local."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import LocalConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LocalConfigEntry
) -> dict[str, Any]:
    """Return connection details and the last raw frames for troubleshooting.

    There are no credentials in this integration, so nothing needs redacting.
    """
    hub = entry.runtime_data.hub
    coordinator = entry.runtime_data.coordinator
    return {
        "host": hub.host,
        "port": hub.port,
        "configured_protocol": hub.configured_protocol,
        "detected_protocol": hub.protocol,
        "detected_framing": hub.framing,
        "last_error": hub.last_error,
        "last_tx_hex": hub.last_tx_hex,
        "last_rx_hex": hub.last_rx_hex,
        "last_update_success": coordinator.last_update_success,
        "data": coordinator.data,
    }
