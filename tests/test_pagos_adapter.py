import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from helena_core.business.pagos.propuestas import CAP_ECHEQ_LEGACY
from helena_core.integrations.powershell.pagos_adapter import PagosPowerShellAdapter
from helena_core.settings import load_settings


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class PagosAdapterTests(unittest.TestCase):
    def settings(self, root):
        return load_settings(root=root, config_path=Path(root) / "missing.json", environ={})

    def test_builds_exact_legacy_commands_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp) / "work_v2")
            adapter = PagosPowerShellAdapter(settings=settings)
            legacy = adapter.build_command(
                capability=CAP_ECHEQ_LEGACY,
                importe=1000.25,
                plazo={"tipo": "DIAS", "dias": 30},
                modo="ECHEQ",
                filtro_fiscal="TODOS",
            )
            optimal = adapter.build_command(
                capability="pagos.propuesta",
                importe=2000,
                plazo={"tipo": "DIAS", "dias": 60},
                modo="MIXTO",
                filtro_fiscal="NN",
            )
            due = adapter.build_command(
                capability="pagos.propuesta",
                importe=2000,
                plazo={"tipo": "ACOBRAR", "dias": None},
                modo="CHEQUE",
                filtro_fiscal="BLANCO",
            )

        self.assertEqual(Path(legacy[5]), settings.paths.scripts / "armar_pago_echeq.ps1")
        self.assertEqual(legacy[6:], ["-Importe", "1000.25", "-Dias", "30"])
        self.assertEqual(Path(optimal[5]), settings.paths.scripts / "armar_pago_optimo.ps1")
        self.assertEqual(
            optimal[6:],
            [
                "-Importe", "2000", "-Modo", "MIXTO", "-FiltroFiscal", "NN",
                "-MaxCandidatos", "35", "-MaxValores", "8", "-MaxCombinaciones", "50000",
                "-Dias", "60",
            ],
        )
        self.assertEqual(due[-1], "-ACobrar")
        self.assertNotIn("\\work\\", " ".join(optimal).lower())

    def test_parses_current_stdout_and_preserves_text(self):
        output = (
            "PAGO OPTIMO\n\n"
            "MEJOR OPCION\n"
            "Total: $ 900.000,50\n"
            "Diferencia: $ 99.999,50 por debajo\n"
            "1️⃣ ECHEQ — BANCO UNO 12345\n"
            "📅 30/08/2026\n"
            "👤 CLIENTE\n"
            "💰 $ 900.000,50\n"
        )
        payload = PagosPowerShellAdapter._parse_output(output)
        self.assertEqual(payload["total_seleccionado"], 900000.50)
        self.assertEqual(payload["opciones"][0]["total_seleccionado"], 900000.50)
        self.assertEqual(
            payload["cheques_seleccionados"][0],
            {
                "tipo": "ECHEQ",
                "numero": "12345",
                "banco": "BANCO UNO",
                "emisor": "CLIENTE",
                "fecha_pago": "30/08/2026",
                "importe": 900000.50,
            },
        )
        self.assertEqual(payload["texto_legacy"], output.strip())

    def test_accepts_current_no_combination_response_from_proven_script(self):
        output = "No se encuentra combinación de cheques."
        payload = PagosPowerShellAdapter._parse_output(output)
        self.assertEqual(payload["texto_legacy"], output)
        self.assertIsNone(payload["total_seleccionado"])
        self.assertEqual(payload["opciones"], [])
        self.assertEqual(payload["cheques_seleccionados"], [])

    def test_runner_timeout_error_and_incomplete_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp) / "work_v2")

            def timeout(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

            timeout_result = PagosPowerShellAdapter(settings=settings, runner=timeout).proponer(
                capability="pagos.propuesta",
                importe=1,
                plazo={"tipo": "DIAS", "dias": 30},
                modo="OPTIMO",
                filtro_fiscal="TODOS",
            )
            error_result = PagosPowerShellAdapter(
                settings=settings,
                runner=lambda *args, **kwargs: Completed(1, "", "fallo"),
            ).proponer(
                capability="pagos.propuesta",
                importe=1,
                plazo={"tipo": "DIAS", "dias": 30},
                modo="OPTIMO",
                filtro_fiscal="TODOS",
            )
            empty_result = PagosPowerShellAdapter(
                settings=settings,
                runner=lambda *args, **kwargs: Completed(0, "", ""),
            ).proponer(
                capability="pagos.propuesta",
                importe=1,
                plazo={"tipo": "DIAS", "dias": 30},
                modo="OPTIMO",
                filtro_fiscal="TODOS",
            )
            incomplete_result = PagosPowerShellAdapter(
                settings=settings,
                runner=lambda *args, **kwargs: Completed(0, "salida inesperada", ""),
            ).proponer(
                capability="pagos.propuesta",
                importe=1,
                plazo={"tipo": "DIAS", "dias": 30},
                modo="OPTIMO",
                filtro_fiscal="TODOS",
            )

        self.assertTrue(timeout_result.timed_out)
        self.assertFalse(error_result.success)
        self.assertFalse(empty_result.success)
        self.assertIn("vacia", empty_result.stderr)
        self.assertFalse(incomplete_result.success)
        self.assertIn("incompleta", incomplete_result.stderr)

    def test_fragmented_portfolio_reuses_validated_cheques_adapter_and_cleans_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp) / "work_v2")

            def runner(command, **kwargs):
                output = Path(command[command.index("-OutJson") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(
                        {
                            "FechaConsulta": date.today().isoformat(),
                            "Dias": 0,
                            "Tipo": "ECHEQ",
                            "FiltroFiscal": "BLANCO",
                            "Registros": [
                                {
                                    "IdENTREGA": 7,
                                    "Estado": "EN CAJA",
                                    "OBSERVACION": "",
                                    "Importe": 1000,
                                    "FechaCobro": (date.today() + timedelta(days=30)).isoformat(),
                                    "DiasRestantes": 30,
                                    "DiasAlVencimiento": 60,
                                    "Tipo": "ECHEQ",
                                    "Banco": "BANCO",
                                    "Numero": "1",
                                    "Cliente": "CLIENTE",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return Completed(0, "resumen", "")

            result = PagosPowerShellAdapter(settings=settings, runner=runner).cargar_cartera(
                modo="ECHEQ",
                filtro_fiscal="BLANCO",
            )
            remaining = list((settings.paths.data / "cache").glob("cheques_resumen_*.json"))

        self.assertTrue(result.success)
        self.assertEqual(result.payload["cantidad"], 1)
        self.assertEqual(result.payload["items"][0].raw["IdENTREGA"], 7)
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
