param(
    [datetime]$FechaReferencia = (Get-Date),
    [switch]$EnviarMail,
    [switch]$RecuperarPendientes,
    [switch]$SoloListarPendientes,
    [switch]$MarcarPendientesComoResueltas
)

$ErrorActionPreference = "Stop"

if ($env:HELENA_PILOT_MODE -eq "1") {
    throw "Modo piloto: las auditorias automaticas estan deshabilitadas."
}

$root = Split-Path -Parent $PSScriptRoot
$outputsDir = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
$python = if ($env:HELENA_PYTHON_EXECUTABLE) { $env:HELENA_PYTHON_EXECUTABLE } else { "python" }
$estadoPath = Join-Path $PSScriptRoot "auditoria_semanal_maxi_estado.json"
$auditUsers = @(
    [pscustomobject]@{ Id = 1; Nombre = "Gaston"; Label = "Usuario 1 / Gaston"; Prefix = "auditoria_usuario_1_gaston" },
    [pscustomobject]@{ Id = 2; Nombre = "Hugo"; Label = "Usuario 2 / Hugo"; Prefix = "auditoria_usuario_2_hugo" },
    [pscustomobject]@{ Id = 3; Nombre = "Maxi"; Label = "Usuario 3 / Maxi"; Prefix = "auditoria_usuario_3_maxi" }
)

function Get-PreviousMonday([datetime]$date) {
    $today = $date.Date
    $daysSinceMonday = (([int]$today.DayOfWeek + 6) % 7)
    $thisMonday = $today.AddDays(-$daysSinceMonday)
    return $thisMonday.AddDays(-7)
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [string]$ErrorMessage = "Fallo un comando requerido."
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage Codigo de salida: $LASTEXITCODE"
    }
}

function Read-AuditState {
    if (-not (Test-Path -LiteralPath $estadoPath)) {
        return [pscustomobject]@{
            version = 1
            envios = @()
        }
    }

    $state = Get-Content -LiteralPath $estadoPath -Raw | ConvertFrom-Json
    if ($null -eq $state.envios) {
        $state | Add-Member -NotePropertyName envios -NotePropertyValue @()
    }
    return $state
}

function Write-AuditState($state) {
    $state | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $estadoPath -Encoding UTF8
}

function Get-WeekKey([datetime]$from, [datetime]$toExclusive) {
    return "{0}_{1}" -f $from.ToString("yyyy-MM-dd"), $toExclusive.AddDays(-1).ToString("yyyy-MM-dd")
}

function Get-RecentCompletedWeeks([datetime]$date, [int]$count = 4) {
    $previousMonday = Get-PreviousMonday $date
    $weeks = @()
    for ($i = $count - 1; $i -ge 0; $i--) {
        $from = $previousMonday.AddDays(-7 * $i)
        $toExclusive = $from.AddDays(7)
        $weekKey = Get-WeekKey $from $toExclusive
        $weeks += [pscustomobject]@{
            Desde = $from
            Hasta = $toExclusive
            Semana = $weekKey
        }
    }
    return $weeks
}

function Test-WeekSent($state, [string]$weekKey) {
    return @($state.envios | Where-Object { $_.semana_auditada -eq $weekKey -and $_.resultado -eq "enviado" }).Count -gt 0
}

function Get-WeekStatus($state, [string]$weekKey) {
    $entry = @($state.envios | Where-Object { $_.semana_auditada -eq $weekKey } | Select-Object -Last 1)
    if ($entry.Count -eq 0) {
        return "pendiente"
    }
    return [string]$entry[0].resultado
}

function Test-WeekResolved($state, [string]$weekKey) {
    return (Get-WeekStatus $state $weekKey) -in @("enviado", "resuelto_manual")
}

function Get-MailRecipient {
    $configPath = Join-Path $PSScriptRoot "email_config.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return ""
    }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    return [string]$config.to
}

function Register-WeekSent($state, [string]$weekKey, [datetime]$from, [datetime]$toExclusive, [string[]]$xlsxPaths) {
    $resolved = @($xlsxPaths | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
    $entry = [pscustomobject]@{
        semana_auditada = $weekKey
        fecha_desde = $from.ToString("yyyy-MM-dd")
        fecha_hasta = $toExclusive.AddDays(-1).ToString("yyyy-MM-dd")
        fecha_hora_envio = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        archivo_excel_enviado = ($resolved -join " | ")
        archivos_excel_enviados = $resolved
        resultado = "enviado"
        destinatario = Get-MailRecipient
    }

    $state.envios = @($state.envios | Where-Object { $_.semana_auditada -ne $weekKey -or $_.resultado -ne "enviado" })
    $state.envios += $entry
    Write-AuditState $state
}

function Get-AuditSuffix([datetime]$from, [datetime]$toExclusive) {
    return "{0}_{1}" -f $from.ToString("yyyy-MM-dd"), $toExclusive.AddDays(-1).ToString("yyyy-MM-dd")
}

function Get-AuditXlsxPath($user, [string]$suffix) {
    return Join-Path $outputsDir ("{0}_{1}.xlsx" -f $user.Prefix, $suffix)
}

function Invoke-AuditUser {
    param(
        [Parameter(Mandatory = $true)]
        [object]$User,
        [Parameter(Mandatory = $true)]
        [datetime]$Desde,
        [Parameter(Mandatory = $true)]
        [datetime]$Hasta
    )

    $suffix = Get-AuditSuffix $Desde $Hasta
    Write-Host "Generando auditoria: $($User.Label)"
    $null = Invoke-Checked -ErrorMessage "No se pudo generar la auditoria de $($User.Label)." -Command {
        $auditArgs = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (Join-Path $PSScriptRoot "auditoria_usuario_3.ps1"),
            "-Desde",
            $Desde,
            "-Hasta",
            $Hasta,
            "-UsuarioId",
            $User.Id
        )
        if ($User.Nombre) {
            $auditArgs += @("-UsuarioNombre", $User.Nombre)
        }
        & powershell @auditArgs
    }
    $null = Invoke-Checked -ErrorMessage "No se pudo generar el Excel de $($User.Label)." -Command {
        & $python (Join-Path $PSScriptRoot "generar_excel_auditoria.py") --prefix $User.Prefix --suffix $suffix
    }

    $xlsx = Get-AuditXlsxPath $User $suffix
    if (-not (Test-Path -LiteralPath $xlsx)) {
        throw "No se genero el Excel esperado para $($User.Label): $xlsx"
    }
    $item = Get-Item -LiteralPath $xlsx
    if ($item.Length -le 0) {
        throw "Excel vacio para $($User.Label): $xlsx"
    }

    [pscustomobject]@{
        UsuarioId = $User.Id
        Usuario = $User.Label
        Archivo = $item.FullName
        Bytes = $item.Length
    }
}

function Apply-MaxiWidthTemplate {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Results,
        [Parameter(Mandatory = $true)]
        [datetime]$Desde,
        [Parameter(Mandatory = $true)]
        [datetime]$Hasta
    )

    $suffix = Get-AuditSuffix $Desde $Hasta
    $maxi = @($Results | Where-Object { $_.UsuarioId -eq 3 } | Select-Object -First 1)
    if ($maxi.Count -eq 0) {
        throw "No se puede normalizar formato: falta planilla de Usuario 3 / Maxi."
    }
    $template = $maxi[0].Archivo
    foreach ($result in @($Results | Where-Object { $_.UsuarioId -ne 3 })) {
        $user = @($auditUsers | Where-Object { $_.Id -eq $result.UsuarioId } | Select-Object -First 1)[0]
        Invoke-Checked -ErrorMessage "No se pudo normalizar formato de $($result.Usuario)." -Command {
            & $python (Join-Path $PSScriptRoot "generar_excel_auditoria.py") --prefix $user.Prefix --suffix $suffix --width-template $template
        } | Out-Null
        $item = Get-Item -LiteralPath $result.Archivo
        $result.Bytes = $item.Length
    }
}

function Register-WeekManualResolved($state, [string]$weekKey, [datetime]$from, [datetime]$toExclusive) {
    $entry = [pscustomobject]@{
        semana_auditada = $weekKey
        fecha_desde = $from.ToString("yyyy-MM-dd")
        fecha_hasta = $toExclusive.AddDays(-1).ToString("yyyy-MM-dd")
        fecha_hora_resolucion = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        resultado = "resuelto_manual"
        nota = "Auditoria realizada manualmente durante desarrollo"
    }

    $state.envios = @($state.envios | Where-Object { $_.semana_auditada -ne $weekKey })
    $state.envios += $entry
    Write-AuditState $state
}

function Invoke-AuditWeek {
    param(
        [Parameter(Mandatory = $true)]
        [datetime]$Desde,
        [Parameter(Mandatory = $true)]
        [datetime]$Hasta,
        [Parameter(Mandatory = $true)]
        [object]$State
    )

    $weekKey = Get-WeekKey $Desde $Hasta

    if ($EnviarMail -and (Test-WeekSent $State $weekKey)) {
        Write-Host "Semana evaluada: $weekKey - ya enviada"
        return
    }

    Write-Host "Auditoria semanal usuarios Access"
    Write-Host "Periodo: $($Desde.ToString('yyyy-MM-dd')) al $($Hasta.AddDays(-1).ToString('yyyy-MM-dd'))"

    Invoke-Checked -ErrorMessage "No se pudo actualizar la copia local; auditoria pendiente." -Command {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "actualizar_copia_base.ps1")
    }

    $results = @()
    $failures = @()
    foreach ($user in $auditUsers) {
        try {
            $results += Invoke-AuditUser -User $user -Desde $Desde -Hasta $Hasta
        }
        catch {
            $failures += [pscustomobject]@{
                UsuarioId = $user.Id
                Usuario = $user.Label
                Error = $_.Exception.Message
            }
            Write-Host "FALLO $($user.Label): $($_.Exception.Message)"
        }
    }

    $results | Select-Object UsuarioId, Usuario, Archivo, Bytes | Format-Table -AutoSize
    if ($failures.Count -gt 0) {
        $failures | Select-Object UsuarioId, Usuario, Error | Format-Table -AutoSize
    }

    if ($results.Count -ne $auditUsers.Count) {
        throw "No se generaron las 3 auditorias requeridas. Generadas: $($results.Count). Fallas: $($failures.Count)."
    }

    Apply-MaxiWidthTemplate -Results $results -Desde $Desde -Hasta $Hasta

    if ($EnviarMail) {
        $attachments = @($results | Sort-Object UsuarioId | ForEach-Object { $_.Archivo })
        $subject = "Auditoria usuarios Access - {0} al {1}" -f $Desde.ToString("dd/MM/yyyy"), $Hasta.AddDays(-1).ToString("dd/MM/yyyy")
        $body = @"
Auditoria semanal de usuarios Access.

Periodo: $($Desde.ToString("dd/MM/yyyy")) al $($Hasta.AddDays(-1).ToString("dd/MM/yyyy"))

Se adjuntan las auditorias separadas de:

- Usuario 1 / Gaston
- Usuario 2 / Hugo
- Usuario 3 / Maxi
"@
        Invoke-Checked -ErrorMessage "No se pudo enviar el mail; auditoria pendiente." -Command {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "enviar_mail_auditoria.ps1") -Adjuntos ($attachments -join "|") -Asunto $subject -Cuerpo $body
        }
        Register-WeekSent $State $weekKey $Desde $Hasta $attachments
        Write-Host "Semana evaluada: $weekKey - enviada OK"
    }
}

$state = Read-AuditState

if ($RecuperarPendientes) {
    $weeks = Get-RecentCompletedWeeks $FechaReferencia 4
    $pendingWeeks = @()

    foreach ($week in $weeks) {
        $status = Get-WeekStatus $state $week.Semana
        if (Test-WeekResolved $state $week.Semana) {
            Write-Host "Semana evaluada: $($week.Semana) - $status"
        }
        else {
            Write-Host "Semana evaluada: $($week.Semana) - pendiente"
            $pendingWeeks += $week
        }
    }

    if ($MarcarPendientesComoResueltas) {
        foreach ($week in $pendingWeeks) {
            Register-WeekManualResolved $state $week.Semana $week.Desde $week.Hasta
            Write-Host "Semana marcada: $($week.Semana) - resuelto_manual"
        }
        Write-Host "Pendientes marcadas como resueltas: $($pendingWeeks.Count)"
        exit 0
    }

    if ($SoloListarPendientes -or -not $EnviarMail) {
        if (-not $SoloListarPendientes -and -not $EnviarMail) {
            Write-Host "Modo recuperacion sin -EnviarMail: no se generan archivos ni se envian mails."
        }
        Write-Host "Pendientes: $($pendingWeeks.Count)"
        exit 0
    }

    foreach ($week in $pendingWeeks) {
        Invoke-AuditWeek -Desde $week.Desde -Hasta $week.Hasta -State $state
    }
    exit 0
}

$desde = Get-PreviousMonday $FechaReferencia
$hasta = $desde.AddDays(7)
Invoke-AuditWeek -Desde $desde -Hasta $hasta -State $state
