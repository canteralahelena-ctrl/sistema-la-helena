$ErrorActionPreference = "Stop"

function Normalize-AuditDetalleTipo([object]$Value) {
    return ([string]$Value).Trim().ToUpperInvariant()
}

function Normalize-AuditDetalleNumero([object]$Value) {
    if ($null -eq $Value -or $Value -is [System.DBNull] -or [string]$Value -eq "") { return "" }
    return [string]([int64]$Value)
}

function Get-AuditDetalleFunctionalKey([object]$Tipo, [object]$Numero) {
    $tipoKey = Normalize-AuditDetalleTipo $Tipo
    $numeroKey = Normalize-AuditDetalleNumero $Numero
    if (-not $tipoKey -or -not $numeroKey) { return "" }
    return "$tipoKey|$numeroKey"
}

function Resolve-ComprobanteDetalle {
    param(
        [array]$Comprobantes,
        [array]$DetallesEstructurados,
        [array]$DetallesLegacyCandidatos,
        [array]$TodosEncabezados
    )

    $headerIds = @{}
    $headersByFunctionalKey = @{}
    foreach ($h in $TodosEncabezados) {
        if ($null -ne $h.IdCOMPROVANTE -and -not ($h.IdCOMPROVANTE -is [System.DBNull])) {
            $headerIds[[string]([int]$h.IdCOMPROVANTE)] = $true
        }
        $key = Get-AuditDetalleFunctionalKey $h.TIPO $h.Numero
        if (-not $key) { continue }
        if (-not $headersByFunctionalKey.ContainsKey($key)) {
            $headersByFunctionalKey[$key] = @()
        }
        $headersByFunctionalKey[$key] = @($headersByFunctionalKey[$key]) + @($h)
    }

    $structuredByHeader = @{}
    foreach ($d in $DetallesEstructurados) {
        $id = [string]([int]$d.IdCOMPROVANTE)
        if (-not $structuredByHeader.ContainsKey($id)) {
            $structuredByHeader[$id] = @()
        }
        $d | Add-Member -NotePropertyName ResolucionDetalle -NotePropertyValue "ID_COMPROVANTE" -Force
        $structuredByHeader[$id] = @($structuredByHeader[$id]) + @($d)
    }

    $legacyByHeader = @{}
    $legacyOwnersByDetail = @{}
    foreach ($d in $DetallesLegacyCandidatos) {
        $id = [string]([int]$d.IdCOMPROVANTE)
        if (-not $legacyByHeader.ContainsKey($id)) {
            $legacyByHeader[$id] = @()
        }
        $legacyByHeader[$id] = @($legacyByHeader[$id]) + @($d)

        $detailId = [string]$d.IdDET
        if ($detailId) {
            if (-not $legacyOwnersByDetail.ContainsKey($detailId)) {
                $legacyOwnersByDetail[$detailId] = @{}
            }
            $legacyOwnersByDetail[$detailId][$id] = $true
        }
    }

    $detalles = @()
    $resoluciones = @{}

    foreach ($c in $Comprobantes) {
        $id = [string]([int]$c.IdCOMPROVANTE)
        if ($structuredByHeader.ContainsKey($id)) {
            $detalles += @($structuredByHeader[$id])
            $resoluciones[$id] = [pscustomobject]@{
                Estado = "OK"
                Metodo = "ID_COMPROVANTE"
                Mensaje = ""
            }
            continue
        }

        $key = Get-AuditDetalleFunctionalKey $c.TIPO $c.Numero
        if (-not $key -or -not $legacyByHeader.ContainsKey($id)) {
            $resoluciones[$id] = [pscustomobject]@{
                Estado = "SIN_DETALLE"
                Metodo = ""
                Mensaje = "No se encontraron lineas de detalle asociables."
            }
            continue
        }

        [array]$headersForKey = if ($headersByFunctionalKey.ContainsKey($key)) { @($headersByFunctionalKey[$key]) } else { @() }
        if ($headersForKey.Count -ne 1 -or [string]([int]$headersForKey[0].IdCOMPROVANTE) -ne $id) {
            $resoluciones[$id] = [pscustomobject]@{
                Estado = "DETALLE_COMPROBANTE_AMBIGUO"
                Metodo = "TIPO_NUMERO_RECHAZADO"
                Mensaje = "TIPO+Numero no identifica un unico encabezado."
            }
            continue
        }

        [array]$candidateLines = @($legacyByHeader[$id] | Where-Object {
            (Get-AuditDetalleFunctionalKey $_.TIPO $_.Numero) -eq $key
        })
        if ($candidateLines.Count -eq 0) {
            $resoluciones[$id] = [pscustomobject]@{
                Estado = "SIN_DETALLE"
                Metodo = ""
                Mensaje = "No se encontraron lineas de detalle asociables."
            }
            continue
        }

        $ambiguousDetail = $false
        foreach ($line in $candidateLines) {
            $detailId = [string]$line.IdDET
            if ($detailId -and $legacyOwnersByDetail.ContainsKey($detailId) -and $legacyOwnersByDetail[$detailId].Count -gt 1) {
                $ambiguousDetail = $true
                break
            }

            $detHeaderId = ""
            if ($null -ne $line.IdCOMPROVANTE_DETALLE -and -not ($line.IdCOMPROVANTE_DETALLE -is [System.DBNull]) -and [string]$line.IdCOMPROVANTE_DETALLE -ne "") {
                $detHeaderId = [string]([int]$line.IdCOMPROVANTE_DETALLE)
            }
            if ($detHeaderId -and $detHeaderId -ne $id -and $headerIds.ContainsKey($detHeaderId)) {
                $ambiguousDetail = $true
                break
            }
        }

        if ($ambiguousDetail) {
            $resoluciones[$id] = [pscustomobject]@{
                Estado = "DETALLE_COMPROBANTE_AMBIGUO"
                Metodo = "TIPO_NUMERO_RECHAZADO"
                Mensaje = "Las lineas candidatas tambien pueden pertenecer a otro encabezado."
            }
            continue
        }

        foreach ($line in $candidateLines) {
            $line | Add-Member -NotePropertyName ResolucionDetalle -NotePropertyValue "LEGACY_TIPO_NUMERO_VALIDADO" -Force
            $detalles += $line
        }
        $resoluciones[$id] = [pscustomobject]@{
            Estado = "OK"
            Metodo = "LEGACY_TIPO_NUMERO_VALIDADO"
            Mensaje = "TIPO+Numero unico sin ambiguedad de encabezado ni detalle."
        }
    }

    return [pscustomobject]@{
        Detalles = $detalles
        Resoluciones = $resoluciones
    }
}

function Get-AuditDetalleComparisonDecision {
    param(
        [bool]$EsAnulado,
        [object[]]$DetallesResueltos = @(),
        [int]$CantidadEstructurados = 0,
        [int]$CantidadLegacy = 0
    )

    if ($EsAnulado) {
        return [pscustomobject]@{ PuedeComparar = $false; Estado = ""; Observacion = "" }
    }

    if (@($DetallesResueltos | Where-Object { $null -ne $_ }).Count -gt 0) {
        return [pscustomobject]@{ PuedeComparar = $true; Estado = ""; Observacion = "" }
    }

    if (($CantidadEstructurados + $CantidadLegacy) -gt 0) {
        return [pscustomobject]@{
            PuedeComparar = $false
            Estado = "DETALLE_NO_RESUELTO"
            Observacion = "Existen lineas en Access pero no pudieron vincularse correctamente al comprobante. Revisar."
        }
    }

    return [pscustomobject]@{
        PuedeComparar = $false
        Estado = "SIN_DETALLE_EN_ACCESS"
        Observacion = "Comprobante sin lineas de detalle en Access. Revisar."
    }
}
