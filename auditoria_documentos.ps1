$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "access_hardening.ps1")
. (Join-Path $PSScriptRoot "normalizacion_unidades.ps1")

function Normalize-AuditDocumentTipo([object]$Value) {
    return (([string]$Value).Trim().ToUpperInvariant() -replace '\s+', ' ')
}

function Normalize-AuditDocumentText([object]$Value) {
    $text = ([string]$Value).Trim().ToUpperInvariant().Normalize([Text.NormalizationForm]::FormD)
    $builder = New-Object Text.StringBuilder
    foreach ($ch in $text.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($ch) -ne [Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$builder.Append($ch)
        }
    }
    return ($builder.ToString() -replace '[^A-Z0-9]+', ' ').Trim()
}

function Test-AuditDocumentClientNameMatch([object]$AccessName, [object]$PdfName) {
    $accessText = Normalize-AuditDocumentText $AccessName
    $pdfText = Normalize-AuditDocumentText $PdfName
    if (-not $accessText -or -not $pdfText) { return $false }
    return $accessText.StartsWith($pdfText, [StringComparison]::Ordinal) -or
        $pdfText.StartsWith($accessText, [StringComparison]::Ordinal)
}

function Convert-AuditDocumentDecimal([object]$Value) {
    return ConvertTo-HelenaDecimal -Value $Value -Field "PDF.NUMERICO" -NullPolicy "NULL" -Context "auditoria_documentos"
}

function Format-AuditDocumentMoney([decimal]$Value) {
    return $Value.ToString("C2", [Globalization.CultureInfo]::GetCultureInfo("es-AR"))
}

function Split-AuditAccessNumber([int]$Number) {
    $point = [math]::Floor($Number / 100000000)
    $seq = $Number % 100000000
    return [pscustomobject]@{ Point = [int]$point; Seq = [int]$seq }
}

function Get-AuditDocumentTypeFolders([string]$Tipo) {
    $t = Normalize-AuditDocumentTipo $Tipo
    switch ($t) {
        "FTS A" { return @("FTS A", "FT A") }
        "FT A" { return @("FT A", "FTS A") }
        "FTS B" { return @("FTS B", "FT B") }
        "FT B" { return @("FT B", "FTS B") }
        "FP A" { return @("FTP A", "FP A") }
        "FP B" { return @("FTP B", "FP B") }
        "NCS A" { return @("NC A", "NC ELECTRONICA", "NCP A") }
        "NC A" { return @("NC A", "NC ELECTRONICA", "NCP A") }
        "NCS B" { return @("NC B", "NC ELECTRONICA", "NCP B") }
        "NC B" { return @("NC B", "NC ELECTRONICA", "NCP B") }
        "ND A" { return @("ND A") }
        "ND B" { return @("ND B") }
        default { return @($t) }
    }
}

function Get-AuditDocumentPdfCandidates([string]$Tipo, [int]$Number) {
    $t = Normalize-AuditDocumentTipo $Tipo
    $n = Split-AuditAccessNumber $Number
    $point5 = "{0:00000}" -f $n.Point
    $point4 = "{0:0000}" -f $n.Point
    $seq8 = "{0:00000000}" -f $n.Seq
    $seq9 = "{0:000000000}" -f $n.Seq
    $seq6 = "{0:000000}" -f $n.Seq
    $folders = Get-AuditDocumentTypeFolders $t
    $names = @()

    if ($t -in @("FTS A", "FT A")) {
        $names += "FTA{0}_{1}.pdf" -f $point5, $seq8
    } elseif ($t -in @("FTS B", "FT B")) {
        $names += "FTB{0}_{1}.pdf" -f $point5, $seq8
    } elseif ($t -eq "FP A") {
        $names += "Factura A{0}_{1}.pdf" -f $point4, $seq9
        $names += "Factura A{0}_{1}.pdf" -f $point5, $seq8
        $names += "Factura A{0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -eq "FP B") {
        $names += "Factura B{0}_{1}.pdf" -f $point4, $seq9
        $names += "Factura B{0}_{1}.pdf" -f $point5, $seq8
        $names += "Factura B{0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -in @("NCS A", "NC A")) {
        $names += "NC A {0}_{1}.pdf" -f $point5, $seq8
        $names += "NC A {0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -in @("NCS B", "NC B")) {
        $names += "NC B{0}_{1}.pdf" -f $point5, $seq8
        $names += "NC B {0}_{1}.pdf" -f $point5, $seq8
        $names += "NC B{0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -eq "ND A") {
        $names += "ND A {0}_{1}.pdf" -f $point5, $seq8
        $names += "ND A {0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -eq "ND B") {
        $names += "ND B{0}_{1}.pdf" -f $point5, $seq8
        $names += "ND B {0}_{1}.pdf" -f $point5, $seq6
    } elseif ($t -eq "RMT") {
        $remito = "{0:000000}" -f $Number
        $names += "RMT_$remito.pdf"
        $names += "RMT_$Number.pdf"
    }

    $result = @()
    foreach ($folder in $folders) {
        foreach ($name in ($names | Select-Object -Unique)) {
            $result += [pscustomobject]@{ Tipo = $t; Folder = $folder; Name = $name }
        }
    }
    return $result
}

function Test-AuditDocumentCandidateName([string]$Tipo, [int]$Number, [string]$FileName) {
    $candidateNames = @(Get-AuditDocumentPdfCandidates $Tipo $Number | ForEach-Object { $_.Name.ToUpperInvariant() } | Select-Object -Unique)
    return $candidateNames -contains ([IO.Path]::GetFileName($FileName).ToUpperInvariant())
}

function Find-AuditDocumentPdf {
    param(
        [Parameter(Mandatory = $true)][string]$Tipo,
        [Parameter(Mandatory = $true)][int]$Number,
        [datetime]$Fecha = [datetime]"1900-01-01",
        [string]$PdfBaseRoot = "",
        [string]$PdfRoot = "",
        [string]$RemitosRoot = ""
    )

    $t = Normalize-AuditDocumentTipo $Tipo
    $candidates = @(Get-AuditDocumentPdfCandidates $t $Number)
    if ($candidates.Count -eq 0) {
        return [pscustomobject]@{ Estado = "NO_APLICA"; Path = ""; Candidato = ""; Carpeta = ""; Fuente = ""; Coincidencias = @() }
    }

    if ($t -eq "RMT") {
        $roots = @()
        if ($RemitosRoot) { $roots += $RemitosRoot }
        foreach ($rootItem in $roots) {
            foreach ($candidate in $candidates) {
                $path = Join-Path $rootItem $candidate.Name
                try {
                    if (Test-Path -LiteralPath $path) {
                        return [pscustomobject]@{ Estado = "ENCONTRADO"; EstadoDocumento = "PDF_OK"; Path = $path; Candidato = $candidate.Name; Carpeta = [IO.Path]::GetFileName($rootItem); Fuente = "DIRECTA_RMT"; Coincidencias = @($path) }
                    }
                } catch {
                    return [pscustomobject]@{ Estado = "RAIZ_INACCESIBLE"; EstadoDocumento = "RAIZ_INACCESIBLE"; Path = $path; Candidato = $candidate.Name; Carpeta = [IO.Path]::GetFileName($rootItem); Fuente = "DIRECTA_RMT"; Coincidencias = @() }
                }
            }
        }
        $matches = @()
        foreach ($rootItem in $roots) {
            try {
                $matches += @(Get-ChildItem -LiteralPath $rootItem -File -Filter "RMT_*.pdf" -Recurse -ErrorAction Stop | Where-Object {
                    Test-AuditDocumentCandidateName $t $Number $_.Name
                } | Select-Object -ExpandProperty FullName)
            } catch {
                return [pscustomobject]@{ Estado = "RAIZ_INACCESIBLE"; EstadoDocumento = "RAIZ_INACCESIBLE"; Path = $rootItem; Candidato = ""; Carpeta = ""; Fuente = "FALLBACK_RECURSIVO_RMT"; Coincidencias = @() }
            }
        }
        $unique = @($matches | Sort-Object -Unique)
        if ($unique.Count -eq 1) {
            return [pscustomobject]@{ Estado = "ENCONTRADO"; EstadoDocumento = "PDF_OK"; Path = $unique[0]; Candidato = [IO.Path]::GetFileName($unique[0]); Carpeta = [IO.Path]::GetDirectoryName($unique[0]); Fuente = "FALLBACK_RECURSIVO_RMT"; Coincidencias = $unique }
        }
        if ($unique.Count -gt 1) {
            return [pscustomobject]@{ Estado = "PDF_AMBIGUO"; EstadoDocumento = "PDF_AMBIGUO"; Path = ""; Candidato = ($unique -join " | "); Carpeta = ""; Fuente = "FALLBACK_RECURSIVO_RMT"; Coincidencias = $unique }
        }
        return [pscustomobject]@{ Estado = "PDF_REMITO_NO_ENCONTRADO"; EstadoDocumento = "PDF_NO_ENCONTRADO"; Path = ""; Candidato = ($candidates.Name -join " | "); Carpeta = ""; Fuente = ""; Coincidencias = @() }
    }

    $yearRoots = @()
    if ($PdfRoot) {
        $yearRoots += $PdfRoot
    } elseif ($PdfBaseRoot -and $Fecha -ne [datetime]"1900-01-01") {
        $yearRoots += (Join-Path $PdfBaseRoot ([string]$Fecha.Year))
    }
    foreach ($rootItem in $yearRoots) {
        foreach ($candidate in $candidates) {
            $path = Join-Path (Join-Path $rootItem $candidate.Folder) $candidate.Name
            try {
                if (Test-Path -LiteralPath $path) {
                    return [pscustomobject]@{ Estado = "ENCONTRADO"; EstadoDocumento = "PDF_OK"; Path = $path; Candidato = $candidate.Name; Carpeta = "$([IO.Path]::GetFileName($rootItem))\$($candidate.Folder)"; Fuente = "DIRECTA_ANIO_TIPO"; Coincidencias = @($path) }
                }
            } catch {
                return [pscustomobject]@{ Estado = "RAIZ_INACCESIBLE"; EstadoDocumento = "RAIZ_INACCESIBLE"; Path = $path; Candidato = $candidate.Name; Carpeta = "$([IO.Path]::GetFileName($rootItem))\$($candidate.Folder)"; Fuente = "DIRECTA_ANIO_TIPO"; Coincidencias = @() }
            }
        }
    }

    $fallbackMatches = @()
    if ($PdfBaseRoot) {
        try {
            $fallbackMatches += @(Get-ChildItem -LiteralPath $PdfBaseRoot -File -Filter "*.pdf" -Recurse -ErrorAction Stop | Where-Object {
                Test-AuditDocumentCandidateName $t $Number $_.Name
            } | Select-Object -ExpandProperty FullName)
        } catch {
            return [pscustomobject]@{ Estado = "RAIZ_INACCESIBLE"; EstadoDocumento = "RAIZ_INACCESIBLE"; Path = $PdfBaseRoot; Candidato = ""; Carpeta = ""; Fuente = "FALLBACK_RECURSIVO_FACTURAS"; Coincidencias = @() }
        }
    }
    $fallbackUnique = @($fallbackMatches | Sort-Object -Unique)
    if ($fallbackUnique.Count -eq 1) {
        return [pscustomobject]@{ Estado = "ENCONTRADO"; EstadoDocumento = "PDF_OK"; Path = $fallbackUnique[0]; Candidato = [IO.Path]::GetFileName($fallbackUnique[0]); Carpeta = [IO.Path]::GetDirectoryName($fallbackUnique[0]); Fuente = "FALLBACK_RECURSIVO_FACTURAS"; Coincidencias = $fallbackUnique }
    }
    if ($fallbackUnique.Count -gt 1) {
        return [pscustomobject]@{ Estado = "PDF_AMBIGUO"; EstadoDocumento = "PDF_AMBIGUO"; Path = ""; Candidato = ($fallbackUnique -join " | "); Carpeta = ""; Fuente = "FALLBACK_RECURSIVO_FACTURAS"; Coincidencias = $fallbackUnique }
    }
    return [pscustomobject]@{ Estado = "FALTANTE"; EstadoDocumento = "PDF_NO_ENCONTRADO"; Path = ""; Candidato = ($candidates | ForEach-Object { "$($_.Folder)\$($_.Name)" }) -join " | "; Carpeta = ""; Fuente = ""; Coincidencias = @() }
}

function Get-AuditRemitoPdfData([string]$Text) {
    $raw = [string]$Text
    $number = $null
    $date = $null
    $client = ""
    $clientId = $null
    $total = $null
    $items = @()

    $mNumber = [regex]::Match($raw, '(?i)N[º°]?\s*REMITO\s*[:#]?\s*(\d+)')
    if ($mNumber.Success) { $number = [int]$mNumber.Groups[1].Value }

    $mDate = [regex]::Match($raw, '(?i)FECHA\s*[:#]?\s*(\d{1,2}/\d{1,2}/\d{4})')
    if ($mDate.Success) {
        $parsedDate = [datetime]::MinValue
        if ([datetime]::TryParseExact($mDate.Groups[1].Value, "dd/MM/yyyy", [Globalization.CultureInfo]::GetCultureInfo("es-AR"), [Globalization.DateTimeStyles]::None, [ref]$parsedDate)) {
            $date = $parsedDate.Date
        }
    }

    $mClient = [regex]::Match($raw, '(?im)^\s*NOMBRE\s*:\s*(.+?)\s*$')
    if ($mClient.Success) { $client = $mClient.Groups[1].Value.Trim() }

    $mClientId = [regex]::Match($raw, '(?im)^\s*(?:ID\s*CLIENTE|IDCLIENTE|C[OÓ]DIGO\s+(?:DE\s+)?CLIENTE|CLIENTE\s+(?:ID|C[OÓ]DIGO|COD\.?|NRO|N[º°]))\s*[:#-]?\s*(\d+)\b')
    if (-not $mClientId.Success) {
        $mClientId = [regex]::Match($raw, '(?ims)^\s*C[OÓ]DIGO\s*:\s*(\d+)\s*\r?\n\s*NOMBRE\s*:')
    }
    if ($mClientId.Success) { $clientId = [long]$mClientId.Groups[1].Value }

    $mTotal = [regex]::Match($raw, '(?i)\bTOTAL\s*[:$]?\s*\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}|[0-9]+(?:\.[0-9]+)?)')
    if ($mTotal.Success) { $total = Convert-AuditDocumentDecimal $mTotal.Groups[1].Value }

    foreach ($line in ($raw -split "`r?`n")) {
        $mItem = [regex]::Match($line.Trim(), '^(?<qty>\d+(?:[,.]\d+)?)\s+(?<unit>[A-Za-z0-9]+\.?)\s+(?<product>.+?)\s+(?<price>\d+(?:[,.]\d+)?)\s+(?<subtotal>\d+(?:[,.]\d+)?)$')
        if ($mItem.Success) {
            $items += [pscustomobject]@{
                Cantidad = Convert-AuditDocumentDecimal $mItem.Groups["qty"].Value
                Unidad = Normalize-HelenaUnit $mItem.Groups["unit"].Value
                Producto = $mItem.Groups["product"].Value.Trim()
                PrecioUnitario = Convert-AuditDocumentDecimal $mItem.Groups["price"].Value
                Subtotal = Convert-AuditDocumentDecimal $mItem.Groups["subtotal"].Value
            }
        }
    }

    return [pscustomobject]@{
        Numero = $number
        Fecha = $date
        IdCliente = $clientId
        Cliente = $client
        Total = $total
        Items = $items
    }
}

function Compare-AuditRemitoPdf {
    param(
        [Parameter(Mandatory = $true)][object]$Comprobante,
        [Parameter(Mandatory = $true)][object[]]$Detalles,
        [Parameter(Mandatory = $true)][object]$PdfData
    )

    $alerts = @()
    $messages = @()
    $numero = if ($null -ne $Comprobante.Numero -and -not ($Comprobante.Numero -is [System.DBNull])) { [int]$Comprobante.Numero } else { $null }
    if ($null -ne $PdfData.Numero -and $null -ne $numero -and [int]$PdfData.Numero -ne $numero) {
        $alerts += "DETALLE_DIFERENTE"
        $messages += "Numero PDF $($PdfData.Numero) distinto de Access $numero."
    }
    if ($PdfData.Fecha -and ([datetime]$Comprobante.FECHA).Date -ne ([datetime]$PdfData.Fecha).Date) {
        $alerts += "FECHA_DIFERENTE"
        $messages += "Fecha PDF $(([datetime]$PdfData.Fecha).ToString('dd/MM/yyyy')) distinta de Access $(([datetime]$Comprobante.FECHA).ToString('dd/MM/yyyy'))."
    }
    $pdfClientId = if ($PdfData.PSObject.Properties['IdCliente']) { $PdfData.IdCliente } else { $null }
    $accessClientId = if ($Comprobante.PSObject.Properties['IdCLIENTE']) { $Comprobante.IdCLIENTE } else { $null }
    if ($null -ne $pdfClientId) {
        if ($null -eq $accessClientId -or [string]$pdfClientId -ne [string]$accessClientId) {
            $alerts += "CLIENTE_DIFERENTE"
            $messages += "IdCLIENTE PDF '$pdfClientId' distinto de Access '$accessClientId'."
        }
    } elseif ($PdfData.Cliente) {
        if (-not (Test-AuditDocumentClientNameMatch $Comprobante.Cliente $PdfData.Cliente)) {
            $alerts += "CLIENTE_DIFERENTE"
            $messages += "Cliente PDF '$($PdfData.Cliente)' distinto de Access '$($Comprobante.Cliente)'."
        }
    }
    if ($null -ne $PdfData.Total) {
        $diffTotal = [math]::Abs([double]([decimal]$Comprobante.IMPORTE - [decimal]$PdfData.Total))
        if ($diffTotal -gt 1.5) {
            $alerts += "IMPORTE_DIFERENTE"
            $messages += "Total PDF $(Format-AuditDocumentMoney ([decimal]$PdfData.Total)) distinto de Access $(Format-AuditDocumentMoney ([decimal]$Comprobante.IMPORTE))."
        }
    }

    $pdfItems = @($PdfData.Items)
    if ($pdfItems.Count -gt 0) {
        [array]$detailItems = @($Detalles)
        if ($pdfItems.Count -ne $detailItems.Count) {
            $alerts += "DETALLE_DIFERENTE"
            $messages += "Cantidad de lineas PDF $($pdfItems.Count) distinta de Access $($detailItems.Count)."
        }
        foreach ($pdfItem in $pdfItems) {
            $productKey = Normalize-AuditDocumentText $pdfItem.Producto
            [array]$matches = @($detailItems | Where-Object { (Normalize-AuditDocumentText $_.PRODUCTO) -eq $productKey })
            if ($matches.Count -ne 1) {
                $alerts += "DETALLE_DIFERENTE"
                $messages += "Producto PDF '$($pdfItem.Producto)' no coincide inequivocamente con el detalle Access."
                continue
            }
            $detail = $matches[0]
            $cantidad = Convert-AuditDocumentDecimal $detail.CANTIDAD
            $precio = Convert-AuditDocumentDecimal $detail.PUNITARIO
            $subtotal = Convert-AuditDocumentDecimal $detail.Subtotal
            if ($null -ne $pdfItem.Cantidad -and $null -ne $cantidad -and [math]::Abs([double]($cantidad - [decimal]$pdfItem.Cantidad)) -gt 0.001) {
                $alerts += "CANTIDAD_DIFERENTE"
                $messages += "Cantidad '$($pdfItem.Producto)' PDF $($pdfItem.Cantidad) distinta de Access $cantidad."
            }
            if ($null -ne $pdfItem.PrecioUnitario -and $null -ne $precio -and $precio -gt 0 -and [math]::Abs([double]($precio - [decimal]$pdfItem.PrecioUnitario)) -gt 1.5) {
                $alerts += "PRECIO_DIFERENTE"
                $messages += "Precio '$($pdfItem.Producto)' PDF $($pdfItem.PrecioUnitario) distinto de Access $precio."
            }
            if ($null -ne $pdfItem.Subtotal -and $null -ne $subtotal -and [math]::Abs([double]($subtotal - [decimal]$pdfItem.Subtotal)) -gt 1.5) {
                $alerts += "IMPORTE_DIFERENTE"
                $messages += "Subtotal '$($pdfItem.Producto)' PDF $($pdfItem.Subtotal) distinto de Access $subtotal."
            }
        }
    }

    $uniqueAlerts = @($alerts | Select-Object -Unique)
    if ($uniqueAlerts.Count -eq 0) {
        return [pscustomobject]@{ Estado = "OK"; Alerta = ""; Observacion = ""; PdfTotalEstado = "OK" }
    }
    return [pscustomobject]@{
        Estado = ($uniqueAlerts -join "|")
        Alerta = ($uniqueAlerts -join "|")
        Observacion = ($messages -join " | ")
        PdfTotalEstado = ($uniqueAlerts -join "|")
    }
}
