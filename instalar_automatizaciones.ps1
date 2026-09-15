param([switch]$Desinstalar)

$ErrorActionPreference = "Stop"
$environmentPath = if ($env:HELENA_ENV_CONFIG) { $env:HELENA_ENV_CONFIG } else { Join-Path $PSScriptRoot "config\environment.json" }
$taskPrefix = "SistemaLaHelena"
$tasks = @(
    @{ Name = "$taskPrefix-AuditoriaSemanal"; Schedule = "WEEKLY"; Day = "MON"; Time = "08:00"; Automation = "auditoria" },
    @{ Name = "$taskPrefix-VencimientosCheques"; Schedule = "DAILY"; Day = $null; Time = "08:00"; Automation = "cheques" },
    @{ Name = "$taskPrefix-ResumenGerencial"; Schedule = "WEEKLY"; Day = "MON"; Time = "08:30"; Automation = "resumen-gerencial" }
)

if ($env:HELENA_PILOT_MODE -eq "1") { throw "Modo piloto: no se registran tareas programadas." }
if (-not (Test-Path -LiteralPath $environmentPath)) { throw "Falta config/environment.json; no se registraron tareas." }
$environment = Get-Content -LiteralPath $environmentPath -Raw | ConvertFrom-Json
if ($environment.environment -ne "production" -or $environment.scheduled_tasks_enabled -ne $true) {
    throw "Registro de tareas deshabilitado por configuracion."
}

foreach ($task in $tasks) {
    if ($Desinstalar) {
        & schtasks.exe /Delete /TN $task.Name /F 2>$null
        continue
    }
    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'ejecutar_automatizacion.ps1')`" -Automatizacion $($task.Automation)"
    $taskRun = "powershell.exe $argument"
    $parameters = @("/Create", "/TN", $task.Name, "/TR", $taskRun, "/SC", $task.Schedule, "/ST", $task.Time, "/F")
    if ($task.Day) { $parameters += @("/D", $task.Day) }
    & schtasks.exe @parameters
    if ($LASTEXITCODE -ne 0) { throw "No se pudo registrar $($task.Name)." }
}


