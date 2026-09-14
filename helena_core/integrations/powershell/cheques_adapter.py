from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellChequesResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    timed_out: bool = False


class ChequesPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
        timeout_seconds: int | None = None,
        token_factory: Callable[[], str] = lambda: uuid4().hex,
        clock_ns: Callable[[], int] = time.time_ns,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner
        self.timeout_seconds = timeout_seconds or self.settings.timeouts.default_script_seconds
        self.token_factory = token_factory
        self.clock_ns = clock_ns
        self.today_provider = today_provider

    def _output_path(self, accion: str) -> Path:
        return self.settings.paths.data / "cache" / f"cheques_{accion}_{self.token_factory()}.json"

    def build_command(
        self,
        *,
        accion: str,
        tipo: str,
        filtro_fiscal: str,
        dias: int,
        out_json: Path | None = None,
    ) -> list[str]:
        args: list[object] = ["-Accion", accion, "-Tipo", tipo]
        if accion != "alertas":
            args.extend(["-FiltroFiscal", filtro_fiscal])
        if accion in {"vencimientos", "alertas"}:
            args.extend(["-Dias", str(dias)])
        if out_json is not None:
            args.extend(["-OutJson", str(out_json)])
        return powershell_file_command(
            self.settings.paths.scripts / "gestion_cheques.ps1",
            args,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def _completed_result(
        self,
        *,
        completed: object,
        command: list[str],
        payload: dict[str, Any],
    ) -> PowerShellChequesResult:
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        returncode = int(getattr(completed, "returncode", 1))
        return PowerShellChequesResult(
            success=returncode == 0,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            command=command,
            cwd=str(self.settings.paths.root),
            timeout=self.timeout_seconds,
            payload=payload if returncode == 0 else {},
        )

    def _run(self, command: list[str]) -> object | PowerShellChequesResult:
        try:
            return self.runner(
                command,
                cwd=str(self.settings.paths.root),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return PowerShellChequesResult(
                success=False,
                returncode=-1,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                command=command,
                cwd=str(self.settings.paths.root),
                timeout=self.timeout_seconds,
                payload={},
                timed_out=True,
            )

    @staticmethod
    def _parse_depositables(stdout: str, *, filtro_fiscal: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            raise ValueError("La salida de cheques a cobrar esta vacia.")
        if text == "No hay valores para ese filtro.":
            return {
                "accion": "depositables",
                "filtro_fiscal": filtro_fiscal,
                "vacio": True,
                "texto_legacy": text,
            }
        required = ("Disponible para depositar hoy", "Filtro:", "Fecha:", "TOTAL:")
        if any(marker not in text for marker in required):
            raise ValueError("La salida de cheques a cobrar esta incompleta.")
        fecha = re.search(r"(?im)^Fecha:\s*(.+?)\s*$", text)
        total = re.search(r"(?im)^TOTAL:\s*(.+?)\s*$", text)
        type_rows: dict[str, dict[str, Any]] = {}
        for match in re.finditer(
            r"(?im)^(CHEQUE FISICO|ECHEQ):\s*(\d+),\s*(.+?)\s*$",
            text,
        ):
            type_rows[match.group(1).upper()] = {
                "cantidad": int(match.group(2)),
                "total": match.group(3).strip(),
            }
        if not fecha or not total or set(type_rows) != {"CHEQUE FISICO", "ECHEQ"}:
            raise ValueError("La salida de cheques a cobrar esta incompleta.")
        return {
            "accion": "depositables",
            "filtro_fiscal": filtro_fiscal,
            "vacio": False,
            "fecha_consulta": fecha.group(1).strip(),
            "total": total.group(1).strip(),
            "por_tipo": type_rows,
            "texto_legacy": text,
        }

    @staticmethod
    def _parse_alertas(stdout: str, *, dias: int) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            raise ValueError("La salida de alertas de Cheques esta vacia.")
        if text == "SIN_ALERTAS":
            return {
                "accion": "alertas",
                "plazo_dias": dias,
                "hay_alertas": False,
                "texto_legacy": text,
            }
        if "Cheques proximos a vencer" not in text or "Total:" not in text:
            raise ValueError("La salida de alertas de Cheques esta incompleta.")
        total = re.search(r"(?im)^Total:\s*(.+?)\s*$", text)
        return {
            "accion": "alertas",
            "plazo_dias": dias,
            "hay_alertas": True,
            "total": total.group(1).strip() if total else "",
            "texto_legacy": text,
        }

    def consultar(
        self,
        *,
        accion: str,
        tipo: str,
        filtro_fiscal: str,
        dias: int,
    ) -> PowerShellChequesResult:
        if accion in {"resumen", "vencimientos"}:
            out_json = self._output_path(accion)
            out_json.parent.mkdir(parents=True, exist_ok=True)
            started_ns = self.clock_ns()
            command = self.build_command(
                accion=accion,
                tipo=tipo,
                filtro_fiscal=filtro_fiscal,
                dias=dias,
                out_json=out_json,
            )
            try:
                completed = self._run(command)
                if isinstance(completed, PowerShellChequesResult):
                    return completed
                base = self._completed_result(completed=completed, command=command, payload={})
                if not base.success:
                    return base
                if not out_json.is_file() or out_json.stat().st_mtime_ns < started_ns:
                    base.success = False
                    base.stderr = "El JSON de Cheques no fue generado en la ejecucion actual."
                    return base
                try:
                    data = json.loads(out_json.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError) as exc:
                    base.success = False
                    base.stderr = f"El JSON de Cheques no es valido: {exc}"
                    return base
                required = ("FechaConsulta", "Dias", "Tipo", "FiltroFiscal", "Registros")
                if (
                    not isinstance(data, dict)
                    or any(key not in data for key in required)
                    or not isinstance(data.get("Registros"), list)
                ):
                    base.success = False
                    base.stderr = "El JSON de Cheques esta incompleto."
                    return base
                if str(data.get("FechaConsulta") or "") != self.today_provider().isoformat():
                    base.success = False
                    base.stderr = "El JSON de Cheques no corresponde a la fecha de la ejecucion actual."
                    return base
                try:
                    returned_days = int(data.get("Dias"))
                except (TypeError, ValueError):
                    returned_days = -1
                if (
                    str(data.get("Tipo") or "").upper() != tipo
                    or str(data.get("FiltroFiscal") or "").upper() != filtro_fiscal
                    or (accion == "vencimientos" and returned_days != dias)
                ):
                    base.success = False
                    base.stderr = "El JSON de Cheques no corresponde a la consulta solicitada."
                    return base
                base.payload = {"accion": accion, **data}
                return base
            finally:
                try:
                    out_json.unlink(missing_ok=True)
                except OSError:
                    pass

        command = self.build_command(
            accion=accion,
            tipo=tipo,
            filtro_fiscal=filtro_fiscal,
            dias=dias,
        )
        completed = self._run(command)
        if isinstance(completed, PowerShellChequesResult):
            return completed
        base = self._completed_result(completed=completed, command=command, payload={})
        if not base.success:
            return base
        try:
            if accion == "depositables":
                base.payload = self._parse_depositables(base.stdout, filtro_fiscal=filtro_fiscal)
            else:
                base.payload = self._parse_alertas(base.stdout, dias=dias)
        except ValueError as exc:
            base.success = False
            base.stderr = str(exc)
        return base
