import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from helena_core.integrations.powershell.caja_adapter import CajaPowerShellAdapter
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

Cobros por medio: TODOS
Periodo: 01/07/2026 al 02/07/2026
Registros: 3
Total: $ 1.000,00

Totales por medio:
- EFECTIVO: 2 registros, $ 600,00
- TRANSFERENCIA: 1 registros, $ 400,00
"""


class CajaAdapterTests(unittest.TestCase):
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
            command = CajaPowerShellAdapter(settings=settings).build_command(
                medio="efectivo",
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-03",
            )
        self.assertEqual(Path(command[5]), settings.paths.scripts / "consultas_rapidas.ps1")
        self.assertEqual(
            command[-6:],
            ["cobros", "efectivo", "-Desde", "2026-07-01", "-Hasta", "2026-07-03"],
        )
        self.assertNotIn("work", [part.casefold() for part in Path(command[5]).parts])

    def test_parses_complete_output_without_recalculating(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(Completed(0, REPORT))
            result = CajaPowerShellAdapter(
                settings=self.make_settings(tmp), runner=runner
            ).consultar_cobros(
                medio="todos",
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-03",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["total"], "$ 1.000,00")
        self.assertEqual(result.payload["cantidad_registros"], 3)
        self.assertEqual(len(result.payload["medios_de_pago"]), 2)
        self.assertEqual(result.payload["texto_legacy"], REPORT[REPORT.index("Cobros por medio:") :].strip())
        self.assertEqual(runner.calls[0][1]["timeout"], 241)

    def test_accepts_zero_records_and_utf8_text(self):
        report = """Cobros por medio: RETENCIÓN
Periodo: 01/07/2026 al 01/07/2026
Registros: 0
Total: $ 0,00"""
        with tempfile.TemporaryDirectory() as tmp:
            result = CajaPowerShellAdapter(
                settings=self.make_settings(tmp), runner=RecordingRunner(Completed(0, report))
            ).consultar_cobros(
                medio="retención",
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-02",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["medio_mostrado"], "RETENCIÓN")

    def test_preserves_negative_totals_without_recalculating(self):
        report = REPORT.replace("$ 1.000,00", "-$ 50,00")
        with tempfile.TemporaryDirectory() as tmp:
            result = CajaPowerShellAdapter(
                settings=self.make_settings(tmp), runner=RecordingRunner(Completed(0, report))
            ).consultar_cobros(
                medio="todos",
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-03",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["total"], "-$ 50,00")

    def test_rejects_incomplete_wrong_period_or_wrong_medium_and_preserves_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            incomplete = CajaPowerShellAdapter(
                settings=settings, runner=RecordingRunner(Completed(0, "Cobros por medio: TODOS"))
            ).consultar_cobros(
                medio="todos", fecha_desde="2026-07-01", fecha_hasta="2026-07-03"
            )
            wrong_period = CajaPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, REPORT.replace("02/07/2026", "03/07/2026"))),
            ).consultar_cobros(
                medio="todos", fecha_desde="2026-07-01", fecha_hasta="2026-07-03"
            )
            wrong_medium = CajaPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, REPORT.replace("medio: TODOS", "medio: EFECTIVO"))),
            ).consultar_cobros(
                medio="todos", fecha_desde="2026-07-01", fecha_hasta="2026-07-03"
            )
            failed = CajaPowerShellAdapter(
                settings=settings, runner=RecordingRunner(Completed(1, "", "fallo controlado"))
            ).consultar_cobros(
                medio="todos", fecha_desde="2026-07-01", fecha_hasta="2026-07-03"
            )
        self.assertFalse(incomplete.success)
        self.assertIn("campos esperados", incomplete.stderr)
        self.assertFalse(wrong_period.success)
        self.assertIn("no coincide", wrong_period.stderr)
        self.assertFalse(wrong_medium.success)
        self.assertIn("medio de pago", wrong_medium.stderr)
        self.assertFalse(failed.success)
        self.assertEqual(failed.stderr, "fallo controlado")

    def test_reports_timeout_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=241))
            result = CajaPowerShellAdapter(
                settings=self.make_settings(tmp), runner=runner
            ).consultar_cobros(
                medio="todos", fecha_desde="2026-07-01", fecha_hasta="2026-07-03"
            )
        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
