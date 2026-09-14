import tempfile
import unittest
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generar_estado_pdf import TEMPLATE_FILE, build_pdf


def make_data(count):
    movimientos = []
    saldo = 0
    for index in range(count):
        debito = 1000 + index
        credito = 0 if index % 4 else 250
        saldo += debito - credito
        movimientos.append(
            {
                "Fecha": f"{(index % 28) + 1:02d}/08/2026",
                "Concepto": "FACTURA" if debito else "RECIBO",
                "Numero": f"A-{index + 1:08d}",
                "Debito": debito,
                "Credito": credito,
                "Saldo": saldo,
            }
        )
    return {
        "Cliente": {"IdCLIENTE": 1, "RazonSocial": "CLIENTE DE PRUEBA"},
        "Desde": "2026-08-01",
        "Hasta": "2026-08-31",
        "SaldoAnterior": 0,
        "SaldoFinal": saldo,
        "Movimientos": movimientos,
    }


class EstadoPdfVisualTests(unittest.TestCase):
    def extract_text(self, pdf_path):
        reader = PdfReader(str(pdf_path))
        return reader, "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_single_movement_uses_dynamic_extract_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "estado_un_movimiento.pdf"
            build_pdf(make_data(1), pdf_path, template_path=TEMPLATE_FILE)

            reader, text = self.extract_text(pdf_path)

        self.assertEqual(len(reader.pages), 1)
        media_box = reader.pages[0].mediabox
        self.assertAlmostEqual(float(media_box.width), 595.28, delta=1)
        self.assertAlmostEqual(float(media_box.height), 841.89, delta=1)
        self.assertGreater(float(media_box.height), float(media_box.width))
        self.assertIn("EXTRACTO DE CUENTA", text)
        self.assertIn("CLIENTE DE PRUEBA", text)
        self.assertIn("FECHA", text)
        self.assertIn("IMPORTE DEBITO", text)
        self.assertIn("IMPORTE CREDITO", text)
        self.assertIn("TOTAL:", text)
        self.assertEqual(text.count("TOTAL:"), 1)
        self.assertNotIn("SALDO\nTOTAL:", text)

    def test_multipage_repeats_table_header_and_total_only_at_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "estado_multipagina.pdf"
            build_pdf(make_data(95), pdf_path, template_path=TEMPLATE_FILE)

            reader, text = self.extract_text(pdf_path)

        self.assertGreater(len(reader.pages), 1)
        self.assertGreaterEqual(text.count("IMPORTE DEBITO"), len(reader.pages))
        self.assertEqual(text.count("TOTAL:"), 1)


if __name__ == "__main__":
    unittest.main()
