param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [string]$NombreArchivo = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$pdfScript = Join-Path $PSScriptRoot "generar_estado_cuenta_pdf.ps1"

function Sql-Text([string]$value) {
    return $value.Replace("'", "''")
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

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    if ($Cliente -match '^\d+$') {
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial FROM CLIENTES WHERE IdCLIENTE=$Cliente"
    } else {
        $q = Sql-Text $Cliente
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial FROM CLIENTES WHERE [RAZ SOCIAL] LIKE '%$q%' ORDER BY [RAZ SOCIAL]"
    }

    $clients = Rows ($conn.Execute($clientSql)) 20
    if ($clients.Count -eq 0) {
        throw "No encontre cliente: $Cliente"
    }
    if ($clients.Count -gt 1) {
        $names = ($clients | ForEach-Object { "$($_.IdCLIENTE): $($_.RazonSocial)" }) -join "; "
        throw "Hay varios clientes. Usa IdCLIENTE: $names"
    }

    $client = $clients[0]
    $id = [int]$client.IdCLIENTE
    $openSql = @"
SELECT Min(FECHA) AS PrimeraFecha
FROM (
    SELECT FECHA FROM COMPROVANTES WHERE IdCLIENTE=$id AND SALDO<>0
    UNION ALL
    SELECT FECHA FROM PAGOS WHERE IdCLIENTE='$id' AND SALDO<>0
)
"@
    $openRows = Rows ($conn.Execute($openSql)) 1
    if ($openRows.Count -eq 0 -or $null -eq $openRows[0].PrimeraFecha) {
        throw "El cliente $($client.RazonSocial) no tiene saldo abierto."
    }

    $desde = [datetime]$openRows[0].PrimeraFecha
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}

Write-Host "Cliente: $($client.RazonSocial)"
Write-Host "Primer movimiento abierto: $($desde.ToString('dd/MM/yyyy'))"

$args = @($Cliente, "-Desde", $desde)
if ($NombreArchivo) {
    $args += @("-NombreArchivo", $NombreArchivo)
}
& powershell -ExecutionPolicy Bypass -File $pdfScript @args
