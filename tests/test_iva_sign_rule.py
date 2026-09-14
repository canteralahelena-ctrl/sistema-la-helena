import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "work_v2" / "iva_mensual.ps1"


def extract_powershell_function(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.index(marker)
    depth = 0
    end = start
    opened = False
    for index, char in enumerate(source[start:], start=start):
        if char == "{":
            depth += 1
            opened = True
        elif char == "}":
            depth -= 1
            if opened and depth == 0:
                end = index + 1
                break
    return source[start:end]


def run_sign_cases(cases):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    function_body = extract_powershell_function(SCRIPT.read_text(encoding="utf-8-sig"), "Normalize-GastoIvaComputado")
    ps_cases = ";".join(
        f"[pscustomobject]@{{Tipo='{tipo}';Iva=[decimal]'{iva}'}}"
        for tipo, iva in cases
    )
    command = (
        f"{function_body}\n"
        f"$cases = @({ps_cases});\n"
        "$cases | ForEach-Object { "
        "[pscustomobject]@{Tipo=$_.Tipo; Iva=[decimal]$_.Iva; Computado=(Normalize-GastoIvaComputado $_.Tipo $_.Iva)} "
        "} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(completed.stdout)
    return data if isinstance(data, list) else [data]


def run_table_alias_case(table_names):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    function_body = extract_powershell_function(SCRIPT.read_text(encoding="utf-8-sig"), "Resolve-GastoTableName")
    names = ",".join("'" + name.replace("'", "''") + "'" for name in table_names)
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"{function_body}\nResolve-GastoTableName @({names})",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


class IvaSignRuleTests(unittest.TestCase):
    def test_known_expense_table_alias_preserves_same_iva_query(self):
        self.assertEqual(
            run_table_alias_case(["CLIENTES", "COMPROBANTES DE GASTOS"]),
            "COMPROBANTES DE GASTOS",
        )
        self.assertEqual(
            run_table_alias_case(["COMPROVANTES DE GASTOS", "COMPROBANTES DE GASTOS"]),
            "COMPROVANTES DE GASTOS",
        )

    def test_expense_invoice_positive_keeps_sign(self):
        [row] = run_sign_cases([("FT A", "210000")])
        self.assertEqual(row["Computado"], 210000.0)

    def test_expense_credit_note_positive_subtracts_once(self):
        [row] = run_sign_cases([("NC A", "21000")])
        self.assertEqual(row["Computado"], -21000.0)

    def test_expense_credit_note_negative_is_not_inverted_twice(self):
        [row] = run_sign_cases([("NC A", "-21000")])
        self.assertEqual(row["Computado"], -21000.0)

    def test_zero_stays_zero(self):
        rows = run_sign_cases([("FT A", "0"), ("NC A", "0")])
        self.assertEqual([row["Computado"] for row in rows], [0.0, 0.0])

    def test_monthly_expenses_total_with_multiple_invoices_and_credit_notes(self):
        rows = run_sign_cases(
            [
                ("FT A", "210000"),
                ("FT B", "105000"),
                ("NC A", "21000"),
                ("NC B", "-5000"),
                ("NC SIN REF", "0"),
            ]
        )
        self.assertEqual(sum(row["Computado"] for row in rows), 289000.0)

    def test_work_and_v2_expected_rule_match_for_controlled_cases(self):
        rows = run_sign_cases([("FT A", "210000"), ("NC A", "21000"), ("NC A", "-21000"), ("NC A", "0")])
        v2_values = [row["Computado"] for row in rows]
        work_expected = [210000.0, -21000.0, -21000.0, 0.0]
        self.assertEqual(v2_values, work_expected)


if __name__ == "__main__":
    unittest.main()
