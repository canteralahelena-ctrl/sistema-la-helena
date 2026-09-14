$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "access_hardening.ps1")
. (Join-Path $root "normalizacion_unidades.ps1")

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ($Expected -ne $Actual) { throw "$Name esperaba '$Expected' y obtuvo '$Actual'." }
}
function Assert-True([bool]$Value, [string]$Name) {
    if (-not $Value) { throw "$Name esperaba verdadero." }
}

foreach ($value in @($null, [DBNull]::Value, "", "   ")) {
    Assert-Equal ([decimal]0) (ConvertTo-HelenaDecimal $value "IVA" "ZERO" "fixture") "IVA nulo tolerado"
    Assert-Equal "DATO_NULO_TOLERADO" (Get-HelenaDataNullState $value "ZERO") "Estado IVA nulo tolerado"
}
Assert-Equal ([decimal]232898.40) (ConvertTo-HelenaDecimal ([decimal]232898.40) "IVA" "ZERO") "IVA informado intacto"
$blocked = $false
try { $null = ConvertTo-HelenaDecimal $null "IMPORTE" "BLOCK" "IdCOMPROVANTE=1" } catch { $blocked = $_.Exception.Message -like "DATO_INVALIDO_BLOQUEANTE*" }
Assert-True $blocked "Importe nulo bloqueante"
Assert-Equal "DATO_INVALIDO_BLOQUEANTE" (Get-HelenaDataNullState $null "BLOCK") "Estado importe nulo bloqueante"

$units = @{
    "Und"="UND"; "Und."="UND"; "Unid"="UND"; "Unid."="UND";
    "tn"="TN"; " toneladas "="TN"; "M3"="M3"; "Mtr3"="M3"
}
foreach ($entry in $units.GetEnumerator()) {
    Assert-Equal $entry.Value (Normalize-HelenaUnit $entry.Key) "Unidad $($entry.Key)"
}

$numeroField = "N$([char]0x00BA)"
$tables = @{
    "COMPROBANTES DE GASTOS" = [pscustomobject]@{
        Nombre="COMPROBANTES DE GASTOS"
        Campos=@{"IDGASTO"="IdGASTO";"FECHA"="FECHA";"TIPO"="TIPO";$numeroField=$numeroField;"IDPROVEEDOR"="IdPROVEEDOR";"IVA"="IVA";"IMPORTE"="IMPORTE";"USERID"="UserID"}
    }
}
$expenseRequirement = [pscustomobject]@{
    Module="iva";Table="COMPROVANTES DE GASTOS";Fields=@("IdGASTO","FECHA","TIPO",$numeroField,"IdPROVEEDOR","IVA","IMPORTE","UserID")
}
$issues = @(Test-HelenaSchemaRequirements -Tables $tables -Requirements @(
    $expenseRequirement
) -KnownAliases @{"COMPROVANTES DE GASTOS"=@("COMPROBANTES DE GASTOS")})
Assert-Equal 0 $issues.Count "Alias conocido valido"

$tables["COMPROBANTES DE GASTOS"].Campos.Remove("IVA")
$invalidAliasIssues = @(Test-HelenaSchemaRequirements -Tables $tables -Requirements @(
    $expenseRequirement
) -KnownAliases @{"COMPROVANTES DE GASTOS"=@("COMPROBANTES DE GASTOS")})
Assert-Equal 1 $invalidAliasIssues.Count "Alias conocido con estructura invalida"
Assert-Equal "CAMPO_INEXISTENTE" $invalidAliasIssues[0].Estado "Campo obligatorio del alias"
Assert-Equal "COMPROBANTES DE GASTOS" $invalidAliasIssues[0].Tabla "Nombre real del alias invalido"

$missingTableIssues = @(Test-HelenaSchemaRequirements -Tables @{} -Requirements @(
    $expenseRequirement
) -KnownAliases @{"COMPROVANTES DE GASTOS"=@("COMPROBANTES DE GASTOS")})
Assert-Equal 1 $missingTableIssues.Count "Tabla canonica y alias ausentes"
Assert-Equal "TABLA_INEXISTENTE" $missingTableIssues[0].Estado "Tabla obligatoria ausente"

$missingRoot = Test-HelenaDocumentRoot "FACTURAS" (Join-Path $root "__raiz_inexistente__")
Assert-Equal "RAIZ_INACCESIBLE" $missingRoot.Estado "Raiz inaccesible"
$missingPdf = Test-HelenaPdfFile (Join-Path $root "__pdf_inexistente__.pdf")
Assert-Equal "PDF_NO_ENCONTRADO" $missingPdf.Estado "PDF no encontrado"

$errorRecord = $null
try { throw "token=secreto IdCOMPROVANTE=9" } catch { $errorRecord = $_ }
$detail = New-HelenaErrorDetail "auditorias" "convertir_iva" $errorRecord @{IdCOMPROVANTE=9;api_key="no_mostrar"}
Assert-Equal "auditorias" $detail.Modulo "Modulo de error"
Assert-True ($detail.Mensaje -notlike "*secreto*") "Secreto redactado"
Assert-True ($detail.Contexto -like "*IdCOMPROVANTE=9*") "Contexto util"
Assert-True ($detail.Contexto -notlike "*api_key*") "Clave sensible omitida"
$formatted = Format-HelenaErrorDetail "auditorias" "convertir_iva" $errorRecord @{IdCOMPROVANTE=9}
foreach ($part in @("modulo=auditorias", "operacion=convertir_iva", "archivo=", "linea=", "tipo=", "mensaje=", "contexto=IdCOMPROVANTE=9")) {
    Assert-True ($formatted -like "*$part*") "Detalle visible $part"
}

Write-Output "OK test_hardening"
