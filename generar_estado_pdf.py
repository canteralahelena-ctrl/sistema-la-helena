import argparse
import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle


TEXTO = colors.HexColor("#0F1720")
GRIS_TABLA = colors.HexColor("#EFEFEF")
GRIS_LINEA = colors.HexColor("#202020")
BLANCO_SUAVE = colors.HexColor("#FFFFFF")

TEMPLATE_FILE = Path(__file__).resolve().parent / "assets" / "estado_cuenta_fondo_aprobado.png"
HEADER_CROP = (0, 0, 1537, 220)
QUARRY_CROP = (0, 620, 1537, 934)
FOOTER_CROP = (0, 930, 1537, 1023)


def money(value):
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    entero = int(math.floor(value + 0.0001))
    dec = int(round((value - entero) * 100))
    if dec == 100:
        entero += 1
        dec = 0
    parts = []
    s = str(entero)
    while s:
        parts.append(s[-3:])
        s = s[:-3]
    return f"{sign}{'.'.join(reversed(parts))},{dec:02d}"


@lru_cache(maxsize=8)
def template_crop(template_path, crop_box):
    image = Image.open(template_path).convert("RGB")
    return ImageReader(image.crop(crop_box))


def draw_fitting_text(canvas, text, x, y, max_width, font_name, font_size, min_size=7):
    text = str(text or "")
    size = font_size
    while size > min_size and canvas.stringWidth(text, font_name, size) > max_width:
        size -= 0.5
    canvas.setFont(font_name, size)
    if canvas.stringWidth(text, font_name, size) <= max_width:
        canvas.drawString(x, y, text)
        return
    ellipsis = "..."
    available = max_width - canvas.stringWidth(ellipsis, font_name, size)
    trimmed = text
    while trimmed and canvas.stringWidth(trimmed, font_name, size) > available:
        trimmed = trimmed[:-1]
    canvas.drawString(x, y, trimmed.rstrip() + ellipsis)


def draw_image_crop(canvas, template_path, crop_box, x, y, width, height):
    canvas.drawImage(
        template_crop(str(template_path), crop_box),
        x,
        y,
        width=width,
        height=height,
        preserveAspectRatio=False,
        mask="auto",
    )


def draw_template(canvas, template_path):
    width, height = A4
    source_w = 1537
    header_h = (HEADER_CROP[3] - HEADER_CROP[1]) / source_w * width
    footer_h = (FOOTER_CROP[3] - FOOTER_CROP[1]) / source_w * width
    quarry_h = (QUARRY_CROP[3] - QUARRY_CROP[1]) / source_w * width

    draw_image_crop(canvas, template_path, HEADER_CROP, 0, height - header_h, width, header_h)
    draw_image_crop(canvas, template_path, QUARRY_CROP, 0, footer_h, width, quarry_h)
    draw_image_crop(canvas, template_path, FOOTER_CROP, 0, 0, width, footer_h)


def draw_header(canvas, doc, data, template_path):
    width, height = A4
    canvas.saveState()
    draw_template(canvas, template_path)

    canvas.setFillColor(TEXTO)
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(width - 18 * mm, height - 47 * mm, date.today().strftime("%d/%m/%Y"))

    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(18 * mm, height - 67 * mm, "EXTRACTO DE CUENTA:")
    cliente = data["Cliente"]["RazonSocial"]
    draw_fitting_text(canvas, cliente, 18 * mm, height - 79 * mm, width - 36 * mm, "Helvetica-Bold", 13)
    canvas.restoreState()


def build_pdf(data, output, logo_path=None, background_path=None, template_path=None):
    del logo_path, background_path
    template_path = Path(template_path or TEMPLATE_FILE)
    if not template_path.exists():
        raise FileNotFoundError(f"No se encontro la plantilla aprobada: {template_path}")

    detail_style = ParagraphStyle(
        "DetalleEstadoCuenta",
        fontName="Helvetica",
        fontSize=8.2,
        leading=10,
        textColor=TEXTO,
        wordWrap="CJK",
    )
    total_label_style = ParagraphStyle(
        "TotalEstadoCuenta",
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11,
        textColor=TEXTO,
        alignment=2,
    )

    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=91 * mm,
        bottomMargin=72 * mm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([
        PageTemplate(
            id="estado",
            frames=[frame],
            onPage=lambda c, d: draw_header(c, d, data, template_path),
        )
    ])

    rows = [["FECHA", "DETALLE", "IMPORTE DEBITO", "IMPORTE CREDITO", "SALDO"]]
    for item in data["Movimientos"]:
        if (
            item["Concepto"] == "SALDO"
            and not item["Debito"]
            and not item["Credito"]
            and not item["Saldo"]
        ):
            continue
        detalle = item["Concepto"]
        if item["Numero"]:
            detalle = f"{item['Concepto']} {item['Numero']}"
        rows.append([
            item["Fecha"],
            Paragraph(str(detalle), detail_style),
            "" if not item["Debito"] else money(item["Debito"]),
            "" if not item["Credito"] else money(item["Credito"]),
            money(item["Saldo"]),
        ])
    rows.append(["", "", "", Paragraph("TOTAL:", total_label_style), money(data["SaldoFinal"])])

    table = Table(rows, colWidths=[23 * mm, 66 * mm, 30 * mm, 33 * mm, 22 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.2),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (3, -1), (-1, -1), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXTO),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, 0), GRIS_TABLA),
        ("BACKGROUND", (0, 1), (-1, -1), BLANCO_SUAVE),
        ("GRID", (0, 0), (-1, -1), 0.7, GRIS_LINEA),
        ("LINEABOVE", (0, -1), (-1, -1), 0.9, GRIS_LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    doc.build([table])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--logo", default=None)
    parser.add_argument("--background", default=None)
    parser.add_argument("--template", default=None)
    args = parser.parse_args()

    data_path = Path(args.data)
    output = Path(args.out)
    data = json.loads(data_path.read_text(encoding="utf-8-sig"))
    build_pdf(data, output, args.logo, args.background, args.template)


if __name__ == "__main__":
    main()
