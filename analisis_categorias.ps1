param(
    [ValidateSet("mensual", "anual", "total")]
    [string]$AgruparPor = "mensual",
    [ValidateSet("", "ultimos-12-meses", "ultimos-3-anios", "ultimos-5-anios", "personalizado")]
    [string]$Periodo = "",
    [int]$Anio = 0,
    [int]$Mes = 0,
    [datetime]$Desde = "1900-01-01",
    [datetime]$Hasta = "1900-01-01",
    [ValidateSet("Ambos", "Facturas", "RMT")]
    [string]$Tipos = "Ambos",
    [string]$Categoria = "",
    [int]$Top = 0,
    [switch]$ExportCsv,
    [switch]$ExportExcel,
    [switch]$Grafico,
    [string]$OutCsv = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "normalizacion_unidades.ps1")
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$mapPath = Join-Path $root "docs\ia\MAPEO_PRODUCTOS_SERVICIOS_DETALLE.csv"
$outputs = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path -LiteralPath $dbPath)) {
    throw "No encontre la base local: $dbPath"
}
if (-not (Test-Path -LiteralPath $mapPath)) {
    throw "No encontre el mapeo oficial: $mapPath"
}
if (-not (Test-Path -LiteralPath $outputs)) {
    New-Item -ItemType Directory -Path $outputs | Out-Null
}

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

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

function Normalize-Key([string]$text) {
    if (-not $text) { return "" }
    $normalized = $text.Trim().ToUpperInvariant().Normalize([Text.NormalizationForm]::FormD)
    $withoutMarks = -join ($normalized.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne [Globalization.UnicodeCategory]::NonSpacingMark
    })
    return ($withoutMarks -replace '\s+', ' ')
}

function Get-Decimal($value) {
    if ($null -eq $value -or $value -is [System.DBNull]) { return [decimal]0 }
    return [decimal]$value
}

function Get-Amount($row) {
    $amount = Get-Decimal $row.SubtotalConIva
    if ($amount -eq 0) { $amount = Get-Decimal $row.Subtotal }
    if ($amount -eq 0) { $amount = Get-Decimal $row.Precio }
    if ($amount -eq 0) {
        $qty = Get-Decimal $row.Cantidad
        $unitPrice = Get-Decimal $row.PrecioUnitario
        $amount = $qty * $unitPrice
    }
    $tipo = Normalize-Key ([string]$row.TipoComprobante)
    if ($tipo -like "NC*" -and $amount -gt 0) { $amount = -1 * $amount }
    return $amount
}

function Get-SignedQuantity($row) {
    $qty = Get-Decimal $row.Cantidad
    $tipo = Normalize-Key ([string]$row.TipoComprobante)
    if ($tipo -like "NC*" -and $qty -gt 0) { $qty = -1 * $qty }
    return $qty
}

function New-LineaInfo(
    [string]$linea,
    [string]$subcategoria,
    [string]$confianza,
    [string]$observacion,
    [decimal]$factorImporte = 1
) {
    return [pscustomobject]@{
        Linea = $linea
        Subcategoria = $subcategoria
        Confianza = $confianza
        Observacion = $observacion
        FactorImporte = $factorImporte
    }
}

function Get-ClasificacionManual([string]$product) {
    $p = Normalize-Key $product
    if (-not $p) { return $null }

    if ($p -match "ANULAD") {
        return New-LineaInfo "EXCLUIR_ANALISIS" "ANULADO" "ALTA" "Concepto anulado/cancelado; excluido del analisis de ventas"
    }

    if ($p -match "ECHEQ.*RECHAZAD|CHEQUE.*RECHAZAD") {
        return New-LineaInfo "EXCLUIR_ANALISIS" "CHEQUE_RECHAZADO" "ALTA" "Cheque/eCheq rechazado; excluido del universo de ventas"
    }

    if (($p -match "PAGO|ECHEQ|CHEQUE") -and ($p -match "FLET|FELT|FLTE")) {
        return New-LineaInfo "EXCLUIR_ANALISIS" "PAGO_FLETES" "ALTA" "Pago de fletes; no corresponde a venta"
    }

    if ($p -match "\b(FLETE|FELTE|FLTE)\s*1\b") {
        return New-LineaInfo "SERVICIOS" "FLETE_TERCERIZADO" "ALTA" "Flete tercerizado; se considera 10% del importe como margen" ([decimal]0.10)
    }

    if ($p -match "\b(FLETE|FELTE|FLTE)\s*2\b") {
        return New-LineaInfo "SERVICIOS" "TRANSPORTE_PROPIO" "ALTA" "Flete propio; se considera 100% del importe"
    }

    if ($p -match "ZANJEO|TAPADO") {
        return New-LineaInfo "SERVICIOS" "Servicios de movimiento de suelos y alquiler de maquinarias" "ALTA" "Servicio de zanjeo/tapado"
    }

    if ($p -match "GRANCILLA") {
        return New-LineaInfo "ARIDOS" "GRANCILLA" "ALTA" "Clasificacion manual: grancilla"
    }

    if ($p -match "ARENA" -and ($p -match "BRUTA|BURTA")) {
        return New-LineaInfo "ARIDOS" "ARENA" "ALTA" "Clasificacion manual: arena bruta/burta"
    }

    $bigBag = ($p -replace "BIG\s*-\s*BAG", "BIG BAG")
    if ($bigBag -match "\bBIG BAG\b") {
        if ($bigBag -match "ARENA\s+FINA\s+PARANA") {
            return New-LineaInfo "ARIDOS" "ARENA" "ALTA" "Clasificacion manual: big bag arena fina Parana"
        }
        if ($bigBag -match "ARENA\s+FINA") {
            return New-LineaInfo "ARIDOS" "ARENA" "ALTA" "Clasificacion manual: big bag arena fina"
        }
        if ($bigBag -match "ARENA\s+BRUTA|ARENA\s+BURTA") {
            return New-LineaInfo "ARIDOS" "ARENA" "ALTA" "Clasificacion manual: big bag arena bruta/burta"
        }
        if ($bigBag -match "GRANZA\s*5\s*/\s*8") {
            return New-LineaInfo "ARIDOS" "GRANZA" "ALTA" "Clasificacion manual: big bag granza 5/8"
        }
        if ($bigBag -match "GRANZA\s*3\s*/\s*8") {
            return New-LineaInfo "ARIDOS" "GRANZA" "ALTA" "Clasificacion manual: big bag granza 3/8"
        }
        if ($bigBag -match "PIEDRA\s*1\s*-\s*3|PIEDRA\s*1\s*/\s*3") {
            return New-LineaInfo "ARIDOS" "PIEDRA" "ALTA" "Clasificacion manual: big bag piedra 1-3"
        }
    }

    return $null
}

function Normalize-Unit([string]$unit) {
    return Normalize-HelenaUnit $unit
}

function Convert-AridoToM3([decimal]$qty, [string]$unit, [string]$product) {
    $u = Normalize-Unit $unit
    $p = Normalize-Key $product
    if ($u -eq "TN") {
        if ($p -match "\bGRANZA\b") { return $qty / [decimal]1.5 }
        return $null
    }
    if ($u -eq "M3") { return $qty }
    if ($u -like "*1200KG*") { return $qty * [decimal]0.8 }
    if ($p -like "*BOLSON*" -or $p -like "*BIG BAG*" -or $p -like "*BIG-BAG*" -or $p -like "*F BOLSON*") {
        return $qty * [decimal]0.8
    }
    if (($u -like "*25KG*" -or ($p -like "*BOLSA*" -and $p -like "*25*")) -and $p -notlike "*ANTRACITA*") {
        return $qty * [decimal]0.01666
    }
    return $null
}

function Get-OperationalExclusion([string]$TipoComprobante, [string]$Product) {
    if ((Normalize-Key $TipoComprobante) -eq "RMT" -and (Normalize-Key $Product) -match "^PAGO(\s+A\s+PROVEEDOR)?$") {
        return New-LineaInfo "EXCLUIR_ANALISIS" "PAGO_PROVEEDOR" "ALTA" "Pago a proveedor en remito; excluido del universo de ventas"
    }
    return $null
}

function Get-LineaNegocio($mapping) {
    if ($null -eq $mapping) {
        return [pscustomobject]@{
            Linea = "SIN_MAPEO"
            Subcategoria = "SIN_MAPEO"
            Confianza = "BAJA"
            Observacion = "Producto no encontrado en el mapeo oficial"
        }
    }

    switch ($mapping.CategoriaPrincipal) {
        "SERVICIOS" {
            return [pscustomobject]@{
                Linea = "SERVICIOS"
                Subcategoria = $mapping.Subcategoria
                Confianza = $mapping.NivelConfianza
                Observacion = $mapping.Observaciones
            }
        }
        "ARIDOS_Y_RELACIONADOS" {
            $linea = if ($mapping.Subcategoria -eq "GRAVAS") { "GRAVAS" } else { "ARIDOS" }
            return [pscustomobject]@{
                Linea = $linea
                Subcategoria = $mapping.Subcategoria
                Confianza = $mapping.NivelConfianza
                Observacion = $mapping.Observaciones
            }
        }
        "PRODUCTOS_COMPRA_VENTA_NO_ARIDOS" {
            $linea = switch ($mapping.Subcategoria) {
                "BENTONITA" { "BENTONITA" }
                "FILTROS" { "FILTROS" }
                "CANO_POCERO" { "CANOS_POCEROS" }
                "ANTRACITA" { "ANTRACITA" }
                "LADRILLOS" { "LADRILLOS" }
                "ADOQUINES" { "ADOQUINES" }
                "VIGUETAS" { "VIGUETAS" }
                default { "OTROS_PRODUCTOS" }
            }
            return [pscustomobject]@{
                Linea = $linea
                Subcategoria = $mapping.Subcategoria
                Confianza = $mapping.NivelConfianza
                Observacion = $mapping.Observaciones
            }
        }
        "REQUIERE_VALIDACION" {
            $linea = if ($mapping.Subcategoria -eq "MIXTO_MATERIAL_SERVICIO") { "REQUIERE_VALIDACION_MIXTO" } else { "REQUIERE_VALIDACION" }
            return [pscustomobject]@{
                Linea = $linea
                Subcategoria = $mapping.Subcategoria
                Confianza = $mapping.NivelConfianza
                Observacion = $mapping.Observaciones
            }
        }
        default {
            return [pscustomobject]@{
                Linea = "REQUIERE_VALIDACION"
                Subcategoria = $mapping.Subcategoria
                Confianza = $mapping.NivelConfianza
                Observacion = "Categoria no reconocida en el mapeo oficial"
            }
        }
    }
}

function Resolve-Period {
    $today = (Get-Date).Date

    if ($Periodo -eq "ultimos-12-meses") {
        $start = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(-11)
        return @($start, $start.AddMonths(12))
    }
    if ($Periodo -eq "ultimos-3-anios") {
        $start = Get-Date -Year ($today.Year - 2) -Month 1 -Day 1
        return @($start, $start.AddYears(3))
    }
    if ($Periodo -eq "ultimos-5-anios") {
        $start = Get-Date -Year ($today.Year - 4) -Month 1 -Day 1
        return @($start, $start.AddYears(5))
    }
    if ($Anio -gt 0 -and $Mes -gt 0) {
        $start = Get-Date -Year $Anio -Month $Mes -Day 1
        return @($start, $start.AddMonths(1))
    }
    if ($Anio -gt 0) {
        $start = Get-Date -Year $Anio -Month 1 -Day 1
        return @($start, $start.AddYears(1))
    }
    if ($Desde -ne [datetime]"1900-01-01") {
        $start = $Desde.Date
        $end = if ($Hasta -ne [datetime]"1900-01-01") { $Hasta.Date.AddDays(1) } else { $today.AddDays(1) }
        return @($start, $end)
    }

    $defaultStart = Get-Date -Year $today.Year -Month 1 -Day 1
    return @($defaultStart, $today.AddDays(1))
}

function Get-PeriodoLabel([datetime]$date) {
    if ($AgruparPor -eq "anual") { return "{0:yyyy}" -f $date }
    if ($AgruparPor -eq "total") { return "TOTAL" }
    return "{0:yyyy-MM}" -f $date
}

function Format-Ars([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Format-Num([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("N2", $culture)
}

$range = Resolve-Period
$fromDate = [datetime]$range[0]
$toDate = [datetime]$range[1]

$mappingByExact = @{}
$mappingByNorm = @{}
Import-Csv -LiteralPath $mapPath -Encoding UTF8 | ForEach-Object {
    $name = [string]$_.NombreOriginal
    if ($name) {
        $mappingByExact[$name.Trim()] = $_
        $mappingByNorm[(Normalize-Key $name)] = $_
    }
}

$whereTipo = ""
if ($Tipos -eq "Facturas") {
    $whereTipo = " AND C.[TIPO] <> 'RMT'"
}
elseif ($Tipos -eq "RMT") {
    $whereTipo = " AND C.[TIPO] = 'RMT'"
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $from = Date-Literal $fromDate
    $to = Date-Literal $toDate
    $headerTotalsSql = @"
SELECT
    IIF(C.[TIPO] = 'RMT', 'RMT', 'FACTURAS') AS Fuente,
    Count(*) AS CantidadComprobantes,
    Sum(C.[IMPORTE]) AS Importe
FROM COMPROVANTES AS C
WHERE C.[FECHA] >= $from
    AND C.[FECHA] < $to
    $whereTipo
GROUP BY IIF(C.[TIPO] = 'RMT', 'RMT', 'FACTURAS')
"@
    $sql = @"
SELECT
    C.*,
    C.[IdCOMPROVANTE] AS IdComprobante,
    C.[TIPO] AS TipoComprobante,
    C.[FECHA] AS FechaComprobante,
    C.[IdCLIENTE] AS IdCliente,
    CL.[RAZ SOCIAL] AS Cliente,
    D.[PRODUCTO] AS Producto,
    D.[UNIDAD] AS Unidad,
    D.[CANTIDAD] AS Cantidad,
    D.[PUNITARIO] AS PrecioUnitario,
    D.[PRECIO] AS Precio,
    D.[Subtot] AS Subtotal,
    D.[Subtot c/IVA] AS SubtotalConIva
FROM (COMPROVANTES AS C
INNER JOIN [DETALLE DE COMPROVANTES] AS D
    ON C.[IdCOMPROVANTE] = D.[IdCOMPROVANTE])
LEFT JOIN CLIENTES AS CL
    ON C.[IdCLIENTE] = CL.[IdCLIENTE]
WHERE C.[FECHA] >= $from
    AND C.[FECHA] < $to
    AND D.[PRODUCTO] Is Not Null
    $whereTipo
"@
    try {
        $headerTotals = Rows ($conn.Execute($headerTotalsSql))
        $data = Rows ($conn.Execute($sql))
    }
    catch {
        if ($env:DEBUG_SQL -eq "1") {
            Write-Host "SQL que fallo:"
            Write-Host $sql
        }
        throw
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}

$validLines = @(
    "SERVICIOS",
    "BENTONITA",
    "FILTROS",
    "CANOS_POCEROS",
    "ANTRACITA",
    "LADRILLOS",
    "ADOQUINES",
    "VIGUETAS",
    "ARIDOS",
    "GRAVAS",
    "OTROS_PRODUCTOS"
)

$lineItems = foreach ($row in $data) {
    $product = ([string]$row.Producto).Trim()
    $lineInfo = Get-ClasificacionManual $product
    if ($null -eq $lineInfo) {
        $mapping = $mappingByExact[$product]
        if ($null -eq $mapping) { $mapping = $mappingByNorm[(Normalize-Key $product)] }
        $lineInfo = Get-LineaNegocio $mapping
    }
    $operationalExclusion = Get-OperationalExclusion ([string]$row.TipoComprobante) $product
    if ($null -ne $operationalExclusion) { $lineInfo = $operationalExclusion }
    if ($lineInfo.Linea -eq "EXCLUIR_ANALISIS") { continue }
    if ($Categoria -and (Normalize-Key $lineInfo.Linea) -ne (Normalize-Key $Categoria)) { continue }

    $qty = Get-SignedQuantity $row
    $amount = Get-Amount $row
    $factorProp = $lineInfo.PSObject.Properties["FactorImporte"]
    if ($null -ne $factorProp -and [decimal]$factorProp.Value -ne 1) {
        $amount = $amount * [decimal]$factorProp.Value
    }
    $m3 = $null
    if ($lineInfo.Linea -eq "ARIDOS") {
        $m3 = Convert-AridoToM3 $qty ([string]$row.Unidad) $product
    }

    $source = if ((Normalize-Key ([string]$row.TipoComprobante)) -eq "RMT") { "RMT" } else { "FACTURAS" }
    $date = [datetime]$row.FechaComprobante
    $numeroField = "N$([char]0x00BA)"
    $numero = ""
    $numeroProp = $row.PSObject.Properties[$numeroField]
    if ($null -ne $numeroProp) { $numero = [string]$numeroProp.Value }

    [pscustomobject]@{
        Periodo = Get-PeriodoLabel $date
        Fecha = $date
        Fuente = $source
        Tipo = $row.TipoComprobante
        IdComprobante = $row.IdComprobante
        Numero = $numero
        IdCliente = $row.IdCliente
        Cliente = $row.Cliente
        ProductoOriginal = $product
        LineaNegocio = $lineInfo.Linea
        Subcategoria = $lineInfo.Subcategoria
        NivelConfianza = $lineInfo.Confianza
        Unidad = $row.Unidad
        Cantidad = $qty
        M3Estimado = $m3
        Importe = $amount
        EsClasificado = ($validLines -contains $lineInfo.Linea)
        MotivoNoClasificacion = if ($validLines -contains $lineInfo.Linea) { "" } elseif ($lineInfo.Observacion) { $lineInfo.Observacion } else { "No pertenece a una categoria comercial valida" }
    }
}

$classifiedItems = @($lineItems | Where-Object { $_.EsClasificado })
$unclassifiedItems = @($lineItems | Where-Object { -not $_.EsClasificado })

$totalImporte = ($classifiedItems | Measure-Object -Property Importe -Sum).Sum
if ($null -eq $totalImporte) { $totalImporte = 0 }
$totalImporte = [decimal]$totalImporte

$summary = $classifiedItems |
    Group-Object Periodo, LineaNegocio |
    ForEach-Object {
        $items = $_.Group
        $first = $items[0]
        $amount = [decimal](($items | Measure-Object -Property Importe -Sum).Sum)
        $qty = [decimal](($items | Measure-Object -Property Cantidad -Sum).Sum)
        $m3Sum = ($items | Where-Object { $null -ne $_.M3Estimado } | Measure-Object -Property M3Estimado -Sum).Sum
        $m3 = if ($null -eq $m3Sum) { $null } else { [decimal]$m3Sum }
        $pct = if ($totalImporte -ne 0) { ($amount / $totalImporte) * 100 } else { 0 }
        [pscustomobject]@{
            Periodo = $first.Periodo
            LineaNegocio = $first.LineaNegocio
            Importe = $amount
            ParticipacionPct = [decimal]$pct
            CantidadTotal = $qty
            M3Estimado = $m3
            CantidadComprobantes = @($items | Select-Object -ExpandProperty IdComprobante -Unique).Count
            CantidadClientes = @($items | Select-Object -ExpandProperty IdCliente -Unique).Count
            CantidadOperaciones = @($items).Count
            Fuentes = (($items | Select-Object -ExpandProperty Fuente -Unique) -join ",")
            UnidadesDetectadas = (($items | Where-Object { $_.Unidad } | Select-Object -ExpandProperty Unidad -Unique) -join ", ")
            SubcategoriasIncluidas = (($items | Select-Object -ExpandProperty Subcategoria -Unique) -join ", ")
        }
    } |
    Sort-Object Periodo, @{ Expression = "Importe"; Descending = $true }

if ($Top -gt 0) {
    $summary = $summary | Group-Object Periodo | ForEach-Object {
        $_.Group | Select-Object -First $Top
    }
}

$bySource = $classifiedItems |
    Group-Object Periodo, LineaNegocio, Fuente |
    ForEach-Object {
        $items = $_.Group
        $first = $items[0]
        [pscustomobject]@{
            Periodo = $first.Periodo
            LineaNegocio = $first.LineaNegocio
            Fuente = $first.Fuente
            Importe = [decimal](($items | Measure-Object -Property Importe -Sum).Sum)
            CantidadComprobantes = @($items | Select-Object -ExpandProperty IdComprobante -Unique).Count
            CantidadClientes = @($items | Select-Object -ExpandProperty IdCliente -Unique).Count
            CantidadOperaciones = @($items).Count
        }
    } |
    Sort-Object Periodo, LineaNegocio, Fuente

$noClasificados = @($unclassifiedItems |
    Sort-Object Fecha, Tipo, IdComprobante, ProductoOriginal |
    Select-Object `
        @{Name = "Fecha"; Expression = { $_.Fecha }},
        @{Name = "TipoComprobante"; Expression = { $_.Tipo }},
        @{Name = "NumeroComprobante"; Expression = { $_.Numero }},
        @{Name = "NumeroFactura"; Expression = { if ($_.Fuente -eq "FACTURAS") { $_.Numero } else { "" } }},
        @{Name = "NumeroRMT"; Expression = { if ($_.Fuente -eq "RMT") { $_.Numero } else { "" } }},
        @{Name = "Cliente"; Expression = { $_.Cliente }},
        @{Name = "ProductoDescripcionOriginal"; Expression = { $_.ProductoOriginal }},
        @{Name = "Cantidad"; Expression = { $_.Cantidad }},
        @{Name = "Unidad"; Expression = { $_.Unidad }},
        @{Name = "ImporteSinIVA"; Expression = { $_.Importe }},
        @{Name = "CategoriaSugerida"; Expression = { $_.Subcategoria }},
        @{Name = "NivelConfianza"; Expression = { $_.NivelConfianza }},
        @{Name = "MotivoNoClasificacion"; Expression = { $_.MotivoNoClasificacion }},
        @{Name = "ObservacionManual"; Expression = { "" }})

$noClasificadosTotal = [decimal]0
if ($noClasificados.Count -gt 0) {
    $sumNoClasificados = ($noClasificados | Measure-Object -Property ImporteSinIVA -Sum).Sum
    if ($null -ne $sumNoClasificados) { $noClasificadosTotal = [decimal]$sumNoClasificados }
}

$facturadoRealTotal = [decimal]0
$remitosRealTotal = [decimal]0
foreach ($row in @($headerTotals)) {
    $source = Normalize-Key ([string]$row.Fuente)
    $amount = Get-Decimal $row.Importe
    if ($source -eq "RMT") {
        $remitosRealTotal += $amount
    } else {
        $facturadoRealTotal += $amount
    }
}
$realTotal = $facturadoRealTotal + $remitosRealTotal

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutCsv -and ($ExportCsv -or $ExportExcel -or $Grafico)) {
    $OutCsv = Join-Path $outputs "analisis_categorias_${AgruparPor}_${stamp}.csv"
}

if ($OutCsv) {
    $summary | Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8
    $sourcePath = [System.IO.Path]::ChangeExtension($OutCsv, ".fuentes.csv")
    $detailPath = [System.IO.Path]::ChangeExtension($OutCsv, ".detalle.csv")
    $noClasificadosPath = [System.IO.Path]::ChangeExtension($OutCsv, ".no_clasificados.csv")
    $bySource | Export-Csv -LiteralPath $sourcePath -NoTypeInformation -Encoding UTF8
    $classifiedItems | Export-Csv -LiteralPath $detailPath -NoTypeInformation -Encoding UTF8
    $noClasificados | Export-Csv -LiteralPath $noClasificadosPath -NoTypeInformation -Encoding UTF8
}

if ($ExportExcel) {
    if (-not $OutCsv) {
        throw "No se pudo definir la ruta base para exportar Excel."
    }
    $excelPath = [System.IO.Path]::ChangeExtension($OutCsv, ".xlsx")
    $excelScript = Join-Path $PSScriptRoot "generar_excel_analisis_categorias.py"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "No encontre Python para generar Excel: $python"
    }
    if (-not (Test-Path -LiteralPath $excelScript)) {
        throw "No encontre el generador de Excel: $excelScript"
    }
    & $python $excelScript --resumen $OutCsv --fuentes $sourcePath --detalle $detailPath --no-clasificados $noClasificadosPath --salida $excelPath
}

if ($Grafico) {
    $graphPath = [System.IO.Path]::ChangeExtension($OutCsv, ".html")
    $topGraph = $summary |
        Group-Object LineaNegocio |
        ForEach-Object {
            [pscustomobject]@{
                LineaNegocio = $_.Name
                Importe = [decimal](($_.Group | Measure-Object -Property Importe -Sum).Sum)
            }
        } |
        Sort-Object Importe -Descending
    $max = [decimal](($topGraph | Measure-Object -Property Importe -Maximum).Maximum)
    if ($max -eq 0) { $max = 1 }
    $bars = foreach ($r in $topGraph) {
        $w = [math]::Round(([decimal]$r.Importe / $max) * 100, 2)
        $importe = Format-Ars ([decimal]$r.Importe)
        "<div class='row'><div class='label'>$($r.LineaNegocio)</div><div class='barwrap'><div class='bar' style='width:${w}%'></div></div><div class='value'>$importe</div></div>"
    }
    $html = @"
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Analisis de categorias</title>
<style>
body { font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }
h1 { font-size: 22px; margin-bottom: 4px; }
.meta { color: #52606d; margin-bottom: 24px; }
.row { display: grid; grid-template-columns: 230px 1fr 150px; gap: 12px; align-items: center; margin: 9px 0; }
.label { font-size: 13px; }
.value { font-size: 13px; text-align: right; }
.barwrap { background: #edf2f7; height: 20px; border-radius: 3px; overflow: hidden; }
.bar { background: #2f80ed; height: 100%; }
</style>
</head>
<body>
<h1>Analisis de categorias comerciales</h1>
<div class="meta">Periodo: $($fromDate.ToString("dd/MM/yyyy")) al $($toDate.AddDays(-1).ToString("dd/MM/yyyy")) - Tipos: $Tipos</div>
$($bars -join "`n")
<p class="meta">Existen $($noClasificados.Count) productos/servicios no clasificados por un total de $(Format-Ars $noClasificadosTotal). Revisar archivo NO_CLASIFICADOS.</p>
</body>
</html>
"@
    Set-Content -LiteralPath $graphPath -Value $html -Encoding UTF8
}

Write-Host "Analisis de categorias comerciales"
Write-Host ("Periodo: {0:dd/MM/yyyy} al {1:dd/MM/yyyy}" -f $fromDate, $toDate.AddDays(-1))
Write-Host "Tipos incluidos: $Tipos"
Write-Host ("Total real ventas: {0}" -f (Format-Ars $realTotal))
Write-Host ("Facturado real: {0}" -f (Format-Ars $facturadoRealTotal))
Write-Host ("Remitos real: {0}" -f (Format-Ars $remitosRealTotal))
Write-Host ("Clasificado: {0}" -f (Format-Ars $totalImporte))
Write-Host ("No clasificado: {0}" -f (Format-Ars $noClasificadosTotal))
Write-Host ("Importe total considerado: {0}" -f (Format-Ars $totalImporte))
if ($Tipos -eq "Ambos") {
    $facturadoTotal = [decimal]0
    $remitosTotal = [decimal]0
    $facturadoSum = ($bySource | Where-Object Fuente -eq "FACTURAS" | Measure-Object -Property Importe -Sum).Sum
    $remitosSum = ($bySource | Where-Object Fuente -eq "RMT" | Measure-Object -Property Importe -Sum).Sum
    if ($null -ne $facturadoSum) { $facturadoTotal = [decimal]$facturadoSum }
    if ($null -ne $remitosSum) { $remitosTotal = [decimal]$remitosSum }
    Write-Host ("Facturado clasificado: {0}" -f (Format-Ars $facturadoTotal))
    Write-Host ("Remitos clasificado: {0}" -f (Format-Ars $remitosTotal))
}
Write-Host ""

$display = $summary | Select-Object `
    Periodo,
    LineaNegocio,
    @{Name = "Importe"; Expression = { Format-Ars ([decimal]$_.Importe) }},
    @{Name = "%"; Expression = { (Format-Num ([decimal]$_.ParticipacionPct)) + "%" }},
    @{Name = "Cantidad"; Expression = { Format-Num ([decimal]$_.CantidadTotal) }},
    @{Name = "M3"; Expression = { if ($null -eq $_.M3Estimado) { "" } else { Format-Num ([decimal]$_.M3Estimado) } }},
    CantidadComprobantes,
    CantidadClientes,
    CantidadOperaciones,
    Fuentes

$display | Format-Table -AutoSize

if ($OutCsv) {
    Write-Host ""
    Write-Host "CSV resumen: $OutCsv"
    Write-Host "CSV por fuente: $sourcePath"
    Write-Host "CSV detalle: $detailPath"
    Write-Host "CSV NO_CLASIFICADOS: $noClasificadosPath"
}
if ($ExportExcel) {
    Write-Host "Excel: $excelPath"
}
if ($Grafico) {
    Write-Host "Grafico HTML: $graphPath"
}

if ($noClasificados.Count -gt 0) {
    Write-Host ""
    Write-Host ("AVISO: Existen {0} productos/servicios no clasificados por un total de {1}. Revisar hoja/archivo NO_CLASIFICADOS." -f $noClasificados.Count, (Format-Ars $noClasificadosTotal))
}
