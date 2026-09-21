param(
    [string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$appDir = Join-Path $InstallDir "app"
$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
$configPath = Join-Path $InstallDir "bridge.json"
$taskLog = Join-Path $InstallDir "bridge-task.log"
$mutex = New-Object System.Threading.Mutex($false, "Local\LaHelenaAccessBridgeSync")
$lockTaken = $false

function Write-TaskEvent([hashtable]$Event) {
    $Event["timestamp"] = [DateTime]::UtcNow.ToString("o")
    Add-Content -LiteralPath $taskLog -Value ($Event | ConvertTo-Json -Compress) -Encoding UTF8
}

try {
    $lockTaken = $mutex.WaitOne(0)
    if (-not $lockTaken) {
        Write-TaskEvent @{ status = "skipped"; reason = "already_running"; exit_code = 0 }
        exit 0
    }
    foreach ($required in @($appDir, $python, $configPath)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Instalación incompleta: falta un componente requerido." }
    }

    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $appDir
        $syncArguments = @("-m", "access_bridge.cli", "sync", "--config", $configPath)
        if ($Force) { $syncArguments += "--force" }
        $output = @(& $python @syncArguments 2>&1)
        $code = $LASTEXITCODE
    }
    finally {
        $env:PYTHONPATH = $previousPythonPath
    }
    if ($code -ne 0) {
        Write-TaskEvent @{ status = "error"; reason = "sync_failed"; exit_code = $code }
        exit $code
    }

    $result = (($output | Out-String).Trim()) | ConvertFrom-Json
    if ($result.status -notin @("ok", "skipped")) { throw "La sincronización devolvió un estado inválido." }
    if ($result.status -eq "skipped") {
        Write-TaskEvent @{ status = "skipped"; reason = "source_unchanged"; exit_code = 0 }
    }
    else {
        Write-TaskEvent @{ status = "ok"; exit_code = 0 }
    }
    if ($output) { $output | Write-Output }
    exit 0
}
catch {
    Write-TaskEvent @{ status = "error"; reason = "wrapper_failed"; message = $_.Exception.Message; exit_code = 1 }
    Write-Error $_.Exception.Message
    exit 1
}
finally {
    if ($lockTaken) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
