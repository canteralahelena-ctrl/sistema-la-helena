import tempfile
import unittest
from pathlib import Path

from helena_core.application.contracts import Request
from helena_core.business.clientes.facturas_pdf import (
    MODE_BY_NUMBER,
    MODE_BY_PERIOD,
    MODE_LATEST,
    MODE_SINCE_LAST_PAYMENT,
    generar_facturas_pdf,
)


class FakeAdapter:
    def __init__(self, result=None, *, raises=None):
        self.result = result or {}
        self.raises = raises
        self.calls = []

    def generar_facturas_pdf(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        defaults = {
            "success": True,
            "returncode": 0,
            "stdout": "{}",
            "stderr": "",
            "timeout": 240,
            "timed_out": False,
            "payload": {},
            "file_path": "",
            "request_signature": kwargs,
        }
        defaults.update(self.result)
        return defaults


class FacturasPdfServiceTests(unittest.TestCase):
    def request(self, modo, **parameters):
        return Request(capability="clientes.facturas_pdf", parameters={"modo": modo, **parameters})

    def make_file(self, directory, name, content=b"contenido"):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(content)
        return path

    def success_payload(self, path, *, total=1, found=1, missing=0, caption="Documento"):
        return {
            "Estado": "OK",
            "Archivo": str(path),
            "Caption": caption,
            "TotalComprobantes": total,
            "Encontrados": found,
            "Faltantes": missing,
        }

    def test_by_number_valid_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "FTA00001_00000001.pdf", b"%PDF")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_BY_NUMBER, tipo="FTS A", numero="1-1"),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["file_type"], "pdf")
        self.assertEqual(adapter.calls[0]["numero"], "1-1")

    def test_by_number_requires_number(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_BY_NUMBER, numero=""), adapter=adapter, outputs_directory=Path("unused")
        )
        self.assertEqual(result.error.code, "numero_requerido")
        self.assertEqual(adapter.calls, [])

    def test_by_number_rejects_path_like_number(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_BY_NUMBER, numero="../123"), adapter=adapter, outputs_directory=Path("unused")
        )
        self.assertEqual(result.error.code, "numero_invalido")

    def test_period_single_document_is_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura_cliente.pdf", b"%PDF")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(
                    MODE_BY_PERIOD,
                    cliente="CLIENTE",
                    desde="2026-07-01",
                    hasta="2026-07-02",
                ),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["file_type"], "pdf")

    def test_period_multiple_documents_is_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            zip_path = self.make_file(outputs, "facturas_cliente.zip", b"PK-test")
            payload = self.success_payload(zip_path, total=3, found=3)
            adapter = FakeAdapter({"payload": payload, "file_path": str(zip_path)})
            result = generar_facturas_pdf(
                self.request(
                    MODE_BY_PERIOD,
                    cliente="CLIENTE",
                    desde="2026-07-01",
                    hasta="2026-07-02",
                ),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["file_type"], "zip")

    def test_same_date_range_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(
                    MODE_BY_PERIOD,
                    cliente="CLIENTE",
                    desde="2026-07-01",
                    hasta="2026-07-01",
                ),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)

    def test_invalid_date(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_BY_PERIOD, cliente="CLIENTE", desde="31/02/2026", hasta="2026-07-01"),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "fecha_invalida")
        self.assertEqual(adapter.calls, [])

    def test_inverted_period(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_BY_PERIOD, cliente="CLIENTE", desde="2026-07-20", hasta="2026-07-01"),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "rango_invertido")

    def test_latest_valid_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura_ultima.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)

    def test_latest_multiple_is_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            zip_path = self.make_file(outputs, "ultimas.zip", b"PK")
            adapter = FakeAdapter(
                {"payload": self.success_payload(zip_path, total=2, found=2), "file_path": str(zip_path)}
            )
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=2),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["file_type"], "zip")

    def test_latest_requires_client(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_LATEST, cliente="", cantidad=1), adapter=adapter, outputs_directory=Path("unused")
        )
        self.assertEqual(result.error.code, "cliente_requerido")

    def test_latest_normalizes_zero_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=0),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["cantidad"], 1)

    def test_latest_normalizes_twenty_one_to_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=21),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["cantidad"], 20)

    def test_client_without_documents(self):
        adapter = FakeAdapter(
            {"payload": {"Estado": "SIN_COMPROBANTES", "Mensaje": "No encontre facturas/notas."}}
        )
        result = generar_facturas_pdf(
            self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "sin_comprobantes")

    def test_powershell_error(self):
        adapter = FakeAdapter({"success": False, "returncode": 2, "stderr": "error controlado"})
        result = generar_facturas_pdf(
            self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "facturas_pdf_error")

    def test_client_not_found_from_script(self):
        adapter = FakeAdapter(
            {"success": False, "returncode": 1, "stderr": "No encontre cliente: CLIENTE INEXISTENTE"}
        )
        result = generar_facturas_pdf(
            self.request(MODE_LATEST, cliente="CLIENTE INEXISTENTE", cantidad=1),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertFalse(result.success)
        self.assertIn("No encontre cliente", result.message)

    def test_timeout(self):
        adapter = FakeAdapter({"success": False, "timed_out": True})
        result = generar_facturas_pdf(
            self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "facturas_pdf_timeout")

    def test_missing_generated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            missing = outputs / "missing.pdf"
            adapter = FakeAdapter({"payload": self.success_payload(missing), "file_path": str(missing)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertEqual(result.error.code, "archivo_no_generado")

    def test_path_outside_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / "outputs"
            outputs.mkdir()
            external = self.make_file(root / "external", "factura.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(external), "file_path": str(external)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="CLIENTE", cantidad=1),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertEqual(result.error.code, "ruta_no_autorizada")

    def test_wrong_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            wrong = self.make_file(outputs, "factura.txt")
            adapter = FakeAdapter({"payload": self.success_payload(wrong), "file_path": str(wrong)})
            result = generar_facturas_pdf(
                self.request(MODE_BY_NUMBER, numero="1"), adapter=adapter, outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "extension_invalida")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            empty = self.make_file(outputs, "factura.pdf", b"")
            adapter = FakeAdapter({"payload": self.success_payload(empty), "file_path": str(empty)})
            result = generar_facturas_pdf(
                self.request(MODE_BY_NUMBER, numero="1"), adapter=adapter, outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "archivo_vacio")

    def test_special_characters_in_client_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura.pdf")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_LATEST, cliente="Áridos Ñandú S.A.", cantidad=1),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["cliente"], "Áridos Ñandú S.A.")

    def test_result_must_match_request_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura.pdf")
            adapter = FakeAdapter(
                {
                    "payload": self.success_payload(pdf),
                    "file_path": str(pdf),
                    "request_signature": {"modo": MODE_BY_NUMBER, "numero": "otro"},
                }
            )
            result = generar_facturas_pdf(
                self.request(MODE_BY_NUMBER, numero="1"), adapter=adapter, outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "archivo_no_corresponde")

    def test_since_last_payment_valid_pdf_and_default_end_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_file(outputs, "factura_desde_pago.pdf", b"%PDF")
            adapter = FakeAdapter({"payload": self.success_payload(pdf), "file_path": str(pdf)})
            result = generar_facturas_pdf(
                self.request(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE"),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertIsNone(adapter.calls[0]["desde"])
        self.assertIsNotNone(adapter.calls[0]["hasta"])

    def test_since_last_payment_requires_client(self):
        adapter = FakeAdapter()
        result = generar_facturas_pdf(
            self.request(MODE_SINCE_LAST_PAYMENT, cliente=""),
            adapter=adapter,
            outputs_directory=Path("unused"),
        )
        self.assertEqual(result.error.code, "cliente_requerido")
        self.assertEqual(adapter.calls, [])

    def test_since_last_payment_resolution_states_are_specific(self):
        expected = {
            "SIN_PAGOS": "ultimo_pago_no_encontrado",
            "SIN_CLIENTE": "cliente_no_encontrado",
            "AMBIGUO": "cliente_ambiguo",
        }
        for state, code in expected.items():
            with self.subTest(state=state):
                adapter = FakeAdapter({"payload": {"Estado": state, "Mensaje": state}})
                result = generar_facturas_pdf(
                    self.request(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20"),
                    adapter=adapter,
                    outputs_directory=Path("unused"),
                )
                self.assertEqual(result.error.code, code)


if __name__ == "__main__":
    unittest.main()
