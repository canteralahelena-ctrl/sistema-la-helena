import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

from helena_core.business.clientes.facturas_pdf import (
    MODE_BY_NUMBER,
    MODE_BY_PERIOD,
    MODE_LATEST,
    MODE_SINCE_LAST_PAYMENT,
)
from helena_core.integrations.powershell.facturas_pdf_adapter import FacturasPdfPowerShellAdapter
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


class CallbackRunner(RecordingRunner):
    def __init__(self, completed, callback):
        super().__init__(completed)
        self.callback = callback

    def __call__(self, command, **kwargs):
        self.callback()
        return super().__call__(command, **kwargs)


class SinceRunner:
    def __init__(self, payment, generation=None):
        self.payment = payment
        self.generation = generation
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if len(self.calls) == 1:
            return self.payment
        if callable(self.generation):
            return self.generation(command)
        return self.generation


class FacturasPdfAdapterTests(unittest.TestCase):
    def make_settings(self, root, *, scripts="scripts"):
        root = Path(root)
        config = root / "config" / "environment.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "paths": {"scripts": scripts, "outputs": "outputs"},
                    "executables": {"powershell": "pwsh-test"},
                    "timeouts": {"default_script_seconds": 181, "long_script_seconds": 241},
                }
            ),
            encoding="utf-8",
        )
        (root / scripts).mkdir(exist_ok=True)
        return load_settings(root=root, config_path=config, environ={})

    def args(self, mode, **overrides):
        values = {
            "modo": mode,
            "cliente": None,
            "tipo": None,
            "numero": None,
            "desde": None,
            "hasta": None,
            "cantidad": None,
        }
        values.update(overrides)
        return values

    def number_source(self, root, *, name="FTA00002_00000001.pdf", content=b"%PDF-current"):
        source = Path(root) / "2026" / "FT A" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        return source

    def number_payload(self, source, *, tipo="FTS A", access_number=200000001):
        return {
            "Estado": "OK",
            "Archivo": str(source),
            "Caption": f"PDF encontrado: {tipo} {access_number}",
        }

    def test_by_number_uses_exact_action_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp))
            command = adapter.build_command(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1-2"))
        self.assertEqual(Path(command[5]).name, "facturas_pdf.ps1")
        self.assertEqual(command[-6:], ["-Accion", "factura", "-Tipo", "FTS A", "-Numero", "1-2"])

    def test_period_uses_exact_action_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp))
            command = adapter.build_command(
                **self.args(
                    MODE_BY_PERIOD,
                    cliente="123",
                    desde="2026-07-01",
                    hasta="2026-07-02",
                )
            )
        self.assertEqual(
            command[-8:],
            ["-Accion", "cliente", "-Cliente", "123", "-Desde", "2026-07-01", "-Hasta", "2026-07-02"],
        )

    def test_latest_uses_exact_action_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp))
            command = adapter.build_command(**self.args(MODE_LATEST, cliente="123", cantidad=3))
        self.assertEqual(command[-6:], ["-Accion", "ultimas-cliente", "-Cliente", "123", "-Cantidad", "3"])

    def test_number_pdf_is_staged_from_authorized_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)
            payload = self.number_payload(source)
            runner = RecordingRunner(Completed(0, json.dumps(payload)))
            copied_to = []

            def copy_spy(origin, destination):
                copied_to.append(Path(destination))
                return shutil.copy2(origin, destination)

            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=runner,
                source_pdf_root=source_root,
                copier=copy_spy,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
            destination = settings.paths.outputs / source.name
            self.assertTrue(destination.exists())
            self.assertEqual(len(copied_to), 1)
            self.assertEqual(copied_to[0].parent, settings.paths.outputs)
            self.assertEqual(copied_to[0].suffix, ".tmp")
            self.assertEqual(list(settings.paths.outputs.glob("*.tmp")), [])
        self.assertTrue(result.success)
        self.assertEqual(Path(result.file_path).name, source.name)
        self.assertEqual(runner.calls[0][1]["timeout"], 181)

    def test_existing_identical_destination_is_reused_without_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)
            destination = settings.paths.outputs / source.name
            destination.parent.mkdir()
            destination.write_bytes(source.read_bytes())
            copier = Mock(side_effect=AssertionError("No debe copiar contenido identico"))
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
                copier=copier,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FT A", numero="00000001"))
        self.assertTrue(result.success)
        copier.assert_not_called()
        self.assertEqual(Path(result.file_path), destination)

    def test_existing_different_destination_gets_unique_name_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root, content=b"%PDF-new")
            preferred = settings.paths.outputs / source.name
            preferred.parent.mkdir()
            preferred.write_bytes(b"%PDF-old")
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
            alternate = Path(result.file_path)
            self.assertEqual(preferred.read_bytes(), b"%PDF-old")
            self.assertNotEqual(alternate, preferred)
            self.assertEqual(alternate.read_bytes(), source.read_bytes())
            self.assertRegex(alternate.name, r"^FTA00002_00000001__[0-9a-f]{12}\.pdf$")
        self.assertTrue(result.success)

    def test_copy_error_removes_partial_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)

            def broken_copy(origin, destination):
                Path(destination).write_bytes(b"partial")
                raise OSError("copia interrumpida")

            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
                copier=broken_copy,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
            self.assertFalse((settings.paths.outputs / source.name).exists())
            self.assertEqual(list(settings.paths.outputs.glob("*.tmp")), [])
        self.assertFalse(result.success)
        self.assertIn("copia interrumpida", result.stderr)

    def test_invalid_temporary_content_is_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)

            def corrupt_copy(origin, destination):
                Path(destination).write_bytes(b"contenido distinto")
                return destination

            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
                copier=corrupt_copy,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
            self.assertFalse((settings.paths.outputs / source.name).exists())
            self.assertEqual(list(settings.paths.outputs.glob("*.tmp")), [])
        self.assertFalse(result.success)
        self.assertIn("no coincide", result.stderr)

    def test_original_source_is_preserved_after_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root, content=b"%PDF-original")
            original = source.read_bytes()
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), original)
        self.assertTrue(result.success)

    def test_number_pdf_outside_authorized_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source_root.mkdir()
            outside = root / "outside" / "FTA00002_00000001.pdf"
            outside.parent.mkdir()
            outside.write_bytes(b"%PDF")
            payload = self.number_payload(outside)
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(payload))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
        self.assertFalse(result.success)
        self.assertIn("preparar", result.stderr)

    def test_unchanged_old_pdf_inside_outputs_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            output = settings.paths.outputs / "FTA00002_00000001.pdf"
            output.parent.mkdir()
            output.write_bytes(b"%PDF-old")
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(output)))),
                source_pdf_root=root / "source",
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
        self.assertFalse(result.success)
        self.assertIn("ya existia y no cambio", result.stderr)

    def test_new_pdf_inside_outputs_created_by_execution_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            output = settings.paths.outputs / "FTA00002_00000001.pdf"
            payload = self.number_payload(output)

            def create_output():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"%PDF-new")

            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=CallbackRunner(Completed(0, json.dumps(payload)), create_output),
                source_pdf_root=root / "source",
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
        self.assertTrue(result.success)
        self.assertEqual(Path(result.file_path), output)

    def test_existing_pdf_updated_by_execution_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            output = settings.paths.outputs / "FTA00002_00000001.pdf"
            output.parent.mkdir()
            output.write_bytes(b"%PDF-before")
            payload = self.number_payload(output)

            def update_output():
                output.write_bytes(b"%PDF-after")

            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=CallbackRunner(Completed(0, json.dumps(payload)), update_output),
                source_pdf_root=root / "source",
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="1"))
        self.assertTrue(result.success)

    def test_type_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS B", numero="1"))
        self.assertFalse(result.success)
        self.assertIn("tipo solicitado", result.stderr)

    def test_number_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_BY_NUMBER, tipo="FTS A", numero="2"))
        self.assertFalse(result.success)
        self.assertIn("tipo o numero", result.stderr)

    def test_valid_type_and_number_format_variations_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            source_root = root / "source"
            source = self.number_source(source_root)
            adapter = FacturasPdfPowerShellAdapter(
                settings=settings,
                runner=RecordingRunner(Completed(0, json.dumps(self.number_payload(source)))),
                source_pdf_root=source_root,
            )
            result = adapter.generar_facturas_pdf(
                **self.args(MODE_BY_NUMBER, tipo="ft a", numero="00002/00000001")
            )
        self.assertTrue(result.success)

    def test_period_captures_json_and_long_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            output = settings.paths.outputs / "facturas.zip"
            output.parent.mkdir()
            output.write_bytes(b"PK")
            payload = {"Estado": "OK", "Archivo": str(output)}
            runner = RecordingRunner(Completed(0, json.dumps(payload)))
            adapter = FacturasPdfPowerShellAdapter(settings=settings, runner=runner)
            result = adapter.generar_facturas_pdf(
                **self.args(MODE_BY_PERIOD, cliente="123", desde="2026-07-01", hasta="2026-07-02")
            )
        self.assertTrue(result.success)
        self.assertEqual(result.payload["Estado"], "OK")
        self.assertEqual(runner.calls[0][1]["timeout"], 241)

    def test_empty_stdout_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FacturasPdfPowerShellAdapter(
                settings=self.make_settings(tmp), runner=RecordingRunner(Completed(0, ""))
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_LATEST, cliente="123", cantidad=1))
        self.assertFalse(result.success)
        self.assertIn("no devolvio contenido", result.stderr)

    def test_process_error_captures_stdout_stderr_and_returncode(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = FacturasPdfPowerShellAdapter(
                settings=self.make_settings(tmp), runner=RecordingRunner(Completed(2, "salida", "error"))
            )
            result = adapter.generar_facturas_pdf(**self.args(MODE_LATEST, cliente="123", cantidad=1))
        self.assertFalse(result.success)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, "salida", "error"))

    def test_timeout_is_captured_without_real_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordingRunner(raises=subprocess.TimeoutExpired(cmd=["pwsh-test"], timeout=241))
            adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp), runner=runner)
            result = adapter.generar_facturas_pdf(**self.args(MODE_LATEST, cliente="123", cantidad=1))
        self.assertTrue(result.timed_out)
        self.assertFalse(result.success)
        self.assertEqual(result.returncode, -1)

    def test_since_last_payment_uses_legacy_order_and_current_isolated_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            payment = Completed(
                0,
                json.dumps(
                    {
                        "Estado": "OK",
                        "Cliente": "CLIENTE",
                        "Fecha": "2026-07-03",
                        "IdPago": 77,
                        "Tipo": "RECIBO",
                    }
                ),
            )

            def generate(command):
                run_directory = Path(command[command.index("-OutDir") + 1])
                current = run_directory / "factura_cliente.pdf"
                current.write_bytes(b"%PDF-current")
                return Completed(
                    0,
                    json.dumps(
                        {
                            "Estado": "OK",
                            "Archivo": str(current),
                            "Caption": "Facturas PDF: CLIENTE | periodo",
                            "TotalComprobantes": 1,
                            "Encontrados": 1,
                            "Faltantes": 0,
                        }
                    ),
                )

            runner = SinceRunner(payment, generate)
            adapter = FacturasPdfPowerShellAdapter(settings=settings, runner=runner)
            result = adapter.generar_facturas_pdf(
                **self.args(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20")
            )
            lookup_script = runner.calls[0][0][-1]
            generation_command = runner.calls[1][0]
            self.assertTrue(Path(result.file_path).is_file())
            self.assertEqual(Path(result.file_path).read_bytes(), b"%PDF-current")
            self.assertEqual(list(settings.paths.outputs.glob(".facturas_pdf_*")), [])
        self.assertTrue(result.success)
        self.assertIn("ORDER BY FECHA DESC, IdPAGO DESC", lookup_script)
        self.assertIn("WHERE IdCLIENTE = ?", lookup_script)
        self.assertEqual(
            generation_command[generation_command.index("-Desde") + 1],
            "2026-07-03",
        )
        self.assertEqual(result.payload["FechaUltimoPago"], "2026-07-03")
        self.assertEqual(result.request_signature["modo"], MODE_SINCE_LAST_PAYMENT)

    def test_since_last_payment_database_matches_script_parent_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_v2 = Path(tmp) / "work_v2"
            settings = self.make_settings(work_v2, scripts=".")
            adapter = FacturasPdfPowerShellAdapter(settings=settings)
            lookup_script = adapter._last_payment_command("CLIENTE")[-1]
            expected = work_v2.parent / "CANTERA LA HELENA 1.0_be.accdb"
        self.assertIn(f"$dbPath = '{expected}'", lookup_script)
        self.assertNotIn(f"$dbPath = '{work_v2 / 'CANTERA LA HELENA 1.0_be.accdb'}'", lookup_script)

    def test_since_last_payment_returns_legacy_resolution_states_without_generation(self):
        for state in ("SIN_PAGOS", "SIN_CLIENTE", "AMBIGUO"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                runner = SinceRunner(Completed(0, json.dumps({"Estado": state})))
                adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp), runner=runner)
                result = adapter.generar_facturas_pdf(
                    **self.args(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20")
                )
                self.assertTrue(result.success)
                self.assertEqual(result.payload["Estado"], state)
                self.assertEqual(len(runner.calls), 1)

    def test_since_last_payment_adapter_error_is_controlled(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = SinceRunner(Completed(2, "", "error controlado"))
            adapter = FacturasPdfPowerShellAdapter(settings=self.make_settings(tmp), runner=runner)
            result = adapter.generar_facturas_pdf(
                **self.args(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20")
            )
        self.assertFalse(result.success)
        self.assertEqual(result.stderr, "error controlado")

    def test_since_last_payment_rejects_missing_or_old_output(self):
        for old_path in (False, True):
            with self.subTest(old_path=old_path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings = self.make_settings(root)
                stale = settings.paths.outputs / "factura_anterior.pdf"
                if old_path:
                    stale.parent.mkdir()
                    stale.write_bytes(b"%PDF-old")

                def generate(command):
                    path = stale if old_path else Path(command[command.index("-OutDir") + 1]) / "missing.pdf"
                    return Completed(
                        0,
                        json.dumps(
                            {
                                "Estado": "OK",
                                "Archivo": str(path),
                                "TotalComprobantes": 1,
                                "Encontrados": 1,
                                "Faltantes": 0,
                            }
                        ),
                    )

                runner = SinceRunner(
                    Completed(0, json.dumps({"Estado": "OK", "Fecha": "2026-07-03"})),
                    generate,
                )
                adapter = FacturasPdfPowerShellAdapter(settings=settings, runner=runner)
                result = adapter.generar_facturas_pdf(
                    **self.args(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20")
                )
                self.assertFalse(result.success)
                self.assertEqual(list(settings.paths.outputs.glob(".facturas_pdf_*")), [])

    def test_since_last_payment_collision_never_reuses_or_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.make_settings(root)
            existing = settings.paths.outputs / "facturas_cliente.zip"
            existing.parent.mkdir()
            existing.write_bytes(b"PK-current")

            def generate(command):
                current = Path(command[command.index("-OutDir") + 1]) / existing.name
                current.write_bytes(b"PK-current")
                return Completed(
                    0,
                    json.dumps(
                        {
                            "Estado": "OK",
                            "Archivo": str(current),
                            "TotalComprobantes": 2,
                            "Encontrados": 2,
                            "Faltantes": 0,
                        }
                    ),
                )

            runner = SinceRunner(
                Completed(0, json.dumps({"Estado": "OK", "Fecha": "2026-07-03"})),
                generate,
            )
            adapter = FacturasPdfPowerShellAdapter(settings=settings, runner=runner)
            result = adapter.generar_facturas_pdf(
                **self.args(MODE_SINCE_LAST_PAYMENT, cliente="CLIENTE", hasta="2026-07-20")
            )
            self.assertEqual(existing.read_bytes(), b"PK-current")
            self.assertNotEqual(Path(result.file_path), existing)
            self.assertTrue(Path(result.file_path).is_file())
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
