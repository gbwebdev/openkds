import os
import re
from typing import Callable

try:
    from escpos.printer import File as EscposFile, Usb as EscposUsb
    from escpos import constants
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False

# Matches "04b8:0e15" style USB IDs
_USB_ID_RE = re.compile(r'^([0-9a-fA-F]{4}):([0-9a-fA-F]{4})$')


class PrinterConnectionError(Exception):
    pass


def get_printer(device: str):
    """
    Connect to a printer. `device` is either:
      - a path  : /dev/ttyACM0  → File printer (CDC ACM serial)
      - USB IDs : 04b8:0e15     → Usb printer  (USB bulk)
    """
    if not device:
        raise PrinterConnectionError("Périphérique non configuré")
    if not ESCPOS_AVAILABLE:
        raise PrinterConnectionError("python-escpos non installé")

    m = _USB_ID_RE.match(device)
    if m:
        # USB bulk mode
        vendor_id, product_id = int(m.group(1), 16), int(m.group(2), 16)
        try:
            return EscposUsb(vendor_id, product_id)
        except Exception as e:
            raise PrinterConnectionError(str(e))
    else:
        # File / CDC ACM mode
        if not os.path.exists(device):
            raise PrinterConnectionError(f"Périphérique {device} introuvable")
        try:
            return EscposFile(device)
        except Exception as e:
            raise PrinterConnectionError(str(e))


def get_printer_status(printer) -> dict:
    if printer is None:
        return {"connected": False, "paper_ok": False, "error": "Imprimante non configurée"}
    try:
        # USB bulk printers support bidirectional status
        if isinstance(printer, EscposUsb):
            status = printer.query_status(constants.RT_STATUS_PAPER)
            return {"connected": True, "paper_ok": not (status & 0x0C), "error": None}
    except Exception:
        pass
    # CDC ACM: check device file existence
    try:
        dev = getattr(printer, 'device', None)
        if dev and hasattr(dev, 'name'):
            exists = os.path.exists(dev.name)
            return {"connected": exists, "paper_ok": exists,
                    "error": None if exists else "Périphérique déconnecté"}
        return {"connected": True, "paper_ok": True, "error": None}
    except Exception as e:
        return {"connected": False, "paper_ok": False, "error": str(e)}


def print_with_status(printer, print_fn: Callable) -> dict:
    if printer is None:
        return {"ok": False, "error": "Imprimante non configurée"}
    try:
        print_fn(printer)
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def try_get_printer(device: str):
    """Returns (printer, error_string). printer is None on failure."""
    try:
        return get_printer(device), None
    except PrinterConnectionError as e:
        return None, str(e)
