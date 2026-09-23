param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$taskName = "LaHelena-AccessBridge"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$windowsUser = $identity.Name
$installFull = [IO.Path]::GetFullPath($InstallDir)

function Write-JsonAtomic([object]$Value, [string]$Path) {
    $temp = "$Path.tmp.$([Guid]::NewGuid().ToString('N'))"
    [IO.File]::WriteAllText($temp, ($Value | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
    $acl = New-Object Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity.User, "FullControl", "Allow")))
    $systemSid = New-Object Security.Principal.SecurityIdentifier("S-1-5-18")
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($systemSid, "FullControl", "Allow")))
    Set-Acl -LiteralPath $temp -AclObject $acl
    if (Test-Path -LiteralPath $Path) {
        $backup = "$Path.replace-backup"
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        [IO.File]::Replace($temp, $Path, $backup, $true)
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
    else { Move-Item -LiteralPath $temp -Destination $Path }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

$launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $launcher) { throw "Se requiere el lanzador py y Python 3.11 o posterior." }
$version = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or [version]$version -lt [version]"3.11") { throw "Se requiere Python 3.11 o posterior." }

$requiredSources = @(
    "access_bridge", "requirements-bridge.txt", "actualizar_copia_base.ps1",
    "access_hardening.ps1", "run_sync.ps1", "validar_access_bridge.ps1"
)
foreach ($name in $requiredSources) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $name))) { throw "Falta el componente de instalación: $name" }
}

New-Item -ItemType Directory -Force -Path $installFull | Out-Null
$sentinelPath = Join-Path $installFull ".lahelena-access-bridge.install.json"
if (Test-Path -LiteralPath $sentinelPath) {
    $sentinel = Get-Content -LiteralPath $sentinelPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([IO.Path]::GetFullPath([string]$sentinel.install_dir) -ne $installFull) { throw "El marcador de instalación no coincide con el destino." }
}

$stage = Join-Path $installFull ("app.staging." + [Guid]::NewGuid().ToString("N"))
$appDir = Join-Path $installFull "app"
$backupApp = Join-Path $installFull ("app.previous." + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $root "access_bridge") -Destination $stage -Recurse -Force
    if (Test-Path -LiteralPath (Join-Path $root "migrations")) {
        Copy-Item -LiteralPath (Join-Path $root "migrations") -Destination $stage -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $root "actualizar_copia_base.ps1") -Destination $stage -Force
    Copy-Item -LiteralPath (Join-Path $root "access_hardening.ps1") -Destination $stage -Force
    Copy-Item -LiteralPath (Join-Path $root "run_sync.ps1") -Destination $stage -Force
    if (-not (Test-Path -LiteralPath (Join-Path $stage "access_bridge\__init__.py"))) { throw "El staging no contiene el paquete esperado." }
    if (Test-Path -LiteralPath (Join-Path $stage "access_bridge\access_bridge")) { throw "El staging contiene una anidación inválida." }

    if (Test-Path -LiteralPath $appDir) { Move-Item -LiteralPath $appDir -Destination $backupApp }
    Move-Item -LiteralPath $stage -Destination $appDir
}
catch {
    if ((-not (Test-Path -LiteralPath $appDir)) -and (Test-Path -LiteralPath $backupApp)) {
        Move-Item -LiteralPath $backupApp -Destination $appDir
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}

$venv = Join-Path $installFull ".venv"
if (-not (Test-Path -LiteralPath $venv)) { & py -3 -m venv $venv }
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements-bridge.txt")
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }

$configPath = Join-Path $installFull "bridge.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    $accessPath = Read-Host "Ruta de la copia LOCAL Access (.accdb)"
    $sourcePath = Read-Host "Ruta de la base ORIGEN en servidor (sólo se copiará; Access no la abre)"
    $secureDsn = Read-Host "DSN PostgreSQL de sincronización" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureDsn)
    try { $dsn = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    $config = [ordered]@{
        access_path = $accessPath; source_access_path = $sourcePath
        refresh_script = (Join-Path $appDir "actualizar_copia_base.ps1")
        postgres_dsn = $dsn; log_path = (Join-Path $installFull "bridge.log")
        batch_size = 1000; refresh_before_sync = $true
    }
}
else {
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $config | Add-Member -NotePropertyName refresh_script -NotePropertyValue (Join-Path $appDir "actualizar_copia_base.ps1") -Force
}
Write-JsonAtomic $config $configPath
Write-JsonAtomic ([ordered]@{ product = "LaHelenaAccessBridge"; install_dir = $installFull; installed_at = [DateTime]::UtcNow.ToString("o") }) $sentinelPath

$wrapper = Join-Path $appDir "run_sync.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`" -InstallDir `"$installFull`""
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $windowsUser -LogonType Interactive -RunLevel Limited
$previousTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$previousTaskXml = if ($previousTask) { Export-ScheduledTask -TaskName $taskName } else { $null }
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Replica Access solo lectura a PostgreSQL" -Force | Out-Null
    & (Join-Path $root "validar_access_bridge.ps1") -InstallDir $installFull
    if ($LASTEXITCODE -ne 0) { throw "La validación operativa falló." }
    if (Test-Path -LiteralPath $backupApp) { Remove-Item -LiteralPath $backupApp -Recurse -Force }
}
catch {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    if ($previousTaskXml) { Register-ScheduledTask -TaskName $taskName -Xml $previousTaskXml -Force | Out-Null }
    if (Test-Path -LiteralPath $backupApp) {
        $failedApp = Join-Path $installFull ("app.failed." + [Guid]::NewGuid().ToString("N"))
        if (Test-Path -LiteralPath $appDir) { Move-Item -LiteralPath $appDir -Destination $failedApp }
        Move-Item -LiteralPath $backupApp -Destination $appDir
    }
    elseif (Test-Path -LiteralPath $appDir) {
        Remove-Item -LiteralPath $appDir -Recurse -Force
    }
    throw
}
Write-Host "INSTALACION_OPERATIVA: OK (sin migraciones ni provisión de roles)" -ForegroundColor Green
