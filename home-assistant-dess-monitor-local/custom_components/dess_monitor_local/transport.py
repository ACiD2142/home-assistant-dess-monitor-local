"""Raw TCP transport for local inverter WiFi dongles.

Three wire flavours are supported:

``ascii``
    Voltronic Axpert (PI30) and PI18 frames. Requests are ASCII plus a
    CRC-16/XMODEM and CR; replies end with a CR. We read to the CR and hand
    the bytes (including CR) to the protocol decoder, which strips the
    envelope itself.

``rtu``
    Raw Modbus RTU bytes over TCP. Many cheap WiFi dongles simply bridge the
    RS-485 line to a TCP socket, so a standard RTU frame goes out and an RTU
    frame comes back. Response length is derived from the byte-count field.

``modbus_tcp``
    Standard MBAP-framed Modbus TCP (typical on port 502). We wrap the RTU
    PDU produced by the codec in an MBAP header and re-build an RTU frame on
    the way back so the protocol decoder stays unchanged.

No external library is used — just asyncio streams.
"""
from __future__ import annotations

import asyncio
import struct
from time import monotonic

from .const import FRAMING_ASCII, FRAMING_MODBUS_TCP, FRAMING_RTU
from .protocols.crc import crc16_modbus_bytes


class TransportError(Exception):
    """Local TCP I/O or framing failure."""


class LocalTcpTransport:
    """One-shot TCP transport: connect, send one frame, read one reply.

    A fresh connection per transaction is intentional. Dongles frequently
    tolerate only a single client and some close the socket after each reply;
    reconnecting keeps every command independent and self-healing.
    """

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._tx_id = 0
        # Last raw bytes on the wire, exposed through diagnostics.
        self.last_tx: bytes = b""
        self.last_rx: bytes = b""

    async def send(self, frame: bytes, framing: str) -> bytes:
        """Send ``frame`` and return the raw reply bytes."""
        if not self.host or not self.port:
            raise TransportError("host and port must be configured")

        wire_frame = self._to_wire(frame, framing)
        self.last_tx = wire_frame
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (OSError, TimeoutError, asyncio.TimeoutError) as err:
            raise TransportError(
                f"cannot connect to {self.host}:{self.port}: {err}"
            ) from err

        try:
            writer.write(wire_frame)
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)

            if framing == FRAMING_ASCII:
                raw = await self._read_ascii(reader)
            elif framing == FRAMING_MODBUS_TCP:
                raw = await self._read_modbus_tcp(reader)
            else:
                raw = await self._read_rtu(reader)
        except (OSError, asyncio.IncompleteReadError, struct.error) as err:
            raise TransportError(f"read from {self.host}:{self.port} failed: {err}") from err
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise TransportError(
                f"timed out waiting for reply from {self.host}:{self.port}"
            ) from err
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except Exception:  # noqa: BLE001 - best-effort socket cleanup
                pass

        self.last_rx = raw
        return raw

    # ------------------------------------------------------------------
    # Request framing
    # ------------------------------------------------------------------
    def _to_wire(self, frame: bytes, framing: str) -> bytes:
        if framing == FRAMING_MODBUS_TCP:
            # ``frame`` is a complete RTU ADU: [unit][pdu][crc_lo][crc_hi].
            # MBAP carries unit id + PDU, and the CRC is dropped.
            pdu = frame[:-2]
            if not pdu:
                raise TransportError("empty Modbus frame")
            self._tx_id = (self._tx_id + 1) & 0xFFFF
            header = struct.pack(">HHHB", self._tx_id, 0, len(pdu), pdu[0])
            return header + pdu[1:]
        # ASCII and raw RTU go out exactly as the codec produced them.
        return frame

    # ------------------------------------------------------------------
    # Reply framing
    # ------------------------------------------------------------------
    async def _read_ascii(self, reader: asyncio.StreamReader) -> bytes:
        """Read one ASCII reply line.

        Voltronic/PI18 replies end with CR, but some dongles emit LF or close
        the socket immediately after the frame. Reading in small chunks and
        stopping on either terminator (or EOF) handles all three cases.
        """
        buf = bytearray()
        deadline = monotonic() + self.timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for ASCII reply")
            chunk = await asyncio.wait_for(reader.read(128), timeout=remaining)
            if not chunk:  # EOF — return whatever arrived before the close
                break
            buf.extend(chunk)
            if b"\r" in chunk or b"\n" in chunk:
                break
        return bytes(buf)

    async def _read_rtu(self, reader: asyncio.StreamReader) -> bytes:
        header = await asyncio.wait_for(reader.readexactly(2), timeout=self.timeout)
        func = header[1]
        if func & 0x80:
            # Exception reply: [unit][func|0x80][code][crc_lo][crc_hi]
            tail = await asyncio.wait_for(reader.readexactly(3), timeout=self.timeout)
            return header + tail
        # Normal read: [unit][func][byte_count][data][crc_lo][crc_hi]
        bc = await asyncio.wait_for(reader.readexactly(1), timeout=self.timeout)
        count = bc[0]
        if count > 250:
            raise TransportError(f"implausible Modbus byte count {count}")
        rest = await asyncio.wait_for(
            reader.readexactly(count + 2), timeout=self.timeout
        )
        return header + bc + rest

    async def _read_modbus_tcp(self, reader: asyncio.StreamReader) -> bytes:
        header = await asyncio.wait_for(reader.readexactly(7), timeout=self.timeout)
        _tx_id, protocol_id, length, unit = struct.unpack(">HHHB", header)
        if protocol_id != 0:
            raise TransportError(f"unexpected Modbus protocol id {protocol_id}")
        if length < 2 or length > 254:
            raise TransportError(f"implausible Modbus TCP length {length}")
        body = await asyncio.wait_for(
            reader.readexactly(length - 1), timeout=self.timeout
        )  # unit byte was already consumed by the 7-byte header
        rtu = header[6:7] + body
        return rtu + crc16_modbus_bytes(rtu)


def hexlify(data: bytes, limit: int = 128) -> str:
    """Compact hex preview for diagnostics."""
    if not data:
        return ""
    shown = data[:limit]
    text = " ".join(f"{b:02X}" for b in shown)
    if len(data) > limit:
        text += f" ... (+{len(data) - limit} bytes)"
    return text
