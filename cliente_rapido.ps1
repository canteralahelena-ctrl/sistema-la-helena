param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [string]$DatabasePath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"
if ($DatabasePath) {
    if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
        throw "No existe la base indicada en DatabasePath."
    }
    $dbPath = $DatabasePath
}

function Sql-Text([string]$value) {
    return $value.Replace("'", "''")
}

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Rows($recordset, [int]$maxRows = 100) {
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

function Scalar($connection, [string]$sql) {
    $rs = $connection.Execute($sql)
    if ($rs.EOF -or $null -eq $rs.Fields.Item(0).Value) {
        return $null
    }
    return $rs.Fields.Item(0).Value
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    if ($Cliente -match '^\d+$') {
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL], CUIT, LOCALIDAD FROM CLIENTES WHERE IdCLIENTE=$Cliente"
    } else {
        $q = Sql-Text $Cliente
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL], CUIT, LOCALIDAD FROM CLIENTES WHERE [RAZ SOCIAL] LIKE '%$q%' ORDER BY [RAZ SOCIAL]"
    }

    $clients = Rows ($conn.Execute($clientSql)) 20

    if ($clients.Count -eq 0) {
        Write-Host "No encontre cliente: $Cliente"
        return
    }

    if ($clients.Count -gt 1) {
        Write-Host "Hay varios clientes. Usa el IdCLIENTE:"
        $clients | Format-Table -AutoSize
        return
    }

    $client = $clients[0]
    $id = [int]$client.IdCLIENTE

    $debeValue = Scalar $conn "SELECT Sum(SALDO) FROM COMPROVANTES WHERE IdCLIENTE=$id AND SALDO<>0"
    $haberValue = Scalar $conn "SELECT Sum(SALDO) FROM PAGOS WHERE IdCLIENTE='$id' AND SALDO<>0"
    $debe = if ($null -eq $debeValue) { [decimal]0 } else { [decimal]$debeValue }
    $haber = if ($null -eq $haberValue) { [decimal]0 } else { [decimal]$haberValue }
    $saldo = $debe - $haber

    $lastPaymentSql = @"
SELECT TOP 1 IdPAGO, FECHA, MONTO, TIPO, SALDO
FROM PAGOS
WHERE IdCLIENTE='$id'
ORDER BY FECHA DESC, IdPAGO DESC
"@
    $lastPayments = Rows ($conn.Execute($lastPaymentSql)) 1

    Write-Host "Cliente: $($client.'RAZ SOCIAL')"
    Write-Host "IdCLIENTE: $id"
    Write-Host "CUIT: $($client.CUIT)"
    Write-Host "Localidad: $($client.LOCALIDAD)"
    Write-Host "Saldo actual: $(Money $saldo)"

    if ($lastPayments.Count -eq 0) {
        Write-Host "Ultimo pago: sin pagos registrados"
    } else {
        $p = $lastPayments[0]
        Write-Host "Ultimo pago: $(([datetime]$p.FECHA).ToString('dd/MM/yyyy HH:mm:ss')) - $(Money ([decimal]$p.MONTO)) - $($p.TIPO) - IdPago $($p.IdPAGO)"
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
