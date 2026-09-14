$ErrorActionPreference = "Stop"

$workDir = $PSScriptRoot
$logPath = Join-Path $workDir "reiniciar_bot_telegram.log"
$stdoutPath = Join-Path $workDir "telegram_bot_stdout.log"
$stderrPath = Join-Path $workDir "telegram_bot_stderr.log"
$launcher = Join-Path $workDir "iniciar_bot_telegram.ps1"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

function Write-RestartLog([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

try {
    Set-Location -LiteralPath $workDir
    Write-RestartLog "Inicio wrapper. WorkDir=$workDir"

    Start-Sleep -Seconds 2

    $pythonProcesses = @(Get-Process python, pythonw -ErrorAction SilentlyContinue)
    if ($pythonProcesses.Count -gt 0) {
        Write-RestartLog ("Deteniendo python/pythonw: " + (($pythonProcesses | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ", "))
        $pythonProcesses | Stop-Process -Force
    } else {
        Write-RestartLog "No habia procesos python/pythonw activos."
    }

    Start-Sleep -Seconds 1

    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "No existe launcher: $launcher"
    }

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$launcher`""
    )

    $process = Start-Process `
        -FilePath $powershell `
        -ArgumentList $arguments `
        -WorkingDirectory $workDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    Write-RestartLog "Start-Process iniciado. PowerShell PID=$($process.Id)"
}
catch {
    Write-RestartLog "ERROR: $($_.Exception.Message)"
    throw
}
