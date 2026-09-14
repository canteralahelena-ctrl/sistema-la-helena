from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


MODE_RANGE = "RANGE"
MODE_OPEN_BALANCE = "OPEN_BALANCE"
MODE_SINCE_LAST_PAYMENT = "SINCE_LAST_PAYMENT"
VALID_MODES = {MODE_RANGE, MODE_OPEN_BALANCE, MODE_SINCE_LAST_PAYMENT}


class EstadoCuentaPdfAdapter(Protocol):
    def generar_estado_pdf(
        self,
        *,
        cliente: str,
        modo: str,
        desde: str | None,
        hasta: str | None,
        nombre_archivo: str,
    ) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _error(code: str, message: str, *, recoverable: bool = True, **metadata: Any) -> Result:
    return Result(
        success=False,
        error=ErrorInfo(
            code=code,
            message=message,
            recoverable=recoverable,
            metadata=metadata,
        ),
        metadata={"capability": "clientes.estado_pdf", **metadata},
    )


def _iso_date(value: Any, field_name: str) -> tuple[str | None, Result | None]:
    if value in (None, ""):
        return None, None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value).strip())
        except ValueError:
            return None, _error("fecha_invalida", f"La fecha {field_name} no es valida.", campo=field_name)
    return parsed.isoformat(), None


def _safe_pdf_name(value: Any) -> tuple[str | None, Result | None]:
    name = str(value or "").strip()
    if not name:
        return None, _error("nombre_archivo_requerido", "Debe indicar el nombre del PDF.")
    path = Path(name)
    if path.name != name or path.suffix.lower() != ".pdf":
        return None, _error("nombre_archivo_invalido", "El nombre de salida debe ser un archivo PDF sin ruta.")
    return name, None


def _validated_pdf(
    path_value: Any,
    outputs_directory: Path,
    *,
    started_at: datetime | None = None,
) -> tuple[Path | None, Result | None]:
    if path_value in (None, ""):
        return None, _error("pdf_no_generado", "No se genero el PDF del estado de cuenta.")
    try:
        outputs = outputs_directory.resolve(strict=True)
        candidate = Path(path_value).resolve(strict=False)
        candidate.relative_to(outputs)
    except (OSError, RuntimeError, ValueError):
        return None, _error("ruta_pdf_no_autorizada", "El PDF generado no esta dentro de la carpeta autorizada.")
    if not candidate.exists():
        return None, _error("pdf_no_generado", "No se genero el PDF del estado de cuenta.")
    if not candidate.is_file():
        return None, _error("pdf_no_generado", "No se genero el PDF del estado de cuenta.")
    if candidate.suffix.lower() != ".pdf":
        return None, _error("extension_pdf_invalida", "El archivo generado no tiene extension PDF.")
    stat = candidate.stat()
    if stat.st_size <= 0:
        return None, _error("pdf_vacio", "El PDF generado esta vacio.")
    if started_at is not None and stat.st_mtime < started_at.timestamp():
        return None, _error("pdf_no_corresponde_ejecucion", "El PDF no corresponde a la ejecucion actual.")
    return candidate, None


def generar_estado_cuenta_pdf(
    request: Request,
    *,
    adapter: EstadoCuentaPdfAdapter,
    outputs_directory: Path,
) -> Result:
    if request.capability != "clientes.estado_pdf":
        return _error("capacidad_invalida", "La capacidad solicitada no corresponde a clientes.estado_pdf.", recoverable=False)

    parameters = request.parameters or {}
    cliente = str(parameters.get("cliente") or "").strip()
    if not cliente:
        return _error("cliente_requerido", "Debe indicar un cliente.")

    modo = str(parameters.get("modo") or "").strip().upper()
    if modo not in VALID_MODES:
        return _error("modo_invalido", "El modo de estado de cuenta PDF no es valido.")

    desde, date_error = _iso_date(parameters.get("desde"), "desde")
    if date_error:
        return date_error
    hasta, date_error = _iso_date(parameters.get("hasta"), "hasta")
    if date_error:
        return date_error

    if modo == MODE_RANGE and not desde:
        return _error("fecha_desde_requerida", "Debe indicar la fecha desde para el estado de cuenta.")
    if desde and hasta and date.fromisoformat(desde) > date.fromisoformat(hasta):
        return _error("rango_invertido", "La fecha desde no puede ser posterior a la fecha hasta.")
    if modo != MODE_RANGE and (desde or hasta):
        return _error("fechas_no_admitidas", "El modo seleccionado no admite fechas explicitas.")

    nombre_archivo, name_error = _safe_pdf_name(parameters.get("nombre_archivo"))
    if name_error:
        return name_error

    started_at = datetime.now()
    try:
        technical = adapter.generar_estado_pdf(
            cliente=cliente,
            modo=modo,
            desde=desde,
            hasta=hasta,
            nombre_archivo=nombre_archivo,
        )
    except TimeoutError:
        return _error("estado_pdf_timeout", "La generacion del estado de cuenta demoro demasiado.")

    stdout = str(_value(technical, "stdout", "") or "").strip()
    stderr = str(_value(technical, "stderr", "") or "").strip()
    returncode = int(_value(technical, "returncode", 1))
    timed_out = bool(_value(technical, "timed_out", False))
    message = stdout or stderr or "Consulta ejecutada."
    metadata = {
        "capability": "clientes.estado_pdf",
        "returncode": returncode,
        "timeout": _value(technical, "timeout", None),
    }

    if timed_out:
        return Result(
            success=False,
            message=message,
            metadata=metadata,
            error=ErrorInfo(code="estado_pdf_timeout", message="La generacion del estado de cuenta demoro demasiado."),
        )
    if not bool(_value(technical, "success", False)):
        error_message = stderr or stdout or "No se pudo generar el PDF del estado de cuenta."
        lowered = error_message.lower()
        if "varios clientes" in lowered:
            code = "cliente_ambiguo"
        elif "no encontre cliente" in lowered or "no encontre clientes" in lowered:
            code = "cliente_no_encontrado"
        else:
            code = "estado_pdf_error"
        return Result(
            success=False,
            message=error_message,
            metadata=metadata,
            error=ErrorInfo(
                code=code,
                message=error_message,
                technical_detail=stderr,
                metadata={"returncode": returncode},
            ),
        )

    pdf_path, pdf_error = _validated_pdf(
        _value(technical, "file_path", None),
        Path(outputs_directory),
        started_at=started_at,
    )
    if pdf_error:
        pdf_error.message = message if pdf_error.error and pdf_error.error.code == "pdf_no_generado" and stdout else pdf_error.message
        pdf_error.metadata.update(metadata)
        return pdf_error

    return Result(
        success=True,
        data={
            "cliente": cliente,
            "modo": modo,
            "desde": desde,
            "hasta": hasta,
            "file_path": str(pdf_path),
            "file_name": pdf_path.name,
            "stdout": stdout,
            "returncode": returncode,
        },
        message=message,
        files=[str(pdf_path)],
        metadata=metadata,
    )
