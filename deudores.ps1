param(
    [int]$Top = 0,
    [switch]$ExportCsv
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$outputRoot = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
$outputPath = Join-Path $outputRoot "deudores.csv"

function Format-Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Get-Rows($recordset, [int]$maxRows = 100000) {
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

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $sql = @"
SELECT
    C.IdCLIENTE,
    C.[RAZ SOCIAL] AS RazonSocial,
    C.CUIT,
    C.LOCALIDAD,
    IIf(IsNull(D.Debe), 0, D.Debe) AS Debe,
    IIf(IsNull(H.Haber), 0, H.Haber) AS Haber,
    IIf(IsNull(D.Debe), 0, D.Debe) - IIf(IsNull(H.Haber), 0, H.Haber) AS Saldo
FROM
    (CLIENTES AS C
    LEFT JOIN
        (SELECT IdCLIENTE, Sum(SALDO) AS Debe
         FROM COMPROVANTES
         WHERE SALDO<>0
         GROUP BY IdCLIENTE) AS D
    ON C.IdCLIENTE = D.IdCLIENTE)
    LEFT JOIN
        (SELECT IdCLIENTE AS ClienteId, Sum(SALDO) AS Haber
         FROM PAGOS
         WHERE SALDO<>0
         GROUP BY IdCLIENTE) AS H
    ON CStr(C.IdCLIENTE) = H.ClienteId
WHERE IIf(IsNull(D.Debe), 0, D.Debe) - IIf(IsNull(H.Haber), 0, H.Haber) > 0
ORDER BY C.[RAZ SOCIAL]
"@
    $rows = Get-Rows ($conn.Execute($sql))

    $report = foreach ($row in $rows) {
        [pscustomobject]@{
            IdCLIENTE = [int]$row.IdCLIENTE
            RazonSocial = $row.RazonSocial
            CUIT = $row.CUIT
            Localidad = $row.LOCALIDAD
            SaldoNumero = [decimal]$row.Saldo
            Saldo = Format-Money ([decimal]$row.Saldo)
        }
    }

    $total = ($report | Measure-Object -Property SaldoNumero -Sum).Sum
    Write-Host "Clientes deudores: $($report.Count)"
    Write-Host "Total deuda: $(Format-Money ([decimal]$total))"
    Write-Host ""

    $display = if ($Top -gt 0) { $report | Select-Object -First $Top } else { $report }
    $display | Select-Object IdCLIENTE, RazonSocial, Localidad, Saldo | Format-Table -AutoSize

    if ($ExportCsv) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
        $report |
            Select-Object IdCLIENTE, RazonSocial, CUIT, Localidad, SaldoNumero |
            Export-Csv -LiteralPath $outputPath -NoTypeInformation -Encoding UTF8
        Write-Host ""
        Write-Host "CSV exportado: $outputPath"
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
