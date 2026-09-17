param([string]$InstallDir = "$env:LOCALAPPDATA\LaHelenaAccessBridge")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { throw "Se requiere Python 3.11 o posterior." }
$version = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$version -lt [version]"3.11") { throw "Se requiere Python 3.11 o posterior." }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path $venv)) { & py -3 -m venv $venv }
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements-bridge.txt")
if ($LASTEXITCODE) { throw "No se pudieron instalar las dependencias." }

$configPath = Join-Path $InstallDir "bridge.json"
if (-not (Test-Path $configPath)) {
    $accessPath = Read-Host "Ruta de la copia LOCAL Access (.accdb)"
    $sourcePath = Read-Host "Ruta de la base ORIGEN en servidor (sólo se copiará; Access no la abre)"
    $secureDsn = Read-Host "DSN PostgreSQL de sincronización" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureDsn)
    try { $dsn = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    $config = [ordered]@{
        access_path = $accessPath
        source_access_path = $sourcePath
        refresh_script = (Join-Path $root "actualizar_copia_base.ps1")
        postgres_dsn = $dsn
        log_path = (Join-Path $InstallDir "bridge.log")
        batch_size = 1000
        refresh_before_sync = $true
    }
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
}
$acl = Get-Acl $configPath
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, "FullControl", "Allow")
$acl.SetAccessRule($rule); Set-Acl $configPath $acl

$env:PYTHONPATH = $root
& $venvPython -m access_bridge.cli sync --config $configPath
if ($LASTEXITCODE) { throw "La sincronización inicial falló de forma segura." }
& $venvPython -m access_bridge.cli provision-reader --config $configPath
if ($LASTEXITCODE) { throw "No se pudo crear el usuario de consulta." }

$action = New-ScheduledTaskAction -Execute $venvPython -Argument "-m access_bridge.cli sync --config `"$configPath`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "LaHelena-AccessBridge" -Action $action -Trigger $trigger -Settings $settings -Description "Replica Access solo lectura a PostgreSQL" -Force | Out-Null

& (Join-Path $root "validar_access_bridge.ps1") -InstallDir $InstallDir
Write-Host "LISTO_PARA_INSTALAR_LOCALMENTE: SI" -ForegroundColor Green
