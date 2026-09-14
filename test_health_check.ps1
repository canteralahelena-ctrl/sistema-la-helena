$ErrorActionPreference = "Stop"

function Assert-Contains([string]$Text, [string]$Expected, [string]$Name) {
    if ($Text -notlike "*$Expected*") { throw "$Name - no se encontro '$Expected'" }
    Write-Host "OK - $Name"
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$fixture = Join-Path $tempBase ("helena_health_" + [guid]::NewGuid().ToString("N"))
try {
    $facturas = Join-Path $fixture "facturas"
    $remitos = Join-Path $fixture "remitos"
    New-Item -ItemType Directory -Force -Path $facturas, $remitos | Out-Null
    $pdf = Join-Path $facturas "prueba.pdf"
    [IO.File]::WriteAllBytes($pdf, [Text.Encoding]::ASCII.GetBytes("%PDF-1.4`nfixture"))
    $audio = Join-Path $fixture "audio.json"
    @{ openai_api_key = "fixture-no-real"; ffmpeg_path = (Get-Process -Id $PID).Path } |
        ConvertTo-Json | Set-Content -LiteralPath $audio -Encoding UTF8

    $hostExecutable = (Get-Process -Id $PID).Path
    $database = Join-Path $PSScriptRoot "data\test_database\CANTERA_LA_HELENA_TEST.accdb"
    $output = & $hostExecutable -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "health_check.ps1") `
        -Database $database -FacturasRoot $facturas -RemitosRoot $remitos -PdfPrueba $pdf -AudioConfig $audio 2>&1
    $exitCode = $LASTEXITCODE
    $text = @($output) -join "`n"

    if ($exitCode -ne 0) { throw "health_check controlado fallo ($exitCode): $text" }
    foreach ($line in @(
        "ACCESS: OK", "ESQUEMA: OK", "FACTURAS_ROOT: OK", "REMITOS_ROOT: OK",
        "PDF_PRUEBA: OK", "IVA: OK", "CARTERA: OK", "AUDITORIA_SECA: OK",
        "AUDIO_CONFIG: OK", "HEALTH_OK"
    )) {
        Assert-Contains $text $line $line
    }

    $missingRoot = Join-Path $fixture "raiz_inexistente"
    $failedOutput = & $hostExecutable -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "health_check.ps1") `
        -Database $database -FacturasRoot $missingRoot -RemitosRoot $remitos -AudioConfig $audio 2>&1
    $failedCode = $LASTEXITCODE
    $failedText = @($failedOutput) -join "`n"
    if ($failedCode -eq 0) { throw "health_check debio fallar con raiz inaccesible" }
    Assert-Contains $failedText "FACTURAS_ROOT: ERROR - RAIZ_INACCESIBLE" "raiz inaccesible visible"
    Assert-Contains $failedText "PDF_PRUEBA: ERROR - RAIZ_INACCESIBLE" "raiz inaccesible no se convierte en PDF faltante"
    Assert-Contains $failedText "HEALTH_ERROR" "estado final de error"
}
finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    if ($resolved.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($resolved).StartsWith("helena_health_", [StringComparison]::Ordinal)) {
        if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    }
}

Write-Host "PRUEBAS COMPLETADAS: health check controlado y raiz inaccesible."
