from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellExecutionResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int


class ClienteSaldoPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner

    def build_command(self, cliente: str) -> list[str]:
        script_path = self.settings.paths.scripts / "cliente_rapido.ps1"
        args = [cliente]
        local_database = self.settings.databases.local_database
        if self.settings.environment.is_development and local_database is not None and local_database.exists():
            args.extend(["-DatabasePath", os.fspath(local_database)])
        return powershell_file_command(
            script_path,
            args,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def consultar_saldo(self, cliente: str) -> PowerShellExecutionResult:
        timeout = self.settings.timeouts.default_script_seconds
        command = self.build_command(cliente)
        cwd = os.fspath(self.settings.paths.root)
        completed = self.runner(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
        )
        returncode = int(getattr(completed, "returncode", 1))
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        return PowerShellExecutionResult(
            success=returncode == 0,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            command=command,
            cwd=cwd,
            timeout=timeout,
        )
