param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
$config = Join-Path $InstallDir "bridge.json"
if (-not (Test-Path $python) -or -not (Test-Path $config)) { throw "El puente no está instalado." }
$env:PYTHONPATH = $root
& $python -m access_bridge.cli sync --config $config
if ($LASTEXITCODE) { throw "Falló la validación de sincronización." }
& $python -m access_bridge.cli diagnose --config $config
if ($LASTEXITCODE) { throw "Falló el diagnóstico end-to-end." }
$task = Get-ScheduledTask -TaskName "LaHelena-AccessBridge" -ErrorAction Stop
if ($task.State -eq "Disabled") { throw "La sincronización automática está deshabilitada." }
Write-Host "VALIDACION_END_TO_END: OK" -ForegroundColor Green
