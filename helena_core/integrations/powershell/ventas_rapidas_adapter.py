from __future__ import annotations

import csv
import os
import re
import subprocess
import time
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellVentasRapidasResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    timed_out: bool = False


class VentasRapidasPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
        token_factory: Callable[[], str] = lambda: uuid4().hex,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner
        self.token_factory = token_factory
        self.clock_ns = clock_ns

    def build_command(self, *, fecha_desde: str, fecha_hasta: str) -> list[str]:
        return powershell_file_command(
            self.settings.paths.scripts / "analisis_categorias.ps1",
            [
                "-AgruparPor",
                "total",
                "-Tipos",
                "Ambos",
                "-Desde",
                fecha_desde,
                "-Hasta",
                fecha_hasta,
            ],
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def build_productos_no_clasificados_command(
        self,
        *,
        fecha_desde: str,
        fecha_hasta: str,
        out_csv: Path,
    ) -> list[str]:
        return powershell_file_command(
            self.settings.paths.scripts / "analisis_categorias.ps1",
            [
                "-AgruparPor",
                "total",
                "-Tipos",
                "Ambos",
                "-Desde",
                fecha_desde,
                "-Hasta",
                fecha_hasta,
                "-OutCsv",
                os.fspath(out_csv),
            ],
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def build_analisis_categorias_command(self) -> list[str]:
        return powershell_file_command(
            self.settings.paths.scripts / "analisis_categorias.ps1",
            powershell_executable=self.settings.technical.powershell_executable,
        )

    @staticmethod
    def _parse_output(output: str, *, fecha_desde: str, fecha_hasta: str) -> dict[str, Any]:
        text = output[output.find("Analisis de categorias comerciales") :] if "Analisis de categorias comerciales" in output else output

        def field(pattern: str) -> str | None:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            return match.group(1).strip() if match else None

        period_match = re.search(
            r"Periodo:\s*(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        values = {
            "total": field(r"Total real ventas:\s*([^\r\n]+)"),
            "facturado": field(r"Facturado real:\s*([^\r\n]+)"),
            "remitos": field(r"Remitos real:\s*([^\r\n]+)"),
            "clasificado": field(r"Clasificado:\s*([^\r\n]+)"),
            "no_clasificado": field(r"No clasificado:\s*([^\r\n]+)"),
        }
        if not period_match or any(value in (None, "") for value in values.values()):
            raise ValueError("La salida no contiene todos los totales esperados.")

        categories: list[dict[str, str]] = []
        seen: set[str] = set()
        valid_codes = ("ARIDOS", "GRAVAS", "SERVICIOS", "OTROS_PRODUCTOS")
        for line in text.splitlines():
            compact = re.sub(r"\s+", " ", line.strip())
            if not compact or "$" not in compact:
                continue
            money_match = re.search(r"(\$\s*-?[\d\.,]+)", compact)
            if not money_match:
                continue
            pct_match = re.search(re.escape(money_match.group(1)) + r"\s+(-?[\d\.,]+%)", compact)
            percentage = pct_match.group(1) if pct_match else "No disponible"
            for code in valid_codes:
                if re.search(rf"\b{re.escape(code)}\b", compact) and code not in seen:
                    seen.add(code)
                    categories.append(
                        {
                            "codigo": code,
                            "importe": money_match.group(1).strip(),
                            "porcentaje": percentage,
                        }
                    )
                    break
            if len(categories) >= 4:
                break

        return {
            "estado": "OK",
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "periodo_desde": period_match.group(1),
            "periodo_hasta": period_match.group(2),
            **values,
            "categorias": categories,
        }

    @staticmethod
    def _decimal_text(value: Any) -> str:
        compact = str(value or "").strip().replace("$", "").replace(" ", "")
        if "." in compact and "," in compact:
            compact = compact.replace(".", "").replace(",", ".")
        elif "," in compact:
            compact = compact.replace(".", "").replace(",", ".")
        try:
            return format(Decimal(compact or "0"), "f")
        except InvalidOperation as exc:
            raise ValueError(f"Importe invalido en CSV: {value}") from exc

    @staticmethod
    def _display_date(value: Any) -> str:
        text = str(value or "").strip()
        for pattern, size in (
            ("%Y-%m-%d", 10),
            ("%d/%m/%Y", 10),
            ("%Y-%m-%dT%H:%M:%S", 19),
        ):
            try:
                return datetime.strptime(text[:size], pattern).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return text[:10] or "-"

    @classmethod
    def _read_no_clasificados_csv(cls, path: Path) -> list[dict[str, Any]]:
        if path.stat().st_size == 0:
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
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
            }
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise ValueError("El CSV NO_CLASIFICADOS no contiene las columnas esperadas.")
            rows = []
            for row in reader:
                product = re.sub(r"\s+", " ", str(row.get("ProductoDescripcionOriginal") or "").strip())
                client = re.sub(r"\s+", " ", str(row.get("Cliente") or "").strip())
                number = (
                    str(row.get("NumeroComprobante") or "").strip()
                    or str(row.get("NumeroFactura") or "").strip()
                    or str(row.get("NumeroRMT") or "").strip()
                    or "s/n"
                )
                rows.append(
                    {
                        "fecha": str(row.get("Fecha") or ""),
                        "fecha_mostrada": cls._display_date(row.get("Fecha")),
                        "tipo_comprobante": str(row.get("TipoComprobante") or "-").strip() or "-",
                        "numero_comprobante": number,
                        "cliente": client or "-",
                        "producto_descripcion": product or "Sin descripción",
                        "cantidad": str(row.get("Cantidad") or "").strip(),
                        "unidad": str(row.get("Unidad") or "").strip(),
                        "importe": cls._decimal_text(row.get("ImporteSinIVA")),
                        "categoria_sugerida": str(row.get("CategoriaSugerida") or "").strip(),
                        "nivel_confianza": str(row.get("NivelConfianza") or "").strip(),
                        "motivo_no_clasificacion": str(row.get("MotivoNoClasificacion") or "").strip(),
                        "observacion_manual": str(row.get("ObservacionManual") or "").strip(),
                    }
                )
            return rows

    @staticmethod
    def _parse_analisis_output(output: str) -> dict[str, Any]:
        parsed = VentasRapidasPowerShellAdapter._parse_output(
            output,
            fecha_desde="",
            fecha_hasta="",
        )
        valid_codes = (
            "SERVICIOS",
            "BENTONITA",
            "FILTROS",
            "CANOS_POCEROS",
            "ANTRACITA",
            "LADRILLOS",
            "ADOQUINES",
            "VIGUETAS",
            "ARIDOS",
            "GRAVAS",
            "OTROS_PRODUCTOS",
        )
        categories = []
        for line in output.splitlines():
            compact = re.sub(r"\s+", " ", line.strip())
            money_match = re.search(r"(\$\s*-?[\d\.,]+)", compact)
            if not money_match:
                continue
            percentage_match = re.search(
                re.escape(money_match.group(1)) + r"\s+(-?[\d\.,]+%)",
                compact,
            )
            if not percentage_match:
                continue
            code = next(
                (item for item in valid_codes if re.search(rf"\b{re.escape(item)}\b", compact)),
                None,
            )
            if not code:
                continue
            period_match = re.match(r"^(TOTAL|\d{4}(?:-\d{2})?)\b", compact)
            categories.append(
                {
                    "periodo": period_match.group(1) if period_match else "",
                    "codigo": code,
                    "importe": money_match.group(1).strip(),
                    "porcentaje": percentage_match.group(1),
                }
            )
        if not categories and Decimal(VentasRapidasPowerShellAdapter._decimal_text(parsed["clasificado"])) != 0:
            raise ValueError("La salida no contiene las categorias esperadas.")
        parsed["fecha_desde"] = datetime.strptime(parsed["periodo_desde"], "%d/%m/%Y").date().isoformat()
        parsed["fecha_hasta"] = datetime.strptime(parsed["periodo_hasta"], "%d/%m/%Y").date().isoformat()
        parsed["categorias"] = categories
        parsed["advertencias"] = [
            line.strip()
            for line in output.splitlines()
            if line.strip().upper().startswith("AVISO:")
        ]
        parsed["texto_resumido"] = output[-3500:]
        return parsed

    def _execute(
        self,
        command: list[str],
        parser: Callable[[str], dict[str, Any]],
    ) -> PowerShellVentasRapidasResult:
        cwd = os.fspath(self.settings.paths.root)
        timeout = self.settings.timeouts.long_script_seconds
        try:
            completed = self.runner(command, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return PowerShellVentasRapidasResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
                timed_out=True,
            )

        returncode = int(getattr(completed, "returncode", 1))
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        payload: dict[str, Any] = {}
        parse_error = ""
        if returncode == 0:
            try:
                payload = parser(stdout)
            except (OSError, UnicodeError, ValueError) as exc:
                parse_error = str(exc)
        return PowerShellVentasRapidasResult(
            success=returncode == 0 and not parse_error,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr or parse_error,
            command=command,
            cwd=cwd,
            timeout=timeout,
            payload=payload,
        )

    def consultar_ventas_rapidas(
        self,
        *,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> PowerShellVentasRapidasResult:
        command = self.build_command(fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        return self._execute(
            command,
            lambda output: self._parse_output(
                output,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            ),
        )

    def consultar_productos_no_clasificados(
        self,
        *,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> PowerShellVentasRapidasResult:
        outputs = self.settings.paths.outputs.resolve()
        outputs.mkdir(parents=True, exist_ok=True)
        token = re.sub(r"[^A-Za-z0-9_-]", "", self.token_factory())
        if not token:
            token = uuid4().hex
        out_csv = outputs / f"productos_no_clasificados_{fecha_desde}_a_{fecha_hasta}_{token}.csv"
        generated = (
            out_csv,
            out_csv.with_suffix(".fuentes.csv"),
            out_csv.with_suffix(".detalle.csv"),
            out_csv.with_suffix(".no_clasificados.csv"),
        )
        command = self.build_productos_no_clasificados_command(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            out_csv=out_csv,
        )
        started_ns = self.clock_ns()

        def parse(output: str) -> dict[str, Any]:
            for path in generated:
                resolved = path.resolve()
                if resolved.parent != outputs:
                    raise ValueError("El CSV generado queda fuera de la raiz autorizada.")
                if not resolved.is_file():
                    raise ValueError(f"No se genero el archivo esperado: {resolved.name}")
                if resolved.stat().st_mtime_ns < started_ns - 2_000_000_000:
                    raise ValueError(f"El archivo generado no corresponde a la ejecucion actual: {resolved.name}")
            rows = self._read_no_clasificados_csv(generated[-1])
            return {
                "estado": "OK",
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "registros": rows,
                "cantidad_total": len(rows),
                "advertencias": [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip().upper().startswith("AVISO:")
                ],
                "archivo_csv": os.fspath(generated[-1]),
                "archivos_generados": [os.fspath(path) for path in generated],
            }

        if any(path.exists() for path in generated):
            return PowerShellVentasRapidasResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="Ya existe un archivo para el identificador de esta ejecucion.",
                command=command,
                cwd=os.fspath(self.settings.paths.root),
                timeout=self.settings.timeouts.long_script_seconds,
                payload={},
            )
        return self._execute(command, parse)

    def consultar_analisis_categorias(self) -> PowerShellVentasRapidasResult:
        return self._execute(
            self.build_analisis_categorias_command(),
            self._parse_analisis_output,
        )
