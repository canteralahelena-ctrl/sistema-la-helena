from __future__ import annotations

from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


class IvaMensualAdapter(Protocol):
    def consultar_iva_mensual(self, *, anio: int, mes: int) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _error(code: str, message: str, *, recoverable: bool = True, **metadata: Any) -> Result:
    return Result(
        success=False,
        message=message,
        error=ErrorInfo(code=code, message=message, recoverable=recoverable, metadata=metadata),
        metadata={"capability": "iva.mensual", **metadata},
    )


def consultar_iva_mensual(request: Request, *, adapter: IvaMensualAdapter) -> Result:
    if request.capability != "iva.mensual":
        return _error(
            "capacidad_invalida",
            "La capacidad solicitada no corresponde a iva.mensual.",
            recoverable=False,
        )

    parameters = request.parameters or {}
    try:
        anio = int(parameters.get("anio"))
        mes = int(parameters.get("mes"))
    except (TypeError, ValueError):
        return _error("periodo_invalido", "El periodo de IVA no es valido.")
    if not 1 <= anio <= 9999 or not 1 <= mes <= 12:
        return _error("periodo_invalido", "El periodo de IVA no es valido.")

    try:
        technical = adapter.consultar_iva_mensual(anio=anio, mes=mes)
    except TimeoutError:
        return _error("iva_mensual_timeout", "La consulta de IVA demoro demasiado.")

    metadata = {
        "capability": "iva.mensual",
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        return _error("iva_mensual_timeout", "La consulta de IVA demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        stderr = str(_value(technical, "stderr", "") or "").strip()
        stdout = str(_value(technical, "stdout", "") or "").strip()
        message = stderr or stdout or "No se pudo consultar IVA."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="iva_mensual_error", message=message, technical_detail=stderr),
            metadata=metadata,
        )

    payload = _value(technical, "payload", {})
    if not isinstance(payload, dict):
        return _error("respuesta_invalida", "La respuesta de IVA no es valida.", **metadata)
    if payload.get("periodo") != f"{anio:04d}-{mes:02d}":
        return _error(
            "respuesta_no_corresponde",
            "La respuesta de IVA no corresponde al periodo solicitado.",
            **metadata,
        )

    return Result(
        success=True,
        data=dict(payload),
        message="Consulta de IVA completada.",
        metadata=metadata,
    )
