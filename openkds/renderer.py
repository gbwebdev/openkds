from __future__ import annotations

import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, ChoiceLoader

# ESC/POS command constants available in all templates.
# Values are Python strings that encode to the correct bytes via latin-1.
ESCPOS = {
    # Reverse video
    "REVERSE_ON":  "\x1d\x42\x01",
    "REVERSE_OFF": "\x1d\x42\x00",
    # Paper cut — GS V 65 0 = feed + full cut (EPSON TM compatible)
    "CUT":         "\n\n\n\n\x1d\x56\x41\x00",
    # Alignment
    "CENTER":      "\x1b\x61\x01",
    "LEFT":        "\x1b\x61\x00",
    "RIGHT":       "\x1b\x61\x02",
    # Bold
    "BOLD_ON":     "\x1b\x45\x01",
    "BOLD_OFF":    "\x1b\x45\x00",
    # Text size: GS ! n  (bits 0-2 = height-1, bits 4-6 = width-1)
    "NORMAL":      "\x1d\x21\x00",   # 1×1
    "SIZE_2H":     "\x1d\x21\x01",   # 2× height
    "SIZE_2W":     "\x1d\x21\x10",   # 2× width
    "SIZE_2HW":    "\x1d\x21\x11",   # 2× height + 2× width
    "SIZE_3H2W":   "\x1d\x21\x12",   # 3× height + 2× width
}


def _build_env() -> Environment:
    data_dir = Path(os.environ.get("OPENKDS_DATA_DIR", Path.cwd()))
    loaders = []
    user_tpl = data_dir / "templates"
    if user_tpl.is_dir():
        loaders.append(FileSystemLoader(str(user_tpl)))
    pkg_tpl = Path(__file__).parent / "default_templates"
    loaders.append(FileSystemLoader(str(pkg_tpl)))
    env = Environment(
        loader=ChoiceLoader(loaders),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    env.globals.update(ESCPOS)
    return env


_env: Environment | None = None


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = _build_env()
    return _env


def render_ticket(printer, template_name: str, context: dict) -> None:
    """Render a Jinja2 template and send raw bytes to the printer."""
    template = _get_env().get_template(template_name)
    rendered = template.render(**context)
    printer._raw(rendered.encode("cp437", errors="replace"))


def print_test_ticket(printer, printer_num: int) -> None:
    rendered = (
        f"{ESCPOS['CENTER']}{ESCPOS['BOLD_ON']}{ESCPOS['SIZE_2HW']}"
        f"TEST IMPRESSION\n"
        f"{ESCPOS['NORMAL']}{ESCPOS['BOLD_OFF']}"
        f"{'=' * 32}\n"
        f"{ESCPOS['CENTER']}Imprimante {printer_num}\n"
        f"Fonctionnement OK\n"
        f"{'=' * 32}"
        f"{ESCPOS['CUT']}"
    )
    printer._raw(rendered.encode("cp437", errors="replace"))
