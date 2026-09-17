param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge", [switch]$EliminarConfiguracionPrivada)
$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName "LaHelena-AccessBridge" -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path $InstallDir) {
    if ($EliminarConfiguracionPrivada) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
    else {
        Remove-Item -LiteralPath (Join-Path $InstallDir ".venv") -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Se conservó bridge.json para evitar perder secretos. Use -EliminarConfiguracionPrivada para borrarlo."
    }
}
Write-Host "ROLLBACK_LOCAL: OK"
