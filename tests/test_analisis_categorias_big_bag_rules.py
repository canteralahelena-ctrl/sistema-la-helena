import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class AnalisisCategoriasBigBagRulesTests(unittest.TestCase):
    def run_function_probe(self, body, names):
        script_path = Path(__file__).resolve().parents[1] / "analisis_categorias.ps1"
        helper_path = Path(__file__).resolve().parents[1] / "normalizacion_unidades.ps1"
        probe = r"""
param([string]$ScriptPath, [string]$HelperPath, [string]$Body, [string]$NamesJson)
$errors = $null
$tokens = $null
$OutputEncoding = [Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
. $HelperPath
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw ($errors | Select-Object -First 1).Message }
foreach ($name in ($NamesJson | ConvertFrom-Json)) {
    $fn = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $fn) { throw "No se encontro funcion $name" }
    Invoke-Expression $fn.Extent.Text
}
Invoke-Expression $Body
"""
        with tempfile.TemporaryDirectory() as tmp:
            probe_path = Path(tmp) / "function_probe.ps1"
            probe_path.write_text(probe, encoding="utf-8")
            completed = subprocess.run(
                [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe_path),
                    "-ScriptPath", str(script_path), "-HelperPath", str(helper_path),
                    "-Body", body, "-NamesJson", json.dumps(names),
                ],
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        return json.loads(completed.stdout)

    def run_rule_probe(self, products):
        script_path = Path(__file__).resolve().parents[1] / "analisis_categorias.ps1"
        probe = r"""
param([string]$ScriptPath, [string]$ProductsJson)
$errors = $null
$tokens = $null
$OutputEncoding = [Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw ($errors | Select-Object -First 1).Message }
$names = @("Normalize-Key", "New-LineaInfo", "Get-ClasificacionManual")
foreach ($name in $names) {
    $fn = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $fn) { throw "No se encontro funcion $name" }
    Invoke-Expression $fn.Extent.Text
}
$products = $ProductsJson | ConvertFrom-Json
$results = foreach ($product in $products) {
    $info = Get-ClasificacionManual ([string]$product)
    if ($null -eq $info) {
        [pscustomobject]@{ Producto = $product; Linea = $null; Subcategoria = $null }
    }
    else {
        [pscustomobject]@{ Producto = $product; Linea = $info.Linea; Subcategoria = $info.Subcategoria }
    }
}
@($results) | ConvertTo-Json -Depth 4
"""
        with tempfile.TemporaryDirectory() as tmp:
            probe_path = Path(tmp) / "probe.ps1"
            probe_path.write_text(probe, encoding="utf-8")
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(probe_path),
                    "-ScriptPath",
                    str(script_path),
                    "-ProductsJson",
                    json.dumps(products),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        result = json.loads(completed.stdout)
        return result if isinstance(result, list) else [result]

    def test_big_bag_confirmed_families_are_aridos(self):
        products = [
            "BIG BAG ARENA FINA",
            "BIG-BAG ARENA FINA",
            "BIG BAG ARENA FINA PARANA",
            "BIG BAG ARENA FINA PARANÁ",
            "BIG BAG ARENA BRUTA",
            "BIG BAG GRANZA 5/8",
            "BIG BAG GRANZA 3/8",
            "BIG BAG PIEDRA 1-3",
        ]
        results = self.run_rule_probe(products)

        self.assertTrue(all(row["Linea"] == "ARIDOS" for row in results))
        self.assertEqual(
            [row["Subcategoria"] for row in results],
            ["ARENA", "ARENA", "ARENA", "ARENA", "ARENA", "GRANZA", "GRANZA", "PIEDRA"],
        )

    def test_unknown_big_bag_is_not_manually_classified(self):
        [result] = self.run_rule_probe(["BIG BAG MATERIAL DESCONOCIDO"])
        self.assertIsNone(result["Linea"])
        self.assertIsNone(result["Subcategoria"])

    def test_rejected_cheques_are_excluded_from_sales_universe(self):
        results = self.run_rule_probe([
            "ECHEQ RECHAZADO (67649060 - MACRO)",
            "CHEQUE RECHAZADO",
        ])
        self.assertTrue(all(row["Linea"] == "EXCLUIR_ANALISIS" for row in results))
        self.assertTrue(all(row["Subcategoria"] == "CHEQUE_RECHAZADO" for row in results))

    def test_supplier_payment_in_rmt_is_excluded_but_invoice_product_is_not(self):
        result = self.run_function_probe(
            "@{ Rmt=(Get-OperationalExclusion 'RMT' 'PAGO A PROVEEDOR'); Factura=(Get-OperationalExclusion 'FT A' 'PAGO A PROVEEDOR') } | ConvertTo-Json -Depth 4",
            ["Normalize-Key", "New-LineaInfo", "Get-OperationalExclusion"],
        )
        self.assertEqual(result["Rmt"]["Linea"], "EXCLUIR_ANALISIS")
        self.assertEqual(result["Rmt"]["Subcategoria"], "PAGO_PROVEEDOR")
        self.assertIsNone(result["Factura"])

    def test_granza_conversion_is_not_applied_globally(self):
        result = self.run_function_probe(
            "@{ Granza=(Convert-AridoToM3 15 'toneladas' 'GRANZA 5/8'); Arena=(Convert-AridoToM3 15 'TN' 'ARENA FINA'); M3=(Convert-AridoToM3 2 'Mtr3' 'ARENA FINA') } | ConvertTo-Json",
            ["Normalize-Key", "Normalize-Unit", "Convert-AridoToM3"],
        )
        self.assertEqual(result["Granza"], 10)
        self.assertIsNone(result["Arena"])
        self.assertEqual(result["M3"], 2)


if __name__ == "__main__":
    unittest.main()
