# Bazaar KDS

Local web-based point-of-sale system for school fairs — tablet order entry, thermal ticket printing, and grill management, self-hosted on a Raspberry Pi with a built-in WiFi hotspot.

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
| Backend | Python 3.11+, FastAPI, SQLite (`sqlite3`), `python-escpos` |
| Frontend | Vanilla JS SPA, HTML5/CSS3 (no framework, no build step) |
| Real-time | Native FastAPI WebSocket |
| Supervision | systemd |
| Network | hostapd + dnsmasq |

---

## Hardware

- Raspberry Pi 3B+ or newer (or any Linux x86 box)
- Two USB thermal printers (tested with Epson TM series; PRP-250 notes in specs)
- A tablet or any device with a browser

---

## Installation

Run once as root on the target machine:

```bash
sudo bash install.sh
```

The script:
1. Installs system dependencies (`python3`, `hostapd`, `dnsmasq`, `libusb`)
2. Creates a `bazaar` system user
3. Deploys sources to `/opt/bazaar` and builds a Python virtualenv
4. Installs udev rules so the `bazaar` user can access USB printers
5. Configures the WiFi hotspot (hostapd + dnsmasq, static IP `192.168.50.1`)
6. Registers and enables two systemd services (`bazaar-hotspot`, `bazaar`)
7. Starts everything immediately — no reboot required

After the next boot, everything comes up automatically.

**Default WiFi credentials** (override via environment variables):

```bash
sudo SSID="MySSID" PASSPHRASE="mypassword" WIFI_IFACE="wlan1" bash install.sh
```

| Parameter | Default |
|---|---|
| SSID | `Bazaar2026` |
| Passphrase | `bazaar2026` |
| Interface | `wlan0` |
| Server IP | `192.168.50.1` |

**Tablet URL:** `http://192.168.50.1:8000`

---

## Configuration

`config.json` is written on first start and persists user settings:

| Key | Description |
|---|---|
| `event_name` | Displayed on customer tickets |
| `printer1_vendor_id` / `printer1_product_id` | USB IDs for the client-ticket printer (`lsusb` to find them) |
| `printer2_vendor_id` / `printer2_product_id` | USB IDs for the assembly printer |
| `grill_window_minutes` | Sliding window for demand forecast (default: 20 min) |
| `grill_segment_size` | Units of meat per gauge segment (default: 6) |
| `button_colors` | Hex color per menu item |
| `next_order_number` | Resume counter after a break |

All settings are also editable from the **Settings** screen in the UI.

> Before the event, run `lsusb` with printers connected to confirm `vendor_id` and `product_id`. Enter them in Settings → Printers.

---

## Local development

No printers required to run the server locally:

```bash
cd bazaar
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000`. Orders are saved to `bazaar.db`; print operations fail gracefully when no printers are configured.

---

## Useful commands

```bash
journalctl -u bazaar -f        # live application logs
systemctl status bazaar         # service status
systemctl restart bazaar        # restart after a config change
```

---

## Project structure

```
bazaar/
├── backend/
│   ├── main.py        # FastAPI app, routes, WebSocket
│   ├── database.py    # SQLite init and queries
│   ├── models.py      # Pydantic models
│   ├── printers.py    # USB printer management
│   ├── tickets.py     # ESC/POS ticket content
│   ├── grill.py       # Grill demand and gauge logic
│   └── config.py      # config.json read/write
├── frontend/
│   ├── index.html     # Single-page app shell
│   ├── style.css      # Dark theme, touch-friendly
│   └── app.js         # Full frontend logic
├── config.json        # User configuration (persisted)
├── install.sh         # One-shot setup script
├── bazaar.service     # systemd unit (reference)
└── requirements.txt
```
