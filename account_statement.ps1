param(
    [Parameter(Mandatory = $true)]
    [int]$ClientId,
    [datetime]$From = "2026-01-01",
    [string]$Database = "backend"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

function Scalar($sql) {
    $rs = $conn.Execute($sql)
    if ($rs.EOF -or $null -eq $rs.Fields.Item(0).Value) { return 0 }
    return [decimal]$rs.Fields.Item(0).Value
}

function DateLiteral([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

try {
    $fromLiteral = DateLiteral $From
    $initialDebe = Scalar "SELECT Sum(SALDO) FROM COMPROVANTES WHERE IdCLIENTE=$ClientId AND FECHA<$fromLiteral"
    $initialHaber = Scalar "SELECT Sum(SALDO) FROM PAGOS WHERE IdCLIENTE='$ClientId' AND FECHA<$fromLiteral"
    $balance = $initialDebe - $initialHaber

    $sql = @"
SELECT FECHA, TIPO, Numero, Debe, Haber, IdMov
FROM (
    SELECT FECHA, TIPO, [Nº] AS Numero, SALDO AS Debe, 0 AS Haber, IdCOMPROVANTE AS IdMov
    FROM COMPROVANTES
    WHERE IdCLIENTE=$ClientId AND FECHA>=$fromLiteral AND SALDO<>0
    UNION ALL
    SELECT FECHA, 'PAGO' AS TIPO, IdPAGO AS Numero, 0 AS Debe, SALDO AS Haber, IdPAGO AS IdMov
    FROM PAGOS
    WHERE IdCLIENTE='$ClientId' AND FECHA>=$fromLiteral AND SALDO<>0
)
ORDER BY FECHA, IdMov
"@
    $rs = $conn.Execute($sql)
    $rows = @()
    while (-not $rs.EOF) {
        $debe = [decimal]$rs.Fields.Item("Debe").Value
        $haber = [decimal]$rs.Fields.Item("Haber").Value
        $balance = $balance + $debe - $haber
        $rows += [pscustomobject]@{
            Fecha = ([datetime]$rs.Fields.Item("FECHA").Value).ToString("dd/MM/yyyy")
            Tipo = $rs.Fields.Item("TIPO").Value
            Numero = $rs.Fields.Item("Numero").Value
            Debe = $debe
            Haber = $haber
            Saldo = $balance
        }
        $rs.MoveNext()
    }

    [pscustomobject]@{
        Cliente = $ClientId
        Desde = $From.ToString("dd/MM/yyyy")
        SaldoInicial = $initialDebe - $initialHaber
        Movimientos = $rows.Count
        SaldoFinal = $balance
    } | Format-List

    $rows | Select-Object -Last 40 | Format-Table -AutoSize
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
