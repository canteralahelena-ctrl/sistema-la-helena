param(
    [ValidateSet("resumen", "depositables", "vencimientos", "disponibles", "alertas")]
    [string]$Accion = "resumen",
    [ValidateSet("TODOS", "CHEQUE", "ECHEQ")]
    [string]$Tipo = "TODOS",
    [ValidateSet("NN", "BLANCO", "TODOS")]
    [string]$FiltroFiscal = "TODOS",
    [int]$Dias = 30,
    [string]$OutJson = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$hardeningHelper = Join-Path $PSScriptRoot "access_hardening.ps1"
. $hardeningHelper
$dbPath = if ($env:HELENA_LOCAL_DATABASE) { $env:HELENA_LOCAL_DATABASE } else { Join-Path $root "CANTERA LA HELENA 1.0_be.accdb" }

function Date-Literal([datetime]$date) {
    return "#{0:MM/dd/yyyy}#" -f $date
}

function Money([decimal]$value) {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("es-AR")
    return $value.ToString("C2", $culture)
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

function Normalize-Type([string]$tipo) {
    if ($null -eq $tipo) { return "" }
    $normalized = ([string]$tipo).Normalize([Text.NormalizationForm]::FormD)
    $chars = $normalized.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne [Globalization.UnicodeCategory]::NonSpacingMark
    }
    $t = (-join $chars).Trim().ToUpperInvariant()
    if ($t -eq "CHEQUE") { return "CHEQUE FISICO" }
    if ($t -eq "CHEQUE FISICO") { return "CHEQUE FISICO" }
    if ($t -eq "ECHEQ") { return "ECHEQ" }
    if ($t -eq "E-CHEQ") { return "ECHEQ" }
    if ($t -eq "ECHEQUE") { return "ECHEQ" }
    if ($t -eq "E-CHEQUE") { return "ECHEQ" }
    if ($t -eq "ECHQ") { return "ECHEQ" }
    return $t
}

function Normalize-Observation($value) {
    if ($null -eq $value -or $value -is [System.DBNull]) { return "" }
    $text = [string]$value
    $normalized = $text.Normalize([Text.NormalizationForm]::FormD)
    $chars = $normalized.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne [Globalization.UnicodeCategory]::NonSpacingMark
    }
    return (-join $chars).Trim().ToUpperInvariant()
}

function Is-NN-Observation($value) {
    $text = Normalize-Observation $value
    foreach ($marker in @(
        "*",
        "NN",
        "EN CUENTA HUGO",
        "EN CUENTA GASTON",
        "EN CUENTA DE HUGO",
        "EN CUENTA DE GASTON",
        "CUENTA HUGO",
        "CUENTA GASTON",
        "CUNETA HUGO",
        "CUNETA GASTON"
    )) {
        if ($text -eq $marker) { return $true }
    }
    return $false
}

function Observation-Class($value) {
    $text = Normalize-Observation $value
    if (-not $text) { return "BLANCO" }
    if (Is-NN-Observation $value) { return "NN" }
    return "DESCONOCIDA"
}

function Passes-Fiscal-Filter($row, [string]$filter) {
    $class = Observation-Class $row.Observacion
    if ($filter -eq "TODOS") { return $class -in @("BLANCO", "NN") }
    if ($filter -eq "NN") { return $class -eq "NN" }
    if ($filter -eq "BLANCO") { return $class -eq "BLANCO" }
    return $false
}

function Fiscal-Label([string]$filter) {
    switch ($filter) {
        "NN" { "NN / sin factura" }
        "BLANCO" { "Blanco / con factura" }
        default { "Todos" }
    }
}

$today = (Get-Date).Date
$limit = $today.AddDays($Dias)
$from = Date-Literal $today
$to = Date-Literal $limit.AddDays(1)

$stateWhere = "AND E.ESTADO='EN CAJA'"

$typeWhere = switch ($Tipo) {
    "CHEQUE" { "AND E.TIPO IN ('CHEQUE','CHEQUE FISICO','CHEQUE FÍSICO')" }
    "ECHEQ" { "AND E.TIPO IN ('ECHEQ','E-CHEQ','ECHEQUE','E-CHEQUE','ECHQ')" }
    default { "AND E.TIPO IN ('CHEQUE','CHEQUE FISICO','CHEQUE FÍSICO','ECHEQ','E-CHEQ','ECHEQUE','E-CHEQUE','ECHQ')" }
}

$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$dbPath;Mode=Read;")
$recordset = $null

try {
    $baseSql = @"
SELECT E.IdENTREGA, E.IdPAGO, E.TIPO, E.ESTADO, E.BANCO, E.NUMERO,
       E.[FECHA A COBRAR] AS FechaCobro, E.IMPORTE, E.IdCLIENTE,
       C.[RAZ SOCIAL] AS Cliente, E.[DEPOSITADO EN] AS DepositadoEn,
       E.[FECHA DE ENDOSO] AS FechaEndoso, E.DESTINATARIO, E.UserID,
       E.OBSERVACION AS Observacion
FROM [DETALLE DE ENTREGAS] AS E
LEFT JOIN CLIENTES AS C ON E.IdCLIENTE=C.IdCLIENTE
WHERE 1=1
  $stateWhere
  $typeWhere
"@

    $recordset = $conn.Execute("$baseSql ORDER BY E.[FECHA A COBRAR], E.IdENTREGA")
    $all = Rows $recordset
    if ($recordset.State -eq 1) { $recordset.Close() }
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($recordset)
    $recordset = $null
    $report = @(foreach ($r in $all) {
        $idEntrega = ConvertTo-HelenaInteger $r.IdENTREGA "DETALLE DE ENTREGAS.IdENTREGA" "BLOCK" "gestion_cheques"
        $fecha = ConvertTo-HelenaDate $r.FechaCobro "DETALLE DE ENTREGAS.FECHA A COBRAR" "NULL" "IdENTREGA=$idEntrega"
        $importe = ConvertTo-HelenaDecimal $r.IMPORTE "DETALLE DE ENTREGAS.IMPORTE" "BLOCK" "IdENTREGA=$idEntrega"
        $diasRestantes = if ($fecha) { [int][math]::Floor(($fecha.Date - $today).TotalDays) } else { $null }
        $fechaVencimiento = if ($fecha) { $fecha.Date.AddDays(30) } else { $null }
        $diasAlVencimiento = if ($fechaVencimiento) {
            [int][math]::Floor(($fechaVencimiento - $today).TotalDays)
        } else {
            $null
        }
        $clienteTexto = if ($null -ne $r.Cliente -and -not ($r.Cliente -is [System.DBNull])) { ([string]$r.Cliente).Trim() } else { "" }
        $diagnosticoCliente = if ($clienteTexto) { "" } else { "CLIENTE_PENDIENTE" }
        $tramo = if (-not $fecha) {
            "SIN FECHA"
        } elseif ($diasRestantes -lt 0) {
            "VENCIDO"
        } elseif ($diasRestantes -le 7) {
            "0-7 DIAS"
        } elseif ($diasRestantes -le 15) {
            "8-15 DIAS"
        } elseif ($diasRestantes -le 30) {
            "16-30 DIAS"
        } else {
            "MAS DE 30 DIAS"
        }

        [pscustomobject]@{
            IdENTREGA = $idEntrega
            IdPAGO = $r.IdPAGO
            Tipo = Normalize-Type ([string]$r.TIPO)
            TipoOriginal = $r.TIPO
            Banco = $r.BANCO
            Numero = $r.NUMERO
            FechaCobro = if ($fecha) { $fecha.ToString("yyyy-MM-dd") } else { "" }
            FechaVencimiento = if ($fechaVencimiento) { $fechaVencimiento.ToString("yyyy-MM-dd") } else { "" }
            DiasRestantes = $diasRestantes
            DiasAlVencimiento = $diasAlVencimiento
            Tramo = $tramo
            Importe = $importe
            IdCLIENTE = $r.IdCLIENTE
            Cliente = $clienteTexto
            DiagnosticoCliente = $diagnosticoCliente
            Estado = $r.ESTADO
            DepositadoEn = $r.DepositadoEn
            FechaEndoso = $r.FechaEndoso
            Destinatario = $r.DESTINATARIO
            UserID = $r.UserID
            Observacion = $r.Observacion
        }
    })

    $report = @($report | Where-Object { Passes-Fiscal-Filter $_ $FiltroFiscal })

    $selected = switch ($Accion) {
        "depositables" {
            @($report | Where-Object {
                $null -ne $_.DiasRestantes -and
                $_.DiasRestantes -le 0 -and
                $_.DiasAlVencimiento -ge 0
            })
        }
        "alertas" {
            @($report | Where-Object {
                $null -ne $_.DiasAlVencimiento -and
                $_.DiasAlVencimiento -ge 0 -and
                $_.DiasAlVencimiento -le $Dias
            })
        }
        "vencimientos" {
            @($report | Where-Object {
                $null -ne $_.DiasRestantes -and
                $_.DiasRestantes -ge 0 -and
                $_.DiasRestantes -le $Dias
            })
        }
        "disponibles" {
            @($report | Where-Object {
                $null -ne $_.DiasRestantes -and
                $_.DiasRestantes -ge 0 -and
                $_.DiasRestantes -le $Dias
            })
        }
        default { @($report) }
    }

    if ($OutJson) {
        [pscustomobject]@{
            FechaConsulta = $today.ToString("yyyy-MM-dd")
            Dias = $Dias
            Tipo = $Tipo
            FiltroFiscal = $FiltroFiscal
            Registros = $selected
        } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutJson -Encoding UTF8
        return
    }

    if ($Accion -eq "resumen") {
        if ($report.Count -eq 0) {
            Write-Host "No hay valores para ese filtro."
            return
        }
        Write-Host "Cartera cheques/eCheq"
        Write-Host "Filtro: $(Fiscal-Label $FiltroFiscal)"
        Write-Host "Fecha: $($today.ToString('dd/MM/yyyy'))"
        Write-Host ""
        $classes = switch ($Tipo) {
            "CHEQUE" { @("CHEQUE FISICO") }
            "ECHEQ" { @("ECHEQ") }
            default { @("CHEQUE FISICO", "ECHEQ") }
        }
        foreach ($class in $classes) {
            $items = @($report | Where-Object { $_.Tipo -eq $class })
            $current = @($items | Where-Object { $_.Tramo -ne "SIN FECHA" -and $_.DiasAlVencimiento -ge 0 })
            $depositable = @($current | Where-Object { $_.DiasRestantes -le 0 })
            $future = @($current | Where-Object { $_.DiasRestantes -gt 0 })
            $oldData = @($items | Where-Object { $_.Tramo -eq "SIN FECHA" -or $_.DiasAlVencimiento -lt 0 })
            $total = ($current | Measure-Object -Property Importe -Sum).Sum
            $depositableTotal = ($depositable | Measure-Object -Property Importe -Sum).Sum
            $oldDataTotal = ($oldData | Measure-Object -Property Importe -Sum).Sum
            Write-Host "$class`: $($current.Count) en caja vigente, $(Money ([decimal]$total))"
            Write-Host "  A cobrar: $($depositable.Count), $(Money ([decimal]$depositableTotal))"
            foreach ($bucket in @("0-7 DIAS", "8-15 DIAS", "16-30 DIAS", "MAS DE 30 DIAS")) {
                $bucketItems = @($future | Where-Object { $_.Tramo -eq $bucket })
                $bucketTotal = ($bucketItems | Measure-Object -Property Importe -Sum).Sum
                Write-Host "  A depositar en $bucket`: $($bucketItems.Count), $(Money ([decimal]$bucketTotal))"
            }
            if ($oldData.Count -gt 0) {
                Write-Host "  Registros viejos EN CAJA a depurar: $($oldData.Count), $(Money ([decimal]$oldDataTotal))"
            }
        }
        $allCurrent = @($report | Where-Object { $_.Tramo -ne "SIN FECHA" -and $_.DiasAlVencimiento -ge 0 })
        $generalTotal = ($allCurrent | Measure-Object -Property Importe -Sum).Sum
        Write-Host ""
        Write-Host "Total cartera: $(Money ([decimal]$generalTotal))"
    }
    elseif ($Accion -eq "depositables") {
        if ($selected.Count -eq 0) {
            Write-Host "No hay valores para ese filtro."
            return
        }
        $total = ($selected | Measure-Object -Property Importe -Sum).Sum
        Write-Host "Disponible para depositar hoy"
        Write-Host "Filtro: $(Fiscal-Label $FiltroFiscal)"
        Write-Host "Fecha: $($today.ToString('dd/MM/yyyy'))"
        foreach ($class in @("CHEQUE FISICO", "ECHEQ")) {
            $items = @($selected | Where-Object { $_.Tipo -eq $class })
            $classTotal = ($items | Measure-Object -Property Importe -Sum).Sum
            Write-Host "$class`: $($items.Count), $(Money ([decimal]$classTotal))"
        }
        Write-Host "TOTAL: $(Money ([decimal]$total))"
    }
    elseif ($Accion -eq "alertas") {
        if ($selected.Count -eq 0) {
            Write-Host "SIN_ALERTAS"
        } else {
            $total = ($selected | Measure-Object -Property Importe -Sum).Sum
            Write-Host "Cheques proximos a vencer"
            Write-Host "Siguen EN CAJA y vencen legalmente dentro de $Dias dias."
            Write-Host "Total: $(Money ([decimal]$total))"
            Write-Host ""
            foreach ($item in ($selected | Sort-Object DiasAlVencimiento, FechaVencimiento, Tipo, Banco, Numero)) {
                $leyenda = if ($item.DiasAlVencimiento -eq 0) {
                    "VENCE HOY"
                } elseif ($item.DiasAlVencimiento -eq 1) {
                    "vence manana"
                } else {
                    "vence en $($item.DiasAlVencimiento) dias"
                }
                Write-Host "- $($item.Tipo) $($item.Banco) $($item.Numero) | $(Money $item.Importe) | cobro $(([datetime]$item.FechaCobro).ToString('dd/MM/yyyy')) | vencimiento $(([datetime]$item.FechaVencimiento).ToString('dd/MM/yyyy')) | $leyenda | $($item.Cliente)"
            }
        }
    }
    else {
        if ($selected.Count -eq 0) {
            Write-Host "No hay valores para ese filtro."
            return
        }
        $total = ($selected | Measure-Object -Property Importe -Sum).Sum
        Write-Host "$($selected.Count) cheques | Total: $(Money ([decimal]$total))"
        Write-Host "Desde hoy hasta $($limit.ToString('dd/MM/yyyy'))"
        Write-Host ""
        $selected |
            Select-Object Tipo, FechaCobro, DiasRestantes, Banco, Numero, Cliente, Importe |
            Format-Table -AutoSize
    }
}
catch {
    throw (Format-HelenaErrorDetail "cheques" $Accion $_)
}
finally {
    if ($recordset) {
        try { if ($recordset.State -eq 1) { $recordset.Close() } } catch {}
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($recordset)
    }
    if ($conn -and $conn.State -eq 1) { $conn.Close() }
    if ($conn) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($conn) }
}
