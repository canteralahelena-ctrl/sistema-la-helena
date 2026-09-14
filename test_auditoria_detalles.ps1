$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "auditoria_detalles.ps1")

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ([string]$Expected -ne [string]$Actual) {
        throw "$Name - esperado: '$Expected'; obtenido: '$Actual'"
    }
    Write-Host "OK - $Name"
}

function New-Header([int]$Id, [string]$Tipo = "RMT", [int]$Numero = 30715, [int]$Cliente = 1) {
    [pscustomobject]@{
        IdCOMPROVANTE = $Id
        TIPO = $Tipo
        Numero = $Numero
        IdCLIENTE = $Cliente
        UserID = 3
        FECHA = [datetime]"2026-08-05"
    }
}

function New-Detail([int]$HeaderId, [int]$DetalleHeaderId, [string]$Tipo = "RMT", [int]$Numero = 30715, [int]$IdDet = 1) {
    [pscustomobject]@{
        IdCOMPROVANTE = $HeaderId
        TIPO = $Tipo
        Numero = $Numero
        IdDET = $IdDet
        IdCOMPROVANTE_DETALLE = $DetalleHeaderId
        PRODUCTO = "ARENA ZARANDEADA"
        CANTIDAD = 100
        PUNITARIO = 0
        Subtotal = 300000
    }
}

$normal = Resolve-ComprobanteDetalle `
    -Comprobantes @(New-Header 1 "RMT" 1) `
    -DetallesEstructurados @(New-Detail 1 1 "RMT" 1 10) `
    -DetallesLegacyCandidatos @() `
    -TodosEncabezados @(New-Header 1 "RMT" 1)
Assert-Equal 1 @($normal.Detalles).Count "Relacion normal por Id/FK"
Assert-Equal "ID_COMPROVANTE" $normal.Resoluciones["1"].Metodo "Metodo normal por Id/FK"

$legacy = Resolve-ComprobanteDetalle `
    -Comprobantes @(New-Header 44648 "RMT" 30715) `
    -DetallesEstructurados @() `
    -DetallesLegacyCandidatos @(New-Detail 44648 44647 "RMT" 30715 55496) `
    -TodosEncabezados @(New-Header 44648 "RMT" 30715)
Assert-Equal 1 @($legacy.Detalles).Count "RMT 30715 con desfasaje real"
Assert-Equal "LEGACY_TIPO_NUMERO_VALIDADO" $legacy.Resoluciones["44648"].Metodo "TIPO+Numero unico legacy permitido"

$duplicateHeaders = Resolve-ComprobanteDetalle `
    -Comprobantes @(New-Header 1 "RMT" 10) `
    -DetallesEstructurados @() `
    -DetallesLegacyCandidatos @(New-Detail 1 999 "RMT" 10 20) `
    -TodosEncabezados @((New-Header 1 "RMT" 10), (New-Header 2 "RMT" 10))
Assert-Equal "DETALLE_COMPROBANTE_AMBIGUO" $duplicateHeaders.Resoluciones["1"].Estado "Dos encabezados mismo TIPO+Numero rechazado"
Assert-Equal 0 @($duplicateHeaders.Detalles).Count "Ambiguedad de encabezado no asocia detalle"

$ambiguousDetail = Resolve-ComprobanteDetalle `
    -Comprobantes @((New-Header 1 "RMT" 10), (New-Header 2 "RMT" 11)) `
    -DetallesEstructurados @() `
    -DetallesLegacyCandidatos @((New-Detail 1 999 "RMT" 10 30), (New-Detail 2 999 "RMT" 11 30)) `
    -TodosEncabezados @((New-Header 1 "RMT" 10), (New-Header 2 "RMT" 11))
Assert-Equal "DETALLE_COMPROBANTE_AMBIGUO" $ambiguousDetail.Resoluciones["1"].Estado "Detalle ambiguo rechazado"

$sameClientDate = Resolve-ComprobanteDetalle `
    -Comprobantes @(New-Header 1 "RMT" 10 183) `
    -DetallesEstructurados @() `
    -DetallesLegacyCandidatos @(New-Detail 1 999 "RMT" 11 40) `
    -TodosEncabezados @(New-Header 1 "RMT" 10 183)
Assert-Equal "SIN_DETALLE" $sameClientDate.Resoluciones["1"].Estado "Mismo cliente/fecha pero otro comprobante no asocia"

$consecutiveIds = Resolve-ComprobanteDetalle `
    -Comprobantes @(New-Header 101 "RMT" 10) `
    -DetallesEstructurados @() `
    -DetallesLegacyCandidatos @() `
    -TodosEncabezados @((New-Header 101 "RMT" 10), (New-Header 100 "RMT" 9))
Assert-Equal "SIN_DETALLE" $consecutiveIds.Resoluciones["101"].Estado "IDs consecutivos sin relacion no asocian"

$anuladoSinDetalle = Get-AuditDetalleComparisonDecision -EsAnulado $true -DetallesResueltos @() -CantidadLegacy 2
Assert-Equal $false $anuladoSinDetalle.PuedeComparar "Anulado sin detalle no se compara"
Assert-Equal "" $anuladoSinDetalle.Estado "Anulado conserva prioridad sobre alerta de detalle"

$detalleNoResuelto = Get-AuditDetalleComparisonDecision -EsAnulado $false -DetallesResueltos @() -CantidadLegacy 2
Assert-Equal $false $detalleNoResuelto.PuedeComparar "Detalle fisico no resuelto no se compara"
Assert-Equal "DETALLE_NO_RESUELTO" $detalleNoResuelto.Estado "Detalle fisico no resuelto queda visible"

$sinDetalle = Get-AuditDetalleComparisonDecision -EsAnulado $false -DetallesResueltos @()
Assert-Equal $false $sinDetalle.PuedeComparar "Cero detalles no se compara"
Assert-Equal "SIN_DETALLE_EN_ACCESS" $sinDetalle.Estado "Cero detalles queda visible sin excepcion"

$conDetalle = Get-AuditDetalleComparisonDecision -EsAnulado $false -DetallesResueltos @(New-Detail 1 1)
Assert-Equal $true $conDetalle.PuedeComparar "Detalle valido habilita comparacion"

Write-Host "PRUEBAS COMPLETADAS: resolucion controlada de detalle."
