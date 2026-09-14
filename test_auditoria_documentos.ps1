$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "auditoria_documentos.ps1")

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ([string]$Expected -ne [string]$Actual) {
        throw "$Name - esperado: '$Expected'; obtenido: '$Actual'"
    }
    Write-Host "OK - $Name"
}

function Assert-True($Actual, [string]$Name) {
    if (-not $Actual) {
        throw "$Name - esperado verdadero; obtenido: '$Actual'"
    }
    Write-Host "OK - $Name"
}

function New-TestFile([string]$Path) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    "PDF" | Set-Content -LiteralPath $Path -Encoding ASCII
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("audit_docs_" + [guid]::NewGuid().ToString("N"))
$factRoot = Join-Path $tmp "02_FACTURACION SOCIEDAD"
$rmtRoot = Join-Path $tmp "37_REMITOS"
try {
    New-TestFile (Join-Path $factRoot "2025\FT A\FTA00002_00004335.pdf")
    New-TestFile (Join-Path $factRoot "2026\FTS A\FTA00002_00004460.pdf")
    New-TestFile (Join-Path $factRoot "2027\FT A\FTA00002_00005001.pdf")
    New-TestFile (Join-Path $factRoot "2026\NC A\NC A 00002_00000125.pdf")
    New-TestFile (Join-Path $factRoot "ANTIGUAS\FT A\FTA00002_00003000.pdf")
    New-TestFile (Join-Path $rmtRoot "RMT_030754.pdf")

    $f2025 = Find-AuditDocumentPdf -Tipo "FT A" -Number 200004335 -Fecha ([datetime]"2025-06-02") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $f2025.Estado "Factura 2025 encontrada por anio"
    Assert-Equal "PDF_OK" $f2025.EstadoDocumento "Factura encontrada usa estado documental canonico"
    Assert-True ($f2025.Path -like "*2025*FT A*") "Factura 2025 usa ruta esperada"

    $f2026 = Find-AuditDocumentPdf -Tipo "FTS A" -Number 200004460 -Fecha ([datetime]"2026-07-30") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $f2026.Estado "FTS A 2026 encontrada"
    Assert-True ($f2026.Path -like "*2026*FTS A*") "FTS A prioriza carpeta del tipo"

    $f2027 = Find-AuditDocumentPdf -Tipo "FT A" -Number 200005001 -Fecha ([datetime]"2027-01-05") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $f2027.Estado "Carpeta futura 2027 encontrada sin cambiar codigo"

    $nc = Find-AuditDocumentPdf -Tipo "NC A" -Number 200000125 -Fecha ([datetime]"2026-07-30") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $nc.Estado "Nota de credito encontrada"

    $old = Find-AuditDocumentPdf -Tipo "FT A" -Number 200003000 -Fecha ([datetime]"2024-01-01") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $old.Estado "Historico en ANTIGUAS encontrado por fallback"

    $missing = Find-AuditDocumentPdf -Tipo "FT A" -Number 200009999 -Fecha ([datetime]"2026-01-01") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "FALTANTE" $missing.Estado "PDF inexistente no devuelve otro comprobante"
    Assert-Equal "PDF_NO_ENCONTRADO" $missing.EstadoDocumento "PDF inexistente se distingue de raiz inaccesible"

    $unavailable = Find-AuditDocumentPdf -Tipo "FT A" -Number 200009999 -Fecha ([datetime]"2026-01-01") -PdfBaseRoot (Join-Path $tmp "RAIZ_INEXISTENTE") -RemitosRoot $rmtRoot
    Assert-Equal "RAIZ_INACCESIBLE" $unavailable.EstadoDocumento "Raiz inaccesible no se informa como PDF faltante"

    New-TestFile (Join-Path $factRoot "2026\FT A\FTA00002_00003000.pdf")
    $ambiguous = Find-AuditDocumentPdf -Tipo "FT A" -Number 200003000 -Fecha ([datetime]"2024-01-01") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "PDF_AMBIGUO" $ambiguous.Estado "Coincidencia ambigua rechazada"
    Assert-Equal "PDF_AMBIGUO" $ambiguous.EstadoDocumento "Coincidencia ambigua usa estado documental canonico"

    $rmt = Find-AuditDocumentPdf -Tipo "RMT" -Number 30754 -Fecha ([datetime]"2026-08-13") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "ENCONTRADO" $rmt.Estado "RMT_030754 encontrado"
    Assert-Equal "RMT_030754.pdf" ([IO.Path]::GetFileName($rmt.Path)) "RMT tolera ceros a la izquierda"

    $noRmt = Find-AuditDocumentPdf -Tipo "RMT" -Number 30999 -Fecha ([datetime]"2026-08-13") -PdfBaseRoot $factRoot -RemitosRoot $rmtRoot
    Assert-Equal "PDF_REMITO_NO_ENCONTRADO" $noRmt.Estado "RMT inexistente informa estado especifico"

    $raw = @"
NºREMITO: 030754 FECHA: 13/08/2026
NOMBRE: CLIENTE_TEST_095
TOTAL: $ 54.000,00
3 Mtr ARENA FINA 18000 54000
"@
    $pdfData = Get-AuditRemitoPdfData $raw
    $comprobante = [pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; Cliente = "CLIENTE_TEST_095"; IMPORTE = [decimal]54000 }
    $detalle = [pscustomobject]@{ PRODUCTO = "ARENA FINA"; CANTIDAD = [decimal]3; PUNITARIO = [decimal]18000; Subtotal = [decimal]54000 }
    $ok = Compare-AuditRemitoPdf -Comprobante $comprobante -Detalles @($detalle) -PdfData $pdfData
    Assert-Equal "OK" $ok.Estado "RMT correcto devuelve OK"

    $badQty = Compare-AuditRemitoPdf -Comprobante $comprobante -Detalles @([pscustomobject]@{ PRODUCTO = "ARENA FINA"; CANTIDAD = [decimal]2; PUNITARIO = [decimal]18000; Subtotal = [decimal]54000 }) -PdfData $pdfData
    Assert-True ($badQty.Alerta -like "*CANTIDAD_DIFERENTE*") "RMT detecta cantidad diferente"

    $badPrice = Compare-AuditRemitoPdf -Comprobante $comprobante -Detalles @([pscustomobject]@{ PRODUCTO = "ARENA FINA"; CANTIDAD = [decimal]3; PUNITARIO = [decimal]17000; Subtotal = [decimal]54000 }) -PdfData $pdfData
    Assert-True ($badPrice.Alerta -like "*PRECIO_DIFERENTE*") "RMT detecta precio diferente"

    $badClient = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; Cliente = "OTRO CLIENTE"; IMPORTE = [decimal]54000 }) -Detalles @($detalle) -PdfData $pdfData
    Assert-True ($badClient.Alerta -like "*CLIENTE_DIFERENTE*") "RMT detecta cliente diferente"

    $rmt30801Data = Get-AuditRemitoPdfData ($raw -replace '030754', '030801' -replace 'CLIENTE_TEST_095', 'CLIENTE DEMOSTRACION TRUN')
    $rmt30801 = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30801; FECHA = [datetime]"2026-08-13"; IdCLIENTE = 349; Cliente = "Cliente  Demostracion Truncado"; IMPORTE = [decimal]54000 }) -Detalles @($detalle) -PdfData $rmt30801Data
    Assert-True ($rmt30801.Alerta -notlike "*CLIENTE_DIFERENTE*") "RMT 30801 acepta nombre normalizado truncado"
    $nombreConTilde = ([char]0x00C1) + "ridos, del  Sur S.A."
    Assert-True (Test-AuditDocumentClientNameMatch $nombreConTilde "aridos del sur") "Nombre ignora tildes, puntuacion y espacios dobles"
    Assert-True (Test-AuditDocumentClientNameMatch "CLIENTE TRUNC" "Cliente Truncado S.A.") "Truncamiento inverso controlado"

    $similarButDifferent = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30801; FECHA = [datetime]"2026-08-13"; IdCLIENTE = 349; Cliente = "CLIENTE DEMOSTRACION OTRO"; IMPORTE = [decimal]54000 }) -Detalles @($detalle) -PdfData $rmt30801Data
    Assert-True ($similarButDifferent.Alerta -like "*CLIENTE_DIFERENTE*") "Nombre parecido pero no truncado sigue alertando"

    $identifiedData = Get-AuditRemitoPdfData ($raw -replace 'NOMBRE: CLIENTE_TEST_095', "CODIGO CLIENTE: 349`r`nNOMBRE: NOMBRE SECUNDARIO")
    Assert-Equal 349 $identifiedData.IdCliente "RMT extrae identificador de cliente"
    $sameId = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; IdCLIENTE = 349; Cliente = "NOMBRE ACCESS"; IMPORTE = [decimal]54000 }) -Detalles @($detalle) -PdfData $identifiedData
    Assert-True ($sameId.Alerta -notlike "*CLIENTE_DIFERENTE*") "IdCLIENTE coincidente es criterio principal"

    $differentId = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; IdCLIENTE = 350; Cliente = "NOMBRE SECUNDARIO"; IMPORTE = [decimal]54000 }) -Detalles @($detalle) -PdfData $identifiedData
    Assert-True ($differentId.Alerta -like "*CLIENTE_DIFERENTE*") "IdCLIENTE distinto alerta aunque coincida el nombre"

    $badAmount = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; Cliente = "CLIENTE_TEST_095"; IMPORTE = [decimal]53000 }) -Detalles @($detalle) -PdfData $pdfData
    Assert-True ($badAmount.Alerta -like "*IMPORTE_DIFERENTE*") "RMT detecta importe diferente"

    $multiRaw = @"
NºREMITO: 030754 FECHA: 13/08/2026
NOMBRE: CLIENTE_TEST_095
TOTAL: $ 84.000,00
3 Mtr ARENA FINA 18000 54000
2 Mtr GRANZA 5/8 15000 30000
"@
    $multiData = Get-AuditRemitoPdfData $multiRaw
    $multiCheck = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30754; FECHA = [datetime]"2026-08-13"; Cliente = "CLIENTE_TEST_095"; IMPORTE = [decimal]84000 }) -Detalles @(
        [pscustomobject]@{ PRODUCTO = "ARENA FINA"; CANTIDAD = [decimal]3; PUNITARIO = [decimal]18000; Subtotal = [decimal]54000 },
        [pscustomobject]@{ PRODUCTO = "GRANZA 5/8"; CANTIDAD = [decimal]2; PUNITARIO = [decimal]15000; Subtotal = [decimal]30000 }
    ) -PdfData $multiData
    Assert-Equal "OK" $multiCheck.Estado "RMT multiproducto correcto"

    $rmt30767Raw = @"
NºREMITO: 030767 FECHA: 20/08/2026
NOMBRE: CLIENTE_TEST_1451
TOTAL: $ 77.600,00
1 1200 BOLSON GRAVA 2-4 mm 51700 51700
2 Und. BENTONITA LA ELCHA 12950 25900
"@
    $rmt30767Data = Get-AuditRemitoPdfData $rmt30767Raw
    Assert-Equal 2 @($rmt30767Data.Items).Count "RMT 30767 detecta ambas lineas"
    Assert-Equal "UND" $rmt30767Data.Items[1].Unidad "RMT normaliza unidad con punto final"
    foreach ($unidad in @("Und", "Und.", "UND", "UND.", "Unid", "Unid.")) {
        $unidadData = Get-AuditRemitoPdfData "1 $unidad PRODUCTO GENERICO 100 100"
        Assert-Equal 1 @($unidadData.Items).Count "RMT acepta unidad $unidad"
    }
    Assert-Equal 0 @((Get-AuditRemitoPdfData "OBSERVACION Und. SIN IMPORTES").Items).Count "RMT no captura texto ajeno al detalle"
    $rmt30767Check = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30767; FECHA = [datetime]"2026-08-20"; Cliente = "CLIENTE_TEST_1451"; IMPORTE = [decimal]77600 }) -Detalles @(
        [pscustomobject]@{ PRODUCTO = "BOLSON GRAVA 2-4 mm"; CANTIDAD = [decimal]1; PUNITARIO = [decimal]51700; Subtotal = [decimal]51700 },
        [pscustomobject]@{ PRODUCTO = "BENTONITA LA ELCHA"; CANTIDAD = [decimal]2; PUNITARIO = [decimal]12950; Subtotal = [decimal]25900 }
    ) -PdfData $rmt30767Data
    Assert-Equal "OK" $rmt30767Check.Estado "RMT 30767 sin falso DETALLE_DIFERENTE"

    $rmt30767MissingLine = Compare-AuditRemitoPdf -Comprobante ([pscustomobject]@{ TIPO = "RMT"; Numero = 30767; FECHA = [datetime]"2026-08-20"; Cliente = "CLIENTE_TEST_1451"; IMPORTE = [decimal]77600 }) -Detalles @(
        [pscustomobject]@{ PRODUCTO = "BOLSON GRAVA 2-4 mm"; CANTIDAD = [decimal]1; PUNITARIO = [decimal]51700; Subtotal = [decimal]51700 }
    ) -PdfData $rmt30767Data
    Assert-True ($rmt30767MissingLine.Alerta -like "*DETALLE_DIFERENTE*") "RMT con diferencia real de lineas sigue alertando"

    Write-Host "PRUEBAS COMPLETADAS: localizador historico, identidad de cliente y auditoria RMT."
}
finally {
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Recurse -Force
    }
}
