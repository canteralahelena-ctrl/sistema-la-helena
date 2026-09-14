param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [datetime]$Desde = "1900-01-01",
    [int]$Top = 10
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }

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

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    if ($Cliente -match '^\d+$') {
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL] FROM CLIENTES WHERE IdCLIENTE=$Cliente"
    } else {
        $q = Sql-Text $Cliente
        $clientSql = "SELECT IdCLIENTE, [RAZ SOCIAL] FROM CLIENTES WHERE [RAZ SOCIAL] LIKE '%$q%' ORDER BY [RAZ SOCIAL]"
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

    $id = [int]$clients[0].IdCLIENTE
    $from = Date-Literal $Desde
    $sql = @"
SELECT TOP $Top
    D.PRODUCTO,
    D.UNIDAD,
    Sum(D.CANTIDAD) AS CantidadTotal,
    Count(*) AS Lineas,
    Sum(D.[Subtot]) AS Subtotal
FROM COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D
    ON C.IdCOMPROVANTE = D.IdCOMPROVANTE
WHERE C.IdCLIENTE=$id
    AND C.FECHA >= $from
    AND D.PRODUCTO Is Not Null
    AND D.PRODUCTO <> ''
GROUP BY D.PRODUCTO, D.UNIDAD
ORDER BY Sum(D.CANTIDAD) DESC
"@

    Write-Host "Cliente: $($clients[0].'RAZ SOCIAL')"
    Write-Host "IdCLIENTE: $id"
    if ($Desde -gt [datetime]"1900-01-01") {
        Write-Host "Desde: $($Desde.ToString('dd/MM/yyyy'))"
    }
    Write-Host ""
    Rows ($conn.Execute($sql)) $Top | Format-Table -AutoSize
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
