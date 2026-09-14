import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from helena_core.business.clientes.estado_pdf import MODE_OPEN_BALANCE, MODE_RANGE, MODE_SINCE_LAST_PAYMENT
from helena_core.integrations.powershell.estado_pdf_adapter import EstadoCuentaPdfPowerShellAdapter
from helena_core.settings import load_settings


@dataclass
class Completed:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class RecordingRunner:
    def __init__(self, completed=None, raises=None):
        self.completed = completed or Completed()
        self.raises = raises
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise self.raises
        return self.completed


class EstadoPdfAdapterTests(unittest.TestCase):
    def make_settings(self, root: Path):
        config = root / "config"
        config.mkdir(parents=True)
        (config / "environment.json").write_text(
            json.dumps({"executables": {"powershell": "pwsh-test"}, "timeouts": {"export_script_seconds": 321}}),
            encoding="utf-8",
        )
        return load_settings(root=root, config_path=config / "environment.json", environ={})

    def build(self, adapter, modo, desde=None, hasta=None):
        return adapter.build_command(
            cliente="CLIENTE",
            modo=modo,
            desde=desde,
            hasta=hasta,
            nombre_archivo="estado_cliente.pdf",
        )

    def test_range_command_matches_existing_action_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = EstadoCuentaPdfPowerShellAdapter(settings=self.make_settings(Path(tmp)), runner=RecordingRunner())
            command = self.build(adapter, MODE_RANGE, "2026-07-01", "2026-07-20")
        self.assertEqual(Path(command[5]).name, "consultas_rapidas.ps1")
        self.assertEqual(command[6:], ["estado-pdf", "CLIENTE", "-Desde", "2026-07-01", "-Hasta", "2026-07-20", "-Archivo", "estado_cliente.pdf"])

    def test_open_balance_command_matches_existing_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = EstadoCuentaPdfPowerShellAdapter(settings=self.make_settings(Path(tmp)), runner=RecordingRunner())
            command = self.build(adapter, MODE_OPEN_BALANCE)
        self.assertEqual(command[6:], ["estado-pdf-abierto", "CLIENTE", "-Archivo", "estado_cliente.pdf"])

    def test_since_last_payment_command_matches_existing_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = EstadoCuentaPdfPowerShellAdapter(settings=self.make_settings(Path(tmp)), runner=RecordingRunner())
            command = self.build(adapter, MODE_SINCE_LAST_PAYMENT)
        self.assertEqual(command[6:], ["estado-pdf-ultimo-pago", "CLIENTE", "-Archivo", "estado_cliente.pdf"])

    def test_runner_receives_timeout_and_returns_expected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(Path(tmp))
            runner = RecordingRunner(Completed(stdout="generado"))
            adapter = EstadoCuentaPdfPowerShellAdapter(settings=settings, runner=runner)
            result = adapter.generar_estado_pdf(
                cliente="CLIENTE", modo=MODE_RANGE, desde="2026-07-01", hasta=None, nombre_archivo="estado_cliente.pdf"
            )
        _, options = runner.calls[0]
        self.assertEqual(options["timeout"], 321)
        self.assertEqual(Path(result.file_path).name, "estado_cliente.pdf")
        self.assertTrue(result.success)

    def test_process_error_is_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = EstadoCuentaPdfPowerShellAdapter(
                settings=self.make_settings(Path(tmp)), runner=RecordingRunner(Completed(2, "salida", "error"))
            )
            result = adapter.generar_estado_pdf(
                cliente="CLIENTE", modo=MODE_RANGE, desde="2026-07-01", hasta=None, nombre_archivo="estado_cliente.pdf"
            )
        self.assertFalse(result.success)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "error")

    def test_timeout_is_captured_without_real_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            timeout = subprocess.TimeoutExpired(cmd=["fake"], timeout=1)
            adapter = EstadoCuentaPdfPowerShellAdapter(
                settings=self.make_settings(Path(tmp)), runner=RecordingRunner(raises=timeout)
            )
            result = adapter.generar_estado_pdf(
                cliente="CLIENTE", modo=MODE_RANGE, desde="2026-07-01", hasta=None, nombre_archivo="estado_cliente.pdf"
            )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -1)

    def test_adapter_does_not_import_telegram(self):
        import helena_core.integrations.powershell.estado_pdf_adapter as module

        self.assertNotIn("telegram", (module.__doc__ or "").lower())
        self.assertFalse(hasattr(module, "telegram"))


if __name__ == "__main__":
    unittest.main()
