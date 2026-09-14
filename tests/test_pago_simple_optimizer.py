import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "combinar_pagos.py"
SPEC = importlib.util.spec_from_file_location("combinar_pagos", MODULE_PATH)
cp = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cp
SPEC.loader.exec_module(cp)


def make_item(item_id, amount_cents, days=0, number=None, item_type=None):
    return cp.PaymentItem(
        raw={"IdENTREGA": item_id},
        amount_cents=amount_cents,
        item_type=item_type or cp.TYPE_ECHEQ,
        bank="BANCO",
        number=str(number or item_id),
        client="CLIENTE",
        due_date=date.today() + timedelta(days=days),
        days=days,
        expiration_days=30,
    )


def make_option(items, mode="ECHEQ"):
    return cp.PaymentOption(
        mode=mode,
        items=list(items),
        total_cents=sum(item.amount_cents for item in items),
        score=0,
        amount_score=0,
        days_score=0,
        count_score=0,
        rotation_score=0,
        stability_score=0,
        penalties=0,
        evaluated_count=1,
    )


class CommercialDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.target = 306_081_600
        fixed_a = make_item(100, 150_000_000, 0)
        fixed_b = make_item(101, 93_152_828, 0)
        self.equal_far = make_option([fixed_a, fixed_b, make_item(102, 62_500_000, 5)])
        self.equal_best = make_option([fixed_a, fixed_b, make_item(103, 62_500_000, 0)])
        self.equal_middle = make_option([fixed_a, fixed_b, make_item(104, 62_500_000, 2)])
        self.other_below = make_option([
            make_item(200, 150_000_000, 0),
            make_item(201, 91_500_000, 0),
            make_item(202, 62_500_000, 0),
        ])
        self.above = make_option([
            make_item(300, 150_000_000, 0),
            make_item(301, 94_500_000, 0),
            make_item(302, 62_500_000, 0),
        ])

    def test_same_total_difference_and_count_keep_one(self):
        result = cp.deduplicate_commercial_options(
            [self.equal_far, self.equal_best, self.equal_middle], self.target, 0, "acobrar"
        )
        self.assertEqual(1, len(result))
        self.assertEqual({100, 101, 103}, {item.raw["IdENTREGA"] for item in result[0].items})

    def test_different_ids_with_same_amounts_are_commercial_duplicates(self):
        self.assertEqual(
            cp.commercial_option_key(self.equal_far, self.target),
            cp.commercial_option_key(self.equal_best, self.target),
        )
        self.assertTrue(cp.is_duplicate_option(self.equal_far, [self.equal_best], self.target))

    def test_tiebreak_prioritizes_total_date_deviation(self):
        lower_total_deviation = make_option([
            make_item(110, 150_000_000, 0),
            make_item(111, 93_152_828, 0),
            make_item(112, 62_500_000, 6),
        ])
        lower_max_but_higher_total = make_option([
            make_item(120, 150_000_000, 2),
            make_item(121, 93_152_828, 2),
            make_item(122, 62_500_000, 3),
        ])
        result = cp.deduplicate_commercial_options(
            [lower_max_but_higher_total, lower_total_deviation], self.target, 0, "acobrar"
        )
        self.assertEqual(
            {110, 111, 112},
            {item.raw["IdENTREGA"] for item in result[0].items},
        )

    def test_same_side_options_under_ten_thousand_are_too_similar(self):
        under_ten_thousand = make_option([
            make_item(130, 150_000_000, 0),
            make_item(131, 93_152_828, 0),
            make_item(132, 62_000_000, 0),
        ])
        exactly_ten_thousand = make_option([
            make_item(140, 150_000_000, 0),
            make_item(141, 93_152_828, 0),
            make_item(142, 61_500_000, 0),
        ])
        self.assertTrue(cp.options_are_too_similar(under_ten_thousand, [self.equal_best], self.target))
        self.assertFalse(cp.options_are_too_similar(exactly_ten_thousand, [self.equal_best], self.target))

    def test_global_best_below_is_preserved_and_once(self):
        result = cp.select_diverse_options(
            [self.equal_far, self.equal_best, self.equal_middle, self.other_below, self.above],
            self.target,
            0,
            3,
            10.0,
            "acobrar",
        )
        self.assertEqual(305_652_828, result[0].total_cents)
        self.assertEqual(1, sum(option.total_cents == 305_652_828 for option in result))

    def test_distinct_below_total_can_be_shown(self):
        result = cp.select_diverse_options(
            [self.equal_best, self.other_below, self.above], self.target, 0, 3, 10.0, "acobrar"
        )
        self.assertIn(self.other_below.total_cents, [option.total_cents for option in result])

    def test_best_above_is_shown(self):
        result = cp.select_diverse_options(
            [self.equal_best, self.other_below, self.above], self.target, 0, 3, 10.0, "acobrar"
        )
        self.assertIn(self.above.total_cents, [option.total_cents for option in result])

    def test_exact_always_wins_and_preserves_both_sides(self):
        exact = make_option([make_item(400, self.target, 0)])
        result = cp.select_diverse_options(
            [self.other_below, self.above, exact], self.target, 0, 3, 10.0, "acobrar"
        )
        self.assertEqual(self.target, result[0].total_cents)
        self.assertEqual(
            ["EXACTA", "POR_DEBAJO", "POR_ENCIMA"],
            [cp.difference_direction(option.total_cents, self.target) for option in result],
        )

    def test_only_one_valid_option_returns_one(self):
        result = cp.select_diverse_options([self.equal_best], self.target, 0, 3, 10.0, "acobrar")
        self.assertEqual(1, len(result))

    def test_two_valid_options_return_two(self):
        result = cp.select_diverse_options(
            [self.equal_best, self.above], self.target, 0, 3, 10.0, "acobrar"
        )
        self.assertEqual(2, len(result))

    def test_same_combination_in_different_order_is_not_repeated(self):
        reversed_option = make_option(list(reversed(self.equal_best.items)))
        result = cp.deduplicate_commercial_options(
            [self.equal_best, reversed_option], self.target, 0, "acobrar"
        )
        self.assertEqual(1, len(result))

    def test_real_case_total_appears_once(self):
        result = cp.select_diverse_options(
            [self.equal_far, self.equal_best, self.equal_middle, self.other_below, self.above],
            self.target,
            0,
            3,
            10.0,
            "acobrar",
        )
        rendered = cp.render_result(result, self.target, 0, "ECHEQ", 5, 5, 5, "BLANCO", "acobrar")
        self.assertEqual(1, rendered.count("Total: $ 3.056.528,28"))

    def test_optimize_end_to_end_deduplicates_real_case_structure(self):
        items = [
            make_item(500, 150_000_000, 0),
            make_item(501, 93_152_828, 0),
            make_item(502, 62_500_000, 0),
            make_item(503, 62_500_000, 2),
            make_item(504, 62_500_000, 5),
        ]
        result, _, _ = cp.optimize(
            items, "ECHEQ", self.target, 0, 3, 10, 3, 10.0, 15, 1000, "acobrar"
        )
        self.assertEqual(1, sum(option.total_cents == 305_652_828 for option in result))

    def test_items_are_not_split_or_reused_inside_combination(self):
        result = cp.select_diverse_options(
            [self.equal_best, self.other_below, self.above], self.target, 0, 3, 10.0, "acobrar"
        )
        for option in result:
            ids = [item.raw["IdENTREGA"] for item in option.items]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(option.total_cents, sum(item.amount_cents for item in option.items))


class SimplePaymentRulesTests(unittest.TestCase):
    def json_row(self, item_id, *, observation="", state="EN CAJA", kind="ECHEQ", amount=1000, due=None):
        today = date.today()
        due = due or today
        return {
            "IdENTREGA": item_id,
            "Estado": state,
            "Observacion": observation,
            "Tipo": kind,
            "Importe": amount,
            "FechaCobro": due.isoformat(),
            "DiasRestantes": (due - today).days,
            "DiasAlVencimiento": 30,
            "Banco": "BANCO",
            "Numero": str(item_id),
            "Cliente": "CLIENTE",
        }

    @staticmethod
    def date_with_business_days_elapsed(days):
        today = date.today()
        candidate = today
        while cp.business_days_elapsed(candidate, today) < days:
            candidate -= timedelta(days=1)
        while cp.business_days_elapsed(candidate, today) > days:
            candidate += timedelta(days=1)
        return candidate

    def load(self, rows, fiscal_filter="TODOS", source="acobrar"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cartera.json"
            path.write_text(json.dumps({"Registros": rows}), encoding="utf-8")
            return cp.load_items(path, fiscal_filter, source)

    def test_filters_states_types_and_business_day_limit(self):
        rows = [
            self.json_row(1, observation=""),
            self.json_row(2, observation=None),
            self.json_row(3, observation="   ", kind="CHEQUE FÍSICO"),
            self.json_row(4, observation="*"),
            self.json_row(5, observation="NN"),
            self.json_row(6, observation="EN CUENTA HUGO"),
            self.json_row(7, observation="EN CUENTA GASTON"),
            self.json_row(8, observation="Con factura"),
            self.json_row(9, state="ENTREGADO"),
            self.json_row(10, state="DEPOSITADO"),
            self.json_row(11, due=self.date_with_business_days_elapsed(30)),
            self.json_row(12, due=self.date_with_business_days_elapsed(31)),
            self.json_row(13, kind="E-CHEQUE"),
        ]
        all_items, error = self.load(rows)
        self.assertIsNone(error)
        self.assertEqual({1, 2, 3, 4, 5, 6, 7, 11, 13}, {item.raw["IdENTREGA"] for item in all_items})
        blank, _ = self.load(rows, "BLANCO")
        nn, _ = self.load(rows, "NN")
        self.assertEqual({1, 2, 3, 11, 13}, {item.raw["IdENTREGA"] for item in blank})
        self.assertEqual({4, 5, 6, 7}, {item.raw["IdENTREGA"] for item in nn})
        self.assertIn(cp.TYPE_CHECK, {item.item_type for item in all_items})
        self.assertIn(cp.TYPE_ECHEQ, {item.item_type for item in all_items})

    def test_all_confirmed_type_aliases_are_normalized(self):
        for value in ("CHEQUE", "CHEQUE FISICO", "CHEQUE FÍSICO"):
            self.assertEqual(cp.TYPE_CHECK, cp.normalize_type(value))
        for value in ("ECHEQ", "E-CHEQ", "ECHEQUE", "E-CHEQUE", "ECHQ"):
            self.assertEqual(cp.TYPE_ECHEQ, cp.normalize_type(value))

    def test_modes_acobrar_and_future_window(self):
        items = [
            make_item(1, 100_000, -2, item_type=cp.TYPE_ECHEQ),
            make_item(2, 110_000, 0, item_type=cp.TYPE_CHECK),
            make_item(3, 120_000, 10, item_type=cp.TYPE_ECHEQ),
            make_item(4, 130_000, 16, item_type=cp.TYPE_CHECK),
            make_item(5, 140_000, 30, item_type=cp.TYPE_ECHEQ),
            make_item(6, 150_000, 45, item_type=cp.TYPE_CHECK),
        ]
        due, _, _ = cp.optimize_mode(items, "MIXTO", 330_000, 0, 3, 20, 3, 10, 15, 1000, "acobrar")
        future, _, _ = cp.optimize_mode(items, "MIXTO", 290_000, 30, 3, 20, 3, 10, 15, 1000, "dias")
        cheque, _, _ = cp.optimize_mode(items, "CHEQUE", 260_000, 0, 3, 20, 3, 10, 15, 1000, "acobrar")
        echeq, _, _ = cp.optimize_mode(items, "ECHEQ", 220_000, 0, 3, 20, 3, 10, 15, 1000, "acobrar")
        self.assertTrue(due)
        self.assertTrue(all(item.days <= 15 for option in due for item in option.items))
        self.assertTrue(future)
        self.assertTrue(all(30 <= item.days <= 45 for option in future for item in option.items))
        self.assertTrue(all(item.item_type == cp.TYPE_CHECK for option in cheque for item in option.items))
        self.assertTrue(all(item.item_type == cp.TYPE_ECHEQ for option in echeq for item in option.items))

    def test_exact_under_over_empty_and_threshold_messages(self):
        self.assertLess(cp.ranking_key(make_option([make_item(1, 100_000)]), 100_000), cp.ranking_key(make_option([make_item(2, 99_999)]), 100_000))
        self.assertIn("transferencia", cp.format_difference_and_suggestion(-9_999_999)[1].lower())
        self.assertIn("propio", cp.format_difference_and_suggestion(-10_000_000)[1].lower())
        self.assertIn("excede", cp.format_difference_and_suggestion(1)[1].lower())
        self.assertNotIn("nota de cr", cp.format_difference_and_suggestion(1)[1].lower())
        self.assertEqual("No se encuentra combinación de cheques.", cp.render_result([], 1, 0, "MIXTO", 0, 0, 0))

    def test_performance_20_40_80_values(self):
        for count in (20, 40, 80):
            items = [make_item(index, 10_000 + (index % 11) * 1_000, index % 15) for index in range(1, count + 1)]
            started = time.perf_counter()
            options, _, evaluated = cp.optimize(items, "OPTIMO", 250_000, 0, 3, 35, 8, 10, 15, 50_000, "acobrar")
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 5.0, f"{count} valores tardaron {elapsed:.3f}s")
            self.assertLessEqual(evaluated, 150_000)
            self.assertTrue(options)

    def test_optimizer_never_returns_total_above_target(self):
        options, _, _ = cp.optimize(
            [make_item(900, 149_023_600, 45)],
            "ECHEQ",
            34_500_075,
            40,
            3,
            10,
            8,
            10.0,
            15,
            1000,
            "dias",
        )
        self.assertEqual([], options)

    def test_current_portfolio_validation_is_present_in_orchestrator(self):
        script = (Path(__file__).parents[1] / "armar_pago_optimo.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Assert-JsonCarteraActual", script)
        self.assertIn("cheques_debug.json", script)
        self.assertIn("LastWriteTime", script)
        self.assertIn("FechaConsulta", script)
        self.assertIn('Properties.Name -contains "Registros"', script)
        self.assertIn("[guid]::NewGuid()", script)
        self.assertIn("if (-not $carteraJsonExiste)", script)
        self.assertNotIn(
            'if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $jsonPath))',
            script,
        )

    def test_orchestrator_uses_fresh_valid_json_if_child_fails_after_export(self):
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(Path(__file__).parents[1] / "armar_pago_optimo.ps1", root)
            shutil.copy2(MODULE_PATH, root)
            (root / "gestion_cheques.ps1").write_text(
                "param([string]$Accion,[string]$Tipo,[int]$Dias,[string]$OutJson)\n"
                "$data = [pscustomobject]@{ FechaConsulta=(Get-Date).Date.ToString('yyyy-MM-dd'); Registros=@() }\n"
                "$data | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutJson -Encoding UTF8\n"
                "exit 5\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(root / "armar_pago_optimo.ps1"),
                    "-Importe",
                    "852412",
                    "-Dias",
                    "45",
                    "-Modo",
                    "ECHEQ",
                    "-FiltroFiscal",
                    "BLANCO",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("No se encuentra combinaci", completed.stdout)
        self.assertNotIn("No se pudo preparar la cartera", completed.stdout + completed.stderr)

    def test_orchestrator_rejects_child_failure_before_json_export(self):
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(Path(__file__).parents[1] / "armar_pago_optimo.ps1", root)
            shutil.copy2(MODULE_PATH, root)
            (root / "gestion_cheques.ps1").write_text(
                "param([string]$Accion,[string]$Tipo,[int]$Dias,[string]$OutJson)\nexit 5\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(root / "armar_pago_optimo.ps1"),
                    "-Importe",
                    "852412",
                    "-Dias",
                    "45",
                    "-Modo",
                    "ECHEQ",
                    "-FiltroFiscal",
                    "BLANCO",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("No se pudo preparar la cartera", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
