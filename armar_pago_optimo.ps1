param(
    [Parameter(Mandatory = $true)]
    [decimal]$Importe,

    [int]$Dias = 0,

    [switch]$ACobrar,

    [ValidateSet("OPTIMO", "ECHEQ", "CHEQUE", "MIXTO")]
    [string]$Modo = "OPTIMO",

    [int]$Alternativas = 3,
    [int]$MaxCandidatos = 35,
    [int]$MaxValores = 8,
    [decimal]$ToleranciaImportePct = 10,
    [int]$ToleranciaDias = 15,
    [int]$MaxCombinaciones = 50000,
    [int]$MinDiasBusqueda = 60,
    [int]$MaxDiasBusqueda = 120,
    [int]$OptimizadorTimeout = 55,

    [ValidateSet("NN", "BLANCO", "TODOS")]
    [string]$FiltroFiscal = "TODOS"
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$dataScript = Join-Path $PSScriptRoot "gestion_cheques.ps1"
$optimizer = Join-Path $PSScriptRoot "combinar_pagos.py"
$tracePath = Join-Path $PSScriptRoot "pago_rapido_debug.log"
$jsonPath = Join-Path $env:TEMP ("pago_optimo_disponibles_{0}.json" -f ([guid]::NewGuid().ToString("N")))
$stdoutPath = Join-Path $env:TEMP ("pago_optimo_stdout_{0}.txt" -f ([guid]::NewGuid().ToString("N")))
$stderrPath = Join-Path $env:TEMP ("pago_optimo_stderr_{0}.txt" -f ([guid]::NewGuid().ToString("N")))

function Write-PagoTrace([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} armar_pago_optimo {1}" -f (Get-Date), $message
    try {
        Add-Content -LiteralPath $tracePath -Value $line -Encoding UTF8 -ErrorAction Stop
    } catch {
        Write-Verbose "No se pudo escribir trace de pago: $($_.Exception.Message)"
    }
}

function Assert-JsonCarteraActual([string]$path, [datetime]$startedAt) {
    $abortMessage = "No se pudo validar la cartera actual. No se generó propuesta de pago."
    try {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "No existe JSON."
        }
        $item = Get-Item -LiteralPath $path
        if ($item.Name -ieq "cheques_debug.json") {
            throw "JSON de debug no permitido."
        }
        if ($item.LastWriteTime -lt $startedAt.AddSeconds(-2)) {
            throw "JSON anterior a la ejecución actual."
        }
        $data = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $expectedDate = (Get-Date).Date.ToString("yyyy-MM-dd")
        if ([string]$data.FechaConsulta -ne $expectedDate) {
            throw "FechaConsulta inválida: $($data.FechaConsulta)"
        }
        if (-not ($data.PSObject.Properties.Name -contains "Registros")) {
            throw "El JSON no contiene Registros."
        }
    } catch {
        Write-PagoTrace "validacion cartera actual fallo: $($_.Exception.Message)"
        throw $abortMessage
    }
}

if ($Importe -le 0) {
    throw "El importe debe ser mayor a cero."
}
if (-not $ACobrar -and $Dias -le 0) {
    throw "Indica el plazo en dias. Ejemplo: pago optimo por 2.000.000 a 30 dias."
}
if ($MaxValores -le 0) {
    throw "MaxValores debe ser mayor a cero."
}

$tipo = switch ($Modo) {
    "ECHEQ" { "ECHEQ" }
    "CHEQUE" { "CHEQUE" }
    default { "TODOS" }
}

$diasBusqueda = if ($ACobrar) { 0 } else { [Math]::Max($MinDiasBusqueda, $Dias + ($ToleranciaDias * 2)) }
$diasBusqueda = if ($ACobrar) { 0 } else { [Math]::Min($MaxDiasBusqueda, $diasBusqueda) }
$accionCheques = if ($ACobrar) { "resumen" } else { "disponibles" }
$diasOptimizador = if ($ACobrar) { 0 } else { $Dias }
$fuenteOptimizador = if ($ACobrar) { "acobrar" } else { "dias" }

try {
    $executionStartedAt = Get-Date
    Write-PagoTrace "inicio comando Importe=$Importe Dias=$Dias ACobrar=$ACobrar Modo=$Modo FiltroFiscal=$FiltroFiscal MaxCandidatos=$MaxCandidatos MaxValores=$MaxValores MaxCombinaciones=$MaxCombinaciones"
    Write-PagoTrace "inicio gestion_cheques Accion=$accionCheques Tipo=$tipo DiasBusqueda=$diasBusqueda"
    & powershell -ExecutionPolicy Bypass -File $dataScript `
        -Accion $accionCheques `
        -Tipo $tipo `
        -Dias $diasBusqueda `
        -OutJson $jsonPath | Out-Null
    $carteraExitCode = $LASTEXITCODE
    $carteraJsonExiste = Test-Path -LiteralPath $jsonPath
    Write-PagoTrace "fin gestion_cheques ExitCode=$carteraExitCode JsonExiste=$carteraJsonExiste"

    if (-not $carteraJsonExiste) {
        throw "No se pudo preparar la cartera de cheques/eCheq."
    }
    Assert-JsonCarteraActual $jsonPath $executionStartedAt
    Write-PagoTrace "validacion cartera actual OK Json=$jsonPath"
    if ($carteraExitCode -ne 0) {
        Write-PagoTrace "gestion_cheques termino con ExitCode=$carteraExitCode despues de generar una cartera valida; se continua con el JSON validado"
    }

    Write-PagoTrace "inicio optimizador Timeout=$OptimizadorTimeout"
    $optimizerArgs = @(
        $optimizer,
        "--data", $jsonPath,
        "--target", ([double]$Importe),
        "--days", $diasOptimizador,
        "--source", $fuenteOptimizador,
        "--mode", $Modo,
        "--fiscal-filter", $FiltroFiscal,
        "--options", $Alternativas,
        "--max-candidates", $MaxCandidatos,
        "--max-values", $MaxValores,
        "--amount-tolerance-pct", ([double]$ToleranciaImportePct),
        "--day-tolerance", $ToleranciaDias,
        "--max-combinations", $MaxCombinaciones
    )
    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $python
    $processInfo.Arguments = (($optimizerArgs | ForEach-Object {
        '"' + ([string]$_).Replace('"', '\"') + '"'
    }) -join " ")
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $optimizerProcess = New-Object System.Diagnostics.Process
    $optimizerProcess.StartInfo = $processInfo
    [void]$optimizerProcess.Start()
    $finished = $optimizerProcess.WaitForExit($OptimizadorTimeout * 1000)
    if (-not $finished) {
        Stop-Process -Id $optimizerProcess.Id -Force -ErrorAction SilentlyContinue
        Write-PagoTrace "timeout optimizador PID=$($optimizerProcess.Id)"
        throw "La consulta de pago demoro demasiado y fue cancelada."
    }
    [System.IO.File]::WriteAllText($stdoutPath, $optimizerProcess.StandardOutput.ReadToEnd(), [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($stderrPath, $optimizerProcess.StandardError.ReadToEnd(), [System.Text.Encoding]::UTF8)
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
        if (-not $message) { $message = "No se pudo calcular la propuesta de pago." }
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
