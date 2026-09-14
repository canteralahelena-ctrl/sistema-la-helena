from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellIvaResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    timed_out: bool = False


class IvaPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
        timeout_seconds: int | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner
        self.timeout_seconds = timeout_seconds or self.settings.timeouts.long_script_seconds

    def build_command(self, *, anio: int, mes: int) -> list[str]:
        desde = f"{anio:04d}-{mes:02d}-01"
        return powershell_file_command(
            self.settings.paths.scripts / "consultas_rapidas.ps1",
            ["iva-mensual", "-Desde", desde],
            powershell_executable=self.settings.technical.powershell_executable,
        )

    @staticmethod
    def _parse_output(output: str, *, anio: int, mes: int) -> dict[str, Any]:
        parsed_json: dict[str, Any] = {}
        try:
            candidate = json.loads(str(output or ""))
            if isinstance(candidate, dict):
                parsed_json = candidate
        except (TypeError, ValueError):
            pass

        def field(name: str) -> str | None:
            if name in parsed_json:
                value = parsed_json[name]
                return None if value is None else str(value).strip()
            match = re.search(rf"(?im)^\s*{re.escape(name)}\s*[:=]\s*(.+?)\s*$", output)
            return match.group(1).strip() if match else None

        values = {
            "periodo": field("Periodo"),
            "iva_ventas": field("IvaVentas"),
            "iva_gastos": field("IvaGastos"),
            "saldo_iva": field("SaldoIva"),
            "ventas_comprobantes": field("VentasComprobantes"),
            "gastos_comprobantes": field("GastosComprobantes"),
            "detalle_csv": field("DetalleCsv"),
            "resumen": field("Resumen"),
        }
        required = ("periodo", "iva_ventas", "iva_gastos", "saldo_iva")
        if any(values[name] in (None, "") for name in required):
            raise ValueError("La salida de IVA no contiene todos los campos esperados.")
        expected_period = f"{anio:04d}-{mes:02d}"
        if values["periodo"] != expected_period:
            raise ValueError("El periodo de la salida de IVA no coincide con el solicitado.")
        counts: dict[str, int | None] = {}
        for name in ("ventas_comprobantes", "gastos_comprobantes"):
            value = values[name]
            if value in (None, ""):
                counts[name] = None
                continue
            try:
                counts[name] = int(value)
            except ValueError as exc:
                raise ValueError("Las cantidades de comprobantes de IVA no son validas.") from exc

        return {
            "periodo": values["periodo"],
            "iva_ventas": values["iva_ventas"],
            "iva_gastos": values["iva_gastos"],
            "saldo_iva": values["saldo_iva"],
            "ventas_comprobantes": counts["ventas_comprobantes"],
            "gastos_comprobantes": counts["gastos_comprobantes"],
            "detalle_csv": values["detalle_csv"],
            "resumen": values["resumen"],
        }

    def consultar_iva_mensual(self, *, anio: int, mes: int) -> PowerShellIvaResult:
        command = self.build_command(anio=anio, mes=mes)
        timeout = self.timeout_seconds
        cwd = str(self.settings.paths.root)
        try:
            completed = self.runner(
                command,
                cwd=cwd,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return PowerShellIvaResult(
                success=False,
                returncode=-1,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
                timed_out=True,
            )

        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        returncode = int(getattr(completed, "returncode", 1))
        if returncode != 0:
            return PowerShellIvaResult(
                success=False,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
            )
        try:
            payload = self._parse_output(stdout, anio=anio, mes=mes)
        except ValueError as exc:
            return PowerShellIvaResult(
                success=False,
                returncode=returncode,
                stdout=stdout,
                stderr=str(exc),
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
            )
        return PowerShellIvaResult(
            success=True,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            command=command,
            cwd=cwd,
            timeout=timeout,
            payload=payload,
        )
