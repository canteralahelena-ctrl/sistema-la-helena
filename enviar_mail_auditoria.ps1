param(
    [string]$Adjunto = "",
    [string[]]$Adjuntos = @(),
    [string]$Asunto = "",
    [string]$Cuerpo = "",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

if ($env:HELENA_PILOT_MODE -eq "1") {
    throw "Modo piloto: el envio de correo esta deshabilitado."
}

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $PSScriptRoot "email_config.json"
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Falta configurar el correo. Copia work\email_config.example.json como work\email_config.json y carga la clave de aplicacion de Gmail."
}

$attachmentPaths = @()
if ($Adjunto) {
    $attachmentPaths += $Adjunto
}
if ($Adjuntos) {
    foreach ($item in $Adjuntos) {
        if ($item -like "*|*") {
            $attachmentPaths += @($item -split "\|" | Where-Object { $_ })
        } else {
            $attachmentPaths += $item
        }
    }
}
$attachmentPaths = @($attachmentPaths | Where-Object { $_ } | Select-Object -Unique)
if ($attachmentPaths.Count -eq 0) {
    throw "Indica al menos un adjunto."
}
foreach ($path in $attachmentPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "No existe el adjunto: $path"
    }
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
foreach ($key in @("smtp_host", "smtp_port", "from", "to", "username", "app_password")) {
    if (-not $config.$key -or $config.$key -eq "PEGAR_CLAVE_DE_APLICACION_DE_GMAIL") {
        throw "Config de correo incompleta: falta $key."
    }
}
$appPassword = ([string]$config.app_password) -replace '\s+', ''

if (-not $Asunto) {
    $Asunto = "Auditoria semanal Maxi - Cantera La Helena"
}
if (-not $Cuerpo) {
    $Cuerpo = "Se adjunta la auditoria semanal de Maxi/usuario 3."
}

$message = [System.Net.Mail.MailMessage]::new()
$attachments = @()
$smtp = $null

try {
    $message.From = [System.Net.Mail.MailAddress]::new([string]$config.from)
    [void]$message.To.Add([string]$config.to)
    $message.Subject = $Asunto
    $message.Body = $Cuerpo
    $message.IsBodyHtml = $false
    foreach ($path in $attachmentPaths) {
        $attachment = [System.Net.Mail.Attachment]::new((Resolve-Path -LiteralPath $path).Path)
        $attachments += $attachment
        [void]$message.Attachments.Add($attachment)
    }

    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $smtp = [System.Net.Mail.SmtpClient]::new([string]$config.smtp_host, [int]$config.smtp_port)
    $smtp.EnableSsl = [bool]$config.use_ssl
    $smtp.UseDefaultCredentials = $false
    $smtp.Credentials = [System.Net.NetworkCredential]::new([string]$config.username, $appPassword)
    $smtp.Send($message)

    [pscustomobject]@{
        Estado = "ENVIADO"
        Para = $config.to
        Adjuntos = @($attachmentPaths | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
        Fecha = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    }
}
finally {
    foreach ($attachment in $attachments) { $attachment.Dispose() }
    if ($message) { $message.Dispose() }
    if ($smtp) { $smtp.Dispose() }
}
