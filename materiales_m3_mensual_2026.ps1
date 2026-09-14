param(
    [datetime]$Desde = "2026-01-01",
    [datetime]$Hasta = "2027-01-01",
    [string]$OutCsv = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "normalizacion_unidades.ps1")

$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Rows($recordset, [int]$maxRows = 1000000) {
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

function Normalize-Text([string]$text) {
    if (-not $text) { return "" }
    return ($text.Trim().ToUpperInvariant() -replace '\s+', ' ')
}

function Normalize-Product([string]$product) {
    $p = Normalize-Text $product
    if (-not $p) { return $null }

    if ($p -like "*ARENA ZARANDEADA*") { return "Arena zarandeada" }
    if ($p -like "*ARENA BRUTA*") { return "Arena bruta" }
    if ($p -like "*ARENA FINA PARANA*" -or $p -like "*ARENA PARANA*") { return "Arena fina Parana" }
    if ($p -like "*ARENA FINA*") { return "Arena fina" }
    if ($p -eq "GRANZA 5/8") { return "Granza 5/8" }
    if ($p -eq "GRANZA 3/8") { return "Granza 3/8" }
    if ($p -like "*GRANZA 5/8*") { return "Granza 5/8" }
    if ($p -like "*GRANZA 3/8*") { return "Granza 3/8" }
    if ($p -like "*GRANZA*") { return "Granza sin especificar" }
    if ($p -like "*PIEDRA*1-3*") { return "Piedra 1-3" }
    if ($p -like "*PIEDRA BOLA*") { return "Piedra bola" }

    if ($p -like "*2-4*") { return "Grava 2-4 mm" }
    if ($p -like "*3-6*") { return "Grava 3-6 mm" }
    if ($p -like "*3-8*") { return "Grava 3-8 mm" }
    if ($p -like "*6-9*") { return "Grava 6-9 mm" }
    if ($p -like "*N12*" -or $p -like "*N 12*") { return "Grava N12" }
    if ($p -like "*N15*" -or $p -like "*N 15*") { return "Grava N15" }
    if ($p -like "*N20*" -or $p -like "*N 20*") { return "Grava N20" }

    return $null
}

function Normalize-Unit([string]$unit) {
    return Normalize-HelenaUnit $unit
}

function Convert-ToM3([decimal]$qty, [string]$unit) {
    $u = Normalize-Unit $unit
    if ($u -eq "TN" -or $u -eq "T") { return $qty / [decimal]1.5 }
    if ($u -eq "M3" -or $u -eq "MTR3" -or $u -like "M*3") { return $qty }
    if ($u -like "*1200KG*") { return $qty * [decimal]0.8 }
    if ($u -like "*25KG*") { return $qty * [decimal]0.01666 }
    return $null
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

    $totals = @{}
    $details = @()
    $omitted = @()

    foreach ($row in $data) {
        $product = Normalize-Product ([string]$row.PRODUCTO)
        if (-not $product) { continue }

        $qty = [decimal]$row.CANTIDAD
        $m3 = Convert-ToM3 $qty ([string]$row.UNIDAD)
        $productText = Normalize-Text ([string]$row.PRODUCTO)
        if ($null -eq $m3 -and ($productText -like "*BOLSON*" -or $productText -like "*BIG BAG*")) {
            $m3 = $qty * [decimal]0.8
        }
        if ($null -eq $m3 -and $productText -like "*BOLSA*" -and $productText -like "*25*") {
            $m3 = $qty * [decimal]0.01666
        }
        if ($null -eq $m3) {
            $omitted += [pscustomobject]@{
                ProductoOriginal = $row.PRODUCTO
                Unidad = $row.UNIDAD
                Cantidad = [double]$qty
            }
            continue
        }

        $date = [datetime]$row.FECHA
        $month = "{0:yyyy-MM}" -f $date
        $key = "$product|$month"
        if (-not $totals.ContainsKey($key)) {
            $totals[$key] = [decimal]0
        }
        $totals[$key] += $m3

        $details += [pscustomobject]@{
            Fecha = $date
            Mes = $month
            Tipo = $row.TIPO
            ProductoOriginal = $row.PRODUCTO
            Producto = $product
            Unidad = $row.UNIDAD
            Cantidad = [double]$qty
            M3 = [double]$m3
        }
    }

    $rows = foreach ($key in $totals.Keys) {
        $parts = $key -split '\|', 2
        [pscustomobject]@{
            Material = $parts[0]
            Mes = $parts[1]
            M3 = [double]$totals[$key]
        }
    }
    $rows = $rows | Sort-Object Mes, Material

    if ($OutCsv) {
        $rows | Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8
        $detailPath = [System.IO.Path]::ChangeExtension($OutCsv, ".detalle.csv")
        $omitPath = [System.IO.Path]::ChangeExtension($OutCsv, ".omitidas.csv")
        $details | Export-Csv -LiteralPath $detailPath -NoTypeInformation -Encoding UTF8
        $omitted | Export-Csv -LiteralPath $omitPath -NoTypeInformation -Encoding UTF8
    }

    $rows | Format-Table -AutoSize
    if ($omitted.Count -gt 0) {
        Write-Host ""
        Write-Host "Unidades omitidas por no tener conversion a m3:"
        $omitted | Group-Object ProductoOriginal, Unidad | Select-Object Count, Name | Format-Table -AutoSize
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
