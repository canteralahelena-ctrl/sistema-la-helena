param(
    [string]$TaskName = "LaHelenaTelegramAccessBot"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$botScript = Join-Path $PSScriptRoot "telegram_access_bot.py"
$logPath = Join-Path $PSScriptRoot "telegram_bot.log"
$errPath = Join-Path $PSScriptRoot "telegram_bot.err.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No encontre Python: $python"
}
if (-not (Test-Path -LiteralPath $botScript)) {
    throw "No encontre el bot: $botScript"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -Command `"& '$python' '$botScript' *> '$logPath' 2> '$errPath'`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Bot Telegram de consultas Access - Cantera La Helena" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Tarea instalada e iniciada: $TaskName"
Write-Host "Se ejecutara automaticamente al iniciar sesion en Windows."
Write-Host "Log: $logPath"
Write-Host "Errores: $errPath"
