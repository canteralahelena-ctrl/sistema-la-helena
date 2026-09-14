from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable


STRICT_WINDOW_DAYS = 10
STRICT_TERM_EXCESS_PERCENT = 15
RANKING_TIMEOUT_SECONDS = 10.0
STRICT_BEAM_WIDTH = 800
RELAXED_BEAM_WIDTH = 600

# Pesos documentados del ranking. Los importes se expresan en centavos y la
# desviacion temporal se pondera por importe para no favorecer valores chicos.
BALANCED_WEIGHTS = {
    "own": 1.25,
    "deviation": 0.85,
    "concentration": 0.75,
    "first_empty": 1.20,
    "count": 0.08,
    "distribution": 0.18,
}
PORTFOLIO_WEIGHTS = {
    "own": 1.80,
    "deviation": 0.35,
    "concentration": 0.20,
    "first_empty": 0.45,
    "count": 0.05,
    "distribution": 0.05,
}


@dataclass(frozen=True)
class _State:
    totals: tuple[int, ...]
    assigned: tuple[tuple[int, ...], ...]
    total: int = 0
    weighted_deviation: int = 0
    count: int = 0
    weighted_days: int = 0


def term_days(term: dict[str, Any]) -> int:
    return 0 if term.get("tipo") == "ACOBRAR" else int(term.get("dias") or 0)


def normalize_terms(raw_terms: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    values: set[int] = set()
    for raw in raw_terms or []:
        if not isinstance(raw, dict):
            raise ValueError("El plazo de pago no es valido.")
        term_type = str(raw.get("tipo") or "").strip().upper()
        if term_type == "ACOBRAR":
            days = 0
        elif term_type == "DIAS":
            try:
                days = int(raw.get("dias"))
            except (TypeError, ValueError) as exc:
                raise ValueError("El plazo de pago no es valido.") from exc
        else:
            raise ValueError("El plazo de pago no es valido.")
        if days < 0 or days > 180:
            raise ValueError("El plazo debe estar entre 0 y 180 dias.")
        values.add(days)
    if not values:
        raise ValueError("El plazo de pago no es valido.")
    return [
        {"tipo": "ACOBRAR", "dias": None} if days == 0 else {"tipo": "DIAS", "dias": days}
        for days in sorted(values)
    ]


def divide_targets(total_cents: int, terms: list[dict[str, Any]]) -> list[int]:
    if total_cents <= 0 or not terms:
        raise ValueError("El total y los plazos deben ser validos.")
    base, remainder = divmod(total_cents, len(terms))
    targets = [base] * len(terms)
    targets[-1] += remainder
    return targets


def item_identity(item: Any) -> str:
    raw = getattr(item, "raw", {}) or {}
    explicit = raw.get("IdENTREGA")
    if explicit not in (None, ""):
        return str(explicit)
    return "|".join(
        str(value)
        for value in (
            getattr(item, "item_type", ""),
            getattr(item, "bank", ""),
            getattr(item, "number", ""),
            getattr(item, "amount_cents", 0),
            getattr(item, "due_date", ""),
        )
    )


def _unique_items(items: Iterable[Any], mode: str, target_cents: int) -> list[Any]:
    unique: dict[str, Any] = {}
    for item in items:
        item_type = str(getattr(item, "item_type", "")).upper()
        if mode == "ECHEQ" and item_type != "ECHEQ":
            continue
        if mode == "CHEQUE" and item_type != "CHEQUE FISICO":
            continue
        amount = int(getattr(item, "amount_cents", 0) or 0)
        if amount <= 0 or amount > target_cents:
            continue
        unique.setdefault(item_identity(item), item)
    return list(unique.values())


def _own_schedule(totals: tuple[int, ...], targets: list[int]) -> tuple[list[dict[str, int]], int, int]:
    rows: list[dict[str, int]] = []
    target_accum = 0
    third_accum = 0
    own_accum = 0
    for index, third_cents in enumerate(totals):
        target_accum += targets[index]
        third_accum += third_cents
        paid_before_own = third_accum + own_accum
        own_cents = max(0, target_accum - paid_before_own)
        own_accum += own_cents
        rows.append(
            {
                "own_cents": own_cents,
                "target_accum": target_accum,
                "third_accum": third_accum,
                "paid_before_own": paid_before_own,
                "previous_compensation": max(0, paid_before_own - target_accum),
                "final_accum": third_accum + own_accum,
            }
        )
    return rows, own_accum, third_accum + own_accum


def _strict_indexes(item: Any, terms: list[dict[str, Any]]) -> list[int]:
    days = int(getattr(item, "days", 0))
    indexes: list[int] = []
    for index, term in enumerate(terms):
        target = term_days(term)
        start = 0 if target == 0 else max(0, target - STRICT_WINDOW_DAYS)
        end = target + STRICT_WINDOW_DAYS
        if start <= days <= end:
            indexes.append(index)
    return indexes


def _extend(state: _State, item_index: int, item: Any, term_index: int, terms: list[dict[str, Any]]) -> _State:
    totals = list(state.totals)
    assigned = list(state.assigned)
    amount = int(item.amount_cents)
    totals[term_index] += amount
    assigned[term_index] = assigned[term_index] + (item_index,)
    target_days = term_days(terms[term_index])
    return _State(
        totals=tuple(totals),
        assigned=tuple(assigned),
        total=state.total + amount,
        weighted_deviation=state.weighted_deviation + abs(int(item.days) - target_days) * amount,
        count=state.count + 1,
        weighted_days=state.weighted_days + int(item.days) * amount,
    )


def _strict_key(state: _State, targets: list[int], items: list[Any]) -> tuple[Any, ...]:
    distribution = sum(abs(state.totals[index] - targets[index]) for index in range(len(targets)))
    ids = tuple(sorted(item_identity(items[index]) for group in state.assigned for index in group))
    return (-state.total, state.weighted_deviation, distribution, state.count, ids)


def _profile_key(state: _State, targets: list[int], profile: str) -> tuple[Any, ...]:
    schedule, own_total, final_total = _own_schedule(state.totals, targets)
    total_target = sum(targets)
    concentration = max(state.totals or (0,)) / max(1, total_target)
    first_empty = int(bool(state.totals) and state.totals[0] == 0)
    distribution = sum(abs(state.totals[index] - targets[index]) for index in range(len(targets)))
    weights = BALANCED_WEIGHTS if profile == "EQUILIBRADA" else PORTFOLIO_WEIGHTS
    score = (
        own_total * weights["own"]
        + (state.weighted_deviation / max(1, total_target)) * total_target / 30 * weights["deviation"]
        + concentration * total_target * weights["concentration"]
        + first_empty * total_target * weights["first_empty"]
        + state.count * 10000 * weights["count"]
        + distribution * weights["distribution"]
    )
    if profile == "CARTERA_OPTIMA":
        own_count = sum(1 for row in schedule if row["own_cents"] > 0)
        return (
            final_total != total_target,
            own_total,
            -state.total,
            own_count,
            first_empty,
            state.count,
            score,
            -state.weighted_days,
            state.weighted_deviation,
        )
    return (final_total != total_target, score, own_total, first_empty, state.weighted_deviation, state.count)


def _initial_state(term_count: int) -> _State:
    return _State(tuple(0 for _ in range(term_count)), tuple(tuple() for _ in range(term_count)))


def _strict_search(
    items: list[Any],
    terms: list[dict[str, Any]],
    targets: list[int],
    target_cents: int,
    deadline: float,
) -> tuple[_State, dict[str, Any]]:
    initial = _initial_state(len(terms))
    eligible = [(item, _strict_indexes(item, terms)) for item in items]
    eligible = [(item, indexes) for item, indexes in eligible if indexes]
    eligible.sort(
        key=lambda pair: (
            min(abs(int(pair[0].days) - term_days(terms[index])) for index in pair[1]),
            -int(pair[0].amount_cents),
            int(pair[0].days),
            item_identity(pair[0]),
        )
    )
    candidates = [pair[0] for pair in eligible]
    indexes_by_item = [pair[1] for pair in eligible]
    caps = [target + target * STRICT_TERM_EXCESS_PERCENT // 100 for target in targets]
    states = [initial]
    evaluated = 0
    timed_out = False
    for item_index, item in enumerate(candidates):
        if time.perf_counter() >= deadline:
            timed_out = True
            break
        next_states = list(states)
        for state in states:
            for term_index in indexes_by_item[item_index]:
                if state.total + item.amount_cents > target_cents:
                    continue
                if state.totals[term_index] + item.amount_cents > caps[term_index]:
                    continue
                candidate = _extend(state, item_index, item, term_index, terms)
                if _own_schedule(candidate.totals, targets)[2] > target_cents:
                    continue
                next_states.append(candidate)
                evaluated += 1
        next_states.sort(key=lambda state: _strict_key(state, targets, candidates))
        states = next_states[:STRICT_BEAM_WIDTH]
    best = min(states, key=lambda state: _strict_key(state, targets, candidates))
    return best, {
        "method": "beam_search_strict",
        "candidate_count": len(candidates),
        "states_evaluated": evaluated,
        "timeout": timed_out,
        "items": candidates,
    }


def _relaxed_search(
    items: list[Any],
    terms: list[dict[str, Any]],
    targets: list[int],
    target_cents: int,
    deadline: float,
) -> tuple[list[_State], dict[str, Any]]:
    candidates = sorted(
        items,
        key=lambda item: (
            min(abs(int(item.days) - term_days(term)) for term in terms),
            -int(item.amount_cents),
            int(item.days),
            item_identity(item),
        ),
    )
    states = [_initial_state(len(terms))]
    evaluated = 0
    timed_out = False
    half = RELAXED_BEAM_WIDTH // 2
    for item_index, item in enumerate(candidates):
        if time.perf_counter() >= deadline:
            timed_out = True
            break
        generated = list(states)
        for state in states:
            if state.total + item.amount_cents > target_cents:
                continue
            for term_index in range(len(terms)):
                candidate = _extend(state, item_index, item, term_index, terms)
                if _own_schedule(candidate.totals, targets)[2] > target_cents:
                    continue
                generated.append(candidate)
                evaluated += 1
        balanced = sorted(generated, key=lambda state: _profile_key(state, targets, "EQUILIBRADA"))[:half]
        portfolio = sorted(generated, key=lambda state: _profile_key(state, targets, "CARTERA_OPTIMA"))[:half]
        selected: list[_State] = []
        seen: set[_State] = set()
        for state in balanced + portfolio:
            if state not in seen:
                seen.add(state)
                selected.append(state)
        states = selected[:RELAXED_BEAM_WIDTH]
    return states, {
        "method": "beam_search_shared_relaxed",
        "candidate_count": len(candidates),
        "states_evaluated": evaluated,
        "timeout": timed_out,
        "items": candidates,
    }


def _serialize_item(item: Any, target_days: int) -> dict[str, Any]:
    raw = dict(getattr(item, "raw", {}) or {})
    due_date = getattr(item, "due_date", None)
    return {
        "id_entrega": raw.get("IdENTREGA"),
        "tipo": getattr(item, "item_type", ""),
        "numero": getattr(item, "number", ""),
        "banco": getattr(item, "bank", ""),
        "cliente": getattr(item, "client", ""),
        "importe_cents": int(getattr(item, "amount_cents", 0)),
        "fecha_cobro": due_date.isoformat() if hasattr(due_date, "isoformat") else str(due_date or ""),
        "dias": int(getattr(item, "days", 0)),
        "desviacion_dias": int(getattr(item, "days", 0)) - target_days,
    }


def _plan(
    profile: str,
    state: _State,
    state_items: list[Any],
    terms: list[dict[str, Any]],
    targets: list[int],
    target_cents: int,
    today: date,
    stats: dict[str, Any],
    strict_own: int | None = None,
) -> dict[str, Any]:
    schedule, own_total, final_total = _own_schedule(state.totals, targets)
    assignments: list[dict[str, Any]] = []
    deviations: list[int] = []
    weighted_deviation = 0
    for index, term in enumerate(terms):
        target_days = term_days(term)
        selected = [state_items[item_index] for item_index in state.assigned[index]]
        serialized = [_serialize_item(item, target_days) for item in selected]
        for item in selected:
            deviation = abs(int(item.days) - target_days)
            deviations.append(deviation)
            weighted_deviation += deviation * int(item.amount_cents)
        assignments.append(
            {
                "plazo": dict(term),
                "fecha_objetivo": (today + timedelta(days=target_days)).isoformat(),
                "objetivo_cents": targets[index],
                "terceros_cents": state.totals[index],
                "instrumentos": serialized,
                **schedule[index],
            }
        )
    max_concentration = max(state.totals or (0,)) / max(1, target_cents)
    within = sum(1 for deviation in deviations if deviation <= STRICT_WINDOW_DAYS)
    metrics = {
        "total_terceros_cents": state.total,
        "total_propios_cents": own_total,
        "porcentaje_propios": own_total * 100 / max(1, target_cents),
        "desviacion_maxima_dias": max(deviations, default=0),
        "desviacion_ponderada_dias": weighted_deviation / max(1, state.total),
        "concentracion_maxima": max_concentration,
        "cantidad_instrumentos": state.count,
        "primer_plazo_con_terceros": bool(state.totals and state.totals[0]),
        "cumplimiento_temporal": within * 100 / max(1, len(deviations)),
        "ahorro_propios_vs_estricta_cents": max(0, (strict_own or own_total) - own_total),
    }
    warnings: list[str] = []
    if profile != "ESTRICTA" and metrics["desviacion_maxima_dias"] > STRICT_WINDOW_DAYS:
        warnings.append("No cumple la ventana estricta de +/-10 dias.")
    if max_concentration > 0.40:
        warnings.append(f"El {max_concentration * 100:.1f}% del total queda concentrado en un plazo.")
    if assignments and not assignments[0]["instrumentos"]:
        warnings.append("El primer plazo queda sin valores de terceros.")
    return {
        "id": profile,
        "nombre": {"ESTRICTA": "ESTRICTA", "EQUILIBRADA": "EQUILIBRADA", "CARTERA_OPTIMA": "CARTERA OPTIMA"}[profile],
        "asignaciones": assignments,
        "total_terceros_cents": state.total,
        "total_propios_cents": own_total,
        "total_final_cents": final_total,
        "diferencia_cents": target_cents - final_total,
        "metricas": metrics,
        "advertencias": warnings,
        "stats": {key: value for key, value in stats.items() if key != "items"},
    }


def plan_signature(plan: dict[str, Any]) -> tuple[Any, ...]:
    assigned = tuple(
        sorted(
            (str(item.get("id_entrega")), index)
            for index, assignment in enumerate(plan["asignaciones"])
            for item in assignment["instrumentos"]
        )
    )
    own = tuple(assignment["own_cents"] for assignment in plan["asignaciones"])
    return assigned, own


def plans_too_similar(left: dict[str, Any], right: dict[str, Any], target_cents: int) -> bool:
    def amounts(plan: dict[str, Any]) -> dict[str, int]:
        return {
            str(item["id_entrega"]): int(item["importe_cents"])
            for assignment in plan["asignaciones"]
            for item in assignment["instrumentos"]
        }

    left_amounts = amounts(left)
    right_amounts = amounts(right)
    shared = sum(amount for identity, amount in left_amounts.items() if identity in right_amounts)
    smaller = min(sum(left_amounts.values()), sum(right_amounts.values()))
    own_close = abs(left["total_propios_cents"] - right["total_propios_cents"]) < target_cents * 0.02
    deviation_close = abs(
        left["metricas"]["desviacion_ponderada_dias"] - right["metricas"]["desviacion_ponderada_dias"]
    ) < 2
    return bool(smaller and shared / smaller > 0.85 and own_close and deviation_close)


def build_ranked_plans(
    items: Iterable[Any],
    total_cents: int,
    raw_terms: Iterable[dict[str, Any]],
    mode: str,
    *,
    today: date | None = None,
    timeout_seconds: float = RANKING_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + min(RANKING_TIMEOUT_SECONDS, max(0.05, timeout_seconds))
    terms = normalize_terms(raw_terms)
    targets = divide_targets(total_cents, terms)
    today = today or date.today()
    candidates = _unique_items(items, mode, total_cents)

    strict_state, strict_stats = _strict_search(candidates, terms, targets, total_cents, deadline)
    strict = _plan(
        "ESTRICTA", strict_state, strict_stats["items"], terms, targets, total_cents, today, strict_stats
    )
    relaxed_states, relaxed_stats = _relaxed_search(candidates, terms, targets, total_cents, deadline)
    balanced_state = min(relaxed_states, key=lambda state: _profile_key(state, targets, "EQUILIBRADA"))
    portfolio_state = min(relaxed_states, key=lambda state: _profile_key(state, targets, "CARTERA_OPTIMA"))
    balanced = _plan(
        "EQUILIBRADA",
        balanced_state,
        relaxed_stats["items"],
        terms,
        targets,
        total_cents,
        today,
        relaxed_stats,
        strict["total_propios_cents"],
    )
    portfolio = _plan(
        "CARTERA_OPTIMA",
        portfolio_state,
        relaxed_stats["items"],
        terms,
        targets,
        total_cents,
        today,
        relaxed_stats,
        strict["total_propios_cents"],
    )

    selected: list[dict[str, Any]] = []
    discarded: list[dict[str, str]] = []
    for plan in (strict, balanced, portfolio):
        if any(plan_signature(plan) == plan_signature(existing) for existing in selected):
            discarded.append({"propuesta": plan["id"], "motivo": "Misma asignacion y propios por plazo."})
            continue
        if any(plans_too_similar(plan, existing, total_cents) for existing in selected):
            discarded.append({"propuesta": plan["id"], "motivo": "Demasiado parecida a una propuesta anterior."})
            continue
        selected.append(plan)
    elapsed = time.perf_counter() - started
    return {
        "plazos": terms,
        "objetivos_cents": targets,
        "propuestas": selected,
        "descartes": discarded,
        "stats": {
            "method": "strict_plus_shared_relaxed_beam",
            "candidate_count": len(candidates),
            "elapsed_seconds": elapsed,
            "timeout": bool(strict_stats["timeout"] or relaxed_stats["timeout"]),
            "strict_states_evaluated": strict_stats["states_evaluated"],
            "relaxed_states_evaluated": relaxed_stats["states_evaluated"],
        },
    }
