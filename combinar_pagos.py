import argparse
from bisect import bisect_right
import json
import math
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path

"""
Optimizador informativo de pagos con cheques y eCheq.

Este modulo no modifica Access ni cambia estados. Recibe un JSON generado por
gestion_cheques.ps1, filtra valores operativos y arma alternativas rankeadas.
"""


TYPE_ECHEQ = "ECHEQ"
TYPE_CHECK = "CHEQUE FISICO"
MODE_LABELS = {
    "OPTIMO": "Pago optimo",
    "ECHEQ": "Solo eCheq",
    "CHEQUE": "Solo cheques fisicos",
    "MIXTO": "Mixto",
}
FISCAL_LABELS = {
    "NN": "Pagos NN / sin factura",
    "BLANCO": "Pagos con factura / cheques en blanco",
    "TODOS": "No importa / cualquier cheque",
}
SEPARATOR = "━━━━━━━━━━━━━━━━━━"
NUMBER_ICONS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
}
NN_OBSERVATION_MARKERS = (
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
)


@dataclass(frozen=True)
class PaymentItem:
    raw: dict
    amount_cents: int
    item_type: str
    bank: str
    number: str
    client: str
    due_date: date
    days: int
    expiration_days: int


@dataclass
class PaymentOption:
    mode: str
    items: list
    total_cents: int
    score: float
    amount_score: float
    days_score: float
    count_score: float
    rotation_score: float
    stability_score: float
    penalties: float
    evaluated_count: int


def money(value):
    text = f"{value:,.2f}"
    return "$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


def cents_money(cents):
    return money(cents / 100)


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def business_days_elapsed(start_date, current_date):
    """Cuenta dias habiles transcurridos sin contar la fecha de cobro."""
    if not start_date or not current_date or current_date <= start_date:
        return 0
    elapsed_days = (current_date - start_date).days
    full_weeks, extra_days = divmod(elapsed_days, 7)
    business_days = full_weeks * 5
    for offset in range(1, extra_days + 1):
        if (start_date + timedelta(days=offset)).weekday() < 5:
            business_days += 1
    return business_days


def normalize_type(value):
    text = str(value or "").strip().upper()
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    if text == "CHEQUE":
        return TYPE_CHECK
    if text == "CHEQUE FISICO":
        return TYPE_CHECK
    if text == "ECHEQ":
        return TYPE_ECHEQ
    if text == "E-CHEQ":
        return TYPE_ECHEQ
    if text == "ECHEQUE":
        return TYPE_ECHEQ
    if text == "E-CHEQUE":
        return TYPE_ECHEQ
    if text == "ECHQ":
        return TYPE_ECHEQ
    return text


def is_marked_for_cleanup(row):
    cleanup_fields = (
        "Depurar",
        "Depurado",
        "ADEPURAR",
        "A Depurar",
        "MarcadoDepuracion",
        "MarcadoParaDepurar",
    )
    for field in cleanup_fields:
        value = row.get(field)
        if isinstance(value, bool) and value:
            return True
        if str(value or "").strip().upper() in {"SI", "S", "TRUE", "1", "DEPURAR"}:
            return True
    return False


def observation_value(row):
    for field in ("OBSERVACION", "Observacion", "observacion"):
        if field in row:
            return row.get(field)
    return None


def has_observation_field(row):
    return any(field in row for field in ("OBSERVACION", "Observacion", "observacion"))


def normalize_text(value):
    text = str(value or "").strip().upper()
    return "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")


def is_nn_observation(value):
    text = normalize_text(value)
    return text in NN_OBSERVATION_MARKERS


def observation_class(value):
    text = normalize_text(value)
    if not text:
        return "BLANCO"
    if text in NN_OBSERVATION_MARKERS:
        return "NN"
    return "DESCONOCIDA"


def passes_fiscal_filter(row, fiscal_filter):
    fiscal_class = observation_class(observation_value(row))
    if fiscal_filter == "TODOS":
        return fiscal_class in {"BLANCO", "NN"}
    if fiscal_filter == "NN":
        return fiscal_class == "NN"
    if fiscal_filter == "BLANCO":
        return fiscal_class == "BLANCO"
    return False


def load_item_rows(data, fiscal_filter="TODOS", source="dias", *, today=None):
    """Normaliza una cartera estructurada con las mismas reglas de Pago Simple."""
    rows = list(data.get("Registros", []))
    if fiscal_filter != "TODOS" and rows and not any(has_observation_field(row) for row in rows):
        return [], "No se pudo aplicar el filtro fiscal: el JSON no trae OBSERVACION."
    items = []
    today = today or date.today()
    expired_business_days_count = 0
    for row in rows:
        estado = str(row.get("Estado") or "").strip().upper()
        if estado != "EN CAJA":
            continue
        if not passes_fiscal_filter(row, fiscal_filter):
            continue
        try:
            amount = round(float(row.get("Importe") or 0), 2)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        if is_marked_for_cleanup(row):
            continue
        due_date = parse_date(row.get("FechaCobro"))
        if not due_date:
            continue
        if business_days_elapsed(due_date, today) > 30:
            expired_business_days_count += 1
            continue
        try:
            days = int(row.get("DiasRestantes"))
            expiration_days = int(row.get("DiasAlVencimiento"))
        except (TypeError, ValueError):
            continue
        if source != "acobrar" and days < 0:
            continue
        item_type = normalize_type(row.get("Tipo"))
        if item_type not in {TYPE_ECHEQ, TYPE_CHECK}:
            continue
        items.append(
            PaymentItem(
                raw=dict(row),
                amount_cents=int(round(amount * 100)),
                item_type=item_type,
                bank=str(row.get("Banco") or "-").strip() or "-",
                number=str(row.get("Numero") or "-").strip() or "-",
                client=str(row.get("Cliente") or "-").strip() or "-",
                due_date=due_date,
                days=days,
                expiration_days=expiration_days,
            )
        )
    if fiscal_filter != "TODOS" and not items:
        return [], "No hay valores disponibles para ese tipo de pago."
    return items, None


def load_items(path, fiscal_filter="TODOS", source="dias"):
    """Carga y prefiltra valores vigentes en cartera desde el JSON del script."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return load_item_rows(data, fiscal_filter, source)


def candidate_key(item, target_days, target_cents):
    day_distance = abs(item.days - target_days)
    rotation = item.days
    useful_amount = abs(min(item.amount_cents, target_cents) - target_cents)
    return (day_distance, rotation, useful_amount, item.amount_cents)


def select_candidates(items, target_cents, target_days, max_candidates):
    """Recorta el universo manteniendo cercania a fecha, montos utiles y rellenos chicos."""
    if len(items) <= max_candidates:
        return sorted(items, key=lambda item: candidate_key(item, target_days, target_cents))

    near_date = sorted(items, key=lambda item: candidate_key(item, target_days, target_cents))
    small_fillers = sorted(items, key=lambda item: (item.amount_cents, abs(item.days - target_days)))
    large_useful = sorted(
        items,
        key=lambda item: (
            0 if item.amount_cents <= target_cents * 1.25 else 1,
            abs(item.amount_cents - target_cents),
            abs(item.days - target_days),
        ),
    )

    selected = []
    seen = set()
    for source in (near_date, large_useful, small_fillers):
        for item in source:
            item_id = item.raw.get("IdENTREGA") or (item.item_type, item.bank, item.number, item.amount_cents)
            if item_id in seen:
                continue
            selected.append(item)
            seen.add(item_id)
            if len(selected) >= max_candidates:
                return selected
    return selected


def score_combination(items, target_cents, target_days, max_values, amount_tolerance_pct, day_tolerance):
    """Calcula score 0..100 priorizando importe y evaluando distancia de fecha por valor."""
    total = sum(item.amount_cents for item in items)
    difference = total - target_cents
    amount_tolerance = max(1, int(round(target_cents * amount_tolerance_pct / 100)))
    relative_amount_error = abs(difference) / max(1, target_cents)
    amount_score = 45.0 / (1.0 + relative_amount_error)
    if difference > 0:
        amount_score *= 0.9

    day_errors = [abs(item.days - target_days) for item in items]
    avg_day_error = sum(day_errors) / len(day_errors)
    max_day_error = max(day_errors)
    days_score = max(0.0, 30.0 * (1.0 - avg_day_error / max(1, day_tolerance)))
    if max_day_error > day_tolerance * 2:
        days_score *= 0.35
    elif max_day_error > day_tolerance:
        days_score *= 0.7

    if len(items) <= 1:
        count_score = 10.0
    else:
        count_score = max(0.0, 10.0 * (1.0 - (len(items) - 1) / max(1, max_values - 1)))

    near_to_expire = sum(1 for item in items if item.days <= target_days)
    avg_days = sum(item.days for item in items) / len(items)
    rotation_score = min(10.0, near_to_expire / len(items) * 7.0 + max(0.0, 3.0 * (1.0 - avg_days / max(1, target_days + day_tolerance))))

    spread = math.sqrt(sum((error - avg_day_error) ** 2 for error in day_errors) / len(day_errors))
    stability_score = max(0.0, 5.0 * (1.0 - spread / max(1, day_tolerance)))

    penalties = 0.0
    if difference < -amount_tolerance:
        penalties += min(8.0, relative_amount_error * 8.0)
    elif difference < 0:
        penalties += 1.5
    if difference > amount_tolerance:
        penalties += min(24.0, relative_amount_error * 24.0)
    elif difference > 0:
        penalties += 7.0
    if len(items) > max_values:
        penalties += (len(items) - max_values) * 5.0
    if max_day_error > day_tolerance * 2:
        penalties += 18.0
    score = max(0.0, min(100.0, amount_score + days_score + count_score + rotation_score + stability_score - penalties))
    return score, amount_score, days_score, count_score, rotation_score, stability_score, penalties


def amount_priority_key(total_cents, target_cents):
    difference = total_cents - target_cents
    if difference == 0:
        amount_rank = 0
    elif difference < 0:
        amount_rank = 1
    else:
        amount_rank = 2
    return amount_rank, abs(difference)


def monetary_key(total_cents, target_cents):
    difference = total_cents - target_cents
    side_rank = 0 if difference <= 0 else 1
    if difference == 0:
        side_rank = -1
    return abs(difference), side_rank


def date_priority_key(option, target_days, source):
    distinct_days = sorted({item.days for item in option.items})
    max_days = max(distinct_days)
    if source == "acobrar":
        distance = abs(max_days - target_days)
    else:
        distance = max_days - target_days
    return distance, len(distinct_days), max_days


def stable_option_key(option):
    return tuple(
        sorted(
            (
                str(item.raw.get("IdENTREGA") or ""),
                item.item_type,
                item.bank,
                item.number,
                item.amount_cents,
                item.days,
            )
            for item in option.items
        )
    )


def combination_ranking_key(items, total_cents, target_cents, target_days=0, source="dias"):
    distinct_days = {item.days for item in items}
    max_days = max(distinct_days)
    day_spread = max_days - min(distinct_days)
    date_distance = abs(max_days - target_days) if source == "acobrar" else max_days - target_days
    stable_key = tuple(
        sorted(
            (
                str(item.raw.get("IdENTREGA") or ""),
                item.item_type,
                item.bank,
                item.number,
                item.amount_cents,
                item.days,
            )
            for item in items
        )
    )
    return (
        abs(total_cents - target_cents),
        len(items),
        date_distance,
        len(distinct_days),
        max_days,
        day_spread,
        stable_key,
    )


def ranking_key(option, target_cents, target_days=0, source="dias"):
    return combination_ranking_key(
        option.items,
        option.total_cents,
        target_cents,
        target_days,
        source,
    )


def date_search_order(target_days, day_tolerance):
    return list(range(target_days, target_days + day_tolerance + 1))


def is_commercially_usable(option, target_cents, amount_tolerance_pct):
    return option.total_cents > 0


def difference_direction(total_cents, target_cents):
    difference = total_cents - target_cents
    if difference == 0:
        return "EXACTA"
    if difference < 0:
        return "POR_DEBAJO"
    return "POR_ENCIMA"


def final_action(option, target_cents):
    difference = option.total_cents - target_cents
    if difference >= 0:
        return "SIN_COMPLEMENTO"
    if abs(difference) < 10000000:
        return "TRANSFERENCIA"
    return "CHEQUE_ECHEQ_PROPIO"


def commercial_option_key(option, target_cents):
    difference = option.total_cents - target_cents
    return (
        option.total_cents,
        abs(difference),
        difference_direction(option.total_cents, target_cents),
        len(option.items),
        final_action(option, target_cents),
    )


def commercial_group_tiebreak_key(option, target_days, source):
    date_entries = []
    for item in option.items:
        distance = abs(item.days - target_days)
        availability_rank = 0 if source == "acobrar" and item.days <= target_days else 1
        date_entries.append((distance, availability_rank, item.days))
    closest_dates = tuple(sorted(date_entries))
    deviations = [entry[0] for entry in date_entries]
    return (
        sum(deviations),
        max(deviations) if deviations else 0,
        closest_dates,
        stable_option_key(option),
    )


def is_duplicate_option(candidate, selected, target_cents):
    candidate_key = commercial_option_key(candidate, target_cents)
    for option in selected:
        if commercial_option_key(option, target_cents) == candidate_key:
            return True
    return False


def deduplicate_commercial_options(options, target_cents, target_days, source):
    grouped = {}
    for option in options:
        key = commercial_option_key(option, target_cents)
        current = grouped.get(key)
        if current is None or commercial_group_tiebreak_key(option, target_days, source) < commercial_group_tiebreak_key(current, target_days, source):
            grouped[key] = option
    return sorted(grouped.values(), key=lambda item: ranking_key(item, target_cents, target_days, source))


def options_are_too_similar(candidate, selected, target_cents):
    if difference_direction(candidate.total_cents, target_cents) == "EXACTA":
        return False
    material_threshold = 1000000
    if material_threshold <= 0:
        return False
    for option in selected:
        if difference_direction(candidate.total_cents, target_cents) != difference_direction(option.total_cents, target_cents):
            continue
        if len(candidate.items) != len(option.items):
            continue
        if final_action(candidate, target_cents) != final_action(option, target_cents):
            continue
        if abs(candidate.total_cents - option.total_cents) < material_threshold:
            return True
    return False


def select_diverse_options(options, target_cents, target_days, options_count, amount_tolerance_pct, source):
    if not options or options_count <= 0:
        return []

    unique = deduplicate_commercial_options(options, target_cents, target_days, source)
    if not unique:
        return []

    best_option = unique[0]
    selected = [best_option]
    if len(selected) >= options_count:
        return selected

    side_order = ["POR_DEBAJO", "POR_ENCIMA"]
    for wanted_direction in side_order:
        if len(selected) >= options_count:
            break
        side_already_selected = any(
            difference_direction(option.total_cents, target_cents) == wanted_direction
            for option in selected
        )
        for option in unique:
            if option in selected:
                continue
            if difference_direction(option.total_cents, target_cents) != wanted_direction:
                continue
            if side_already_selected and options_are_too_similar(option, selected, target_cents):
                continue
            if side_already_selected and not is_reasonable_alternative(option, best_option, target_cents, amount_tolerance_pct):
                continue
            selected.append(option)
            break

    if len(selected) < options_count:
        for option in unique:
            if option in selected:
                continue
            if not is_reasonable_alternative(option, best_option, target_cents, amount_tolerance_pct):
                continue
            if options_are_too_similar(option, selected, target_cents):
                continue
            selected.append(option)
            if len(selected) >= options_count:
                break
    return selected


def is_reasonable_alternative(option, best_option, target_cents, amount_tolerance_pct):
    if best_option is None:
        return True
    difference = abs(option.total_cents - target_cents)
    best_difference = abs(best_option.total_cents - target_cents)
    amount_tolerance = max(1, int(round(target_cents * amount_tolerance_pct / 100)))
    return difference <= max(best_difference * 3, amount_tolerance)


def generate_options_for_candidates(candidates, mode, target_cents, target_days, options_count, max_values, amount_tolerance_pct, day_tolerance, max_combinations, source, deadline=None):
    best = []
    best_keys = []
    keep_count = max(1, options_count * 8)
    evaluated = 0
    for size in range(1, min(max_values, len(candidates)) + 1):
        for combo in combinations(candidates, size):
            evaluated += 1
            if deadline is not None and evaluated % 256 == 0 and time.perf_counter() >= deadline:
                return best, evaluated
            identities = [item.raw.get("IdENTREGA") for item in combo]
            if len(identities) != len(set(identities)):
                continue
            total_cents = sum(item.amount_cents for item in combo)
            option_key = combination_ranking_key(combo, total_cents, target_cents, target_days, source)
            if len(best) >= keep_count and option_key >= best_keys[-1]:
                if evaluated >= max_combinations:
                    return best, evaluated
                continue
            score_parts = score_combination(combo, target_cents, target_days, max_values, amount_tolerance_pct, day_tolerance)
            option = PaymentOption(
                mode=mode,
                items=list(combo),
                total_cents=total_cents,
                score=score_parts[0],
                amount_score=score_parts[1],
                days_score=score_parts[2],
                count_score=score_parts[3],
                rotation_score=score_parts[4],
                stability_score=score_parts[5],
                penalties=score_parts[6],
                evaluated_count=evaluated,
            )
            insert_at = bisect_right(best_keys, option_key)
            best_keys.insert(insert_at, option_key)
            best.insert(insert_at, option)
            if len(best) > keep_count:
                best_keys.pop()
                best.pop()
            if evaluated >= max_combinations:
                return best, evaluated
    return best, evaluated


def prepare_mode_candidates(items, mode, target_cents, target_days, max_candidates, day_tolerance, source):
    if mode == "ECHEQ":
        universe = [item for item in items if item.item_type == TYPE_ECHEQ]
    elif mode == "CHEQUE":
        universe = [item for item in items if item.item_type == TYPE_CHECK]
    else:
        universe = list(items)

    if source == "acobrar":
        eligible = [item for item in universe if item.days <= target_days + day_tolerance]
    else:
        eligible = [item for item in universe if item.days >= target_days and item.days <= target_days + day_tolerance]
    if not eligible:
        return []
    return select_candidates(eligible, target_cents, target_days, max_candidates)


def candidate_universe_key(candidates):
    return tuple(
        (
            str(item.raw.get("IdENTREGA") or ""),
            item.item_type,
            item.amount_cents,
            item.days,
            item.bank,
            item.number,
        )
        for item in candidates
    )


def optimize_mode(items, mode, target_cents, target_days, options_count, max_candidates, max_values, amount_tolerance_pct, day_tolerance, max_combinations, source="dias", deadline=None, prepared_candidates=None):
    """Evalua todos los valores de la ventana y prioriza cercania monetaria."""
    candidates = prepared_candidates
    if candidates is None:
        candidates = prepare_mode_candidates(
            items, mode, target_cents, target_days, max_candidates, day_tolerance, source
        )
    if not candidates:
        return [], 0, 0

    options, evaluated = generate_options_for_candidates(
        candidates,
        mode,
        target_cents,
        target_days,
        options_count,
        max_values,
        amount_tolerance_pct,
        day_tolerance,
        max_combinations,
        source,
        deadline,
    )
    return options, len(candidates), evaluated


def build_reasons(option, target_cents, target_days):
    difference = option.total_cents - target_cents
    day_errors = [abs(item.days - target_days) for item in option.items]
    reasons = []
    if difference == 0:
        reasons.append("importe exacto")
    elif difference > 0:
        reasons.append("Queda por encima del objetivo; revisar el excedente.")
    else:
        reasons.append("Queda por debajo del objetivo; diferencia a completar por transferencia.")
    if max(day_errors) <= 2:
        reasons.append("fechas muy cercanas al plazo")
    elif sum(day_errors) / len(day_errors) <= 7:
        reasons.append("plazo razonablemente cercano")
    if len(option.items) <= 3:
        reasons.append(f"solo {len(option.items)} valores")
    if any(item.days <= target_days for item in option.items):
        reasons.append("consume valores de menor plazo")
    if option.mode == "ECHEQ":
        reasons.append("solo eCheq")
    elif option.mode == "CHEQUE":
        reasons.append("solo cheques fisicos")
    elif option.mode == "MIXTO" and {item.item_type for item in option.items} == {TYPE_ECHEQ, TYPE_CHECK}:
        reasons.append("combina eCheq y cheques fisicos")
    return reasons[:4]


def format_average_days(option):
    if option.total_cents <= 0:
        return 0
    weighted = sum(item.amount_cents * item.days for item in option.items) / option.total_cents
    return round(weighted)


def format_difference_and_suggestion(difference):
    if difference == 0:
        return f"{cents_money(0)} exacto", "Sin faltante ni excedente"
    if difference < 0:
        missing = abs(difference)
        if missing < 10000000:
            return f"{cents_money(missing)} por debajo", "Sugerencia: completar diferencia con transferencia"
        return f"{cents_money(missing)} por debajo", f"Sugerencia: agregar cheque/eCheq propio por {cents_money(missing)}"
    return f"{cents_money(abs(difference))} por encima", "Advertencia: excede el importe objetivo"


def render_option(rank, option, target_cents, target_days):
    medals = ["🥇 MEJOR OPCIÓN", "🥈 ALTERNATIVA 2", "🥉 ALTERNATIVA 3"]
    title = medals[rank - 1] if rank <= len(medals) else f"Alternativa {rank}"
    difference = option.total_cents - target_cents
    diff_text, suggestion = format_difference_and_suggestion(difference)

    lines = [
        SEPARATOR,
        "",
        title,
        f"Total: {cents_money(option.total_cents)}",
        f"Diferencia: {diff_text}",
        suggestion,
        "",
        f"Cantidad: {len(option.items)} valores",
        "",
    ]
    for index, item in enumerate(sorted(option.items, key=lambda value: (value.days, value.due_date, value.item_type, value.bank)), start=1):
        label = "CHEQUE FÍSICO" if item.item_type == TYPE_CHECK else item.item_type
        number_icon = NUMBER_ICONS.get(index, f"{index}.")
        lines.extend(
            [
                f"{number_icon} {label} — {item.bank} {item.number}",
                f"📅 {item.due_date.strftime('%d/%m/%Y')}",
                f"👤 {item.client}",
                f"💰 {cents_money(item.amount_cents)}",
                "",
            ]
        )
    return lines


def render_result(options, target_cents, target_days, mode, total_items, selected_items, evaluated, fiscal_filter="TODOS", source="dias"):
    if not options:
        return "No se encuentra combinación de cheques."

    plazo_label = "A cobrar" if source == "acobrar" else f"{target_days} días"
    lines = [
        "💳 PAGO ÓPTIMO",
        "",
        f"Solicitado: {cents_money(target_cents)}",
        f"Plazo objetivo: {plazo_label}",
        f"Modo: {mode}",
        f"Filtro: {fiscal_filter}",
        "",
    ]

    for index, option in enumerate(options[:3], start=1):
        lines.extend(render_option(index, option, target_cents, target_days))

    lines.extend(["", SEPARATOR, "", "ℹ️ Propuesta informativa.", "No se modificó ni endosó ningún cheque."])
    return "\n".join(lines)


def optimize(items, mode, target_cents, target_days, options_count, max_candidates, max_values, amount_tolerance_pct, day_tolerance, max_combinations, source="dias"):
    """Ejecuta un modo directo o los tres universos cuando se pide Pago Optimo."""
    modes = ["ECHEQ", "CHEQUE", "MIXTO"] if mode == "OPTIMO" else [mode]
    deadline = time.perf_counter() + 6.0
    all_options = []
    selected_total = 0
    evaluated_total = 0
    seen_universes = set()
    for current_mode in modes:
        candidates = prepare_mode_candidates(
            items,
            current_mode,
            target_cents,
            target_days,
            max_candidates,
            day_tolerance,
            source,
        )
        universe_key = candidate_universe_key(candidates)
        if mode == "OPTIMO" and candidates and universe_key in seen_universes:
            continue
        if candidates:
            seen_universes.add(universe_key)
        options, selected_count, evaluated = optimize_mode(
            items,
            current_mode,
            target_cents,
            target_days,
            options_count,
            max_candidates,
            max_values,
            amount_tolerance_pct,
            day_tolerance,
            max_combinations,
            source,
            deadline,
            candidates,
        )
        selected_total += selected_count
        evaluated_total += evaluated
        all_options.extend(options)
        if time.perf_counter() >= deadline:
            break

    all_options = [option for option in all_options if option.total_cents <= target_cents]
    all_options.sort(key=lambda item: ranking_key(item, target_cents, target_days, source))
    selected = select_diverse_options(
        all_options,
        target_cents,
        target_days,
        options_count,
        amount_tolerance_pct,
        source,
    )
    return selected, selected_total, evaluated_total


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Optimizador informativo de pagos con cheques/eCheq.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--target", required=True, type=float)
    parser.add_argument("--days", required=True, type=int)
    parser.add_argument("--source", default="dias", choices=["dias", "acobrar"])
    parser.add_argument("--mode", default="OPTIMO", choices=["OPTIMO", "ECHEQ", "CHEQUE", "MIXTO"])
    parser.add_argument("--fiscal-filter", default="TODOS", choices=["NN", "BLANCO", "TODOS"])
    parser.add_argument("--options", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--max-values", type=int, default=8)
    parser.add_argument("--amount-tolerance-pct", type=float, default=10.0)
    parser.add_argument("--day-tolerance", type=int, default=15)
    parser.add_argument("--max-combinations", type=int, default=100000)
    args = parser.parse_args()

    if args.target <= 0:
        raise SystemExit("El importe objetivo debe ser mayor a cero.")
    if args.source != "acobrar" and args.days <= 0:
        raise SystemExit("El plazo objetivo debe ser mayor a cero.")
    if args.max_values <= 0:
        raise SystemExit("El maximo de valores debe ser mayor a cero.")

    items, load_error = load_items(args.data, args.fiscal_filter, args.source)
    target_cents = int(round(args.target * 100))
    if load_error:
        if load_error.startswith("No hay valores disponibles"):
            print("No se encuentra combinación de cheques.")
        else:
            print(load_error)
        return
    options, selected_count, evaluated = optimize(
        items,
        args.mode,
        target_cents,
        args.days,
        max(1, args.options),
        max(1, args.max_candidates),
        max(1, args.max_values),
        max(1.0, args.amount_tolerance_pct),
        max(1, args.day_tolerance),
        max(1, args.max_combinations),
        args.source,
    )
    print(render_result(options, target_cents, args.days, args.mode, len(items), selected_count, evaluated, args.fiscal_filter, args.source))


if __name__ == "__main__":
    main()
