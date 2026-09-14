import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from helena_core.integrations.powershell.ventas_rapidas_adapter import VentasRapidasPowerShellAdapter
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


REPORT = """Analisis de categorias comerciales
Periodo: 01/07/2026 al 20/07/2026
Total real ventas: $ 1.000,00
Facturado real: $ 800,00
Remitos real: $ 200,00
Clasificado: $ 900,00
No clasificado: $ 100,00

Categoria       TotalReal Porcentaje
ARIDOS          $ 600,00  60,00%
GRAVAS          $ 200,00  20,00%
SERVICIOS       $ 100,00  10,00%
OTROS_PRODUCTOS $ 100,00  10,00%
"""


class VentasRapidasAdapterTests(unittest.TestCase):
    def make_settings(self, root):
        root = Path(root)
        config = root / "config" / "environment.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "paths": {"scripts": "scripts", "outputs": "outputs"},
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
            adapter = VentasRapidasPowerShellAdapter(settings=settings)
            command = adapter.build_command(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertEqual(Path(command[5]), settings.paths.scripts / "analisis_categorias.ps1")
        self.assertEqual(
            command[-8:],
            [
                "-AgruparPor",
                "total",
                "-Tipos",
                "Ambos",
                "-Desde",
                "2026-07-01",
                "-Hasta",
                "2026-07-20",
            ],
        )

    def test_parses_totals_categories_and_percentages(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            runner = RecordingRunner(Completed(0, REPORT))
            result = VentasRapidasPowerShellAdapter(settings=settings, runner=runner).consultar_ventas_rapidas(
                fecha_desde="2026-07-01", fecha_hasta="2026-07-20"
            )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["total"], "$ 1.000,00")
        self.assertEqual(result.payload["facturado"], "$ 800,00")
        self.assertEqual(result.payload["remitos"], "$ 200,00")
        self.assertEqual(
            [item["codigo"] for item in result.payload["categorias"]],
            ["ARIDOS", "GRAVAS", "SERVICIOS", "OTROS_PRODUCTOS"],
        )
        self.assertEqual(result.payload["categorias"][0]["porcentaje"], "60,00%")
        self.assertEqual(runner.calls[0][1]["timeout"], 241)

    def test_accepts_report_without_category_rows(self):
        output = "\n".join(REPORT.splitlines()[:7])
        with tempfile.TemporaryDirectory() as tmp:
            result = VentasRapidasPowerShellAdapter(
                settings=self.make_settings(tmp), runner=RecordingRunner(Completed(0, output))
            ).consultar_ventas_rapidas(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertTrue(result.success)
        self.assertEqual(result.payload["categorias"], [])

    def test_rejects_incomplete_output_and_preserves_script_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            invalid = VentasRapidasPowerShellAdapter(
                settings=settings, runner=RecordingRunner(Completed(0, "salida incompleta"))
            ).consultar_ventas_rapidas(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
            failed = VentasRapidasPowerShellAdapter(
                settings=settings, runner=RecordingRunner(Completed(1, "", "fallo controlado"))
            ).consultar_ventas_rapidas(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertFalse(invalid.success)
        self.assertIn("totales esperados", invalid.stderr)
        self.assertFalse(failed.success)
        self.assertEqual(failed.stderr, "fallo controlado")

    def test_reports_timeout_without_executing_any_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=241))
            result = VentasRapidasPowerShellAdapter(
                settings=self.make_settings(tmp), runner=runner
            ).consultar_ventas_rapidas(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
