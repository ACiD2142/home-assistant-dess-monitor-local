"""Auto-detection of the inverter protocol, wire framing and TCP port.

The detector is intentionally conservative: it only issues read-only probe
commands, one connection at a time, and accepts a reply only when the codec
produces real inverter fields (not a NAK, banner, or random bytes).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .const import (
    CANDIDATE_PORTS,
    FRAMING_ASCII,
    FRAMING_MODBUS_TCP,
    FRAMING_RTU,
    PROBE_COMMANDS,
    PROTOCOL_AXPERT,
    PROTOCOL_PI18,
    PROTOCOL_SMG2,
    has_meaningful_data,
)
from .protocols import AxpertProtocol, Pi18Protocol, Smg2ModbusProtocol
from .transport import LocalTcpTransport, TransportError, hexlify

_LOGGER = logging.getLogger(__name__)

# Detection must stay bounded — a config flow that hangs is worse than one
# that reports "not found".
CONNECT_CHECK_TIMEOUT = 0.6
PROBE_TIMEOUT = 2.0
TOTAL_DETECTION_TIMEOUT = 45.0

_PROTOCOL_FACTORIES = {
    PROTOCOL_AXPERT: AxpertProtocol,
    PROTOCOL_PI18: Pi18Protocol,
    PROTOCOL_SMG2: Smg2ModbusProtocol,
}


@dataclass(frozen=True)
class DetectionResult:
    """Everything setup needs to talk to the device."""

    host: str
    port: int
    protocol: str
    framing: str
    sample: dict[str, Any]


def _framings_for(protocol: str, port: int) -> tuple[str, ...]:
    if protocol == PROTOCOL_AXPERT or protocol == PROTOCOL_PI18:
        return (FRAMING_ASCII,)
    # Port 502 is almost always MBAP-framed Modbus TCP; dongles on other
    # ports usually bridge raw RTU bytes. Try the likely one first but fall
    # back to the other.
    if port == 502:
        return (FRAMING_MODBUS_TCP, FRAMING_RTU)
    return (FRAMING_RTU, FRAMING_MODBUS_TCP)


def _protocol_order() -> tuple[str, ...]:
    return (PROTOCOL_AXPERT, PROTOCOL_PI18, PROTOCOL_SMG2)


async def _port_is_open(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=CONNECT_CHECK_TIMEOUT
        )
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass
    return True


async def probe(
    host: str,
    port: int,
    protocol: str,
    framing: str,
    timeout: float = PROBE_TIMEOUT,
) -> DetectionResult | None:
    """Try one (port, protocol, framing) combination.

    Returns a :class:`DetectionResult` on the first meaningful reply, else
    ``None``. The transport's last raw frames are kept for diagnostics.
    """
    codec = _PROTOCOL_FACTORIES[protocol]()
    transport = LocalTcpTransport(host, port, timeout=timeout)

    for command in PROBE_COMMANDS[protocol]:
        try:
            frame = codec.encode(command)
        except (ValueError, KeyError):
            continue
        try:
            raw = await transport.send(frame, framing)
        except TransportError as err:
            _LOGGER.debug(
                "DESS local probe %s/%s/%s on %s:%s: %s",
                protocol, framing, command, host, port, err,
            )
            continue
        if not raw:
            continue
        decoded = codec.decode(command, raw)
        _LOGGER.debug(
            "DESS local probe %s/%s/%s reply=%s decoded=%s",
            protocol, framing, command, hexlify(raw), decoded,
        )
        if has_meaningful_data(decoded):
            return DetectionResult(
                host=host,
                port=port,
                protocol=protocol,
                framing=framing,
                sample=decoded,
            )
    return None


async def detect_device(
    host: str,
    port: int = 0,
    timeout: float = PROBE_TIMEOUT,
) -> DetectionResult:
    """Find a working (port, protocol, framing) for ``host``.

    ``port == 0`` scans :data:`CANDIDATE_PORTS`; a non-zero port probes only
    that port. Raises ``TimeoutError`` when nothing responds.
    """
    ports = (int(port),) if port else CANDIDATE_PORTS

    async def _run() -> DetectionResult | None:
        for candidate_port in ports:
            if not await _port_is_open(host, candidate_port):
                continue
            _LOGGER.debug("DESS local: port %s open, probing protocols", candidate_port)
            for protocol in _protocol_order():
                for framing in _framings_for(protocol, candidate_port):
                    result = await probe(
                        host, candidate_port, protocol, framing, timeout=timeout
                    )
                    if result is not None:
                        return result
        return None

    result = await asyncio.wait_for(_run(), timeout=TOTAL_DETECTION_TIMEOUT)
    if result is None:
        raise TimeoutError(
            f"No DESS inverter answered on {host} "
            f"(tried ports: {', '.join(str(p) for p in ports)})"
        )
    _LOGGER.info(
        "DESS local: detected %s / %s on %s:%s",
        result.protocol, result.framing, result.host, result.port,
    )
    return result
