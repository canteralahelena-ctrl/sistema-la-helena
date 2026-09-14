function Test-AuditComprobanteAnulado {
    param([object[]]$Detalles)

    return @($Detalles | Where-Object {
        ([string]$_.PRODUCTO).Trim().ToUpperInvariant() -match '^ANULADO(?:\s|$)'
    }).Count -gt 0
}

function Get-AuditComprobantesAnulados {
    param(
        [hashtable]$DetallesPorComprobante,
        [object[]]$DetallesLegacyCandidatos = @(),
        [object[]]$TodosEncabezados = @()
    )

    $result = @{}
    foreach ($detalleKey in $DetallesPorComprobante.Keys) {
        if (Test-AuditComprobanteAnulado @($DetallesPorComprobante[$detalleKey])) {
            $result[[string]$detalleKey] = $true
        }
    }

    foreach ($legacy in @($DetallesLegacyCandidatos | Where-Object {
        Test-AuditComprobanteAnulado @($_)
    })) {
        $tipo = ([string]$legacy.TIPO).Trim().ToUpperInvariant()
        $numero = if ($null -eq $legacy.Numero -or $legacy.Numero -is [System.DBNull]) { "" } else { [string]([int64]$legacy.Numero) }
        if (-not $tipo -or -not $numero) { continue }

        [array]$headers = @($TodosEncabezados | Where-Object {
            ([string]$_.TIPO).Trim().ToUpperInvariant() -eq $tipo -and
            $null -ne $_.Numero -and -not ($_.Numero -is [System.DBNull]) -and
            [string]([int64]$_.Numero) -eq $numero
        })
        if ($headers.Count -ne 1) { continue }

        $headerId = [string]([int]$headers[0].IdCOMPROVANTE)
        if ($headerId -eq [string]([int]$legacy.IdCOMPROVANTE)) {
            $result[$headerId] = $true
        }
    }

    return $result
}

function Resolve-AuditComprobanteSaldo {
    param(
        [bool]$EsAnulado,
        [object]$Saldo,
        [int]$IdCOMPROVANTE,
        [Parameter(Mandatory = $true)]
        [scriptblock]$ResolverActivo
    )

    if ($EsAnulado) {
        return [pscustomobject]@{
            Valor = $null
            Estado = "NO_COMPARADO_ANULADA"
            Diagnostico = ""
        }
    }

    return & $ResolverActivo $Saldo $IdCOMPROVANTE
}

function Get-AuditPdfAmountResult {
    param(
        [bool]$EsAnulado,
        [bool]$EsNotaCredito,
        [bool]$PdfLeido,
        [object]$ImporteSistema,
        [object]$ImportePdf,
        [string]$ErrorLectura = ""
    )

    if ($EsAnulado) {
        return [pscustomobject]@{
            PdfTotalEstado = "NO_COMPARADO_ANULADA"
            PdfDiferencia = $null
            Alerta = ""
        }
    }

    if (-not $PdfLeido) {
        $prefix = if ($EsNotaCredito) { "NC_PDF_NO_LEIDO" } else { "NO_LEIDO" }
        return [pscustomobject]@{
            PdfTotalEstado = "$prefix`: $ErrorLectura"
            PdfDiferencia = $null
            Alerta = ""
        }
    }

    if ($EsNotaCredito) {
        return [pscustomobject]@{
            PdfTotalEstado = "NC_REVISION_ADMINISTRATIVA"
            PdfDiferencia = $null
            Alerta = ""
        }
    }

    $diferencia = [decimal]$ImporteSistema - [decimal]$ImportePdf
    if ([math]::Abs([double]$diferencia) -le 1.0) {
        return [pscustomobject]@{
            PdfTotalEstado = "OK"
            PdfDiferencia = $diferencia
            Alerta = ""
        }
    }

    return [pscustomobject]@{
        PdfTotalEstado = "DIFERENTE"
        PdfDiferencia = $diferencia
        Alerta = "IMPORTE_PDF_DIFERENTE"
    }
}

function Resolve-AuditAnulacionState {
    param(
        [bool]$EsAnulado,
        [object[]]$NotasCreditoVinculadas = @(),
        [Alias("HayNcMismoClienteNoVinculada")]
        [bool]$HayNcPosibleNoVinculada = $false
    )

    if (-not $EsAnulado) { return $null }

    $exclusion = "Comprobante excluido de controles de saldo/cobranza."

    [array]$linked = @($NotasCreditoVinculadas)
    if ($linked.Count -gt 0) {
        $details = @($linked | ForEach-Object {
            $parts = @("$($_.TipoNC) $($_.NumeroNC)")
            if ($_.FechaNC) { $parts += "Fecha: $($_.FechaNC)" }
            if ($null -ne $_.ImporteNC -and [string]$_.ImporteNC -ne "") { $parts += "Importe: $($_.ImporteNC)" }
            if ($_.ComprobanteReferenciado) { $parts += "Factura referenciada: $($_.ComprobanteReferenciado)" }
            $parts -join " | "
        })
        return [pscustomobject]@{
            Estado = "ANULADA CON NC"
            Observacion = ("$exclusion VERIFICAR POR QU{0} FUE ANULADA." -f [char]0x00C9)
            NotaCreditoRelacionada = ($details -join " || ")
        }
    }

    if ($HayNcPosibleNoVinculada) {
        return [pscustomobject]@{
            Estado = ("ANULADA {0} NC NO VINCULADA AUTOM{1}TICAMENTE" -f [char]0x2014, [char]0x00C1)
            Observacion = ("$exclusion VERIFICAR ANULACI{0}N." -f [char]0x00D3)
            NotaCreditoRelacionada = ""
        }
    }

    return [pscustomobject]@{
        Estado = "ANULADA SIN NC"
        Observacion = ("$exclusion VERIFICAR ANULACI{0}N." -f [char]0x00D3)
        NotaCreditoRelacionada = ""
    }
}

function Get-AuditComprobanteLetter([string]$Tipo) {
    $normalized = ([string]$Tipo).Trim().ToUpperInvariant()
    if ($normalized -match '\bB\b' -or $normalized -like '* B') { return "B" }
    if ($normalized -match '\bA\b' -or $normalized -like '* A') { return "A" }
    return ""
}

function Format-AuditAccessNumber([int]$Number) {
    $point = [math]::Floor($Number / 100000000)
    $sequence = $Number % 100000000
    return "{0:00000}-{1:00000000}" -f $point, $sequence
}

function Get-AuditNcPdfReference([string]$Text) {
    if (-not $Text) {
        return [pscustomobject]@{ Found = $false; Letter = ""; Point = $null; Seq = $null; NumeroAccess = $null; Display = ""; Raw = "" }
    }

    $patterns = @(
        "(?i)\bFac(?:tura)?\.?\s*([AB])?\s*[:#]?\s*(\d{4,5})\s*[-_]\s*(\d{6,9})",
        "(?i)\bComprobante\s+Asoc(?:iado)?\.?\s*[:#]?\s*(?:Fac(?:tura)?\.?\s*)?([AB])?\s*(\d{4,5})\s*[-_]\s*(\d{6,9})",
        "(?i)\bCbte\.?\s+Asoc(?:iado)?\.?\s*[:#]?\s*(?:Fac(?:tura)?\.?\s*)?([AB])?\s*(\d{4,5})\s*[-_]\s*(\d{6,9})"
    )
    foreach ($pattern in $patterns) {
        $match = [regex]::Match($Text, $pattern)
        if (-not $match.Success) { continue }
        $letter = $match.Groups[1].Value.ToUpperInvariant()
        $point = [int]$match.Groups[2].Value
        $sequence = [int]$match.Groups[3].Value
        $accessNumber = ($point * 100000000) + $sequence
        $label = if ($letter) { "Factura $letter" } else { "Factura" }
        return [pscustomobject]@{
            Found = $true
            Letter = $letter
            Point = $point
            Seq = $sequence
            NumeroAccess = $accessNumber
            Display = "$label $(Format-AuditAccessNumber $accessNumber)"
            Raw = $match.Value.Trim()
        }
    }
    return [pscustomobject]@{ Found = $false; Letter = ""; Point = $null; Seq = $null; NumeroAccess = $null; Display = ""; Raw = "" }
}

function Find-AuditReferencedComprobante {
    param([object]$Reference, [object[]]$Documentos)

    if (-not $Reference -or -not $Reference.Found) { return $null }
    [array]$matches = @($Documentos | Where-Object {
        $tipo = ([string]$_.TIPO).Trim().ToUpperInvariant()
        $isCreditNote = $tipo -match '^NC' -or $tipo -like 'NOTA*CREDITO*'
        -not $isCreditNote -and [int64]$_.Numero -eq [int64]$Reference.NumeroAccess
    })
    if ($Reference.Letter) {
        $matches = @($matches | Where-Object { (Get-AuditComprobanteLetter $_.TIPO) -eq $Reference.Letter })
    }
    $matches = @($matches | Sort-Object IdCOMPROVANTE -Unique)
    if ($matches.Count -ne 1) { return $null }
    return $matches[0]
}
