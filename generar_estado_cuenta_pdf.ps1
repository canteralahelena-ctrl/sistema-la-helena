param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Cliente,
    [Parameter(Mandatory = $true)]
    [datetime]$Desde,
    [datetime]$Hasta = [datetime]::MaxValue,
    [string]$NombreArchivo = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$outputs = if ($env:HELENA_OUTPUTS_DIR) { $env:HELENA_OUTPUTS_DIR } else { Join-Path $PSScriptRoot "outputs" }
$python = "C:\USUARIO_EJEMPLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$dataScript = Join-Path $PSScriptRoot "estado_pdf_data.ps1"
$pdfScript = Join-Path $PSScriptRoot "generar_estado_pdf.py"
$logo = Join-Path $PSScriptRoot "assets\LOgoTIPO.jpg"
$background = Join-Path $PSScriptRoot "assets\cantera_fondo.jpg"
$template = Join-Path $PSScriptRoot "assets\estado_cuenta_fondo_aprobado.png"

function Safe-Name([string]$value) {
    $safe = $value.ToLowerInvariant()
    $safe = $safe -replace '[^a-z0-9]+', '_'
    $safe = $safe.Trim('_')
    if (-not $safe) { return "cliente" }
    return $safe
}

if (-not (Test-Path -LiteralPath $outputs)) {
    New-Item -ItemType Directory -Path $outputs | Out-Null
}

$stamp = if ($Hasta -lt [datetime]::MaxValue) {
    "{0}_a_{1}" -f $Desde.ToString("yyyy-MM-dd"), $Hasta.ToString("yyyy-MM-dd")
} else {
    $Desde.ToString("yyyy-MM-dd")
}
$baseName = if ($NombreArchivo) {
    $NombreArchivo
} else {
    "estado_{0}_{1}.pdf" -f (Safe-Name $Cliente), $stamp
}

if (-not $baseName.EndsWith(".pdf", [StringComparison]::OrdinalIgnoreCase)) {
    $baseName += ".pdf"
}

$jsonPath = Join-Path $env:TEMP ("estado_cuenta_{0}_{1}.json" -f (Safe-Name $Cliente), ([guid]::NewGuid().ToString("N")))
$pdfPath = Join-Path $outputs $baseName

try {
    $dataArgs = @($Cliente, "-Desde", $Desde, "-OutFile", $jsonPath)
    if ($Hasta -lt [datetime]::MaxValue) {
        $dataArgs += @("-Hasta", $Hasta)
    }
    & powershell -ExecutionPolicy Bypass -File $dataScript @dataArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $jsonPath)) {
        throw "No se pudo generar la informacion del estado de cuenta."
    }
    & $python $pdfScript --data $jsonPath --out $pdfPath --logo $logo --background $background --template $template
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pdfPath)) {
        throw "No se pudo generar el PDF del estado de cuenta."
    }
    Get-Item -LiteralPath $pdfPath | Select-Object FullName, Length, LastWriteTime
}
finally {
    if (Test-Path -LiteralPath $jsonPath) {
        Remove-Item -LiteralPath $jsonPath -Force
    }
}
