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
    $p = $p -replace 'º', '°'

    if ($p -like "*2-4*") { return "Grava 2-4 mm" }
    if ($p -like "*3-6*") { return "Grava 3-6 mm" }
    if ($p -like "*6-9*") { return "Grava 6-9 mm" }
    if ($p -like "*N°12*" -or $p -like "*N12*") { return "Grava N12" }
    if ($p -like "*N°15*" -or $p -like "*N15*") { return "Grava N15" }
    if ($p -like "*N°20*" -or $p -like "*N20*") { return "Grava N20" }
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
    AND D.PRODUCTO LIKE '%grava%'
"@
    $data = Rows ($conn.Execute($sql))

    $expected = @(
        "Grava 2-4 mm",
        "Grava 3-6 mm",
        "Grava N12",
        "Grava N15",
        "Grava N20",
        "Grava 6-9 mm"
    )

    $totals = [ordered]@{}
    foreach ($name in $expected) { $totals[$name] = [decimal]0 }
    $details = @()

    foreach ($row in $data) {
        $product = Normalize-Product ([string]$row.PRODUCTO)
        if (-not $product) { continue }

        $qty = [decimal]$row.CANTIDAD
        $unit = Normalize-Unit ([string]$row.UNIDAD)
        $m3 = $null
        $conversion = ""

        if ($unit -eq "TN" -or $unit -eq "T") {
            $m3 = $qty / [decimal]1.5
            $conversion = "TN / 1,5"
        }
        elseif ($unit -eq "M3" -or $unit -eq "MTR3" -or $unit -eq "M³") {
            $m3 = $qty
            $conversion = "m3 directo"
        }
        elseif ($unit -like "*1200KG*") {
            $m3 = $qty * [decimal]0.8
            $conversion = "bolson * 0,8"
        }
        elseif ($unit -like "*25KG*") {
            $m3 = $qty * [decimal]0.01666
            $conversion = "bolsa * 0,01666"
        }

        if ($null -eq $m3) { continue }
        $totals[$product] += $m3
        $details += [pscustomobject]@{
            ProductoOriginal = $row.PRODUCTO
            Producto = $product
            Unidad = $row.UNIDAD
            Cantidad = [double]$qty
            M3 = [double]$m3
            Conversion = $conversion
        }
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
        $detailPath = [System.IO.Path]::ChangeExtension($OutCsv, ".detalle.csv")
        $details | Export-Csv -LiteralPath $detailPath -NoTypeInformation -Encoding UTF8
    }

    $rows | Format-Table -AutoSize
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
