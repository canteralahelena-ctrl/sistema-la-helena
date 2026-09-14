from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import date
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from helena_core.business.clientes.facturas_pdf import (
    MODE_BY_NUMBER,
    MODE_BY_PERIOD,
    MODE_LATEST,
    MODE_SINCE_LAST_PAYMENT,
)
from helena_core.process_runner import powershell_file_command, powershell_inline_command, ps_quote, run_text_subprocess
from helena_core.settings import AppSettings, load_settings


DEFAULT_FACTURAS_PDF_ROOT = Path(
    r"\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\FACTURAS_EJEMPLO\02_FACTURACION SOCIEDAD"
)


@dataclass
class PowerShellFacturasPdfResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str
    timeout: int
    payload: dict[str, Any]
    file_path: str
    request_signature: dict[str, Any]
    timed_out: bool = False


class FacturasPdfPowerShellAdapter:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        runner: Callable[..., object] = run_text_subprocess,
        source_pdf_root: Path | str = DEFAULT_FACTURAS_PDF_ROOT,
        copier: Callable[..., Any] = shutil.copy2,
    ) -> None:
        self.settings = settings or load_settings()
        self.runner = runner
        self.source_pdf_root = Path(source_pdf_root)
        self.copier = copier

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _fingerprint(cls, path: Path) -> tuple[int, int, str]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns, cls._hash_file(path)

    @classmethod
    def _snapshot_output_pdfs(cls, outputs: Path) -> dict[Path, tuple[int, int, str] | None]:
        if not outputs.exists():
            return {}
        snapshot: dict[Path, tuple[int, int, str] | None] = {}
        for path in outputs.rglob("*.pdf"):
            resolved = path.resolve(strict=False)
            try:
                if path.is_file():
                    snapshot[resolved] = cls._fingerprint(path)
            except OSError:
                snapshot[resolved] = None
        return snapshot

    @staticmethod
    def _plain_text(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").upper())
        return "".join(character for character in text if not unicodedata.combining(character))

    @classmethod
    def _canonical_type(cls, value: Any) -> str | None:
        compact = re.sub(r"[^A-Z0-9]", "", cls._plain_text(value))
        aliases = {
            "A": "FTS_A",
            "FTA": "FTS_A",
            "FTSA": "FTS_A",
            "FACTURAA": "FTS_A",
            "B": "FTS_B",
            "FTB": "FTS_B",
            "FTSB": "FTS_B",
            "FACTURAB": "FTS_B",
            "FPA": "FP_A",
            "FPB": "FP_B",
            "NCA": "NCS_A",
            "NCSA": "NCS_A",
            "NOTACREDITOA": "NCS_A",
            "NCB": "NCS_B",
            "NCSB": "NCS_B",
            "NOTACREDITOB": "NCS_B",
            "NDA": "ND_A",
            "NOTADEBITOA": "ND_A",
            "NDB": "ND_B",
            "NOTADEBITOB": "ND_B",
        }
        return aliases.get(compact)

    @classmethod
    def _type_from_file_name(cls, path: Path) -> str | None:
        compact = re.sub(r"[^A-Z0-9]", "", cls._plain_text(path.stem))
        prefixes = (
            ("FACTURAA", "FP_A"),
            ("FACTURAB", "FP_B"),
            ("FTA", "FTS_A"),
            ("FTB", "FTS_B"),
            ("NCA", "NCS_A"),
            ("NCB", "NCS_B"),
            ("NDA", "ND_A"),
            ("NDB", "ND_B"),
        )
        for prefix, canonical in prefixes:
            if compact.startswith(prefix):
                return canonical
        return None

    @staticmethod
    def _access_number(value: Any) -> tuple[int, int, int]:
        digits = re.sub(r"\D", "", str(value or ""))
        if not digits:
            raise ValueError("No se pudo validar el numero solicitado.")
        access_number = int(digits)
        if access_number < 100000000:
            access_number += 200000000
        return access_number, access_number // 100000000, access_number % 100000000

    @staticmethod
    def _number_from_file_name(path: Path) -> tuple[int, int] | None:
        match = re.search(r"(\d+)[_\-\s]+(\d+)$", path.stem)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @classmethod
    def _validate_number_correspondence(
        cls,
        source: Path,
        *,
        tipo: str | None,
        numero: str | None,
        payload: dict[str, Any],
    ) -> None:
        expected_access, expected_point, expected_sequence = cls._access_number(numero)
        caption = str(payload.get("Caption") or "").strip()
        caption_match = re.match(r"^PDF encontrado:\s*(.+?)\s+(\d+)\s*$", caption, flags=re.IGNORECASE)
        caption_type = None
        if caption_match:
            caption_type = cls._canonical_type(caption_match.group(1))
            if caption_type is None or int(caption_match.group(2)) != expected_access:
                raise ValueError("El PDF devuelto no corresponde al tipo o numero solicitado.")

        requested_type = cls._canonical_type(tipo) if tipo else None
        file_type = cls._type_from_file_name(source)
        effective_type = caption_type or file_type
        if effective_type is None:
            raise ValueError("No se pudo verificar el tipo del comprobante devuelto.")
        if requested_type is not None and effective_type != requested_type:
            raise ValueError("El PDF devuelto no corresponde al tipo solicitado.")
        if caption_type is not None and file_type is not None and caption_type != file_type:
            raise ValueError("El tipo informado no coincide con el nombre del PDF.")

        file_number = cls._number_from_file_name(source)
        if file_number is None:
            if caption_match is None:
                raise ValueError("No se pudo verificar el numero del comprobante devuelto.")
        elif file_number != (expected_point, expected_sequence):
            raise ValueError("El nombre del PDF no corresponde al numero solicitado.")

    @classmethod
    def _same_content(cls, left: Path, right: Path) -> bool:
        try:
            if left.stat().st_size != right.stat().st_size:
                return False
            return cls._hash_file(left) == cls._hash_file(right)
        except OSError:
            return False

    @classmethod
    def _collision_safe_destination(
        cls,
        outputs: Path,
        source: Path,
        *,
        reuse_identical: bool = True,
    ) -> tuple[Path, bool]:
        preferred = outputs / source.name
        if not preferred.exists():
            return preferred, False
        if reuse_identical and cls._same_content(source, preferred):
            return preferred, True

        source_hash = cls._hash_file(source)[:12]
        candidate = outputs / f"{source.stem}__{source_hash}{source.suffix.lower()}"
        counter = 1
        while candidate.exists():
            if reuse_identical and cls._same_content(source, candidate):
                return candidate, True
            candidate = outputs / f"{source.stem}__{source_hash}_{counter}{source.suffix.lower()}"
            counter += 1
        return candidate, False

    def _atomic_copy(self, source: Path, destination: Path) -> Path:
        temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
        try:
            self.copier(source, temporary)
            if not temporary.exists() or not temporary.is_file() or temporary.stat().st_size <= 0:
                raise ValueError("La copia temporal no es un archivo valido.")
            if not self._same_content(source, temporary):
                raise ValueError("La copia temporal no coincide con el archivo original.")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if self._same_content(source, destination):
                    return destination.resolve(strict=False)
                raise ValueError("El destino aparecio durante la copia y contiene otro archivo.")
            temporary.unlink()
            return destination.resolve(strict=False)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _signature(
        *,
        modo: str,
        cliente: str | None,
        tipo: str | None,
        numero: str | None,
        desde: str | None,
        hasta: str | None,
        cantidad: int | None,
    ) -> dict[str, Any]:
        return {
            "modo": modo,
            "cliente": cliente,
            "tipo": tipo,
            "numero": numero,
            "desde": desde,
            "hasta": hasta,
            "cantidad": cantidad,
        }

    def build_command(
        self,
        *,
        modo: str,
        cliente: str | None,
        tipo: str | None,
        numero: str | None,
        desde: str | None,
        hasta: str | None,
        cantidad: int | None,
    ) -> list[str]:
        if modo == MODE_BY_NUMBER:
            args: list[object] = ["-Accion", "factura", "-Tipo", tipo or "", "-Numero", numero or ""]
        elif modo == MODE_BY_PERIOD:
            args = [
                "-Accion",
                "cliente",
                "-Cliente",
                cliente or "",
                "-Desde",
                desde or "",
                "-Hasta",
                hasta or "",
            ]
        elif modo == MODE_LATEST:
            args = ["-Accion", "ultimas-cliente", "-Cliente", cliente or "", "-Cantidad", cantidad or 1]
        else:
            raise ValueError("Modo de facturas PDF no soportado.")
        return powershell_file_command(
            self.settings.paths.scripts / "facturas_pdf.ps1",
            args,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def _last_payment_command(self, cliente: str) -> list[str]:
        database = (
            self.settings.databases.local_database
            or self.settings.paths.scripts.parent / "CANTERA LA HELENA 1.0_be.accdb"
        )
        script = fr"""
$ErrorActionPreference = "Stop"
$dbPath = {ps_quote(database)}
$client = {ps_quote(cliente)}
function Rows($rs, [int]$max = 20) {{
    $rows = @()
    while (-not $rs.EOF -and $rows.Count -lt $max) {{
        $row = [ordered]@{{}}
        for ($i = 0; $i -lt $rs.Fields.Count; $i++) {{
            $row[$rs.Fields.Item($i).Name] = $rs.Fields.Item($i).Value
        }}
        $rows += [pscustomobject]$row
        $rs.MoveNext()
    }}
    return $rows
}}
function Query($connection, [string]$sql, [int]$type, $value, [int]$size = 0) {{
    $command = New-Object -ComObject ADODB.Command
    $command.ActiveConnection = $connection
    $command.CommandText = $sql
    $parameter = $command.CreateParameter()
    $parameter.Name = "@value"
    $parameter.Type = $type
    $parameter.Direction = 1
    if ($size -gt 0) {{ $parameter.Size = $size }}
    $parameter.Value = $value
    [void]$command.Parameters.Append($parameter)
    return $command.Execute()
}}
$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")
try {{
    if ($client -match '^\d+$') {{
        $clients = Rows (Query $conn "SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial FROM CLIENTES WHERE IdCLIENTE = ?" 3 ([int]$client)) 2
    }} else {{
        $clients = Rows (Query $conn "SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial FROM CLIENTES WHERE [RAZ SOCIAL] LIKE ? ORDER BY [RAZ SOCIAL]" 202 ("%" + $client + "%") 255) 2
    }}
    if ($clients.Count -eq 0) {{
        [pscustomobject]@{{ Estado = "SIN_CLIENTE" }} | ConvertTo-Json -Compress
        return
    }}
    if ($clients.Count -gt 1) {{
        [pscustomobject]@{{ Estado = "AMBIGUO" }} | ConvertTo-Json -Compress
        return
    }}
    $id = [int]$clients[0].IdCLIENTE
    $payments = Rows (Query $conn "SELECT TOP 1 IdPAGO, FECHA, MONTO, TIPO FROM PAGOS WHERE IdCLIENTE = ? ORDER BY FECHA DESC, IdPAGO DESC" 3 $id) 1
    if ($payments.Count -eq 0) {{
        [pscustomobject]@{{ Estado = "SIN_PAGOS"; Cliente = $clients[0].RazonSocial }} | ConvertTo-Json -Compress
        return
    }}
    [pscustomobject]@{{
        Estado = "OK"
        Cliente = $clients[0].RazonSocial
        Fecha = ([datetime]$payments[0].FECHA).ToString("yyyy-MM-dd")
        IdPago = $payments[0].IdPAGO
        Tipo = $payments[0].TIPO
    }} | ConvertTo-Json -Compress
}}
finally {{
    if ($conn.State -eq 1) {{ $conn.Close() }}
}}
"""
        return powershell_inline_command(
            script,
            powershell_executable=self.settings.technical.powershell_executable,
        )

    def _stage_current_result(self, path_value: Any, run_directory: Path) -> Path:
        source = Path(str(path_value or "")).resolve(strict=True)
        run_root = run_directory.resolve(strict=True)
        source.relative_to(run_root)
        if not source.is_file() or source.suffix.lower() not in {".pdf", ".zip"} or source.stat().st_size <= 0:
            raise ValueError("El archivo generado en esta ejecucion no es valido.")
        self.settings.paths.outputs.mkdir(parents=True, exist_ok=True)
        destination, reusable = self._collision_safe_destination(
            self.settings.paths.outputs,
            source,
            reuse_identical=False,
        )
        if reusable:
            raise ValueError("No se permite reutilizar un archivo anterior.")
        return self._atomic_copy(source, destination)

    @staticmethod
    def _parse_json_result(completed: object) -> tuple[int, str, str, dict[str, Any], str]:
        returncode = int(getattr(completed, "returncode", 1))
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        payload: dict[str, Any] = {}
        parse_error = ""
        if stdout:
            try:
                parsed = json.loads(stdout.lstrip("\ufeff"))
                if isinstance(parsed, dict):
                    payload = parsed
                else:
                    parse_error = "La salida del script no es un objeto JSON."
            except json.JSONDecodeError:
                parse_error = "La salida del script no contiene JSON valido."
        elif returncode == 0:
            parse_error = "El script no devolvio contenido."
        return returncode, stdout, stderr, payload, parse_error

    def _generar_since_last_payment(
        self,
        *,
        signature: dict[str, Any],
    ) -> PowerShellFacturasPdfResult:
        cliente = str(signature["cliente"] or "")
        lookup_command = self._last_payment_command(cliente)
        cwd = os.fspath(self.settings.paths.root)
        lookup_timeout = self.settings.timeouts.default_script_seconds
        try:
            lookup_completed = self.runner(
                lookup_command,
                cwd=cwd,
                capture_output=True,
                timeout=lookup_timeout,
            )
        except subprocess.TimeoutExpired:
            return PowerShellFacturasPdfResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                command=lookup_command,
                cwd=cwd,
                timeout=lookup_timeout,
                payload={},
                file_path="",
                request_signature=signature,
                timed_out=True,
            )

        returncode, stdout, stderr, payment, parse_error = self._parse_json_result(lookup_completed)
        if returncode != 0 or parse_error:
            return PowerShellFacturasPdfResult(
                success=False,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr or parse_error,
                command=lookup_command,
                cwd=cwd,
                timeout=lookup_timeout,
                payload=payment,
                file_path="",
                request_signature=signature,
            )

        payment_state = str(payment.get("Estado") or "").upper()
        messages = {
            "SIN_PAGOS": "No encontré un último pago para ese cliente.",
            "SIN_CLIENTE": "No encontré el cliente indicado.",
            "AMBIGUO": "Encontré varios clientes parecidos. Indicá el cliente con más detalle.",
        }
        if payment_state != "OK":
            payment["Mensaje"] = messages.get(payment_state, "No se pudo determinar el último pago.")
            return PowerShellFacturasPdfResult(
                success=True,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                command=lookup_command,
                cwd=cwd,
                timeout=lookup_timeout,
                payload=payment,
                file_path="",
                request_signature=signature,
            )

        try:
            payment_date = date.fromisoformat(str(payment.get("Fecha") or ""))
        except ValueError:
            payment = {**payment, "Estado": "SIN_PAGOS", "Mensaje": messages["SIN_PAGOS"]}
            return PowerShellFacturasPdfResult(
                success=True,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                command=lookup_command,
                cwd=cwd,
                timeout=lookup_timeout,
                payload=payment,
                file_path="",
                request_signature=signature,
            )

        outputs = self.settings.paths.outputs
        outputs.mkdir(parents=True, exist_ok=True)
        run_directory = outputs / f".facturas_pdf_{uuid4().hex}"
        run_directory.mkdir(exist_ok=False)
        period_signature = {
            **signature,
            "modo": MODE_BY_PERIOD,
            "desde": payment_date.isoformat(),
        }
        generation_command = self.build_command(**period_signature) + ["-OutDir", os.fspath(run_directory)]
        timeout = self.settings.timeouts.long_script_seconds
        try:
            try:
                completed = self.runner(
                    generation_command,
                    cwd=cwd,
                    capture_output=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return PowerShellFacturasPdfResult(
                    success=False,
                    returncode=-1,
                    stdout="",
                    stderr="",
                    command=generation_command,
                    cwd=cwd,
                    timeout=timeout,
                    payload={},
                    file_path="",
                    request_signature=signature,
                    timed_out=True,
                )

            returncode, stdout, stderr, payload, parse_error = self._parse_json_result(completed)
            payload.update(
                {
                    "FechaUltimoPago": payment_date.isoformat(),
                }
            )
            payload.setdefault("Cliente", payment.get("Cliente"))
            file_path = str(payload.get("Archivo") or "")
            success = returncode == 0 and not parse_error
            if success and str(payload.get("Estado") or "").upper() == "OK":
                try:
                    file_path = os.fspath(self._stage_current_result(file_path, run_directory))
                    payload["Archivo"] = file_path
                except (OSError, RuntimeError, ValueError) as exc:
                    success = False
                    parse_error = f"No se pudo preparar el archivo solicitado: {exc}"
            return PowerShellFacturasPdfResult(
                success=success,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr or parse_error,
                command=generation_command,
                cwd=cwd,
                timeout=timeout,
                payload=payload,
                file_path=file_path,
                request_signature=signature,
            )
        finally:
            shutil.rmtree(run_directory, ignore_errors=True)

    def _stage_number_pdf(
        self,
        path_value: Any,
        *,
        tipo: str | None,
        numero: str | None,
        payload: dict[str, Any],
        outputs_before: dict[Path, tuple[int, int, str] | None],
    ) -> Path:
        source = Path(str(path_value or "")).resolve(strict=True)
        source_root = self.source_pdf_root.resolve(strict=False)
        outputs = self.settings.paths.outputs.resolve(strict=False)
        if not source.is_file() or source.suffix.lower() != ".pdf" or source.stat().st_size <= 0:
            raise ValueError("El PDF encontrado no es un archivo valido.")
        self._validate_number_correspondence(source, tipo=tipo, numero=numero, payload=payload)
        try:
            source.relative_to(outputs)
            if source in outputs_before:
                previous = outputs_before[source]
                if previous is None or self._fingerprint(source) == previous:
                    raise ValueError("El PDF de outputs ya existia y no cambio durante esta ejecucion.")
            return source
        except ValueError:
            if source in outputs_before:
                raise
            try:
                source.relative_to(outputs)
                return source
            except ValueError:
                pass
        source.relative_to(source_root)
        self.settings.paths.outputs.mkdir(parents=True, exist_ok=True)
        destination, reusable = self._collision_safe_destination(self.settings.paths.outputs, source)
        if reusable:
            return destination.resolve(strict=False)
        return self._atomic_copy(source, destination)

    def generar_facturas_pdf(
        self,
        *,
        modo: str,
        cliente: str | None,
        tipo: str | None,
        numero: str | None,
        desde: str | None,
        hasta: str | None,
        cantidad: int | None,
    ) -> PowerShellFacturasPdfResult:
        signature = self._signature(
            modo=modo,
            cliente=cliente,
            tipo=tipo,
            numero=numero,
            desde=desde,
            hasta=hasta,
            cantidad=cantidad,
        )
        if modo == MODE_SINCE_LAST_PAYMENT:
            return self._generar_since_last_payment(signature=signature)
        command = self.build_command(**signature)
        outputs_before = (
            self._snapshot_output_pdfs(self.settings.paths.outputs) if modo == MODE_BY_NUMBER else {}
        )
        timeout = (
            self.settings.timeouts.default_script_seconds
            if modo == MODE_BY_NUMBER
            else self.settings.timeouts.long_script_seconds
        )
        cwd = os.fspath(self.settings.paths.root)
        try:
            completed = self.runner(command, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return PowerShellFacturasPdfResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                command=command,
                cwd=cwd,
                timeout=timeout,
                payload={},
                file_path="",
                request_signature=signature,
                timed_out=True,
            )

        returncode, stdout, stderr, payload, parse_error = self._parse_json_result(completed)

        file_path = str(payload.get("Archivo") or "")
        success = returncode == 0 and not parse_error
        if success and modo == MODE_BY_NUMBER and str(payload.get("Estado") or "").upper() == "OK":
            try:
                file_path = os.fspath(
                    self._stage_number_pdf(
                        file_path,
                        tipo=tipo,
                        numero=numero,
                        payload=payload,
                        outputs_before=outputs_before,
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                success = False
                parse_error = f"No se pudo preparar el PDF solicitado: {exc}"

        return PowerShellFacturasPdfResult(
            success=success,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr or parse_error,
            command=command,
            cwd=cwd,
            timeout=timeout,
            payload=payload,
            file_path=file_path,
            request_signature=signature,
        )
