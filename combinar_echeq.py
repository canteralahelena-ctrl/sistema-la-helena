import argparse
import json
from itertools import combinations
from pathlib import Path
from datetime import datetime


def money(value):
    text = f"{value:,.2f}"
    return "$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_date(value):
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return text or "-"


def load_items(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    items = []
    for row in data.get("Registros", []):
        if row.get("Tipo") != "ECHEQ":
            continue
        amount = round(float(row.get("Importe") or 0), 2)
        if amount <= 0:
            continue
        item = dict(row)
        item["amount_cents"] = int(round(amount * 100))
        items.append(item)
    return items


def choose_best(items, target_cents):
    exact = None
    under = None
    over = None
    count = len(items)

    for size in range(1, count + 1):
        for indexes in combinations(range(count), size):
            total = sum(items[index]["amount_cents"] for index in indexes)
            candidate = (total, size, indexes)
            if total == target_cents:
                return candidate, under, over
            if total < target_cents:
                if under is None or total > under[0] or (total == under[0] and size < under[1]):
                    under = candidate
            else:
                if over is None or total < over[0] or (total == over[0] and size < over[1]):
                    over = candidate
    return exact, under, over


def render_option(title, subtitle, candidate, items, target_cents):
    if candidate is None:
        return ["━━━━━━━━━━━━━━", title, "Sin opción disponible."]
    total, _, indexes = candidate
    difference = total - target_cents
    if difference == 0:
        difference_text = "exacta"
    elif difference > 0:
        difference_text = f"{money(abs(difference) / 100)} por encima"
    else:
        difference_text = f"{money(abs(difference) / 100)} por debajo"
    lines = [
        "━━━━━━━━━━━━━━",
        title,
        subtitle,
        "",
        f"Total: {money(total / 100)}",
        f"Diferencia: {difference_text}",
        f"Cantidad: {len(indexes)} eCheq",
        "",
    ]
    for number, index in enumerate(indexes, start=1):
        item = items[index]
        lines.extend(
            [
                f"{number}) {item.get('Banco') or '-'} {item.get('Numero') or '-'}",
                f"   {format_date(item.get('FechaCobro'))}",
                f"   {item.get('Cliente') or '-'}",
                f"   {money(item['amount_cents'] / 100)}",
            ]
        )
    return lines


def option_sort_key(candidate, target_cents):
    if candidate is None:
        return (9, 0)
    total = candidate[0]
    difference = total - target_cents
    covers = difference >= 0
    return (0 if covers else 1, abs(difference))


def render_options(exact, under, over, items, target_cents):
    candidates = []
    if exact:
        candidates.append(("🥇 Opción recomendada", "Importe exacto", exact))
    else:
        available = [
            ("Cubre el objetivo", over),
            ("No excede el objetivo", under),
        ]
        available = [(subtitle, candidate) for subtitle, candidate in available if candidate is not None]
        available.sort(key=lambda item: option_sort_key(item[1], target_cents))
        for index, (subtitle, candidate) in enumerate(available[:2]):
            title = "🥇 Opción recomendada" if index == 0 else "🥈 Alternativa"
            candidates.append((title, subtitle, candidate))

    lines = []
    for index, (title, subtitle, candidate) in enumerate(candidates):
        if index:
            lines.append("")
        lines.extend(render_option(title, subtitle, candidate, items, target_cents))
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--target", required=True, type=float)
    args = parser.parse_args()

    items = load_items(args.data)
    target_cents = int(round(args.target * 100))
    if not items:
        print("No hay eCheq disponibles dentro del plazo solicitado.")
        return

    exact, under, over = choose_best(items, target_cents)
    print("💳 Pago con eCheq")
    print("")
    print(f"Objetivo: {money(args.target)}")
    print(f"eCheq evaluados: {len(items)}")
    print("")

    print("\n".join(render_options(exact, under, over, items, target_cents)))

    print("")
    print("ℹ️ Propuesta informativa.")
    print("No se modificó ni endosó ningún cheque.")


if __name__ == "__main__":
    main()
