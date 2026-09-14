import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from helena_core.integrations.powershell.cheques_adapter import ChequesPowerShellAdapter
from helena_core.settings import load_settings


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str = ""


class RecordingRunner:
    def __init__(self, completed=None, *, json_data=None, raises=None):
        self.completed = completed
        self.json_data = json_data
        self.raises = raises
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise self.raises
        if self.json_data is not None and "-OutJson" in command:
            path = Path(command[command.index("-OutJson") + 1])
            path.write_text(json.dumps(self.json_data), encoding="utf-8")
        return self.completed


class ChequesAdapterTests(unittest.TestCase):
    def make_settings(self, root):
        root = Path(root)
        config = root / "config" / "environment.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "paths": {"scripts": "scripts", "data": "data"},
                    "executables": {"powershell": "pwsh-test"},
                    "timeouts": {"default_script_seconds": 181},
                }
            ),
            encoding="utf-8",
        )
        (root / "scripts").mkdir()
        return load_settings(root=root, config_path=config, environ={})

    def test_builds_exact_commands_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            adapter = ChequesPowerShellAdapter(settings=settings)
            output = settings.paths.data / "cache" / "out.json"
            summary = adapter.build_command(
                accion="resumen",
                tipo="ECHEQ",
                filtro_fiscal="NN",
                dias=30,
                out_json=output,
            )
            depositables = adapter.build_command(
                accion="depositables",
                tipo="TODOS",
                filtro_fiscal="BLANCO",
                dias=30,
            )
            vencimientos = adapter.build_command(
                accion="vencimientos",
                tipo="CHEQUE",
                filtro_fiscal="TODOS",
                dias=15,
                out_json=output,
            )
            alertas = adapter.build_command(
                accion="alertas",
                tipo="TODOS",
                filtro_fiscal="TODOS",
                dias=3,
            )
        self.assertEqual(Path(summary[5]), settings.paths.scripts / "gestion_cheques.ps1")
        self.assertEqual(
            summary[-8:],
            ["-Accion", "resumen", "-Tipo", "ECHEQ", "-FiltroFiscal", "NN", "-OutJson", str(output)],
        )
        self.assertEqual(
            depositables[-6:],
            ["-Accion", "depositables", "-Tipo", "TODOS", "-FiltroFiscal", "BLANCO"],
        )
        self.assertEqual(
            vencimientos[-10:],
            [
                "-Accion",
                "vencimientos",
                "-Tipo",
                "CHEQUE",
                "-FiltroFiscal",
                "TODOS",
                "-Dias",
                "15",
                "-OutJson",
                str(output),
            ],
        )
        self.assertEqual(alertas[-6:], ["-Accion", "alertas", "-Tipo", "TODOS", "-Dias", "3"])

    def test_reads_current_json_and_cleans_own_file(self):
        data = {
            "FechaConsulta": date.today().isoformat(),
            "Dias": 30,
            "Tipo": "TODOS",
            "FiltroFiscal": "TODOS",
            "Registros": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            runner = RecordingRunner(Completed(0, "No hay valores para ese filtro."), json_data=data)
            adapter = ChequesPowerShellAdapter(
                settings=settings,
                runner=runner,
                token_factory=lambda: "actual",
                clock_ns=lambda: 0,
            )
            result = adapter.consultar(
                accion="resumen",
                tipo="TODOS",
                filtro_fiscal="TODOS",
                dias=30,
            )
            output = settings.paths.data / "cache" / "cheques_resumen_actual.json"
        self.assertTrue(result.success)
        self.assertEqual(result.payload["Registros"], [])
        self.assertFalse(output.exists())
        self.assertEqual(runner.calls[0][1]["timeout"], 181)

    def test_rejects_missing_stale_or_invalid_json(self):
        data = {
            "FechaConsulta": date.today().isoformat(),
            "Dias": 30,
            "Tipo": "TODOS",
            "FiltroFiscal": "TODOS",
            "Registros": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            missing = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, "")),
                token_factory=lambda: "missing",
                clock_ns=lambda: 0,
            ).consultar(accion="resumen", tipo="TODOS", filtro_fiscal="TODOS", dias=30)
            stale = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, ""), json_data=data),
                token_factory=lambda: "stale",
                clock_ns=lambda: 10**30,
            ).consultar(accion="resumen", tipo="TODOS", filtro_fiscal="TODOS", dias=30)
            invalid = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, ""), json_data={"otro": []}),
                token_factory=lambda: "invalid",
                clock_ns=lambda: 0,
            ).consultar(accion="resumen", tipo="TODOS", filtro_fiscal="TODOS", dias=30)
            wrong_date_data = dict(data, FechaConsulta="2000-01-01")
            wrong_date = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, ""), json_data=wrong_date_data),
                token_factory=lambda: "wrong-date",
                clock_ns=lambda: 0,
            ).consultar(accion="resumen", tipo="TODOS", filtro_fiscal="TODOS", dias=30)
        self.assertFalse(missing.success)
        self.assertIn("ejecucion actual", missing.stderr)
        self.assertFalse(stale.success)
        self.assertIn("ejecucion actual", stale.stderr)
        self.assertFalse(invalid.success)
        self.assertIn("incompleto", invalid.stderr)
        self.assertFalse(wrong_date.success)
        self.assertIn("fecha", wrong_date.stderr)

    def test_parses_depositables_empty_and_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            empty = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, "No hay valores para ese filtro.")),
            ).consultar(
                accion="depositables",
                tipo="TODOS",
                filtro_fiscal="NN",
                dias=30,
            )
            depositables = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(
                    Completed(
                        0,
                        "Disponible para depositar hoy\nFiltro: Todos\nFecha: 24/07/2026\n"
                        "CHEQUE FISICO: 1, $ 10,00\nECHEQ: 0, $ 0,00\nTOTAL: $ 10,00",
                    )
                ),
            ).consultar(
                accion="depositables",
                tipo="TODOS",
                filtro_fiscal="TODOS",
                dias=30,
            )
            alerts = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(
                    Completed(0, "Cheques proximos a vencer\nTotal: $ 10,00\n- ECHEQ")
                ),
            ).consultar(
                accion="alertas",
                tipo="TODOS",
                filtro_fiscal="TODOS",
                dias=3,
            )
        self.assertTrue(empty.success)
        self.assertTrue(empty.payload["vacio"])
        self.assertTrue(depositables.success)
        self.assertFalse(depositables.payload["vacio"])
        self.assertEqual(depositables.payload["total"], "$ 10,00")
        self.assertEqual(depositables.payload["por_tipo"]["CHEQUE FISICO"]["cantidad"], 1)
        self.assertTrue(alerts.success)
        self.assertTrue(alerts.payload["hay_alertas"])

    def test_preserves_process_error_timeout_and_rejects_incomplete_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.make_settings(tmp)
            failed = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(1, "", "fallo controlado")),
            ).consultar(
                accion="depositables", tipo="TODOS", filtro_fiscal="TODOS", dias=30
            )
            timeout_runner = RecordingRunner(
                raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=181)
            )
            timeout = ChequesPowerShellAdapter(
                settings=settings, runner=timeout_runner
            ).consultar(accion="alertas", tipo="TODOS", filtro_fiscal="TODOS", dias=3)
            incomplete = ChequesPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, "salida incompleta")),
            ).consultar(
                accion="depositables", tipo="TODOS", filtro_fiscal="TODOS", dias=30
            )
        self.assertFalse(failed.success)
        self.assertEqual(failed.stderr, "fallo controlado")
        self.assertTrue(timeout.timed_out)
        self.assertEqual(len(timeout_runner.calls), 1)
        self.assertFalse(incomplete.success)
        self.assertIn("incompleta", incomplete.stderr)


if __name__ == "__main__":
    unittest.main()
