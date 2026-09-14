$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "auditoria_anulados.ps1")

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ([string]$Expected -ne [string]$Actual) {
        throw "$Name - esperado: '$Expected'; obtenido: '$Actual'"
    }
    Write-Host "OK - $Name"
}

function Assert-Null($Actual, [string]$Name) {
    if ($null -ne $Actual) { throw "$Name - esperado: null; obtenido: '$Actual'" }
    Write-Host "OK - $Name"
}

$activeDifferent = Get-AuditPdfAmountResult -EsAnulado $false -EsNotaCredito $false -PdfLeido $true -ImporteSistema 100 -ImportePdf 120
Assert-Equal "DIFERENTE" $activeDifferent.PdfTotalEstado "Factura activa mantiene diferencia PDF"
Assert-Equal "IMPORTE_PDF_DIFERENTE" $activeDifferent.Alerta "Factura activa mantiene alerta monetaria"

$cancelledPdf = Get-AuditPdfAmountResult -EsAnulado $true -EsNotaCredito $false -PdfLeido $true -ImporteSistema 0 -ImportePdf 562650
Assert-Equal "NO_COMPARADO_ANULADA" $cancelledPdf.PdfTotalEstado "Factura anulada omite comparacion monetaria"
Assert-Equal "" $cancelledPdf.Alerta "Factura anulada no genera diferencia PDF"
Assert-Null $cancelledPdf.PdfDiferencia "Factura anulada no calcula diferencia"

$linkedNc = [pscustomobject]@{
    TipoNC = "NCS A"
    NumeroNC = "00002-00000125"
    FechaNC = "30/07/2026"
    ImporteNC = '$ 562.650,00'
    ComprobanteReferenciado = "Factura A 00002-00004460"
}
$cancelledWithNc = Resolve-AuditAnulacionState -EsAnulado $true -NotasCreditoVinculadas @($linkedNc)
Assert-Equal "ANULADA CON NC" $cancelledWithNc.Estado "Factura anulada con NC vinculada"
Assert-Equal ("Comprobante excluido de controles de saldo/cobranza. VERIFICAR POR QU{0} FUE ANULADA." -f [char]0x00C9) $cancelledWithNc.Observacion "Observacion de anulacion con NC"
Assert-Equal $true ($cancelledWithNc.NotaCreditoRelacionada -like "*NCS A 00002-00000125*Factura A 00002-00004460*") "Datos de NC vinculada incluidos"

$cancelledWithoutNc = Resolve-AuditAnulacionState -EsAnulado $true -NotasCreditoVinculadas @()
Assert-Equal "ANULADA SIN NC" $cancelledWithoutNc.Estado "Factura anulada sin NC"
Assert-Equal ("Comprobante excluido de controles de saldo/cobranza. VERIFICAR ANULACI{0}N." -f [char]0x00D3) $cancelledWithoutNc.Observacion "Observacion de anulacion sin NC"

$sameClientUnlinked = Resolve-AuditAnulacionState -EsAnulado $true -NotasCreditoVinculadas @() -HayNcPosibleNoVinculada $true
Assert-Equal ("ANULADA {0} NC NO VINCULADA AUTOM{1}TICAMENTE" -f [char]0x2014, [char]0x00C1) $sameClientUnlinked.Estado "NC del mismo cliente no se vincula automaticamente"
Assert-Equal "" $sameClientUnlinked.NotaCreditoRelacionada "NC no vinculada no se presenta como relacionada"

$activeOk = Get-AuditPdfAmountResult -EsAnulado $false -EsNotaCredito $false -PdfLeido $true -ImporteSistema 100 -ImportePdf 100
Assert-Equal "OK" $activeOk.PdfTotalEstado "Factura activa correcta continua OK"
Assert-Equal "" $activeOk.Alerta "Factura activa correcta sin alerta"

$detected = Test-AuditComprobanteAnulado @([pscustomobject]@{ PRODUCTO = " ANULADO " })
Assert-Equal $true $detected "Marcador explicito ANULADO detectado"
$detectedWithNote = Test-AuditComprobanteAnulado @([pscustomobject]@{ PRODUCTO = "anulado con fact 4528" })
Assert-Equal $true $detectedWithNote "Marcador ANULADO con observacion detectado"
$notDetected = Test-AuditComprobanteAnulado @([pscustomobject]@{ PRODUCTO = "GRANZA 5/8" })
Assert-Equal $false $notDetected "Producto normal no se considera anulado"

$regressionAnulados = Get-AuditComprobantesAnulados `
    -DetallesPorComprobante @{ "44812" = @([pscustomobject]@{ PRODUCTO = "GRANCILLA" }) } `
    -DetallesLegacyCandidatos @([pscustomobject]@{ IdCOMPROVANTE = 44812; TIPO = "RMT"; Numero = 30814; PRODUCTO = "anulado con fact 4528" }) `
    -TodosEncabezados @([pscustomobject]@{ IdCOMPROVANTE = 44812; TIPO = "RMT"; Numero = 30814 })
Assert-Equal $true $regressionAnulados.ContainsKey("44812") "RMT 30814 detectado por marcador legacy inequivoco"

$ambiguousAnulados = Get-AuditComprobantesAnulados `
    -DetallesPorComprobante @{} `
    -DetallesLegacyCandidatos @([pscustomobject]@{ IdCOMPROVANTE = 44812; TIPO = "RMT"; Numero = 30814; PRODUCTO = "ANULADO" }) `
    -TodosEncabezados @(
        [pscustomobject]@{ IdCOMPROVANTE = 44812; TIPO = "RMT"; Numero = 30814 },
        [pscustomobject]@{ IdCOMPROVANTE = 99999; TIPO = "RMT"; Numero = 30814 }
    )
Assert-Equal $false $ambiguousAnulados.ContainsKey("44812") "Marcador legacy ambiguo no se vincula"

$saldoAnulado = Resolve-AuditComprobanteSaldo `
    -EsAnulado $true `
    -Saldo ([System.DBNull]::Value) `
    -IdCOMPROVANTE 44812 `
    -ResolverActivo { throw "El saldo anulado no debe validarse" }
Assert-Equal "NO_COMPARADO_ANULADA" $saldoAnulado.Estado "SALDO NULL anulado no bloquea"
Assert-Null $saldoAnulado.Valor "SALDO NULL anulado no genera falsa deuda"

$reference = Get-AuditNcPdfReference "Factura A 00002-00004460"
Assert-Equal $true $reference.Found "Referencia exacta de factura detectada en PDF de NC"
Assert-Equal "A" $reference.Letter "Letra de factura referenciada"
Assert-Equal 200004460 $reference.NumeroAccess "Numero Access de FTS A 200004460"

$documents = @(
    [pscustomobject]@{ IdCOMPROVANTE = 44603; TIPO = "FTS A"; Numero = 200004460 },
    [pscustomobject]@{ IdCOMPROVANTE = 44604; TIPO = "NCS A"; Numero = 200000125 }
)
$referencedDocument = Find-AuditReferencedComprobante -Reference $reference -Documentos $documents
Assert-Equal 44603 $referencedDocument.IdCOMPROVANTE "Caso real vincula la factura exacta"

$ambiguous = Find-AuditReferencedComprobante -Reference $reference -Documentos @(
    [pscustomobject]@{ IdCOMPROVANTE = 44603; TIPO = "FTS A"; Numero = 200004460 },
    [pscustomobject]@{ IdCOMPROVANTE = 99999; TIPO = "FT A"; Numero = 200004460 }
)
Assert-Null $ambiguous "Referencia ambigua no se vincula automaticamente"

Write-Host "PRUEBAS COMPLETADAS: prioridad de anulacion, SALDO NULL, RMT 30814 y vinculo explicito."
