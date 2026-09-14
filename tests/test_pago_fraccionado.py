import time
import unittest
from datetime import date, timedelta

from combinar_pagos import PaymentItem
from helena_core.business.pagos.fraccionado import (
    STRICT_WINDOW_DAYS,
    build_ranked_plans,
    divide_targets,
    normalize_terms,
    plan_signature,
)


TODAY = date(2026, 8, 4)


def item(identity, cents, days, item_type="ECHEQ"):
    due = TODAY + timedelta(days=days)
    return PaymentItem(
        raw={"IdENTREGA": identity},
        amount_cents=cents,
        item_type=item_type,
        bank="BANCO",
        number=str(identity),
        client="CLIENTE",
        due_date=due,
        days=days,
        expiration_days=days + 30,
    )


def terms(*days):
    return [
        {"tipo": "ACOBRAR", "dias": None} if value == 0 else {"tipo": "DIAS", "dias": value}
        for value in days
    ]


def strict(result):
    return next(plan for plan in result["propuestas"] if plan["id"] == "ESTRICTA")


def selected_ids(plan):
    return [
        value["id_entrega"]
        for assignment in plan["asignaciones"]
        for value in assignment["instrumentos"]
    ]


class FragmentedTermAndStrictRuleTests(unittest.TestCase):
    def test_dynamic_terms_zero_long_non_uniform_and_normalization(self):
        cases = [
            ([0], [0]),
            ([0, 15, 30], [0, 15, 30]),
            ([30, 60, 90, 120], [30, 60, 90, 120]),
            ([0, 15, 30, 45, 60, 75, 90, 120, 150, 180], [0, 15, 30, 45, 60, 75, 90, 120, 150, 180]),
            ([0, 20, 55, 110, 180], [0, 20, 55, 110, 180]),
            ([60, 0, 30, 15, 30], [0, 15, 30, 60]),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                normalized = normalize_terms(terms(*raw))
                self.assertEqual([0 if value["tipo"] == "ACOBRAR" else value["dias"] for value in normalized], expected)

    def test_negative_terms_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_terms([{"tipo": "DIAS", "dias": -1}])

    def test_residual_cents_are_assigned_to_last_term(self):
        self.assertEqual(divide_targets(1_008_232_499, terms(30, 60, 90, 120)), [252_058_124, 252_058_124, 252_058_124, 252_058_127])
        self.assertEqual(sum(divide_targets(101, terms(0, 15, 30))), 101)

    def test_long_and_non_uniform_schedules_execute_with_exact_close(self):
        for schedule in ((0, 15, 30, 45, 60, 75, 90, 120, 150, 180), (0, 20, 55, 110, 180)):
            with self.subTest(schedule=schedule):
                result = build_ranked_plans([], 1_000_003, terms(*schedule), "MIXTO", today=TODAY)
                self.assertEqual(result["plazos"], normalize_terms(terms(*schedule)))
                self.assertEqual(sum(result["objetivos_cents"]), 1_000_003)
                self.assertEqual(result["propuestas"][0]["total_final_cents"], 1_000_003)

    def test_strict_window_includes_boundaries_and_rejects_outside(self):
        values = [item(1, 10_000, 20), item(2, 10_000, 40), item(3, 10_000, 19), item(4, 10_000, 41)]
        plan = strict(build_ranked_plans(values, 100_000, terms(30, 60), "ECHEQ", today=TODAY))
        self.assertEqual(set(selected_ids(plan)), {1, 2})
        self.assertEqual(STRICT_WINDOW_DAYS, 10)

    def test_term_zero_uses_today_through_plus_ten_only(self):
        values = [item(1, 10_000, 0), item(2, 10_000, 10), item(3, 10_000, -1), item(4, 10_000, 11)]
        plan = strict(build_ranked_plans(values, 50_000, terms(0, 30), "ECHEQ", today=TODAY))
        self.assertEqual(set(selected_ids(plan)), {1, 2})

    def test_strict_accepts_fifteen_percent_and_rejects_more(self):
        accepted = strict(build_ranked_plans([item(1, 11_500, 30)], 20_000, terms(30, 60), "ECHEQ", today=TODAY))
        rejected = strict(build_ranked_plans([item(2, 11_501, 30)], 20_000, terms(30, 60), "ECHEQ", today=TODAY))
        self.assertEqual(selected_ids(accepted), [1])
        self.assertEqual(selected_ids(rejected), [])

    def test_accumulated_compensation_never_creates_negative_own(self):
        result = build_ranked_plans(
            [item(1, 11_000, 30), item(2, 8_000, 60)],
            20_000,
            terms(30, 60),
            "ECHEQ",
            today=TODAY,
        )
        plan = strict(result)
        own = [assignment["own_cents"] for assignment in plan["asignaciones"]]
        self.assertEqual(own, [0, 1_000])
        self.assertTrue(all(value >= 0 for value in own))
        self.assertEqual(plan["total_final_cents"], 20_000)

    def test_mode_filter_and_unique_ids_are_absolute(self):
        values = [item(1, 20_000, 30, "ECHEQ"), item(1, 20_000, 30, "ECHEQ"), item(2, 20_000, 60, "CHEQUE FISICO")]
        echeq = strict(build_ranked_plans(values, 50_000, terms(30, 60), "ECHEQ", today=TODAY))
        cheque = strict(build_ranked_plans(values, 50_000, terms(30, 60), "CHEQUE", today=TODAY))
        self.assertEqual(selected_ids(echeq), [1])
        self.assertEqual(selected_ids(cheque), [2])
        self.assertEqual(len(selected_ids(echeq)), len(set(selected_ids(echeq))))

    def test_every_plan_closes_exactly_without_transfer_or_excess(self):
        result = build_ranked_plans(
            [item(index, 15_000 + index * 100, index * 9) for index in range(1, 12)],
            200_000,
            terms(0, 20, 55, 110),
            "OPTIMO",
            today=TODAY,
        )
        for plan in result["propuestas"]:
            self.assertEqual(plan["total_final_cents"], 200_000)
            self.assertEqual(plan["diferencia_cents"], 0)
            self.assertNotIn("TRANSFER", str(plan).upper())


class RankingAndRealCaseTests(unittest.TestCase):
    def real_case(self):
        values = [
            item(1, 60_000_000, 30),
            item(2, 60_000_000, 60),
            item(3, 60_000_000, 90),
            item(4, 66_507_554, 120),
            item(21114, 549_624_260, 43),
            item(21115, 549_624_260, 73),
        ]
        return build_ranked_plans(values, 1_008_232_499, terms(30, 60, 90, 120), "ECHEQ", today=TODAY)

    def test_real_case_strict_totals_are_preserved(self):
        plan = strict(self.real_case())
        self.assertEqual(plan["total_terceros_cents"], 246_507_554)
        self.assertEqual(plan["total_propios_cents"], 761_724_945)
        self.assertEqual(plan["total_final_cents"], 1_008_232_499)
        self.assertEqual(plan["diferencia_cents"], 0)

    def test_large_real_echeqs_are_considered_outside_strict_window(self):
        result = self.real_case()
        plan = strict(result)
        self.assertNotIn(21114, selected_ids(plan))
        self.assertNotIn(21115, selected_ids(plan))
        relaxed_ids = {value for proposal in result["propuestas"][1:] for value in selected_ids(proposal)}
        self.assertIn(21114, relaxed_ids)
        self.assertNotIn(21115, relaxed_ids)
        selected = next(
            item_data
            for proposal in result["propuestas"][1:]
            for assignment in proposal["asignaciones"]
            for item_data in assignment["instrumentos"]
            if item_data["id_entrega"] == 21114
        )
        self.assertEqual(selected["desviacion_dias"], 13)

    def test_profiles_metrics_and_shared_relaxed_search_are_structured(self):
        result = self.real_case()
        self.assertEqual(result["stats"]["method"], "strict_plus_shared_relaxed_beam")
        self.assertGreaterEqual(len(result["propuestas"]), 2)
        self.assertIn("EQUILIBRADA", {plan["id"] for plan in result["propuestas"]})
        for plan in result["propuestas"]:
            metrics = plan["metricas"]
            for key in (
                "total_terceros_cents",
                "total_propios_cents",
                "porcentaje_propios",
                "desviacion_maxima_dias",
                "desviacion_ponderada_dias",
                "concentracion_maxima",
                "cantidad_instrumentos",
                "primer_plazo_con_terceros",
                "ahorro_propios_vs_estricta_cents",
            ):
                self.assertIn(key, metrics)

    def test_portfolio_profile_can_select_more_cartera_when_materially_distinct(self):
        result = build_ranked_plans(
            [item(1, 8_000, 30), item(2, 8_000, 60), item(3, 18_000, 180)],
            20_000,
            terms(30, 60),
            "ECHEQ",
            today=TODAY,
        )
        portfolio = next(plan for plan in result["propuestas"] if plan["id"] == "CARTERA_OPTIMA")
        self.assertEqual(selected_ids(portfolio), [3])
        self.assertEqual(portfolio["total_terceros_cents"], 18_000)
        self.assertEqual(portfolio["total_final_cents"], 20_000)

    def test_exact_and_near_duplicate_plans_are_not_shown(self):
        empty = build_ranked_plans([], 100_000, terms(30, 60), "ECHEQ", today=TODAY)
        self.assertEqual(len(empty["propuestas"]), 1)
        result = self.real_case()
        signatures = [plan_signature(plan) for plan in result["propuestas"]]
        self.assertEqual(len(signatures), len(set(signatures)))
        self.assertLessEqual(len(result["propuestas"]), 3)

    def test_timeout_returns_valid_best_plans(self):
        values = [item(1000 + index, 1_000_000 + index * 10_000, (index * 13) % 181) for index in range(80)]
        result = build_ranked_plans(
            values,
            100_000_000,
            terms(0, 15, 30, 45, 60, 75, 90, 120, 150, 180),
            "ECHEQ",
            today=TODAY,
            timeout_seconds=0.05,
        )
        self.assertTrue(result["stats"]["timeout"])
        self.assertTrue(result["propuestas"])
        self.assertTrue(all(plan["total_final_cents"] == 100_000_000 for plan in result["propuestas"]))

    def test_performance_19_40_60_80_values(self):
        for count in (19, 40, 60, 80):
            values = [item(2000 + index, 10_000_000 + (index % 9) * 3_000_000, (index * 13) % 181) for index in range(count)]
            started = time.perf_counter()
            result = build_ranked_plans(values, 1_008_232_499, terms(30, 60, 90, 120), "ECHEQ", today=TODAY)
            elapsed = time.perf_counter() - started
            with self.subTest(count=count, elapsed=elapsed):
                self.assertLess(elapsed, 5.0)
                self.assertLessEqual(result["stats"]["elapsed_seconds"], 10.0)
                self.assertTrue(result["propuestas"])


if __name__ == "__main__":
    unittest.main()
