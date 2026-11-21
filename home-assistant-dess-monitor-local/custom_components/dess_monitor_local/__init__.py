"""The DESS Monitor Local integration.

Talks straight to an inverter WiFi dongle on the local network. No cloud
account, no internet access, no credentials — just one TCP socket.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import LocalCoordinator, LocalInverterHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)


@dataclass
class LocalRuntimeData:
    """Per-entry runtime objects."""

    hub: LocalInverterHub
    coordinator: LocalCoordinator


type LocalConfigEntry = ConfigEntry[LocalRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: LocalConfigEntry) -> bool:
    """Set up a local DESS inverter connection."""
    hub = LocalInverterHub(hass, entry)
    try:
        await hub.async_detect()
    except (TimeoutError, OSError, ValueError) as err:
        raise ConfigEntryNotReady(
            f"Cannot reach inverter at {hub.host}: {err}"
        ) from err

    coordinator = LocalCoordinator(hass, entry, hub)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = LocalRuntimeData(hub=hub, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LocalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: LocalConfigEntry) -> None:
    """Reload when options (e.g. poll interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
