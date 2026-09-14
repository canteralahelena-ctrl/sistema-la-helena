param(
    [Parameter(Mandatory = $true)]
    [decimal]$Importe,
    [int]$Dias = 30,
    [int]$OptimizadorTimeout = 55
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$dataScript = Join-Path $PSScriptRoot "gestion_cheques.ps1"
$optimizer = Join-Path $PSScriptRoot "combinar_echeq.py"
$tracePath = Join-Path $PSScriptRoot "pago_rapido_debug.log"
$jsonPath = Join-Path $env:TEMP ("echeq_disponibles_{0}.json" -f ([guid]::NewGuid().ToString("N")))
$stdoutPath = Join-Path $env:TEMP ("echeq_optimizer_stdout_{0}.txt" -f ([guid]::NewGuid().ToString("N")))
$stderrPath = Join-Path $env:TEMP ("echeq_optimizer_stderr_{0}.txt" -f ([guid]::NewGuid().ToString("N")))

function Write-PagoTrace([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} armar_pago_echeq {1}" -f (Get-Date), $message
    try {
        Add-Content -LiteralPath $tracePath -Value $line -Encoding UTF8 -ErrorAction Stop
    } catch {
        Write-Verbose "No se pudo escribir trace de pago: $($_.Exception.Message)"
    }
}

try {
    Write-PagoTrace "inicio comando Importe=$Importe Dias=$Dias"
    Write-PagoTrace "inicio gestion_cheques"
    & powershell -ExecutionPolicy Bypass -File $dataScript `
        -Accion disponibles `
        -Tipo ECHEQ `
        -Dias $Dias `
        -OutJson $jsonPath | Out-Null
    Write-PagoTrace "fin gestion_cheques ExitCode=$LASTEXITCODE JsonExiste=$(Test-Path -LiteralPath $jsonPath)"

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $jsonPath)) {
        throw "No se pudo preparar la cartera de eCheq."
    }

    Write-PagoTrace "inicio optimizador Timeout=$OptimizadorTimeout"
    $optimizerProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @($optimizer, "--data", $jsonPath, "--target", ([double]$Importe)) `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    $finished = $optimizerProcess.WaitForExit($OptimizadorTimeout * 1000)
    if (-not $finished) {
        Stop-Process -Id $optimizerProcess.Id -Force -ErrorAction SilentlyContinue
        Write-PagoTrace "timeout optimizador PID=$($optimizerProcess.Id)"
        throw "La consulta de pago demoro demasiado y fue cancelada."
    }
    $optimizerProcess.Refresh()
    $exitCode = $optimizerProcess.ExitCode
    if ($null -eq $exitCode) { $exitCode = 0 }
    $stdout = ""
    if (Test-Path -LiteralPath $stdoutPath) { $stdout = [string](Get-Content -LiteralPath $stdoutPath -Raw -Encoding UTF8) }
    if ($null -eq $stdout) { $stdout = "" }
    $stderr = ""
    if (Test-Path -LiteralPath $stderrPath) { $stderr = [string](Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8) }
    if ($null -eq $stderr) { $stderr = "" }
    Write-PagoTrace "fin optimizador ExitCode=$exitCode"
    if ($exitCode -ne 0) {
        $message = $stderr.Trim()
        if (-not $message) { $message = "No se pudo calcular la combinacion de eCheq." }
        throw $message
    }
    [Console]::Out.Write($stdout)
}
finally {
    Write-PagoTrace "fin comando"
    if (Test-Path -LiteralPath $jsonPath) {
        Remove-Item -LiteralPath $jsonPath -Force
    }
    if (Test-Path -LiteralPath $stdoutPath) {
        Remove-Item -LiteralPath $stdoutPath -Force
    }
    if (Test-Path -LiteralPath $stderrPath) {
        Remove-Item -LiteralPath $stderrPath -Force
    }
}
