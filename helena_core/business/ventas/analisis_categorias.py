from __future__ import annotations

from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


class AnalisisCategoriasAdapter(Protocol):
    def consultar_analisis_categorias(self) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def consultar_analisis_categorias(
    request: Request,
    *,
    adapter: AnalisisCategoriasAdapter,
) -> Result:
    if request.capability != "ventas.analisis_categorias":
        message = "La capacidad solicitada no corresponde a ventas.analisis_categorias."
        return Result(success=False, message=message, error=ErrorInfo(code="capacidad_invalida", message=message))
    technical = adapter.consultar_analisis_categorias()
    metadata = {
        "capability": "ventas.analisis_categorias",
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        message = "La consulta de categorias demoro demasiado."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="analisis_categorias_timeout", message=message),
            metadata=metadata,
        )
    if not bool(_value(technical, "success", False)):
        message = str(_value(technical, "stderr", "") or _value(technical, "stdout", "") or "No se pudo completar la consulta.")
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="analisis_categorias_error", message=message),
            metadata=metadata,
        )
    payload = _value(technical, "payload", {})
    required = {
        "estado",
        "fecha_desde",
        "fecha_hasta",
        "total",
        "categorias",
        "advertencias",
        "texto_resumido",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        message = "La respuesta del analisis de categorias es incompleta."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="respuesta_invalida", message=message),
            metadata=metadata,
        )
    return Result(
        success=True,
        data=dict(payload),
        message="Analisis de categorias completado.",
        warnings=list(payload.get("advertencias") or []),
        metadata=metadata,
    )
