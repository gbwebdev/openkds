from typing import Callable

try:
    from escpos.printer import Usb
    from escpos import constants
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False


class PrinterConnectionError(Exception):
    pass


def get_printer(vendor_id: str, product_id: str):
    if not ESCPOS_AVAILABLE:
        raise PrinterConnectionError("python-escpos non installé")
    if not vendor_id or not product_id:
        raise PrinterConnectionError("vendor_id ou product_id manquant")
    try:
        p = Usb(int(vendor_id, 16), int(product_id, 16))
        return p
    except Exception as e:
        raise PrinterConnectionError(str(e))


def get_printer_status(printer) -> dict:
    if printer is None:
        return {"connected": False, "paper_ok": False, "error": "Imprimante non configurée"}
    try:
        if ESCPOS_AVAILABLE:
            status = printer.query_status(constants.RT_STATUS_PAPER)
            return {
                "connected": True,
                "paper_ok": not (status & 0x0C),
                "error": None
            }
        return {"connected": True, "paper_ok": True, "error": None}
    except Exception as e:
        # Some printers (PRP-250) don't support bidirectional status
        # Try to detect USB presence as fallback
        try:
            _ = printer.device
            return {"connected": True, "paper_ok": True, "error": None}
        except Exception:
            return {"connected": False, "paper_ok": False, "error": str(e)}


def print_with_status(printer, print_fn: Callable) -> dict:
    if printer is None:
        return {"ok": False, "error": "Imprimante non configurée"}

    pre_status = get_printer_status(printer)
    if not pre_status["connected"]:
        return {"ok": False, "error": "Imprimante non connectée"}

    try:
        print_fn(printer)
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def try_get_printer(vendor_id: str, product_id: str):
    """Returns (printer, error_string). printer is None on failure."""
    try:
        p = get_printer(vendor_id, product_id)
        return p, None
    except PrinterConnectionError as e:
        return None, str(e)
