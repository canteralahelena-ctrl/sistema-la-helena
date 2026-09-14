param(
    [string]$FrontEndPassword = "",
    [string]$BackEndPassword = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontEnd = Join-Path $root "CANTERA LA HELENA 2-4-26.accdb"
$backEnd = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"

function Get-AccessConnection($path, $password) {
    $conn = New-Object -ComObject ADODB.Connection
    $connectionString = "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$path;Mode=Read;"
    if ($password) {
        $connectionString += "Jet OLEDB:Database Password=$password;"
    }
    $conn.Open($connectionString)
    return $conn
}

function Read-RecordsetRows($recordset, $maxRows = 200) {
    $rows = @()
    $count = 0
    while (-not $recordset.EOF -and $count -lt $maxRows) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $recordset.Fields.Count; $i++) {
            $row[$recordset.Fields.Item($i).Name] = $recordset.Fields.Item($i).Value
        }
        $rows += [pscustomobject]$row
        $recordset.MoveNext()
        $count++
    }
    return $rows
}

function Inspect-Database($label, $path, $password) {
    Write-Host ""
    Write-Host "== $label =="
    Write-Host $path

    $conn = $null
    try {
        $conn = Get-AccessConnection $path $password
        $tablesRs = $conn.OpenSchema(20)
        $tables = Read-RecordsetRows $tablesRs 1000 |
            Where-Object { $_.TABLE_TYPE -in @("TABLE", "LINK", "VIEW") -and $_.TABLE_NAME -notlike "MSys*" } |
            Sort-Object TABLE_TYPE, TABLE_NAME

        Write-Host "-- Tablas/links/vistas visibles: $($tables.Count)"
        $tables | Select-Object TABLE_TYPE, TABLE_NAME | Format-Table -AutoSize

        $queryRs = $conn.Execute("SELECT Name, Type FROM MSysObjects WHERE Type IN (5) AND Name NOT LIKE '~%' ORDER BY Name")
        $queries = Read-RecordsetRows $queryRs 1000
        Write-Host "-- Consultas guardadas: $($queries.Count)"
        $queries | Select-Object Name | Format-Table -AutoSize
    }
    catch {
        Write-Host "-- Aviso: no se pudo leer alguna metadata: $($_.Exception.Message)"
    }
    finally {
        if ($conn -and $conn.State -eq 1) { $conn.Close() }
    }
}

Inspect-Database "FRONT-END / MASCARA" $frontEnd $FrontEndPassword
Inspect-Database "BACK-END / TABLAS" $backEnd $BackEndPassword
