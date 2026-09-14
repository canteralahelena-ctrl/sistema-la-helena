param(
    [switch]$IniciarTelegram,
    [string]$BaseLocal = ""
)

$ErrorActionPreference = "Stop"
$pilotRoot = $PSScriptRoot
$pilotData = Join-Path $pilotRoot "data\pilot"
$pilotOutputs = Join-Path $pilotRoot "outputs\pilot"
$pilotLogs = Join-Path $pilotRoot "logs\pilot"
$pilotConfig = Join-Path $pilotRoot "config\pilot.telegram.json"
$pilotSecrets = Join-Path $pilotRoot "config\pilot.secrets.json"
$pilotUsers = Join-Path $pilotRoot "config\pilot.telegram_usuarios.json"
$pilotPendingUsers = Join-Path $pilotData "telegram_pending_users.json"
$updateScript = Join-Path $pilotRoot "actualizar_copia_base.ps1"

function Test-ValidPythonExecutable([string]$Path) {
    if (-not $Path) {
        return $false
    }
    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    }
    catch {
        return $false
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        return $false
    }
    return ($resolved -notmatch "\\WindowsApps\\python(?:3)?\.exe$")
}

function Resolve-PilotPython {
    $candidates = @()
    if ($env:HELENA_PYTHON_EXECUTABLE) {
        if ($env:HELENA_PYTHON_EXECUTABLE -match "\\WindowsApps\\python(?:3)?\.exe$") {
            throw "Python no valido: se detecto el alias de WindowsApps. Defini HELENA_PYTHON_EXECUTABLE con una ruta real a python.exe."
        }
        if (Test-ValidPythonExecutable $env:HELENA_PYTHON_EXECUTABLE) {
            return (Resolve-Path -LiteralPath $env:HELENA_PYTHON_EXECUTABLE).Path
        }
        throw "HELENA_PYTHON_EXECUTABLE no apunta a un Python valido: $($env:HELENA_PYTHON_EXECUTABLE)"
    }

    foreach ($commandName in @("python.exe", "python3.exe", "python", "python3")) {
        $commands = @(Get-Command $commandName -ErrorAction SilentlyContinue)
        foreach ($command in $commands) {
            $candidates += [pscustomobject]@{
                Source = $commandName
                Path = $command.Source
            }
        }
    }

    $codexPython = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $codexPython -PathType Leaf) {
        $candidates += [pscustomobject]@{
            Source = "codex-runtime"
            Path = $codexPython
        }
    }

    $rejectedWindowsApps = @()
    foreach ($candidate in $candidates) {
        $candidatePath = [string]$candidate.Path
        if (-not $candidatePath) {
            continue
        }
        if ($candidatePath -match "\\WindowsApps\\python(?:3)?\.exe$") {
            $rejectedWindowsApps += $candidatePath
            continue
        }
        if (Test-ValidPythonExecutable $candidatePath) {
            return (Resolve-Path -LiteralPath $candidatePath).Path
        }
    }

    if ($rejectedWindowsApps.Count -gt 0) {
        throw "Python no valido: se detecto el alias de WindowsApps. Defini HELENA_PYTHON_EXECUTABLE con una ruta real a python.exe."
    }
    throw "No se encontro un Python valido. Defini HELENA_PYTHON_EXECUTABLE con la ruta completa a python.exe."
}

function Ensure-PilotOpenAIKey {
    if ($env:OPENAI_API_KEY) {
        return "ENTORNO"
    }

    $projectRoot = Split-Path -Parent $pilotRoot
    $productionConfig = Join-Path $projectRoot "work\telegram_bot_config.json"
    if (-not (Test-Path -LiteralPath $productionConfig -PathType Leaf)) {
        throw "Falta OPENAI_API_KEY en el entorno y no existe la configuracion operativa para reutilizar la clave de audio."
    }

    try {
        $config = Get-Content -LiteralPath $productionConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "No se pudo leer la configuracion operativa para reutilizar la clave de audio."
    }

    $key = [string]$config.openai_api_key
    if (-not $key) {
        throw "Falta OPENAI_API_KEY en el entorno y la configuracion operativa no tiene clave de audio."
    }

    $env:OPENAI_API_KEY = $key
    return "CONFIG_OPERATIVA"
}

function Ensure-PilotTelegramToken {
    if ($env:TELEGRAM_BOT_TOKEN) {
        return "ENTORNO"
    }

    if (-not (Test-Path -LiteralPath $pilotSecrets -PathType Leaf)) {
        throw "Falta TELEGRAM_BOT_TOKEN en el entorno. Configura el token piloto privado en work_v2\config\pilot.secrets.json."
    }

    try {
        $secrets = Get-Content -LiteralPath $pilotSecrets -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "No se pudo leer work_v2\config\pilot.secrets.json."
    }

    $token = [string]$secrets.telegram_bot_token
    if (-not $token) {
        throw "Falta TELEGRAM_BOT_TOKEN en el entorno y work_v2\config\pilot.secrets.json no tiene telegram_bot_token configurado."
    }

    $env:TELEGRAM_BOT_TOKEN = $token
    return "PILOT_SECRETS"
}

if (-not (Test-Path -LiteralPath $pilotSecrets -PathType Leaf)) {
    [pscustomobject]@{
        telegram_bot_token = ""
    } | ConvertTo-Json -Depth 2 | Set-Content -LiteralPath $pilotSecrets -Encoding UTF8
}

if (-not $BaseLocal) {
    $BaseLocal = Join-Path $pilotRoot "data\test_database\CANTERA_LA_HELENA_TEST.accdb"
}
$resolvedBaseParent = Split-Path -Parent $BaseLocal
if ($resolvedBaseParent -and -not (Test-Path -LiteralPath $resolvedBaseParent)) {
    New-Item -ItemType Directory -Force -Path $resolvedBaseParent | Out-Null
}
$resolvedBase = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BaseLocal)

Write-Host "Refresco seguro de copia local antes de activar modo piloto..."
try {
    $previousPilotMode = $env:HELENA_PILOT_MODE
    Remove-Item Env:\HELENA_PILOT_MODE -ErrorAction SilentlyContinue
    & powershell -NoProfile -ExecutionPolicy Bypass -File $updateScript -Destino $resolvedBase
    if ($LASTEXITCODE -ne 0) {
        throw "actualizar_copia_base.ps1 finalizo con codigo $LASTEXITCODE"
    }
}
catch {
    Write-Host "ADVERTENCIA: no se pudo refrescar la copia local antes del piloto. Detalle: $($_.Exception.Message)"
    if (Test-Path -LiteralPath $resolvedBase -PathType Leaf) {
        $localInfo = Get-Item -LiteralPath $resolvedBase
        Write-Host "ADVERTENCIA: se continuara con copia local existente: $($localInfo.LastWriteTime) tamano: $($localInfo.Length)"
    }
    else {
        throw "No existe copia local valida para continuar el piloto: $resolvedBase"
    }
}
finally {
    if ($previousPilotMode) {
        $env:HELENA_PILOT_MODE = $previousPilotMode
    }
    else {
        Remove-Item Env:\HELENA_PILOT_MODE -ErrorAction SilentlyContinue
    }
}

$resolvedBase = (Resolve-Path -LiteralPath $resolvedBase -ErrorAction Stop).Path

$env:HELENA_PILOT_MODE = "1"
$env:HELENA_PILOT_TELEGRAM = if ($IniciarTelegram) { "1" } else { "0" }
$env:HELENA_OUTPUTS_DIR = $pilotOutputs
$env:HELENA_LOGS_DIR = $pilotLogs
$env:HELENA_DATA_DIR = $pilotData
$env:HELENA_LOCAL_DATABASE = $resolvedBase
$env:HELENA_PRIVATE_CONFIG = $pilotConfig
$env:HELENA_TELEGRAM_USERS = $pilotUsers
$env:HELENA_TELEGRAM_PENDING_USERS = $pilotPendingUsers
$env:HELENA_LOCK_PORT = "47826"

Write-Host "work_v2 PILOTO - SOLO LECTURA"
Write-Host "Base local: $resolvedBase"
Write-Host "Outputs: $pilotOutputs"
Write-Host "Logs: $pilotLogs"
Write-Host "Data/PID: $pilotData"
Write-Host "Alertas automaticas: DESHABILITADAS"
Write-Host "Tareas programadas: DESHABILITADAS"
Write-Host "Escrituras Access/servidor: DESHABILITADAS"

if (-not $IniciarTelegram) {
    Write-Host "Validacion completada. Telegram no fue iniciado."
    exit 0
}

if (-not (Test-Path -LiteralPath $pilotConfig -PathType Leaf)) {
    throw "Falta config piloto separada: $pilotConfig"
}
if (-not (Test-Path -LiteralPath $pilotUsers -PathType Leaf)) {
    throw "Falta lista aislada de usuarios piloto: $pilotUsers"
}
$null = Ensure-PilotTelegramToken
$null = Ensure-PilotOpenAIKey

$python = Resolve-PilotPython
Write-Host "Python: $python"

New-Item -ItemType Directory -Force -Path $pilotData, $pilotOutputs, $pilotLogs | Out-Null
& $python (Join-Path $pilotRoot "telegram_access_bot.py")
exit $LASTEXITCODE
