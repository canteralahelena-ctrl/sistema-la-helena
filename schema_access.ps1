param(
    [Parameter(Mandatory = $true)]
    [string]$Table,
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
    $rs = $conn.OpenSchema(4, @($null, $null, $Table, $null))
    $rows = @()
    while (-not $rs.EOF) {
        $rows += [pscustomobject]@{
            Column = $rs.Fields.Item("COLUMN_NAME").Value
            Type = $rs.Fields.Item("DATA_TYPE").Value
            Size = $rs.Fields.Item("CHARACTER_MAXIMUM_LENGTH").Value
            Nullable = $rs.Fields.Item("IS_NULLABLE").Value
        }
        $rs.MoveNext()
    }
    $rows | Format-Table -AutoSize
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
