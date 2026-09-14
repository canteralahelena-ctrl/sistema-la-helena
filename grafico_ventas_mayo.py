import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
csv_path = ROOT / "work" / "ventas_productos_mayo_2026.csv"
out_png = ROOT / "outputs" / "ventas_productos_mayo_2026_torta.png"
out_txt = ROOT / "outputs" / "ventas_productos_mayo_2026_resumen.txt"

expected = [
    "Arena zarandeada",
    "Arena bruta",
    "Granza 5/8",
    "Granza 3/8",
    "Piedra 1-3",
    "Piedra bola",
    "Arena fina",
    "Arena fina Parana",
]

colors = [
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#b07aa1",
    "#9c755f",
]


def parse_float(value):
    return float(str(value).replace(",", "."))


def fmt(value):
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


values = {name: 0.0 for name in expected}
with csv_path.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        values[row["Producto"]] = parse_float(row["M3"])

nonzero = [(k, v) for k, v in values.items() if v > 0]
nonzero.sort(key=lambda item: item[1], reverse=True)
total = sum(v for _, v in nonzero)

img = Image.new("RGB", (1500, 950), "white")
draw = ImageDraw.Draw(img)
title_font = font(38, True)
subtitle_font = font(22)
label_font = font(21)
small_font = font(18)

draw.text((60, 45), "Ventas por producto - Mayo 2026", fill="#111827", font=title_font)
draw.text((60, 92), "Unidad normalizada: m3  |  Equivalencia aplicada: 1 m3 = 1,5 TN", fill="#374151", font=subtitle_font)

cx, cy, r = 430, 500, 300
bbox = [cx - r, cy - r, cx + r, cy + r]
start = -90.0
for idx, (name, value) in enumerate(nonzero):
    angle = 360.0 * value / total if total else 0
    draw.pieslice(bbox, start=start, end=start + angle, fill=colors[idx % len(colors)], outline="white", width=3)
    if angle >= 14:
        mid = math.radians(start + angle / 2)
        tx = cx + math.cos(mid) * r * 0.62
        ty = cy + math.sin(mid) * r * 0.62
        pct = value / total * 100
        text = f"{pct:.1f}%"
        tw = draw.textlength(text, font=label_font)
        draw.text((tx - tw / 2, ty - 12), text, fill="white", font=label_font)
    start += angle

legend_x = 850
legend_y = 220
draw.text((legend_x, legend_y - 55), "Producto", fill="#111827", font=font(26, True))
for idx, (name, value) in enumerate(nonzero):
    y = legend_y + idx * 58
    draw.rounded_rectangle([legend_x, y, legend_x + 34, y + 34], radius=5, fill=colors[idx % len(colors)])
    pct = value / total * 100 if total else 0
    draw.text((legend_x + 52, y - 2), name, fill="#111827", font=label_font)
    draw.text((legend_x + 52, y + 25), f"{fmt(value)} m3  ({pct:.2f}%)", fill="#4b5563", font=small_font)

zero_items = [name for name, value in values.items() if value == 0]
if zero_items:
    draw.text((60, 875), "Sin ventas en mayo: " + ", ".join(zero_items), fill="#6b7280", font=small_font)

img.save(out_png)

lines = [
    "VENTAS POR PRODUCTO - MAYO 2026",
    "Unidad normalizada: m3",
    "Equivalencia: 1 m3 = 1,5 TN",
    "",
]
for name, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
    pct = (value / total * 100) if total else 0
    lines.append(f"{name:<22} {fmt(value):>12} m3   {pct:>6.2f}%")
lines += ["", f"TOTAL {fmt(total)} m3"]
out_txt.write_text("\n".join(lines), encoding="utf-8")

print(out_png)
print(out_txt)
