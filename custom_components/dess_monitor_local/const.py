"""Constants for the DESS Monitor Local integration.

Everything here is local-only: no cloud host, no credentials, no account.
"""
from __future__ import annotations

DOMAIN = "dess_monitor_local"

# ---------------------------------------------------------------------------
# Configuration keys
# ---------------------------------------------------------------------------
CONF_HOST = "host"
CONF_PORT = "port"
CONF_PROTOCOL = "protocol"
CONF_FRAMING = "framing"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TIMEOUT = "timeout"

DEFAULT_HOST = "192.168.1.4"
DEFAULT_PORT = 0  # 0 = scan the candidate port list
DEFAULT_PROTOCOL = "auto"
DEFAULT_FRAMING = "auto"
DEFAULT_UPDATE_INTERVAL = 10
DEFAULT_TIMEOUT = 5.0

MIN_UPDATE_INTERVAL = 2
MAX_UPDATE_INTERVAL = 600
MIN_TIMEOUT = 0.5
MAX_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Protocols / wire framings
# ---------------------------------------------------------------------------
PROTOCOL_AXPERT = "axpert"
PROTOCOL_PI18 = "pi18"
PROTOCOL_SMG2 = "smg2_modbus"
PROTOCOL_AUTO = "auto"
PROTOCOL_OPTIONS = (PROTOCOL_AUTO, PROTOCOL_AXPERT, PROTOCOL_PI18, PROTOCOL_SMG2)

FRAMING_ASCII = "ascii"          # Voltronic ASCII / PI18: read until CR
FRAMING_RTU = "rtu"              # raw Modbus RTU bytes over TCP (WiFi dongle passthrough)
FRAMING_MODBUS_TCP = "modbus_tcp"  # standard MBAP-framed Modbus TCP (port 502 devices)
FRAMING_AUTO = "auto"

# Ports commonly used by Voltronic / SMG-II WiFi dongles. 0 is never scanned.
CANDIDATE_PORTS: tuple[int, ...] = (
    502,     # standard Modbus TCP
    8899,    # common Voltronic WiFi dongle
    9000,    # common Voltronic WiFi dongle
    5000,    # common logger port
    23,      # raw serial-over-Telnet dongles
    8888,
    8000,
    10001,
    12345,
    2000,
    4000,
    15000,
)

# Probe commands, in order. Read-only commands only.
PROBE_COMMANDS: dict[str, tuple[str, ...]] = {
    PROTOCOL_AXPERT: ("QID", "QPIGS", "QMOD"),
    PROTOCOL_PI18: ("PI", "GS", "MOD"),
    # SMG2 is probed with both RTU and MBAP framings by the detector.
    PROTOCOL_SMG2: ("QPIGS",),
}

# Poll plans. A command may populate more than one section (PI18's GS reply
# carries both qpigs and qpigs2), so sections are grouped by command.
POLL_COMMANDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    PROTOCOL_AXPERT: (
        ("QPIGS", ("qpigs",)),
        ("QPIGS2", ("qpigs2",)),
        ("QPIRI", ("qpiri",)),
        ("QMOD", ("qmod",)),
    ),
    PROTOCOL_PI18: (
        ("QPIGS", ("qpigs", "qpigs2")),  # GS → multi-section reply
        ("QPIRI", ("qpiri",)),
        ("QMOD", ("qmod",)),
    ),
    PROTOCOL_SMG2: (
        ("QPIGS", ("qpigs",)),
        ("QPIRI", ("qpiri",)),
        ("QMOD", ("qmod",)),
    ),
}

# A probe result is only accepted if the decoded reply contains at least one
# of these keys. This rejects random banner text and NAK frames.
_VALID_KEYS = frozenset({
    "grid_voltage",
    "battery_voltage",
    "output_active_power",
    "Device ID",
    "protocol_id",
    "operating_mode",
    "qpigs",
})


def has_meaningful_data(decoded: dict) -> bool:
    """True when a decoded probe reply looks like real inverter data."""
    if not isinstance(decoded, dict):
        return False
    if decoded.get("error") or decoded.get("status") == "NAK":
        return False
    if decoded.get("Raw"):
        return False
    if any(key in decoded for key in _VALID_KEYS):
        return True
    # Multi-section replies (PI18 GS) nest the real data under section keys.
    for value in decoded.values():
        if isinstance(value, dict) and any(k in value for k in _VALID_KEYS):
            return True
    return False
