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


def _process(printer, rendered: str) -> None:
    """Interpret rendered template text: directives + plain text lines."""
    align = "left"
    bold = False
    height = 1
    width = 1

    def apply():
        printer.set(align=align, bold=bold, height=height, width=width)

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
                height, width, bold = 1, 1, False
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
                printer.set(align="left", bold=False, height=1, width=1)
                printer.text("=" * 32 + "\n")
            elif d == "sep-":
                printer.set(align="left", bold=False, height=1, width=1)
                printer.text("-" * 32 + "\n")
            elif d == "cut":
                printer.cut()
                stop = True
                break

        if stop:
            return

        if line:
            apply()
            printer.text(line + "\n")


def render_ticket(printer, template_name: str, context: dict) -> None:
    template = _get_env().get_template(template_name)
    rendered = template.render(**context)
    _process(printer, rendered)


def print_test_ticket(printer, printer_num: int) -> None:
    _process(printer, "\n".join([
        "[center][big]TEST IMPRESSION",
        "[sep]",
        f"[center][normal]Imprimante {printer_num}",
        "Fonctionnement OK",
        "[sep]",
        "[cut]",
    ]))
