param(
    [string]$Medio = "",
    [datetime]$Desde = (Get-Date).Date,
    [datetime]$Hasta = (Get-Date).Date.AddDays(1),
    [switch]$Detalle
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$hardeningHelper = Join-Path $PSScriptRoot "access_hardening.ps1"
. $hardeningHelper
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
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

function Normalize-Medio([string]$tipo) {
    if (-not $tipo) { return "SIN_DETALLE" }
    $t = $tipo.Trim().ToUpperInvariant()
    if ($t -like "CHE*") { return "CHEQUE" }
    if ($t -like "ECH*") { return "ECHEQ" }
    if ($t -like "TRA*" -or $t -like "TRF*" -or $t -like "TRANS*") { return "TRANSFERENCIA" }
    if ($t -like "EFE*") { return "EFECTIVO" }
    if ($t -like "RET*") { return "RETENCION" }
    if ($t -like "FLE*") { return "FLETE" }
    if ($t -like "MAT*" -or $t -like "LAD*" -or $t -like "PAL*") { return "MATERIALES" }
    return "PAGOS_VARIOS"
}

function Medio-Like([string]$medio) {
    $m = $medio.Trim().ToUpperInvariant()
    if ($m -in @("", "TODOS", "TODO")) { return "" }
    if ($m -like "EFECT*") { return "E.TIPO LIKE 'EFE*'" }
    if ($m -like "TRANS*" -or $m -like "TRANSFER*") { return "(E.TIPO LIKE 'TRA*' OR E.TIPO LIKE 'TRF*' OR E.TIPO LIKE 'TRANS*')" }
    if ($m -like "ECHEQ*" -or $m -like "E-CHEQ*") { return "E.TIPO LIKE 'ECH*'" }
    if ($m -like "CHEQ*") { return "E.TIPO LIKE 'CHE*'" }
    if ($m -like "FLET*") { return "E.TIPO LIKE 'FLE*'" }
    if ($m -like "RET*") { return "E.TIPO LIKE 'RET*'" }
    if ($m -like "MAT*") { return "(E.TIPO LIKE 'MAT*' OR E.TIPO LIKE 'LAD*' OR E.TIPO LIKE 'PAL*')" }
    return "E.TIPO LIKE '$($m.Replace("'", "''"))*'"
}

$from = Date-Literal $Desde
$to = Date-Literal $Hasta
$whereMedio = Medio-Like $Medio
$whereMedioSql = if ($whereMedio) { "AND $whereMedio" } else { "" }

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $sql = @"
SELECT E.IdENTREGA, E.IdPAGO, P.FECHA, P.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente,
       P.TIPO AS TipoPagoSistema, E.TIPO AS MedioOriginal, E.BANCO, E.NUMERO,
       E.[FECHA A COBRAR] AS FechaACobrar, E.IMPORTE, E.ESTADO, E.[DEPOSITADO EN] AS DepositadoEn, E.UserID
FROM ([DETALLE DE ENTREGAS] AS E
INNER JOIN PAGOS AS P ON E.IdPAGO = P.IdPAGO)
LEFT JOIN CLIENTES AS CL ON Val(P.IdCLIENTE) = CL.IdCLIENTE
WHERE P.FECHA >= $from
  AND P.FECHA < $to
  $whereMedioSql
ORDER BY P.FECHA, E.IdPAGO, E.IdENTREGA
"@
    $rows = Rows ($conn.Execute($sql))
    $report = foreach ($r in $rows) {
        $idEntrega = ConvertTo-HelenaInteger $r.IdENTREGA "DETALLE DE ENTREGAS.IdENTREGA" "BLOCK" "cobros_medio"
        $idPago = ConvertTo-HelenaInteger $r.IdPAGO "DETALLE DE ENTREGAS.IdPAGO" "BLOCK" "IdENTREGA=$idEntrega"
        $fecha = ConvertTo-HelenaDate $r.FECHA "PAGOS.FECHA" "BLOCK" "IdPAGO=$idPago"
        $importe = ConvertTo-HelenaDecimal $r.IMPORTE "DETALLE DE ENTREGAS.IMPORTE" "BLOCK" "IdENTREGA=$idEntrega"
        [pscustomobject]@{
            Fecha = $fecha.ToString("dd/MM/yyyy HH:mm:ss")
            IdPAGO = $idPago
            Cliente = $r.Cliente
            TipoPagoSistema = $r.TipoPagoSistema
            Medio = Normalize-Medio ([string]$r.MedioOriginal)
            MedioOriginal = $r.MedioOriginal
            Banco = $r.BANCO
            Numero = $r.NUMERO
            Importe = $importe
            Estado = $r.ESTADO
            DepositadoEn = $r.DepositadoEn
            UserID = $r.UserID
        }
    }

    $total = ($report | Measure-Object -Property Importe -Sum).Sum
    $labelMedio = if ($Medio) { $Medio.ToUpperInvariant() } else { "TODOS LOS MEDIOS" }
    Write-Host "Cobros por medio: $labelMedio"
    Write-Host "Periodo: $($Desde.ToString('dd/MM/yyyy')) al $($Hasta.AddDays(-1).ToString('dd/MM/yyyy'))"
    Write-Host "Registros: $($report.Count)"
    Write-Host "Total: $(Money ([decimal]$total))"

    $byMedio = $report | Group-Object Medio | Sort-Object Name
    if ($byMedio.Count -gt 1 -or -not $Medio) {
        Write-Host ""
        Write-Host "Totales por medio:"
        foreach ($g in $byMedio) {
            $sum = ($g.Group | Measure-Object -Property Importe -Sum).Sum
            Write-Host "- $($g.Name): $($g.Count) registros, $(Money ([decimal]$sum))"
        }
    }

    if ($Detalle) {
        Write-Host ""
        $report | Select-Object Fecha, IdPAGO, Cliente, Medio, Banco, Numero, Importe, Estado | Format-Table -AutoSize
    }
}
catch {
    throw (Format-HelenaErrorDetail "pagos" "consultar_cobros_por_medio" $_ @{Medio=$Medio})
}
finally {
    if ($conn -and $conn.State -eq 1) { $conn.Close() }
}
