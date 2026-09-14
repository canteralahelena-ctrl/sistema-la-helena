param(
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$config = Join-Path $PSScriptRoot "telegram_bot_config.json"
$example = Join-Path $PSScriptRoot "telegram_bot_config.example.json"

if ($Setup -and -not (Test-Path -LiteralPath $config)) {
    Copy-Item -LiteralPath $example -Destination $config
    Write-Host "Config creado: $config"
    Write-Host "Editalo y pega el token de BotFather antes de iniciar el bot."
    return
}

if (-not (Test-Path -LiteralPath $config)) {
    throw "Falta $config. Ejecuta: .\work\iniciar_bot_telegram.ps1 -Setup"
}

& $python (Join-Path $PSScriptRoot "telegram_access_bot.py")
