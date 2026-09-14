param(
    [string]$Database = "",
    [string]$FacturasRoot = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\FACTURAS_EJEMPLO\02_FACTURACION SOCIEDAD",
    [string]$RemitosRoot = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\37_REMITOS",
    [string]$PdfPrueba = "",
    [string]$AudioConfig = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "access_hardening.ps1")

if (-not $Database) {
    $environmentPath = Join-Path $root "config\environment.json"
    if (Test-Path -LiteralPath $environmentPath) {
        $environment = Get-Content -LiteralPath $environmentPath -Raw | ConvertFrom-Json
        if ($environment.local_database_path) {
            $candidate = [string]$environment.local_database_path
            $Database = if ([IO.Path]::IsPathRooted($candidate)) { $candidate } else { Join-Path $root $candidate }
        }
    }
}
if (-not $Database) { $Database = Join-Path $root "data\test_database\CANTERA_LA_HELENA_TEST.accdb" }
if (-not $AudioConfig) { $AudioConfig = Join-Path $root "telegram_bot_config.json" }

$results = [ordered]@{}
function Set-HealthResult([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:results[$Name] = [pscustomobject]@{ Ok=$Ok; Detalle=(Protect-HelenaDiagnosticText $Detail) }
}

$schema = Get-HelenaAccessSchema $Database
Set-HealthResult "ACCESS" $schema.Ok $schema.Estado

$numeroField = "N$([char]0x00BA)"
$requirements = @(
    [pscustomobject]@{ Module="clientes"; Table="CLIENTES"; Fields=@("IdCLIENTE","RAZ SOCIAL","CUIT","LOCALIDAD") },
    [pscustomobject]@{ Module="ventas"; Table="COMPROVANTES"; Fields=@("IdCOMPROVANTE","TIPO","FECHA",$numeroField,"IdCLIENTE","SUBTOTAL","IVA","IMPORTE","SALDO","UserID") },
    [pscustomobject]@{ Module="ventas"; Table="DETALLE DE COMPROVANTES"; Fields=@("IdCOMPROVANTE","PRODUCTO","CANTIDAD","UNIDAD","PUNITARIO","Subtot") },
    [pscustomobject]@{ Module="iva"; Table="COMPROVANTES DE GASTOS"; Fields=@("IdGASTO","FECHA","TIPO",$numeroField,"IdPROVEEDOR","IVA","IMPORTE","UserID") },
    [pscustomobject]@{ Module="pagos"; Table="PAGOS"; Fields=@("IdPAGO","IdCLIENTE","FECHA","MONTO","SALDO","TIPO","UserID") },
    [pscustomobject]@{ Module="pagos"; Table="DETPAGO"; Fields=@("IdPAGO","IdCOMPROVANTE","IdCLIENTE","IMPORTE") },
    [pscustomobject]@{ Module="cheques"; Table="DETALLE DE ENTREGAS"; Fields=@("IdENTREGA","IdPAGO","IdCLIENTE","TIPO","IMPORTE","FECHA A COBRAR","ESTADO","OBSERVACION") },
    [pscustomobject]@{ Module="auditorias"; Table="PRODUCTOS"; Fields=@("IdPRODUCTO","PRODUCTO","PUNITARIO","UNIDAD") },
    [pscustomobject]@{ Module="auditorias"; Table="MovCajaGeneral"; Fields=@("FECHA","IMPORTE","TIPO","UserID") },
    [pscustomobject]@{ Module="auditorias"; Table="MovCajaChica"; Fields=@("FECHA","IMPORTE","TIPO","UserID") }
)
$knownAliases = @{
    "COMPROVANTES DE GASTOS" = @("COMPROBANTES DE GASTOS", "COMPROVANTES GASTOS", "COMPROBANTES GASTOS")
}
$schemaIssues = if ($schema.Ok) { @(Test-HelenaSchemaRequirements -Tables $schema.Tablas -Requirements $requirements -KnownAliases $knownAliases) } else { @() }
if (-not $schema.Ok) {
    Set-HealthResult "ESQUEMA" $false "BASE_INACCESIBLE"
} elseif ($schemaIssues.Count -gt 0) {
    Set-HealthResult "ESQUEMA" $false (($schemaIssues | ForEach-Object { "$($_.Modulo):$($_.Estado):$($_.Tabla):$($_.Detalle)" }) -join " | ")
} else {
    Set-HealthResult "ESQUEMA" $true "BASE_VALIDA"
}

$facturasAccess = Test-HelenaDocumentRoot "FACTURAS_ROOT" $FacturasRoot
$remitosAccess = Test-HelenaDocumentRoot "REMITOS_ROOT" $RemitosRoot
Set-HealthResult "FACTURAS_ROOT" $facturasAccess.Ok $facturasAccess.Estado
Set-HealthResult "REMITOS_ROOT" $remitosAccess.Ok $remitosAccess.Estado

if (-not $PdfPrueba -and $facturasAccess.Ok) {
    try {
        $PdfPrueba = Get-ChildItem -LiteralPath $FacturasRoot -Filter "*.pdf" -File -Recurse -ErrorAction Stop | Select-Object -First 1 -ExpandProperty FullName
    } catch {
        $PdfPrueba = ""
    }
}
$pdfCheck = if ($PdfPrueba) { Test-HelenaPdfFile $PdfPrueba } elseif (-not $facturasAccess.Ok) {
    [pscustomobject]@{ Estado="RAIZ_INACCESIBLE"; Ok=$false; Detalle="" }
} else {
    [pscustomobject]@{ Estado="PDF_NO_ENCONTRADO"; Ok=$false; Detalle="SIN_PDF_PRUEBA" }
}
Set-HealthResult "PDF_PRUEBA" $pdfCheck.Ok $pdfCheck.Estado

$conn = $null
if ($schema.Ok -and $schemaIssues.Count -eq 0) {
    try {
        $conn = New-Object -ComObject ADODB.Connection
        $conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$Database;Mode=Read;")
        $ivaRow = $conn.Execute("SELECT TOP 1 IVA, IMPORTE, FECHA FROM COMPROVANTES WHERE TIPO<>'RMT' ORDER BY FECHA DESC")
        if (-not $ivaRow.EOF) {
            $null = ConvertTo-HelenaDecimal $ivaRow.Fields.Item("IVA").Value "COMPROVANTES.IVA" "ZERO" "health_iva"
            $null = ConvertTo-HelenaDecimal $ivaRow.Fields.Item("IMPORTE").Value "COMPROVANTES.IMPORTE" "BLOCK" "health_iva"
            $null = ConvertTo-HelenaDate $ivaRow.Fields.Item("FECHA").Value "COMPROVANTES.FECHA" "BLOCK" "health_iva"
        }
        Set-HealthResult "IVA" $true "LECTURA_OK"

        $carteraRow = $conn.Execute("SELECT TOP 1 IdENTREGA, IdCLIENTE, IMPORTE, [FECHA A COBRAR] AS FechaCobro, ESTADO, OBSERVACION FROM [DETALLE DE ENTREGAS] WHERE ESTADO='EN CAJA'")
        if (-not $carteraRow.EOF) {
            $idEntrega = ConvertTo-HelenaInteger $carteraRow.Fields.Item("IdENTREGA").Value "DETALLE DE ENTREGAS.IdENTREGA" "BLOCK" "health_cartera"
            $null = ConvertTo-HelenaDecimal $carteraRow.Fields.Item("IMPORTE").Value "DETALLE DE ENTREGAS.IMPORTE" "BLOCK" "IdENTREGA=$idEntrega"
            $null = ConvertTo-HelenaInteger $carteraRow.Fields.Item("IdCLIENTE").Value "DETALLE DE ENTREGAS.IdCLIENTE" "NULL" "IdENTREGA=$idEntrega"
            $null = ConvertTo-HelenaDate $carteraRow.Fields.Item("FechaCobro").Value "DETALLE DE ENTREGAS.FECHA A COBRAR" "NULL" "IdENTREGA=$idEntrega"
            $null = ConvertTo-HelenaText $carteraRow.Fields.Item("OBSERVACION").Value "DETALLE DE ENTREGAS.OBSERVACION" "EMPTY" "IdENTREGA=$idEntrega"
        }
        Set-HealthResult "CARTERA" $true "LECTURA_OK"
    }
    catch {
        $detail = New-HelenaErrorDetail "health_check" "lectura_access" $_
        if (-not $results.Contains("IVA")) { Set-HealthResult "IVA" $false "$($detail.TipoExcepcion):$($detail.Mensaje)" }
        if (-not $results.Contains("CARTERA")) { Set-HealthResult "CARTERA" $false "$($detail.TipoExcepcion):$($detail.Mensaje)" }
    }
    finally { if ($conn -and $conn.State -eq 1) { $conn.Close() } }
} else {
    Set-HealthResult "IVA" $false "ESQUEMA_NO_VALIDO"
    Set-HealthResult "CARTERA" $false "ESQUEMA_NO_VALIDO"
}

$auditFilesOk = @("auditoria_usuario_3.ps1","auditoria_documentos.ps1","auditoria_anulados.ps1","auditoria_detalles.ps1") |
    ForEach-Object { Test-Path -LiteralPath (Join-Path $root $_) } |
    Where-Object { -not $_ } |
    Measure-Object |
    Select-Object -ExpandProperty Count
$auditDryOk = ($auditFilesOk -eq 0 -and $schema.Ok -and $schemaIssues.Count -eq 0 -and $facturasAccess.Ok -and $remitosAccess.Ok)
Set-HealthResult "AUDITORIA_SECA" $auditDryOk $(if ($auditDryOk) { "PRECONDICIONES_OK_SIN_GENERAR" } else { "PRECONDICIONES_INCOMPLETAS" })

try {
    $audio = Get-Content -LiteralPath $AudioConfig -Raw | ConvertFrom-Json
    $apiConfigured = -not [string]::IsNullOrWhiteSpace([string]$audio.openai_api_key)
    $ffmpeg = [string]$audio.ffmpeg_path
    $ffmpegOk = (-not [string]::IsNullOrWhiteSpace($ffmpeg)) -and ((Test-Path -LiteralPath $ffmpeg -PathType Leaf) -or $null -ne (Get-Command $ffmpeg -ErrorAction SilentlyContinue))
    Set-HealthResult "AUDIO_CONFIG" ($apiConfigured -and $ffmpegOk) $(if (-not $apiConfigured) { "API_KEY_NO_CONFIGURADA" } elseif (-not $ffmpegOk) { "FFMPEG_NO_DISPONIBLE" } else { "CONFIG_OK" })
}
catch {
    Set-HealthResult "AUDIO_CONFIG" $false "CONFIG_INACCESIBLE_O_INVALIDA"
}

foreach ($name in @("ACCESS","ESQUEMA","FACTURAS_ROOT","REMITOS_ROOT","PDF_PRUEBA","IVA","CARTERA","AUDITORIA_SECA","AUDIO_CONFIG")) {
    $result = $results[$name]
    $status = if ($result.Ok) { "OK" } else { "ERROR" }
    Write-Output "${name}: $status - $($result.Detalle)"
}
$allOk = @($results.Values | Where-Object { -not $_.Ok }).Count -eq 0
if ($allOk) {
    Write-Output "HEALTH_OK"
    exit 0
}
Write-Output "HEALTH_ERROR"
exit 1
