from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellCajaResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    timed_out: bool = False


class CajaPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner

    def build_command(self, *, medio: str, fecha_desde: str, fecha_hasta: str) -> list[str]:
        return powershell_file_command(
            self.settings.paths.scripts / "consultas_rapidas.ps1",
            ["cobros", medio, "-Desde", fecha_desde, "-Hasta", fecha_hasta],
            powershell_executable=self.settings.technical.powershell_executable,
        )

    @staticmethod
    def _parse_output(
        output: str,
        *,
        medio: str,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> dict[str, Any]:
        marker = "Cobros por medio:"
        position = output.find(marker)
        if position < 0:
            raise ValueError("La salida no contiene el encabezado de Caja esperado.")
        text = output[position:].strip()

        header = re.search(r"^Cobros por medio:\s*(.+)$", text, flags=re.MULTILINE)
        period = re.search(
            r"^Periodo:\s*(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})$",
            text,
            flags=re.MULTILINE,
        )
        records = re.search(r"^Registros:\s*(\d+)$", text, flags=re.MULTILINE)
        total = re.search(r"^Total:\s*(.+)$", text, flags=re.MULTILINE)
        if not all((header, period, records, total)):
            raise ValueError("La salida de Caja no contiene todos los campos esperados.")

        requested_from = date.fromisoformat(fecha_desde).strftime("%d/%m/%Y")
        requested_to = (date.fromisoformat(fecha_hasta) - timedelta(days=1)).strftime("%d/%m/%Y")
        if period.group(1) != requested_from or period.group(2) != requested_to:
            raise ValueError("El periodo de la salida de Caja no coincide con el solicitado.")
        if header.group(1).strip().casefold() != medio.upper().casefold():
            raise ValueError("El medio de pago de la salida de Caja no coincide con el solicitado.")

        totals: list[dict[str, Any]] = []
        for line in text.splitlines():
            match = re.match(r"^-\s+([^:]+):\s+(\d+)\s+registros,\s+(.+)$", line.strip())
            if match:
                totals.append(
                    {
                        "medio": match.group(1).strip(),
                        "cantidad_registros": int(match.group(2)),
                        "total": match.group(3).strip(),
                    }
                )

        return {
            "fecha_desde": fecha_desde,
            "fecha_hasta_exclusiva": fecha_hasta,
            "periodo_desde": period.group(1),
            "periodo_hasta": period.group(2),
            "medio": medio,
            "medio_mostrado": header.group(1).strip(),
            "cantidad_registros": int(records.group(1)),
            "total": total.group(1).strip(),
            "medios_de_pago": totals,
            "texto_legacy": text,
        }

    def consultar_cobros(
        self,
        *,
        medio: str,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> PowerShellCajaResult:
        command = self.build_command(
            medio=medio,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        timeout = self.settings.timeouts.long_script_seconds
        cwd = str(self.settings.paths.root)
        try:
            completed = self.runner(
                command,
                cwd=cwd,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return PowerShellCajaResult(
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
            return PowerShellCajaResult(
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
            payload = self._parse_output(
                stdout,
                medio=medio,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        except ValueError as exc:
            return PowerShellCajaResult(
                success=False,
                returncode=returncode,
                stdout=stdout,
                stderr=str(exc),
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
            )
        return PowerShellCajaResult(
            success=True,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            command=command,
            cwd=cwd,
            timeout=timeout,
            payload=payload,
        )
