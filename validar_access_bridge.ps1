param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge")

$ErrorActionPreference = "Stop"
$taskName = "LaHelena-AccessBridge"
$installFull = [IO.Path]::GetFullPath($InstallDir)
$appDir = Join-Path $installFull "app"
$python = Join-Path $installFull ".venv\Scripts\python.exe"
$config = Join-Path $installFull "bridge.json"
$wrapper = Join-Path $appDir "run_sync.ps1"
$taskLog = Join-Path $installFull "bridge-task.log"

foreach ($required in @($python, $config, $wrapper, (Join-Path $appDir "access_bridge\__init__.py"))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "El puente no está instalado correctamente." }
}
if (Test-Path -LiteralPath (Join-Path $appDir "access_bridge\access_bridge")) { throw "El despliegue contiene una anidación inválida." }

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $appDir
    $modulePath = (& $python -c "import access_bridge, pathlib; print(pathlib.Path(access_bridge.__file__).resolve())").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $modulePath.StartsWith([IO.Path]::GetFullPath($appDir), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Python no está cargando el código instalado."
    }
    $beforeJson = & $python -m access_bridge.cli diagnose --config $config
    if ($LASTEXITCODE -ne 0) { throw "Falló el diagnóstico previo." }
    $before = $beforeJson | ConvertFrom-Json
}
finally { $env:PYTHONPATH = $previousPythonPath }

$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
& $powershellExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $wrapper -InstallDir $installFull -Force
if ($LASTEXITCODE -ne 0) { throw "Falló la primera sincronización de validación." }

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $appDir
    $afterJson = & $python -m access_bridge.cli diagnose --config $config
    if ($LASTEXITCODE -ne 0) { throw "Falló el diagnóstico posterior." }
    $after = $afterJson | ConvertFrom-Json
}
finally { $env:PYTHONPATH = $previousPythonPath }
if (-not $after.last_sync -or $after.last_sync -eq $before.last_sync) { throw "No se registró un sync_run nuevo." }

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -eq "Disabled") { throw "La sincronización automática está deshabilitada." }
$previousRunTime = (Get-ScheduledTaskInfo -TaskName $taskName).LastRunTime
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $taskName
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
    $newRunObserved = $taskInfo.LastRunTime -gt $previousRunTime
} while ((-not $newRunObserved -or $task.State -eq "Running") -and (Get-Date) -lt $deadline)
if (-not $newRunObserved -or $task.State -eq "Running") { throw "La tarea no terminó dentro del plazo de validación." }
if ($taskInfo.LastTaskResult -ne 0) { throw "La tarea terminó con código $($taskInfo.LastTaskResult)." }
if (-not (Test-Path -LiteralPath $taskLog -PathType Leaf)) { throw "La tarea no generó su log operativo." }
$lastEvent = (Get-Content -LiteralPath $taskLog -Tail 1 -Encoding UTF8) | ConvertFrom-Json
if ($lastEvent.status -ne "skipped" -or $lastEvent.reason -ne "source_unchanged") {
    throw "La segunda ejecución no fue omitida pese a que el origen no cambió."
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $appDir
    $scheduledJson = & $python -m access_bridge.cli diagnose --config $config
    if ($LASTEXITCODE -ne 0) { throw "Falló el diagnóstico posterior a la tarea." }
    $scheduled = $scheduledJson | ConvertFrom-Json
}
finally { $env:PYTHONPATH = $previousPythonPath }
if (-not $scheduled.last_sync -or $scheduled.last_sync -le $after.last_sync) {
    throw "La tarea no registró la ejecución omitida en sync_runs."
}

Write-Host "VALIDACION_END_TO_END: OK" -ForegroundColor Green
Write-Host "CODIGO_INSTALADO: $modulePath"
Write-Host "NUEVO_SYNC_RUN: $($after.last_sync)"
Write-Host "LAST_TASK_RESULT: $($taskInfo.LastTaskResult)"
Write-Host "SEGUNDA_EJECUCION: skipped"
