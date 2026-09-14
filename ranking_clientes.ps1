param(
    [ValidateSet("mejores", "peores", "deuda-antigua", "compran-pagan-mal", "todos")]
    [string]$Accion = "mejores",
    [int]$Top = 10,
    [ValidateSet("", "3m", "6m", "1a", "3a", "personalizado")]
    [string]$Periodo = "",
    [datetime]$Desde = "1900-01-01",
    [datetime]$Hasta = "1900-01-01",
    [int]$DeudaVencidaDias = 30,
    [int]$MaxAntiguedadDeudaDias = 730,
    [decimal]$MinDeudaRiesgo = 10000,
    [int[]]$ExcluirMejoresIdCliente = @(183, 1274),
    [switch]$ExportCsv
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }
$outputs = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
}

function Pct([decimal]$value) {
    return ("{0:N1}%" -f ([double]$value * 100.0))
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

function NzDec($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return [decimal]0 }
    return [decimal]$value
}

function NzInt($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return 0 }
    return [int]$value
}

function Is-BlankDb($value) {
    return ($null -eq $value -or $value -is [DBNull])
}

function Normalize01([decimal]$value, [decimal]$min, [decimal]$max) {
    if ($max -le $min) {
        if ($value -gt 0) { return [decimal]1 }
        return [decimal]0
    }
    $n = ($value - $min) / ($max - $min)
    if ($n -lt 0) { return [decimal]0 }
    if ($n -gt 1) { return [decimal]1 }
    return [decimal]$n
}

function Risk-Level([decimal]$score, [decimal]$debt) {
    if ($debt -lt [decimal]10000) {
        if ($score -ge [decimal]0.35) { return "MEDIO" }
        return "BAJO"
    }
    if ($score -ge [decimal]0.70 -or $debt -ge [decimal]3000000) { return "CRITICO" }
    if ($score -ge [decimal]0.50 -or $debt -ge [decimal]1000000) { return "ALTO" }
    if ($score -ge [decimal]0.25 -or $debt -ge [decimal]300000) { return "MEDIO" }
    return "BAJO"
}

function Best-Client-Category([decimal]$score) {
    if ($score -ge [decimal]0.90) { return "AAA" }
    if ($score -ge [decimal]0.75) { return "AA" }
    if ($score -ge [decimal]0.60) { return "A" }
    return "B"
}

function Risk-Rank([string]$level) {
    switch ($level) {
        "CRITICO" { return 4 }
        "ALTO" { return 3 }
        "MEDIO" { return 2 }
        default { return 1 }
    }
}

function Cap-Risk-Level([string]$level, [string]$maxLevel) {
    if ((Risk-Rank $level) -gt (Risk-Rank $maxLevel)) { return $maxLevel }
    return $level
}

function Worst-Risk-Policy($row, [decimal]$score, [string]$baseRisk) {
    $debt = [decimal]$row.DeudaVencidaNumero
    $age = [int]$row.DiasDeudaContinuaActual
    $count = [int]$row.CantidadComprobantes
    $unpaidCount = [int]$row.CantidadComprobantesImpagos
    $risk = "BAJO"
    $notes = @()

    if ($debt -ge [decimal]3000000) {
        $risk = "CRITICO"
        $notes += "Critico por deuda mayor a `$3.000.000"
    }
    elseif ($debt -ge [decimal]1000000 -and $age -ge 180) {
        $risk = "CRITICO"
        $notes += "Critico por deuda mayor a `$1.000.000 y mora prolongada"
    }
    elseif (($debt -ge [decimal]1000000 -and $age -ge 60) -or ($debt -ge [decimal]2000000)) {
        $risk = "ALTO"
        $notes += "Alto por deuda importante y mora"
    }
    elseif ($debt -ge [decimal]1000000 -and $age -lt 60) {
        $risk = "MEDIO"
        $notes += "Medio por deuda importante reciente"
    }

    if ($unpaidCount -ge 2) { $notes += "Riesgo por conducta repetida" }
    if ($notes.Count -eq 0) { $notes += "Riesgo operativo" }

    [pscustomobject]@{
        Nivel = $risk
        Observacion = (($notes | Select-Object -Unique) -join "; ")
    }
}

function Resolve-Period {
    $today = (Get-Date).Date
    $to = if ($Hasta -ne [datetime]"1900-01-01") { $Hasta.Date.AddDays(1) } else { $today.AddDays(1) }
    $from = $Desde

    if ($Periodo -and $Periodo -ne "personalizado") {
        switch ($Periodo) {
            "3m" { $from = $today.AddMonths(-3) }
            "6m" { $from = $today.AddMonths(-6) }
            "1a" { $from = $today.AddYears(-1) }
            "3a" { $from = $today.AddYears(-3) }
        }
    }
    elseif ($from -eq [datetime]"1900-01-01") {
        $from = $today.AddMonths(-3)
    }

    [pscustomobject]@{
        Desde = $from.Date
        HastaExclusivo = $to
        HastaVisible = $to.AddDays(-1)
    }
}

function Month-Key([datetime]$date) {
    return "{0:0000}-{1:00}" -f $date.Year, $date.Month
}

function Months-In-Period([datetime]$from, [datetime]$toExclusive) {
    $months = (($toExclusive.Year - $from.Year) * 12) + ($toExclusive.Month - $from.Month)
    if ($toExclusive.Day -gt 1) { $months += 1 }
    if ($months -lt 1) { return 1 }
    return $months
}

$period = Resolve-Period
$fromLit = Date-Literal $period.Desde
$toLit = Date-Literal $period.HastaExclusivo
$today = (Get-Date).Date
$monthsInPeriod = Months-In-Period $period.Desde $period.HastaExclusivo

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")

try {
    $clientes = Rows ($conn.Execute("SELECT IdCLIENTE, [RAZ SOCIAL] AS RazonSocial, CUIT, LOCALIDAD FROM CLIENTES"))

    $compsPeriodoSql = @"
SELECT IdCOMPROVANTE, IdCLIENTE, FECHA, TIPO, IMPORTE, SALDO
FROM COMPROVANTES
WHERE FECHA >= $fromLit AND FECHA < $toLit
"@
    $compsPeriodo = Rows ($conn.Execute($compsPeriodoSql))

    $compsAbiertos = Rows ($conn.Execute("SELECT IdCOMPROVANTE, IdCLIENTE, FECHA, TIPO, IMPORTE, SALDO FROM COMPROVANTES WHERE SALDO<>0"))
    $pagosAbiertos = Rows ($conn.Execute("SELECT IdCLIENTE, SALDO FROM PAGOS WHERE SALDO<>0"))
    $movComps = Rows ($conn.Execute("SELECT IdCLIENTE, FECHA, IMPORTE FROM COMPROVANTES WHERE FECHA < $toLit"))
    $movPagos = Rows ($conn.Execute("SELECT IdCLIENTE, FECHA, MONTO AS IMPORTE FROM PAGOS WHERE FECHA < $toLit"))

    $detPagoSql = @"
SELECT DP.IdDETPAGO, DP.IdPAGO, DP.IdCOMPROVANTE, DP.IMPORTE AS ImporteAplicado,
       P.FECHA AS FechaPago, C.FECHA AS FechaComprobante, C.IdCLIENTE
FROM (DETPAGO AS DP
INNER JOIN PAGOS AS P ON DP.IdPAGO = P.IdPAGO)
INNER JOIN COMPROVANTES AS C ON DP.IdCOMPROVANTE = C.IdCOMPROVANTE
WHERE C.FECHA >= $fromLit AND C.FECHA < $toLit
"@
    $detPagos = Rows ($conn.Execute($detPagoSql))

    $stats = @{}
    foreach ($c in $clientes) {
        $id = [int]$c.IdCLIENTE
        $stats[$id] = [ordered]@{
            IdCLIENTE = $id
            RazonSocial = [string]$c.RazonSocial
            CUIT = $c.CUIT
            Localidad = $c.LOCALIDAD
            TotalVendido = [decimal]0
            CantidadComprobantes = 0
            MesesCompra = @{}
            PagoAplicadoPeriodo = [decimal]0
            DelayWeightedSum = [decimal]0
            DelayWeight = [decimal]0
            DiasMaxDemora = 0
            SaldoDebeActual = [decimal]0
            SaldoHaberActual = [decimal]0
            SaldoDebeConsiderado = [decimal]0
            DeudaPeriodo = [decimal]0
            DeudaVencida = [decimal]0
            AntiguedadDeudaVieja = 0
            AntiguedadDeudaConsiderada = 0
            FechaComprobanteAbiertoMasViejo = $null
            TienePagosAplicados = $false
            TienePagoPosteriorAComprobanteAbierto = $false
            CantidadComprobantesImpagos = 0
            MovimientosCuenta = @()
            DiasDeudaContinuaActual = 0
        }
    }

    foreach ($c in $compsPeriodo) {
        if (Is-BlankDb $c.IdCLIENTE) { continue }
        $id = [int]$c.IdCLIENTE
        if (-not $stats.Contains($id)) { continue }
        $s = $stats[$id]
        $fecha = [datetime]$c.FECHA
        $s.TotalVendido += NzDec $c.IMPORTE
        $s.CantidadComprobantes += 1
        $s.MesesCompra[(Month-Key $fecha)] = $true
        $s.DeudaPeriodo += NzDec $c.SALDO
    }

    foreach ($c in $compsAbiertos) {
        if (Is-BlankDb $c.IdCLIENTE) { continue }
        $id = [int]$c.IdCLIENTE
        if (-not $stats.Contains($id)) { continue }
        $s = $stats[$id]
        $saldo = NzDec $c.SALDO
        $fecha = [datetime]$c.FECHA
        $age = [int]($today - $fecha.Date).TotalDays
        $s.SaldoDebeActual += $saldo
        if ($age -gt $s.AntiguedadDeudaVieja) { $s.AntiguedadDeudaVieja = $age }
        if ($age -le $MaxAntiguedadDeudaDias) {
            $s.SaldoDebeConsiderado += $saldo
            if ($saldo -gt 0) { $s.CantidadComprobantesImpagos += 1 }
            if ($age -gt $s.AntiguedadDeudaConsiderada) {
                $s.AntiguedadDeudaConsiderada = $age
                $s.FechaComprobanteAbiertoMasViejo = $fecha.Date
            }
            if ($age -gt $DeudaVencidaDias) { $s.DeudaVencida += $saldo }
        }
    }

    foreach ($p in $pagosAbiertos) {
        if (Is-BlankDb $p.IdCLIENTE) { continue }
        $idText = [string]$p.IdCLIENTE
        $id = 0
        if (-not [int]::TryParse($idText, [ref]$id)) { continue }
        if (-not $stats.Contains($id)) { continue }
        $stats[$id].SaldoHaberActual += NzDec $p.SALDO
    }

    foreach ($m in $movComps) {
        if (Is-BlankDb $m.IdCLIENTE) { continue }
        $id = [int]$m.IdCLIENTE
        if (-not $stats.Contains($id)) { continue }
        $importe = NzDec $m.IMPORTE
        if ($importe -eq 0) { continue }
        $stats[$id].MovimientosCuenta += [pscustomobject]@{
            Fecha = ([datetime]$m.FECHA).Date
            Orden = 1
            Importe = $importe
        }
    }

    foreach ($m in $movPagos) {
        if (Is-BlankDb $m.IdCLIENTE) { continue }
        $idText = [string]$m.IdCLIENTE
        $id = 0
        if (-not [int]::TryParse($idText, [ref]$id)) { continue }
        if (-not $stats.Contains($id)) { continue }
        $importe = [math]::Abs([double](NzDec $m.IMPORTE))
        if ($importe -le 0) { continue }
        $stats[$id].MovimientosCuenta += [pscustomobject]@{
            Fecha = ([datetime]$m.FECHA).Date
            Orden = 0
            Importe = [decimal](-1 * $importe)
        }
    }

    foreach ($entry in $stats.GetEnumerator()) {
        $s = $entry.Value
        $saldoCc = [decimal]0
        $inicioDeudaContinua = $null
        # Access no aporta hora confiable en estos movimientos; se usa FECHA y, a igual fecha, pagos antes que comprobantes.
        foreach ($m in @($s.MovimientosCuenta | Sort-Object Fecha, Orden)) {
            $saldoAnterior = $saldoCc
            $saldoCc += [decimal]$m.Importe
            if ($saldoCc -le 0) {
                $inicioDeudaContinua = $null
            }
            elseif ($saldoAnterior -le 0 -and $saldoCc -gt 0) {
                $inicioDeudaContinua = $m.Fecha
            }
        }
        if ($null -ne $inicioDeudaContinua) {
            $s.DiasDeudaContinuaActual = [int]($today - $inicioDeudaContinua.Date).TotalDays
        }
    }

    foreach ($dp in $detPagos) {
        if (Is-BlankDb $dp.IdCLIENTE) { continue }
        $id = [int]$dp.IdCLIENTE
        if (-not $stats.Contains($id)) { continue }
        $s = $stats[$id]
        $importe = [math]::Abs([double](NzDec $dp.ImporteAplicado))
        if ($importe -le 0) { continue }
        $fechaPago = [datetime]$dp.FechaPago
        $fechaComp = [datetime]$dp.FechaComprobante
        $s.TienePagosAplicados = $true
        if ($null -ne $s.FechaComprobanteAbiertoMasViejo -and $fechaPago.Date -gt $s.FechaComprobanteAbiertoMasViejo) {
            $s.TienePagoPosteriorAComprobanteAbierto = $true
        }
        $dias = [int]($fechaPago.Date - $fechaComp.Date).TotalDays
        if ($dias -lt 0) { $dias = 0 }
        $s.PagoAplicadoPeriodo += [decimal]$importe
        $s.DelayWeightedSum += [decimal]($dias * $importe)
        $s.DelayWeight += [decimal]$importe
        if ($dias -gt $s.DiasMaxDemora) { $s.DiasMaxDemora = $dias }
    }

    $raw = foreach ($entry in $stats.GetEnumerator()) {
        $s = $entry.Value
        $saldoActual = $s.SaldoDebeActual - $s.SaldoHaberActual
        $saldoConsiderado = [decimal][math]::Max([double]0, [double]($s.SaldoDebeConsiderado - $s.SaldoHaberActual))
        $avgDelayExact = if ($s.DelayWeight -gt 0) { $s.DelayWeightedSum / $s.DelayWeight } else { [decimal]0 }
        $delayForScore = if ($s.DelayWeight -gt 0) { $avgDelayExact } elseif ($saldoConsiderado -gt 0) { [decimal]$s.AntiguedadDeudaConsiderada } else { [decimal]0 }
        $paidPct = if ($s.TotalVendido -gt 0) { $s.PagoAplicadoPeriodo / $s.TotalVendido } else { [decimal]0 }
        $regularity = if ($monthsInPeriod -gt 0) { [decimal]$s.MesesCompra.Count / [decimal]$monthsInPeriod } else { [decimal]0 }
        $deudaVencidaAjustada = [decimal][math]::Min([double]([math]::Max([double]0, [double]$saldoConsiderado)), [double]([math]::Max([double]0, [double]$s.DeudaVencida)))
        if ($deudaVencidaAjustada -lt $MinDeudaRiesgo) {
            $deudaVencidaAjustada = [decimal]0
        }
        $debtRatio = if ($s.TotalVendido -gt 0) { [math]::Max([double]0, [double]$deudaVencidaAjustada) / [double]$s.TotalVendido } elseif ($deudaVencidaAjustada -gt 0) { 1.0 } else { 0.0 }

        [pscustomobject]@{
            IdCLIENTE = $s.IdCLIENTE
            Cliente = $s.RazonSocial
            Localidad = $s.Localidad
            TotalVendidoNumero = [decimal]$s.TotalVendido
            CantidadComprobantes = [int]$s.CantidadComprobantes
            CantidadComprobantesImpagos = [int]$s.CantidadComprobantesImpagos
            PromedioMensualNumero = if ($monthsInPeriod -gt 0) { [decimal]$s.TotalVendido / [decimal]$monthsInPeriod } else { [decimal]0 }
            PagoAplicadoNumero = [decimal]$s.PagoAplicadoPeriodo
            SaldoActualNumero = [decimal]$saldoActual
            SaldoConsideradoNumero = [decimal]$saldoConsiderado
            DeudaPeriodoNumero = [decimal]$s.DeudaPeriodo
            DeudaVencidaNumero = [decimal]$deudaVencidaAjustada
            DiasPromedioPagoNumero = [decimal]$avgDelayExact
            DiasPenalizacionNumero = [decimal]$delayForScore
            DiasMaxDemora = [int]$s.DiasMaxDemora
            AntiguedadDeudaVieja = [int]$s.AntiguedadDeudaVieja
            AntiguedadDeudaConsiderada = [int]$s.AntiguedadDeudaConsiderada
            DiasDeudaContinuaActual = [int]$s.DiasDeudaContinuaActual
            AdvertenciaAntiguedad = if ($s.TienePagosAplicados -or $s.TienePagoPosteriorAComprobanteAbierto) { "Puede no representar deuda continua" } else { "Sin advertencia" }
            PorcentajePagadoNumero = [decimal]$paidPct
            RegularidadNumero = [decimal]$regularity
            DeudaVentasNumero = [decimal]$debtRatio
            TieneDemoraExacta = ($s.DelayWeight -gt 0)
        }
    }

    $candidates = @($raw | Where-Object { $_.TotalVendidoNumero -gt 0 -or $_.SaldoActualNumero -gt 0 })

    $maxSales = [decimal](($candidates | Measure-Object TotalVendidoNumero -Maximum).Maximum)
    $minSales = [decimal](($candidates | Measure-Object TotalVendidoNumero -Minimum).Minimum)
    $maxDelay = [decimal](($candidates | Measure-Object DiasPenalizacionNumero -Maximum).Maximum)
    $minDelay = [decimal](($candidates | Measure-Object DiasPenalizacionNumero -Minimum).Minimum)
    $maxDebtRatio = [decimal](($candidates | Measure-Object DeudaVentasNumero -Maximum).Maximum)
    $minDebtRatio = [decimal](($candidates | Measure-Object DeudaVentasNumero -Minimum).Minimum)
    $maxDebt = [decimal](($candidates | Measure-Object DeudaVencidaNumero -Maximum).Maximum)
    $minDebt = [decimal]0
    $maxAge = [decimal](($candidates | Measure-Object AntiguedadDeudaConsiderada -Maximum).Maximum)
    $maxContinuousAge = [decimal](($candidates | Measure-Object DiasDeudaContinuaActual -Maximum).Maximum)

    $scored = foreach ($r in $candidates) {
        $volumeScore = Normalize01 $r.TotalVendidoNumero $minSales $maxSales
        $delayNorm = Normalize01 $r.DiasPenalizacionNumero $minDelay $maxDelay
        $speedScore = if ($r.TieneDemoraExacta) { [decimal]1 - $delayNorm } else { [decimal]1 }
        $debtRatioNorm = Normalize01 $r.DeudaVentasNumero $minDebtRatio $maxDebtRatio
        $debtAbsNorm = Normalize01 ([math]::Max([double]0, [double]$r.DeudaVencidaNumero)) $minDebt $maxDebt
        $lowDebtScore = [decimal]1 - (([decimal]0.60 * $debtAbsNorm) + ([decimal]0.40 * $debtRatioNorm))
        $saldoActualNorm = Normalize01 ([math]::Max([double]0, [double]$r.SaldoActualNumero)) 0 $maxDebt
        $saldoActualScore = [decimal]1 - $saldoActualNorm
        $regularityScore = if ($r.RegularidadNumero -gt 1) { [decimal]1 } else { [decimal]$r.RegularidadNumero }

        $debtScore = Normalize01 ([math]::Max([double]0, [double]$r.DeudaVencidaNumero)) $minDebt $maxDebt
        $ageForRisk = if ($r.DeudaVencidaNumero -gt 0) { [decimal]$r.AntiguedadDeudaConsiderada } else { [decimal]0 }
        $delayForRisk = if ($r.DeudaVencidaNumero -gt 0) { $delayNorm } else { [decimal]0 }
        $ageScore = Normalize01 $ageForRisk 0 $maxAge
        $badDelayScore = $delayForRisk
        $badRatioScore = $debtRatioNorm
        $continuousAgeForRisk = if ($r.DeudaVencidaNumero -gt 0) { [decimal]$r.DiasDeudaContinuaActual } else { [decimal]0 }
        $continuousAgeScore = Normalize01 $continuousAgeForRisk 0 $maxContinuousAge
        $badDelayScorePeores = if ($r.TieneDemoraExacta) { $delayNorm } else { $continuousAgeScore }

        $best = ([decimal]0.70 * $volumeScore) + ([decimal]0.20 * $speedScore) + ([decimal]0.10 * $saldoActualScore)
        $worst = ([decimal]0.40 * $debtScore) + ([decimal]0.25 * $ageScore) + ([decimal]0.15 * $badDelayScore) + ([decimal]0.20 * $badRatioScore)
        $worstPeores = ([decimal]0.40 * $debtScore) + ([decimal]0.25 * $continuousAgeScore) + ([decimal]0.15 * $badDelayScorePeores) + ([decimal]0.20 * $badRatioScore)
        $riskLevel = Risk-Level $worst $r.DeudaVencidaNumero

        $delayLabel = if ($r.TieneDemoraExacta) { "pago promedio $([math]::Round([double]$r.DiasPromedioPagoNumero,1)) dias" } else { "sin demora exacta; penaliza deuda considerada $($r.AntiguedadDeudaConsiderada) dias" }
        $reasonBest = "ventas $(Money $r.TotalVendidoNumero); $delayLabel; saldo real $(Money $r.SaldoActualNumero); deuda vencida considerada $(Money $r.DeudaVencidaNumero); regularidad $(Pct $r.RegularidadNumero)"
        $reasonWorst = "riesgo $riskLevel; saldo real $(Money $r.SaldoActualNumero); deuda vencida considerada $(Money $r.DeudaVencidaNumero); deuda continua actual $($r.DiasDeudaContinuaActual) dias; comprobante abierto mas viejo $($r.AntiguedadDeudaConsiderada) dias; $delayLabel; deuda vencida/ventas $(Pct $r.DeudaVentasNumero)"

        $r | Add-Member -NotePropertyName ScoreComercialNumero -NotePropertyValue ([decimal](($volumeScore * [decimal]0.80) + ($regularityScore * [decimal]0.20))) -Force
        $r | Add-Member -NotePropertyName ScoreFinancieroNumero -NotePropertyValue ([decimal](($speedScore * [decimal]0.60) + ($lowDebtScore * [decimal]0.40))) -Force
        $r | Add-Member -NotePropertyName ScoreMejorNumero -NotePropertyValue ([decimal]$best) -Force
        $r | Add-Member -NotePropertyName CategoriaCliente -NotePropertyValue (Best-Client-Category $best) -Force
        $r | Add-Member -NotePropertyName ScorePeorNumero -NotePropertyValue ([decimal]$worst) -Force
        $r | Add-Member -NotePropertyName ScorePeorContinuoNumero -NotePropertyValue ([decimal]$worstPeores) -Force
        $worstRiskPolicy = Worst-Risk-Policy $r $worstPeores $riskLevel
        $r | Add-Member -NotePropertyName NivelRiesgoPeores -NotePropertyValue $worstRiskPolicy.Nivel -Force
        $r | Add-Member -NotePropertyName OrdenRiesgoPeores -NotePropertyValue (Risk-Rank $worstRiskPolicy.Nivel) -Force
        $r | Add-Member -NotePropertyName NivelRiesgo -NotePropertyValue $riskLevel -Force
        $r | Add-Member -NotePropertyName MotivoMejor -NotePropertyValue $reasonBest -Force
        $r | Add-Member -NotePropertyName MotivoPeor -NotePropertyValue $reasonWorst -Force
        $r
    }

    $selected = switch ($Accion) {
        "mejores" {
            $scored |
                Where-Object { $_.TotalVendidoNumero -gt 0 -and $_.IdCLIENTE -notin $ExcluirMejoresIdCliente -and ($_.PagoAplicadoNumero -gt 0 -or $_.SaldoActualNumero -le 0) } |
                Sort-Object @{Expression="ScoreMejorNumero"; Descending=$true}, @{Expression="TotalVendidoNumero"; Descending=$true} |
                Select-Object -First $Top
        }
        "peores" {
            $scored |
                Where-Object {
                    $_.SaldoActualNumero -gt 0 -and
                    $_.DeudaVencidaNumero -ge [decimal]1000000
                } |
                Sort-Object @{Expression="OrdenRiesgoPeores"; Descending=$true}, @{Expression="DeudaVencidaNumero"; Descending=$true} |
                Select-Object -First $Top
        }
        "deuda-antigua" {
            $scored |
                Where-Object { $_.SaldoConsideradoNumero -gt 0 } |
                Sort-Object @{Expression="AntiguedadDeudaConsiderada"; Descending=$true}, @{Expression="SaldoConsideradoNumero"; Descending=$true} |
                Select-Object -First $Top
        }
        "compran-pagan-mal" {
            $scored |
                Where-Object { $_.TotalVendidoNumero -gt 0 -and $_.DeudaVencidaNumero -gt 0 } |
                Sort-Object @{Expression="TotalVendidoNumero"; Descending=$true}, @{Expression="ScorePeorNumero"; Descending=$true} |
                Select-Object -First $Top
        }
        "todos" {
            $scored |
                Sort-Object @{Expression="ScorePeorNumero"; Descending=$true}, @{Expression="SaldoConsideradoNumero"; Descending=$true}, Cliente |
                Select-Object -First $Top
        }
    }

    Write-Host "Ranking de clientes: $Accion"
    Write-Host "Periodo: $($period.Desde.ToString('dd/MM/yyyy')) al $($period.HastaVisible.ToString('dd/MM/yyyy'))"
    Write-Host "Criterio deuda vencida operativa: comprobante abierto con mas de $DeudaVencidaDias dias desde FECHA."
    Write-Host "Deudas abiertas con mas de $MaxAntiguedadDeudaDias dias no se consideran para el score."
    Write-Host "Demora de pago: usa DETPAGO cuando existe imputacion; si no hay demora exacta y hay deuda, usa antiguedad de deuda como penalizacion."
    Write-Host "Deudas vencidas menores a $(Money $MinDeudaRiesgo) no se consideran riesgo operativo."
    Write-Host "Registros evaluados: $($candidates.Count)"
    Write-Host ""

    $display = foreach ($r in $selected) {
        $scoreFinal = if ($Accion -eq "mejores") { $r.ScoreMejorNumero } elseif ($Accion -eq "compran-pagan-mal") { $r.ScorePeorNumero } elseif ($Accion -eq "deuda-antigua") { $r.AntiguedadDeudaConsiderada / [math]::Max(1, [double]$maxAge) } elseif ($Accion -eq "peores") { $r.ScorePeorContinuoNumero } else { $r.ScorePeorNumero }
        $riskPolicy = if ($Accion -eq "peores") { Worst-Risk-Policy $r $r.ScorePeorContinuoNumero $r.NivelRiesgo } else { [pscustomobject]@{ Nivel = $r.NivelRiesgo; Observacion = "" } }
        [pscustomobject]@{
            Cliente = $r.Cliente
            Vendido = Money $r.TotalVendidoNumero
            PagadoAplicado = Money $r.PagoAplicadoNumero
            SaldoActual = Money $r.SaldoActualNumero
            SaldoConsiderado = Money $r.SaldoConsideradoNumero
            DeudaVencida = Money $r.DeudaVencidaNumero
            DiasDeudaContinuaActual = $r.DiasDeudaContinuaActual
            ComprobanteAbiertoMasViejoDias = $r.AntiguedadDeudaConsiderada
            AdvertenciaAntiguedad = if ($Accion -eq "peores") { $r.AdvertenciaAntiguedad } else { "" }
            ScoreFinal = [math]::Round([double]($scoreFinal * 100), 1)
            CategoriaCliente = if ($Accion -eq "mejores") { $r.CategoriaCliente } else { "" }
            NivelRiesgo = $riskPolicy.Nivel
            Observacion = $riskPolicy.Observacion
            Motivo = if ($Accion -eq "mejores") { $r.MotivoMejor } else { "$($r.MotivoPeor); observacion: $($riskPolicy.Observacion)" }
        }
    }

    if ($Accion -eq "peores") {
        $display | Select-Object Cliente, Vendido, SaldoActual, DeudaVencida, DiasDeudaContinuaActual, NivelRiesgo, Observacion | Format-Table -AutoSize -Wrap
    }
    else {
        $display | Select-Object Cliente, Vendido, PagadoAplicado, SaldoActual, ScoreFinal, CategoriaCliente | Format-Table -AutoSize -Wrap
    }

    Write-Host ""
    Write-Host "Motivos:"
    $n = 1
    foreach ($row in $display) {
        Write-Host ("{0}. {1}: {2}" -f $n, $row.Cliente, $row.Motivo)
        $n += 1
    }

    if ($ExportCsv) {
        if (-not (Test-Path -LiteralPath $outputs)) { New-Item -ItemType Directory -Path $outputs | Out-Null }
        $suffix = "{0}_{1}_{2}_{3}" -f $Accion, $period.Desde.ToString("yyyy-MM-dd"), $period.HastaVisible.ToString("yyyy-MM-dd"), (Get-Date).ToString("HHmmss")
        $csvPath = Join-Path $outputs ("ranking_clientes_{0}.csv" -f $suffix)
        $selected |
            Select-Object IdCLIENTE, Cliente, Localidad,
                @{Name="TotalVendido"; Expression={$_.TotalVendidoNumero}},
                CantidadComprobantes,
                @{Name="PromedioMensual"; Expression={$_.PromedioMensualNumero}},
                @{Name="PagoAplicadoPeriodo"; Expression={$_.PagoAplicadoNumero}},
                @{Name="SaldoActual"; Expression={$_.SaldoActualNumero}},
                @{Name="SaldoConsiderado"; Expression={$_.SaldoConsideradoNumero}},
                @{Name="DeudaPeriodo"; Expression={$_.DeudaPeriodoNumero}},
                @{Name="DeudaVencida"; Expression={$_.DeudaVencidaNumero}},
                @{Name="MinDeudaRiesgo"; Expression={$MinDeudaRiesgo}},
                @{Name="DiasPromedioPago"; Expression={$_.DiasPromedioPagoNumero}},
                @{Name="DiasPenalizacionScore"; Expression={$_.DiasPenalizacionNumero}},
                DiasMaxDemora,
                AntiguedadDeudaVieja,
                AntiguedadDeudaConsiderada,
                @{Name="PorcentajePagado"; Expression={$_.PorcentajePagadoNumero}},
                @{Name="DeudaSobreVentas"; Expression={$_.DeudaVentasNumero}},
                @{Name="ScoreComercial"; Expression={$_.ScoreComercialNumero}},
                @{Name="ScoreFinanciero"; Expression={$_.ScoreFinancieroNumero}},
                @{Name="ScoreMejor"; Expression={$_.ScoreMejorNumero}},
                @{Name="ScorePeor"; Expression={$_.ScorePeorNumero}},
                NivelRiesgo,
                TieneDemoraExacta |
            Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding UTF8
        Write-Host ""
        Write-Host "CSV exportado: $csvPath"
    }
}
finally {
    if ($conn.State -eq 1) { $conn.Close() }
}
