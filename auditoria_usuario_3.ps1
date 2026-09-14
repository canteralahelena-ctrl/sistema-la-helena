param(
    [datetime]$Desde = "2026-06-01",
    [datetime]$Hasta = "2026-06-06",
    [int]$UsuarioId = 3,
    [string]$UsuarioNombre = "",
    [string]$PdfBaseRoot = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\FACTURAS_EJEMPLO\02_FACTURACION SOCIEDAD",
    [string]$PdfRoot = "",
    [string]$OutMarkdown = "",
    [string]$OutHtml = "",
    [string]$OutCsv = "",
    [string]$OutPagosCsv = "",
    [string]$OutEntregasCsv = "",
    [string]$OutNotasCreditoCsv = "",
    [string]$RemitosRoot = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\37_REMITOS"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$outputsDir = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pdfReader = Join-Path $PSScriptRoot "leer_total_pdf.py"
$hardeningHelper = Join-Path $PSScriptRoot "access_hardening.ps1"
. $hardeningHelper
$anuladosHelper = Join-Path $PSScriptRoot "auditoria_anulados.ps1"
. $anuladosHelper
$precioVentaHelper = Join-Path $PSScriptRoot "auditoria_precio_venta.ps1"
. $precioVentaHelper
$detallesHelper = Join-Path $PSScriptRoot "auditoria_detalles.ps1"
. $detallesHelper
$documentosHelper = Join-Path $PSScriptRoot "auditoria_documentos.ps1"
. $documentosHelper
$cacheDir = Join-Path $PSScriptRoot "data\cache"
$pdfTotalCachePath = Join-Path $cacheDir "pdf_totales_cache.json"
$auditUserId = [int]$UsuarioId
if (-not $UsuarioNombre) {
    $UsuarioNombre = switch ($auditUserId) {
        1 { "Gaston" }
        2 { "Hugo" }
        3 { "Maxi" }
        default { "" }
    }
}
$auditUserLabel = if ($UsuarioNombre) { "Usuario $auditUserId / $UsuarioNombre" } else { "Usuario $auditUserId" }
$auditUserFileName = if ($UsuarioNombre) { $UsuarioNombre.ToLowerInvariant() -replace '[^a-z0-9]+', '_' } else { "" }
$auditFilePrefix = if ($auditUserFileName) { "auditoria_usuario_{0}_{1}" -f $auditUserId, $auditUserFileName.Trim("_") } else { "auditoria_usuario_$auditUserId" }
if (-not $OutMarkdown) {
    $OutMarkdown = Join-Path $outputsDir ("{0}_{1}_{2}.md" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}
if (-not $OutCsv) {
    $OutCsv = Join-Path $outputsDir ("{0}_comprobantes_{1}_{2}.csv" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}
if (-not $OutHtml) {
    $OutHtml = Join-Path $outputsDir ("{0}_{1}_{2}.html" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}
if (-not $OutPagosCsv) {
    $OutPagosCsv = Join-Path $outputsDir ("{0}_pagos_{1}_{2}.csv" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}
if (-not $OutEntregasCsv) {
    $OutEntregasCsv = Join-Path $outputsDir ("{0}_entregas_{1}_{2}.csv" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}
if (-not $OutNotasCreditoCsv) {
    $OutNotasCreditoCsv = Join-Path $outputsDir ("{0}_notas_credito_{1}_{2}.csv" -f $auditFilePrefix, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
}

function Get-YearPdfRoots([datetime]$from, [datetime]$to, [string]$baseRoot, [string]$explicitRoot) {
    if ($explicitRoot) {
        return @($explicitRoot)
    }
    $endInclusive = $to.AddDays(-1)
    if ($endInclusive -lt $from) {
        $endInclusive = $from
    }
    $roots = @()
    for ($year = $from.Year; $year -le $endInclusive.Year; $year++) {
        $roots += (Join-Path $baseRoot ([string]$year))
    }
    return $roots
}

$PdfRoots = Get-YearPdfRoots $Desde $Hasta $PdfBaseRoot $PdfRoot
$facturasRootToCheck = if ($PdfRoot) { $PdfRoot } else { $PdfBaseRoot }
$documentRoots = @(Test-HelenaDocumentRoot "FACTURAS" $facturasRootToCheck)
$documentRoots += Test-HelenaDocumentRoot "REMITOS" $RemitosRoot
$inaccessibleRoots = @($documentRoots | Where-Object { -not $_.Ok })
if ($inaccessibleRoots.Count -gt 0) {
    $detail = ($inaccessibleRoots | ForEach-Object { "$($_.Nombre):$($_.Estado)" }) -join " | "
    throw "RAIZ_INACCESIBLE modulo=auditorias operacion=precheck_documental detalle=$detail"
}
$outputParents = @($OutMarkdown, $OutHtml, $OutCsv, $OutPagosCsv, $OutEntregasCsv, $OutNotasCreditoCsv) |
    ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique
New-Item -ItemType Directory -Force -Path $outputParents | Out-Null
$IconOk = [char]::ConvertFromUtf32(0x2705)
$IconWarning = [char]::ConvertFromUtf32(0x26A0) + [char]::ConvertFromUtf32(0xFE0F)
$IconInfo = [char]::ConvertFromUtf32(0x2139) + [char]::ConvertFromUtf32(0xFE0F)

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Rows($recordset, [int]$maxRows = 100000) {
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

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function NzDecimal($value, [string]$field = "IVA", [string]$nullPolicy = "ZERO", [string]$context = "auditoria") {
    return ConvertTo-HelenaDecimal -Value $value -Field $field -NullPolicy $nullPolicy -Context $context
}

function Parse-Decimal($value) {
    if ($null -eq $value -or $value -eq "" -or $value -is [System.DBNull]) { return $null }
    if ($value -is [decimal] -or $value -is [double] -or $value -is [float] -or $value -is [int] -or $value -is [long]) {
        return [decimal]$value
    }
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    $text = [string]$value
    $parsed = 0
    if ([decimal]::TryParse($text, [System.Globalization.NumberStyles]::Any, $culture, [ref]$parsed)) {
        return [decimal]$parsed
    }
    if ([decimal]::TryParse($text, [System.Globalization.NumberStyles]::Any, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return [decimal]$parsed
    }
    return $null
}

function Split-AccessNumber([int]$number) {
    $point = [math]::Floor($number / 100000000)
    $seq = $number % 100000000
    return [pscustomobject]@{ Point = [int]$point; Seq = [int]$seq }
}

function Format-AccessNumber([int]$number) {
    $n = Split-AccessNumber $number
    return "{0:00000}-{1:00000000}" -f $n.Point, $n.Seq
}

function Is-NotaCredito([string]$tipo) {
    $t = ([string]$tipo).Trim().ToUpperInvariant()
    return ($t -match '^NC' -or $t -match '^NCS' -or $t -like 'NOTA*CREDITO*')
}

function Get-ComprobanteLetter([string]$tipo) {
    $t = ([string]$tipo).Trim().ToUpperInvariant()
    if ($t -match '\bB\b' -or $t -like '* B') { return "B" }
    if ($t -match '\bA\b' -or $t -like '* A') { return "A" }
    return ""
}

function Normalize-Cuit([object]$value) {
    return ([string]$value) -replace '\D', ''
}

function Get-PdfCandidates([string]$tipo, [int]$number) {
    $t = $tipo.Trim().ToUpperInvariant()
    $n = Split-AccessNumber $number
    $point5 = "{0:00000}" -f $n.Point
    $point4 = "{0:0000}" -f $n.Point
    $seq8 = "{0:00000000}" -f $n.Seq
    $seq9 = "{0:000000000}" -f $n.Seq
    $seq6 = "{0:000000}" -f $n.Seq

    $candidates = @()
    if ($t -in @("FTS A", "FT A")) {
        $candidates += [pscustomobject]@{ Folder = "FT A"; Name = "FTA{0}_{1}.pdf" -f $point5, $seq8 }
    }
    elseif ($t -in @("FTS B", "FT B")) {
        $candidates += [pscustomobject]@{ Folder = "FT B"; Name = "FTB{0}_{1}.pdf" -f $point5, $seq8 }
    }
    elseif ($t -eq "FP A") {
        $candidates += [pscustomobject]@{ Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point4, $seq9 }
        $candidates += [pscustomobject]@{ Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -eq "FP B") {
        $candidates += [pscustomobject]@{ Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point4, $seq9 }
        $candidates += [pscustomobject]@{ Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("NCS A", "NC A")) {
        $candidates += [pscustomobject]@{ Folder = "NC A"; Name = "NC A {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "NC A"; Name = "NC A {0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("NCS B", "NC B")) {
        $candidates += [pscustomobject]@{ Folder = "NC B"; Name = "NC B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "NC B"; Name = "NC B {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "NC B"; Name = "NC B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("ND A")) {
        $candidates += [pscustomobject]@{ Folder = "ND A"; Name = "ND A {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "ND A"; Name = "ND A {0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("ND B")) {
        $candidates += [pscustomobject]@{ Folder = "ND B"; Name = "ND B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Folder = "ND B"; Name = "ND B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    return $candidates
}

function Find-Pdf([string]$tipo, [int]$number) {
    $candidates = Get-PdfCandidates $tipo $number
    foreach ($pdfRootItem in $PdfRoots) {
        $yearName = [IO.Path]::GetFileName($pdfRootItem)
        foreach ($candidate in $candidates) {
            $path = Join-Path (Join-Path $pdfRootItem $candidate.Folder) $candidate.Name
            try {
                if (Test-Path -LiteralPath $path) {
                    return [pscustomobject]@{ Estado = "ENCONTRADO"; Path = $path; Candidato = $candidate.Name; Carpeta = "$yearName\$($candidate.Folder)" }
                }
            }
            catch {
                return [pscustomobject]@{ Estado = "NO_LEIDO"; Path = $path; Candidato = $candidate.Name; Carpeta = "$yearName\$($candidate.Folder)" }
            }
        }
    }
    if ($candidates.Count -eq 0) {
        return [pscustomobject]@{ Estado = "NO_APLICA"; Path = ""; Candidato = ""; Carpeta = "" }
    }
    return [pscustomobject]@{
        Estado = "FALTANTE"
        Path = ""
        Candidato = ($PdfRoots | ForEach-Object {
            $yearName = [IO.Path]::GetFileName($_)
            foreach ($candidate in $candidates) {
                "$yearName\$($candidate.Folder)\$($candidate.Name)"
            }
        }) -join " | "
        Carpeta = ""
    }
}

function Read-PdfTotal([string]$path, [bool]$NeedRaw = $false) {
    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{ Ok = $false; Total = $null; Raw = ""; Matched = ""; Error = "PDF no existe" }
    }
    $info = Get-Item -LiteralPath $path
    $stamp = "{0}|{1}" -f $info.LastWriteTimeUtc.ToString("o"), $info.Length
    if ($script:pdfTotalCache.ContainsKey($path)) {
        $cached = $script:pdfTotalCache[$path]
        $cachedHasRaw = $cached.PSObject.Properties.Name -contains "Raw"
        if ($cached.Stamp -eq $stamp -and (-not $NeedRaw -or $cachedHasRaw)) {
            return [pscustomobject]@{
                Ok = [bool]$cached.Ok
                Total = $cached.Total
                Raw = if ($cachedHasRaw) { [string]$cached.Raw } else { "" }
                Matched = if ($cached.PSObject.Properties.Name -contains "Matched") { [string]$cached.Matched } else { "" }
                Error = $cached.Error
            }
        }
    }
    try {
        $json = & $python $pdfReader $path
        $data = $json | ConvertFrom-Json
        $result = [pscustomobject]@{
            Ok = [bool]$data.ok
            Total = $data.total
            Raw = [string]$data.raw
            Matched = [string]$data.matched
            Error = $data.error
        }
        $script:pdfTotalCache[$path] = [pscustomobject]@{
            Path = $path
            Stamp = $stamp
            Ok = $result.Ok
            Total = $result.Total
            Raw = $result.Raw
            Matched = $result.Matched
            Error = $result.Error
            Leido = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        }
        return $result
    }
    catch {
        $result = [pscustomobject]@{ Ok = $false; Total = $null; Raw = ""; Matched = ""; Error = $_.Exception.Message }
        $script:pdfTotalCache[$path] = [pscustomobject]@{
            Path = $path
            Stamp = $stamp
            Ok = $result.Ok
            Total = $result.Total
            Raw = $result.Raw
            Matched = $result.Matched
            Error = $result.Error
            Leido = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        }
        return $result
    }
}

function Parse-NcPdfReference([string]$text) {
    return Get-AuditNcPdfReference $text
}

function Find-ReferencedDocument([object]$reference, [hashtable]$docsByNumber) {
    if (-not $reference -or -not $reference.Found) { return $null }
    $key = [string]$reference.NumeroAccess
    if (-not $docsByNumber.ContainsKey($key)) { return $null }
    return Find-AuditReferencedComprobante -Reference $reference -Documentos @($docsByNumber[$key])
}

function Test-SameClientOrCuit([object]$nc, [object]$referenced) {
    if (-not $referenced) { return $false }
    $ncCuit = Normalize-Cuit $nc.CUIT
    $refCuit = Normalize-Cuit $referenced.CUIT
    if ($ncCuit -and $refCuit) { return $ncCuit -eq $refCuit }
    return ([string]$nc.IdCLIENTE) -eq ([string]$referenced.IdCLIENTE)
}

function Get-NcIvaCheck([object]$nc, [object]$referenced) {
    if (-not $referenced) {
        return [pscustomobject]@{ Estado = "NO_VERIFICABLE"; TipoAjuste = "SIN_COMPROBANTE"; Mensaje = "No se puede verificar IVA sin comprobante referenciado." }
    }
    $ncIva = [math]::Abs([double](NzDecimal $nc.IVA))
    $refIva = [math]::Abs([double](NzDecimal $referenced.IVA))
    $ncImporte = [math]::Abs([double](NzDecimal $nc.IMPORTE "COMPROVANTES.IMPORTE" "BLOCK" "nota_credito"))
    $refImporte = [math]::Abs([double](NzDecimal $referenced.IMPORTE "COMPROVANTES.IMPORTE" "BLOCK" "comprobante_referenciado"))
    $tolerance = 1.5

    if ($refIva -le $tolerance) {
        if ($ncIva -le $tolerance) {
            return [pscustomobject]@{ Estado = "OK"; TipoAjuste = "SIN_IVA_COMPARABLE"; Mensaje = "IVA sin monto comparable en el comprobante referenciado." }
        }
        return [pscustomobject]@{ Estado = "REVISAR"; TipoAjuste = "SIN_IVA_COMPARABLE"; Mensaje = "El comprobante referenciado no tiene IVA comparable y la NC si informa IVA." }
    }

    if ($ncIva -gt ($refIva + $tolerance)) {
        return [pscustomobject]@{ Estado = "REVISAR"; TipoAjuste = "IVA_SUPERA_ORIGINAL"; Mensaje = "El IVA de la NC supera el IVA del comprobante referenciado." }
    }

    if ([math]::Abs($ncIva - $refIva) -le $tolerance -and [math]::Abs($ncImporte - $refImporte) -le $tolerance) {
        return [pscustomobject]@{ Estado = "OK"; TipoAjuste = "ANULACION_TOTAL"; Mensaje = "Anulacion total aparente." }
    }

    return [pscustomobject]@{ Estado = "OK"; TipoAjuste = "AJUSTE_PARCIAL"; Mensaje = "Ajuste parcial. Revisar correspondencia entre importe e IVA." }
}

function Normalize-MedioPago([string]$tipo) {
    if (-not $tipo) { return "SIN_DETALLE" }
    $t = $tipo.Trim().ToUpperInvariant()
    if ($t -like "CHE*") { return "CHEQUE" }
    if ($t -like "ECH*") { return "ECHEQ" }
    if ($t -like "TRA*" -or $t -like "TRF*" -or $t -like "TRANS*") { return "TRANSFERENCIA" }
    if ($t -like "EFE*") { return "EFECTIVO" }
    if ($t -like "RET*") { return "RETENCION" }
    if ($t -like "FLE*") { return "FLETE" }
    if ($t -like "MAT*" -or $t -like "LAD*" -or $t -like "PAL*") { return "MATERIALES" }
    return "PAGOS_VARIOS"
}

New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
$script:pdfTotalCache = @{}
if (Test-Path -LiteralPath $pdfTotalCachePath) {
    try {
        $rawPdfCache = Get-Content -LiteralPath $pdfTotalCachePath -Raw | ConvertFrom-Json
        foreach ($entry in @($rawPdfCache.Entries)) {
            if ($entry.Path) {
                $script:pdfTotalCache[[string]$entry.Path] = $entry
            }
        }
    }
    catch {
        $script:pdfTotalCache = @{}
    }
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $from = Date-Literal $Desde
    $to = Date-Literal $Hasta
    $numeroColumn = "[N$([char]186)]"
    $comprobantesSql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, CL.CUIT, C.SUBTOTAL, C.IVA, C.IMPORTE, C.SALDO, C.UserID
FROM COMPROVANTES AS C
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.UserID=$auditUserId
  AND C.FECHA >= $from
  AND C.FECHA < $to
ORDER BY C.FECHA, C.TIPO, C.$numeroColumn
"@
    $comprobantes = Rows ($conn.Execute($comprobantesSql))

    $todosComprobantesSql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, CL.CUIT, C.SUBTOTAL, C.IVA, C.IMPORTE, C.SALDO, C.UserID
FROM COMPROVANTES AS C
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.TIPO <> 'RMT'
ORDER BY C.FECHA, C.TIPO, C.$numeroColumn
"@
    $todosComprobantes = Rows ($conn.Execute($todosComprobantesSql))
    $comprobantesPorNumero = @{}
    foreach ($doc in $todosComprobantes) {
        if ($null -eq $doc.Numero -or $doc.Numero -is [System.DBNull] -or $doc.Numero -eq "") {
            continue
        }
        $docKey = [string]([int]$doc.Numero)
        if (-not $comprobantesPorNumero.ContainsKey($docKey)) {
            $comprobantesPorNumero[$docKey] = @()
        }
        $comprobantesPorNumero[$docKey] = @($comprobantesPorNumero[$docKey]) + @($doc)
    }

    $todosEncabezadosDetalleSql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.$numeroColumn AS Numero, C.FECHA, C.IdCLIENTE, C.UserID
FROM COMPROVANTES AS C
WHERE C.TIPO Is Not Null AND C.$numeroColumn Is Not Null
"@
    $todosEncabezadosDetalle = Rows ($conn.Execute($todosEncabezadosDetalleSql))

    $detalleSql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente,
       D.IdDET, D.IdCOMPROVANTE AS IdCOMPROVANTE_DETALLE, D.PRODUCTO, D.UNIDAD, D.CANTIDAD, D.PUNITARIO, D.[Subtot] AS Subtotal
FROM (COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D ON C.IdCOMPROVANTE = D.IdCOMPROVANTE)
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.UserID=$auditUserId
  AND C.FECHA >= $from
  AND C.FECHA < $to
ORDER BY C.FECHA, C.$numeroColumn, D.IdDET
"@
    $detallesEstructurados = Rows ($conn.Execute($detalleSql))
    $detallesEstructuradosCount = @{}
    foreach ($detalle in $detallesEstructurados) {
        $detalleKey = [string]([int]$detalle.IdCOMPROVANTE)
        $detallesEstructuradosCount[$detalleKey] = 1 + [int]$detallesEstructuradosCount[$detalleKey]
    }

    $detalleLegacyCandidatosSql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente,
       D.IdDET, D.IdCOMPROVANTE AS IdCOMPROVANTE_DETALLE, D.PRODUCTO, D.UNIDAD, D.CANTIDAD, D.PUNITARIO, D.[Subtot] AS Subtotal
FROM (COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D ON C.TIPO = D.TIPO AND C.$numeroColumn = D.$numeroColumn)
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.UserID=$auditUserId
  AND C.FECHA >= $from
  AND C.FECHA < $to
  AND (D.IdCOMPROVANTE Is Null OR D.IdCOMPROVANTE <> C.IdCOMPROVANTE)
ORDER BY C.FECHA, C.$numeroColumn, D.IdDET
"@
    $detallesLegacyCandidatos = Rows ($conn.Execute($detalleLegacyCandidatosSql))
    $detallesLegacyCount = @{}
    foreach ($detalle in $detallesLegacyCandidatos) {
        $detalleKey = [string]([int]$detalle.IdCOMPROVANTE)
        $detallesLegacyCount[$detalleKey] = 1 + [int]$detallesLegacyCount[$detalleKey]
    }
    $detalleResolucion = Resolve-ComprobanteDetalle -Comprobantes $comprobantes -DetallesEstructurados $detallesEstructurados -DetallesLegacyCandidatos $detallesLegacyCandidatos -TodosEncabezados $todosEncabezadosDetalle
    $detalles = @($detalleResolucion.Detalles)
    $detalleResoluciones = $detalleResolucion.Resoluciones
    $detallesPorComprobante = @{}
    foreach ($detalle in $detalles) {
        $detalleKey = [string]([int]$detalle.IdCOMPROVANTE)
        if (-not $detallesPorComprobante.ContainsKey($detalleKey)) {
            $detallesPorComprobante[$detalleKey] = @()
        }
        $detallesPorComprobante[$detalleKey] = @($detallesPorComprobante[$detalleKey]) + @($detalle)
    }
    $comprobantesAnulados = Get-AuditComprobantesAnulados `
        -DetallesPorComprobante $detallesPorComprobante `
        -DetallesLegacyCandidatos $detallesLegacyCandidatos `
        -TodosEncabezados $todosEncabezadosDetalle

    $aplicacionesNc = @()
    try {
        $aplicacionesNcSql = @"
SELECT A.IdAplicacionNC, A.IdFactura, A.IdNotaCredito, A.ImporteAplicado, A.FechaAplicacion,
       NC.TIPO AS TipoNC, NC.[N$([char]186)] AS NumeroNC, NC.FECHA AS FechaNC, NC.IMPORTE AS ImporteNC,
       F.TIPO AS TipoFactura, F.[N$([char]186)] AS NumeroFactura
FROM (T_GAS_NotasCreditoAplicaciones AS A
INNER JOIN COMPROVANTES AS NC ON A.IdNotaCredito = NC.IdCOMPROVANTE)
INNER JOIN COMPROVANTES AS F ON A.IdFactura = F.IdCOMPROVANTE
"@
        $aplicacionesNc = Rows ($conn.Execute($aplicacionesNcSql))
    }
    catch {
        $aplicacionesNc = @()
    }

    $productos = Rows ($conn.Execute("SELECT IdPRODUCTO, PRODUCTO, PUNITARIO, UNIDAD FROM PRODUCTOS"))
    $preciosBase = @{}
    foreach ($p in $productos) {
        if ($p.PRODUCTO -and -not $preciosBase.ContainsKey([string]$p.PRODUCTO)) {
            $preciosBase[[string]$p.PRODUCTO] = [pscustomobject]@{
                PUNITARIO = $p.PUNITARIO
                UNIDAD = $p.UNIDAD
            }
        }
    }

    $pagosSql = @"
SELECT P.IdPAGO, P.FECHA, P.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, P.MONTO, P.SALDO, P.TIPO, P.UserID
FROM PAGOS AS P
LEFT JOIN CLIENTES AS CL ON Val(P.IdCLIENTE) = CL.IdCLIENTE
WHERE P.UserID=$auditUserId
  AND P.FECHA >= $from
  AND P.FECHA < $to
ORDER BY P.FECHA, P.IdPAGO
"@
    $pagos = Rows ($conn.Execute($pagosSql))

    $detPagosSql = @"
SELECT DP.IdDETPAGO, DP.IdPAGO, DP.FECHA, DP.[N$([char]186)] AS Numero, DP.IMPORTE, DP.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente,
       DP.TIPO, DP.IdCOMPROVANTE, DP.UserID
FROM DETPAGO AS DP
LEFT JOIN CLIENTES AS CL ON DP.IdCLIENTE = CL.IdCLIENTE
WHERE DP.IdPAGO In (
    SELECT IdPAGO FROM PAGOS
    WHERE UserID=$auditUserId AND FECHA >= $from AND FECHA < $to
)
ORDER BY DP.IdPAGO, DP.IdDETPAGO
"@
    $detPagos = Rows ($conn.Execute($detPagosSql))

    $detPagoPorPago = @{}
    foreach ($dp in $detPagos) {
        $key = [int]$dp.IdPAGO
        if (-not $detPagoPorPago.ContainsKey($key)) {
            $detPagoPorPago[$key] = @()
        }
        $detPagoPorPago[$key] = @($detPagoPorPago[$key]) + @($dp)
    }

    $entregasSql = @"
SELECT E.IdENTREGA, E.IdPAGO, P.FECHA, P.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, P.MONTO AS MontoPago,
       P.TIPO AS TipoPagoSistema, E.TIPO AS MedioPagoOriginal, E.BANCO, E.NUMERO, E.[FECHA A COBRAR] AS FechaACobrar,
       E.IMPORTE, E.ESTADO, E.[DEPOSITADO EN] AS DepositadoEn, E.UserID
FROM ([DETALLE DE ENTREGAS] AS E
INNER JOIN PAGOS AS P ON E.IdPAGO = P.IdPAGO)
LEFT JOIN CLIENTES AS CL ON Val(P.IdCLIENTE) = CL.IdCLIENTE
WHERE P.UserID=$auditUserId
  AND P.FECHA >= $from
  AND P.FECHA < $to
ORDER BY P.FECHA, P.IdPAGO, E.IdENTREGA
"@
    $entregas = Rows ($conn.Execute($entregasSql))
    $entregaRows = @()
    $entregasPorPago = @{}
    foreach ($e in $entregas) {
        $medio = Normalize-MedioPago ([string]$e.MedioPagoOriginal)
        $idEntrega = ConvertTo-HelenaInteger $e.IdENTREGA "DETALLE DE ENTREGAS.IdENTREGA" "BLOCK" "auditoria"
        $idPagoEntrega = ConvertTo-HelenaInteger $e.IdPAGO "DETALLE DE ENTREGAS.IdPAGO" "BLOCK" "IdENTREGA=$idEntrega"
        $importeEntrega = ConvertTo-HelenaDecimal $e.IMPORTE "DETALLE DE ENTREGAS.IMPORTE" "BLOCK" "IdENTREGA=$idEntrega"
        $fechaEntrega = ConvertTo-HelenaDate $e.FECHA "PAGOS.FECHA" "BLOCK" "IdPAGO=$idPagoEntrega"
        $fechaCobro = ConvertTo-HelenaDate $e.FechaACobrar "DETALLE DE ENTREGAS.FECHA A COBRAR" "NULL" "IdENTREGA=$idEntrega"
        $rowEntrega = [pscustomobject]@{
            Fecha = $fechaEntrega.ToString("dd/MM/yyyy HH:mm:ss")
            IdPAGO = $idPagoEntrega
            IdENTREGA = $idEntrega
            Cliente = $e.Cliente
            TipoPagoSistema = $e.TipoPagoSistema
            MedioPago = $medio
            MedioPagoOriginal = $e.MedioPagoOriginal
            Banco = $e.BANCO
            Numero = $e.NUMERO
            FechaACobrar = if ($fechaCobro) { $fechaCobro.ToString("dd/MM/yyyy") } else { "" }
            Importe = $importeEntrega
            Estado = $e.ESTADO
            DepositadoEn = $e.DepositadoEn
            UserID = $e.UserID
        }
        $entregaRows += $rowEntrega
        if (-not $entregasPorPago.ContainsKey($idPagoEntrega)) {
            $entregasPorPago[$idPagoEntrega] = @()
        }
        $entregasPorPago[$idPagoEntrega] = @($entregasPorPago[$idPagoEntrega]) + @($rowEntrega)
    }

    $pagoRows = @()
    foreach ($p in $pagos) {
        $idPago = ConvertTo-HelenaInteger $p.IdPAGO "PAGOS.IdPAGO" "BLOCK" "auditoria"
        [array]$detalle = if ($detPagoPorPago.ContainsKey($idPago)) { @($detPagoPorPago[$idPago]) } else { @() }
        $imputado = [decimal]0
        foreach ($dpp in $detalle) {
            $imputado += ConvertTo-HelenaDecimal $dpp.IMPORTE "DETPAGO.IMPORTE" "BLOCK" "IdPAGO=$idPago"
        }
        $monto = ConvertTo-HelenaDecimal $p.MONTO "PAGOS.MONTO" "BLOCK" "IdPAGO=$idPago"
        $saldoPago = ConvertTo-HelenaDecimal $p.SALDO "PAGOS.SALDO" "BLOCK" "IdPAGO=$idPago"
        $fechaPago = ConvertTo-HelenaDate $p.FECHA "PAGOS.FECHA" "BLOCK" "IdPAGO=$idPago"
        [array]$entregasPago = if ($entregasPorPago.ContainsKey($idPago)) { @($entregasPorPago[$idPago]) } else { @() }
        $totalEntregado = [decimal]0
        foreach ($ep in $entregasPago) { $totalEntregado += [decimal]$ep.Importe }
        $mediosPago = if ($entregasPago.Count -gt 0) {
            (($entregasPago | Group-Object MedioPago | ForEach-Object { "$($_.Name):$(Money ([decimal](($_.Group | Measure-Object -Property Importe -Sum).Sum)))" }) -join " | ")
        } else {
            "SIN_DETALLE"
        }
        $estadoImputacion = "OK"
        if ($p.TIPO -eq "CANCELACION" -and [math]::Abs([double]($monto - $imputado)) -gt 1.5) {
            $estadoImputacion = "REVISAR_CANCELACION_NO_IMPUTA_TOTAL"
        }
        elseif ($p.TIPO -eq "A CUENTA" -and $saldoPago -le 0) {
            $estadoImputacion = "REVISAR_A_CUENTA_SIN_SALDO"
        }
        elseif ($p.TIPO -eq "A CUENTA" -and $detalle.Count -gt 0) {
            $estadoImputacion = "A_CUENTA_CON_IMPUTACIONES"
        }
        elseif ([math]::Abs([double]($monto - $totalEntregado)) -gt 1.5) {
            $estadoImputacion = "REVISAR_MEDIOS_NO_COINCIDEN_CON_PAGO"
        }

        $pagoRows += [pscustomobject]@{
            Fecha = $fechaPago.ToString("dd/MM/yyyy HH:mm:ss")
            IdPAGO = $idPago
            IdCLIENTE = $p.IdCLIENTE
            Cliente = $p.Cliente
            TipoPagoSistema = $p.TIPO
            MedioPago = $mediosPago
            Monto = $monto
            Saldo = $saldoPago
            ImputadoADocumentos = $imputado
            TotalMediosPago = $totalEntregado
            CantidadImputaciones = $detalle.Count
            CantidadMediosPago = $entregasPago.Count
            EstadoImputacion = $estadoImputacion
            UserID = $p.UserID
            Alerta = if ($estadoImputacion -like "REVISAR*") { $estadoImputacion } else { "" }
        }
    }

    $cajaGeneralSql = @"
SELECT 'GENERAL' AS Caja, IdCajaGrande AS IdMov, FECHA, TipoMov, TIPO, IMPORTE, DESCRIPCION, UserID
FROM MovCajaGeneral
WHERE UserID=$auditUserId AND FECHA >= $from AND FECHA < $to
ORDER BY FECHA, IdCajaGrande
"@
    $cajaGeneral = Rows ($conn.Execute($cajaGeneralSql))
    $cajaChicaSql = @"
SELECT 'CHICA' AS Caja, IdCajaChica AS IdMov, FECHA, TipoMov, TIPO, IMPORTE, DESCRIPCION, UserID
FROM MovCajaChica
WHERE UserID=$auditUserId AND FECHA >= $from AND FECHA < $to
ORDER BY FECHA, IdCajaChica
"@
    $cajaChica = Rows ($conn.Execute($cajaChicaSql))
    $cajaMovs = @($cajaGeneral) + @($cajaChica)

    $ncVinculadasPorFactura = @{}
    foreach ($application in $aplicacionesNc) {
        $facturaKey = [string]([int]$application.IdFactura)
        if (-not $ncVinculadasPorFactura.ContainsKey($facturaKey)) {
            $ncVinculadasPorFactura[$facturaKey] = @()
        }
        $numeroNc = if ($null -ne $application.NumeroNC -and -not ($application.NumeroNC -is [System.DBNull])) {
            Format-AccessNumber ([int]$application.NumeroNC)
        } else { "" }
        $importeNc = if ($null -ne $application.ImporteAplicado -and -not ($application.ImporteAplicado -is [System.DBNull])) {
            Money ([decimal][math]::Abs([double]$application.ImporteAplicado))
        } elseif ($null -ne $application.ImporteNC -and -not ($application.ImporteNC -is [System.DBNull])) {
            Money ([decimal][math]::Abs([double]$application.ImporteNC))
        } else { "" }
        $ncVinculadasPorFactura[$facturaKey] = @($ncVinculadasPorFactura[$facturaKey]) + @([pscustomobject]@{
            IdNotaCredito = $application.IdNotaCredito
            TipoNC = $application.TipoNC
            NumeroNC = $numeroNc
            FechaNC = if ($application.FechaNC -and -not ($application.FechaNC -is [System.DBNull])) { ([datetime]$application.FechaNC).ToString("dd/MM/yyyy") } else { "" }
            ImporteNC = $importeNc
            ComprobanteReferenciado = "$($application.TipoFactura) $(Format-AccessNumber ([int]$application.NumeroFactura))"
            FuenteVinculo = "T_GAS_NotasCreditoAplicaciones"
        })
    }

    [array]$notasCreditoPeriodo = @($todosComprobantes | Where-Object {
        (Is-NotaCredito ([string]$_.TIPO)) -and ([datetime]$_.FECHA) -ge $Desde -and ([datetime]$_.FECHA) -lt $Hasta
    })
    $ncPeriodoPorCliente = @{}
    foreach ($nc in $notasCreditoPeriodo) {
        $clientKey = [string]$nc.IdCLIENTE
        if (-not $ncPeriodoPorCliente.ContainsKey($clientKey)) {
            $ncPeriodoPorCliente[$clientKey] = @()
        }
        $ncPeriodoPorCliente[$clientKey] = @($ncPeriodoPorCliente[$clientKey]) + @($nc)

        $ncPdf = Find-AuditDocumentPdf -Tipo ([string]$nc.TIPO) -Number ([int]$nc.Numero) -Fecha ([datetime]$nc.FECHA) -PdfBaseRoot $PdfBaseRoot -PdfRoot $PdfRoot -RemitosRoot $RemitosRoot
        if ($ncPdf.Estado -ne "ENCONTRADO") { continue }
        $ncRead = Read-PdfTotal $ncPdf.Path $true
        if (-not $ncRead.Ok) { continue }
        $ncReference = Parse-NcPdfReference ([string]$ncRead.Raw)
        $ncReferenced = Find-ReferencedDocument $ncReference $comprobantesPorNumero
        if (-not $ncReference.Found -or -not $ncReferenced) { continue }

        $facturaKey = [string]([int]$ncReferenced.IdCOMPROVANTE)
        if (-not $ncVinculadasPorFactura.ContainsKey($facturaKey)) {
            $ncVinculadasPorFactura[$facturaKey] = @()
        }
        $alreadyLinked = @($ncVinculadasPorFactura[$facturaKey] | Where-Object {
            [string]$_.IdNotaCredito -eq [string]$nc.IdCOMPROVANTE
        }).Count -gt 0
        if (-not $alreadyLinked) {
            $importeNc = if ($null -ne $ncRead.Total -and [string]$ncRead.Total -ne "") {
                Money ([decimal][math]::Abs([double]$ncRead.Total))
            } elseif ($null -ne $nc.IMPORTE -and -not ($nc.IMPORTE -is [System.DBNull])) {
                Money ([decimal][math]::Abs([double]$nc.IMPORTE))
            } else { "" }
            $ncVinculadasPorFactura[$facturaKey] = @($ncVinculadasPorFactura[$facturaKey]) + @([pscustomobject]@{
                IdNotaCredito = $nc.IdCOMPROVANTE
                TipoNC = $nc.TIPO
                NumeroNC = Format-AccessNumber ([int]$nc.Numero)
                FechaNC = ([datetime]$nc.FECHA).ToString("dd/MM/yyyy")
                ImporteNC = $importeNc
                ComprobanteReferenciado = $ncReference.Display
                FuenteVinculo = "REFERENCIA_EXPLICITA_PDF_NC"
            })
        }
    }

    $reportRows = @()
    $notaCreditoRows = @()
    foreach ($c in $comprobantes) {
        $isNc = Is-NotaCredito ([string]$c.TIPO)
        $idComprobante = ConvertTo-HelenaInteger $c.IdCOMPROVANTE "COMPROVANTES.IdCOMPROVANTE" "BLOCK" "auditoria"
        $comprobanteKey = [string]$idComprobante
        $isRmt = (Normalize-AuditDocumentTipo ([string]$c.TIPO)) -eq "RMT"
        $fechaComprobante = ConvertTo-HelenaDate $c.FECHA "COMPROVANTES.FECHA" "BLOCK" "IdCOMPROVANTE=$idComprobante"
        $importeComprobante = ConvertTo-HelenaDecimal $c.IMPORTE "COMPROVANTES.IMPORTE" "BLOCK" "IdCOMPROVANTE=$idComprobante"
        $isAnulado = (-not $isNc) -and $comprobantesAnulados.ContainsKey($comprobanteKey)
        $rowDetails = if ($detallesPorComprobante.ContainsKey($comprobanteKey)) { @($detallesPorComprobante[$comprobanteKey]) } else { @() }
        $cantidadEstructurados = if ($detallesEstructuradosCount.ContainsKey($comprobanteKey)) { [int]$detallesEstructuradosCount[$comprobanteKey] } else { 0 }
        $cantidadLegacy = if ($detallesLegacyCount.ContainsKey($comprobanteKey)) { [int]$detallesLegacyCount[$comprobanteKey] } else { 0 }
        $detalleDecision = if ($isRmt) {
            Get-AuditDetalleComparisonDecision -EsAnulado $isAnulado -DetallesResueltos $rowDetails -CantidadEstructurados $cantidadEstructurados -CantidadLegacy $cantidadLegacy
        } else {
            [pscustomobject]@{ PuedeComparar = $false; Estado = ""; Observacion = "" }
        }
        $saldoComprobante = Resolve-AuditComprobanteSaldo `
            -EsAnulado $isAnulado `
            -Saldo $c.SALDO `
            -IdCOMPROVANTE $idComprobante `
            -ResolverActivo {
                param($value, $id)
                [pscustomobject]@{
                    Valor = ConvertTo-HelenaDecimal $value "COMPROVANTES.SALDO" "BLOCK" "IdCOMPROVANTE=$id"
                    Estado = "OK"
                    Diagnostico = ""
                }
            }
        $pdf = Find-AuditDocumentPdf -Tipo ([string]$c.TIPO) -Number ([int]$c.Numero) -Fecha $fechaComprobante -PdfBaseRoot $PdfBaseRoot -PdfRoot $PdfRoot -RemitosRoot $RemitosRoot
        $readTotal = $null
        $pdfTotal = $null
        $pdfTotalEstado = ""
        $pdfDiferencia = $null
        $rmtCheck = $null
        if ($pdf.Estado -eq "ENCONTRADO") {
            if ($isRmt) {
                if ($isAnulado) {
                    $pdfTotalEstado = "NO_COMPARADO_ANULADA"
                } elseif ($detalleDecision.PuedeComparar) {
                    $readTotal = Read-PdfTotal $pdf.Path $true
                    $pdfTotal = if ($readTotal.Ok) { [decimal]$readTotal.Total } else { $null }
                    if ($readTotal.Ok) {
                        $rmtPdfData = Get-AuditRemitoPdfData ([string]$readTotal.Raw)
                        $rmtCheck = Compare-AuditRemitoPdf -Comprobante $c -Detalles $rowDetails -PdfData $rmtPdfData
                        $pdfTotalEstado = $rmtCheck.PdfTotalEstado
                    } else {
                        $pdfTotalEstado = "NO_LEIDO: $($readTotal.Error)"
                    }
                } else {
                    $pdfTotalEstado = $detalleDecision.Estado
                }
            } elseif ($isAnulado) {
                $pdfCheck = Get-AuditPdfAmountResult -EsAnulado $true -EsNotaCredito $false -PdfLeido $false -ImporteSistema $c.IMPORTE -ImportePdf $null
                $pdfTotalEstado = $pdfCheck.PdfTotalEstado
                $pdfDiferencia = $pdfCheck.PdfDiferencia
            } else {
                $readTotal = Read-PdfTotal $pdf.Path $isNc
                $pdfTotal = if ($readTotal.Ok) { [decimal]$readTotal.Total } else { $null }
                $pdfCheck = Get-AuditPdfAmountResult -EsAnulado $false -EsNotaCredito $isNc -PdfLeido ([bool]$readTotal.Ok) -ImporteSistema $c.IMPORTE -ImportePdf $pdfTotal -ErrorLectura ([string]$readTotal.Error)
                $pdfTotalEstado = $pdfCheck.PdfTotalEstado
                $pdfDiferencia = $pdfCheck.PdfDiferencia
            }
        }
        $reportRows += [pscustomobject]@{
            Fecha = $fechaComprobante.ToString("dd/MM/yyyy")
            Tipo = $c.TIPO
            Numero = $c.Numero
            IdCOMPROVANTE = $idComprobante
            IdCLIENTE = $c.IdCLIENTE
            Cliente = $c.Cliente
            CUIT = $c.CUIT
            IVA = NzDecimal $c.IVA
            Importe = $importeComprobante
            Saldo = $saldoComprobante.Valor
            EsNotaCredito = $isNc
            EsAnulado = $isAnulado
            Estado = ""
            Observacion = if ($rmtCheck -and $rmtCheck.Observacion) { $rmtCheck.Observacion } else { $detalleDecision.Observacion }
            NotaCreditoRelacionada = ""
            PdfEstado = $pdf.Estado
            PdfArchivo = $pdf.Path
            PdfEsperado = $pdf.Candidato
            PdfTotal = $pdfTotal
            PdfTotalEstado = $pdfTotalEstado
            PdfDiferencia = $pdfDiferencia
            Alerta = if ($isAnulado) {
                ""
            } elseif ($isRmt) {
                if ($detalleDecision.Estado) { $detalleDecision.Estado }
                elseif ($pdf.Estado -eq "PDF_REMITO_NO_ENCONTRADO") { "PDF_REMITO_NO_ENCONTRADO" }
                elseif ($pdf.Estado -eq "PDF_AMBIGUO") { "PDF_REMITO_AMBIGUO" }
                elseif ($pdf.Estado -eq "ENCONTRADO" -and $rmtCheck -and $rmtCheck.Alerta) { $rmtCheck.Alerta }
                elseif ($pdf.Estado -eq "ENCONTRADO" -and $pdfTotalEstado -like "NO_LEIDO*") { "PDF_REMITO_NO_LEIDO" }
                else { "" }
            } elseif ($pdf.Estado -eq "FALTANTE") {
                if ($isNc) { "PDF_NC_FALTANTE" } else { "PDF_FALTANTE" }
            } elseif ($pdf.Estado -eq "PDF_AMBIGUO") {
                "PDF_AMBIGUO"
            } elseif (-not $isNc -and $pdfTotalEstado -eq "DIFERENTE") {
                "IMPORTE_PDF_DIFERENTE"
            } else { "" }
        }

        if ($isNc) {
            $ncDisplay = Format-AccessNumber ([int]$c.Numero)
            $reference = if ($pdf.Estado -eq "ENCONTRADO" -and $null -ne $readTotal) {
                Parse-NcPdfReference ([string]$readTotal.Raw)
            } else {
                [pscustomobject]@{ Found = $false; Letter = ""; Point = $null; Seq = $null; NumeroAccess = $null; Display = ""; Raw = "" }
            }
            $referenced = Find-ReferencedDocument $reference $comprobantesPorNumero
            $sameClient = Test-SameClientOrCuit $c $referenced
            $ivaCheck = Get-NcIvaCheck $c $referenced
            $referenceLabel = if ($reference.Found) { $reference.Display } else { "NO_IDENTIFICABLE" }
            $facturaExiste = if (-not $reference.Found) { "NO_VERIFICABLE" } elseif ($referenced) { "SI" } else { "NO" }
            $mismoCliente = if ($referenced) { if ($sameClient) { "SI" } else { "NO" } } else { "NO_VERIFICABLE" }
            $puntoNumero = if (-not $reference.Found) { "SIN_REFERENCIA" } elseif ($referenced) { "OK" } else { "REFERENCIA_NO_ENCONTRADA" }
            $ivaCoherente = if (-not $referenced) { "NO_VERIFICABLE" } elseif ($ivaCheck.Estado -eq "OK") { "SI" } else { "NO" }

            $messages = @()
            if ($pdf.Estado -ne "ENCONTRADO") {
                $messages += "$IconWarning Referencia de factura no disponible automaticamente. Revisar el PDF de la NC."
            }
            elseif (-not $reference.Found) {
                $messages += "$IconWarning Referencia de factura no disponible automaticamente. Revisar el PDF de la NC."
            }
            elseif (-not $referenced) {
                $messages += "$IconWarning NC $ncDisplay referencia una factura inexistente."
            }
            else {
                if (-not $sameClient) {
                    $messages += "$IconWarning NC $ncDisplay corresponde a otro cliente o CUIT."
                }
                if ($ivaCheck.Estado -eq "REVISAR") {
                    $messages += "$IconWarning El IVA de la NC no coincide con el IVA que deberia anular o descontar."
                }
                elseif ($ivaCheck.TipoAjuste -eq "AJUSTE_PARCIAL") {
                    $messages += "$IconInfo Ajuste parcial. Revisar correspondencia entre importe e IVA."
                }
                if ($messages.Count -eq 0) {
                    $messages += "$IconOk NC $ncDisplay vinculada correctamente con $referenceLabel."
                }
            }

            $notaCreditoRows += [pscustomobject]@{
                Fecha = ([datetime]$c.FECHA).ToString("dd/MM/yyyy")
                TipoNC = $c.TIPO
                NumeroNC = $ncDisplay
                IdCOMPROVANTE = $c.IdCOMPROVANTE
                Cliente = $c.Cliente
                CUIT = $c.CUIT
                Importe = $importeComprobante
                IVA = NzDecimal $c.IVA
                ComprobanteReferenciado = $referenceLabel
                ReferenciaTextoPDF = $reference.Raw
                ReferenciaNumeroAccess = if ($reference.Found) { $reference.NumeroAccess } else { "" }
                FacturaExiste = $facturaExiste
                MismoClienteOCuit = $mismoCliente
                PuntoVentaNumero = $puntoNumero
                IvaCoherente = $ivaCoherente
                TipoAjuste = $ivaCheck.TipoAjuste
                ReferenciaDuplicada = "NO"
                Resultado = ($messages -join " ")
                PdfEstado = $pdf.Estado
                PdfArchivo = $pdf.Path
            }
        }
    }

    foreach ($group in @($notaCreditoRows | Where-Object { $_.ReferenciaNumeroAccess } | Group-Object ReferenciaNumeroAccess)) {
        if ($group.Count -gt 1) {
            $display = Format-AccessNumber ([int]$group.Name)
            foreach ($row in $group.Group) {
                $row.ReferenciaDuplicada = "SI"
                $row.Resultado = "$($row.Resultado) $IconWarning La factura $display tiene mas de una NC asociada. Revisar."
            }
        }
    }

    foreach ($row in $reportRows) {
        if (-not $row.EsAnulado) {
            if ($row.Alerta) {
                $row.Estado = $row.Alerta
            } elseif ($row.PdfTotalEstado -eq "OK") {
                $row.Estado = "OK"
            } elseif ($row.EsNotaCredito) {
                $row.Estado = "NC_REVISION_ADMINISTRATIVA"
            } else {
                $row.Estado = $row.PdfEstado
            }
            continue
        }

        $rowKey = [string]([int]$row.IdCOMPROVANTE)
        [array]$linkedNotes = if ($ncVinculadasPorFactura.ContainsKey($rowKey)) { @($ncVinculadasPorFactura[$rowKey]) } else { @() }
        [array]$sameClientNotes = if ($ncPeriodoPorCliente.ContainsKey([string]$row.IdCLIENTE)) { @($ncPeriodoPorCliente[[string]$row.IdCLIENTE]) } else { @() }
        [array]$unlinkedSameClientNotes = @($sameClientNotes | Where-Object {
            $candidateId = [string]$_.IdCOMPROVANTE
            @($linkedNotes | Where-Object { [string]$_.IdNotaCredito -eq $candidateId }).Count -eq 0
        })
        $anulacion = Resolve-AuditAnulacionState -EsAnulado $true -NotasCreditoVinculadas $linkedNotes -HayNcPosibleNoVinculada ($unlinkedSameClientNotes.Count -gt 0)
        $row.Estado = $anulacion.Estado
        $row.Observacion = ("{0} {1} {2} ANULADO. Verificar anulaci{3}n. {4}" -f $row.Tipo, $row.Numero, [char]0x2014, [char]0x00F3, $anulacion.Observacion).Trim()
        $row.NotaCreditoRelacionada = $anulacion.NotaCreditoRelacionada
        $row.PdfTotal = $null
        $row.PdfTotalEstado = "NO_COMPARADO_ANULADA"
        $row.PdfDiferencia = $null
        $row.Alerta = ""
    }

    $detalleAlertas = @()
    foreach ($row in $reportRows) {
        if ($row.EsAnulado -or $row.EsNotaCredito) {
            continue
        }
        $rowKey = [string]([int]$row.IdCOMPROVANTE)
        if (-not $detalleResoluciones.ContainsKey($rowKey)) {
            continue
        }
        $detalleState = $detalleResoluciones[$rowKey]
        if ($detalleState.Estado -ne "DETALLE_COMPROBANTE_AMBIGUO") {
            continue
        }
        if ($row.Alerta -eq "DETALLE_NO_RESUELTO") {
            $detalleAlertas += [pscustomobject]@{
                TipoAlerta = "DETALLE_NO_RESUELTO"
                Fecha = $row.Fecha
                Comprobante = "$($row.Tipo) $($row.Numero)"
                Cliente = $row.Cliente
                Producto = ""
                Detalle = $detalleState.Mensaje
            }
            continue
        }
        $row.Estado = "ALERTA"
        $row.Observacion = if ($row.Observacion) { "$($row.Observacion) | REVISAR DETALLE DE COMPROBANTE" } else { "REVISAR DETALLE DE COMPROBANTE" }
        $row.Alerta = if ($row.Alerta) { "$($row.Alerta) | DETALLE_COMPROBANTE_AMBIGUO" } else { "DETALLE_COMPROBANTE_AMBIGUO" }
        $detalleAlertas += [pscustomobject]@{
            TipoAlerta = "DETALLE_COMPROBANTE_AMBIGUO"
            Fecha = $row.Fecha
            Comprobante = "$($row.Tipo) $($row.Numero)"
            Cliente = $row.Cliente
            Producto = ""
            Detalle = $detalleState.Mensaje
        }
    }

    $precioVentaBajoPorComprobante = Get-AuditPrecioVentaBajo -Detalles $detalles -PreciosPorProducto $preciosBase -ComprobantesAnulados $comprobantesAnulados
    foreach ($row in $reportRows) {
        if ($row.EsAnulado -or $row.EsNotaCredito) {
            continue
        }
        $rowKey = [string]([int]$row.IdCOMPROVANTE)
        if (-not $precioVentaBajoPorComprobante.ContainsKey($rowKey)) {
            continue
        }

        $priceAlert = $precioVentaBajoPorComprobante[$rowKey]
        $row.Estado = "ALERTA"
        $row.Observacion = if ($row.Observacion) { "$($row.Observacion) | $($priceAlert.Observacion)" } else { $priceAlert.Observacion }
        $row.Alerta = if ($row.Alerta) { "$($row.Alerta) | $($priceAlert.TipoAlerta)" } else { $priceAlert.TipoAlerta }
    }

    $alerts = @($detalleAlertas) + @($precioVentaBajoPorComprobante.Values)
    foreach ($d in $detalles) {
        if (Is-NotaCredito ([string]$d.TIPO)) {
            continue
        }
        if ($comprobantesAnulados.ContainsKey([string]([int]$d.IdCOMPROVANTE))) {
            continue
        }
        $qty = Parse-Decimal $d.CANTIDAD
        $price = Parse-Decimal $d.PUNITARIO
        $subtotal = Parse-Decimal $d.Subtotal
        if ($qty -ne $null -and $price -ne $null -and $subtotal -ne $null) {
            $expected = $qty * $price
            if ([math]::Abs([double]($expected - $subtotal)) -gt 1.5) {
                $alerts += [pscustomobject]@{
                    TipoAlerta = "SUBTOTAL_NO_COINCIDE"
                    Fecha = ([datetime]$d.FECHA).ToString("dd/MM/yyyy")
                    Comprobante = "$($d.TIPO) $($d.Numero)"
                    Cliente = $d.Cliente
                    Producto = $d.PRODUCTO
                    Detalle = "Cantidad x PUnitario = $(Money $expected), Subtot = $(Money $subtotal)"
                }
            }
        }

    }

    foreach ($r in $reportRows) {
        if ($r.PdfEstado -eq "ENCONTRADO" -and $r.PdfTotalEstado -eq "DIFERENTE") {
            $alerts += [pscustomobject]@{
                TipoAlerta = "IMPORTE_PDF_DIFERENTE"
                Fecha = $r.Fecha
                Comprobante = "$($r.Tipo) $($r.Numero)"
                Cliente = $r.Cliente
                Producto = ""
                Detalle = "Access = $(Money $r.Importe), PDF = $(Money $r.PdfTotal), Diferencia = $(Money $r.PdfDiferencia)"
            }
        }
        elseif ($r.PdfEstado -eq "ENCONTRADO" -and $r.PdfTotalEstado -like "NO_LEIDO*") {
            $alerts += [pscustomobject]@{
                TipoAlerta = "PDF_TOTAL_NO_LEIDO"
                Fecha = $r.Fecha
                Comprobante = "$($r.Tipo) $($r.Numero)"
                Cliente = $r.Cliente
                Producto = ""
                Detalle = $r.PdfTotalEstado
            }
        }
    }

    $reportRows |
        Select-Object Fecha, Tipo, Numero, IdCOMPROVANTE, Cliente, Importe, Saldo, Estado, Observacion, NotaCreditoRelacionada, PdfEstado, PdfEsperado, PdfTotal, PdfTotalEstado, PdfDiferencia, Alerta |
        Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8
    $pagoRows | Export-Csv -LiteralPath $OutPagosCsv -NoTypeInformation -Encoding UTF8
    $entregaRows | Export-Csv -LiteralPath $OutEntregasCsv -NoTypeInformation -Encoding UTF8
    if ($notaCreditoRows.Count -gt 0) {
        $notaCreditoRows |
            Select-Object Fecha, TipoNC, NumeroNC, IdCOMPROVANTE, Cliente, CUIT, Importe, IVA, ComprobanteReferenciado, ReferenciaTextoPDF, FacturaExiste, MismoClienteOCuit, PuntoVentaNumero, IvaCoherente, TipoAjuste, ReferenciaDuplicada, Resultado, PdfEstado, PdfArchivo |
            Export-Csv -LiteralPath $OutNotasCreditoCsv -NoTypeInformation -Encoding UTF8
    } else {
        Set-Content -LiteralPath $OutNotasCreditoCsv -Value "" -Encoding UTF8
    }

    [array]$reportRowsSinNc = @($reportRows | Where-Object { -not $_.EsNotaCredito })
    $totalImporte = ($reportRowsSinNc | Measure-Object -Property Importe -Sum).Sum
    $totalNotasCreditoImporte = ($reportRows | Where-Object { $_.EsNotaCredito } | Measure-Object -Property Importe -Sum).Sum
    $totalNotasCreditoIva = ($reportRows | Where-Object { $_.EsNotaCredito } | Measure-Object -Property IVA -Sum).Sum
    $totalPagos = ($pagoRows | Measure-Object -Property Monto -Sum).Sum
    $totalPagoCancelacion = ($pagoRows | Where-Object { $_.TipoPagoSistema -eq "CANCELACION" } | Measure-Object -Property Monto -Sum).Sum
    $totalPagoACuenta = ($pagoRows | Where-Object { $_.TipoPagoSistema -eq "A CUENTA" } | Measure-Object -Property Monto -Sum).Sum
    $pagosAlertas = @($pagoRows | Where-Object { $_.Alerta })
    $mediosResumen = $entregaRows | Group-Object MedioPago | Sort-Object Name
    $totalCajaGeneral = ($cajaGeneral | Measure-Object -Property IMPORTE -Sum).Sum
    $totalCajaChica = ($cajaChica | Measure-Object -Property IMPORTE -Sum).Sum
    $byTipo = $reportRows | Group-Object Tipo | Sort-Object Name
    $pdfChecks = $reportRows | Where-Object { $_.PdfEstado -ne "NO_APLICA" }
    $pdfFound = @($pdfChecks | Where-Object { $_.PdfEstado -eq "ENCONTRADO" })
    $pdfMissing = @($pdfChecks | Where-Object { $_.PdfEstado -eq "FALTANTE" })
    $pdfTotalDiff = @($reportRows | Where-Object { $_.PdfTotalEstado -eq "DIFERENTE" })
    $pdfTotalRead = @($reportRows | Where-Object { $_.PdfTotalEstado -eq "OK" -or $_.PdfTotalEstado -eq "DIFERENTE" })
    $anuladosRows = @($reportRows | Where-Object { $_.EsAnulado })

    $lines = @()
    $lines += "# Auditoria $auditUserLabel"
    $lines += ""
    $lines += "Periodo: $($Desde.ToString('dd/MM/yyyy')) al $($Hasta.AddDays(-1).ToString('dd/MM/yyyy'))"
    $lines += "Base local: ``$dbPath``"
    $lines += "PDF roots: ``$($PdfRoots -join ' | ')``"
    $lines += ""
    $lines += "## Resumen"
    $lines += ""
    $lines += "- Comprobantes generados: $($reportRows.Count)"
    if ($notaCreditoRows.Count -gt 0) {
        $lines += "- Importe total sin notas de credito: $(Money ([decimal]$totalImporte))"
        $lines += "- Notas de credito detectadas: $($notaCreditoRows.Count), importe: $(Money ([decimal]$totalNotasCreditoImporte)), IVA: $(Money ([decimal]$totalNotasCreditoIva))"
    } else {
        $lines += "- Importe total: $(Money ([decimal]$totalImporte))"
        $lines += "- Notas de credito detectadas: 0"
    }
    $lines += "- Lineas de detalle revisadas: $($detalles.Count)"
    $lines += "- Comprobantes anulados: $($anuladosRows.Count)"
    $lines += "- Recibos/pagos cargados por ${auditUserLabel}: $($pagoRows.Count)"
    $lines += "- Total pagos ${auditUserLabel}: $(Money ([decimal]$totalPagos))"
    $lines += "- PDFs esperados: $($pdfChecks.Count)"
    $lines += "- PDFs encontrados: $($pdfFound.Count)"
    $lines += "- Totales PDF leidos: $($pdfTotalRead.Count)"
    if ($pdfTotalDiff.Count -gt 0) {
        $lines += "- <span style='color:#b00020; font-weight:bold'>Totales PDF diferentes a Access: $($pdfTotalDiff.Count)</span>"
    } else {
        $lines += "- Totales PDF diferentes a Access: 0"
    }
    if ($pdfMissing.Count -gt 0) {
        $lines += "- <span style='color:#b00020; font-weight:bold'>PDFs faltantes/dudosos: $($pdfMissing.Count)</span>"
    } else {
        $lines += "- PDFs faltantes/dudosos: 0"
    }
    if ($alerts.Count -gt 0) {
        $lines += "- <span style='color:#b00020; font-weight:bold'>Alertas de precio/subtotal: $($alerts.Count)</span>"
    } else {
        $lines += "- Alertas de precio/subtotal: 0"
    }
    if ($pagosAlertas.Count -gt 0) {
        $lines += "- <span style='color:#b00020; font-weight:bold'>Alertas de imputacion de pagos: $($pagosAlertas.Count)</span>"
    } else {
        $lines += "- Alertas de imputacion de pagos: 0"
    }
    $lines += ""
    $lines += "## Por tipo"
    $lines += ""
    foreach ($g in $byTipo) {
        $sum = ($g.Group | Measure-Object -Property Importe -Sum).Sum
        $lines += "- $($g.Name): $($g.Count) comprobantes, $(Money ([decimal]$sum))"
    }
    $lines += ""
    $lines += "## Recibos/pagos $auditUserLabel"
    $lines += ""
    $lines += "- Pagos cargados: $($pagoRows.Count)"
    $lines += "- Total pagos: $(Money ([decimal]$totalPagos))"
    $lines += "- Cancelaciones: $(Money ([decimal]$totalPagoCancelacion))"
    $lines += "- A cuenta: $(Money ([decimal]$totalPagoACuenta))"
    $lines += "- Movimientos caja general ${auditUserLabel}: $($cajaGeneral.Count), total: $(Money ([decimal]$totalCajaGeneral))"
    $lines += "- Movimientos caja chica ${auditUserLabel}: $($cajaChica.Count), total: $(Money ([decimal]$totalCajaChica))"
    $lines += "- Detalle de medios: tomado desde `DETALLE DE ENTREGAS`."
    $lines += ""
    $lines += "### Totales por medio de pago"
    if ($mediosResumen.Count -eq 0) {
        $lines += "- Sin detalle de medios de pago."
    } else {
        foreach ($m in $mediosResumen) {
            $sumMedio = ($m.Group | Measure-Object -Property Importe -Sum).Sum
            $lines += "- $($m.Name): $($m.Count) registros, $(Money ([decimal]$sumMedio))"
        }
    }
    $lines += ""
    if ($pagosAlertas.Count -gt 0) {
        $lines += "### Alertas de pagos"
        foreach ($p in $pagosAlertas) {
            $lines += "- <strong style='color:#b00020'>$($p.Fecha) Pago $($p.IdPAGO) - $($p.Cliente) - $(Money $p.Monto) - $($p.Alerta)</strong>"
        }
        $lines += ""
    }
    foreach ($p in $pagoRows) {
        if ($p.Alerta) {
            $lines += "- <strong style='color:#b00020'>$($p.Fecha) Pago $($p.IdPAGO) - $($p.Cliente) - $($p.TipoPagoSistema) - $(Money $p.Monto) - Medios: $($p.MedioPago) - Imputado: $(Money $p.ImputadoADocumentos) - Saldo: $(Money $p.Saldo)</strong>"
        } else {
            $lines += "- $($p.Fecha) Pago $($p.IdPAGO) - $($p.Cliente) - $($p.TipoPagoSistema) - $(Money $p.Monto) - Medios: $($p.MedioPago) - Imputado: $(Money $p.ImputadoADocumentos) - Saldo: $(Money $p.Saldo)"
        }
    }
    $lines += ""
    $lines += "## PDFs faltantes o dudosos"
    $lines += ""
    if ($pdfMissing.Count -eq 0) {
        $lines += "Sin faltantes detectados para los tipos con mapeo de PDF."
    } else {
        foreach ($r in $pdfMissing) {
            $lines += "- <span style='color:#b00020; font-weight:bold'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente)</span> - esperado: '$($r.PdfEsperado)'"
        }
    }
    $lines += ""
    $lines += "## Notas de credito"
    $lines += ""
    if ($notaCreditoRows.Count -eq 0) {
        $lines += "Sin notas de credito detectadas en la actividad auditada."
    } else {
        $lines += "Las notas de credito se informan para revision administrativa. No se tratan como venta negativa adicional ni como diferencia de importe PDF vs Access."
        foreach ($nc in $notaCreditoRows) {
            $lines += "- <strong>$($nc.Fecha) $($nc.TipoNC) $($nc.NumeroNC) - $($nc.Cliente) - CUIT: $($nc.CUIT)</strong>"
            $lines += "  - Importe: $(Money ([decimal]$nc.Importe)) - IVA: $(Money ([decimal]$nc.IVA))"
            $lines += "  - Referencia: $($nc.ComprobanteReferenciado)"
            $lines += "  - Verificacion: $($nc.Resultado)"
        }
    }
    $lines += ""
    $lines += "## Comprobantes anulados"
    $lines += ""
    if ($anuladosRows.Count -eq 0) {
        $lines += "Sin comprobantes anulados detectados."
    } else {
        foreach ($r in $anuladosRows) {
            $lines += "- <strong style='color:#7a4b00'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - ESTADO: $($r.Estado)</strong>"
            $lines += "  - OBSERVACION: $($r.Observacion)"
            if ($r.NotaCreditoRelacionada) {
                $lines += "  - NC relacionada: $($r.NotaCreditoRelacionada)"
            }
        }
    }
    $lines += ""
    $lines += "## Alertas"
    $lines += ""
    if ($alerts.Count -eq 0) {
        $lines += "Sin alertas basicas de precio/subtotal."
    } else {
        foreach ($a in $alerts | Select-Object -First 80) {
            $lines += "- <span style='color:#b00020; font-weight:bold'>[$($a.TipoAlerta)] $($a.Fecha) $($a.Comprobante)</span> - $($a.Cliente) - $($a.Producto): $($a.Detalle)"
        }
        if ($alerts.Count -gt 80) {
            $lines += "- ... $($alerts.Count - 80) alertas adicionales no mostradas en este resumen."
        }
    }
    $lines += ""
    $lines += "## Control de importes PDF vs Access"
    $lines += ""
    if ($pdfTotalDiff.Count -eq 0) {
        $lines += "Sin diferencias de importe entre Access y los PDF leidos."
    } else {
        foreach ($r in $pdfTotalDiff) {
            $lines += "- <strong style='color:#b00020'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - Access: $(Money $r.Importe), PDF: $(Money $r.PdfTotal), diferencia: $(Money $r.PdfDiferencia)</strong>"
        }
    }
    $lines += ""
    $lines += "## Comprobantes"
    $lines += ""
    foreach ($r in $reportRows) {
        if ($r.EsAnulado) {
            $ncText = if ($r.NotaCreditoRelacionada) { " - NC relacionada: $($r.NotaCreditoRelacionada)" } else { "" }
            $lines += "- <strong style='color:#7a4b00'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - ESTADO: $($r.Estado) - $($r.Observacion)$ncText</strong>"
        } elseif ($r.PdfEstado -eq "FALTANTE") {
            $lines += "- <strong style='color:#b00020'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - $(Money $r.Importe) - PDF: FALTANTE</strong>"
        } elseif ($r.PdfTotalEstado -eq "DIFERENTE") {
            $lines += "- <strong style='color:#b00020'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - $(Money $r.Importe) - PDF: ENCONTRADO - IMPORTE DIFERENTE</strong>"
        } elseif ($r.Alerta) {
            $lines += "- <strong style='color:#b00020'>$($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - $(Money $r.Importe) - ESTADO: $($r.Estado) - $($r.Observacion)</strong>"
        } else {
            $lines += "- $($r.Fecha) $($r.Tipo) $($r.Numero) - $($r.Cliente) - $(Money $r.Importe) - PDF: $($r.PdfEstado)"
        }
    }

    Set-Content -LiteralPath $OutMarkdown -Value $lines -Encoding UTF8

    $html = @()
    $html += "<!doctype html><html><head><meta charset='utf-8'>"
    $html += "<style>body{font-family:Arial,Segoe UI,sans-serif;margin:32px;color:#111827} h1{font-size:24px} h2{font-size:18px;margin-top:28px;border-bottom:1px solid #e5e7eb;padding-bottom:6px} li{margin:5px 0} code{background:#f3f4f6;padding:2px 4px;border-radius:4px}.muted{color:#6b7280}</style>"
    $html += "</head><body>"
    foreach ($line in $lines) {
        if ($line -like "# *") {
            $html += "<h1>$($line.Substring(2))</h1>"
        }
        elseif ($line -like "## *") {
            $html += "<h2>$($line.Substring(3))</h2>"
        }
        elseif ($line -like "- *") {
            $html += "<li>$($line.Substring(2))</li>"
        }
        elseif ($line.Trim() -eq "") {
            $html += "<br>"
        }
        else {
            $html += "<p>$line</p>"
        }
    }
    $html += "</body></html>"
    Set-Content -LiteralPath $OutHtml -Value $html -Encoding UTF8

    [pscustomobject]@{
        Creado = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        Entries = @($script:pdfTotalCache.Values)
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pdfTotalCachePath -Encoding UTF8

    [pscustomobject]@{
        Markdown = $OutMarkdown
        Html = $OutHtml
        Csv = $OutCsv
        PagosCsv = $OutPagosCsv
        EntregasCsv = $OutEntregasCsv
        NotasCreditoCsv = $OutNotasCreditoCsv
        UsuarioId = $auditUserId
        Usuario = $auditUserLabel
        Comprobantes = $reportRows.Count
        ImporteTotal = Money ([decimal]$totalImporte)
        NotasCredito = $notaCreditoRows.Count
        Pagos = $pagoRows.Count
        TotalPagos = Money ([decimal]$totalPagos)
        PdfEsperados = $pdfChecks.Count
        PdfEncontrados = $pdfFound.Count
        PdfFaltantes = $pdfMissing.Count
        Anulados = $anuladosRows.Count
        Alertas = $alerts.Count
    } | Format-List
}
catch {
    throw (Format-HelenaErrorDetail "auditorias" "generar_auditoria_usuario" $_ @{UsuarioId=$auditUserId})
}
finally {
    if ($conn -and $conn.State -eq 1) { $conn.Close() }
}
