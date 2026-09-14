from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


MODE_BY_NUMBER = "BY_NUMBER"
MODE_BY_PERIOD = "BY_PERIOD"
MODE_LATEST = "LATEST"
MODE_SINCE_LAST_PAYMENT = "SINCE_LAST_PAYMENT"
VALID_MODES = {MODE_BY_NUMBER, MODE_BY_PERIOD, MODE_LATEST, MODE_SINCE_LAST_PAYMENT}


class FacturasPdfAdapter(Protocol):
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
    ) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _error(
    code: str,
    message: str,
    *,
    recoverable: bool = True,
    data: dict[str, Any] | None = None,
    **metadata: Any,
) -> Result:
    return Result(
        success=False,
        data=data or {},
        message=message,
        error=ErrorInfo(code=code, message=message, recoverable=recoverable, metadata=metadata),
        metadata={"capability": "clientes.facturas_pdf", **metadata},
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


def _validate_file(
    path_value: Any,
    *,
    outputs_directory: Path,
    expected_extensions: set[str],
) -> tuple[Path | None, Result | None]:
    if path_value in (None, ""):
        return None, _error("archivo_no_generado", "No se genero el archivo solicitado.")
    try:
        outputs = Path(outputs_directory).resolve(strict=True)
        candidate = Path(path_value).resolve(strict=False)
        candidate.relative_to(outputs)
    except (OSError, RuntimeError, ValueError):
        return None, _error("ruta_no_autorizada", "El archivo generado no esta dentro de la carpeta autorizada.")
    if not candidate.exists() or not candidate.is_file():
        return None, _error("archivo_no_generado", "No se genero el archivo solicitado.")
    if candidate.suffix.lower() not in expected_extensions:
        return None, _error("extension_invalida", "La extension del archivo generado no corresponde a la solicitud.")
    if candidate.stat().st_size <= 0:
        return None, _error("archivo_vacio", "El archivo generado esta vacio.")
    return candidate, None


def _request_signature(
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


def generar_facturas_pdf(
    request: Request,
    *,
    adapter: FacturasPdfAdapter,
    outputs_directory: Path,
) -> Result:
    if request.capability != "clientes.facturas_pdf":
        return _error(
            "capacidad_invalida",
            "La capacidad solicitada no corresponde a clientes.facturas_pdf.",
            recoverable=False,
        )

    parameters = request.parameters or {}
    modo = str(parameters.get("modo") or "").strip().upper()
    if modo not in VALID_MODES:
        return _error("modo_invalido", "El modo de facturas PDF no es valido.")

    cliente = str(parameters.get("cliente") or "").strip() or None
    tipo = str(parameters.get("tipo") or "").strip() or None
    numero = str(parameters.get("numero") or "").strip() or None
    desde, date_error = _iso_date(parameters.get("desde"), "desde")
    if date_error:
        return date_error
    hasta, date_error = _iso_date(parameters.get("hasta"), "hasta")
    if date_error:
        return date_error

    cantidad: int | None = None
    if modo == MODE_BY_NUMBER:
        if not numero:
            return _error("numero_requerido", "Debe indicar el numero del comprobante.")
        if not any(character.isdigit() for character in numero) or any(
            character not in "0123456789-/ " for character in numero
        ):
            return _error("numero_invalido", "El numero del comprobante no es valido.")
        cliente = None
        desde = None
        hasta = None
    elif modo == MODE_BY_PERIOD:
        if not cliente:
            return _error("cliente_requerido", "Debe indicar un cliente.")
        if not desde or not hasta:
            return _error("periodo_requerido", "Debe indicar las fechas desde y hasta.")
        if date.fromisoformat(desde) > date.fromisoformat(hasta):
            return _error("rango_invertido", "La fecha desde no puede ser posterior a la fecha hasta.")
        tipo = None
        numero = None
    elif modo == MODE_SINCE_LAST_PAYMENT:
        if not cliente:
            return _error("cliente_requerido", "Debe indicar un cliente.")
        hasta = hasta or date.today().isoformat()
        tipo = None
        numero = None
        desde = None
    else:
        if not cliente:
            return _error("cliente_requerido", "Debe indicar un cliente.")
        try:
            cantidad = int(parameters.get("cantidad", 1) or 1)
        except (TypeError, ValueError):
            return _error("cantidad_invalida", "La cantidad solicitada no es valida.")
        cantidad = max(1, min(cantidad, 20))
        tipo = None
        numero = None
        desde = None
        hasta = None

    signature = _request_signature(
        modo=modo,
        cliente=cliente,
        tipo=tipo,
        numero=numero,
        desde=desde,
        hasta=hasta,
        cantidad=cantidad,
    )
    try:
        technical = adapter.generar_facturas_pdf(**signature)
    except TimeoutError:
        return _error("facturas_pdf_timeout", "La consulta de facturas demoro demasiado.")

    stdout = str(_value(technical, "stdout", "") or "").strip()
    stderr = str(_value(technical, "stderr", "") or "").strip()
    returncode = int(_value(technical, "returncode", 1))
    timed_out = bool(_value(technical, "timed_out", False))
    payload = _value(technical, "payload", {})
    payload = payload if isinstance(payload, dict) else {}
    metadata = {
        "capability": "clientes.facturas_pdf",
        "returncode": returncode,
        "timeout": _value(technical, "timeout", None),
        "modo": modo,
    }

    if timed_out:
        return _error("facturas_pdf_timeout", "La consulta de facturas demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        message = stderr or stdout or "No se pudo generar el archivo de facturas."
        return Result(
            success=False,
            message=message,
            data=payload,
            metadata=metadata,
            error=ErrorInfo(
                code="facturas_pdf_error",
                message=message,
                technical_detail=stderr,
                metadata={"returncode": returncode},
            ),
        )

    if _value(technical, "request_signature", None) != signature:
        return _error(
            "archivo_no_corresponde",
            "El resultado no corresponde exactamente a la solicitud.",
            data=payload,
            **metadata,
        )

    estado = str(payload.get("Estado") or "").strip().upper()
    if estado != "OK":
        message = str(payload.get("Mensaje") or "No se encontro el archivo solicitado.").strip()
        if estado == "SIN_COMPROBANTES":
            code = "sin_comprobantes"
        elif estado == "SIN_PAGOS":
            code = "ultimo_pago_no_encontrado"
        elif estado == "SIN_CLIENTE":
            code = "cliente_no_encontrado"
        elif estado == "AMBIGUO":
            code = "cliente_ambiguo"
        elif estado in {"FALTANTE", "NO_LEIDO"}:
            code = "archivo_no_encontrado"
        else:
            code = "respuesta_no_exitosa"
        return _error(code, message, data=payload, estado=estado, **metadata)

    if modo == MODE_BY_NUMBER:
        expected_extensions = {".pdf"}
    else:
        total = int(payload.get("TotalComprobantes", 0) or 0)
        encontrados = int(payload.get("Encontrados", 0) or 0)
        faltantes = int(payload.get("Faltantes", 0) or 0)
        expected_extensions = {".pdf"} if total == 1 and encontrados == 1 and faltantes == 0 else {".zip"}

    file_path, file_error = _validate_file(
        _value(technical, "file_path", payload.get("Archivo")),
        outputs_directory=Path(outputs_directory),
        expected_extensions=expected_extensions,
    )
    if file_error:
        file_error.data.update(payload)
        file_error.metadata.update(metadata)
        return file_error

    file_type = file_path.suffix.lower().lstrip(".")
    data = dict(payload)
    data.update(
        {
            "modo": modo,
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_type": file_type,
            "cliente_resuelto": payload.get("Cliente") or cliente,
        }
    )
    return Result(
        success=True,
        data=data,
        message=str(payload.get("Mensaje") or stdout or "Archivo generado."),
        files=[str(file_path)],
        metadata=metadata,
    )
