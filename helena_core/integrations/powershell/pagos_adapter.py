from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from combinar_pagos import load_item_rows
from helena_core.business.pagos.propuestas import CAP_ECHEQ_LEGACY
from helena_core.integrations.powershell.cheques_adapter import ChequesPowerShellAdapter
from helena_core.process_runner import powershell_file_command, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


@dataclass
class PowerShellPagosResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    timed_out: bool = False


class PagosPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
        timeout_seconds: int | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner
        self.timeout_seconds = timeout_seconds or self.settings.timeouts.payment_seconds

    def cargar_cartera(self, *, modo: str, filtro_fiscal: str) -> PowerShellPagosResult:
        tipo = {"ECHEQ": "ECHEQ", "CHEQUE": "CHEQUE"}.get(modo, "TODOS")
        adapter = ChequesPowerShellAdapter(
            settings=self.settings,
            runner=self.runner,
            timeout_seconds=self.timeout_seconds,
        )
        technical = adapter.consultar(
            accion="resumen",
            tipo=tipo,
            filtro_fiscal=filtro_fiscal,
            dias=0,
        )
        payload: dict[str, Any] = {}
        stderr = technical.stderr
        success = technical.success
        if success:
            items, load_error = load_item_rows(technical.payload, filtro_fiscal, "dias")
            if load_error and not str(load_error).startswith("No hay valores disponibles"):
                success = False
                stderr = str(load_error)
            else:
                payload = {"items": items, "cantidad": len(items)}
        return PowerShellPagosResult(
            success=success,
            returncode=technical.returncode,
            stdout=technical.stdout,
            stderr=stderr,
            command=technical.command,
            cwd=technical.cwd,
            timeout=technical.timeout,
            payload=payload,
            timed_out=technical.timed_out,
        )

    def build_command(
        self,
        *,
        capability: str,
        importe: float,
        plazo: dict[str, Any],
        modo: str,
        filtro_fiscal: str,
    ) -> list[str]:
        if capability == CAP_ECHEQ_LEGACY:
            script = self.settings.paths.scripts / "armar_pago_echeq.ps1"
            args: list[object] = ["-Importe", str(importe), "-Dias", str(int(plazo["dias"]))]
        else:
            script = self.settings.paths.scripts / "armar_pago_optimo.ps1"
            args = [
                "-Importe",
                str(importe),
                "-Modo",
                modo,
                "-FiltroFiscal",
                filtro_fiscal,
                "-MaxCandidatos",
                "35",
                "-MaxValores",
                "8",
                "-MaxCombinaciones",
                "50000",
            ]
            if plazo["tipo"] == "ACOBRAR":
                args.append("-ACobrar")
            else:
                args.extend(["-Dias", str(int(plazo["dias"]))])
        return powershell_file_command(
            script,
            args,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    @staticmethod
    def _money(value: str) -> float:
        text = str(value or "").strip().replace("$", "").replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        return round(float(text), 2)

    @staticmethod
    def _clean_visible_prefix(value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^[^\w\d$-]+\s*", "", text, flags=re.UNICODE)
        return text.strip()

    @classmethod
    def _parse_selected_cheques(cls, text: str, *, capability: str) -> list[dict[str, Any]]:
        best = re.split(r"(?im)^\s*(?:🥈\s*)?ALTERNATIVA\b", text, maxsplit=1)[0]
        lines = best.splitlines()
        cheques: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            optimal = re.match(
                r"^.*?\b(ECHEQ|CHEQUE F[ÍI]SICO)\b\s+[—-]\s+(.+?)\s+(\S+)\s*$",
                line.strip(),
                flags=re.IGNORECASE,
            )
            legacy = None
            if capability == CAP_ECHEQ_LEGACY:
                legacy = re.match(r"^\s*\d+\)\s+(.+?)\s+(\S+)\s*$", line)
            if not optimal and not legacy:
                continue
            cheque_type = "ECHEQ" if legacy else optimal.group(1).upper().replace("I", "Í", 1)
            bank = (legacy or optimal).group(1 if legacy else 2).strip()
            number = (legacy or optimal).group(2 if legacy else 3).strip()
            following = [cls._clean_visible_prefix(item) for item in lines[index + 1 : index + 5]]
            date_value = next(
                (match.group(1) for item in following if (match := re.search(r"(\d{2}/\d{2}/\d{4})", item))),
                None,
            )
            amount_value = next(
                (
                    cls._money(match.group(1))
                    for item in following
                    if not re.search(r"\d{2}/\d{2}/\d{4}", item)
                    and (match := re.search(r"\$?\s*([0-9][0-9.,]*)\s*$", item))
                ),
                None,
            )
            client = next(
                (
                    item
                    for item in following
                    if item
                    and not re.search(r"\d{2}/\d{2}/\d{4}", item)
                    and not re.search(r"\$?\s*[0-9][0-9.,]*\s*$", item)
                ),
                None,
            )
            cheque = {
                "tipo": cheque_type,
                "numero": number,
                "banco": bank,
            }
            if client:
                cheque["emisor"] = client
            if date_value:
                cheque["fecha_pago"] = date_value
            if amount_value is not None:
                cheque["importe"] = amount_value
            cheques.append(cheque)
        return cheques

    @classmethod
    def _parse_output(cls, output: str, *, capability: str = "") -> dict[str, Any]:
        text = str(output or "").strip()
        if not text:
            raise ValueError("La salida de Pagos esta vacia.")
        valid_no_combination = re.fullmatch(
            r"(?i)no\s+se\s+encuentra\s+combinaci[oó]n\s+de\s+cheques\.?",
            text,
        )
        if not valid_no_combination and not re.search(
            r"(?i)\b(?:pago|no hay|no encontre|no se pudo aplicar)\b",
            text,
        ):
            raise ValueError("La salida de Pagos esta incompleta.")
        totals = re.findall(r"(?im)^\s*Total:\s*\$?\s*([0-9][0-9.,]*)\s*$", text)
        selected = cls._money(totals[0]) if totals else None
        options = []
        for index, total in enumerate(totals, start=1):
            options.append({"orden": index, "total_seleccionado": cls._money(total)})
        return {
            "texto_legacy": text,
            "total_seleccionado": selected,
            "opciones": options,
            "cheques_seleccionados": cls._parse_selected_cheques(text, capability=capability),
        }

    def proponer(
        self,
        *,
        capability: str,
        importe: float,
        plazo: dict[str, Any],
        modo: str,
        filtro_fiscal: str,
    ) -> PowerShellPagosResult:
        command = self.build_command(
            capability=capability,
            importe=importe,
            plazo=plazo,
            modo=modo,
            filtro_fiscal=filtro_fiscal,
        )
        timeout = self.timeout_seconds
        cwd = str(self.settings.paths.root)
        try:
            completed = self.runner(command, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return PowerShellPagosResult(
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
            return PowerShellPagosResult(
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
            payload = self._parse_output(stdout, capability=capability)
        except (TypeError, ValueError) as exc:
            return PowerShellPagosResult(
                success=False,
                returncode=returncode,
                stdout=stdout,
                stderr=str(exc),
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
            )
        return PowerShellPagosResult(
            success=True,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            command=command,
            cwd=cwd,
            timeout=timeout,
            payload=payload,
        )
