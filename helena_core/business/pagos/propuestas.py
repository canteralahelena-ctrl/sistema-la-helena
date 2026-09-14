from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol

from helena_core.application.contracts import ErrorInfo, Request, Result
from helena_core.business.pagos.fraccionado import build_ranked_plans, normalize_terms


CAP_PROPOSAL = "pagos.propuesta"
CAP_ECHEQ_LEGACY = "pagos.echeq_legacy"
CAPABILITIES = {CAP_PROPOSAL, CAP_ECHEQ_LEGACY}
VALID_MODES = {"OPTIMO", "ECHEQ", "CHEQUE", "MIXTO"}
VALID_FISCAL_FILTERS = {"NN", "BLANCO", "TODOS"}
MISSING_TRANSFER_THRESHOLD = 100000
NO_COMBINATION_MESSAGE = "No se encuentra combinación de cheques"


class PagosAdapter(Protocol):
    def proponer(
        self,
        *,
        capability: str,
        importe: float,
        plazo: dict[str, Any],
        modo: str,
        filtro_fiscal: str,
    ) -> Any:
        ...

    def cargar_cartera(self, *, modo: str, filtro_fiscal: str) -> Any:
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


def _amount(value: Any) -> float:
    amount = round(float(value), 2)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError
    return amount


def _amount_cents(value: Any) -> int:
    try:
        decimal = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError from exc
    cents = int(decimal * 100)
    if cents <= 0:
        raise ValueError
    return cents


def _normalize_term(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError
    term_type = str(value.get("tipo") or "").strip().upper()
    if term_type == "ACOBRAR":
        return {"tipo": "ACOBRAR", "dias": None}
    if term_type != "DIAS":
        raise ValueError
    days = int(value.get("dias") or 0)
    if not 1 <= days <= 180:
        raise ValueError
    return {"tipo": "DIAS", "dias": days}


def split_payment_amount(amount: float, terms: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    total_cents = int(round(amount * 100))
    base_cents = total_cents // len(terms)
    assigned = 0
    payments: list[dict[str, Any]] = []
    for index, term in enumerate(terms):
        cents = base_cents if index < len(terms) - 1 else total_cents - assigned
        assigned += cents
        payments.append(
            {
                "numero_pago": index + 1,
                "plazo": dict(term),
                "importe_objetivo": cents / 100,
            }
        )
    return payments, base_cents / 100


def _missing_action(target: float, selected: float | None, mode: str) -> dict[str, Any]:
    if selected is None:
        return {
            "diferencia": None,
            "faltante": None,
            "excedente": None,
            "accion_faltante": None,
            "resultado": "SIN_RESULTADO",
        }
    difference = round(target - selected, 2)
    if difference > 0:
        action = "TRANSFERIR" if difference < MISSING_TRANSFER_THRESHOLD else "AGREGAR_PROPIO"
        instrument = "eCheq" if mode == "ECHEQ" else "cheque/eCheq"
        return {
            "diferencia": difference,
            "faltante": difference,
            "excedente": 0.0,
            "accion_faltante": action,
            "instrumento_faltante": instrument,
            "resultado": "POR_DEBAJO",
        }
    if difference < 0:
        return {
            "diferencia": difference,
            "faltante": 0.0,
            "excedente": abs(difference),
            "accion_faltante": None,
            "resultado": "POR_ENCIMA",
        }
    return {
        "diferencia": 0.0,
        "faltante": 0.0,
        "excedente": 0.0,
        "accion_faltante": None,
        "resultado": "EXACTO",
    }


def _technical_result(
    technical: Any,
    *,
    capability: str,
    target: float,
    mode: str,
    term: dict[str, Any],
) -> Result | dict[str, Any]:
    metadata = {
        "capability": capability,
        "returncode": int(_value(technical, "returncode", 1)),
        "timeout": _value(technical, "timeout", None),
    }
    if bool(_value(technical, "timed_out", False)):
        return _error("pagos_timeout", "La consulta de pago demoro demasiado.", **metadata)
    if not bool(_value(technical, "success", False)):
        stderr = str(_value(technical, "stderr", "") or "").strip()
        stdout = str(_value(technical, "stdout", "") or "").strip()
        message = stderr or stdout or "No se pudo calcular la propuesta de pago."
        return Result(
            success=False,
            message=message,
            error=ErrorInfo(code="pagos_error", message=message, technical_detail=stderr),
            metadata=metadata,
        )
    payload = _value(technical, "payload", {})
    if not isinstance(payload, dict) or not str(payload.get("texto_legacy") or "").strip():
        return _error("respuesta_invalida", "La respuesta de Pagos no es valida.", **metadata)
    selected = payload.get("total_seleccionado")
    if selected is not None:
        try:
            selected = round(float(selected), 2)
        except (TypeError, ValueError):
            return _error("respuesta_invalida", "El total seleccionado no es valido.", **metadata)
    return {
        "modo": mode,
        "importe_objetivo": target,
        "plazo": dict(term),
        "cheques_seleccionados": list(payload.get("cheques_seleccionados") or []),
        "opciones": list(payload.get("opciones") or []),
        "total_seleccionado": selected,
        "texto_legacy": str(payload["texto_legacy"]).strip(),
        "estado": "COMPLETADO",
        **_missing_action(target, selected, mode),
    }


def _is_no_combination(result: dict[str, Any]) -> bool:
    text = str(result.get("texto_legacy") or "").strip().rstrip(".")
    return text.casefold() == NO_COMBINATION_MESSAGE.casefold()


def _relaxed_single_payment(
    ranking: dict[str, Any],
    *,
    amount: float,
    term: dict[str, Any],
    mode: str,
) -> dict[str, Any] | None:
    proposals = list(ranking.get("propuestas") or [])
    plan = next(
        (
            proposal
            for proposal in proposals
            if proposal.get("id") == "CARTERA_OPTIMA"
            and int(proposal.get("total_terceros_cents") or 0) > 0
        ),
        None,
    )
    if plan is None:
        plan = next(
            (
                proposal
                for proposal in proposals
                if proposal.get("id") != "ESTRICTA"
                and int(proposal.get("total_terceros_cents") or 0) > 0
            ),
            None,
        )
    if plan is None:
        return None
    instruments = [
        instrument
        for assignment in plan.get("asignaciones") or []
        for instrument in assignment.get("instrumentos") or []
    ]
    selected = int(plan.get("total_terceros_cents") or 0) / 100
    return {
        "modo": mode,
        "importe_objetivo": amount,
        "plazo": dict(term),
        "cheques_seleccionados": instruments,
        "opciones": [],
        "total_seleccionado": selected,
        "texto_legacy": NO_COMBINATION_MESSAGE + ".",
        "estado": "COMPLETADO",
        "alternativa_fuera_ventana_estricta": True,
        "propuesta_relaxed": plan,
        **_missing_action(amount, selected, mode),
    }


def consultar_propuesta_pago(request: Request, *, adapter: PagosAdapter) -> Result:
    capability = request.capability
    if capability not in CAPABILITIES:
        return _error(
            "capacidad_invalida",
            "La capacidad solicitada no corresponde a Pagos.",
            capability=capability,
            recoverable=False,
        )
    parameters = request.parameters or {}
    try:
        amount_cents = _amount_cents(parameters.get("importe"))
        amount = amount_cents / 100
    except (TypeError, ValueError):
        return _error("importe_invalido", "El importe debe ser mayor a cero.", capability=capability)

    mode = "ECHEQ" if capability == CAP_ECHEQ_LEGACY else str(parameters.get("modo") or "OPTIMO").upper()
    if mode not in VALID_MODES:
        return _error("modo_invalido", "El modo de pago no es valido.", capability=capability)
    fiscal_filter = str(parameters.get("filtro_fiscal") or "TODOS").upper()
    if fiscal_filter not in VALID_FISCAL_FILTERS:
        return _error("filtro_invalido", "El filtro fiscal no es valido.", capability=capability)

    fragmented = bool(parameters.get("fraccionado"))
    raw_terms = parameters.get("plazos") if fragmented else [parameters.get("plazo")]
    if not isinstance(raw_terms, list) or not raw_terms:
        return _error("plazo_invalido", "El plazo de pago no es valido.", capability=capability)
    try:
        terms = normalize_terms(raw_terms) if fragmented else [_normalize_term(raw_terms[0])]
    except (TypeError, ValueError):
        return _error("plazo_invalido", "El plazo debe estar entre 0 y 180 dias.", capability=capability)
    if fragmented and len(terms) == 1:
        fragmented = False
    if capability == CAP_ECHEQ_LEGACY and (fragmented or terms[0]["tipo"] != "DIAS"):
        return _error("plazo_invalido", "El pago eCheq legacy requiere un plazo en dias.", capability=capability)

    if fragmented:
        try:
            technical = adapter.cargar_cartera(modo=mode, filtro_fiscal=fiscal_filter)
        except TimeoutError:
            return _error("pagos_timeout", "La consulta de pago demoro demasiado.", capability=capability)
        if bool(_value(technical, "timed_out", False)):
            return _error("pagos_timeout", "La consulta de pago demoro demasiado.", capability=capability)
        if not bool(_value(technical, "success", False)):
            message = str(_value(technical, "stderr", "") or _value(technical, "stdout", "") or "No se pudo validar la cartera.").strip()
            return _error("pagos_error", message, capability=capability)
        payload = _value(technical, "payload", {})
        items = list(payload.get("items") or []) if isinstance(payload, dict) else []
        try:
            ranking = build_ranked_plans(
                items,
                amount_cents,
                terms,
                mode,
                timeout_seconds=float(parameters.get("timeout_ranking") or 10.0),
            )
        except (TypeError, ValueError) as exc:
            return _error("respuesta_invalida", str(exc), capability=capability)
        data = {
            "modo": mode,
            "filtro_fiscal": fiscal_filter,
            "importe_objetivo": amount,
            "importe_objetivo_cents": amount_cents,
            "cantidad_pagos": len(terms),
            "plazos": ranking["plazos"],
            "objetivos_cents": ranking["objetivos_cents"],
            "propuestas": ranking["propuestas"],
            "descartes": ranking["descartes"],
            "fraccionado": True,
            "importe_por_plazo": ranking["objetivos_cents"][0] / 100,
            "estado": "COMPLETADO",
            "exclusion_entre_pagos": True,
            "stats": ranking["stats"],
        }
        return Result(
            success=True,
            data=data,
            message="Ranking de pago fraccionado completado.",
            metadata={"capability": capability},
        )

    payments, amount_per_term = split_payment_amount(amount, terms) if fragmented else (
        [{"numero_pago": 1, "plazo": terms[0], "importe_objetivo": amount}],
        amount,
    )
    completed: list[dict[str, Any]] = []
    for payment in payments:
        try:
            technical = adapter.proponer(
                capability=capability,
                importe=payment["importe_objetivo"],
                plazo=payment["plazo"],
                modo=mode,
                filtro_fiscal=fiscal_filter,
            )
        except TimeoutError:
            return _error("pagos_timeout", "La consulta de pago demoro demasiado.", capability=capability)
        parsed = _technical_result(
            technical,
            capability=capability,
            target=payment["importe_objetivo"],
            mode=mode,
            term=payment["plazo"],
        )
        if isinstance(parsed, Result):
            return parsed
        if not fragmented and _is_no_combination(parsed):
            try:
                portfolio = adapter.cargar_cartera(modo=mode, filtro_fiscal=fiscal_filter)
            except TimeoutError:
                return _error("pagos_timeout", "La consulta de pago demoro demasiado.", capability=capability)
            if bool(_value(portfolio, "timed_out", False)):
                return _error("pagos_timeout", "La consulta de pago demoro demasiado.", capability=capability)
            if not bool(_value(portfolio, "success", False)):
                message = str(
                    _value(portfolio, "stderr", "")
                    or _value(portfolio, "stdout", "")
                    or "No se pudo validar la cartera."
                ).strip()
                return _error("pagos_error", message, capability=capability)
            payload = _value(portfolio, "payload", {})
            items = list(payload.get("items") or []) if isinstance(payload, dict) else []
            try:
                ranking = build_ranked_plans(
                    items,
                    amount_cents,
                    terms,
                    mode,
                    timeout_seconds=float(parameters.get("timeout_ranking") or 10.0),
                )
            except (TypeError, ValueError) as exc:
                return _error("respuesta_invalida", str(exc), capability=capability)
            relaxed = _relaxed_single_payment(
                ranking,
                amount=amount,
                term=payment["plazo"],
                mode=mode,
            )
            if relaxed is not None:
                parsed = relaxed
        completed.append({"numero_pago": payment["numero_pago"], **parsed})

    first = completed[0]
    if not fragmented and first.get("accion_faltante") == "AGREGAR_PROPIO":
        first["instrumento_faltante"] = {
            "ECHEQ": "eCheq",
            "CHEQUE": "cheque",
        }.get(mode, "cheque/eCheq")
    data: dict[str, Any] = {
        "modo": mode,
        "filtro_fiscal": fiscal_filter,
        "importe_objetivo": amount,
        "cantidad_pagos": len(completed),
        "plazos": terms,
        "pagos": completed,
        "fraccionado": fragmented,
        "importe_por_plazo": amount_per_term,
        "estado": "COMPLETADO",
        # The legacy script has no exclusion parameter; this documents the
        # preserved behavior without inventing a new cross-payment algorithm.
        "exclusion_entre_pagos": False if fragmented else True,
    }
    if not fragmented:
        data.update({key: value for key, value in first.items() if key != "numero_pago"})
    return Result(
        success=True,
        data=data,
        message="Propuesta de pago completada.",
        metadata={"capability": capability},
    )
