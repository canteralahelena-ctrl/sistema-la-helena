from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from helena_core.business.clientes.estado_pdf import (
    MODE_OPEN_BALANCE,
    MODE_RANGE,
    MODE_SINCE_LAST_PAYMENT,
)
from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellPdfExecutionResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    file_path: str
    timed_out: bool = False


class EstadoCuentaPdfPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner

    def build_command(
        self,
        *,
        cliente: str,
        modo: str,
        desde: str | None,
        hasta: str | None,
        nombre_archivo: str,
    ) -> list[str]:
        output_name = Path(nombre_archivo)
        if output_name.name != nombre_archivo or output_name.suffix.lower() != ".pdf":
            raise ValueError("El nombre de salida debe ser un archivo PDF sin ruta.")
        action_by_mode = {
            MODE_RANGE: "estado-pdf",
            MODE_OPEN_BALANCE: "estado-pdf-abierto",
            MODE_SINCE_LAST_PAYMENT: "estado-pdf-ultimo-pago",
        }
        if modo not in action_by_mode:
            raise ValueError("Modo de estado PDF no soportado.")

        args: list[object] = [action_by_mode[modo], cliente]
        if modo == MODE_RANGE:
            args.extend(["-Desde", desde or ""])
            if hasta:
                args.extend(["-Hasta", hasta])
        args.extend(["-Archivo", nombre_archivo])
        return powershell_file_command(
            self.settings.paths.scripts / "consultas_rapidas.ps1",
            args,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def generar_estado_pdf(
        self,
        *,
        cliente: str,
        modo: str,
        desde: str | None,
        hasta: str | None,
        nombre_archivo: str,
    ) -> PowerShellPdfExecutionResult:
        timeout = self.settings.timeouts.export_script_seconds
        command = self.build_command(
            cliente=cliente,
            modo=modo,
            desde=desde,
            hasta=hasta,
            nombre_archivo=nombre_archivo,
        )
        cwd = os.fspath(self.settings.paths.root)
        expected_file = self.settings.paths.outputs / Path(nombre_archivo).name
        try:
            completed = self.runner(command, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return PowerShellPdfExecutionResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                command=command,
                cwd=cwd,
                timeout=timeout,
                file_path=os.fspath(expected_file),
                timed_out=True,
            )

        returncode = int(getattr(completed, "returncode", 1))
        return PowerShellPdfExecutionResult(
            success=returncode == 0,
            returncode=returncode,
            stdout=str(getattr(completed, "stdout", "") or "").strip(),
            stderr=str(getattr(completed, "stderr", "") or "").strip(),
            command=command,
            cwd=cwd,
            timeout=timeout,
            file_path=os.fspath(expected_file),
        )
