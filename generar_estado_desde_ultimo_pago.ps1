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
    $lastSql = @"
SELECT TOP 1 IdPAGO, FECHA, MONTO, TIPO
FROM PAGOS
WHERE IdCLIENTE='$id'
ORDER BY FECHA DESC, IdPAGO DESC
"@
    $payments = Rows ($conn.Execute($lastSql)) 1
    if ($payments.Count -eq 0) {
        throw "El cliente $($client.RazonSocial) no tiene pagos registrados."
    }

    $last = $payments[0]
    $desde = [datetime]$last.FECHA
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}

Write-Host "Cliente: $($client.RazonSocial)"
Write-Host "Ultimo pago: $(([datetime]$last.FECHA).ToString('dd/MM/yyyy HH:mm:ss')) - IdPago $($last.IdPAGO) - $($last.TIPO)"
Write-Host "Generando estado desde: $($desde.ToString('dd/MM/yyyy HH:mm:ss'))"

$args = @($Cliente, "-Desde", $desde)
if ($NombreArchivo) {
    $args += @("-NombreArchivo", $NombreArchivo)
}
& powershell -ExecutionPolicy Bypass -File $pdfScript @args
