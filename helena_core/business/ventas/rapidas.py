from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


class VentasRapidasAdapter(Protocol):
    def consultar_ventas_rapidas(self, *, fecha_desde: str, fecha_hasta: str) -> Any:
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
        metadata={"capability": "ventas.rapidas", **metadata},
    )


def _iso_date(value: Any, field_name: str) -> tuple[str | None, Result | None]:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value or "").strip())
        except ValueError:
            return None, _error("fecha_invalida", f"La fecha {field_name} no es valida.", campo=field_name)
    return parsed.isoformat(), None


def consultar_ventas_rapidas(request: Request, *, adapter: VentasRapidasAdapter) -> Result:
    if request.capability != "ventas.rapidas":
        return _error(
            "capacidad_invalida",
            "La capacidad solicitada no corresponde a ventas.rapidas.",
            recoverable=False,
        )

    parameters = request.parameters or {}
    fecha_desde, date_error = _iso_date(parameters.get("fecha_desde"), "desde")
    if date_error:
        return date_error
    fecha_hasta, date_error = _iso_date(parameters.get("fecha_hasta"), "hasta")
    if date_error:
        return date_error
    if date.fromisoformat(fecha_desde) > date.fromisoformat(fecha_hasta):
        return _error("rango_invertido", "La fecha desde no puede ser posterior a la fecha hasta.")

    try:
        technical = adapter.consultar_ventas_rapidas(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except TimeoutError:
        return _error("ventas_rapidas_timeout", "La consulta de ventas demoro demasiado.")

    metadata = {
        "capability": "ventas.rapidas",
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        return _error("ventas_rapidas_timeout", "La consulta de ventas demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        stderr = str(_value(technical, "stderr", "") or "").strip()
        stdout = str(_value(technical, "stdout", "") or "").strip()
        message = stderr or stdout or "No se pudo consultar las ventas."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="ventas_rapidas_error", message=message, technical_detail=stderr),
            metadata=metadata,
        )

    payload = _value(technical, "payload", {})
    if not isinstance(payload, dict):
        return _error("respuesta_invalida", "La respuesta de ventas no es valida.", **metadata)
    if payload.get("fecha_desde") != fecha_desde or payload.get("fecha_hasta") != fecha_hasta:
        return _error("respuesta_no_corresponde", "La respuesta no corresponde al periodo solicitado.", **metadata)

    return Result(
        success=True,
        data=dict(payload),
        message="Consulta de ventas completada.",
        metadata=metadata,
    )
