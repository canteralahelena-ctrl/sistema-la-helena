$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "normalizacion_unidades.ps1")

function Normalize-AuditPrecioUnidad([object]$Value) {
    return Normalize-HelenaUnit $Value
}

function Test-AuditProductoFamiliaGranza([string]$Producto) {
    $normalizado = ([string]$Producto).Trim().ToUpperInvariant()
    return ($normalizado -match '(^|[^A-Z0-9])GRANZA([^A-Z0-9]|$)')
}

function Test-AuditProductoFamiliaArena([string]$Producto) {
    $normalizado = ([string]$Producto).Trim().ToUpperInvariant()
    return ($normalizado -match '(^|[^A-Z0-9])ARENAS?([^A-Z0-9]|$)')
}

function Get-AuditPrecioListaEquivalente {
    param(
        [Parameter(Mandatory = $true)][string]$Producto,
        [Parameter(Mandatory = $true)][AllowNull()][object]$Referencia,
        [object]$UnidadVenta
    )

    $precioRaw = $Referencia
    $unidadListaRaw = ""
    if ($Referencia -is [System.Collections.IDictionary]) {
        if ($Referencia.Contains("PUNITARIO")) { $precioRaw = $Referencia["PUNITARIO"] }
        if ($Referencia.Contains("UNIDAD")) { $unidadListaRaw = [string]$Referencia["UNIDAD"] }
    }
    elseif ($null -ne $Referencia -and $Referencia.PSObject.Properties["PUNITARIO"]) {
        $precioRaw = $Referencia.PUNITARIO
        if ($Referencia.PSObject.Properties["UNIDAD"]) { $unidadListaRaw = [string]$Referencia.UNIDAD }
    }

    $precioLista = Parse-Decimal $precioRaw
    $unidadLista = Normalize-AuditPrecioUnidad $unidadListaRaw
    $unidadVentaNormalizada = Normalize-AuditPrecioUnidad $UnidadVenta
    $precioEquivalente = $precioLista
    $conversion = ""

    $familiaConversion = if (Test-AuditProductoFamiliaGranza $Producto) {
        "GRANZA"
    }
    elseif (Test-AuditProductoFamiliaArena $Producto) {
        "ARENA"
    }
    else {
        ""
    }
    if ($null -ne $precioLista -and $familiaConversion) {
        if ($unidadLista -eq "M3" -and $unidadVentaNormalizada -eq "TN") {
            $precioEquivalente = $precioLista / [decimal]1.5
            $conversion = "${familiaConversion}_M3_A_TN"
        }
        elseif ($unidadLista -eq "TN" -and $unidadVentaNormalizada -eq "M3") {
            $precioEquivalente = $precioLista * [decimal]1.5
            $conversion = "${familiaConversion}_TN_A_M3"
        }
    }

    return [pscustomobject]@{
        PrecioOriginal = $precioLista
        PrecioEquivalente = $precioEquivalente
        UnidadLista = $unidadLista
        UnidadVenta = $unidadVentaNormalizada
        ConversionAplicada = $conversion
    }
}

function Get-AuditPrecioVentaBajo {
    param(
        [array]$Detalles,
        [Parameter(Mandatory = $true)]
        [hashtable]$PreciosPorProducto,
        [hashtable]$ComprobantesAnulados = @{}
    )

    $porComprobante = @{}
    foreach ($d in $Detalles) {
        if (Is-NotaCredito ([string]$d.TIPO)) {
            continue
        }

        $idComprobante = [string]([int]$d.IdCOMPROVANTE)
        if ($ComprobantesAnulados.ContainsKey($idComprobante)) {
            continue
        }

        $producto = ([string]$d.PRODUCTO).Trim()
        if (-not $producto -or -not $PreciosPorProducto.ContainsKey($producto)) {
            continue
        }

        $referenciaLista = Get-AuditPrecioListaEquivalente -Producto $producto -Referencia $PreciosPorProducto[$producto] -UnidadVenta $d.UNIDAD
        $precioLista = $referenciaLista.PrecioEquivalente
        $precioVendido = Parse-Decimal $d.PUNITARIO
        $cantidad = Parse-Decimal $d.CANTIDAD
        $subtotal = Parse-Decimal $d.Subtotal
        if (($null -eq $precioVendido -or $precioVendido -le [decimal]0) -and $null -ne $subtotal -and $null -ne $cantidad -and $cantidad -ne [decimal]0) {
            $precioVendido = $subtotal / $cantidad
        }
        if ($null -eq $precioLista -or $null -eq $precioVendido) {
            continue
        }
        if ($precioLista -le [decimal]0) {
            continue
        }

        $precioMinimo = $precioLista * [decimal]0.80
        if ($precioVendido -ge $precioMinimo) {
            continue
        }

        $desvio = (($precioVendido / $precioLista) - [decimal]1) * [decimal]100
        $diferenciaPesos = $precioVendido - $precioLista
        $linea = [pscustomobject]@{
            IdCOMPROVANTE = [int]$d.IdCOMPROVANTE
            IdDET = $d.IdDET
            Fecha = ([datetime]$d.FECHA).ToString("dd/MM/yyyy")
            Comprobante = "$($d.TIPO) $($d.Numero)"
            Cliente = $d.Cliente
            Producto = $producto
            Cantidad = $cantidad
            PrecioVendido = $precioVendido
            PrecioLista = $precioLista
            PrecioListaOriginal = $referenciaLista.PrecioOriginal
            UnidadLista = $referenciaLista.UnidadLista
            UnidadVenta = $referenciaLista.UnidadVenta
            ConversionAplicada = $referenciaLista.ConversionAplicada
            PrecioMinimo = $precioMinimo
            DiferenciaPesos = $diferenciaPesos
            DesvioPorcentual = $desvio
        }

        if (-not $porComprobante.ContainsKey($idComprobante)) {
            $porComprobante[$idComprobante] = @()
        }
        $porComprobante[$idComprobante] = @($porComprobante[$idComprobante]) + @($linea)
    }

    $alertas = @{}
    foreach ($id in $porComprobante.Keys) {
        [array]$lineas = @($porComprobante[$id])
        $detalle = ($lineas | ForEach-Object {
            "Producto: {0}; Precio vendido: {1}; Precio de lista: {2}; Minimo permitido (80%): {3}; Diferencia: {4:N2}%" -f `
                $_.Producto, (Money $_.PrecioVendido), (Money $_.PrecioLista), (Money $_.PrecioMinimo), $_.DesvioPorcentual
        }) -join " | "

        $first = $lineas[0]
        $alertas[$id] = [pscustomobject]@{
            TipoAlerta = "PRECIO_VENTA_BAJO"
            Fecha = $first.Fecha
            Comprobante = $first.Comprobante
            Cliente = $first.Cliente
            Producto = ($lineas.Producto -join " | ")
            Detalle = $detalle
            Observacion = "VERIFICAR PRECIO DE VENTA"
            Lineas = $lineas
        }
    }

    return $alertas
}
