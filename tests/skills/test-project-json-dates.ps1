$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$temp = Join-Path ([IO.Path]::GetTempPath()) ('project-json-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $temp 'synthetic-db') | Out-Null
    $project = [ordered]@{
        testArgs = @('2024-01-01T03:00:00+03:00', 'plain')
        one = @('2024-01-01T00:00:00Z'); empty = @(); nullValue = $null
        single = '2024-01-01T03:00:00+03:00'
        databases = @(
            @{ name = '2024-01-01T03:00:00+03:00'; type = 'server'; server = 'example'; ref = 'demo'; role = 'prod' },
            @{ name = '2024-01-01T03:00:00+03:00'; type = 'file'; path = 'synthetic-db'; role = 'prod' }
        )
    }
    [IO.File]::WriteAllText((Join-Path $temp '.v8-project.json'), ($project | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    foreach ($skill in @('db-run', 'db-create', 'epf-build')) {
        $path = Join-Path $root "skills/1c-$skill/scripts/$skill.ps1"
        $tokens = $null; $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
        if ($errors.Count) { throw "Parse error in $skill" }
        foreach ($name in @('Split-PlatformArguments', 'Find-V8ProjectFile', 'Get-ProjectPlatformArguments')) {
            $fn = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
            if (-not $fn) { throw "$skill missing $name" }
            Invoke-Expression $fn.Extent.Text
        }
        $actual = @(Get-ProjectPlatformArguments -StartDir $temp -Key 'testArgs')
        if ($actual.Count -ne 2 -or $actual[0] -cne '2024-01-01T03:00:00+03:00' -or $actual[1] -cne 'plain') {
            throw "$skill changed project arguments: $($actual -join ', ')"
        }
        if (@(Get-ProjectPlatformArguments -StartDir $temp -Key 'one')[0] -cne '2024-01-01T00:00:00Z') { throw "$skill changed singleton array" }
        if (@(Get-ProjectPlatformArguments -StartDir $temp -Key 'single')[0] -cne '2024-01-01T03:00:00+03:00') { throw "$skill changed scalar" }
        if (@(Get-ProjectPlatformArguments -StartDir $temp -Key 'empty').Count -ne 0) { throw "$skill changed empty array" }
        if (@(Get-ProjectPlatformArguments -StartDir $temp -Key 'nullValue').Count -ne 0) { throw "$skill changed null" }
    }
    $originalDirectory = [IO.Directory]::GetCurrentDirectory()
    [IO.Directory]::SetCurrentDirectory($temp)
    try {
        foreach ($skill in @('db-load-dt', 'db-update', 'db-load-cf', 'db-cfe-admin', 'db-load-xml', 'db-load-git', 'storage-ops')) {
            $path = Join-Path $root "skills/1c-$skill/scripts/$skill.ps1"
            $tokens = $null; $errors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
            if ($errors.Count) { throw "Parse error in $skill" }
            $functionTexts = [System.Collections.Generic.List[string]]::new()
            foreach ($name in @('Get-InfoBaseStartDir', 'Find-GuardProjectFile', 'Get-InfoBaseServerKey', 'Get-InfoBaseRecordKind', 'Get-InfoBaseFinalPath', 'Get-InfoBasePathKey', 'Get-InfoBaseRole', 'Assert-InfoBaseMutable')) {
                $fn = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
                if (-not $fn) { throw "$skill missing $name" }
                Invoke-Expression $fn.Extent.Text
                $functionTexts.Add($fn.Extent.Text)
            }
            $role = Get-InfoBaseRole -InfoBaseServer 'example' -InfoBaseRef 'demo'
            if ($role.Role -cne 'prod' -or $role.Name -cne '2024-01-01T03:00:00+03:00') { throw "$skill changed database name or role: $($role.Name) / $($role.Role)" }
            $fileRole = Get-InfoBaseRole -InfoBasePath (Join-Path $temp 'synthetic-db')
            if ($fileRole.Role -cne 'prod' -or $fileRole.Name -cne '2024-01-01T03:00:00+03:00') { throw "$skill changed file database name or role" }
            $child = Join-Path $temp 'guard-check.ps1'
            $childScript = 'param([string]$TrialDir, [string]$Mode)' + "`n" + ($functionTexts -join "`n") + @'

[IO.Directory]::SetCurrentDirectory($TrialDir)
if ($Mode -eq 'server') { Assert-InfoBaseMutable -InfoBaseServer 'example' -InfoBaseRef 'demo' }
elseif ($Mode -eq 'file') { Assert-InfoBaseMutable -InfoBasePath (Join-Path $TrialDir 'synthetic-db') }
else { Assert-InfoBaseMutable -InfoBaseServer 'example' -InfoBaseRef 'demo' -AllowProd }
'@
            [IO.File]::WriteAllText($child, $childScript, [Text.UTF8Encoding]::new($false))
            $hostExe = (Get-Process -Id $PID).Path
            foreach ($mode in @('server', 'file', 'allowed')) {
                & $hostExe -NoProfile -File $child $temp $mode 2>&1 | Out-Null
                $expected = if ($mode -eq 'allowed') { 0 } else { 1 }
                if ($LASTEXITCODE -ne $expected) { throw "$skill guard $mode exited $LASTEXITCODE instead of $expected" }
            }
        }
    } finally { [IO.Directory]::SetCurrentDirectory($originalDirectory) }
    Write-Host 'Project platform arguments preserve date-like strings.'
} finally {
    if (Test-Path -LiteralPath $temp) {
        $resolved = (Resolve-Path -LiteralPath $temp).Path
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not [IO.Path]::GetFileName($resolved).StartsWith('project-json-')) {
            throw "Refusing to remove unexpected test directory: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
