<#
.SYNOPSIS
    Install Cursor skills and rules for 1C:Enterprise development.

.DESCRIPTION
    Copies skills, rules, and commands to .cursor/ directory
    in the target project or globally (~/.cursor/).

.PARAMETER ProjectDir
    Target project directory. Default: current directory.

.PARAMETER Global
    Install globally to ~/.cursor/ instead of project-level.

.PARAMETER RulesOnly
    Install only rules (skip skills and commands).

.PARAMETER SkillsOnly
    Install only skills (skip rules and commands).

.EXAMPLE
    .\install.ps1
    # Install to current project (.cursor/)

.EXAMPLE
    .\install.ps1 -ProjectDir "C:\Projects\my-1c-project"
    # Install to specific project

.EXAMPLE
    .\install.ps1 -Global
    # Install globally (~/.cursor/)
#>

[CmdletBinding()]
param(
    [string]$ProjectDir = (Get-Location).Path,
    [switch]$Global,
    [switch]$RulesOnly,
    [switch]$SkillsOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Determine target directory
if ($Global) {
    $TargetBase = Join-Path $env:USERPROFILE ".cursor"
} else {
    $TargetBase = Join-Path $ProjectDir ".cursor"
}

$installRules    = -not $SkillsOnly
$installSkills   = -not $RulesOnly
$installCommands = (-not $RulesOnly) -and (-not $SkillsOnly)

$stats = @{ rules = 0; skills = 0; commands = 0 }

# ── Install rules ────────────────────────────────────────────────────────
if ($installRules) {
    $RulesSource = Join-Path $ScriptDir "rules"
    $RulesTarget = Join-Path $TargetBase "rules"

    if (Test-Path $RulesSource) {
        if (-not (Test-Path $RulesTarget)) {
            New-Item -ItemType Directory -Path $RulesTarget -Force | Out-Null
        }

        Get-ChildItem -Path $RulesSource -Filter "*.mdc" | ForEach-Object {
            Copy-Item -Path $_.FullName -Destination $RulesTarget -Force
            $stats.rules++
        }

        Write-Host "Rules: $($stats.rules) files -> $RulesTarget" -ForegroundColor Green
    } else {
        Write-Host "Rules: source directory not found ($RulesSource)" -ForegroundColor Yellow
    }
}

# ── Install skills ───────────────────────────────────────────────────────
if ($installSkills) {
    $SkillsSource = Join-Path $ScriptDir "skills"
    $SkillsTarget = Join-Path $TargetBase "skills"

    if (Test-Path $SkillsSource) {
        if (-not (Test-Path $SkillsTarget)) {
            New-Item -ItemType Directory -Path $SkillsTarget -Force | Out-Null
        }

        Get-ChildItem -Path $SkillsSource -Directory | ForEach-Object {
            $dest = Join-Path $SkillsTarget $_.Name
            if (Test-Path $dest) {
                Remove-Item -Path $dest -Recurse -Force
            }
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
            $stats.skills++
        }

        Write-Host "Skills: $($stats.skills) directories -> $SkillsTarget" -ForegroundColor Green
    } else {
        Write-Host "Skills: source directory not found ($SkillsSource)" -ForegroundColor Yellow
    }
}

# ── Install commands ─────────────────────────────────────────────────────
if ($installCommands) {
    $CommandsSource = Join-Path $ScriptDir "commands"
    $CommandsTarget = Join-Path $TargetBase "commands"

    if (Test-Path $CommandsSource) {
        if (-not (Test-Path $CommandsTarget)) {
            New-Item -ItemType Directory -Path $CommandsTarget -Force | Out-Null
        }

        Get-ChildItem -Path $CommandsSource -File | ForEach-Object {
            Copy-Item -Path $_.FullName -Destination $CommandsTarget -Force
            $stats.commands++
        }

        Write-Host "Commands: $($stats.commands) files -> $CommandsTarget" -ForegroundColor Green
    } else {
        Write-Host "Commands: source directory not found ($CommandsSource)" -ForegroundColor Yellow
    }
}

# ── Summary ──────────────────────────────────────────────────────────────
$total = $stats.rules + $stats.skills + $stats.commands
if ($total -gt 0) {
    Write-Host "`nInstalled: $($stats.rules) rules, $($stats.skills) skills, $($stats.commands) commands" -ForegroundColor Cyan
    Write-Host "Target: $TargetBase" -ForegroundColor Cyan
} else {
    Write-Host "`nNothing installed." -ForegroundColor Yellow
}
