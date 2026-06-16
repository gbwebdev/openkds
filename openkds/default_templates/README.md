# Ticket templates

Templates are [Jinja2](https://jinja.palletsprojects.com/) files rendered as plain text.
The renderer interprets simple `[directive]` tags to control ESC/POS formatting,
then calls the printer's high-level API (`set()`, `text()`, `cut()`) — no raw byte knowledge required.

## How templates are loaded

1. The renderer looks for the template in **`OPENKDS_DATA_DIR/templates/`** first.
2. If not found there, it falls back to the **bundled defaults** in this directory.

To override a default template, copy it to `OPENKDS_DATA_DIR/templates/` and edit it.
To create a template for a new workshop, add the file there and reference it in `menu.yaml`:

```yaml
workshops:
  - id: myworkshop
    type: ticket
    printer: caisse
    template: myworkshop.j2   # loaded from OPENKDS_DATA_DIR/templates/myworkshop.j2
```

## Directives

Directives can appear **anywhere on a line** — at the start, between text, or at the end. They are recognised inline.

```jinja2
[reverse][center]TITLE[/reverse]   {# all three directives apply inline, TITLE is reversed #}
```

### Alignment

| Directive | Effect |
|-----------|--------|
| `[left]` | Left-align subsequent text (default) |
| `[center]` | Center-align subsequent text |
| `[right]` | Right-align subsequent text |

### Text size

| Directive | Height | Width | Chars/line |
|-----------|--------|-------|------------|
| `[normal]` | 1× | 1× | ~48 |
| `[big]` | 2× | 2× | ~24 |
| `[huge]` | 3× | 2× | ~16 |

`[normal]` also resets bold.

### Style

| Directive | Effect |
|-----------|--------|
| `[bold]` | Bold on |
| `[/bold]` | Bold off |
| `[reverse]` | White text on black background |
| `[/reverse]` | Back to normal background |

### Output

| Directive | Effect |
|-----------|--------|
| `[sep]` | Print a full-width separator made of `=` (48 chars, normal size, left) |
| `[sep-]` | Print a full-width separator made of `-` (48 chars, normal size, left) |
| `[br]` | Print a normal-size blank line |
| `[cut]` | Feed paper and cut — **required at the end of every template** |

### Blank lines

An **empty line in the template prints a blank line on the ticket** at the current text size. Use `[br]` for a normal-size blank line regardless of current state (useful after `[huge]` to avoid a giant gap).

```jinja2
Line 1

Line 3 (preceded by a blank line at current size)

[normal][br]
Line 4 (small fixed-size gap above)
```

## Charset and line width

Templates are encoded as **cp437** before being sent to the printer.
Common French characters (`é è à ù â ê î ô û ç`) are supported.

| Size | Max characters per line |
|------|------------------------|
| `[normal]` | ~48 |
| `[big]` | ~24 |
| `[huge]` | ~16 |

Exact width depends on your printer model (58mm vs 80mm paper roll). The default line width is **48 columns** (80mm thermal paper with Font A). If you use 58mm paper, override the templates and use 32 columns instead.

## Jinja2 context

Every template receives the following variables:

| Variable | Type | Description |
|----------|------|-------------|
| `order.number` | int | Sequential order number |
| `order.created_at` | str | ISO 8601 timestamp |
| `order.items` | dict | `{item_id: qty}` for the full order |
| `config.org_name` | str | Organisation name (from settings) |
| `config.event_name` | str | Event name (from settings) |
| `workshop` | dict | The workshop definition from `menu.yaml` |
| `workshop_items` | list | Items in this order that belong to this workshop: `[{id, label, qty, components}]` |
| `workshop_components` | dict | Component totals from workshop items only: `{component: total}` |
| `order_components` | dict | Component totals from all items in the order |

## Example

```jinja2
{# my_ticket.j2 — custom receipt #}
[center][big]{{ config.event_name or 'My Event' }}
[sep]
[center][huge]#{{ "%03d" % order.number }}
[sep]
[left][normal]
{% for item in workshop_items %}  {{ item.qty }}x {{ item.label | replace('\n', ' ') }}
{% endfor %}[sep]
{% if workshop_components.get('boisson', 0) %}[center]Boissons : {{ workshop_components['boisson'] }}
{% endif %}[cut]
```

## Tips

- State directives (`[center]`, `[big]`, etc.) persist until changed — you don't need to repeat them on every line.
- A line containing only state directives produces no newline; it just changes the formatting for what follows.
- `[sep]`, `[sep-]` and `[br]` always print at normal size and left alignment, regardless of the current state.
- Use `{# ... #}` for Jinja2 comments — they produce no output.
- `[reverse]` blocks must be closed with `[/reverse]` before `[cut]`.
