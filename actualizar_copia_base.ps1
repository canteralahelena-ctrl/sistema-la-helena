param(
    [string]$Origen = "\\SERVIDOR_EJEMPLO\D\LA HELENA\RUTA_ADMIN_EJEMPLO\BASE_DATOS_EJEMPLO\CANTERA LA HELENA 1.0_be.accdb",
    [string]$Destino = "",
    [switch]$SinBackup
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "access_hardening.ps1")

if ($env:HELENA_PILOT_MODE -eq "1") {
    throw "Modo piloto: la actualizacion desde servidor esta deshabilitada."
}

$root = Split-Path -Parent $PSScriptRoot
if (-not $Destino) {
    $Destino = Join-Path $root "CANTERA LA HELENA 1.0_be.accdb"
}

$backupDir = Join-Path $PSScriptRoot "data\backups_base"
$logRoot = if ($env:HELENA_LOGS_DIR) { $env:HELENA_LOGS_DIR } else { Join-Path $PSScriptRoot "logs" }
$logPath = Join-Path $logRoot "actualizacion_base.log"
$statePath = Join-Path $PSScriptRoot "data\actualizacion_base_estado.json"
$lockDir = Join-Path $PSScriptRoot "data\actualizacion_base.lock"
New-Item -ItemType Directory -Force -Path $logRoot, (Split-Path -Parent $statePath) | Out-Null

function Log-Line([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $message
    try {
        Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    }
    catch {
        # El log es diagnostico; una colision de escritura no debe frenar la consulta.
    }
    Write-Host $line
}

try {
    if (-not (Test-Path -LiteralPath $Origen -ErrorAction Stop)) {
        throw "No existe la base origen: $Origen"
    }

    $sourceInfo = Get-Item -LiteralPath $Origen -ErrorAction Stop
    if ($sourceInfo.Extension -ne ".accdb") {
        throw "El origen no es .accdb: $Origen"
    }
}
catch {
    Log-Line "Servidor no disponible para verificar base. Se usara copia local. Detalle: $($_.Exception.Message)"
    if (Test-Path -LiteralPath $Destino) {
        $destInfo = Get-Item -LiteralPath $Destino
        [pscustomobject]@{
            UltimaVerificacion = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            Origen = $Origen
            Destino = $Destino
            DestinoFecha = $destInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            DestinoTamano = $destInfo.Length
            Estado = "SERVIDOR_NO_DISPONIBLE_USANDO_COPIA_LOCAL"
        } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $statePath -Encoding UTF8
        return
    }
    throw
}

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$tempDestino = "$Destino.tmp"
$lockTaken = $false
$lockStart = Get-Date

while (-not $lockTaken) {
    try {
        if (Test-Path -LiteralPath $lockDir) {
            throw "LOCK_EXISTS"
        }
        New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null
        if (Test-Path -LiteralPath $lockDir) {
            $lockTaken = $true
        }
    }
    catch {
        if (((Get-Date) - $lockStart).TotalSeconds -gt 90) {
            throw "Otra actualizacion de base sigue en curso hace mas de 90 segundos."
        }
        Start-Sleep -Milliseconds 500
    }
}

try {
    Log-Line "Inicio actualizacion desde servidor."
    Log-Line "Origen: $Origen"
    Log-Line "Destino: $Destino"
    Log-Line "Origen fecha: $($sourceInfo.LastWriteTime) tamano: $($sourceInfo.Length)"

    if ((Test-Path -LiteralPath $statePath) -and (Test-Path -LiteralPath $Destino)) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $sourceStamp = $sourceInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        $sameSource = (
            $state.Origen -eq $Origen -and
            [int64]$state.OrigenTamano -eq [int64]$sourceInfo.Length -and
            [string]$state.OrigenFecha -eq $sourceStamp
        )

        if ($sameSource) {
            $destInfo = Get-Item -LiteralPath $Destino
            Log-Line "Sin cambios en origen. Se conserva copia local existente."
            [pscustomobject]@{
                UltimaActualizacionOk = $state.UltimaActualizacionOk
                UltimaVerificacion = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                Origen = $Origen
                OrigenFecha = $sourceInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                OrigenTamano = $sourceInfo.Length
                Destino = $Destino
                DestinoFecha = $destInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                DestinoTamano = $destInfo.Length
                Estado = "SIN_CAMBIOS"
            } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $statePath -Encoding UTF8
            return
        }
    }

    if ((Test-Path -LiteralPath $Destino) -and -not $SinBackup) {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
        $backupPath = Join-Path $backupDir ("CANTERA LA HELENA 1.0_be_{0}.accdb" -f $stamp)
        Copy-Item -LiteralPath $Destino -Destination $backupPath -Force
        Log-Line "Backup local creado: $backupPath"
    }

    if (Test-Path -LiteralPath $tempDestino) {
        Remove-Item -LiteralPath $tempDestino -Force
    }

    Copy-Item -LiteralPath $Origen -Destination $tempDestino -Force
    $tempInfo = Get-Item -LiteralPath $tempDestino

    if ($tempInfo.Length -le 0) {
        throw "La copia temporal quedo vacia."
    }

    Move-Item -LiteralPath $tempDestino -Destination $Destino -Force
    $destInfo = Get-Item -LiteralPath $Destino
    Log-Line "Copia actualizada OK. Destino fecha: $($destInfo.LastWriteTime) tamano: $($destInfo.Length)"
    [pscustomobject]@{
        UltimaActualizacionOk = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        Origen = $Origen
        OrigenFecha = $sourceInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        OrigenTamano = $sourceInfo.Length
        Destino = $Destino
        DestinoFecha = $destInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        DestinoTamano = $destInfo.Length
        Estado = "OK"
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $statePath -Encoding UTF8
}
catch {
    Log-Line ("ERROR " + (Format-HelenaErrorDetail "actualizacion_base" "copiar_base" $_))
    if (Test-Path -LiteralPath $tempDestino) {
        Remove-Item -LiteralPath $tempDestino -Force
    }
    throw
}
finally {
    if ($lockTaken -and (Test-Path -LiteralPath $lockDir)) {
        Remove-Item -LiteralPath $lockDir -Force
    }
}
