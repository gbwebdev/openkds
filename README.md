# OpenKDS

Open-source point-of-sale and kitchen display system for school fairs — tablet order entry, thermal ticket printing, and grill management, self-hosted on a Raspberry Pi with a built-in WiFi hotspot.

---

## Features

- **Order entry** — touch-friendly menu buttons on a tablet, real-time order summary
- **Thermal printing** — any number of printers, each assigned to one or more workshops via `menu.yaml`
- **Grill management** — sliding-window demand forecast with a 4-segment gauge per tracked component
- **Live updates** — WebSocket push to all connected tablets on every new order
- **History & stats** — full order log with reprint, per-item totals, time histogram
- **Self-contained** — runs entirely offline; built-in WiFi hotspot turns the Pi into its own network
- **Fully configurable** — menu, workshops, printers and ticket templates defined in `menu.yaml`; no code change needed to adapt to a new event layout

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLite, `python-escpos`, PyYAML, Jinja2 |
| Frontend | Vanilla JS SPA, HTML5/CSS3 (no framework, no build step) |
| Real-time | Native FastAPI WebSocket |
| Supervision | systemd |
| Network | hostapd + dnsmasq |

---

## Hardware

- Raspberry Pi 3B+ or newer (or any Linux x86 box)
- One or more USB thermal printers (tested with Epson TM series)
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
  --device /dev/ttyACM1 \
  ghcr.io/gbwebdev/openkds:latest
```

Runtime data (config, database, and optional config overrides) is persisted in the `/data` volume.
USB printer devices must be passed through with `--device`.

---

## Configuration

### Runtime settings — `config.json`

Written to the data directory on first start. All settings are also editable from the **Settings** screen in the UI.

| Key | Description |
|---|---|
| `org_name` | Organisation name displayed on customer tickets |
| `event_name` | Event name displayed on customer tickets |
| `printer_devices` | Object mapping printer ID → device path or USB ID, e.g. `{"caisse": "/dev/ttyACM0", "cuisine": "04b8:0e15"}` |
| `grill_window_minutes` | Sliding window for demand forecast (default: 20 min) |
| `grill_segment_size` | Units per gauge segment (default: 6) |
| `button_colors` | Hex color overrides per menu item ID |
| `next_order_number` | Resume counter after a break |

> Run `lsusb` with printers connected to find their USB IDs (`VVVV:PPPP`). Enter them in Settings → Printers.

### Menu & workshops — `menu.yaml`

Defines the menu items, printers, workshops and grill configuration. The package ships a working default. To customise, place a `menu.yaml` in `OPENKDS_DATA_DIR` — it takes precedence over the bundled default.

```yaml
menu:
  items:
    - id: adulte_merguez
      label: "Menu Adulte\nMerguez"
      color: "#e74c3c"
      workshops: [client, assemblage, grillade]  # which workshops handle this item
      components:
        merguez: 2
        frites: 1
        boisson: 1

printers:
  - id: caisse
    label: "Caisse (ticket client)"
  - id: cuisine
    label: "Cuisine (assemblage)"

workshops:
  - id: client
    type: ticket
    printer: caisse
    template: client.j2
  - id: grillade
    type: dashboard
    tracks: [merguez, chipo, saucisse]
```

Adding a printer or a new workshop requires only a `menu.yaml` edit — no code change.

### Ticket templates — `*.j2`

Jinja2 templates rendered as plain text. The package ships defaults for `client.j2`, `assembly.j2` and `billigs.j2`. Place custom templates in `OPENKDS_DATA_DIR/templates/` to override.

**Available directives** (on their own line or at the start of a line):

| Directive | Effect |
|---|---|
| `[left]` `[center]` `[right]` | Text alignment |
| `[normal]` `[big]` `[huge]` | Text size (1×, 2×, 3× height + 2× width) |
| `[bold]` `[/bold]` | Bold on / off |
| `[reverse]` `[/reverse]` | White-on-black printing |
| `[sep]` | Print `========` separator line |
| `[sep-]` | Print `--------` separator line |
| `[cut]` | Feed paper and cut (required at end of template) |

**Template context variables:** `order`, `config`, `workshop`, `workshop_items`, `workshop_components`, `order_components`.

> **Charset:** templates are encoded as `cp437`. Most French accented characters are supported. Maximum line width: 48 chars at normal size, 24 chars at `[big]`/`[huge]`.

Example:

```jinja2
[center][huge]COMMANDE #{{ "%03d" % order.number }}
[sep]
[left][normal]
{% for item in workshop_items %}  {{ item.qty }}x {{ item.label | replace('\n', ' ') }}
{% endfor %}[sep]
[center]Presentez ce ticket
[cut]
```

> **Note:** changing the menu or workshops requires a database reset (the schema ties orders to item IDs).

---

## Local development

No printers required to run the server locally:

```bash
pip install -e .
openkds
```

Or with auto-reload:

```bash
uvicorn openkds.main:app --reload --port 8000
```

Open `http://localhost:8000`. Orders are saved to `./openkds.db`; print operations fail gracefully when no printers are configured.

Set `OPENKDS_DATA_DIR` to control where config, database and overrides are stored.

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
openkds/
├── main.py              # FastAPI app, routes, WebSocket
├── database.py          # SQLite schema and queries
├── models.py            # Pydantic models
├── menu.py              # menu.yaml loader
├── renderer.py          # Jinja2 ticket renderer + directive interpreter
├── printers.py          # USB/serial printer abstraction
├── grill.py             # Demand and gauge logic
├── config.py            # config.json read/write
├── defaults/
│   └── menu.yaml        # Default menu, printers, workshops, grill config
├── default_templates/
│   ├── client.j2        # Customer receipt
│   ├── assembly.j2      # Kitchen assembly sheet
│   └── billigs.j2       # Billigs (galette-saucisse) stand
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```
