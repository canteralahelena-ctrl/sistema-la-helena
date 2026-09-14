param(
    [Parameter(Mandatory=$true)]
    [string]$Frase,

    [string]$DiccionarioPath = "work/diccionario_intenciones.json",

    [switch]$Agregar,

    [string]$Intencion,

    [switch]$Confirmar
)

function Normalizar-Frase {
    param([string]$Texto)

    $t = $Texto.ToLower().Trim()

    $t = $t -replace "á","a"
    $t = $t -replace "é","e"
    $t = $t -replace "í","i"
    $t = $t -replace "ó","o"
    $t = $t -replace "ú","u"
    $t = $t -replace "ñ","n"

    $t = $t -replace "[^\w\s]", " "
    $t = $t -replace "\s+", " "

    return $t.Trim()
}

if (-not (Test-Path $DiccionarioPath)) {
    Write-Host "No existe el diccionario: $DiccionarioPath"
    exit 1
}

$diccionario = Get-Content $DiccionarioPath -Raw | ConvertFrom-Json

$fraseNormalizada = Normalizar-Frase $Frase

$coincidencias = @()

foreach ($intent in $diccionario.intenciones) {
    foreach ($f in $intent.frases) {
        $fn = Normalizar-Frase $f

        if ($fraseNormalizada -eq $fn -or $fraseNormalizada.Contains($fn) -or $fn.Contains($fraseNormalizada)) {
            $coincidencias += [pscustomobject]@{
                Id = $intent.id
                Descripcion = $intent.descripcion
                Script = $intent.script
                ParametrosBase = $intent.parametros_base
                FraseDetectada = $f
            }
        }
    }
}

if ($coincidencias.Count -eq 1 -and -not $Agregar) {
    $c = $coincidencias[0]

    Write-Host "Intencion detectada: $($c.Id)"
    Write-Host "Descripcion: $($c.Descripcion)"
    Write-Host "Script: $($c.Script)"
    Write-Host "Frase reconocida: $($c.FraseDetectada)"

    Write-Host ""
    Write-Host "Parametros base:"
    $c.ParametrosBase | Format-List

    exit 0
}

if ($coincidencias.Count -gt 1 -and -not $Agregar) {
    Write-Host "La frase es ambigua. Posibles intenciones:"
    $i = 1
    foreach ($c in $coincidencias) {
        Write-Host "$i. $($c.Id) - $($c.Descripcion)"
        $i++
    }
    Write-Host ""
    Write-Host "Indicar una intencion explicita antes de agregar la frase."
    exit 2
}

if ($coincidencias.Count -eq 0 -and -not $Agregar) {
    Write-Host "No reconozco esta forma de pedir la consulta:"
    Write-Host "`"$Frase`""
    Write-Host ""
    Write-Host "Para agregarla al diccionario ejecutar:"
        Write-Host ".\work\intenciones_consultas.ps1 -Frase `"$Frase`" -Agregar -Intencion ID_INTENCION -Confirmar"
    Write-Host ""
    Write-Host "Intenciones disponibles:"
    foreach ($intent in $diccionario.intenciones) {
        Write-Host "- $($intent.id): $($intent.descripcion)"
    }
    exit 3
}

if ($Agregar) {
    if (-not $Confirmar) {
        Write-Host "Para agregar una frase debe usar -Confirmar."
        exit 4
    }

    if ([string]::IsNullOrWhiteSpace($Intencion)) {
        Write-Host "Debe indicar -Intencion."
        exit 5
    }

    $intentObjetivo = $diccionario.intenciones | Where-Object { $_.id -eq $Intencion } | Select-Object -First 1

    if ($null -eq $intentObjetivo) {
        Write-Host "No existe la intencion: $Intencion"
        Write-Host "Intenciones disponibles:"
        foreach ($intent in $diccionario.intenciones) {
            Write-Host "- $($intent.id): $($intent.descripcion)"
        }
        exit 6
    }

    $yaExiste = $false

    foreach ($f in $intentObjetivo.frases) {
        if ((Normalizar-Frase $f) -eq $fraseNormalizada) {
            $yaExiste = $true
            break
        }
    }

    if ($yaExiste) {
        Write-Host "La frase ya existe en la intencion $Intencion."
        exit 0
    }

    $lista = @($intentObjetivo.frases)
    $lista += $Frase
    $intentObjetivo.frases = $lista

    $backupPath = "$DiccionarioPath.bak"
    Copy-Item $DiccionarioPath $backupPath -Force

    $diccionario | ConvertTo-Json -Depth 20 | Set-Content $DiccionarioPath -Encoding UTF8

    Write-Host "Frase agregada correctamente."
    Write-Host "Frase: $Frase"
    Write-Host "Intencion: $Intencion"
    Write-Host "Backup: $backupPath"

    exit 0
}
