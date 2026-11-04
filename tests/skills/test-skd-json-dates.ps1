param([string]$CompilerPath = '')

$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$compiler = if ($CompilerPath) { $CompilerPath } else { Join-Path $root 'skills/1c-skd-compile/scripts/skd-compile.ps1' }
$caseFile = Join-Path $root 'tests/skills/cases/skd-compile/data-parameters-list.json'
$jsonArgs = @{}
if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) { $jsonArgs.DateKind = 'String' }
$case = Get-Content -LiteralPath $caseFile -Raw -Encoding UTF8 | ConvertFrom-Json @jsonArgs
$case.input.settingsVariants[1].settings.dataParameters[2] | Add-Member -NotePropertyName valueType -NotePropertyValue 'string(20)'
$definition = $case.input | ConvertTo-Json -Depth 100 -Compress
$temp = Join-Path ([IO.Path]::GetTempPath()) ('skd-json-date-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $definitionFile = Join-Path $temp 'definition.json'
    [IO.File]::WriteAllText($definitionFile, $definition, [Text.UTF8Encoding]::new($false))
    foreach ($mode in @('DefinitionFile', 'Value')) {
        $out = Join-Path $temp "$mode.xml"
        $argsForCompiler = @{ OutputPath = $out }
        $argsForCompiler[$mode] = if ($mode -eq 'Value') { $definition } else { $definitionFile }
        & $compiler @argsForCompiler
        if (-not (Test-Path -LiteralPath $out)) { throw "$mode did not create output" }
        $xml = [IO.File]::ReadAllText($out)
        if ($xml -notmatch '<dcscor:value xsi:type="xs:string">2024-01-01T00:00:00</dcscor:value>') {
            throw "$mode failed to preserve the ISO date-like string as a string list value"
        }
        if ($xml -notmatch '<dcscor:value xsi:type="xs:boolean">true</dcscor:value>') {
            throw "$mode did not preserve boolean list values"
        }
        if ($xml -notmatch '<dcscor:value xsi:nil="true"\s*/>') {
            throw "$mode did not preserve null list values"
        }
    }
    Write-Host 'СКД: -DefinitionFile и -Value сохраняют строку даты, boolean и null.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
