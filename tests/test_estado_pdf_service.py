import tempfile
import time
import unittest
from pathlib import Path

from helena_core.application.contracts import Request
from helena_core.business.clientes.estado_pdf import (
    MODE_OPEN_BALANCE,
    MODE_RANGE,
    MODE_SINCE_LAST_PAYMENT,
    generar_estado_cuenta_pdf,
)


class FakeAdapter:
    def __init__(self, result=None, *, raises=None, touch_returned_file=True):
        self.result = result or {}
        self.raises = raises
        self.calls = []
        self.touch_returned_file = touch_returned_file

    def generar_estado_pdf(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        file_path = self.result.get("file_path")
        if self.touch_returned_file and file_path:
            path = Path(file_path)
            if path.exists():
                now = time.time()
                path.touch()
                path.chmod(path.stat().st_mode)
                time.sleep(0.01)
                path.touch()
        return {
            "success": True,
            "returncode": 0,
            "stdout": "PDF generado",
            "stderr": "",
            "timeout": 300,
            **self.result,
        }


class EstadoPdfServiceTests(unittest.TestCase):
    def make_pdf(self, directory: Path, name="estado_cliente.pdf", content=b"%PDF-test"):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(content)
        return path

    def request(self, **parameters):
        defaults = {
            "cliente": "CLIENTE",
            "modo": MODE_RANGE,
            "desde": "2026-07-01",
            "nombre_archivo": "estado_cliente.pdf",
        }
        defaults.update(parameters)
        return Request(capability="clientes.estado_pdf", parameters=defaults)

    def test_range_pdf_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            adapter = FakeAdapter({"file_path": str(pdf)})
            result = generar_estado_cuenta_pdf(self.request(hasta="2026-07-20"), adapter=adapter, outputs_directory=outputs)
        self.assertTrue(result.success)
        self.assertEqual(result.data["modo"], MODE_RANGE)
        self.assertEqual(adapter.calls[0]["hasta"], "2026-07-20")

    def test_range_accepts_only_start_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            adapter = FakeAdapter({"file_path": str(pdf)})
            result = generar_estado_cuenta_pdf(self.request(), adapter=adapter, outputs_directory=outputs)
        self.assertTrue(result.success)
        self.assertIsNone(adapter.calls[0]["hasta"])

    def test_inverted_range_is_rejected_without_adapter(self):
        adapter = FakeAdapter()
        result = generar_estado_cuenta_pdf(
            self.request(desde="2026-07-20", hasta="2026-07-01"), adapter=adapter, outputs_directory=Path("unused")
        )
        self.assertEqual(result.error.code, "rango_invertido")
        self.assertEqual(adapter.calls, [])

    def test_invalid_date_is_rejected(self):
        adapter = FakeAdapter()
        result = generar_estado_cuenta_pdf(self.request(desde="31/02/2026"), adapter=adapter, outputs_directory=Path("unused"))
        self.assertEqual(result.error.code, "fecha_invalida")
        self.assertEqual(adapter.calls, [])

    def test_open_balance_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            adapter = FakeAdapter({"file_path": str(pdf)})
            request = self.request(modo=MODE_OPEN_BALANCE, desde=None)
            result = generar_estado_cuenta_pdf(request, adapter=adapter, outputs_directory=outputs)
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["modo"], MODE_OPEN_BALANCE)

    def test_since_last_payment_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            adapter = FakeAdapter({"file_path": str(pdf)})
            request = self.request(modo=MODE_SINCE_LAST_PAYMENT, desde=None)
            result = generar_estado_cuenta_pdf(request, adapter=adapter, outputs_directory=outputs)
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["modo"], MODE_SINCE_LAST_PAYMENT)

    def test_valid_client_is_delegated_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            adapter = FakeAdapter({"file_path": str(pdf)})
            result = generar_estado_cuenta_pdf(self.request(cliente=" CLIENTE "), adapter=adapter, outputs_directory=outputs)
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["cliente"], "CLIENTE")

    def test_client_not_found_is_classified(self):
        adapter = FakeAdapter({"success": False, "returncode": 1, "stderr": "No encontre cliente: CLIENTE"})
        result = generar_estado_cuenta_pdf(self.request(), adapter=adapter, outputs_directory=Path("unused"))
        self.assertEqual(result.error.code, "cliente_no_encontrado")

    def test_ambiguous_client_is_classified(self):
        adapter = FakeAdapter({"success": False, "returncode": 1, "stderr": "Hay varios clientes. Usa IdCLIENTE"})
        result = generar_estado_cuenta_pdf(self.request(), adapter=adapter, outputs_directory=Path("unused"))
        self.assertEqual(result.error.code, "cliente_ambiguo")

    def test_powershell_error_is_controlled(self):
        adapter = FakeAdapter({"success": False, "returncode": 2, "stderr": "fallo controlado"})
        result = generar_estado_cuenta_pdf(self.request(), adapter=adapter, outputs_directory=Path("unused"))
        self.assertEqual(result.error.code, "estado_pdf_error")
        self.assertEqual(result.metadata["returncode"], 2)

    def test_timeout_is_controlled(self):
        result = generar_estado_cuenta_pdf(
            self.request(), adapter=FakeAdapter(raises=TimeoutError()), outputs_directory=Path("unused")
        )
        self.assertEqual(result.error.code, "estado_pdf_timeout")

    def test_empty_stdout_is_allowed_when_pdf_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            result = generar_estado_cuenta_pdf(
                self.request(), adapter=FakeAdapter({"file_path": str(pdf), "stdout": ""}), outputs_directory=outputs
            )
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Consulta ejecutada.")

    def test_missing_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            result = generar_estado_cuenta_pdf(
                self.request(), adapter=FakeAdapter({"file_path": str(outputs / "missing.pdf")}), outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "pdf_no_generado")

    def test_old_pdf_from_previous_execution_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs)
            old_time = time.time() - 3600
            os_utime = getattr(__import__("os"), "utime")
            os_utime(pdf, (old_time, old_time))
            result = generar_estado_cuenta_pdf(
                self.request(),
                adapter=FakeAdapter({"file_path": str(pdf)}, touch_returned_file=False),
                outputs_directory=outputs,
            )
        self.assertEqual(result.error.code, "pdf_no_corresponde_ejecucion")

    def test_pdf_outside_authorized_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / "outputs"
            outputs.mkdir()
            outside = self.make_pdf(root / "outside")
            result = generar_estado_cuenta_pdf(
                self.request(), adapter=FakeAdapter({"file_path": str(outside)}), outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "ruta_pdf_no_autorizada")

    def test_non_pdf_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            file_path = self.make_pdf(outputs, name="estado.txt")
            result = generar_estado_cuenta_pdf(
                self.request(), adapter=FakeAdapter({"file_path": str(file_path)}), outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "extension_pdf_invalida")

    def test_empty_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs, content=b"")
            result = generar_estado_cuenta_pdf(
                self.request(), adapter=FakeAdapter({"file_path": str(pdf)}), outputs_directory=outputs
            )
        self.assertEqual(result.error.code, "pdf_vacio")

    def test_special_characters_are_preserved_in_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            pdf = self.make_pdf(outputs, name="estado_jose_nunez.pdf")
            adapter = FakeAdapter({"file_path": str(pdf)})
            result = generar_estado_cuenta_pdf(
                self.request(cliente="José Núñez", nombre_archivo="estado_jose_nunez.pdf"),
                adapter=adapter,
                outputs_directory=outputs,
            )
        self.assertTrue(result.success)
        self.assertEqual(adapter.calls[0]["cliente"], "José Núñez")


if __name__ == "__main__":
    unittest.main()
