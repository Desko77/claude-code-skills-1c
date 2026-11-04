$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$paths = @(
    '1c-meta-compile/scripts/meta-compile.ps1', '1c-cfe-borrow/scripts/cfe-borrow.ps1',
    '1c-epf-add-form/scripts/add-form.ps1', '1c-form-add/scripts/form-add.ps1',
    '1c-form-compile/scripts/form-compile.ps1', '1c-help-manage/scripts/add-help.ps1',
    '1c-interface-edit/scripts/interface-edit.ps1', '1c-role-compile/scripts/role-compile.ps1',
    '1c-subsystem-compile/scripts/subsystem-compile.ps1', '1c-template-add/scripts/add-template.ps1'
)
$temp = Join-Path ([IO.Path]::GetTempPath()) ('format-version-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $config = Join-Path $temp 'Configuration.xml'
    foreach ($padding in @('', ('x' * 2200))) {
        [IO.File]::WriteAllText($config, ('<MetaDataObject version="2.20"><Name>Тест</Name>' + $padding + '</MetaDataObject>'), [Text.UTF8Encoding]::new($true))
        foreach ($path in $paths) {
            $tokens = $null; $errors = $null
            $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $root "skills/$path"), [ref]$tokens, [ref]$errors)
            if ($errors.Count) { throw "Parse error: $path" }
            $fn = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Detect-FormatVersion' }, $true)
            if (-not $fn) { throw "Function missing: $path" }
            Invoke-Expression $fn.Extent.Text
            try { $version = Detect-FormatVersion $temp } catch { throw "$path : $_" }
            if ($version -ne '2.20') { throw "$path returned $version" }
        }
    }
    Write-Host 'All ten format detectors passed short and long UTF-8 inputs.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
