"""Hub + coordinator for the local (cloud-free) inverter connection."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import detector
from .const import (
    CONF_FRAMING,
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FRAMING,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PROTOCOL,
    DEFAULT_UPDATE_INTERVAL,
    FRAMING_AUTO,
    POLL_COMMANDS,
    PROTOCOL_AUTO,
)
from .protocols import AxpertProtocol, Pi18Protocol, Protocol, Smg2ModbusProtocol
from .transport import LocalTcpTransport, TransportError, hexlify

_LOGGER = logging.getLogger(__name__)

_CODECS = {
    "axpert": AxpertProtocol,
    "pi18": Pi18Protocol,
    "smg2_modbus": Smg2ModbusProtocol,
}


class LocalInverterHub:
    """Owns the connection details, detected codec and poll state."""

    manufacturer = "DESS (local)"

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data.get(CONF_HOST, DEFAULT_HOST)
        self.port: int = int(entry.data.get(CONF_PORT, DEFAULT_PORT))
        self.configured_protocol: str = entry.data.get(CONF_PROTOCOL, DEFAULT_PROTOCOL)
        self.configured_framing: str = entry.data.get(CONF_FRAMING, DEFAULT_FRAMING)
        self.name: str = entry.data.get("name") or f"DESS {self.host}"
        self.device_id: str = self.host

        self.protocol: str = ""
        self.framing: str = ""
        self.codec: Protocol | None = None
        self.transport = LocalTcpTransport(
            self.host,
            self.port,
            timeout=float(entry.data.get("timeout", 5.0)),
        )

        self.last_success_at: float | None = None
        self.last_error: str | None = None
        self.last_tx_hex = ""
        self.last_rx_hex = ""

    @property
    def detected(self) -> bool:
        return self.codec is not None

    async def async_detect(self) -> None:
        """Resolve protocol/port/framing, storing concrete values on the entry.

        A failed detection raises :class:`TimeoutError`; ``async_setup_entry``
        translates that into ``ConfigEntryNotReady`` so HA retries later.
        """
        if (
            self.configured_protocol not in (PROTOCOL_AUTO, "")
            and self.configured_framing not in (FRAMING_AUTO, "")
            and self.port
        ):
            # Everything pinned by the user — no probing needed.
            self.protocol = self.configured_protocol
            self.framing = self.configured_framing
            self.port = int(self.port)
            self.transport.port = self.port
        else:
            result = await detector.detect_device(
                self.host,
                self.port,
                timeout=self.transport.timeout,
            )
            self.protocol = result.protocol
            self.framing = result.framing
            self.port = result.port
            self.transport.port = result.port

        self.codec = _CODECS[self.protocol]()
        # Persist what we learned so subsequent restarts skip the scan.
        updates = {
            CONF_PORT: self.port,
            CONF_PROTOCOL: self.protocol,
            CONF_FRAMING: self.framing,
        }
        if updates != {k: self.entry.data.get(k) for k in updates}:
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, **updates},
            )
        _LOGGER.info(
            "DESS local: %s on %s:%s (%s)", self.name, self.host, self.port, self.protocol
        )

    async def async_poll(self) -> dict[str, dict[str, Any]]:
        """Fetch all sections for this device in one coordinator tick."""
        assert self.codec is not None, "hub must be detected before polling"
        commands = POLL_COMMANDS[self.protocol]
        sections: dict[str, dict[str, Any]] = {}
        errors: list[str] = []

        for command, targets in commands:
            try:
                frame = self.codec.encode(command)
            except (ValueError, KeyError) as err:
                errors.append(f"{command} encode: {err}")
                for target in targets:
                    sections[target] = {}
                continue

            # Record the attempted frame even when the device never answers,
            # so diagnostics show what was sent on the failing transaction.
            self.last_tx_hex = hexlify(frame)
            self.last_rx_hex = ""

            try:
                raw = await self.transport.send(frame, self.framing)
                decoded = self.codec.decode(command, raw)
            except (ValueError, KeyError, IndexError, TypeError, TransportError) as err:
                self.last_rx_hex = hexlify(self.transport.last_rx)
                errors.append(f"{command}: {err}")
                for target in targets:
                    sections[target] = {}
                continue

            self.last_tx_hex = hexlify(self.transport.last_tx)
            self.last_rx_hex = hexlify(self.transport.last_rx)

            if decoded.get("error"):
                errors.append(f"{command}: {decoded['error']}")
                for target in targets:
                    sections[target] = {}
                continue

            if len(targets) == 1:
                sections[targets[0]] = decoded
                continue
            # Multi-section reply (PI18 GS): pull each section out by name.
            for target in targets:
                value = decoded.get(target)
                sections[target] = value if isinstance(value, dict) else {}

        if errors:
            self.last_error = "; ".join(errors)
        else:
            self.last_error = None
            self.last_success_at = monotonic()
        return sections


class LocalCoordinator(DataUpdateCoordinator):
    """Polls the local inverter and fans the data out to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Any,
        hub: LocalInverterHub,
    ) -> None:
        interval = int(
            entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        interval = max(2, min(600, interval))
        super().__init__(
            hass,
            _LOGGER,
            name="DESS Local",
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
            # Diagnostic entities read hub state (last success/error), not
            # coordinator.data. Keeping always_update=True guarantees they
            # refresh even when the inverter's values are unchanged.
            always_update=True,
        )
        self.hub = hub

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            async with asyncio.timeout(max(30, int(self.update_interval.total_seconds()) + 5)):
                sections = await self.hub.async_poll()
            return {self.hub.device_id: sections}
        except TransportError as err:
            raise UpdateFailed(f"DESS local: {err}") from err
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise UpdateFailed("DESS local: timed out talking to the inverter") from err
