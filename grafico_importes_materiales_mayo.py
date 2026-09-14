import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
csv_path = ROOT / "work" / "ventas_importes_materiales_mayo_2026.csv"
out_png = ROOT / "outputs" / "ventas_importes_materiales_mayo_2026_barras.png"
out_txt = ROOT / "outputs" / "ventas_importes_materiales_mayo_2026_resumen.txt"


def parse_float(value):
    return float(str(value).replace(",", "."))


def fmt_money(value):
    return "$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


rows = []
with csv_path.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        rows.append((row["Producto"], parse_float(row["Importe"])))

rows.sort(key=lambda item: item[1], reverse=True)
total = sum(value for _, value in rows)
max_value = max((value for _, value in rows), default=1)

width, height = 1700, 1050
img = Image.new("RGB", (width, height), "white")
draw = ImageDraw.Draw(img)

title_font = font(40, True)
subtitle_font = font(22)
label_font = font(22)
small_font = font(18)
value_font = font(20, True)

draw.text((60, 45), "Importe de ventas por material - Mayo 2026", fill="#111827", font=title_font)
draw.text((60, 95), "Materiales de construccion + gravas | Importe segun subtotal de detalle de comprobantes", fill="#374151", font=subtitle_font)
draw.text((60, 130), f"Total analizado: {fmt_money(total)}", fill="#111827", font=font(24, True))

left_label = 60
bar_left = 470
bar_top = 190
bar_width = 860
bar_height = 34
gap = 25

palette = [
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#b07aa1",
    "#9c755f",
    "#bab0ab",
    "#86bc86",
]

for idx, (name, value) in enumerate(rows):
    y = bar_top + idx * (bar_height + gap)
    pct = value / total * 100 if total else 0
    draw.text((left_label, y + 3), name, fill="#111827", font=label_font)
    draw.rounded_rectangle([bar_left, y, bar_left + bar_width, y + bar_height], radius=7, fill="#eef2f7")
    actual_width = int(bar_width * value / max_value) if max_value else 0
    draw.rounded_rectangle([bar_left, y, bar_left + actual_width, y + bar_height], radius=7, fill=palette[idx % len(palette)])
    draw.text((bar_left + bar_width + 25, y - 1), fmt_money(value), fill="#111827", font=value_font)
    draw.text((bar_left + bar_width + 225, y + 1), f"{pct:.2f}%", fill="#4b5563", font=small_font)

draw.text((60, height - 55), "Nota: no se convierte unidad porque el grafico compara importe de venta, no volumen.", fill="#6b7280", font=small_font)
img.save(out_png)

lines = [
    "IMPORTE DE VENTAS POR MATERIAL - MAYO 2026",
    "Base: Subtot de DETALLE DE COMPROVANTES",
    "",
]
for name, value in rows:
    pct = value / total * 100 if total else 0
    lines.append(f"{name:<24} {fmt_money(value):>18}   {pct:>6.2f}%")
lines += ["", f"TOTAL {fmt_money(total)}"]
out_txt.write_text("\n".join(lines), encoding="utf-8")

print(out_png)
print(out_txt)
