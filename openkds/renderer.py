from __future__ import annotations

import os
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, ChoiceLoader


# Directive syntax: [name] inline. Directives are recognised anywhere on a line.
#
# State directives — change formatting for subsequent text:
#   [left]  [center]  [right]
#   [normal]  [big]  [huge]       (normal = 1×1, big = 2×2, huge = 3×2)
#   [bold]  [/bold]
#   [reverse]  [/reverse]         (white-on-black via raw ESC/POS)
#
# Output directives — emit something immediately:
#   [sep]   print ===== separator (32 chars, normal size, left-aligned)
#   [sep-]  print ----- separator (32 chars, normal size, left-aligned)
#   [br]    print a normal-size blank line
#   [cut]   feed + cut paper (terminates processing)
#
# Empty template lines produce blank lines in the output at the current size.

_DIRECTIVE_RE = re.compile(r'\[([a-zA-Z/\-]+)\]')


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
_FMT_NORMAL = b"\x1b\x61\x00\x1b\x45\x00\x1d\x21\x00"  # left, no bold, 1×1

# Default line width for [sep]/[sep-] at normal size.
# 48 columns matches 80mm thermal paper with Font A. For 58mm paper, set 32.
_LINE_WIDTH = 48


def _fmt(printer, align: str, bold: bool, height: int, width: int) -> None:
    """Send align/bold/size as raw ESC/POS bytes.

    Bypasses printer.set() which caps height/width at 2 in escpos v3 and would
    raise SetVariableError on [huge] (height=3), aborting the print pipeline
    before [cut] is ever reached.
    """
    printer._raw(_ALIGN.get(align, _ALIGN["left"]))           # ESC a n
    printer._raw(bytes([0x1b, 0x45, 1 if bold else 0]))       # ESC E n
    size_n = (max(1, height) - 1) | ((max(1, width) - 1) << 4)
    printer._raw(bytes([0x1d, 0x21, size_n]))                 # GS ! n


# State-only directives that never produce output by themselves.
_STATE_DIRECTIVES = {
    "left", "center", "right",
    "normal", "big", "huge",
    "bold", "/bold",
    "reverse", "/reverse",
}


def _flush(printer, buf: str, state: dict) -> None:
    """Write the accumulated text buffer with the current formatting."""
    if not buf:
        return
    _fmt(printer, state["align"], state["bold"], state["height"], state["width"])
    printer.text(buf)


def _apply_directive(printer, d: str, state: dict) -> bool:
    """Apply a directive. Returns False if processing should stop ([cut])."""
    if d == "cut":
        _cut(printer)
        return False
    if d == "sep":
        printer._raw(_FMT_NORMAL)
        printer.text("=" * _LINE_WIDTH + "\n")
    elif d == "sep-":
        printer._raw(_FMT_NORMAL)
        printer.text("-" * _LINE_WIDTH + "\n")
    elif d == "br":
        printer._raw(_FMT_NORMAL)
        printer.text("\n")
    elif d == "reverse":
        printer._raw(b"\x1d\x42\x01")
    elif d == "/reverse":
        printer._raw(b"\x1d\x42\x00")
    elif d == "left":
        state["align"] = "left"
    elif d == "center":
        state["align"] = "center"
    elif d == "right":
        state["align"] = "right"
    elif d == "normal":
        state.update(align="left", bold=False, height=1, width=1)
    elif d == "big":
        state["height"] = 2
        state["width"] = 2
    elif d == "huge":
        state["height"] = 3
        state["width"] = 2
    elif d == "bold":
        state["bold"] = True
    elif d == "/bold":
        state["bold"] = False
    return True


def _process_line(printer, line: str, state: dict) -> bool:
    """Process one rendered template line. Returns False if [cut] encountered."""
    pending = ""
    saw_output_directive = False  # sep, sep-, br — they emit their own newline
    saw_only_state = True         # true while line has had nothing but state directives

    i = 0
    while i < len(line):
        m = _DIRECTIVE_RE.match(line, i)
        if not m:
            pending += line[i]
            saw_only_state = False
            i += 1
            continue

        # A directive: flush pending text under the current formatting first
        _flush(printer, pending, state)
        pending = ""

        d = m.group(1)
        i = m.end()

        if d not in _STATE_DIRECTIVES:
            saw_only_state = False
            if d in ("sep", "sep-", "br", "cut"):
                saw_output_directive = True

        if not _apply_directive(printer, d, state):
            return False

    # End-of-line handling:
    if pending:
        # Trailing text after directives → flush with newline
        _flush(printer, pending + "\n", state)
    elif not line:
        # Empty template line → blank line on the ticket (current formatting)
        _flush(printer, "\n", state)
    elif saw_only_state:
        # Line was nothing but state changes → no newline emitted
        pass
    elif saw_output_directive:
        # sep/sep-/br already printed their own newline → no extra
        pass
    else:
        # Inline-state-only line with text consumed mid-line — terminate it
        printer.text("\n")
    return True


def _process(printer, rendered: str) -> None:
    state = {"align": "left", "bold": False, "height": 1, "width": 1}
    for raw_line in rendered.split("\n"):
        if not _process_line(printer, raw_line, state):
            return


def _cut(printer) -> None:
    """Feed paper, cut, then flush any write buffer."""
    printer._raw(b"\n\n\n\n")
    printer.cut()
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
