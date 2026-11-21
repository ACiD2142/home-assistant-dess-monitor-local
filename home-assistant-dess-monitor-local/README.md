# DESS Monitor Local — Home Assistant integration

A **cloud-free** Home Assistant integration for inverter WiFi dongles. It talks
straight to the device on your LAN — no dessmonitor.com account, no internet,
no rate limits.

Default target: **`192.168.1.4`** (changeable in the UI).

---

## Features

- **Auto-detection** of the TCP port, protocol and wire framing:
  - Ports scanned: `502, 8899, 9000, 5000, 23, 8888, 8000, 10001, 12345, 2000, 4000, 15000`
  - Protocols: **Axpert / PI30** (ASCII), **PI18** (InfiniSolar), **SMG2 Modbus RTU**
  - Framings: ASCII-to-CR, raw RTU-over-TCP, standard MBAP Modbus TCP
  - Only read-only probe commands are sent; detection results are stored so
    restarts skip the scan.
- **Native HA sensors** for PV, battery, grid, load, ratings and operating mode,
  plus diagnostics showing the detected protocol, port, last successful poll
  and last error.
- **Fully standalone** — the protocol codecs are bundled inside the integration,
  so the cloud `dess_monitor` integration is not required.
- Configurable poll interval (default 10 s).

---

## Installation via HACS

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Find **DESS Monitor Local** in HACS and install it.
4. Restart Home Assistant.

Or use the badge:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OWNER&repository=home-assistant-dess-monitor-local&category=Integration)

*(Replace `OWNER` in the badge URL with your GitHub username after publishing.)*

### Manual installation

Copy `custom_components/dess_monitor_local/` into `<config>/custom_components/`
and restart HA.

---

## Configuration

**Settings → Devices & Services → Add Integration → DESS Monitor Local**

- **IP address** — defaults to `192.168.1.4`
- **Port** — `0` = auto-scan, or enter a specific port
- **Protocol / framing** — leave on Auto-detect unless auto-detection fails
- **Poll interval** — seconds (2–600)

---

## Troubleshooting

Download diagnostics from the integration card. It includes the detected
protocol/framing/port, the last transmitted and received frames in hex, and
the last poll error.

If nothing answers:

- the dongle may use a proprietary binary protocol — send us the `last_rx_hex`
  dump from diagnostics and a codec can be added;
- the vendor app may be holding the dongle's single client slot — close it;
- reserve a DHCP lease so the dongle keeps the same IP.

---

## License

[MIT](LICENSE)
