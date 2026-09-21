param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge")

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$configPath = Join-Path $InstallDir "bridge.json"
$readerPath = Join-Path $InstallDir "chatgpt-reader-v2.json"
$backupPath = Join-Path $InstallDir "bridge.pre-v2.json"
$candidateConfig = Join-Path $InstallDir ("bridge.v2.candidate." + [Guid]::NewGuid().ToString("N") + ".json")
$candidateReader = Join-Path $InstallDir ("reader.v2.candidate." + [Guid]::NewGuid().ToString("N") + ".json")
$ownerDsnFile = Join-Path $InstallDir ("owner.dsn." + [Guid]::NewGuid().ToString("N") + ".tmp")
$taskName = "LaHelena-AccessBridge"
$mutex = New-Object Threading.Mutex($false, "Local\LaHelenaAccessBridgeRolesV2")
$hasMutex = $false
$taskWasEnabled = $false
$configSwapped = $false

function Set-PrivateAcl([string]$Path) {
    $acl = New-Object Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity.User, "FullControl", "Allow")))
    $systemSid = New-Object Security.Principal.SecurityIdentifier("S-1-5-18")
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($systemSid, "FullControl", "Allow")))
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if (-not (Test-Path -LiteralPath $configPath)) { throw "No existe la configuración instalada: $configPath" }
$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "No existe el Python privado del puente." }
$helper = Join-Path $PSScriptRoot "admin\cutover_production_v2.py"
if (-not (Test-Path -LiteralPath $helper)) { throw "Falta admin\cutover_production_v2.py." }

try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) { throw "Ya hay otro corte de roles V2 en ejecución." }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne "Disabled") {
        Disable-ScheduledTask -TaskName $taskName | Out-Null
        $taskWasEnabled = $true
        $limit = (Get-Date).AddMinutes(2)
        while ((Get-ScheduledTask -TaskName $taskName).State -eq "Running") {
            if ((Get-Date) -gt $limit) { throw "La tarea programada no terminó dentro del plazo seguro." }
            Start-Sleep -Seconds 2
        }
    }
    if (-not (Test-Path -LiteralPath $backupPath)) {
        Copy-Item -LiteralPath $configPath -Destination $backupPath
        Set-PrivateAcl $backupPath
    }
    New-Item -ItemType File -Path $candidateConfig -ErrorAction Stop | Out-Null
    New-Item -ItemType File -Path $candidateReader -ErrorAction Stop | Out-Null
    New-Item -ItemType File -Path $ownerDsnFile -ErrorAction Stop | Out-Null
    Set-PrivateAcl $candidateConfig
    Set-PrivateAcl $candidateReader
    Set-PrivateAcl $ownerDsnFile
    $secureOwnerDsn = Read-Host "Pegue la cadena DIRECTA de neondb_owner y presione ENTER" -AsSecureString
    $ownerPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureOwnerDsn)
    try {
        $ownerDsn = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ownerPtr)
        [IO.File]::WriteAllText($ownerDsnFile, $ownerDsn, (New-Object Text.UTF8Encoding($false)))
    }
    finally {
        if ($ownerPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ownerPtr) }
        $ownerDsn = $null
        $secureOwnerDsn = $null
    }
    & $python $helper --config $configPath --config-candidate $candidateConfig --reader-candidate $candidateReader --owner-dsn-file $ownerDsnFile
    if ($LASTEXITCODE -ne 0) { throw "Falló la validación de los logins V2." }
    if (-not (Test-Path -LiteralPath $candidateConfig) -or -not (Test-Path -LiteralPath $candidateReader)) {
        throw "La validación no generó los candidatos privados esperados."
    }
    Move-Item -LiteralPath $candidateReader -Destination $readerPath -Force
    [IO.File]::Replace($candidateConfig, $configPath, $null, $true)
    $configSwapped = $true
}
catch {
    if ($configSwapped -and (Test-Path -LiteralPath $backupPath)) {
        Copy-Item -LiteralPath $backupPath -Destination $configPath -Force
    }
    throw
}
finally {
    Remove-Item -LiteralPath $candidateConfig -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $candidateReader -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $ownerDsnFile -Force -ErrorAction SilentlyContinue
    if ($taskWasEnabled) { Enable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null }
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

Write-Host "CONFIG_SYNC_V2_ACTIVA: OK" -ForegroundColor Green
Write-Host "READER_V2_GUARDADO: OK" -ForegroundColor Green
Write-Host "BACKUP_CONFIGURACION: $backupPath" -ForegroundColor Green
Write-Host "CORTE_ROLES_V2: OK" -ForegroundColor Green
