ITEM_LABELS = {
    "adulte_merguez":  "Menu Adulte Merguez",
    "adulte_chipo":    "Menu Adulte Chipolatas",
    "enfant_merguez":  "Menu Enfant Merguez",
    "enfant_chipo":    "Menu Enfant Chipolatas",
    "galette_saucisse":"Galette-Saucisse",
    "barquette_frite": "Barquette Frite",
}

ASSEMBLY_ITEMS = {
    "adulte_merguez":  "Menu Adulte Merguez",
    "adulte_chipo":    "Menu Adulte Chipolatas",
    "enfant_merguez":  "Menu Enfant Merguez",
    "enfant_chipo":    "Menu Enfant Chipolatas",
    "barquette_frite": "Barquette Frite",
}


def print_client_ticket(printer, order: dict, config: dict):
    event_name = config.get("event_name", "Kermesse")

    printer.set(align='center', bold=True, height=2, width=2)
    printer.text(event_name + "\n")
    printer.set(align='center', bold=False, height=1, width=1)
    printer.text("=" * 32 + "\n")

    printer.set(align='center', bold=True, height=3, width=2)
    printer.text(f"COMMANDE #{order['number']:03d}\n")

    printer.set(align='center', bold=False, height=1, width=1)
    printer.text("=" * 32 + "\n")

    printer.set(align='left')
    for item_id, label in ITEM_LABELS.items():
        qty = order.get(item_id, 0)
        if qty > 0:
            printer.text(f"  {qty}x {label}\n")

    printer.text("=" * 32 + "\n")
    printer.set(align='center')
    printer.text("Presentez ce ticket\n")
    printer.text("a la remise de commande\n")
    printer.cut()


def print_assembly_ticket(printer, order: dict):
    frites = (order.get("adulte_merguez", 0) + order.get("adulte_chipo", 0) +
              order.get("enfant_merguez", 0) + order.get("enfant_chipo", 0) +
              order.get("barquette_frite", 0))
    merguez = 2 * order.get("adulte_merguez", 0) + order.get("enfant_merguez", 0)
    chipo   = 2 * order.get("adulte_chipo", 0)   + order.get("enfant_chipo", 0)
    boisson = (order.get("adulte_merguez", 0) + order.get("adulte_chipo", 0) +
               order.get("enfant_merguez", 0) + order.get("enfant_chipo", 0))

    printer.set(align='center', bold=True, height=2, width=2)
    printer.text("== ASSEMBLAGE ==\n")
    printer.set(align='center', bold=True, height=2, width=2)
    printer.text(f"COMMANDE #{order['number']:03d}\n")
    printer.set(align='left', bold=False, height=1, width=1)
    printer.text("=" * 32 + "\n")

    for item_id, label in ASSEMBLY_ITEMS.items():
        qty = order.get(item_id, 0)
        for _ in range(qty):
            printer.text(f"[ ] {label}\n")

    printer.text("-" * 32 + "\n")

    if frites:   printer.text(f"Frites    : {frites}\n")
    if merguez:  printer.text(f"Merguez   : {merguez}\n")
    if chipo:    printer.text(f"Chipolatas: {chipo}\n")
    if boisson:  printer.text(f"Boissons  : {boisson}\n")
    printer.text("=" * 32 + "\n")
    printer.cut()


def print_billigs_ticket(printer, order: dict):
    qty = order.get("galette_saucisse", 0)
    if qty == 0:
        return

    printer.set(align='center', bold=True, height=2, width=2)
    printer.text("\x1b\x45\x01")  # bold on
    printer.text("\x1d\x42\x01")  # reverse mode on
    printer.text("    BILLIGS    \n")
    printer.text("\x1d\x42\x00")  # reverse mode off
    printer.set(align='center', bold=True, height=2, width=2)
    printer.text(f"COMMANDE #{order['number']:03d}\n")
    printer.set(align='left', bold=False, height=1, width=1)
    printer.text("=" * 32 + "\n")

    for _ in range(qty):
        printer.text("[ ] Galette-saucisse\n")

    printer.text("=" * 32 + "\n")
    printer.cut()


def print_test_ticket(printer, printer_num: int):
    printer.set(align='center', bold=True, height=2, width=2)
    printer.text("TEST IMPRESSION\n")
    printer.set(align='center', bold=False, height=1, width=1)
    printer.text("=" * 32 + "\n")
    printer.text(f"Imprimante {printer_num}\n")
    printer.text("Fonctionnement OK\n")
    printer.text("=" * 32 + "\n")
    printer.cut()
