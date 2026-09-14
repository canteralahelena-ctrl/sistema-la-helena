from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result


CAP_RESUMEN = "cheques.resumen"
CAP_DEPOSITABLES = "cheques.depositables"
CAP_VENCIMIENTOS = "cheques.vencimientos"
CAP_ALERTAS = "cheques.alertas"
VALID_CAPABILITIES = {
    CAP_RESUMEN: "resumen",
    CAP_DEPOSITABLES: "depositables",
    CAP_VENCIMIENTOS: "vencimientos",
    CAP_ALERTAS: "alertas",
}
VALID_TYPES = {"TODOS", "CHEQUE", "ECHEQ"}
VALID_FILTERS = {"NN", "BLANCO", "TODOS"}
SUMMARY_BUCKETS = ("0-7 DIAS", "8-15 DIAS", "16-30 DIAS", "MAS DE 30 DIAS")
NN_OBSERVATION_MARKERS = {
    "*",
    "NN",
    "EN CUENTA HUGO",
    "EN CUENTA GASTON",
    "EN CUENTA DE HUGO",
    "EN CUENTA DE GASTON",
    "CUENTA HUGO",
    "CUENTA GASTON",
    "CUNETA HUGO",
    "CUNETA GASTON",
}


class ChequesAdapter(Protocol):
    def consultar(
        self,
        *,
        accion: str,
        tipo: str,
        filtro_fiscal: str,
        dias: int,
    ) -> Any:
        ...


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _error(code: str, message: str, *, capability: str, recoverable: bool = True, **metadata: Any) -> Result:
    return Result(
        success=False,
        message=message,
        error=ErrorInfo(code=code, message=message, recoverable=recoverable, metadata=metadata),
        metadata={"capability": capability, **metadata},
    )


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            continue
    return text


def _normalize_observation(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def _is_nn(item: dict[str, Any]) -> bool:
    text = _normalize_observation(item.get("Observacion"))
    return text in NN_OBSERVATION_MARKERS


def _observation_class(item: dict[str, Any]) -> str:
    text = _normalize_observation(item.get("Observacion"))
    if not text:
        return "BLANCO"
    return "NN" if _is_nn(item) else "DESCONOCIDA"


def business_days_elapsed(start: date, current: date) -> int:
    """Cuenta lunes a viernes transcurridos sin contar FechaCobro."""
    if current <= start:
        return 0
    elapsed = (current - start).days
    full_weeks, extra_days = divmod(elapsed, 7)
    total = full_weeks * 5
    for offset in range(1, extra_days + 1):
        if (start + timedelta(days=offset)).weekday() < 5:
            total += 1
    return total


def _is_current(item: dict[str, Any], current: date) -> bool:
    if str(item.get("Estado") or "").strip().upper() != "EN CAJA":
        return False
    if _observation_class(item) not in {"BLANCO", "NN"}:
        return False
    try:
        collection_date = date.fromisoformat(_date_text(item.get("FechaCobro")))
    except ValueError:
        return False
    tramo = str(item.get("Tramo") or "").strip().upper()
    return business_days_elapsed(collection_date, current) <= 30 and tramo != "SIN FECHA"


def _count_total(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cantidad": len(items),
        "total": sum(_amount(item.get("Importe")) for item in items),
    }


def _record(item: dict[str, Any]) -> dict[str, Any]:
    cliente = str(item.get("Cliente") or "")
    diagnostico_cliente = str(item.get("DiagnosticoCliente") or "")
    if not cliente.strip():
        diagnostico_cliente = "CLIENTE_PENDIENTE"
    return {
        "identificador": item.get("IdENTREGA"),
        "pago_id": item.get("IdPAGO"),
        "tipo": str(item.get("Tipo") or ""),
        "tipo_original": str(item.get("TipoOriginal") or ""),
        "banco": str(item.get("Banco") or ""),
        "numero": str(item.get("Numero") or ""),
        "fecha_cobro": _date_text(item.get("FechaCobro")),
        "fecha_vencimiento": _date_text(item.get("FechaVencimiento")),
        "dias_restantes": _int(item.get("DiasRestantes")),
        "dias_al_vencimiento": _int(item.get("DiasAlVencimiento")),
        "tramo": str(item.get("Tramo") or ""),
        "importe": _amount(item.get("Importe")),
        "cliente_id": item.get("IdCLIENTE"),
        "cliente": cliente,
        "diagnostico_cliente": diagnostico_cliente,
        "estado": str(item.get("Estado") or ""),
        "depositado_en": str(item.get("DepositadoEn") or ""),
        "fecha_endoso": _date_text(item.get("FechaEndoso")),
        "destinatario": str(item.get("Destinatario") or ""),
        "usuario_id": item.get("UserID"),
        "observacion": str(item.get("Observacion") or ""),
    }


def _summary_payload(raw: dict[str, Any], *, tipo: str, filtro_fiscal: str) -> dict[str, Any]:
    rows = [item for item in list(raw.get("Registros") or []) if isinstance(item, dict)]
    try:
        current_date = date.fromisoformat(_date_text(raw.get("FechaConsulta")))
    except ValueError:
        current_date = date.today()
    current = [item for item in rows if _is_current(item, current_date)]
    echeq = [item for item in current if str(item.get("Tipo") or "").strip().upper() == "ECHEQ"]
    physical = [
        item
        for item in current
        if str(item.get("Tipo") or "").strip().upper() == "CHEQUE FISICO"
    ]
    cobrar = [
        item
        for item in current
        if _int(item.get("DiasRestantes")) is not None and int(item["DiasRestantes"]) <= 0
    ]
    depositar = [
        item
        for item in current
        if _int(item.get("DiasRestantes")) is not None and int(item["DiasRestantes"]) > 0
    ]
    nn_rows = [item for item in current if _is_nn(item)]
    blanco_rows = [item for item in current if not _is_nn(item)]
    buckets = {
        bucket: _count_total(
            [
                item
                for item in depositar
                if str(item.get("Tramo") or "").strip().upper() == bucket
            ]
        )
        for bucket in SUMMARY_BUCKETS
    }
    return {
        "fecha_consulta": _date_text(raw.get("FechaConsulta")),
        "tipo": tipo,
        "filtro_fiscal": filtro_fiscal,
        "vacio": not current,
        "total_cartera": _count_total(current),
        "por_tipo": {
            "ECHEQ": _count_total(echeq),
            "CHEQUE FISICO": _count_total(physical),
        },
        "a_cobrar": _count_total(cobrar),
        "a_depositar": buckets,
        "por_filtro_fiscal": {
            "NN": _count_total(nn_rows),
            "BLANCO": _count_total(blanco_rows),
        },
        "cheques": [_record(item) for item in current],
    }


def _vencimientos_payload(
    raw: dict[str, Any],
    *,
    tipo: str,
    filtro_fiscal: str,
    dias: int,
) -> dict[str, Any]:
    rows = [item for item in list(raw.get("Registros") or []) if isinstance(item, dict)]
    fecha_consulta = _date_text(raw.get("FechaConsulta"))
    try:
        fecha_limite = (date.fromisoformat(fecha_consulta) + timedelta(days=dias)).isoformat()
    except ValueError:
        fecha_limite = ""
    rows.sort(
        key=lambda item: (
            _date_text(item.get("FechaCobro")) or "9999-12-31",
            str(item.get("Tipo") or ""),
            str(item.get("Banco") or ""),
            str(item.get("Numero") or ""),
        )
    )
    return {
        "fecha_consulta": fecha_consulta,
        "fecha_limite": fecha_limite,
        "plazo_dias": dias,
        "tipo": tipo,
        "filtro_fiscal": filtro_fiscal,
        "cantidad": len(rows),
        "total": sum(_amount(item.get("Importe")) for item in rows),
        "cheques": [_record(item) for item in rows],
    }


def consultar_cheques(request: Request, *, adapter: ChequesAdapter) -> Result:
    capability = request.capability
    accion = VALID_CAPABILITIES.get(capability)
    if accion is None:
        return _error(
            "capacidad_invalida",
            "La capacidad solicitada no corresponde a consultas de Cheques.",
            capability=capability,
            recoverable=False,
        )

    parameters = request.parameters or {}
    tipo = str(parameters.get("tipo") or "TODOS").strip().upper()
    filtro_fiscal = str(parameters.get("filtro_fiscal") or "TODOS").strip().upper()
    if tipo not in VALID_TYPES:
        return _error("tipo_invalido", "El tipo de cheque no es valido.", capability=capability)
    if filtro_fiscal not in VALID_FILTERS:
        return _error("filtro_invalido", "El filtro fiscal no es valido.", capability=capability)
    try:
        dias = int(parameters.get("dias", 7 if accion == "vencimientos" else 30))
    except (TypeError, ValueError):
        return _error("plazo_invalido", "El plazo de Cheques no es valido.", capability=capability)
    if accion == "vencimientos" and not 1 <= dias <= 180:
        return _error("plazo_invalido", "El plazo de Cheques debe estar entre 1 y 180 dias.", capability=capability)
    if accion == "alertas" and not 0 <= dias <= 30:
        return _error("plazo_invalido", "El plazo de alertas debe estar entre 0 y 30 dias.", capability=capability)

    try:
        technical = adapter.consultar(
            accion=accion,
            tipo=tipo,
            filtro_fiscal=filtro_fiscal,
            dias=dias,
        )
    except TimeoutError:
        return _error("cheques_timeout", "La consulta de Cheques demoro demasiado.", capability=capability)

    metadata = {
        "capability": capability,
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        return _error("cheques_timeout", "La consulta de Cheques demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        stderr = str(_value(technical, "stderr", "") or "").strip()
        stdout = str(_value(technical, "stdout", "") or "").strip()
        message = stderr or stdout or "No se pudo consultar Cheques."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="cheques_error", message=message, technical_detail=stderr),
            metadata=metadata,
        )

    raw = _value(technical, "payload", {})
    if not isinstance(raw, dict):
        return _error("respuesta_invalida", "La respuesta de Cheques no es valida.", **metadata)
    if raw.get("accion") != accion:
        return _error("respuesta_no_corresponde", "La respuesta no corresponde a la consulta.", **metadata)

    if accion == "resumen":
        payload = _summary_payload(raw, tipo=tipo, filtro_fiscal=filtro_fiscal)
    elif accion == "vencimientos":
        payload = _vencimientos_payload(
            raw,
            tipo=tipo,
            filtro_fiscal=filtro_fiscal,
            dias=dias,
        )
    else:
        payload = dict(raw)
    return Result(
        success=True,
        data=payload,
        message="Consulta de Cheques completada.",
        metadata=metadata,
    )
