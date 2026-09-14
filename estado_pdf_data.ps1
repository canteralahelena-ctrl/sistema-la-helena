param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [Parameter(Mandatory = $true)]
    [datetime]$Desde,
    [datetime]$Hasta = [datetime]::MaxValue,
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }

function Sql-Text([string]$value) {
    return $value.Replace("'", "''")
}

function Rows($recordset, [int]$maxRows = 10000) {
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
    if ($rs.EOF -or $null -eq $rs.Fields.Item(0).Value -or $rs.Fields.Item(0).Value -is [System.DBNull]) {
        return 0
    }
    return [decimal]$rs.Fields.Item(0).Value
}

function Date-Literal([datetime]$date) {
    if ($date.TimeOfDay.TotalSeconds -eq 0) {
        return "#{0:MM/dd/yyyy}#" -f $date
    }
    return "#{0:MM/dd/yyyy HH:mm:ss}#" -f $date
}

function Format-Numero([int]$numero) {
    $point = [math]::Floor($numero / 100000000)
    $seq = $numero % 100000000
    return ("{0:0000}-{1:00000000}" -f $point, $seq)
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
        throw "No encontre cliente: $Cliente"
    }
    if ($clients.Count -gt 1) {
        $names = ($clients | ForEach-Object { "$($_.IdCLIENTE): $($_.'RAZ SOCIAL')" }) -join "; "
        throw "Hay varios clientes. Usa IdCLIENTE: $names"
    }

    $client = $clients[0]
    $clientId = [int]$client.IdCLIENTE
    $from = Date-Literal $Desde
    $hasEnd = $Hasta -lt [datetime]::MaxValue
    $endExclusive = if ($hasEnd -and $Hasta.TimeOfDay.TotalSeconds -eq 0) { $Hasta.AddDays(1) } else { $Hasta }
    $to = if ($hasEnd) { Date-Literal $endExclusive } else { "" }
    $endWhere = if ($hasEnd) { " AND FECHA<$to" } else { "" }
    $numeroColumn = "[N$([char]186)]"

    $debeAntes = Scalar $conn "SELECT Sum(SALDO) FROM COMPROVANTES WHERE IdCLIENTE=$clientId AND SALDO<>0 AND FECHA<$from"
    $haberAntes = Scalar $conn "SELECT Sum(SALDO) FROM PAGOS WHERE IdCLIENTE='$clientId' AND SALDO<>0 AND FECHA<$from"
    $saldo = $debeAntes - $haberAntes

    $comprobantesSql = @"
SELECT FECHA, TIPO, $numeroColumn AS Numero, SALDO AS Debe, IdCOMPROVANTE AS IdMov
FROM COMPROVANTES
WHERE IdCLIENTE=$clientId AND FECHA>=$from$endWhere AND SALDO<>0
"@
    $pagosSql = @"
SELECT FECHA, IdPAGO AS Numero, SALDO AS Haber, IdPAGO AS IdMov
FROM PAGOS
WHERE IdCLIENTE='$clientId' AND FECHA>=$from$endWhere AND SALDO<>0
"@

    $movements = @()
    foreach ($row in (Rows ($conn.Execute($comprobantesSql)) 10000)) {
        $movements += [pscustomobject]@{
            Fecha = ([datetime]$row.FECHA)
            Concepto = $row.TIPO
            Numero = [int]$row.Numero
            Debito = [decimal]$row.Debe
            Credito = [decimal]0
            IdMov = [int]$row.IdMov
        }
    }
    foreach ($row in (Rows ($conn.Execute($pagosSql)) 10000)) {
        $movements += [pscustomobject]@{
            Fecha = ([datetime]$row.FECHA)
            Concepto = "PAGO"
            Numero = [int]$row.Numero
            Debito = [decimal]0
            Credito = [decimal]$row.Haber
            IdMov = [int]$row.IdMov
        }
    }

    $statement = @()
    $statement += [pscustomobject]@{
        Fecha = $Desde.ToString("d/M/yyyy")
        Concepto = "SALDO"
        Numero = ""
        Debito = 0
        Credito = [double][Math]::Abs($saldo)
        Saldo = [double]$saldo
    }

    foreach ($m in ($movements | Sort-Object Fecha, IdMov)) {
        $saldo = $saldo + $m.Debito - $m.Credito
        $statement += [pscustomobject]@{
            Fecha = $m.Fecha.ToString("d/M/yyyy")
            Concepto = $m.Concepto
            Numero = Format-Numero $m.Numero
            Debito = [double]$m.Debito
            Credito = [double]$m.Credito
            Saldo = [double]$saldo
        }
    }

    $result = [pscustomobject]@{
        Cliente = [pscustomobject]@{
            IdCLIENTE = $clientId
            RazonSocial = $client.'RAZ SOCIAL'
            CUIT = $client.CUIT
            Localidad = $client.LOCALIDAD
        }
        Desde = $Desde.ToString("d/M/yyyy")
        Hasta = if ($hasEnd) { $Hasta.ToString("d/M/yyyy") } else { "" }
        SaldoAnterior = [double]($debeAntes - $haberAntes)
        SaldoFinal = [double]$saldo
        Movimientos = $statement
    }

    $json = $result | ConvertTo-Json -Depth 5
    if ($OutFile) {
        Set-Content -LiteralPath $OutFile -Value $json -Encoding UTF8
    } else {
        $json
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
