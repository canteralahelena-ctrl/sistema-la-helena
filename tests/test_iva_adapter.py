import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from helena_core.integrations.powershell.iva_adapter import IvaPowerShellAdapter
from helena_core.settings import load_settings


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str = ""


class RecordingRunner:
    def __init__(self, completed=None, *, raises=None):
        self.completed = completed
        self.raises = raises
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise self.raises
        return self.completed


REPORT = """Actualizando copia local de Access antes de consultar...

Periodo            : 2026-07
IvaVentas          : $ 1.000,00
IvaGastos          : $ 400,00
SaldoIva           : $ 600,00
VentasComprobantes : 10
GastosComprobantes : 4
DetalleCsv         : C:\\outputs\\iva_detalle.csv
Resumen            : C:\\outputs\\iva_resumen.txt
"""


class IvaAdapterTests(unittest.TestCase):
    def make_settings(self, root):
        root = Path(root)
        config = root / "config" / "environment.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "paths": {"scripts": "scripts"},
                    "executables": {"powershell": "pwsh-test"},
                    "timeouts": {"long_script_seconds": 241},
                }
            ),
            encoding="utf-8",
        )
        (root / "scripts").mkdir()
        return load_settings(root=root, config_path=config, environ={})

    def test_builds_exact_legacy_command_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            command = IvaPowerShellAdapter(settings=settings).build_command(anio=2026, mes=7)
        self.assertEqual(Path(command[5]), settings.paths.scripts / "consultas_rapidas.ps1")
        self.assertEqual(command[-3:], ["iva-mensual", "-Desde", "2026-07-01"])

    def test_parses_complete_output_and_preserves_fiscal_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(Completed(0, REPORT))
            result = IvaPowerShellAdapter(
                settings=self.make_settings(tmp), runner=runner
            ).consultar_iva_mensual(anio=2026, mes=7)
        self.assertTrue(result.success)
        self.assertEqual(result.payload["iva_ventas"], "$ 1.000,00")
        self.assertEqual(result.payload["iva_gastos"], "$ 400,00")
        self.assertEqual(result.payload["saldo_iva"], "$ 600,00")
        self.assertEqual(result.payload["ventas_comprobantes"], 10)
        self.assertEqual(runner.calls[0][1]["timeout"], 241)

    def test_accepts_current_visible_iva_contract_without_auxiliary_fields(self):
        output = (
            "Periodo: 2026-07\n"
            "IvaVentas: $ 1.000,00\n"
            "IvaGastos: $ 400,00\n"
            "SaldoIva: $ 600,00\n"
        )
        payload = IvaPowerShellAdapter._parse_output(output, anio=2026, mes=7)
        self.assertEqual(payload["iva_ventas"], "$ 1.000,00")
        self.assertEqual(payload["iva_gastos"], "$ 400,00")
        self.assertEqual(payload["saldo_iva"], "$ 600,00")
        self.assertIsNone(payload["ventas_comprobantes"])
        self.assertIsNone(payload["gastos_comprobantes"])

    def test_accepts_same_current_contract_as_json(self):
        output = json.dumps(
            {
                "Periodo": "2026-07",
                "IvaVentas": "$ 1.000,00",
                "IvaGastos": "$ 400,00",
                "SaldoIva": "$ 600,00",
            }
        )
        payload = IvaPowerShellAdapter._parse_output(output, anio=2026, mes=7)
        self.assertEqual(payload["saldo_iva"], "$ 600,00")

    def test_preserves_custom_dashboard_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(Completed(0, REPORT))
            result = IvaPowerShellAdapter(
                settings=self.make_settings(tmp),
                runner=runner,
                timeout_seconds=180,
            ).consultar_iva_mensual(anio=2026, mes=7)
        self.assertTrue(result.success)
        self.assertEqual(runner.calls[0][1]["timeout"], 180)

    def test_rejects_incomplete_wrong_period_or_invalid_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            incomplete = IvaPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(
                    Completed(
                        0,
                        "Periodo: 2026-07\nIvaVentas: $ 1,00\nIvaGastos: $ 0,50",
                    )
                ),
            ).consultar_iva_mensual(anio=2026, mes=7)
            wrong = IvaPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, REPORT.replace("2026-07", "2026-06"))),
            ).consultar_iva_mensual(anio=2026, mes=7)
            invalid_count = IvaPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, REPORT.replace(": 10", ": diez"))),
            ).consultar_iva_mensual(anio=2026, mes=7)
        self.assertFalse(incomplete.success)
        self.assertIn("campos esperados", incomplete.stderr)
        self.assertFalse(wrong.success)
        self.assertIn("no coincide", wrong.stderr)
        self.assertFalse(invalid_count.success)
        self.assertIn("cantidades", invalid_count.stderr)

    def test_preserves_process_error_and_timeout_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            failed = IvaPowerShellAdapter(
                settings=settings, runner=RecordingRunner(Completed(1, "", "fallo controlado"))
            ).consultar_iva_mensual(anio=2026, mes=7)
            timeout_runner = RecordingRunner(
                raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=241)
            )
            timeout = IvaPowerShellAdapter(
                settings=settings, runner=timeout_runner
            ).consultar_iva_mensual(anio=2026, mes=7)
        self.assertFalse(failed.success)
        self.assertEqual(failed.stderr, "fallo controlado")
        self.assertFalse(timeout.success)
        self.assertTrue(timeout.timed_out)
        self.assertEqual(len(timeout_runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
