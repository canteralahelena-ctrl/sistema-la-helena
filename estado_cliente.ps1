param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [int]$Ultimos = 20,
    [datetime]$Desde = "1900-01-01"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }

function ConvertTo-SqlText([string]$value) {
    return $value.Replace("'", "''")
}

function Format-Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Get-Scalar($connection, [string]$sql) {
    $rs = $connection.Execute($sql)
    if ($rs.EOF -or $null -eq $rs.Fields.Item(0).Value) {
        return [decimal]0
    }
    return [decimal]$rs.Fields.Item(0).Value
}

function Get-Rows($recordset, [int]$maxRows = 1000) {
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

function Get-DateLiteral([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    if ($Cliente -match '^\d+$') {
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL], CUIT, CONTACTO, LOCALIDAD FROM CLIENTES WHERE IdCLIENTE=$Cliente"
    } else {
        $search = ConvertTo-SqlText $Cliente
        $clientSql = @"
SELECT IdCLIENTE, [RAZ SOCIAL], CUIT, CONTACTO, LOCALIDAD
FROM CLIENTES
WHERE [RAZ SOCIAL] LIKE '%$search%'
ORDER BY [RAZ SOCIAL]
"@
    }
    $clients = Get-Rows ($conn.Execute($clientSql)) 50

    if ($clients.Count -eq 0) {
        Write-Host "No encontre clientes que coincidan con: $Cliente"
        return
    }

    if ($clients.Count -gt 1) {
        Write-Host "Encontre varios clientes. Consulta de nuevo usando el IdCLIENTE exacto:"
        $clients | Select-Object IdCLIENTE, "RAZ SOCIAL", CUIT, CONTACTO, LOCALIDAD | Format-Table -AutoSize
        return
    }

    $client = $clients[0]
    $clientId = [int]$client.IdCLIENTE
    $fromLiteral = Get-DateLiteral $Desde

    $debeTotal = Get-Scalar $conn "SELECT Sum(SALDO) FROM COMPROVANTES WHERE IdCLIENTE=$clientId AND SALDO<>0"
    $haberTotal = Get-Scalar $conn "SELECT Sum(SALDO) FROM PAGOS WHERE IdCLIENTE='$clientId' AND SALDO<>0"
    $saldoFinal = $debeTotal - $haberTotal

    $debeAntes = Get-Scalar $conn "SELECT Sum(SALDO) FROM COMPROVANTES WHERE IdCLIENTE=$clientId AND SALDO<>0 AND FECHA<$fromLiteral"
    $haberAntes = Get-Scalar $conn "SELECT Sum(SALDO) FROM PAGOS WHERE IdCLIENTE='$clientId' AND SALDO<>0 AND FECHA<$fromLiteral"
    $saldo = $debeAntes - $haberAntes

    $comprobantesSql = @"
SELECT FECHA, TIPO, IdCOMPROVANTE AS Numero, SALDO AS Debe, IdCOMPROVANTE AS IdMov
FROM COMPROVANTES
WHERE IdCLIENTE=$clientId AND FECHA>=$fromLiteral AND SALDO<>0
"@
    $pagosSql = @"
SELECT FECHA, IdPAGO AS Numero, SALDO AS Haber, IdPAGO AS IdMov
FROM PAGOS
WHERE IdCLIENTE='$clientId' AND FECHA>=$fromLiteral AND SALDO<>0
"@
    $movements = @()
    foreach ($row in (Get-Rows ($conn.Execute($comprobantesSql)) 5000)) {
        $movements += [pscustomobject]@{
            FECHA = $row.FECHA
            TIPO = $row.TIPO
            Numero = $row.Numero
            Debe = [decimal]$row.Debe
            Haber = [decimal]0
            IdMov = [int]$row.IdMov
        }
    }
    foreach ($row in (Get-Rows ($conn.Execute($pagosSql)) 5000)) {
        $movements += [pscustomobject]@{
            FECHA = $row.FECHA
            TIPO = "PAGO"
            Numero = $row.Numero
            Debe = [decimal]0
            Haber = [decimal]$row.Haber
            IdMov = [int]$row.IdMov
        }
    }
    $movements = $movements | Sort-Object FECHA, IdMov
    $statement = @()
    foreach ($movement in $movements) {
        $debe = [decimal]$movement.Debe
        $haber = [decimal]$movement.Haber
        $saldo = $saldo + $debe - $haber
        $statement += [pscustomobject]@{
            Fecha = ([datetime]$movement.FECHA).ToString("dd/MM/yyyy")
            Tipo = $movement.TIPO
            Numero = $movement.Numero
            Debe = if ($debe -ne 0) { Format-Money $debe } else { "" }
            Haber = if ($haber -ne 0) { Format-Money $haber } else { "" }
            Saldo = Format-Money $saldo
        }
    }

    Write-Host "Cliente: $($client.'RAZ SOCIAL')"
    Write-Host "IdCLIENTE: $clientId"
    Write-Host "CUIT: $($client.CUIT)"
    Write-Host "Localidad: $($client.LOCALIDAD)"
    Write-Host "Total comprobantes abiertos: $(Format-Money $debeTotal)"
    Write-Host "Total pagos abiertos:        $(Format-Money $haberTotal)"
    Write-Host "Saldo final:                 $(Format-Money $saldoFinal)"
    Write-Host ""

    if ($Desde -gt [datetime]"1900-01-01") {
        Write-Host "Saldo inicial al $($Desde.ToString('dd/MM/yyyy')): $(Format-Money ($debeAntes - $haberAntes))"
    }

    if ($statement.Count -eq 0) {
        Write-Host "No hay movimientos abiertos desde la fecha indicada."
    } else {
        Write-Host "Ultimos $Ultimos movimientos:"
        $statement | Select-Object -Last $Ultimos | Format-Table -AutoSize
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
