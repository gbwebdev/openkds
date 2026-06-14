from __future__ import annotations

import os
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, ChoiceLoader


# Directive syntax: [name] at the start of a line (one or more, in sequence).
# State directives  — change formatting for subsequent text lines:
#   [left]  [center]  [right]
#   [normal]  [big]  [huge]       (normal=1×1, big=2×2, huge=3×2)
#   [bold]  [/bold]
#   [reverse]  [/reverse]         (white-on-black via raw ESC/POS)
# Immediate directives — produce output now and don't linger:
#   [sep]   print === separator (32 chars, normal, left)
#   [sep-]  print --- separator (32 chars, normal, left)
#   [cut]   feed + cut (terminates processing)

_DIRECTIVE_RE = re.compile(r'^\[([a-zA-Z/\-]+)\]')


def _build_env() -> Environment:
    data_dir = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd()))
    loaders = []
    user_tpl = data_dir / "templates"
    if user_tpl.is_dir():
        loaders.append(FileSystemLoader(str(user_tpl)))
    pkg_tpl = Path(__file__).parent / "default_templates"
    loaders.append(FileSystemLoader(str(pkg_tpl)))
    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


_env: Environment | None = None


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = _build_env()
    return _env


_ALIGN = {"left": b"\x1b\x61\x00", "center": b"\x1b\x61\x01", "right": b"\x1b\x61\x02"}


def _fmt(printer, align: str, bold: bool, height: int, width: int) -> None:
    """Send formatting as raw ESC/POS bytes.

    Bypasses printer.set() which caps height/width at 2 in escpos v3,
    causing SetVariableError for [huge] (height=3) and silently aborting
    the print function before the cut command is ever reached.
    """
    printer._raw(_ALIGN.get(align, _ALIGN["left"]))           # ESC a n
    printer._raw(bytes([0x1b, 0x45, 1 if bold else 0]))       # ESC E n
    size_n = (max(1, height) - 1) | ((max(1, width) - 1) << 4)
    printer._raw(bytes([0x1d, 0x21, size_n]))                 # GS ! n


_FMT_NORMAL = b"\x1b\x61\x00\x1b\x45\x00\x1d\x21\x00"  # left, no bold, 1×1


def _process(printer, rendered: str) -> None:
    """Interpret rendered template text: directives + plain text lines."""
    align = "left"
    bold = False
    height = 1
    width = 1

    for raw_line in rendered.split("\n"):
        line = raw_line

        # Collect all leading directives on this line
        directives: list[str] = []
        while True:
            m = _DIRECTIVE_RE.match(line)
            if not m:
                break
            directives.append(m.group(1))
            line = line[m.end():]

        stop = False
        for d in directives:
            if d == "left":
                align = "left"
            elif d == "center":
                align = "center"
            elif d == "right":
                align = "right"
            elif d == "normal":
                align, bold, height, width = "left", False, 1, 1
            elif d == "big":
                height, width = 2, 2
            elif d == "huge":
                height, width = 3, 2
            elif d == "bold":
                bold = True
            elif d == "/bold":
                bold = False
            elif d == "reverse":
                printer._raw(b"\x1d\x42\x01")
            elif d == "/reverse":
                printer._raw(b"\x1d\x42\x00")
            elif d == "sep":
                printer._raw(_FMT_NORMAL)
                printer.text("=" * 32 + "\n")
            elif d == "sep-":
                printer._raw(_FMT_NORMAL)
                printer.text("-" * 32 + "\n")
            elif d == "cut":
                _cut(printer)
                stop = True
                break

        if stop:
            return

        if line:
            _fmt(printer, align, bold, height, width)
            printer.text(line + "\n")


def _cut(printer) -> None:
    """Feed paper and cut, then flush any write buffer."""
    printer.text("\n" * 4)
    # GS V A 0 = feed + full cut (Epson TM and most ESC/POS compatible printers).
    # Sent as raw bytes to bypass any escpos library version differences.
    printer._raw(b"\x1d\x56\x41\x00")
    # Flush Python's write buffer if the printer uses a file descriptor
    # (EscposFile / CDC ACM). Without this, the last bytes can stay in the
    # BufferedWriter buffer indefinitely on a cached long-lived connection.
    try:
        device = getattr(printer, "device", None)
        if device and hasattr(device, "flush"):
            device.flush()
    except Exception:
        pass


def render_ticket(printer, template_name: str, context: dict) -> None:
    template = _get_env().get_template(template_name)
    rendered = template.render(**context)
    _process(printer, rendered)


def print_test_ticket(printer, printer_id: str) -> None:
    _process(printer, "\n".join([
        "[center][big]TEST IMPRESSION",
        "[sep]",
        f"[center][normal]{printer_id}",
        "Fonctionnement OK",
        "[sep]",
        "[cut]",
    ]))
