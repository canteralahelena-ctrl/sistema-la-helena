param(
    [datetime]$Desde = "2026-05-01",
    [datetime]$Hasta = "2026-06-01",
    [string]$OutCsv = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "normalizacion_unidades.ps1")

$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Rows($recordset, [int]$maxRows = 100000) {
    $rows = @()
    while (-not $recordset.EOF -and $rows.Count -lt $maxRows) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $recordset.Fields.Count; $i++) {
            $row[$recordset.Fields.Item($i).Name] = $recordset.Fields.Item($i).Value
        }
        $rows += [pscustomobject]$row
        $recordset.MoveNext()
    }
    return $rows
}

function Normalize-Product([string]$product) {
    if (-not $product) { return $null }
    $p = $product.Trim().ToUpperInvariant()
    $p = $p -replace '\s+', ' '

    if ($p -eq "ARENA ZARANDEADA") { return "Arena zarandeada" }
    if ($p -eq "ARENA BRUTA") { return "Arena bruta" }
    if ($p -eq "GRANZA 5/8") { return "Granza 5/8" }
    if ($p -eq "GRANZA 3/8") { return "Granza 3/8" }
    if ($p -eq "PIEDRA 1-3") { return "Piedra 1-3" }
    if ($p -like "PIEDRA BOLA*") { return "Piedra bola" }
    if ($p -eq "ARENA FINA") { return "Arena fina" }
    if ($p -eq "ARENA FINA PARANA" -or $p -eq "ARENA FINA PARANA") { return "Arena fina Parana" }
    return $null
}

function Normalize-Unit([string]$unit) {
    return Normalize-HelenaUnit $unit
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $from = Date-Literal $Desde
    $to = Date-Literal $Hasta
    $sql = @"
SELECT D.PRODUCTO, D.UNIDAD, D.CANTIDAD, C.FECHA, C.TIPO
FROM COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D
    ON C.IdCOMPROVANTE = D.IdCOMPROVANTE
WHERE C.FECHA >= $from
    AND C.FECHA < $to
    AND D.CANTIDAD Is Not Null
    AND D.PRODUCTO Is Not Null
"@
    $data = Rows ($conn.Execute($sql))

    $totals = [ordered]@{}
    $units = @()
    foreach ($row in $data) {
        $product = Normalize-Product ([string]$row.PRODUCTO)
        if (-not $product) { continue }

        $qty = [decimal]$row.CANTIDAD
        $unit = Normalize-Unit ([string]$row.UNIDAD)
        $m3 = $qty
        if ($unit -eq "TN" -or $unit -eq "T") {
            $m3 = $qty / [decimal]1.5
        }
        elseif ($unit -eq "M3" -or $unit -eq "MTR3" -or $unit -eq "M³") {
            $m3 = $qty
        }
        else {
            $units += [pscustomobject]@{
                Producto = $row.PRODUCTO
                Unidad = $row.UNIDAD
                Cantidad = $qty
            }
            continue
        }

        if (-not $totals.Contains($product)) {
            $totals[$product] = [decimal]0
        }
        $totals[$product] += $m3
    }

    $rows = foreach ($key in $totals.Keys) {
        [pscustomobject]@{
            Producto = $key
            M3 = [double]$totals[$key]
        }
    }
    $rows = $rows | Sort-Object M3 -Descending

    if ($OutCsv) {
        $rows | Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8
    }

    $rows | Format-Table -AutoSize
    if ($units.Count -gt 0) {
        Write-Host ""
        Write-Host "Unidades omitidas por no ser m3/TN:"
        $units | Group-Object Producto, Unidad | Select-Object Count, Name | Format-Table -AutoSize
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
