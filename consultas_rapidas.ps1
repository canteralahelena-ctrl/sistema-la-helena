param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("cliente", "estado-pdf", "estado-pdf-abierto", "estado-pdf-ultimo-pago", "estado", "deudores", "material", "cobros", "iva-mensual", "mejores-clientes", "peores-clientes", "clientes-deuda-antigua", "clientes-compran-pagan-mal", "ventas-m3", "gravas-m3", "ventas-importes", "ayuda")]
    [string]$Accion,
    [Parameter(Position = 1)]
    [string]$Cliente = "",
    [datetime]$Desde = "1900-01-01",
    [datetime]$Hasta = "1900-01-01",
    [int]$Top = 20,
    [string]$Periodo = "",
    [int]$DeudaVencidaDias = 30,
    [switch]$ExportCsv,
    [string]$Archivo = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$actualizador = Join-Path $PSScriptRoot "actualizar_copia_base.ps1"
$cacheBuilder = Join-Path $PSScriptRoot "cache_access.ps1"
$cacheQuery = Join-Path $PSScriptRoot "consulta_cache.ps1"

function Update-LocalBase {
    Write-Host "Actualizando copia local de Access antes de consultar..."
    try {
        & powershell -ExecutionPolicy Bypass -File $actualizador
    }
    catch {
        Write-Host ""
        Write-Host "AVISO: No pude actualizar desde el servidor."
        Write-Host "Motivo: $($_.Exception.Message)"
        $statePath = Join-Path $PSScriptRoot "data\actualizacion_base_estado.json"
        if (Test-Path -LiteralPath $statePath) {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            Write-Host "Uso la ultima copia local disponible."
            Write-Host "Ultima actualizacion correcta: $($state.UltimaActualizacionOk)"
            Write-Host "Fecha de la base copiada: $($state.DestinoFecha)"
        } else {
            Write-Host "No encontre registro de ultima actualizacion correcta."
            Write-Host "Si existe una copia local, intentare consultar con esa copia."
        }
    }
    Write-Host ""
}

function Update-FastCache {
    try {
        & powershell -ExecutionPolicy Bypass -File $cacheBuilder
    }
    catch {
        Write-Host ""
        Write-Host "AVISO: No pude reconstruir el cache rapido."
        Write-Host "Motivo: $($_.Exception.Message)"
        Write-Host "Intentare seguir con la consulta directa cuando corresponda."
    }
    Write-Host ""
}

function Show-Help {
    Write-Host "Consultas rapidas disponibles:"
    Write-Host ""
    Write-Host "  cliente        - saldo actual y ultimo pago"
    Write-Host "  estado         - estado de cuenta en consola desde una fecha"
    Write-Host "  estado-pdf     - genera PDF de estado de cuenta desde una fecha"
    Write-Host "  estado-pdf-abierto - genera PDF desde el primer movimiento con saldo abierto"
    Write-Host "  estado-pdf-ultimo-pago - genera PDF desde el ultimo pago del cliente"
    Write-Host "  deudores       - listado completo de clientes deudores"
    Write-Host "  material       - materiales que mas compra un cliente"
    Write-Host "  cobros         - total cobrado por medio de pago entre fechas"
    Write-Host "  iva-mensual    - IVA ventas - IVA gastos de un mes"
    Write-Host "  mejores-clientes - ranking comercial/financiero de mejores clientes"
    Write-Host "  peores-clientes  - ranking de clientes con peor comportamiento financiero"
    Write-Host "  clientes-deuda-antigua - clientes con deuda mas antigua"
    Write-Host "  clientes-compran-pagan-mal - clientes que compran mucho y pagan mal"
    Write-Host "  ventas-m3      - grafico de materiales de mayo en m3"
    Write-Host "  gravas-m3      - grafico de gravas de mayo en m3"
    Write-Host "  ventas-importes- grafico por importe de ventas de mayo"
    Write-Host ""
    Write-Host "Ejemplos:"
    Write-Host "  .\work\consultas_rapidas.ps1 cliente 'VMR TEAM'"
    Write-Host "  .\work\consultas_rapidas.ps1 estado '327' -Desde '2026-05-01'"
    Write-Host "  .\work\consultas_rapidas.ps1 estado-pdf "CLIENTE_A" -Desde '2026-06-01'"
    Write-Host "  .\work\consultas_rapidas.ps1 estado-pdf-ultimo-pago "CLIENTE_A""
    Write-Host "  .\work\consultas_rapidas.ps1 material 'CLIENTE_TEST_1396' -Top 10"
    Write-Host "  .\work\consultas_rapidas.ps1 cobros efectivo -Desde '2026-06-04' -Hasta '2026-06-05'"
    Write-Host "  .\work\consultas_rapidas.ps1 iva-mensual -Desde '2026-05-01'"
    Write-Host "  .\work\consultas_rapidas.ps1 mejores-clientes -Top 5 -Periodo 3m"
    Write-Host "  .\work\consultas_rapidas.ps1 peores-clientes -Top 10 -Periodo 1a"
}

switch ($Accion) {
    "ayuda" {
        Show-Help
    }
    "cliente" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        Update-LocalBase
        Update-FastCache
        & powershell -ExecutionPolicy Bypass -File $cacheQuery cliente $Cliente -Top $Top
    }
    "estado" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        if ($Desde -eq [datetime]"1900-01-01") { throw "Indica -Desde con una fecha." }
        Update-LocalBase
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "estado_cliente.ps1") $Cliente -Desde $Desde -Ultimos 200
    }
    "estado-pdf" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        if ($Desde -eq [datetime]"1900-01-01") { throw "Indica -Desde con una fecha." }
        Update-LocalBase
        $args = @($Cliente, "-Desde", $Desde)
        if ($Hasta -ne [datetime]"1900-01-01") { $args += @("-Hasta", $Hasta) }
        if ($Archivo) { $args += @("-NombreArchivo", $Archivo) }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "generar_estado_cuenta_pdf.ps1") @args
    }
    "estado-pdf-abierto" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        Update-LocalBase
        $args = @($Cliente)
        if ($Archivo) { $args += @("-NombreArchivo", $Archivo) }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "generar_estado_abierto.ps1") @args
    }
    "estado-pdf-ultimo-pago" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        Update-LocalBase
        $args = @($Cliente)
        if ($Archivo) { $args += @("-NombreArchivo", $Archivo) }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "generar_estado_desde_ultimo_pago.ps1") @args
    }
    "deudores" {
        Update-LocalBase
        Update-FastCache
        & powershell -ExecutionPolicy Bypass -File $cacheQuery deudores -Top $Top
    }
    "material" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        Update-LocalBase
        if ($Desde -eq [datetime]"1900-01-01") {
            Update-FastCache
            & powershell -ExecutionPolicy Bypass -File $cacheQuery material $Cliente -Top $Top
        } else {
            & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "material_cliente.ps1") $Cliente -Desde $Desde -Top $Top
        }
    }
    "cobros" {
        if (-not $Cliente) { $Cliente = "todos" }
        if ($Desde -eq [datetime]"1900-01-01") { $Desde = (Get-Date).Date }
        if ($Hasta -eq [datetime]"1900-01-01") { $Hasta = $Desde.AddDays(1) }
        Update-LocalBase
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "cobros_medio.ps1") -Medio $Cliente -Desde $Desde -Hasta $Hasta
    }
    "iva-mensual" {
        if ($Desde -eq [datetime]"1900-01-01") { $Desde = (Get-Date).Date }
        Update-LocalBase
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "iva_mensual.ps1") -Anio $Desde.Year -Mes $Desde.Month
    }
    "mejores-clientes" {
        Update-LocalBase
        $args = @("-Accion", "mejores", "-Top", $Top, "-DeudaVencidaDias", $DeudaVencidaDias)
        if ($Periodo) { $args += @("-Periodo", $Periodo) }
        if ($Desde -ne [datetime]"1900-01-01") { $args += @("-Desde", $Desde) }
        if ($Hasta -ne [datetime]"1900-01-01") { $args += @("-Hasta", $Hasta) }
        if ($ExportCsv) { $args += "-ExportCsv" }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ranking_clientes.ps1") @args
    }
    "peores-clientes" {
        Update-LocalBase
        $args = @("-Accion", "peores", "-Top", $Top, "-DeudaVencidaDias", $DeudaVencidaDias)
        if ($Periodo) { $args += @("-Periodo", $Periodo) }
        if ($Desde -ne [datetime]"1900-01-01") { $args += @("-Desde", $Desde) }
        if ($Hasta -ne [datetime]"1900-01-01") { $args += @("-Hasta", $Hasta) }
        if ($ExportCsv) { $args += "-ExportCsv" }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ranking_clientes.ps1") @args
    }
    "clientes-deuda-antigua" {
        Update-LocalBase
        $args = @("-Accion", "deuda-antigua", "-Top", $Top, "-DeudaVencidaDias", $DeudaVencidaDias)
        if ($Periodo) { $args += @("-Periodo", $Periodo) }
        if ($Desde -ne [datetime]"1900-01-01") { $args += @("-Desde", $Desde) }
        if ($Hasta -ne [datetime]"1900-01-01") { $args += @("-Hasta", $Hasta) }
        if ($ExportCsv) { $args += "-ExportCsv" }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ranking_clientes.ps1") @args
    }
    "clientes-compran-pagan-mal" {
        Update-LocalBase
        $args = @("-Accion", "compran-pagan-mal", "-Top", $Top, "-DeudaVencidaDias", $DeudaVencidaDias)
        if ($Periodo) { $args += @("-Periodo", $Periodo) }
        if ($Desde -ne [datetime]"1900-01-01") { $args += @("-Desde", $Desde) }
        if ($Hasta -ne [datetime]"1900-01-01") { $args += @("-Hasta", $Hasta) }
        if ($ExportCsv) { $args += "-ExportCsv" }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ranking_clientes.ps1") @args
    }
    "ventas-m3" {
        Update-LocalBase
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ventas_productos_mayo.ps1") -OutCsv (Join-Path $PSScriptRoot "ventas_productos_mayo_2026.csv")
        & $python (Join-Path $PSScriptRoot "grafico_ventas_mayo.py")
    }
    "gravas-m3" {
        Update-LocalBase
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ventas_gravas_mayo.ps1") -OutCsv (Join-Path $PSScriptRoot "ventas_gravas_mayo_2026.csv")
        & $python (Join-Path $PSScriptRoot "grafico_gravas_mayo.py")
    }
    "ventas-importes" {
        Update-LocalBase
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ventas_importes_materiales_mayo.ps1") -OutCsv (Join-Path $PSScriptRoot "ventas_importes_materiales_mayo_2026.csv")
        & $python (Join-Path $PSScriptRoot "grafico_importes_materiales_mayo.py")
    }
}
