$ErrorActionPreference = "Stop"

function Is-NotaCredito([string]$tipo) {
    $t = ([string]$tipo).Trim().ToUpperInvariant()
    return ($t -match '^NC' -or $t -match '^NCS' -or $t -like 'NOTA*CREDITO*')
}

function Parse-Decimal($value) {
    if ($null -eq $value -or $value -eq "" -or $value -is [System.DBNull]) { return $null }
    return [decimal]$value
}

function Money([decimal]$value) {
    return ("$ {0:N2}" -f $value)
}

. (Join-Path $PSScriptRoot "auditoria_precio_venta.ps1")

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ([string]$Expected -ne [string]$Actual) {
        throw "$Name - esperado: '$Expected'; obtenido: '$Actual'"
    }
    Write-Host "OK - $Name"
}

function New-Detalle([string]$Tipo, [int]$Id, [string]$Producto, [decimal]$Precio, [decimal]$Cantidad = 1) {
    [pscustomobject]@{
        IdCOMPROVANTE = $Id
        IdDET = $Id * 10
        TIPO = $Tipo
        FECHA = [datetime]"2026-08-05"
        Numero = 30715
        Cliente = "CLIENTE"
        PRODUCTO = $Producto
        UNIDAD = "Mtr3"
        CANTIDAD = $Cantidad
        PUNITARIO = $Precio
        Subtotal = $Precio * $Cantidad
    }
}

$precios = @{
    "ARENA ZARANDEADA" = [decimal]10500
    "SIN PRECIO" = $null
    "PRECIO CERO" = [decimal]0
    "ARENA FINA" = [pscustomobject]@{ PUNITARIO = [decimal]18000; UNIDAD = "Mtr3" }
    "ARENA FINA PARANA" = [pscustomobject]@{ PUNITARIO = [decimal]57120; UNIDAD = "Mtr3" }
    "ARENA BRUTA" = [pscustomobject]@{ PUNITARIO = [decimal]7000; UNIDAD = "TN" }
    "GRANZA 5/8" = [pscustomobject]@{ PUNITARIO = [decimal]18600; UNIDAD = "Mtr3" }
    "PRODUCTO SIN CONVERSION" = [pscustomobject]@{ PUNITARIO = [decimal]18600; UNIDAD = "Mtr3" }
}

$empty = Get-AuditPrecioVentaBajo -Detalles @() -PreciosPorProducto $precios
Assert-Equal 0 $empty.Count "Sin detalles no genera alertas ni falla"

$cases = @(
    @{ Name = "Precio lista exacto OK"; Detalles = @(New-Detalle "RMT" 1 "ARENA ZARANDEADA" 10500); Count = 0 },
    @{ Name = "Vendido 8500 OK"; Detalles = @(New-Detalle "RMT" 2 "ARENA ZARANDEADA" 8500); Count = 0 },
    @{ Name = "Vendido exactamente 8400 OK"; Detalles = @(New-Detalle "RMT" 3 "ARENA ZARANDEADA" 8400); Count = 0 },
    @{ Name = "Vendido 8399 alerta"; Detalles = @(New-Detalle "RMT" 4 "ARENA ZARANDEADA" 8399); Count = 1 },
    @{ Name = "Descuento superior al 20 alerta"; Detalles = @(New-Detalle "RMT" 5 "ARENA ZARANDEADA" 5000); Count = 1 },
    @{ Name = "PUNITARIO null no alerta"; Detalles = @(New-Detalle "RMT" 6 "SIN PRECIO" 5000); Count = 0 },
    @{ Name = "PUNITARIO cero no alerta"; Detalles = @(New-Detalle "RMT" 7 "PRECIO CERO" 1); Count = 0 },
    @{ Name = "Importe correcto precio normal OK"; Detalles = @(New-Detalle "RMT" 8 "ARENA ZARANDEADA" 10500); Count = 0 },
    @{ Name = "Importe correcto precio bajo alerta"; Detalles = @(New-Detalle "RMT" 9 "ARENA ZARANDEADA" 7000); Count = 1 },
    @{ Name = "Nota de credito no controla"; Detalles = @(New-Detalle "NCS A" 10 "ARENA ZARANDEADA" 1); Count = 0 },
    @{ Name = "Usuario 1 cubierto por motor"; Detalles = @(New-Detalle "RMT" 11 "ARENA ZARANDEADA" 7000); Count = 1 },
    @{ Name = "Usuario 2 cubierto por motor"; Detalles = @(New-Detalle "RMT" 12 "ARENA ZARANDEADA" 7000); Count = 1 },
    @{ Name = "Usuario 3 cubierto por motor"; Detalles = @(New-Detalle "RMT" 13 "ARENA ZARANDEADA" 7000); Count = 1 }
)

foreach ($case in $cases) {
    $result = Get-AuditPrecioVentaBajo -Detalles $case.Detalles -PreciosPorProducto $precios
    Assert-Equal $case.Count $result.Count $case.Name
}

$anulado = Get-AuditPrecioVentaBajo -Detalles @(New-Detalle "RMT" 14 "ARENA ZARANDEADA" 1) -PreciosPorProducto $precios -ComprobantesAnulados @{ "14" = $true }
Assert-Equal 0 $anulado.Count "ANULADO con precio extrano no controla"

$variasUnaBaja = Get-AuditPrecioVentaBajo -Detalles @(
    (New-Detalle "RMT" 15 "ARENA ZARANDEADA" 10500),
    (New-Detalle "RMT" 15 "ARENA ZARANDEADA" 8399)
) -PreciosPorProducto $precios
Assert-Equal 1 $variasUnaBaja.Count "Varias lineas, una baja genera una alerta"
Assert-Equal 1 @($variasUnaBaja["15"].Lineas).Count "Varias lineas, una baja detalla solo la afectada"

$variasBajas = Get-AuditPrecioVentaBajo -Detalles @(
    (New-Detalle "RMT" 16 "ARENA ZARANDEADA" 7000),
    (New-Detalle "RMT" 16 "ARENA ZARANDEADA" 6000)
) -PreciosPorProducto $precios
Assert-Equal 1 $variasBajas.Count "Varias lineas bajas generan una alerta"
Assert-Equal 2 @($variasBajas["16"].Lineas).Count "Varias lineas bajas detalla todas"

$rmtDetalle = New-Detalle "RMT" 44648 "ARENA ZARANDEADA" 0 100
$rmtDetalle.Subtotal = [decimal]300000
$rmt30715 = Get-AuditPrecioVentaBajo -Detalles @($rmtDetalle) -PreciosPorProducto $precios
Assert-Equal 1 $rmt30715.Count "Caso RMT 30715 detectado"
Assert-Equal "PRECIO_VENTA_BAJO" $rmt30715["44648"].TipoAlerta "Clasificacion RMT 30715"
Assert-Equal 3000 $rmt30715["44648"].Lineas[0].PrecioVendido "Caso RMT 30715 usa Subtot / Cantidad"

$fts4526 = New-Detalle "FTS A" 44809 "ARENA FINA" 0 34
$fts4526.Numero = 200004526
$fts4526.UNIDAD = "TN"
$fts4526.Subtotal = [decimal]408000
$arenaEquivalente = Get-AuditPrecioListaEquivalente -Producto $fts4526.PRODUCTO -Referencia $precios[$fts4526.PRODUCTO] -UnidadVenta $fts4526.UNIDAD
Assert-Equal 18000 $arenaEquivalente.PrecioOriginal "FTS A 200004526 conserva lista original ARENA FINA"
Assert-Equal "M3" $arenaEquivalente.UnidadLista "FTS A 200004526 normaliza unidad lista Mtr3"
Assert-Equal 12000 $arenaEquivalente.PrecioEquivalente "FTS A 200004526 convierte lista ARENA M3 a TN"
Assert-Equal "TN" $arenaEquivalente.UnidadVenta "FTS A 200004526 usa unidad real de venta"
Assert-Equal "ARENA_M3_A_TN" $arenaEquivalente.ConversionAplicada "FTS A 200004526 registra conversion aplicada"
$fts4526Result = Get-AuditPrecioVentaBajo -Detalles @($fts4526) -PreciosPorProducto $precios
Assert-Equal 0 $fts4526Result.Count "FTS A 200004526 no genera falso precio bajo"

$arenaBaja = New-Detalle "FTS A" 44810 "ARENA FINA" 9599 34
$arenaBaja.UNIDAD = "toneladas"
$arenaBajaResult = Get-AuditPrecioVentaBajo -Detalles @($arenaBaja) -PreciosPorProducto $precios
Assert-Equal 1 $arenaBajaResult.Count "ARENA realmente por debajo del 80 por ciento sigue alertando"
Assert-Equal 12000 $arenaBajaResult["44810"].Lineas[0].PrecioLista "Alerta ARENA informa precio equivalente usado"

$arenaMismaUnidad = Get-AuditPrecioListaEquivalente -Producto "ARENA FINA PARANA" -Referencia $precios["ARENA FINA PARANA"] -UnidadVenta "M3"
Assert-Equal 57120 $arenaMismaUnidad.PrecioEquivalente "ARENA en misma unidad conserva precio lista"
Assert-Equal "" $arenaMismaUnidad.ConversionAplicada "ARENA en misma unidad no convierte"

$arenaInversa = Get-AuditPrecioListaEquivalente -Producto "ARENA BRUTA" -Referencia $precios["ARENA BRUTA"] -UnidadVenta "Mtr3"
Assert-Equal 10500.0 $arenaInversa.PrecioEquivalente "ARENA convierte lista TN a venta M3"
Assert-Equal "ARENA_TN_A_M3" $arenaInversa.ConversionAplicada "ARENA registra conversion inversa"

$fts4508 = New-Detalle "FTS A" 44749 "GRANZA 5/8" 12400 34
$fts4508.Numero = 200004508
$fts4508.UNIDAD = "TN"
$granzaEquivalente = Get-AuditPrecioListaEquivalente -Producto $fts4508.PRODUCTO -Referencia $precios[$fts4508.PRODUCTO] -UnidadVenta $fts4508.UNIDAD
Assert-Equal 12400 $granzaEquivalente.PrecioEquivalente "FTS A 200004508 convierte lista 18600 M3 a 12400 TN"
Assert-Equal "GRANZA_M3_A_TN" $granzaEquivalente.ConversionAplicada "FTS A 200004508 registra conversion aplicada"
$fts4508Result = Get-AuditPrecioVentaBajo -Detalles @($fts4508) -PreciosPorProducto $precios
Assert-Equal 0 $fts4508Result.Count "FTS A 200004508 no genera falso precio bajo"

$granzaListaTn = [pscustomobject]@{ PUNITARIO = [decimal]12400; UNIDAD = "TN" }
$granzaEquivalenteM3 = Get-AuditPrecioListaEquivalente -Producto "GRANZA 5/8" -Referencia $granzaListaTn -UnidadVenta "M3"
Assert-Equal 18600.0 $granzaEquivalenteM3.PrecioEquivalente "GRANZA convierte lista TN a venta M3"
Assert-Equal "GRANZA_TN_A_M3" $granzaEquivalenteM3.ConversionAplicada "GRANZA registra conversion inversa"

$granzaBaja = New-Detalle "FTS A" 44750 "GRANZA 5/8" 9919 34
$granzaBaja.UNIDAD = "toneladas"
$granzaBajaResult = Get-AuditPrecioVentaBajo -Detalles @($granzaBaja) -PreciosPorProducto $precios
Assert-Equal 1 $granzaBajaResult.Count "GRANZA realmente por debajo del 80 por ciento sigue alertando"

$sinConversion = Get-AuditPrecioListaEquivalente -Producto "PRODUCTO SIN CONVERSION" -Referencia $precios["PRODUCTO SIN CONVERSION"] -UnidadVenta "TN"
Assert-Equal 18600 $sinConversion.PrecioEquivalente "Producto ajeno a GRANZA no recibe conversion inventada"
Assert-Equal "" $sinConversion.ConversionAplicada "Producto ajeno a GRANZA conserva unidad sin conversion"

Write-Host "PRUEBAS COMPLETADAS: control precio venta bajo."
