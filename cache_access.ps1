param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$cacheDir = if ($env:HELENA_DATA_DIR) { Join-Path $env:HELENA_DATA_DIR "cache" } else { Join-Path $PSScriptRoot "data\cache" }
$cachePath = Join-Path $cacheDir "access_fast_cache.json"

function Rows($recordset, [int]$maxRows = 1000000) {
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

if (-not (Test-Path -LiteralPath $dbPath)) {
    throw "No existe la base local: $dbPath"
}

New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
$dbInfo = Get-Item -LiteralPath $dbPath
$dbStamp = "{0}|{1}" -f $dbInfo.LastWriteTimeUtc.ToString("o"), $dbInfo.Length

if (-not $Force -and (Test-Path -LiteralPath $cachePath)) {
    $old = Get-Content -LiteralPath $cachePath -Raw | ConvertFrom-Json
    if ($old.DbStamp -eq $dbStamp) {
        Write-Host "Cache vigente. No se reconstruye."
        Write-Host $cachePath
        return
    }
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $clientes = Rows ($conn.Execute(@"
SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial, CUIT, LOCALIDAD
FROM CLIENTES
ORDER BY [RAZ SOCIAL]
"@))

    $saldos = Rows ($conn.Execute(@"
SELECT
    C.IdCLIENTE,
    C.[RAZ SOCIAL] AS RazonSocial,
    C.CUIT,
    C.LOCALIDAD,
    IIf(IsNull(D.Debe), 0, D.Debe) AS Debe,
    IIf(IsNull(H.Haber), 0, H.Haber) AS Haber,
    IIf(IsNull(D.Debe), 0, D.Debe) - IIf(IsNull(H.Haber), 0, H.Haber) AS Saldo
FROM
    (CLIENTES AS C
    LEFT JOIN
        (SELECT IdCLIENTE, Sum(SALDO) AS Debe
         FROM COMPROVANTES
         WHERE SALDO<>0
         GROUP BY IdCLIENTE) AS D
    ON C.IdCLIENTE = D.IdCLIENTE)
    LEFT JOIN
        (SELECT IdCLIENTE AS ClienteId, Sum(SALDO) AS Haber
         FROM PAGOS
         WHERE SALDO<>0
         GROUP BY IdCLIENTE) AS H
    ON CStr(C.IdCLIENTE) = H.ClienteId
ORDER BY C.[RAZ SOCIAL]
"@))

    $pagos = Rows ($conn.Execute(@"
SELECT IdPAGO, FECHA, IdCLIENTE, MONTO, TIPO, SALDO
FROM PAGOS
ORDER BY IdCLIENTE, FECHA DESC, IdPAGO DESC
"@))

    $materiales = Rows ($conn.Execute(@"
SELECT
    C.IdCLIENTE,
    D.PRODUCTO,
    D.UNIDAD,
    Sum(D.CANTIDAD) AS CantidadTotal,
    Count(*) AS Lineas,
    Sum(D.[Subtot]) AS Subtotal
FROM COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D
    ON C.IdCOMPROVANTE = D.IdCOMPROVANTE
WHERE D.PRODUCTO Is Not Null
    AND D.PRODUCTO <> ''
GROUP BY C.IdCLIENTE, D.PRODUCTO, D.UNIDAD
ORDER BY C.IdCLIENTE, Sum(D.CANTIDAD) DESC
"@))

    $ultimosPagos = @{}
    foreach ($p in $pagos) {
        $key = [string]$p.IdCLIENTE
        if (-not $ultimosPagos.ContainsKey($key)) {
            $ultimosPagos[$key] = [pscustomobject]@{
                IdPAGO = $p.IdPAGO
                Fecha = if ($p.FECHA) { ([datetime]$p.FECHA).ToString("yyyy-MM-dd HH:mm:ss") } else { "" }
                Monto = $p.MONTO
                Tipo = $p.TIPO
                Saldo = $p.SALDO
            }
        }
    }

    $ultimosPagosRows = @(
        $ultimosPagos.GetEnumerator() |
            Sort-Object Name |
            ForEach-Object {
                [pscustomobject]@{
                    IdCLIENTE = $_.Name
                    IdPAGO = $_.Value.IdPAGO
                    Fecha = $_.Value.Fecha
                    Monto = $_.Value.Monto
                    Tipo = $_.Value.Tipo
                    Saldo = $_.Value.Saldo
                }
            }
    )

    $data = [pscustomobject]@{
        Creado = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        DbPath = $dbPath
        DbStamp = $dbStamp
        DbFecha = $dbInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        DbTamano = $dbInfo.Length
        Clientes = $clientes
        Saldos = $saldos
        UltimosPagos = $ultimosPagosRows
        Materiales = $materiales
    }

    $data | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $cachePath -Encoding UTF8
    Write-Host "Cache reconstruido: $cachePath"
    Write-Host "Clientes: $($clientes.Count) | Saldos: $($saldos.Count) | Materiales: $($materiales.Count)"
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
