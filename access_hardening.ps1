function Test-HelenaNull([AllowNull()][object]$Value) {
    return ($null -eq $Value -or [System.Convert]::IsDBNull($Value))
}

function New-HelenaDataException([string]$Field, [string]$Context, [string]$Reason) {
    $suffix = if ($Context) { " contexto=$Context" } else { "" }
    return [System.Data.DataException]::new("DATO_INVALIDO_BLOQUEANTE campo=$Field motivo=$Reason$suffix")
}

function Get-HelenaDataNullState([AllowNull()][object]$Value, [string]$NullPolicy) {
    $isNull = (Test-HelenaNull $Value) -or ($Value -is [string] -and [string]::IsNullOrWhiteSpace($Value))
    if (-not $isNull) { return "DATO_OK" }
    if ($NullPolicy -eq "BLOCK") { return "DATO_INVALIDO_BLOQUEANTE" }
    return "DATO_NULO_TOLERADO"
}

function ConvertTo-HelenaDecimal {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field,
        [ValidateSet("BLOCK", "ZERO", "NULL")][string]$NullPolicy = "BLOCK",
        [string]$Context = ""
    )

    $nullState = Get-HelenaDataNullState $Value $NullPolicy
    if ($nullState -ne "DATO_OK") {
        Write-Verbose "$nullState campo=$Field contexto=$Context"
        switch ($NullPolicy) {
            "ZERO" { return [decimal]0 }
            "NULL" { return $null }
            default { throw (New-HelenaDataException $Field $Context "VALOR_NULO") }
        }
    }

    if ($Value -is [decimal] -or $Value -is [double] -or $Value -is [float] -or
        $Value -is [int] -or $Value -is [long] -or $Value -is [System.Int16]) {
        return [decimal]$Value
    }

    $parsed = [decimal]0
    $text = [string]$Value
    foreach ($culture in @(
        [Globalization.CultureInfo]::GetCultureInfo("es-AR"),
        [Globalization.CultureInfo]::InvariantCulture
    )) {
        if ([decimal]::TryParse($text, [Globalization.NumberStyles]::Any, $culture, [ref]$parsed)) {
            return $parsed
        }
    }
    throw (New-HelenaDataException $Field $Context "NUMERO_INVALIDO")
}

function ConvertTo-HelenaInteger {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field,
        [ValidateSet("BLOCK", "NULL")][string]$NullPolicy = "BLOCK",
        [string]$Context = ""
    )

    $number = ConvertTo-HelenaDecimal -Value $Value -Field $Field -NullPolicy $NullPolicy -Context $Context
    if ($null -eq $number) { return $null }
    if ([decimal]::Truncate($number) -ne $number -or $number -gt [int]::MaxValue -or $number -lt [int]::MinValue) {
        throw (New-HelenaDataException $Field $Context "ENTERO_INVALIDO")
    }
    return [int]$number
}

function ConvertTo-HelenaDate {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field,
        [ValidateSet("BLOCK", "NULL")][string]$NullPolicy = "BLOCK",
        [string]$Context = ""
    )

    $nullState = Get-HelenaDataNullState $Value $NullPolicy
    if ($nullState -ne "DATO_OK") {
        Write-Verbose "$nullState campo=$Field contexto=$Context"
        if ($NullPolicy -eq "NULL") { return $null }
        throw (New-HelenaDataException $Field $Context "VALOR_NULO")
    }
    if ($Value -is [datetime]) { return [datetime]$Value }

    $parsed = [datetime]::MinValue
    $text = [string]$Value
    foreach ($culture in @(
        [Globalization.CultureInfo]::GetCultureInfo("es-AR"),
        [Globalization.CultureInfo]::InvariantCulture
    )) {
        if ([datetime]::TryParse($text, $culture, [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
            return $parsed
        }
    }
    throw (New-HelenaDataException $Field $Context "FECHA_INVALIDA")
}

function ConvertTo-HelenaText {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field,
        [ValidateSet("BLOCK", "EMPTY", "NULL")][string]$NullPolicy = "EMPTY",
        [string]$Context = ""
    )

    $nullState = Get-HelenaDataNullState $Value $NullPolicy
    if ($nullState -ne "DATO_OK") {
        Write-Verbose "$nullState campo=$Field contexto=$Context"
        switch ($NullPolicy) {
            "EMPTY" { return "" }
            "NULL" { return $null }
            default { throw (New-HelenaDataException $Field $Context "VALOR_NULO") }
        }
    }
    return [string]$Value
}

function Protect-HelenaDiagnosticText([AllowNull()][object]$Value) {
    $text = [string]$Value
    if (-not $text) { return "" }
    return [regex]::Replace(
        $text,
        '(?i)(token|password|contrase(?:n|ñ)a|api[_ -]?key|secret)\s*[:=]\s*[^\s;]+',
        '$1=[REDACTADO]'
    )
}

function New-HelenaErrorDetail {
    param(
        [Parameter(Mandatory = $true)][string]$Module,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord,
        [hashtable]$Context = @{}
    )

    $safeContext = @()
    foreach ($key in @($Context.Keys | Sort-Object)) {
        if ($key -match '(?i)token|password|clave|secret|api') { continue }
        $safeContext += "$key=$(Protect-HelenaDiagnosticText $Context[$key])"
    }
    $invocation = $ErrorRecord.InvocationInfo
    return [pscustomobject]@{
        Modulo = $Module
        Operacion = $Operation
        Archivo = if ($invocation -and $invocation.ScriptName) { [IO.Path]::GetFileName($invocation.ScriptName) } else { "" }
        Linea = if ($invocation) { [int]$invocation.ScriptLineNumber } else { 0 }
        Mensaje = Protect-HelenaDiagnosticText $ErrorRecord.Exception.Message
        TipoExcepcion = $ErrorRecord.Exception.GetType().FullName
        Contexto = ($safeContext -join " ")
    }
}

function Format-HelenaErrorDetail {
    param(
        [Parameter(Mandatory = $true)][string]$Module,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord,
        [hashtable]$Context = @{}
    )
    $detail = New-HelenaErrorDetail $Module $Operation $ErrorRecord $Context
    return "modulo=$($detail.Modulo) operacion=$($detail.Operacion) archivo=$($detail.Archivo) linea=$($detail.Linea) tipo=$($detail.TipoExcepcion) mensaje=$($detail.Mensaje) contexto=$($detail.Contexto)"
}

function Test-HelenaDocumentRoot([string]$Name, [string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return [pscustomobject]@{ Nombre=$Name; Ruta=$Path; Estado="RAIZ_INACCESIBLE"; Ok=$false; Detalle="RUTA_NO_CONFIGURADA" }
    }
    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if (-not $item.PSIsContainer) {
            return [pscustomobject]@{ Nombre=$Name; Ruta=$Path; Estado="RAIZ_INACCESIBLE"; Ok=$false; Detalle="NO_ES_DIRECTORIO" }
        }
        $null = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop | Select-Object -First 1)
        return [pscustomobject]@{ Nombre=$Name; Ruta=$Path; Estado="RAIZ_OK"; Ok=$true; Detalle="" }
    }
    catch {
        return [pscustomobject]@{ Nombre=$Name; Ruta=$Path; Estado="RAIZ_INACCESIBLE"; Ok=$false; Detalle=(Protect-HelenaDiagnosticText $_.Exception.Message) }
    }
}

function Test-HelenaPdfFile([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [pscustomobject]@{ Estado="PDF_NO_ENCONTRADO"; Ok=$false; Ruta=$Path; Detalle="" }
    }
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $header = New-Object byte[] 5
            $read = $stream.Read($header, 0, $header.Length)
            if ($read -lt 5 -or [Text.Encoding]::ASCII.GetString($header) -ne '%PDF-') {
                return [pscustomobject]@{ Estado="PDF_INVALIDO"; Ok=$false; Ruta=$Path; Detalle="CABECERA_INVALIDA" }
            }
        }
        finally { $stream.Dispose() }
        return [pscustomobject]@{ Estado="PDF_OK"; Ok=$true; Ruta=$Path; Detalle="" }
    }
    catch {
        return [pscustomobject]@{ Estado="RAIZ_INACCESIBLE"; Ok=$false; Ruta=$Path; Detalle=(Protect-HelenaDiagnosticText $_.Exception.Message) }
    }
}

function Get-HelenaAccessSchema([string]$Database) {
    $conn = $null
    try {
        if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) {
            return [pscustomobject]@{ Estado="BASE_INACCESIBLE"; Ok=$false; Tablas=@{}; Detalle="ARCHIVO_NO_ENCONTRADO" }
        }
        $conn = New-Object -ComObject ADODB.Connection
        $conn.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$Database;Mode=Read;")
        $tables = @{}
        $columns = $conn.OpenSchema(4)
        while (-not $columns.EOF) {
            $tableName = [string]$columns.Fields.Item("TABLE_NAME").Value
            $columnName = [string]$columns.Fields.Item("COLUMN_NAME").Value
            $tableKey = $tableName.Trim().ToUpperInvariant()
            if (-not $tables.ContainsKey($tableKey)) {
                $tables[$tableKey] = [pscustomobject]@{ Nombre=$tableName; Campos=@{} }
            }
            $tables[$tableKey].Campos[$columnName.Trim().ToUpperInvariant()] = $columnName
            $columns.MoveNext()
        }
        return [pscustomobject]@{ Estado="BASE_VALIDA"; Ok=$true; Tablas=$tables; Detalle="" }
    }
    catch {
        return [pscustomobject]@{ Estado="BASE_INACCESIBLE"; Ok=$false; Tablas=@{}; Detalle=(Protect-HelenaDiagnosticText $_.Exception.Message) }
    }
    finally {
        if ($conn -and $conn.State -eq 1) { $conn.Close() }
    }
}

function Test-HelenaSchemaRequirements {
    param(
        [hashtable]$Tables,
        [object[]]$Requirements,
        [hashtable]$KnownAliases = @{}
    )

    $issues = @()
    foreach ($requirement in $Requirements) {
        $canonical = ([string]$requirement.Table).Trim().ToUpperInvariant()
        $resolved = $canonical
        if (-not $Tables.ContainsKey($canonical)) {
            $alias = @($KnownAliases[$canonical] | Where-Object { $Tables.ContainsKey(([string]$_).ToUpperInvariant()) } | Select-Object -First 1)
            if ($alias.Count -gt 0) {
                $resolved = ([string]$alias[0]).Trim().ToUpperInvariant()
            } else {
                $issues += [pscustomobject]@{ Modulo=$requirement.Module; Estado="TABLA_INEXISTENTE"; Tabla=$canonical; Detalle="" }
                continue
            }
        }
        foreach ($field in @($requirement.Fields)) {
            $fieldKey = ([string]$field).Trim().ToUpperInvariant()
            if (-not $Tables[$resolved].Campos.ContainsKey($fieldKey)) {
                $issues += [pscustomobject]@{ Modulo=$requirement.Module; Estado="CAMPO_INEXISTENTE"; Tabla=$resolved; Detalle=[string]$field }
            }
        }
    }
    return @($issues)
}
