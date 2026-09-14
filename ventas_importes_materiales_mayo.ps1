param(
    [datetime]$Desde = "2026-05-01",
    [datetime]$Hasta = "2026-06-01",
    [string]$OutCsv = ""
)

$ErrorActionPreference = "Stop"

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

    if ($p -eq "ARENA ZARANDEADA") { return "Arena zarandeada" }
    if ($p -eq "ARENA BRUTA") { return "Arena bruta" }
    if ($p -eq "GRANZA 5/8") { return "Granza 5/8" }
    if ($p -eq "GRANZA 3/8") { return "Granza 3/8" }
    if ($p -eq "PIEDRA 1-3") { return "Piedra 1-3" }
    if ($p -like "PIEDRA BOLA*") { return "Piedra bola" }
    if ($p -eq "ARENA FINA") { return "Arena fina" }
    if ($p -eq "ARENA FINA PARANA") { return "Arena fina Parana" }

    if ($p -like "*GRAVA*2-4*") { return "Grava 2-4 mm" }
    if ($p -like "*GRAVA*3-6*") { return "Grava 3-6 mm" }
    if ($p -like "*GRAVA*6-9*") { return "Grava 6-9 mm" }
    if ($p -like "*GRAVA*N°12*" -or $p -like "*GRAVA*N12*") { return "Grava N12" }
    if ($p -like "*GRAVA*N°15*" -or $p -like "*GRAVA*N15*") { return "Grava N15" }
    if ($p -like "*GRAVA*N°20*" -or $p -like "*GRAVA*N20*") { return "Grava N20" }

    return $null
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $from = Date-Literal $Desde
    $to = Date-Literal $Hasta
    $sql = @"
SELECT D.PRODUCTO, D.UNIDAD, D.CANTIDAD, D.[Subtot] AS Subtotal, D.[Subtot c/IVA] AS SubtotalConIva, C.FECHA, C.TIPO
FROM COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D
    ON C.IdCOMPROVANTE = D.IdCOMPROVANTE
WHERE C.FECHA >= $from
    AND C.FECHA < $to
    AND D.PRODUCTO Is Not Null
"@
    $data = Rows ($conn.Execute($sql))

    $totals = [ordered]@{}
    $details = @()
    foreach ($row in $data) {
        $product = Normalize-Product ([string]$row.PRODUCTO)
        if (-not $product) { continue }

        $subtotal = if ($null -eq $row.Subtotal) { [decimal]0 } else { [decimal]$row.Subtotal }
        if (-not $totals.Contains($product)) {
            $totals[$product] = [decimal]0
        }
        $totals[$product] += $subtotal

        $details += [pscustomobject]@{
            ProductoOriginal = $row.PRODUCTO
            Producto = $product
            Unidad = $row.UNIDAD
            Cantidad = $row.CANTIDAD
            Subtotal = [double]$subtotal
            Fecha = $row.FECHA
            Tipo = $row.TIPO
        }
    }

    $rows = foreach ($key in $totals.Keys) {
        [pscustomobject]@{
            Producto = $key
            Importe = [double]$totals[$key]
        }
    }
    $rows = $rows | Sort-Object Importe -Descending

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
