param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("auditoria", "cheques", "resumen-gerencial")]
    [string]$Automatizacion
)

$ErrorActionPreference = "Stop"
$environmentPath = if ($env:HELENA_ENV_CONFIG) { $env:HELENA_ENV_CONFIG } else { Join-Path $PSScriptRoot "config\environment.json" }

if ($env:HELENA_PILOT_MODE -eq "1") {
    throw "Modo piloto: las automatizaciones estan deshabilitadas."
}
if (-not (Test-Path -LiteralPath $environmentPath)) {
    throw "Falta config/environment.json; automatizacion cancelada."
}
$environment = Get-Content -LiteralPath $environmentPath -Raw | ConvertFrom-Json
if ($environment.environment -ne "production") {
    throw "Entorno no productivo: las automatizaciones estan deshabilitadas."
}
if ($environment.scheduled_tasks_enabled -ne $true -or $environment.automatic_alerts_enabled -ne $true) {
    throw "Automatizaciones o tareas programadas deshabilitadas por configuracion."
}

if ($Automatizacion -eq "auditoria") {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "auditoria_semanal_maxi.ps1") -EnviarMail
}
else {
    $python = if ($env:HELENA_PYTHON_EXECUTABLE) { $env:HELENA_PYTHON_EXECUTABLE } else { "python" }
    & $python (Join-Path $PSScriptRoot "ejecutar_automatizacion.py") $Automatizacion
}
if ($LASTEXITCODE -ne 0) {
    throw "La automatizacion $Automatizacion finalizo con codigo $LASTEXITCODE."
}
