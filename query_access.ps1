param(
    [Parameter(Mandatory = $true)]
    [string]$Sql,
    [string]$Database = "backend",
    [string]$Password = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($Database -eq "frontend") {
    Join-Path $root "CANTERA LA HELENA 2-4-26.accdb"
} else {
    Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"
}

$conn = New-Object -ComObject ADODB.Connection
$connectionString = "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;"
if ($Password) {
    $connectionString += "Jet OLEDB:Database Password=$Password;"
}

$conn.Open($connectionString)
try {
    $rs = $conn.Execute($Sql)
    if (-not $rs) {
        Write-Host "Consulta ejecutada sin filas."
        return
    }

    $rows = @()
    while (-not $rs.EOF -and $rows.Count -lt 200) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $rs.Fields.Count; $i++) {
            $row[$rs.Fields.Item($i).Name] = $rs.Fields.Item($i).Value
        }
        $rows += [pscustomobject]$row
        $rs.MoveNext()
    }

    if ($rows.Count -eq 0) {
        Write-Host "Sin resultados."
    } else {
        $rows | Format-Table -AutoSize
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
