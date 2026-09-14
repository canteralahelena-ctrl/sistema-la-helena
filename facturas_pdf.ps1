param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("factura", "cliente", "ultimas-cliente")]
    [string]$Accion,
    [string]$Cliente = "",
    [string]$Tipo = "",
    [string]$Numero = "",
    [datetime]$Desde = "1900-01-01",
    [datetime]$Hasta = "1900-01-01",
    [int]$Cantidad = 1,
    [string]$PdfBaseRoot = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\FACTURAS_EJEMPLO\02_FACTURACION SOCIEDAD",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$hardeningHelper = Join-Path $PSScriptRoot "access_hardening.ps1"
. $hardeningHelper
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
if (-not $OutDir) {
    $OutDir = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
}

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

function Clean-FileName([string]$name) {
    $clean = $name -replace '[\\/:*?"<>|]', '_'
    $clean = $clean -replace '\s+', '_'
    return $clean.Trim('_')
}

function Split-AccessNumber([int]$number) {
    $point = [math]::Floor($number / 100000000)
    $seq = $number % 100000000
    return [pscustomobject]@{ Point = [int]$point; Seq = [int]$seq }
}

function Parse-AccessNumber([string]$text) {
    $digits = ($text -replace '\D', '')
    if (-not $digits) {
        throw "Indica el numero de comprobante."
    }
    $raw = [int64]$digits
    if ($raw -lt 100000000) {
        return [int](200000000 + $raw)
    }
    return [int]$raw
}

function Get-YearPdfRoots([string]$baseRoot, [datetime]$from, [datetime]$to) {
    if ($from -ne [datetime]"1900-01-01") {
        $endInclusive = if ($to -eq [datetime]"1900-01-01") { $from } else { $to.AddDays(-1) }
        if ($endInclusive -lt $from) { $endInclusive = $from }
        $roots = @()
        for ($year = $from.Year; $year -le $endInclusive.Year; $year++) {
            $roots += (Join-Path $baseRoot ([string]$year))
        }
        return $roots
    }

    try {
        $dirs = Get-ChildItem -LiteralPath $baseRoot -Directory -ErrorAction Stop |
            Where-Object { $_.Name -match '^\d{4}$' } |
            Sort-Object Name -Descending
        if ($dirs.Count -gt 0) {
            return @($dirs | ForEach-Object { $_.FullName })
        }
    }
    catch { throw "RAIZ_INACCESIBLE modulo=pdf operacion=listar_anios" }
    return @((Join-Path $baseRoot ((Get-Date).Year.ToString())))
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
    if ($t -in @("FTS A", "FT A", "FACTURA A", "A")) {
        $candidates += [pscustomobject]@{ Tipo = "FTS A"; Folder = "FT A"; Name = "FTA{0}_{1}.pdf" -f $point5, $seq8 }
    }
    elseif ($t -in @("FTS B", "FT B", "FACTURA B", "B")) {
        $candidates += [pscustomobject]@{ Tipo = "FTS B"; Folder = "FT B"; Name = "FTB{0}_{1}.pdf" -f $point5, $seq8 }
    }
    elseif ($t -eq "FP A") {
        $candidates += [pscustomobject]@{ Tipo = "FP A"; Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point4, $seq9 }
        $candidates += [pscustomobject]@{ Tipo = "FP A"; Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "FP A"; Folder = "FTP A"; Name = "Factura A{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -eq "FP B") {
        $candidates += [pscustomobject]@{ Tipo = "FP B"; Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point4, $seq9 }
        $candidates += [pscustomobject]@{ Tipo = "FP B"; Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "FP B"; Folder = "FTP B"; Name = "Factura B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("NCS A", "NC A", "NOTA CREDITO A")) {
        $candidates += [pscustomobject]@{ Tipo = "NCS A"; Folder = "NC A"; Name = "NC A {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "NCS A"; Folder = "NC A"; Name = "NC A {0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -in @("NCS B", "NC B", "NOTA CREDITO B")) {
        $candidates += [pscustomobject]@{ Tipo = "NCS B"; Folder = "NC B"; Name = "NC B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "NCS B"; Folder = "NC B"; Name = "NC B {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "NCS B"; Folder = "NC B"; Name = "NC B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -eq "ND A") {
        $candidates += [pscustomobject]@{ Tipo = "ND A"; Folder = "ND A"; Name = "ND A {0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "ND A"; Folder = "ND A"; Name = "ND A {0}_{1}.pdf" -f $point5, $seq6 }
    }
    elseif ($t -eq "ND B") {
        $candidates += [pscustomobject]@{ Tipo = "ND B"; Folder = "ND B"; Name = "ND B{0}_{1}.pdf" -f $point5, $seq8 }
        $candidates += [pscustomobject]@{ Tipo = "ND B"; Folder = "ND B"; Name = "ND B{0}_{1}.pdf" -f $point5, $seq6 }
    }
    return $candidates
}

function Get-AllCandidates([int]$number) {
    $types = @("FTS A", "FTS B", "FP A", "FP B", "NCS A", "NCS B", "ND A", "ND B")
    $all = @()
    foreach ($t in $types) {
        $all += Get-PdfCandidates $t $number
    }
    return $all
}

function Find-Pdf([string]$tipo, [int]$number, [object[]]$pdfRoots) {
    $candidates = if ($tipo) { Get-PdfCandidates $tipo $number } else { Get-AllCandidates $number }
    foreach ($pdfRootItem in $pdfRoots) {
        foreach ($candidate in $candidates) {
            $path = Join-Path (Join-Path $pdfRootItem $candidate.Folder) $candidate.Name
            try {
                if (Test-Path -LiteralPath $path) {
                    return [pscustomobject]@{
                        Estado = "ENCONTRADO"
                        EstadoDocumento = "PDF_OK"
                        Path = $path
                        Tipo = $candidate.Tipo
                        Esperado = "$([IO.Path]::GetFileName($pdfRootItem))\$($candidate.Folder)\$($candidate.Name)"
                    }
                }
            }
            catch {
                return [pscustomobject]@{ Estado = "RAIZ_INACCESIBLE"; EstadoDocumento = "RAIZ_INACCESIBLE"; Path = $path; Tipo = $candidate.Tipo; Esperado = $path }
            }
        }
    }
    return [pscustomobject]@{
        Estado = "FALTANTE"
        EstadoDocumento = "PDF_NO_ENCONTRADO"
        Path = ""
        Tipo = $tipo
        Esperado = ($candidates | ForEach-Object { "$($_.Folder)\$($_.Name)" }) -join " | "
    }
}

function Resolve-ClientId([object]$conn, [string]$client) {
    if ($client -match '^\d+$') {
        return [int]$client
    }
    $safe = $client.Replace("'", "''")
    $sql = "SELECT TOP 1 IdCLIENTE, [RAZ SOCIAL] FROM CLIENTES WHERE [RAZ SOCIAL] LIKE '%$safe%' ORDER BY [RAZ SOCIAL]"
    $rows = Rows ($conn.Execute($sql)) 5
    if ($rows.Count -eq 0) {
        throw "No encontre cliente: $client"
    }
    return [int]$rows[0].IdCLIENTE
}

$rootAccess = Test-HelenaDocumentRoot "FACTURAS_ROOT" $PdfBaseRoot
if (-not $rootAccess.Ok) {
    [pscustomobject]@{
        Estado = "RAIZ_INACCESIBLE"
        EstadoDocumento = "RAIZ_INACCESIBLE"
        Mensaje = "No se puede leer la raiz de facturas."
    } | ConvertTo-Json -Depth 3
    return
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    if ($Accion -eq "factura") {
        $accessNumber = Parse-AccessNumber $Numero
        $pdfRoots = Get-YearPdfRoots $PdfBaseRoot $Desde $Hasta
        $found = Find-Pdf $Tipo $accessNumber $pdfRoots
        if ($found.Estado -eq "ENCONTRADO") {
            [pscustomobject]@{
                Estado = "OK"
                EstadoDocumento = "PDF_OK"
                Archivo = $found.Path
                Caption = "PDF encontrado: $($found.Tipo) $accessNumber"
            } | ConvertTo-Json -Depth 3
        } else {
            [pscustomobject]@{
                Estado = $found.Estado
                EstadoDocumento = $found.EstadoDocumento
                Mensaje = "No encontre el PDF solicitado."
                Esperado = $found.Esperado
            } | ConvertTo-Json -Depth 3
        }
        return
    }

    if (-not $Cliente) { throw "Indica el cliente." }

    $idCliente = Resolve-ClientId $conn $Cliente
    $numeroColumn = "[N" + [char]186 + "]"
    if ($Accion -eq "ultimas-cliente") {
        if ($Cantidad -lt 1) { $Cantidad = 1 }
        if ($Cantidad -gt 20) { $Cantidad = 20 }
        $sql = @"
SELECT TOP $Cantidad C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, C.IMPORTE
FROM COMPROVANTES AS C
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.IdCLIENTE=$idCliente
  AND C.TIPO IN ('FTS A','FT A','FTS B','FT B','FP A','FP B','NCS A','NC A','NCS B','NC B','ND A','ND B')
ORDER BY C.FECHA DESC, C.IdCOMPROVANTE DESC
"@
        $docs = @(Rows ($conn.Execute($sql)))
    }
    else {
        if ($Desde -eq [datetime]"1900-01-01") { throw "Indica -Desde." }
        if ($Hasta -eq [datetime]"1900-01-01") { $Hasta = (Get-Date).Date.AddDays(1) }
        $from = Date-Literal $Desde
        $to = Date-Literal $Hasta
        $sql = @"
SELECT C.IdCOMPROVANTE, C.TIPO, C.FECHA, C.$numeroColumn AS Numero, C.IdCLIENTE, CL.[RAZ SOCIAL] AS Cliente, C.IMPORTE
FROM COMPROVANTES AS C
LEFT JOIN CLIENTES AS CL ON C.IdCLIENTE = CL.IdCLIENTE
WHERE C.IdCLIENTE=$idCliente
  AND C.FECHA >= $from
  AND C.FECHA < $to
  AND C.TIPO IN ('FTS A','FT A','FTS B','FT B','FP A','FP B','NCS A','NC A','NCS B','NC B','ND A','ND B')
ORDER BY C.FECHA, C.TIPO, C.$numeroColumn
"@
        $docs = @(Rows ($conn.Execute($sql)))
    }
    if ($docs.Count -eq 0) {
        [pscustomobject]@{ Estado = "SIN_COMPROBANTES"; Mensaje = "No encontre facturas/notas para ese cliente y periodo." } | ConvertTo-Json -Depth 3
        return
    }

    if ($Accion -eq "ultimas-cliente") {
        $years = @($docs | ForEach-Object { ([datetime]$_.FECHA).Year } | Sort-Object -Unique)
        $pdfRoots = @($years | ForEach-Object { Join-Path $PdfBaseRoot ([string]$_) })
    } else {
        $pdfRoots = Get-YearPdfRoots $PdfBaseRoot $Desde $Hasta
    }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $clientName = Clean-FileName ([string]$docs[0].Cliente)
    $tempDir = Join-Path $OutDir ("facturas_{0}_{1}" -f $clientName, $stamp)
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $foundCount = 0
    $missing = @()
    $foundFiles = @()

    foreach ($doc in $docs) {
        $found = Find-Pdf ([string]$doc.TIPO) ([int]$doc.Numero) $pdfRoots
        $label = "{0:yyyy-MM-dd}_{1}_{2}.pdf" -f ([datetime]$doc.FECHA), (Clean-FileName ([string]$doc.TIPO)), $doc.Numero
        if ($found.Estado -eq "ENCONTRADO") {
            $dest = Join-Path $tempDir $label
            Copy-Item -LiteralPath $found.Path -Destination $dest -Force
            $foundFiles += $dest
            $foundCount++
        } else {
            $missing += "{0:dd/MM/yyyy} {1} {2} - {3} - esperado: {4}" -f ([datetime]$doc.FECHA), $doc.TIPO, $doc.Numero, $doc.Cliente, $found.Esperado
        }
    }

    $manifest = Join-Path $tempDir "_faltantes_o_dudosos.txt"
    if ($missing.Count -gt 0) {
        $missing | Set-Content -LiteralPath $manifest -Encoding UTF8
    } else {
        "Sin faltantes detectados." | Set-Content -LiteralPath $manifest -Encoding UTF8
    }

    if ($Accion -eq "ultimas-cliente") {
        $zipPath = Join-Path $OutDir ("facturas_{0}_ultimas_{1}.zip" -f $clientName, $Cantidad)
        $captionPeriodo = "ultimas $($docs.Count)"
    } else {
        $zipPath = Join-Path $OutDir ("facturas_{0}_{1}_{2}.zip" -f $clientName, $Desde.ToString("yyyy-MM-dd"), $Hasta.AddDays(-1).ToString("yyyy-MM-dd"))
        $captionPeriodo = "$($Desde.ToString('dd/MM/yyyy')) al $($Hasta.AddDays(-1).ToString('dd/MM/yyyy'))"
    }

    if ($docs.Count -eq 1 -and $foundCount -eq 1 -and $missing.Count -eq 0) {
        $singlePdfPath = Join-Path $OutDir ("factura_{0}_{1}.pdf" -f $clientName, ([IO.Path]::GetFileNameWithoutExtension($foundFiles[0])))
        if (Test-Path -LiteralPath $singlePdfPath) { Remove-Item -LiteralPath $singlePdfPath -Force }
        Move-Item -LiteralPath $foundFiles[0] -Destination $singlePdfPath -Force
        Remove-Item -LiteralPath $tempDir -Recurse -Force

        [pscustomobject]@{
            Estado = "OK"
            Archivo = $singlePdfPath
            Caption = "Factura PDF: $($docs[0].Cliente) | $captionPeriodo"
            TotalComprobantes = $docs.Count
            Encontrados = $foundCount
            Faltantes = $missing.Count
        } | ConvertTo-Json -Depth 3
        return
    }

    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $tempDir "*") -DestinationPath $zipPath -Force
    Remove-Item -LiteralPath $tempDir -Recurse -Force

    [pscustomobject]@{
        Estado = "OK"
        Archivo = $zipPath
        Caption = "Facturas PDF: $($docs[0].Cliente) | $captionPeriodo | encontradas $foundCount de $($docs.Count)"
        TotalComprobantes = $docs.Count
        Encontrados = $foundCount
        Faltantes = $missing.Count
    } | ConvertTo-Json -Depth 3
}
finally {
    $conn.Close()
}
