import os
from typing import Callable

try:
    from escpos.printer import File as EscposFile
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False


class PrinterConnectionError(Exception):
    pass


def get_printer(device_path: str):
    """Connect to a printer via its device path (e.g. /dev/ttyACM0)."""
    if not device_path:
        raise PrinterConnectionError("Chemin du périphérique non configuré")
    if not ESCPOS_AVAILABLE:
        raise PrinterConnectionError("python-escpos non installé")
    if not os.path.exists(device_path):
        raise PrinterConnectionError(f"Périphérique {device_path} introuvable")
    try:
        return EscposFile(device_path)
    except Exception as e:
        raise PrinterConnectionError(str(e))


def get_printer_status(printer) -> dict:
    if printer is None:
        return {"connected": False, "paper_ok": False, "error": "Imprimante non configurée"}
    # CDC ACM printers don't support bidirectional status queries —
    # checking device file existence is the best we can do.
    try:
        dev = getattr(printer, 'device', None)
        if dev and hasattr(dev, 'name'):
            exists = os.path.exists(dev.name)
            return {"connected": exists, "paper_ok": exists, "error": None if exists else "Périphérique déconnecté"}
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


def try_get_printer(device_path: str):
    """Returns (printer, error_string). printer is None on failure."""
    try:
        return get_printer(device_path), None
    except PrinterConnectionError as e:
        return None, str(e)
