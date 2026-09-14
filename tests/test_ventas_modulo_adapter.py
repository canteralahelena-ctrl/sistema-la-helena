import csv
import json
import os
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


REPORT = """Analisis de categorias comerciales
Periodo: 01/01/2026 al 23/07/2026
Total real ventas: $ 1.000,00
Facturado real: $ 800,00
Remitos real: $ 200,00
Clasificado: $ 900,00
No clasificado: $ 100,00

Periodo LineaNegocio Importe %
2026-01 ARIDOS $ 600,00 66,67%
2026-01 SERVICIOS $ 300,00 33,33%
AVISO: Existen 1 productos/servicios no clasificados.
"""

HEADERS = [
    "Fecha",
    "TipoComprobante",
    "NumeroComprobante",
    "NumeroFactura",
    "NumeroRMT",
    "Cliente",
    "ProductoDescripcionOriginal",
    "Cantidad",
    "Unidad",
    "ImporteSinIVA",
    "CategoriaSugerida",
    "NivelConfianza",
    "MotivoNoClasificacion",
    "ObservacionManual",
]


class Runner:
    def __init__(self, callback=None, completed=None, raises=None):
        self.callback = callback
        self.completed = completed or Completed(0, REPORT)
        self.raises = raises
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise self.raises
        if self.callback:
            self.callback(command)
        return self.completed


class VentasModuloAdapterTests(unittest.TestCase):
    def settings(self, root):
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

    def write_outputs(self, command, rows=None, invalid=False, omit=None):
        out = Path(command[command.index("-OutCsv") + 1])
        paths = [
            out,
            out.with_suffix(".fuentes.csv"),
            out.with_suffix(".detalle.csv"),
            out.with_suffix(".no_clasificados.csv"),
        ]
        for path in paths:
            if path.name == omit:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path == paths[-1]:
                if invalid:
                    path.write_text("columna_invalida\nvalor\n", encoding="utf-8")
                elif rows:
                    with path.open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=HEADERS)
                        writer.writeheader()
                        writer.writerows(rows)
                else:
                    path.write_bytes(b"")
            else:
                path.write_bytes(b"")

    def row(self):
        return {
            "Fecha": "2026-07-01",
            "TipoComprobante": "FT A",
            "NumeroComprobante": "0001",
            "NumeroFactura": "0001",
            "NumeroRMT": "",
            "Cliente": "CLIENTE Á",
            "ProductoDescripcionOriginal": "Árido especial",
            "Cantidad": "2",
            "Unidad": "TN",
            "ImporteSinIVA": "1.234,50",
            "CategoriaSugerida": "",
            "NivelConfianza": "",
            "MotivoNoClasificacion": "Pendiente",
            "ObservacionManual": "",
        }

    def adapter(self, settings, runner):
        return VentasRapidasPowerShellAdapter(
            settings=settings,
            runner=runner,
            token_factory=lambda: "ejecucion_actual",
            clock_ns=lambda: 0,
        )

    def test_products_uses_exact_command_and_reads_current_utf8_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            runner = Runner(callback=lambda command: self.write_outputs(command, [self.row()]))
            result = self.adapter(settings, runner).consultar_productos_no_clasificados(
                fecha_desde="2026-07-01", fecha_hasta="2026-07-20"
            )
            command = runner.calls[0][0]
        self.assertTrue(result.success)
        self.assertEqual(Path(command[5]), settings.paths.scripts / "analisis_categorias.ps1")
        self.assertEqual(
            command[-10:-2],
            ["-AgruparPor", "total", "-Tipos", "Ambos", "-Desde", "2026-07-01", "-Hasta", "2026-07-20"],
        )
        self.assertEqual(command[-2], "-OutCsv")
        self.assertNotIn("\\work\\", str(Path(command[5])).lower())
        self.assertEqual(result.payload["registros"][0]["producto_descripcion"], "Árido especial")
        self.assertEqual(result.payload["registros"][0]["importe"], "1234.50")
        self.assertEqual(result.payload["registros"][0]["numero_comprobante"], "0001")

    def test_products_accepts_empty_file_and_rejects_missing_invalid_or_old_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            empty = self.adapter(
                settings, Runner(callback=lambda command: self.write_outputs(command))
            ).consultar_productos_no_clasificados(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertTrue(empty.success)
        self.assertEqual(empty.payload["registros"], [])

        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            missing_runner = Runner(
                callback=lambda command: self.write_outputs(
                    command,
                    omit=Path(command[command.index("-OutCsv") + 1]).with_suffix(".no_clasificados.csv").name,
                )
            )
            missing = self.adapter(settings, missing_runner).consultar_productos_no_clasificados(
                fecha_desde="2026-07-01", fecha_hasta="2026-07-20"
            )
        self.assertFalse(missing.success)
        self.assertIn("No se genero", missing.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            invalid = self.adapter(
                settings, Runner(callback=lambda command: self.write_outputs(command, invalid=True))
            ).consultar_productos_no_clasificados(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertFalse(invalid.success)
        self.assertIn("columnas esperadas", invalid.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            old = settings.paths.outputs / "productos_no_clasificados_2026-07-01_a_2026-07-20_ejecucion_actual.csv"
            old.parent.mkdir()
            old.write_bytes(b"viejo")
            runner = Runner()
            collision = self.adapter(settings, runner).consultar_productos_no_clasificados(
                fecha_desde="2026-07-01", fecha_hasta="2026-07-20"
            )
        self.assertFalse(collision.success)
        self.assertEqual(runner.calls, [])

    def test_products_timeout_and_powershell_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            timeout = self.adapter(
                settings,
                Runner(raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=241)),
            ).consultar_productos_no_clasificados(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
            failed = self.adapter(
                settings,
                Runner(completed=Completed(1, "", "fallo controlado")),
            ).consultar_productos_no_clasificados(fecha_desde="2026-07-01", fecha_hasta="2026-07-20")
        self.assertTrue(timeout.timed_out)
        self.assertFalse(failed.success)
        self.assertEqual(failed.stderr, "fallo controlado")

    def test_products_rejects_files_with_old_timestamp(self):
        def write_old(command):
            self.write_outputs(command, [self.row()])
            out = Path(command[command.index("-OutCsv") + 1])
            for path in (
                out,
                out.with_suffix(".fuentes.csv"),
                out.with_suffix(".detalle.csv"),
                out.with_suffix(".no_clasificados.csv"),
            ):
                os.utime(path, ns=(1_000_000_000, 1_000_000_000))

        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            adapter = VentasRapidasPowerShellAdapter(
                settings=settings,
                runner=Runner(callback=write_old),
                token_factory=lambda: "ejecucion_actual",
                clock_ns=lambda: 10_000_000_000,
            )
            result = adapter.consultar_productos_no_clasificados(
                fecha_desde="2026-07-01", fecha_hasta="2026-07-20"
            )
        self.assertFalse(result.success)
        self.assertIn("no corresponde a la ejecucion actual", result.stderr)

    def test_analysis_uses_legacy_no_argument_command_and_structures_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            runner = Runner()
            result = self.adapter(settings, runner).consultar_analisis_categorias()
            command = runner.calls[0][0]
        self.assertTrue(result.success)
        self.assertEqual(Path(command[5]), settings.paths.scripts / "analisis_categorias.ps1")
        self.assertEqual(command[-2:], ["-File", str(settings.paths.scripts / "analisis_categorias.ps1")])
        self.assertEqual(result.payload["total"], "$ 1.000,00")
        self.assertEqual([row["codigo"] for row in result.payload["categorias"]], ["ARIDOS", "SERVICIOS"])
        self.assertEqual(result.payload["categorias"][0]["porcentaje"], "66,67%")
        self.assertEqual(result.payload["advertencias"], ["AVISO: Existen 1 productos/servicios no clasificados."])

    def test_analysis_preserves_legacy_3500_character_truncation(self):
        output = ("prefijo\n" * 600) + REPORT
        with tempfile.TemporaryDirectory() as tmp:
            result = self.adapter(
                self.settings(tmp), Runner(completed=Completed(0, output))
            ).consultar_analisis_categorias()
        self.assertTrue(result.success)
        self.assertEqual(len(result.payload["texto_resumido"]), 3500)
        self.assertTrue(result.payload["texto_resumido"].endswith(REPORT.strip()))

    def test_analysis_accepts_period_without_sales(self):
        no_sales = """Analisis de categorias comerciales
Periodo: 01/01/2026 al 23/07/2026
Total real ventas: $ 0,00
Facturado real: $ 0,00
Remitos real: $ 0,00
Clasificado: $ 0,00
No clasificado: $ 0,00
"""
        with tempfile.TemporaryDirectory() as tmp:
            result = self.adapter(
                self.settings(tmp), Runner(completed=Completed(0, no_sales))
            ).consultar_analisis_categorias()
        self.assertTrue(result.success)
        self.assertEqual(result.payload["categorias"], [])

    def test_analysis_rejects_invalid_output_timeout_and_script_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            invalid = self.adapter(
                settings, Runner(completed=Completed(0, "salida incompleta"))
            ).consultar_analisis_categorias()
            timeout = self.adapter(
                settings,
                Runner(raises=subprocess.TimeoutExpired(cmd="pwsh-test", timeout=241)),
            ).consultar_analisis_categorias()
            failed = self.adapter(
                settings, Runner(completed=Completed(1, "", "fallo"))
            ).consultar_analisis_categorias()
        self.assertFalse(invalid.success)
        self.assertTrue(timeout.timed_out)
        self.assertEqual(failed.stderr, "fallo")


if __name__ == "__main__":
    unittest.main()
