# OpenKDS

Open-source point-of-sale and kitchen display system for school fairs — tablet order entry, thermal ticket printing, and grill management, self-hosted on a Raspberry Pi with a built-in WiFi hotspot.

---

## Features

- **Order entry** — touch-friendly menu buttons on a tablet, real-time order summary
- **Dual thermal printing** — customer ticket (printer 1) + assembly + billigs tickets (printer 2) via ESC/POS over USB
- **Grill management** — sliding-window demand forecast with a 4-segment gauge per meat type, stock declarations
- **Live updates** — WebSocket push to all connected tablets on every new order
- **History & stats** — full order log with reprint, per-item totals, time histogram
- **Self-contained** — runs entirely offline; built-in WiFi hotspot turns the Pi into its own network

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLite, `python-escpos` |
| Frontend | Vanilla JS SPA, HTML5/CSS3 (no framework, no build step) |
| Real-time | Native FastAPI WebSocket |
| Supervision | systemd |
| Network | hostapd + dnsmasq |

---

## Hardware

- Raspberry Pi 3B+ or newer (or any Linux x86 box)
- Two USB thermal printers (tested with Epson TM series)
- A tablet or any device with a browser

---

## Installation

### Option 1 — Script (Raspberry Pi / bare metal)

Run once as root on the target machine:

```bash
sudo bash install.sh
```

The script:
1. Installs system dependencies (`python3`, `hostapd`, `dnsmasq`, `libusb`)
2. Creates an `openkds` system user
3. Deploys the package to `/opt/openkds` and installs it in a Python virtualenv
4. Stores runtime data (config, database) in `/opt/openkds/data`
5. Installs udev rules so the `openkds` user can access USB printers
6. Configures the WiFi hotspot (hostapd + dnsmasq, static IP `192.168.50.1`)
7. Registers and enables two systemd services (`openkds-hotspot`, `openkds`)
8. Starts everything immediately — no reboot required

After the next boot, everything comes up automatically.

**Default WiFi credentials** (override via environment variables):

```bash
sudo SSID="MySSID" PASSPHRASE="mypassword" WIFI_IFACE="wlan1" bash install.sh
```

| Parameter | Default |
|---|---|
| SSID | `Bazaar2026` |
| Passphrase | `bazaar2026` |
| Interface | auto-detected |
| Server IP | `192.168.50.1` |

**Tablet URL:** `http://192.168.50.1:8000`

### Option 2 — Docker

```bash
docker run -d \
  --name openkds \
  -p 8000:8000 \
  -v ./data:/data \
  --device /dev/ttyACM0 \
  ghcr.io/gbwebdev/openkds:latest
```

Runtime data (config and database) is persisted in the `/data` volume.
USB printer devices must be passed through with `--device`.

---

## Configuration

`config.json` is written to the data directory on first start and persists user settings:

| Key | Description |
|---|---|
| `org_name` | Organisation name displayed on customer tickets |
| `event_name` | Event name displayed on customer tickets |
| `printer1_device` | Device path (`/dev/ttyACM0`) or USB ID (`04b8:0e15`) for the client-ticket printer |
| `printer2_device` | Device path or USB ID for the assembly printer |
| `grill_window_minutes` | Sliding window for demand forecast (default: 20 min) |
| `grill_segment_size` | Units of meat per gauge segment (default: 6) |
| `button_colors` | Hex color per menu item |
| `next_order_number` | Resume counter after a break |

All settings are also editable from the **Settings** screen in the UI.

> Run `lsusb` with printers connected to find their USB IDs (`VVVV:PPPP`). Enter them in Settings → Printers.

---

## Local development

No printers required to run the server locally:

```bash
pip install -e ".[dev]"   # or: pip install -e .
openkds
```

Or with auto-reload:

```bash
uvicorn openkds.main:app --reload --port 8000
```

Open `http://localhost:8000`. Orders are saved to `./openkds.db`; print operations fail gracefully when no printers are configured.

Set `OPENKDS_DATA_DIR` to control where config and database are stored.

---

## Useful commands

```bash
journalctl -u openkds -f        # live application logs
systemctl status openkds        # service status
systemctl restart openkds       # restart after a config change
```

---

## Project structure

```
bazaar/
├── openkds/
│   ├── main.py        # FastAPI app, routes, WebSocket
│   ├── database.py    # SQLite init and queries
│   ├── models.py      # Pydantic models
│   ├── printers.py    # USB printer management
│   ├── tickets.py     # ESC/POS ticket content
│   ├── grill.py       # Grill demand and gauge logic
│   ├── config.py      # config.json read/write
│   └── frontend/      # Static files bundled with the package
│       ├── index.html
│       ├── style.css
│       └── app.js
├── pyproject.toml     # Package definition + entry point
├── Dockerfile
├── install.sh         # One-shot bare-metal setup script
└── openkds.service    # systemd unit (reference)
```
