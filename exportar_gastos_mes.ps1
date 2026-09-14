param(
    [Parameter(Mandatory = $true)]
    [int]$Anio,
    [Parameter(Mandatory = $true)]
    [int]$Mes
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Rows($recordset, [int]$maxRows = 100000) {
    $rows = @()
    while (-not $recordset.EOF -and $rows.Count -lt $maxRows) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $recordset.Fields.Count; $i++) {
            $name = $recordset.Fields.Item($i).Name
            $value = $recordset.Fields.Item($i).Value
            if ($null -ne $value -and $name -eq "FECHA") {
                $value = ([datetime]$value).ToString("yyyy-MM-dd")
            }
            $row[$name] = $value
        }
        $rows += [pscustomobject]$row
        $recordset.MoveNext()
    }
    return $rows
}

$desde = [datetime]::new($Anio, $Mes, 1)
$hasta = $desde.AddMonths(1)
$from = Date-Literal $desde
$to = Date-Literal $hasta
$numeroColumn = "[N" + [char]186 + "]"

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $sql = @"
SELECT G.IdGASTO, G.FECHA, G.TIPO, G.$numeroColumn AS Numero, G.IdPROVEEDOR,
       P.PROVEEDOR, G.IVA, G.IMPORTE, G.SALDO, G.UserID
FROM [COMPROVANTES DE GASTOS] AS G
LEFT JOIN PROVEEDORES AS P ON G.IdPROVEEDOR=P.IdPROVEEDOR
WHERE G.FECHA >= $from
  AND G.FECHA < $to
ORDER BY G.FECHA, G.TIPO, G.$numeroColumn
"@
    Rows ($conn.Execute($sql)) | ConvertTo-Json -Depth 4
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
