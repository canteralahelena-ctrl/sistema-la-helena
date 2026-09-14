param(
    [int]$Anio = (Get-Date).Year,
    [int]$Mes = (Get-Date).Month,
    [string]$OutCsv = "",
    [string]$OutResumen = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$hardeningHelper = Join-Path $PSScriptRoot "access_hardening.ps1"
. $hardeningHelper
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$outputs = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }

if (-not $OutCsv) {
    $OutCsv = Join-Path $outputs ("iva_mensual_{0:0000}-{1:00}_detalle.csv" -f $Anio, $Mes)
}
if (-not $OutResumen) {
    $OutResumen = Join-Path $outputs ("iva_mensual_{0:0000}-{1:00}_resumen.txt" -f $Anio, $Mes)
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutCsv), (Split-Path -Parent $OutResumen) | Out-Null

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Rows($recordset, [int]$maxRows = 100000) {
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

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function NzDecimal($value) {
    return ConvertTo-HelenaDecimal -Value $value -Field "IVA" -NullPolicy "ZERO" -Context "iva_mensual"
}

function Normalize-GastoIvaComputado([string]$tipo, [decimal]$iva) {
    $tipoNormalizado = ([string]$tipo).Trim().ToUpperInvariant()
    if ($tipoNormalizado -match '^NC') {
        return -[math]::Abs($iva)
    }
    return $iva
}

function Resolve-GastoTableName([string[]]$tableNames) {
    foreach ($candidate in @(
        "COMPROVANTES DE GASTOS",
        "COMPROBANTES DE GASTOS",
        "COMPROVANTES GASTOS",
        "COMPROBANTES GASTOS"
    )) {
        foreach ($tableName in $tableNames) {
            if ([string]::Equals($tableName, $candidate, [StringComparison]::OrdinalIgnoreCase)) {
                return $tableName
            }
        }
    }
    throw "No existe la tabla de comprobantes de gastos ni un alias conocido."
}

$desde = [datetime]::new($Anio, $Mes, 1)
$hasta = $desde.AddMonths(1)
$from = Date-Literal $desde
$to = Date-Literal $hasta

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $numeroColumn = "[N" + [char]186 + "]"
    $tableRows = $conn.OpenSchema(20)
    try {
        $tableNames = @()
        while (-not $tableRows.EOF) {
            $tableNames += [string]$tableRows.Fields.Item("TABLE_NAME").Value
            $tableRows.MoveNext()
        }
    }
    finally {
        if ($tableRows -and $tableRows.State -eq 1) { $tableRows.Close() }
    }
    $gastosTable = Resolve-GastoTableName $tableNames
    $gastosTableSql = "[" + $gastosTable.Replace("]", "]]" ) + "]"

    $ventasSql = @"
SELECT 'VENTA' AS Origen, IdCOMPROVANTE AS Id, FECHA, TIPO, $numeroColumn AS Numero,
       IdCLIENTE AS EntidadId, SUBTOTAL, IVA, IMPORTE, UserID
FROM COMPROVANTES
WHERE FECHA >= $from AND FECHA < $to
  AND TIPO <> 'RMT'
ORDER BY FECHA, TIPO, $numeroColumn
"@

    $gastosSql = @"
SELECT 'GASTO' AS Origen, IdGASTO AS Id, FECHA, TIPO, $numeroColumn AS Numero,
       IdPROVEEDOR AS EntidadId, Null AS SUBTOTAL, IVA, IMPORTE, UserID
FROM $gastosTableSql
WHERE FECHA >= $from AND FECHA < $to
ORDER BY FECHA, TIPO, $numeroColumn
"@

    $ventas = @(Rows ($conn.Execute($ventasSql)))
    $gastos = @(Rows ($conn.Execute($gastosSql)))

    $detalle = @()
    foreach ($v in $ventas) {
        $iva = NzDecimal $v.IVA
        $id = ConvertTo-HelenaInteger $v.Id "COMPROVANTES.IdCOMPROVANTE" "BLOCK" "iva_mensual"
        $fecha = ConvertTo-HelenaDate $v.FECHA "COMPROVANTES.FECHA" "BLOCK" "IdCOMPROVANTE=$id"
        $importe = ConvertTo-HelenaDecimal $v.IMPORTE "COMPROVANTES.IMPORTE" "ZERO" "IdCOMPROVANTE=$id"
        $detalle += [pscustomobject]@{
            Origen = "VENTA"
            Fecha = $fecha.ToString("yyyy-MM-dd")
            Tipo = $v.TIPO
            Numero = $v.Numero
            Id = $id
            EntidadId = $v.EntidadId
            IvaOriginal = $iva
            SignoAplicado = 1
            IvaComputado = $iva
            Importe = $importe
            UserID = $v.UserID
            Regla = "IVA ventas tomado como esta cargado en COMPROVANTES.IVA"
        }
    }

    foreach ($g in $gastos) {
        $iva = NzDecimal $g.IVA
        $id = ConvertTo-HelenaInteger $g.Id "COMPROVANTES DE GASTOS.IdGASTO" "BLOCK" "iva_mensual"
        $fecha = ConvertTo-HelenaDate $g.FECHA "COMPROVANTES DE GASTOS.FECHA" "BLOCK" "IdGASTO=$id"
        $importe = ConvertTo-HelenaDecimal $g.IMPORTE "COMPROVANTES DE GASTOS.IMPORTE" "ZERO" "IdGASTO=$id"
        $tipo = ([string]$g.TIPO).Trim().ToUpperInvariant()
        $ivaComputado = Normalize-GastoIvaComputado $tipo $iva
        $signo = if ($iva -eq 0) { 0 } elseif ($ivaComputado -lt 0) { -1 } else { 1 }
        $detalle += [pscustomobject]@{
            Origen = "GASTO"
            Fecha = $fecha.ToString("yyyy-MM-dd")
            Tipo = $g.TIPO
            Numero = $g.Numero
            Id = $id
            EntidadId = $g.EntidadId
            IvaOriginal = $iva
            SignoAplicado = $signo
            IvaComputado = $ivaComputado
            Importe = $importe
            UserID = $g.UserID
            Regla = if ($tipo -match '^NC') { "Nota de credito de gasto resta IVA credito" } else { "Factura/gasto suma IVA credito" }
        }
    }

    $ivaVentas = [decimal](($detalle | Where-Object Origen -eq "VENTA" | Measure-Object -Property IvaComputado -Sum).Sum)
    $ivaGastos = [decimal](($detalle | Where-Object Origen -eq "GASTO" | Measure-Object -Property IvaComputado -Sum).Sum)
    $saldo = $ivaVentas - $ivaGastos

    $detalle | Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8

    $ventasPorTipo = $detalle | Where-Object Origen -eq "VENTA" | Group-Object Tipo | ForEach-Object {
        [pscustomobject]@{ Tipo = $_.Name; Cantidad = $_.Count; IVA = [decimal](($_.Group | Measure-Object IvaComputado -Sum).Sum) }
    } | Sort-Object Tipo
    $gastosPorTipo = $detalle | Where-Object Origen -eq "GASTO" | Group-Object Tipo | ForEach-Object {
        [pscustomobject]@{ Tipo = $_.Name; Cantidad = $_.Count; IVA = [decimal](($_.Group | Measure-Object IvaComputado -Sum).Sum) }
    } | Sort-Object Tipo

    $lines = @()
    $lines += "Reporte IVA mensual"
    $lines += "Periodo: $($desde.ToString('MM/yyyy'))"
    $lines += ""
    $lines += "IVA ventas: $(Money $ivaVentas)"
    $lines += "IVA gastos: $(Money $ivaGastos)"
    $lines += "IVA ventas - IVA gastos: $(Money $saldo)"
    $lines += ""
    $lines += "Ventas por tipo:"
    foreach ($r in $ventasPorTipo) {
        $lines += "- $($r.Tipo): $($r.Cantidad) comprobantes, $(Money $r.IVA)"
    }
    $lines += ""
    $lines += "Gastos por tipo:"
    foreach ($r in $gastosPorTipo) {
        $lines += "- $($r.Tipo): $($r.Cantidad) comprobantes, $(Money $r.IVA)"
    }
    $lines += ""
    $lines += "Reglas:"
    $lines += "- Ventas: COMPROVANTES.IVA se toma con el signo cargado."
    $lines += "- RMT queda excluido porque no computa IVA."
    $lines += "- Gastos: COMPROVANTES DE GASTOS.IVA suma, salvo TIPO que empieza con NC, que resta."
    $lines += "- Este reporte es operativo; debe validarse con el contador antes de usarlo como liquidacion fiscal."
    $lines | Set-Content -LiteralPath $OutResumen -Encoding UTF8

    [pscustomobject]@{
        Periodo = $desde.ToString("yyyy-MM")
        IvaVentas = Money $ivaVentas
        IvaGastos = Money $ivaGastos
        SaldoIva = Money $saldo
        VentasComprobantes = $ventas.Count
        GastosComprobantes = $gastos.Count
        DetalleCsv = $OutCsv
        Resumen = $OutResumen
    }
}
catch {
    throw (Format-HelenaErrorDetail "iva" "generar_reporte_mensual" $_ @{Anio=$Anio;Mes=$Mes})
}
finally {
    if ($conn -and $conn.State -eq 1) { $conn.Close() }
}
