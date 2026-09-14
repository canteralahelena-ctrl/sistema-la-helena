from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


class ProductosNoClasificadosAdapter(Protocol):
    def consultar_productos_no_clasificados(
        self,
        *,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _error(code: str, message: str, **metadata: Any) -> Result:
    return Result(
        success=False,
        message=message,
        error=ErrorInfo(code=code, message=message, metadata=metadata),
        metadata={"capability": "ventas.productos_no_clasificados", **metadata},
    )


def _date(value: Any, field: str) -> tuple[str | None, Result | None]:
    try:
        parsed = date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None, _error("fecha_invalida", f"La fecha {field} no es valida.", campo=field)
    return parsed.isoformat(), None


def _amount(row: dict[str, Any]) -> Decimal:
    try:
        return Decimal(str(row.get("importe") or "0"))
    except InvalidOperation:
        return Decimal("0")


def consultar_productos_no_clasificados(
    request: Request,
    *,
    adapter: ProductosNoClasificadosAdapter,
) -> Result:
    if request.capability != "ventas.productos_no_clasificados":
        return _error("capacidad_invalida", "La capacidad solicitada no corresponde.")
    parameters = request.parameters or {}
    fecha_desde, error = _date(parameters.get("fecha_desde"), "desde")
    if error:
        return error
    fecha_hasta, error = _date(parameters.get("fecha_hasta"), "hasta")
    if error:
        return error
    if date.fromisoformat(fecha_desde) > date.fromisoformat(fecha_hasta):
        return _error("rango_invertido", "La fecha desde no puede ser posterior a la fecha hasta.")

    technical = adapter.consultar_productos_no_clasificados(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    metadata = {
        "capability": "ventas.productos_no_clasificados",
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        return _error("productos_no_clasificados_timeout", "La consulta demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        message = str(_value(technical, "stderr", "") or _value(technical, "stdout", "") or "No se pudo completar la consulta.")
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="productos_no_clasificados_error", message=message),
            metadata=metadata,
        )
    payload = _value(technical, "payload", {})
    if not isinstance(payload, dict):
        return _error("respuesta_invalida", "La respuesta no es valida.", **metadata)
    if payload.get("fecha_desde") != fecha_desde or payload.get("fecha_hasta") != fecha_hasta:
        return _error("respuesta_no_corresponde", "La respuesta no corresponde al periodo solicitado.", **metadata)

    records = list(payload.get("registros") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        grouped.setdefault(str(row.get("producto_descripcion") or "Sin descripción"), []).append(row)
    ordered = sorted(
        grouped.items(),
        key=lambda item: sum((_amount(row) for row in item[1]), Decimal("0")),
        reverse=True,
    )
    groups = []
    shown_rows = 0
    for product, rows in ordered[:8]:
        ordered_rows = sorted(rows, key=_amount, reverse=True)
        visible = ordered_rows[:5]
        shown_rows += len(visible)
        groups.append(
            {
                "producto": product,
                "importe_total": format(sum((_amount(row) for row in rows), Decimal("0")), "f"),
                "cantidad_lineas": len(rows),
                "registros": visible,
                "lineas_ocultas": max(0, len(rows) - 5),
            }
        )
    data = {
        **payload,
        "registros": records,
        "cantidad_total": len(records),
        "importe_total": format(sum((_amount(row) for row in records), Decimal("0")), "f"),
        "grupos": groups,
        "productos_ocultos": max(0, len(ordered) - 8),
        "registros_mostrados": shown_rows,
        "truncado": shown_rows < len(records),
    }
    return Result(
        success=True,
        data=data,
        message="Consulta de productos no clasificados completada.",
        metadata=metadata,
    )
