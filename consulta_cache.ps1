param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("cliente", "deudores", "material")]
    [string]$Accion,
    [Parameter(Position = 1)]
    [string]$Cliente = "",
    [int]$Top = 20
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$cacheRoot = if ($env:HELENA_DATA_DIR) { $env:HELENA_DATA_DIR } else { Join-Path $PSScriptRoot "data" }
$cachePath = Join-Path $cacheRoot "cache\access_fast_cache.json"

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Find-Client($cache, [string]$query) {
    if ($query -match '^\d+$') {
        return @($cache.Clientes | Where-Object { [int]$_.IdCLIENTE -eq [int]$query })
    }
    $q = $query.ToUpperInvariant()
    return @($cache.Clientes | Where-Object { ([string]$_.RazonSocial).ToUpperInvariant().Contains($q) })
}

if (-not (Test-Path -LiteralPath $cachePath)) {
    throw "No existe cache rapido. Ejecuta cache_access.ps1 primero."
}

$cache = Get-Content -LiteralPath $cachePath -Raw | ConvertFrom-Json

switch ($Accion) {
    "cliente" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        $clients = Find-Client $cache $Cliente
        if ($clients.Count -eq 0) {
            Write-Host "No encontre cliente: $Cliente"
            return
        }
        if ($clients.Count -gt 1) {
            Write-Host "Hay varios clientes. Usa el IdCLIENTE:"
            $clients | Select-Object IdCLIENTE, RazonSocial, CUIT, LOCALIDAD | Format-Table -AutoSize
            return
        }

        $client = $clients[0]
        $id = [string]$client.IdCLIENTE
        $saldoRow = @($cache.Saldos | Where-Object { [int]$_.IdCLIENTE -eq [int]$id })[0]
        $debe = if ($saldoRow -and $saldoRow.Debe) { [decimal]$saldoRow.Debe } else { [decimal]0 }
        $haber = if ($saldoRow -and $saldoRow.Haber) { [decimal]$saldoRow.Haber } else { [decimal]0 }
        $saldo = $debe - $haber
        $last = @($cache.UltimosPagos | Where-Object { [string]$_.IdCLIENTE -eq $id } | Select-Object -First 1)[0]

        Write-Host "Cliente: $($client.RazonSocial)"
        Write-Host "IdCLIENTE: $id"
        Write-Host "CUIT: $($client.CUIT)"
        Write-Host "Localidad: $($client.LOCALIDAD)"
        Write-Host "Saldo actual: $(Money $saldo)"
        if ($last) {
            Write-Host "Ultimo pago: $(([datetime]$last.Fecha).ToString('dd/MM/yyyy HH:mm:ss')) - $(Money ([decimal]$last.Monto)) - $($last.Tipo) - IdPago $($last.IdPAGO)"
        } else {
            Write-Host "Ultimo pago: sin pagos registrados"
        }
        Write-Host "Fuente: cache local creado $($cache.Creado)"
    }

    "deudores" {
        $rows = @(
            $cache.Saldos |
                Where-Object { [decimal]$_.Saldo -gt 0 } |
                Sort-Object RazonSocial |
                ForEach-Object {
                    [pscustomobject]@{
                        IdCLIENTE = [int]$_.IdCLIENTE
                        RazonSocial = $_.RazonSocial
                        Localidad = $_.LOCALIDAD
                        SaldoNumero = [decimal]$_.Saldo
                        Saldo = Money ([decimal]$_.Saldo)
                    }
                }
        )
        $total = ($rows | Measure-Object -Property SaldoNumero -Sum).Sum
        Write-Host "Clientes deudores: $($rows.Count)"
        Write-Host "Total deuda: $(Money ([decimal]$total))"
        Write-Host "Fuente: cache local creado $($cache.Creado)"
        Write-Host ""
        $display = if ($Top -gt 0) { $rows | Select-Object -First $Top } else { $rows }
        $display | Select-Object IdCLIENTE, RazonSocial, Localidad, Saldo | Format-Table -AutoSize
    }

    "material" {
        if (-not $Cliente) { throw "Indica el cliente o IdCLIENTE." }
        $clients = Find-Client $cache $Cliente
        if ($clients.Count -eq 0) {
            Write-Host "No encontre cliente: $Cliente"
            return
        }
        if ($clients.Count -gt 1) {
            Write-Host "Hay varios clientes. Usa el IdCLIENTE:"
            $clients | Select-Object IdCLIENTE, RazonSocial | Format-Table -AutoSize
            return
        }

        $client = $clients[0]
        $id = [int]$client.IdCLIENTE
        Write-Host "Cliente: $($client.RazonSocial)"
        Write-Host "IdCLIENTE: $id"
        Write-Host "Fuente: cache local creado $($cache.Creado)"
        Write-Host ""
        $cache.Materiales |
            Where-Object { [int]$_.IdCLIENTE -eq $id } |
            Sort-Object @{ Expression = { [decimal]$_.CantidadTotal }; Descending = $true } |
            Select-Object -First $Top PRODUCTO, UNIDAD, CantidadTotal, Lineas, Subtotal |
            Format-Table -AutoSize
    }
}
