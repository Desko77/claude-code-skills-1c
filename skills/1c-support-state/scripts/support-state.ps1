# support-state v1.0 - Read and switch 1C configuration support state in XML dump
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Чтение и переключение состояния поддержки конфигурации 1С в XML-выгрузке

.DESCRIPTION
    Работает с файлом Ext/ParentConfigurations.bin внутри выгрузки конфигурации.
    Режимы: -Get (показать состояние, по умолчанию), -Set (правило объекта),
    -Capability (возможность изменения всей конфигурации).
    Изменения касаются только файлов выгрузки; для эффекта в ИБ выгрузку
    нужно загрузить обратно (полная загрузка).

.PARAMETER Path
    XML-файл объекта, каталог объекта или корень выгрузки

.PARAMETER Get
    Показать состояние поддержки (режим по умолчанию)

.PARAMETER Set
    Переключить правило объекта: editable | off-support | locked

.PARAMETER Capability
    Включить/выключить возможность изменения конфигурации: on | off

.EXAMPLE
    .\support-state.ps1 -Path "C:\Dump\MyConfig\Documents\МойДокумент.xml"

.EXAMPLE
    .\support-state.ps1 -Path "C:\Dump\MyConfig\Documents\МойДокумент.xml" -Set editable

.EXAMPLE
    .\support-state.ps1 -Path "C:\Dump\MyConfig" -Capability on
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Path,

    [Parameter(Mandatory=$false)]
    [switch]$Get,

    [Parameter(Mandatory=$false)]
    [ValidateSet("editable", "off-support", "locked")]
    [string]$Set,

    [Parameter(Mandatory=$false)]
    [ValidateSet("on", "off")]
    [string]$Capability
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$stateByF1 = @{
    "0" = "locked (на замке, правка запрещена)"
    "1" = "editable (редактируется с сохранением поддержки)"
    "2" = "off-support (снят с поддержки)"
}
$f1ByState = @{ "editable" = "1"; "off-support" = "2"; "locked" = "0" }

$chosen = 0
if ($Get) { $chosen++ }
if ($Set) { $chosen++ }
if ($Capability) { $chosen++ }
if ($chosen -eq 0) { $Get = $true }
elseif ($chosen -gt 1) {
    [Console]::Error.WriteLine("Error: specify only one of -Get, -Set, -Capability")
    exit 1
}

function Get-RootUuid([string]$XmlPath) {
    if (-not (Test-Path -LiteralPath $XmlPath -PathType Leaf)) { return $null }
    try {
        [xml]$doc = Get-Content -LiteralPath $XmlPath -Raw -Encoding UTF8
    } catch { return $null }
    if (-not $doc.DocumentElement) { return $null }
    foreach ($child in $doc.DocumentElement.ChildNodes) {
        if ($child.NodeType -eq 'Element') {
            $u = $child.GetAttribute("uuid")
            if ($u) { return $u }
        }
    }
    return $null
}

function Save-Bin([string]$BinFile, [string]$Content) {
    [System.IO.File]::WriteAllText($BinFile, $Content, [System.Text.UTF8Encoding]::new($true))
}

# --- Resolve target: object uuid + configuration root + bin path ---
if (-not (Test-Path -LiteralPath $Path)) {
    [Console]::Error.WriteLine("Error: path not found: $Path")
    exit 1
}
$rp = (Resolve-Path -LiteralPath $Path).Path
$elemUuid = $null
if (Test-Path -LiteralPath $rp -PathType Leaf) { $elemUuid = Get-RootUuid $rp }
$cfgDir = $null
$binPath = $null
$d = if (Test-Path -LiteralPath $rp -PathType Container) { $rp } else { Split-Path $rp -Parent }
for ($i = 0; $i -lt 12; $i++) {
    if (-not $elemUuid) { $elemUuid = Get-RootUuid ($d + ".xml") }
    if (-not $cfgDir) {
        $candBin = Join-Path $d "Ext\ParentConfigurations.bin"
        $cfgXml = Join-Path $d "Configuration.xml"
        if ((Test-Path -LiteralPath $candBin) -or (Test-Path -LiteralPath $cfgXml)) {
            $cfgDir = $d
            $binPath = $candBin
        }
    }
    if ($elemUuid -and $cfgDir) { break }
    $parent = Split-Path $d -Parent
    if (-not $parent -or $parent -eq $d) { break }
    $d = $parent
}
if (-not $cfgDir) {
    [Console]::Error.WriteLine("Error: configuration root (Configuration.xml) not found above: $rp")
    exit 1
}
if (-not $elemUuid) { $elemUuid = Get-RootUuid (Join-Path $cfgDir "Configuration.xml") }

$cfgXmlPath = Join-Path $cfgDir "Configuration.xml"
if (Test-Path -LiteralPath $cfgXmlPath) {
    $cfgText = Get-Content -LiteralPath $cfgXmlPath -Raw -Encoding UTF8
    if ($cfgText -match "ConfigurationExtensionPurpose") {
        Write-Host "Это расширение конфигурации - состояние поддержки не применимо."
        exit 0
    }
}
if (-not (Test-Path -LiteralPath $binPath)) {
    Write-Host "Конфигурация не на поддержке (нет Ext/ParentConfigurations.bin) - переключать нечего."
    exit 0
}

# --- Read bin ---
$raw = [System.IO.File]::ReadAllBytes($binPath)
if ($raw.Length -le 32) {
    Write-Host "Поддержка снята полностью (пустой ParentConfigurations.bin)."
    exit 0
}
$bomOffset = 0
if ($raw.Length -ge 3 -and $raw[0] -eq 0xEF -and $raw[1] -eq 0xBB -and $raw[2] -eq 0xBF) { $bomOffset = 3 }
$text = [System.Text.Encoding]::UTF8.GetString($raw, $bomOffset, $raw.Length - $bomOffset)
if ($text.IndexOf([char]0xFFFD) -ge 0) {
    [Console]::Error.WriteLine("Error: неизвестный формат ParentConfigurations.bin")
    exit 1
}

$m = [regex]::Match($text, "^\{6,(\d+),(\d+),")
if (-not $m.Success) {
    [Console]::Error.WriteLine("Error: неизвестный формат ParentConfigurations.bin")
    exit 1
}
$g = $m.Groups[1].Value
$k = $m.Groups[2].Value

# --- Mode: -Get ---
if ($Get) {
    if ($g -eq "1") {
        Write-Host "Возможность изменения конфигурации: ВЫКЛЮЧЕНА (вся конфигурация read-only)"
    } else {
        Write-Host "Возможность изменения конфигурации: включена"
    }
    Write-Host "Конфигураций поставщика на поддержке: $k"
    $headerRx = '([0-9a-f-]{36}),\d+,([0-9a-f-]{36}),"((?:[^"]|"")*)","((?:[^"]|"")*)","((?:[^"]|"")*)",(\d+)'
    $idx = 0
    foreach ($mm in [regex]::Matches($text, $headerRx)) {
        $idx++
        $ver = $mm.Groups[3].Value -replace '""', '"'
        $vendor = $mm.Groups[4].Value -replace '""', '"'
        $name = $mm.Groups[5].Value -replace '""', '"'
        Write-Host ("  {0}. {1} ({2}), версия {3}, записей: {4}" -f $idx, $name, $vendor, $ver, $mm.Groups[6].Value)
    }
    if ($elemUuid) {
        $u = [regex]::Escape($elemUuid.ToLower())
        $found = [regex]::Matches($text, "(?<![0-9a-f-])([0-2]),0,$u")
        if ($found.Count -gt 0) {
            $vals = @($found | ForEach-Object { $_.Groups[1].Value })
            $eff = ($vals | Sort-Object)[0]
            $note = ""
            if (($vals | Select-Object -Unique).Count -gt 1) { $note = " (по вхождениям: $($vals -join ','))" }
            Write-Host ("Объект {0}: вхождений {1}, правило: {2}{3}" -f $elemUuid, $found.Count, $stateByF1[$eff], $note)
        } else {
            Write-Host "Объект ${elemUuid}: не найден в поддержке (свое добавление)"
        }
    }
    exit 0
}

# --- Mode: -Capability ---
if ($Capability) {
    $target = if ($Capability -eq "on") { "0" } else { "1" }
    if ($g -eq $target) {
        Write-Host "Уже в целевом состоянии - изменения не требуются."
        exit 0
    }
    $text = [regex]::new("^(\{6,)\d+(,)").Replace($text, "`${1}$target`${2}", 1)
    # заголовок каждого блока поставщика: guidA,X,guidVendor - X следует за G
    $text = [regex]::Replace($text, "([0-9a-f-]{36}),\d+,([0-9a-f-]{36})", "`${1},$target,`${2}")
    $text = [regex]::Replace($text, "(?<![0-9a-f-])[0-2],0,([0-9a-f-]{36})", "$target,0,`${1}")
    Save-Bin $binPath $text
    if ($Capability -eq "on") {
        Write-Host "Возможность изменения конфигурации ВКЛЮЧЕНА. Все объекты поставщика - на замке." -ForegroundColor Green
        Write-Host "Дальше включай правку точечно: -Set editable по нужным объектам."
    } else {
        Write-Host "Возможность изменения конфигурации ВЫКЛЮЧЕНА. Вся конфигурация read-only, пообъектные правила сброшены." -ForegroundColor Green
    }
    exit 0
}

# --- Mode: -Set ---
if ($g -eq "1") {
    [Console]::Error.WriteLine("Возможность изменения конфигурации выключена - пообъектное переключение недоступно.")
    [Console]::Error.WriteLine("Сначала: support-state.ps1 -Path `"$Path`" -Capability on")
    exit 1
}
if (-not $elemUuid) {
    [Console]::Error.WriteLine("Error: не удалось определить объект по пути: $rp")
    exit 1
}
$uLow = $elemUuid.ToLower()
$u = [regex]::Escape($uLow)
$foundSet = [regex]::Matches($text, "(?<![0-9a-f-])([0-2]),0,$u")
$n = $foundSet.Count
if ($n -eq 0) {
    Write-Host "Объект не найден в поддержке (свое добавление) - переключать нечего."
    exit 0
}
$newF1 = $f1ByState[$Set]
$setVals = @($foundSet | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
if ($setVals.Count -eq 1 -and $setVals[0] -eq $newF1) {
    Write-Host "Объект уже в целевом состоянии - изменения не требуются."
    exit 0
}
$text = [regex]::Replace($text, "(?<![0-9a-f-])[0-2],0,$u", "$newF1,0,$uLow")
Save-Bin $binPath $text
Write-Host ("Объект {0} -> {1}" -f $elemUuid, $stateByF1[$newF1]) -ForegroundColor Green
Write-Host "Изменено записей: $n"
exit 0
