param(
    [string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge",
    [switch]$EliminarConfiguracionPrivada
)

$ErrorActionPreference = "Stop"
$taskName = "LaHelena-AccessBridge"
$installFull = [IO.Path]::GetFullPath($InstallDir)
$sentinelPath = Join-Path $installFull ".lahelena-access-bridge.install.json"
if (-not (Test-Path -LiteralPath $sentinelPath -PathType Leaf)) {
    throw "Desinstalación cancelada: falta el marcador propio de LaHelenaAccessBridge."
}
$sentinel = Get-Content -LiteralPath $sentinelPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sentinel.product -ne "LaHelenaAccessBridge" -or [IO.Path]::GetFullPath([string]$sentinel.install_dir) -ne $installFull) {
    throw "Desinstalación cancelada: el marcador no coincide con el destino."
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    $expectedWrapper = Join-Path $installFull "app\run_sync.ps1"
    $matches = @($task.Actions | Where-Object { $_.Arguments -like "*$expectedWrapper*" }).Count -gt 0
    if (-not $matches) { throw "La tarea existente no pertenece a esta instalación; no se modificó." }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ($EliminarConfiguracionPrivada) {
    Remove-Item -LiteralPath $installFull -Recurse -Force
    Write-Host "DESINSTALACION_COMPLETA: OK"
}
else {
    foreach ($name in @("app", ".venv", "last-successful-source.json")) {
        $path = Join-Path $installFull $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    Write-Host "DESINSTALACION_OPERATIVA: OK. Se conservaron bridge.json, logs y el marcador."
    Write-Host "Use -EliminarConfiguracionPrivada para borrar también la configuración privada."
}
