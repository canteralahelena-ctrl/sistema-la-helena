param(
    [string]$ShortcutName = "LaHelenaTelegramAccessBot.vbs"
)

$ErrorActionPreference = "Stop"

$startup = [Environment]::GetFolderPath("Startup")
$target = Join-Path $startup $ShortcutName
$launcher = Join-Path $PSScriptRoot "iniciar_bot_telegram.ps1"
$workDir = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "No encontre el lanzador: $launcher"
}

$vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$workDir"
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""$launcher""", 0, False
"@

Set-Content -LiteralPath $target -Value $vbs -Encoding ASCII

Write-Host "Inicio automatico instalado:"
Write-Host $target
Write-Host "El bot se iniciara cuando este usuario inicie sesion en Windows."
