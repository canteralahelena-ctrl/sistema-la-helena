$ErrorActionPreference = "Stop"

$workDir = $PSScriptRoot
$botScript = Join-Path $workDir "telegram_access_bot.py"
$launcher = Join-Path $workDir "iniciar_bot_telegram.ps1"
$logPath = Join-Path $workDir "watchdog_bot.log"
$stdoutPath = Join-Path $workDir "telegram_bot_stdout.log"
$stderrPath = Join-Path $workDir "telegram_bot_stderr.log"
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

function Write-WatchdogLog([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

try {
    Set-Location -LiteralPath $workDir

    $botPathPattern = [regex]::Escape($botScript)
    $botProcesses = @(
        Get-CimInstance Win32_Process -Filter "name='python.exe' or name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match $botPathPattern }
    )

    if ($botProcesses.Count -gt 0) {
        $pids = ($botProcesses | ForEach-Object { $_.ProcessId }) -join ","
        Write-WatchdogLog "OK bot activo. PID=$pids"
        exit 0
    }

    Write-WatchdogLog "RECUPERACION bot no activo. Iniciando launcher."

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

    Write-WatchdogLog "RECUPERACION lanzada. PowerShell PID=$($process.Id)"
}
catch {
    Write-WatchdogLog "ERROR $($_.Exception.Message)"
    throw
}
