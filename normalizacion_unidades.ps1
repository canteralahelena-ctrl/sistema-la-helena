function Normalize-HelenaUnit([AllowNull()][object]$Value) {
    if ($null -eq $Value -or [System.Convert]::IsDBNull($Value)) { return "" }
    $text = ([string]$Value).Trim().ToUpperInvariant().Replace([char]0x00B3, "3")
    $text = $text.Normalize([Text.NormalizationForm]::FormD)
    $text = -join ($text.ToCharArray() | Where-Object {
        [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne [Globalization.UnicodeCategory]::NonSpacingMark
    })
    $compact = $text -replace '[\.\s]', ''
    if ($compact -match '^(UND|UNID|UNIDAD|UNIDADES)$') { return "UND" }
    if ($compact -match '^(TN|T|TON|TONELADA|TONELADAS)$') { return "TN" }
    if ($compact -match '^(M3|MTR3|MTS3|METROCUBICO|METROSCUBICOS)$') { return "M3" }
    return $compact
}
