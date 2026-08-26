# mxl-compile v1.1 — Compile 1C spreadsheet from JSON
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$JsonPath,

	[Parameter(Mandatory)]
	[string]$OutputPath
)

$ErrorActionPreference = "Stop"

# Версия формата берется из Configuration.xml вверх по дереву от каталога вывода: от нее
# зависит состав шапки макета.
function Get-TemplateFormatVersion([string]$startPath) {
	$d = if (Test-Path $startPath -PathType Container) { $startPath } else { Split-Path $startPath -Parent }
	if (-not $d) { $d = (Get-Location).Path }
	for ($i = 0; $i -lt 20 -and $d; $i++) {
		$cfgPath = Join-Path $d "Configuration.xml"
		if (Test-Path $cfgPath) {
			$head = [System.IO.File]::ReadAllText($cfgPath, [System.Text.Encoding]::UTF8)
			if ($head -match '<MetaDataObject[^>]+version="(\d+\.\d+)"') { return $Matches[1] }
		}
		$parent = Split-Path $d -Parent
		if ($parent -eq $d) { break }
		$d = $parent
	}
	return "2.17"
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Support guard (Ext/ParentConfigurations.bin) ---
# See docs/1c-support-state-spec.md. Blocks edits of vendor objects "на замке" /
# read-only configs unless allowed. Trigger = bin present; reaction from
# .v8-project.json editingAllowedCheck (deny|warn|off, default deny). Never
# throws — guard errors degrade to allow.
function Get-RootUuid([string]$xmlPath) {
	if (-not (Test-Path $xmlPath)) { return $null }
	try {
		[xml]$mx = Get-Content -Path $xmlPath -Encoding UTF8
		$el = $mx.DocumentElement.FirstChild
		while ($el -and $el.NodeType -ne 'Element') { $el = $el.NextSibling }
		if ($el) { $u = $el.GetAttribute("uuid"); if ($u) { return $u } }
	} catch {}
	return $null
}
function Test-ExternalObjectRoot([string]$xmlPath) {
	if (-not (Test-Path $xmlPath)) { return $false }
	try {
		[xml]$mx = Get-Content -Path $xmlPath -Encoding UTF8
		$el = $mx.DocumentElement.FirstChild
		while ($el -and $el.NodeType -ne 'Element') { $el = $el.NextSibling }
		if ($el) { return @('ExternalDataProcessor','ExternalReport') -contains $el.LocalName }
	} catch {}
	return $false
}
function Find-V8Project([string]$startDir) {
	$d = $startDir
	for ($i = 0; $i -lt 20 -and $d; $i++) {
		$pj = Join-Path $d ".v8-project.json"
		if (Test-Path $pj) { return $pj }
		$parent = [System.IO.Path]::GetDirectoryName($d)
		if ($parent -eq $d) { break }
		$d = $parent
	}
	return $null
}
function Get-EditMode([string]$cfgDir) {
	try {
		$pj = Find-V8Project (Get-Location).Path
		if (-not $pj) { $pj = Find-V8Project $cfgDir }
		if (-not $pj) { return 'deny' }
		$proj = Get-Content -Raw $pj | ConvertFrom-Json
		$cfgFull = [System.IO.Path]::GetFullPath($cfgDir).TrimEnd('\', '/')
		if ($proj.databases) {
			foreach ($db in $proj.databases) {
				if ($db.configSrc) {
					$src = [System.IO.Path]::GetFullPath($db.configSrc).TrimEnd('\', '/')
					if ($cfgFull -eq $src -or $cfgFull.StartsWith($src + [System.IO.Path]::DirectorySeparatorChar)) {
						if ($db.editingAllowedCheck) { return $db.editingAllowedCheck }
					}
				}
			}
		}
		if ($proj.editingAllowedCheck) { return $proj.editingAllowedCheck }
		return 'deny'
	} catch { return 'deny' }
}
function Assert-EditAllowed([string]$targetPath, [string]$require) {
	try {
		$rp = $targetPath
		try { $rp = (Resolve-Path $targetPath -ErrorAction Stop).Path } catch {}
		# Autonomous external object (EPF/ERF): never part of a config on support (issue #39).
		if (Test-ExternalObjectRoot $rp) { return }
		$elemUuid = Get-RootUuid $rp
		$cfgDir = $null; $binPath = $null
		$d = if (Test-Path $rp -PathType Container) { $rp } else { [System.IO.Path]::GetDirectoryName($rp) }
		for ($i = 0; $i -lt 12 -and $d; $i++) {
			if (Test-ExternalObjectRoot "$d.xml") { return }
			if (-not $elemUuid) { $elemUuid = Get-RootUuid "$d.xml" }
			if (-not $cfgDir) {
				$cand = Join-Path (Join-Path $d "Ext") "ParentConfigurations.bin"
				if ((Test-Path $cand) -or (Test-Path (Join-Path $d "Configuration.xml"))) { $cfgDir = $d; $binPath = $cand }
			}
			if ($elemUuid -and $cfgDir) { break }
			$parent = [System.IO.Path]::GetDirectoryName($d)
			if ($parent -eq $d) { break }
			$d = $parent
		}
		# New object (no element file): fall back to config root uuid.
		if (-not $elemUuid -and $cfgDir) { $elemUuid = Get-RootUuid (Join-Path $cfgDir "Configuration.xml") }
		if (-not $binPath -or -not (Test-Path $binPath)) { return }
		$bytes = [System.IO.File]::ReadAllBytes($binPath)
		if ($bytes.Length -le 32) { return }
		$start = 0
		if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $start = 3 }
		$text = [System.Text.Encoding]::UTF8.GetString($bytes, $start, $bytes.Length - $start)
		$hm = [regex]::Match($text, '^\{6,(\d+),(\d+),')
		if (-not $hm.Success) { return }
		$G = [int]$hm.Groups[1].Value
		$K = [int]$hm.Groups[2].Value
		if ($K -eq 0) { return }
		$best = $null
		if ($elemUuid) {
			$u = [regex]::Escape($elemUuid.ToLower())
			foreach ($m in [regex]::Matches($text, "([0-2]),0,$u")) {
				$f1 = [int]$m.Groups[1].Value
				if ($null -eq $best -or $f1 -lt $best) { $best = $f1 }
			}
		}
		$blocked = $false; $code = ""; $reason = ""
		if ($G -eq 1) { $blocked = $true; $code = "capability-off"; $reason = "возможность изменения конфигурации выключена (вся конфигурация read-only)" }
		elseif ($require -eq 'removed') {
			if ($null -ne $best -and $best -ne 2) { $blocked = $true; $code = "not-removed"; $reason = "объект не снят с поддержки — удаление сломает обновления" }
		}
		else {
			if ($null -ne $best -and $best -eq 0) { $blocked = $true; $code = "locked"; $reason = "объект на замке — редактирование сломает обновления" }
		}
		if (-not $blocked) { return }
		$mode = Get-EditMode $cfgDir
		if ($mode -eq 'off') { return }
		# Use Console.Error (not Write-Error) — under ErrorActionPreference=Stop the
		# latter throws and would be swallowed by this function's own catch.
		if ($mode -eq 'warn') { [Console]::Error.WriteLine("[support-guard] ПРЕДУПРЕЖДЕНИЕ: $reason. Цель: $rp"); return }
		$head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
		$cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) — состояние поддержки менять не нужно, обновления вендора сохраняются."
		$offNote = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
		if ($code -eq "capability-off") {
			$state = "Состояние: у всей конфигурации выключена возможность изменения (режим read-only «из коробки») — поэтому объект «$rp» редактировать нельзя."
			$fix = "Либо снять защиту явно (навык support-edit, два шага):`n  1. support-edit -Path ""$cfgDir"" -Capability on — включить возможность изменения (объекты пока остаются на замке);`n  2. support-edit -Path ""$rp"" -Set editable — открыть этот объект для редактирования.`n  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
		} elseif ($code -eq "not-removed") {
			$state = "Состояние: объект «$rp» на поддержке (не снят с поддержки) — его удаление разорвёт обновления вендора."
			$fix = "Либо сначала снять объект с поддержки, затем удалять:`n  support-edit -Path ""$rp"" -Set off-support — объект уходит из-под обновлений, после этого удаление безопасно."
		} else {
			$state = "Состояние: объект «$rp» на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
			$fix = "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):`n  support-edit -Path ""$rp"" -Set editable — редактировать и дальше получать обновления вендора (возможны конфликты слияния);`n  support-edit -Path ""$rp"" -Set off-support — снять с поддержки: обновления по объекту больше не приходят."
		}
		[Console]::Error.WriteLine("$head`n$state`n$cfe`n$fix`n$offNote")
		exit 1
	} catch { return }
}
# --- Конец общего блока гарда поддержки ---

# --- 1. Load and validate JSON ---

if (-not (Test-Path $JsonPath)) {
	[Console]::Error.WriteLine("File not found: $JsonPath")
	exit 1
}

$json = Get-Content -Raw -Encoding UTF8 $JsonPath
$def = $json | ConvertFrom-Json

if (-not $def.columns) {
	[Console]::Error.WriteLine("Required field 'columns' is missing")
	exit 1
}
if (-not $def.areas -and -not $def.rows) {
	[Console]::Error.WriteLine("Required field 'areas' is missing")
	exit 1
}

# Идентификатор набора колонок выводится из его имени: UUID версии 3 (MD5) без
# пространства имен - одно и то же имя всегда дает один и тот же идентификатор.
function Get-NameUuid {
	param([string]$name)
	$md5 = [System.Security.Cryptography.MD5]::Create()
	$bytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($name))
	$bytes[6] = [byte](($bytes[6] -band 0x0F) -bor 0x30)
	$bytes[8] = [byte](($bytes[8] -band 0x3F) -bor 0x80)
	$hex = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
	return "$($hex.Substring(0,8))-$($hex.Substring(8,4))-$($hex.Substring(12,4))-$($hex.Substring(16,4))-$($hex.Substring(20,12))"
}

# Координаты области 1-based, а ноль дал бы -1 - сентинел отсутствующей оси.
function Test-NamedAreaBounds {
	param([int]$begin, [int]$end, [string]$axis, [int]$index, [string]$name)
	if ($begin -lt 1 -or $end -lt $begin) {
		[Console]::Error.WriteLine("namedAreas: '$axis' must be a 1-based number or ascending range, got `"$begin-$end`": namedAreas[$index] `"$name`"")
		exit 1
	}
	return @{ Begin = $begin; End = $end }
}

# Ось именованной области задается числом или диапазоном; список через запятую не
# описывает прямоугольник и потому отвергается.
function Get-NamedAreaRange {
	param($value, [string]$axis, [int]$index, [string]$name)
	$text = "$value"
	if ($text -match ',') {
		[Console]::Error.WriteLine("namedAreas: '$axis' must be a single number or range, got list `"$text`": namedAreas[$index] `"$name`"")
		exit 1
	}
	if ($text -match '^\s*(\d+)\s*-\s*(\d+)\s*$') { return Test-NamedAreaBounds ([int]$Matches[1]) ([int]$Matches[2]) $axis $index $name }
	if ($text -match '^\s*(\d+)\s*$') { return Test-NamedAreaBounds ([int]$Matches[1]) ([int]$Matches[1]) $axis $index $name }
	[Console]::Error.WriteLine("namedAreas: '$axis' must be a single number or range, got `"$text`": namedAreas[$index] `"$name`"")
	exit 1
}

# Строка задается массивом: элемент на колонку слева направо. Такая запись разворачивается в
# канонический вид до расчета форматов и вывода, поэтому дальше по коду вид строки один.
function ConvertTo-CellTable {
	param($cell)
	if ($cell -is [hashtable]) { return $cell }
	$t = @{}
	foreach ($p in $cell.PSObject.Properties) { $t[$p.Name] = $p.Value }
	return $t
}

function ConvertTo-RowTable {
	param($row)
	if ($row -is [hashtable]) { return $row }
	$t = @{}
	foreach ($p in $row.PSObject.Properties) { $t[$p.Name] = $p.Value }
	if ($t.cells) {
		$cells = @()
		foreach ($c in @($t.cells)) { $cells += (ConvertTo-CellTable $c) }
		$t.cells = $cells
	}
	return $t
}

function Get-ShorthandCell {
	param([string]$value, [int]$col)
	# Фигурные скобки означают параметр, квадратные внутри строки - шаблонный текст.
	if ($value -match '^\{(.+)\}$') { return @{ col = $col; param = $Matches[1] } }
	if ($value -match '\[.+\]') { return @{ col = $col; template = $value } }
	return @{ col = $col; text = $value }
}

function Expand-AreaRows {
	param($areaRows, [string]$areaName)
	$expanded = @()
	$prevOccupied = @{}
	$rowNo = 0
	foreach ($row in @($areaRows)) {
		$rowNo++
		if ($row -isnot [array]) {
			$table = ConvertTo-RowTable $row
			$occupied = @{}
			if ($table.cells) {
				foreach ($c in @($table.cells)) {
					# Колонка без явного номера раскладывается позже, в основном проходе: до
					# него занятые ей клетки неизвестны, поэтому в опору для '|' она не идет.
					if (-not $c.col) { continue }
					$span = if ($c.span) { [int]$c.span } else { 1 }
					for ($k = 0; $k -lt $span; $k++) { $occupied[[int]$c.col + $k] = $c }
				}
			}
			$prevOccupied = $occupied
			$expanded += $table
			continue
		}

		$cells = @()
		$occupied = @{}
		$lastCell = $null
		$colNo = 0
		foreach ($item in $row) {
			$colNo++
			if ($null -eq $item) { $lastCell = $null; continue }

			if ($item -is [string] -and $item -eq ">") {
				if (-not $lastCell) {
					[Console]::Error.WriteLine("Row shorthand: '>' has no cell to the left: area `"$areaName`", row $rowNo, cell $colNo")
					exit 1
				}
				$curSpan = if ($lastCell.span) { [int]$lastCell.span } else { 1 }
				$lastCell.span = $curSpan + 1
				$occupied[$colNo] = $lastCell
				continue
			}

			if ($item -is [string] -and $item -eq "|") {
				$above = $prevOccupied[$colNo]
				if (-not $above) {
					[Console]::Error.WriteLine("Row shorthand: '|' has no cell above: area `"$areaName`", row $rowNo, cell $colNo")
					exit 1
				}
				$curRowspan = if ($above.rowspan) { [int]$above.rowspan } else { 1 }
				$above.rowspan = $curRowspan + 1
				$occupied[$colNo] = $above
				$lastCell = $null
				continue
			}

			if ($item -is [string]) {
				$cell = Get-ShorthandCell -value $item -col $colNo
			} else {
				$cell = ConvertTo-CellTable $item
				if ($cell.Contains("col")) {
					[Console]::Error.WriteLine("Row shorthand: cell object must not carry 'col': area `"$areaName`", row $rowNo, cell $colNo")
					exit 1
				}
				$cell.col = $colNo
			}
			$cells += $cell
			$span = if ($cell.span) { [int]$cell.span } else { 1 }
			for ($k = 0; $k -lt $span; $k++) { $occupied[$colNo + $k] = $cell }
			$lastCell = $cell
		}
		$prevOccupied = $occupied
		$expanded += @{ cells = $cells }
	}
	return ,$expanded
}

# Строки вне именованных областей обрабатываются как безымянная область: в файл она не
# попадает, но строки выгружаются так же.
$sheetAreas = @()
if ($def.areas) { $sheetAreas += @($def.areas) }
if ($def.rows) {
	$sheetAreas += (New-Object PSObject -Property @{ name = ""; rows = $def.rows })
}

$normalizedAreas = @()
foreach ($area in $sheetAreas) {
	$normalizedAreas += (New-Object PSObject -Property @{
		name = $area.name
		columnSet = $area.columnSet
		rows = (Expand-AreaRows -areaRows $area.rows -areaName "$($area.name)")
	})
}
$sheetAreas = $normalizedAreas

$totalColumns = [int]$def.columns
# Языки, на которые идет текст ячейки, заданный одной строкой.
$textLanguages = if ($def.textLanguages) { @($def.textLanguages | ForEach-Object { "$_" }) } else { @("ru") }
$defaultWidth = if ($def.defaultWidth) { [int]$def.defaultWidth } else { 10 }

# --- 2. Build font palette ---

$fontMap = [ordered]@{}   # name -> 0-based index
$fontEntries = @()        # array of hashtables

function Add-Font {
	param([string]$name, $fontDef)
	$face = if ($fontDef.face) { $fontDef.face } else { "Arial" }
	$size = if ($fontDef.size) {
		[System.Convert]::ToString([double]$fontDef.size, [System.Globalization.CultureInfo]::InvariantCulture)
	} else { "10" }
	$bold = if ($fontDef.bold -eq $true) { "true" } else { "false" }
	$italic = if ($fontDef.italic -eq $true) { "true" } else { "false" }
	$underline = if ($fontDef.underline -eq $true) { "true" } else { "false" }
	$strikeout = if ($fontDef.strikeout -eq $true) { "true" } else { "false" }

	$idx = $script:fontEntries.Count
	$script:fontMap[$name] = $idx
	$script:fontEntries += @{
		# Шрифт задается либо своими свойствами, либо ссылкой на элемент стиля или
		# системный шрифт - тогда своих свойств у него нет.
		Ref       = if ($fontDef.ref) { "$($fontDef.ref)" } else { "" }
		Kind      = if ($fontDef.kind) { "$($fontDef.kind)" } else { "Absolute" }
		Namespace = $fontDef.namespace
		Face      = $face
		Size      = $size
		Bold      = $bold
		Italic    = $italic
		Underline = $underline
		Strikeout = $strikeout
	}
}

# Add user-defined fonts
$hasDefault = $false
if ($def.fonts) {
	foreach ($prop in $def.fonts.PSObject.Properties) {
		if ($prop.Name -eq "default") { $hasDefault = $true }
		Add-Font -name $prop.Name -fontDef $prop.Value
	}
}

# Ensure default font exists
# Шрифт по умолчанию не объявляется: платформа пишет шрифт только там, где он задан.

# --- 3. Determine line palette ---

$hasThinBorders = $false
$hasThickBorders = $false

# Scan styles for border usage
if ($def.styles) {
	foreach ($prop in $def.styles.PSObject.Properties) {
		$s = $prop.Value
		if ($s.border -and $s.border -ne "none") {
			if ($s.borderWidth -eq "thick") {
				$hasThickBorders = $true
			} else {
				$hasThinBorders = $true
			}
		}
	}
}

$thinLineIndex = -1
$thickLineIndex = -1
$lineCount = 0
if ($hasThinBorders) {
	$thinLineIndex = $lineCount; $lineCount++
}
if ($hasThickBorders) {
	$thickLineIndex = $lineCount; $lineCount++
}

# --- 4. Parse column width specs ---

function Parse-ColumnSpec {
	param([string]$spec)
	$cols = @()
	foreach ($part in $spec -split ',') {
		$part = $part.Trim()
		if ($part -match '^(\d+)-(\d+)$') {
			$from = [int]$Matches[1]
			$to = [int]$Matches[2]
			for ($i = $from; $i -le $to; $i++) { $cols += $i }
		} else {
			$cols += [int]$part
		}
	}
	return $cols
}

# --- 4a. Auto-calculate defaultWidth from page format ---

$pageTargets = @{
	"A4-landscape" = 780
	"A4-portrait"  = 540
}

if ($def.page) {
	$pageName = "$($def.page)"
	$targetWidth = $null

	if ($pageName -match '^\d+$') {
		$targetWidth = [int]$pageName
	} elseif ($pageTargets.ContainsKey($pageName)) {
		$targetWidth = $pageTargets[$pageName]
	} else {
		Write-Warning "Unknown page format '$pageName'. Known: $($pageTargets.Keys -join ', '), or a number."
	}

	if ($targetWidth) {
		$totalUnits = 0.0
		$absoluteSum = 0
		$specifiedCols = @{}

		if ($def.columnWidths) {
			foreach ($prop in $def.columnWidths.PSObject.Properties) {
				$val = "$($prop.Value)"
				$cols = Parse-ColumnSpec $prop.Name
				foreach ($c in $cols) {
					$specifiedCols[[int]$c] = $true
					if ($val -match '^([0-9.]+)x$') {
						$totalUnits += [double]$Matches[1]
					} else {
						$absoluteSum += [int]$val
					}
				}
			}
		}

		for ($c = 1; $c -le $totalColumns; $c++) {
			if (-not $specifiedCols.ContainsKey($c)) {
				$totalUnits += 1.0
			}
		}

		if ($totalUnits -gt 0) {
			$defaultWidth = [int][math]::Round(($targetWidth - $absoluteSum) / $totalUnits)
		}
	}
}

# Build column width map: 1-based col -> width
$colWidthMap = @{}
if ($def.columnWidths) {
	foreach ($prop in $def.columnWidths.PSObject.Properties) {
		$val = "$($prop.Value)"
		if ($val -match '^([0-9.]+)x$') {
			$width = [int][math]::Round([double]$Matches[1] * $defaultWidth)
		} else {
			$width = [int]$val
		}
		$columns = Parse-ColumnSpec $prop.Name
		foreach ($c in $columns) {
			$colWidthMap[$c] = $width
		}
	}
}

# Набор колонок - своя раскладка ширин для части строк. Ширины разбираются тем же
# правилом, что и основные, а идентификатор берется из описания или выводится из имени.
$columnSets = [ordered]@{}
if ($def.columnSets) {
	foreach ($prop in $def.columnSets.PSObject.Properties) {
		$setDef = $prop.Value
		$setWidths = @{}
		if ($setDef.columnWidths) {
			foreach ($wp in $setDef.columnWidths.PSObject.Properties) {
				$val = "$($wp.Value)"
				if ($val -match '^([0-9.]+)x$') {
					$width = [int][math]::Round([double]$Matches[1] * $defaultWidth)
				} else {
					$width = [int]$val
				}
				foreach ($c in (Parse-ColumnSpec $wp.Name)) { $setWidths[$c] = $width }
			}
		}
		$columnSets[$prop.Name] = @{
			Id       = if ($setDef.id) { "$($setDef.id)" } else { Get-NameUuid $prop.Name }
			Columns  = if ($setDef.columns) { [int]$setDef.columns } else { $totalColumns }
			WidthMap = $setWidths
		}
	}
}

# Ссылка на набор допустима только именем: объект на месте имени - ошибка описания.
function Resolve-ColumnSetName {
	param($value, [string]$areaName)
	if ($null -eq $value) { return $null }
	if ($value -isnot [string]) {
		[Console]::Error.WriteLine("'columnSet' must be a name declared in columnSets, got an object: area `"$areaName`"")
		exit 1
	}
	if (-not $columnSets.Contains($value)) {
		[Console]::Error.WriteLine("'columnSet' is not declared in columnSets: `"$value`", area `"$areaName`"")
		exit 1
	}
	return $value
}

# --- 5. Style resolver ---

function Resolve-Style {
	param([string]$styleName, [string]$fillType)

	$fontIdx = if ($fontMap.Contains("default")) { $fontMap["default"] } else { -1 }
	$lb = -1; $tb = -1; $rb = -1; $bb = -1
	$ha = ""; $va = ""; $nf = ""
	$textColor = ""
	$wrap = $false

	if ($styleName -and $def.styles) {
		$style = $def.styles.$styleName
		if ($style) {
			# Font
			if ($style.font -and $fontMap.Contains($style.font)) {
				$fontIdx = $fontMap[$style.font]
			}

			# Borders
			if ($style.border -and $style.border -ne "none") {
				$lineIdx = if ($style.borderWidth -eq "thick") { $thickLineIndex } else { $thinLineIndex }
				foreach ($side in ($style.border -split ',')) {
					switch ($side.Trim()) {
						"all"    { $lb = $lineIdx; $tb = $lineIdx; $rb = $lineIdx; $bb = $lineIdx }
						"left"   { $lb = $lineIdx }
						"top"    { $tb = $lineIdx }
						"right"  { $rb = $lineIdx }
						"bottom" { $bb = $lineIdx }
					}
				}
			}

			# Выравнивание задается коротким ключом или полным именем свойства платформы.
			$alignValue = if ($style.align) { "$($style.align)" } elseif ($style.horizontalAlignment) { "$($style.horizontalAlignment)" } else { "" }
			if ($alignValue) {
				switch ($alignValue.ToLower()) {
					"left"   { $ha = "Left" }
					"center" { $ha = "Center" }
					"right"  { $ha = "Right" }
					"justify" { $ha = "Justify" }
				}
			}
			$valignValue = if ($style.valign) { "$($style.valign)" } elseif ($style.verticalAlignment) { "$($style.verticalAlignment)" } else { "" }
			if ($valignValue) {
				switch ($valignValue.ToLower()) {
					"top"    { $va = "Top" }
					"center" { $va = "Center" }
					"bottom" { $va = "Bottom" }
				}
			}

			# Wrap
			if ($style.wrap -eq $true) { $wrap = $true }

			# Number format
			if ($style.format) { $nf = $style.format }

			# Цвет текста задается ссылкой на элемент стиля платформы.
			if ($style.textColor) { $textColor = "$($style.textColor)" }
		}
	}

	return @{
		FontIdx      = $fontIdx
		LB           = $lb; TB = $tb; RB = $rb; BB = $bb
		HA           = $ha; VA = $va
		Wrap         = $wrap
		FillType     = $fillType
		NumberFormat = $nf
		TextColor    = $textColor
	}
}

# --- 6. Format palette builder ---

$formatRegistry = [ordered]@{}  # key -> hashtable with properties
$formatOrder = @()              # ordered keys for index assignment

function Get-FormatKey {
	param(
		[int]$fontIdx = -1,
		[int]$lb = -1, [int]$tb = -1, [int]$rb = -1, [int]$bb = -1,
		[string]$ha = "", [string]$va = "",
		[bool]$wrap = $false,
		[string]$fillType = "",
		[string]$numberFormat = "",
		[int]$width = -1,
		[int]$height = -1,
		[string]$textColor = "",
		[bool]$hidden = $false
	)
	return "f=$fontIdx|lb=$lb|tb=$tb|rb=$rb|bb=$bb|ha=$ha|va=$va|wr=$wrap|ft=$fillType|nf=$numberFormat|w=$width|h=$height|tc=$textColor|hd=$hidden"
}

function Register-Format {
	param([string]$key, [hashtable]$props)
	if (-not $script:formatRegistry.Contains($key)) {
		$script:formatRegistry[$key] = $props
		$script:formatOrder += $key
	}
	# Return 1-based index
	$idx = 0
	foreach ($k in $script:formatRegistry.Keys) {
		$idx++
		if ($k -eq $key) { return $idx }
	}
	return $idx
}

# 6b. Column width formats
$colFormatMap = @{}  # 1-based col -> format index
foreach ($col in ($colWidthMap.Keys | Sort-Object)) {
	$w = $colWidthMap[$col]
	$key = Get-FormatKey -width $w
	$idx = Register-Format -key $key -props @{ Width = $w }
	$colFormatMap[[int]$col] = $idx
}

# 6b-1. Форматы ширин наборов колонок
$setFormatMaps = @{}
foreach ($setName in $columnSets.Keys) {
	$map = @{}
	$widths = $columnSets[$setName].WidthMap
	foreach ($col in ($widths.Keys | Sort-Object)) {
		$w = $widths[$col]
		$map[[int]$col] = Register-Format -key (Get-FormatKey -width $w) -props @{ Width = $w }
	}
	$setFormatMaps[$setName] = $map
}

# 6c. Scan areas for row heights and cell formats
# We need to do two passes: first collect all formats, then generate XML

# Helper: escape XML special characters
function Esc-Xml {
	param([string]$s)
	return $s.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

# Helper: determine fillType from cell content
# Текст ячейки задается строкой - тогда он идет на все языки вывода - или объектом
# вида "язык: текст", тогда на каждый язык идет свой.
function Get-TextItems {
	param($value)
	$items = @()
	if ($value -is [string]) {
		foreach ($lang in $textLanguages) { $items += @{ Lang = $lang; Content = $value } }
		return ,$items
	}
	foreach ($p in $value.PSObject.Properties) { $items += @{ Lang = $p.Name; Content = "$($p.Value)" } }
	return ,$items
}

function Get-FillType {
	param($cell)
	if ($cell.param) { return "Parameter" }
	if ($cell.template) { return "Template" }
	return ""
}

# Helper: register a cell format and return its index
function Register-CellFormat {
	param($styleName, [string]$fillType)
	$resolved = Resolve-Style -styleName $styleName -fillType $fillType
	$key = Get-FormatKey -fontIdx $resolved.FontIdx `
		-lb $resolved.LB -tb $resolved.TB -rb $resolved.RB -bb $resolved.BB `
		-ha $resolved.HA -va $resolved.VA `
		-wrap $resolved.Wrap -fillType $resolved.FillType `
		-numberFormat $resolved.NumberFormat -textColor $resolved.TextColor
	if ($key -eq (Get-FormatKey -fontIdx -1)) { return 0 }
	$props = @{
		FontIdx      = $resolved.FontIdx
		LB           = $resolved.LB; TB = $resolved.TB
		RB           = $resolved.RB; BB = $resolved.BB
		HA           = $resolved.HA; VA = $resolved.VA
		Wrap         = $resolved.Wrap
		FillType     = $resolved.FillType
		NumberFormat = $resolved.NumberFormat
		TextColor    = $resolved.TextColor
	}
	return Register-Format -key $key -props $props
}

# Формат строки собирается из высоты, скрытия и собственного стиля строки: платформа
# держит их одним форматом.
function Get-RowFormat {
	param($row)
	$rowHeight = if ($row.height) { [int]$row.height } else { -1 }
	$rowHidden = ($row.hidden -eq $true)
	$props = @{ Hidden = $rowHidden }
	if ($rowHeight -ge 0) { $props["Height"] = $rowHeight }
	if (-not $row.style) {
		return @{ Key = (Get-FormatKey -height $rowHeight -hidden $rowHidden); Props = $props }
	}
	$r = Resolve-Style -styleName $row.style -fillType ""
	$props["FontIdx"] = $r.FontIdx
	$props["LB"] = $r.LB; $props["TB"] = $r.TB
	$props["RB"] = $r.RB; $props["BB"] = $r.BB
	$props["HA"] = $r.HA; $props["VA"] = $r.VA
	$props["Wrap"] = $r.Wrap
	$props["NumberFormat"] = $r.NumberFormat
	$props["TextColor"] = $r.TextColor
	$key = Get-FormatKey -fontIdx $r.FontIdx -lb $r.LB -tb $r.TB -rb $r.RB -bb $r.BB `
		-ha $r.HA -va $r.VA -wrap $r.Wrap -numberFormat $r.NumberFormat `
		-textColor $r.TextColor -height $rowHeight -hidden $rowHidden
	return @{ Key = $key; Props = $props }
}

# Pre-register all formats from areas
foreach ($area in $sheetAreas) {
	foreach ($row in $area.rows) {
		# Skip empty row placeholder
		if ($row.empty) { continue }

		# Row height format
		if ($row.height -or $row.hidden -eq $true -or $row.style) {
			$rf = Get-RowFormat $row
			Register-Format -key $rf.Key -props $rf.Props | Out-Null
		}

		# rowStyle gap-fill format (no content → no fillType)
		if ($row.rowStyle) {
			Register-CellFormat -styleName $row.rowStyle -fillType "" | Out-Null
		}

		# Explicit cell formats
		if ($row.cells) {
			foreach ($cell in $row.cells) {
				$cellStyle = if ($cell.style) { $cell.style } elseif ($row.rowStyle) { $row.rowStyle } else { "default" }
				$ft = Get-FillType $cell
				Register-CellFormat -styleName $cellStyle -fillType $ft | Out-Null
			}
		}
	}
}

# --- 7. Generate XML ---

$xml = New-Object System.Text.StringBuilder 4096

# Версии формата сравниваются по составным частям, а не как десятичная дробь:
# 2.9 старее, чем 2.21, хотя как число больше.
function Get-FormatVersionRank {
	param([string]$Version)
	if ($Version -match '^(\d+)\.(\d+)$') { return [int]$Matches[1] * 100 + [int]$Matches[2] }
	return 0
}

function X {
	param([string]$text)
	$script:xml.AppendLine($text) | Out-Null
}

# Ширина по умолчанию идет последним форматом палитры: платформа пишет ее после всех прочих.
$defaultFormatKey = Get-FormatKey -width $defaultWidth
$defaultFormatIndex = Register-Format -key $defaultFormatKey -props @{ Width = $defaultWidth }

# 7a. Header
X '<?xml version="1.0" encoding="UTF-8"?>'
# Палитра появляется в шапке макета с формата 2.21 (8.5) и встает после основного
# пространства имен.
$mxlTemplateVersion = Get-TemplateFormatVersion $OutputPath
$mxlPal = if ((Get-FormatVersionRank $mxlTemplateVersion) -ge 221) { ' xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"' } else { '' }
X "<document xmlns=`"http://v8.1c.ru/8.2/data/spreadsheet`"$mxlPal xmlns:style=`"http://v8.1c.ru/8.1/data/ui/style`" xmlns:v8=`"http://v8.1c.ru/8.1/data/core`" xmlns:v8ui=`"http://v8.1c.ru/8.1/data/ui`" xmlns:xs=`"http://www.w3.org/2001/XMLSchema`" xmlns:xsi=`"http://www.w3.org/2001/XMLSchema-instance`">"

# 7b. Language settings
# Состав языков берется из описания: у макета их бывает несколько, и порядок значим.
$languageList = @()
if ($def.languages) {
	foreach ($lang in @($def.languages)) {
		if ($lang -is [string]) {
			$languageList += @{ id = "$lang"; code = "$lang"; description = "$lang" }
		} else {
			$languageList += @{
				id = "$($lang.id)"
				code = if ($lang.code) { "$($lang.code)" } else { "$($lang.id)" }
				description = if ($lang.description) { "$($lang.description)" } else { "$($lang.id)" }
			}
		}
	}
}
if ($languageList.Count -eq 0) {
	$languageList = @(@{ id = "ru"; code = "Русский"; description = "Русский" })
}
$currentLanguage = if ($def.currentLanguage) { "$($def.currentLanguage)" } else { $languageList[0].id }
$defaultLanguage = if ($def.defaultLanguage) { "$($def.defaultLanguage)" } else { $languageList[0].id }

X "`t<languageSettings>"
X "`t`t<currentLanguage>$currentLanguage</currentLanguage>"
X "`t`t<defaultLanguage>$defaultLanguage</defaultLanguage>"
foreach ($lang in $languageList) {
	X "`t`t<languageInfo>"
	X "`t`t`t<id>$(Esc-Xml $lang.id)</id>"
	X "`t`t`t<code>$(Esc-Xml $lang.code)</code>"
	X "`t`t`t<description>$(Esc-Xml $lang.description)</description>"
	X "`t`t</languageInfo>"
}
X "`t</languageSettings>"

# 7c. Columns
X "`t<columns>"
X "`t`t<size>$totalColumns</size>"

# Emit columnsItem for columns with non-default widths
foreach ($col in ($colFormatMap.Keys | Sort-Object)) {
	$fmtIdx = $colFormatMap[$col]
	$colIdx = $col - 1  # Convert to 0-based
	X "`t`t<columnsItem>"
	X "`t`t`t<index>$colIdx</index>"
	X "`t`t`t<column>"
	X "`t`t`t`t<formatIndex>$fmtIdx</formatIndex>"
	X "`t`t`t</column>"
	X "`t`t</columnsItem>"
}

X "`t</columns>"

# Раскладки наборов идут отдельными блоками колонок, отличаясь идентификатором.
foreach ($setName in $columnSets.Keys) {
	$set = $columnSets[$setName]
	X "`t<columns>"
	X "`t`t<id>$($set.Id)</id>"
	X "`t`t<size>$($set.Columns)</size>"
	$map = $setFormatMaps[$setName]
	foreach ($col in ($map.Keys | Sort-Object)) {
		X "`t`t<columnsItem>"
		X "`t`t`t<index>$($col - 1)</index>"
		X "`t`t`t<column>"
		X "`t`t`t`t<formatIndex>$($map[$col])</formatIndex>"
		X "`t`t`t</column>"
		X "`t`t</columnsItem>"
	}
	X "`t</columns>"
}

# 7d. Rows — main generation loop
$globalRow = 0
$merges = @()
$namedItems = @()
$totalRowCount = 0

foreach ($area in $sheetAreas) {
	$areaStartRow = $globalRow
	$areaName = $area.name
	$areaColumnSet = Resolve-ColumnSetName $area.columnSet $areaName
	$activeRowspans = @()  # @{ColStart=1-based; ColEnd=1-based; EndLocalRow=int}
	$localRow = 0

	foreach ($row in $area.rows) {
		$rowColumnSet = if ($null -ne $row.columnSet) { Resolve-ColumnSetName $row.columnSet $areaName } else { $areaColumnSet }
		# Ширина строки берется из выбранного набора колонок: у набора она своя, и
		# проверять колонки строки по раскладке документа нельзя.
		$rowColumns = if ($rowColumnSet) { [int]$columnSets[$rowColumnSet].Columns } else { $totalColumns }

		# Empty row placeholder: emit N empty rows
		if ($row.empty) {
			$count = [int]$row.empty
			for ($ei = 0; $ei -lt $count; $ei++) {
				X "`t<rowsItem>"
				X "`t`t<index>$globalRow</index>"
				X "`t`t<row>"
				if ($rowColumnSet) { X "`t`t`t<columnsID>$($columnSets[$rowColumnSet].Id)</columnsID>" }
				X "`t`t`t<empty>true</empty>"
				X "`t`t</row>"
				X "`t</rowsItem>"
				$globalRow++; $localRow++
			}
			continue
		}

		# Build set of columns occupied by rowspans from previous rows
		$rowspanOccupied = @{}  # 1-based col -> $true
		foreach ($rs in $activeRowspans) {
			if ($localRow -gt $rs.StartLocalRow -and $localRow -le $rs.EndLocalRow) {
				for ($c = $rs.ColStart; $c -le $rs.ColEnd; $c++) {
					$rowspanOccupied[$c] = $true
				}
			}
		}

		$rowHasContent = $false
		$rowCells = @()  # array of { Col(0-based), FormatIdx, Content }

		# Determine row height format
		$rowFormatIdx = 0
		if ($row.height -or $row.hidden -eq $true -or $row.style) {
			$hKey = (Get-RowFormat $row).Key
			# Find format index for this key
			$rIdx = 0
			foreach ($k in $formatRegistry.Keys) {
				$rIdx++
				if ($k -eq $hKey) { $rowFormatIdx = $rIdx; break }
			}
		}

		if ($row.cells -and $row.cells.Count -gt 0) {
			$rowHasContent = $true

			# Явные номера колонок проверяются до раскладки: дальше по коду они уже приводятся
			# к числу, и отличить "0" от отсутствующего значения будет нельзя.
			$cellNo = 0
			$withCol = 0
			foreach ($cell in $row.cells) {
				$cellNo++
				if ($null -eq $cell.col -or "$($cell.col)" -eq "") { continue }
				$withCol++
				$colNum = 0
				if (-not [int]::TryParse("$($cell.col)", [ref]$colNum) -or $colNum -lt 1 -or $colNum -gt $rowColumns) {
					[Console]::Error.WriteLine("Invalid 'col' value `"$($cell.col)`": area `"$areaName`", row $($localRow + 1), cell $cellNo")
					exit 1
				}
			}
			if ($withCol -gt 0 -and $withCol -lt $row.cells.Count) {
				[Console]::Error.WriteLine("Cell without 'col' mixed with positioned cells: area `"$areaName`", row $($localRow + 1)")
				exit 1
			}

			# Ячейка без col занимает ближайшую свободную колонку слева направо. Раньше такой
			# ячейке доставался номер 0 (пустое свойство приводилось к нулю), и в файл уходил
			# индекс -1 сразу для всех - колонки не различались.
			$claimed = @{}
			foreach ($rsk in $rowspanOccupied.Keys) { $claimed[$rsk] = $true }
			foreach ($cell in $row.cells) {
				if ($cell.col) {
					$cs = [int]$cell.col
					$sp = if ($cell.span) { [int]$cell.span } else { 1 }
					for ($c = $cs; $c -lt ($cs + $sp); $c++) { $claimed[$c] = $true }
				}
			}
			$cursor = 1
			foreach ($cell in $row.cells) {
				if ($cell.col) { continue }
				$sp = if ($cell.span) { [int]$cell.span } else { 1 }
				# Свободным должен быть ВЕСЬ диапазон объединения: иначе ячейка с span
				# начиналась в свободной колонке и накрывала занятую соседнюю.
				while (@($cursor..($cursor + $sp - 1)) | Where-Object { $claimed[$_] }) { $cursor++ }
				if (($cursor + $sp - 1) -gt $rowColumns) {
					[Console]::Error.WriteLine("Row exceeds 'columns' ($rowColumns): area `"$areaName`", row $($localRow + 1)")
					exit 1
				}
				$cell | Add-Member -NotePropertyName col -NotePropertyValue $cursor -Force
				for ($c = $cursor; $c -lt ($cursor + $sp); $c++) { $claimed[$c] = $true }
				$cursor += $sp
			}

			# Build set of occupied columns (1-based): explicit cells + rowspan from above
			$occupiedCols = @{}
			foreach ($rsk in $rowspanOccupied.Keys) { $occupiedCols[$rsk] = $true }
			foreach ($cell in $row.cells) {
				$colStart = [int]$cell.col
				$colSpan = if ($cell.span) { [int]$cell.span } else { 1 }
				for ($c = $colStart; $c -lt ($colStart + $colSpan); $c++) {
					$occupiedCols[$c] = $true
				}
			}

			# Generate explicit cells
			foreach ($cell in $row.cells) {
				$colStart = [int]$cell.col
				$colSpan = if ($cell.span) { [int]$cell.span } else { 1 }
				$rowspan = if ($cell.rowspan) { [int]$cell.rowspan } else { 1 }
				$cellStyle = if ($cell.style) { $cell.style } elseif ($row.rowStyle) { $row.rowStyle } else { "default" }
				$ft = Get-FillType $cell
				$fmtIdx = Register-CellFormat -styleName $cellStyle -fillType $ft

				$cellInfo = @{
					Col       = $colStart - 1  # 0-based
					FormatIdx = $fmtIdx
					Param     = $cell.param
					Detail    = $cell.detail
					Text      = $cell.text
					Template  = $cell.template
				}
				$rowCells += $cellInfo

				# Track rowspan for subsequent rows
				if ($rowspan -gt 1) {
					$activeRowspans += @{
						ColStart      = $colStart
						ColEnd        = $colStart + $colSpan - 1
						StartLocalRow = $localRow
						EndLocalRow   = $localRow + $rowspan - 1
					}
				}

				# Collect merge (horizontal, vertical, or both)
				if ($colSpan -gt 1 -or $rowspan -gt 1) {
					$merge = @{ R = $globalRow; C = $colStart - 1; W = $colSpan - 1 }
					if ($rowspan -gt 1) { $merge.H = $rowspan - 1 }
					$merges += $merge
				}
			}

			# Generate gap-fill cells for rowStyle
			if ($row.rowStyle) {
				$gapFmtIdx = Register-CellFormat -styleName $row.rowStyle -fillType ""
				for ($c = 1; $c -le $rowColumns; $c++) {
					if (-not $occupiedCols.ContainsKey($c)) {
						$rowCells += @{
							Col       = $c - 1  # 0-based
							FormatIdx = $gapFmtIdx
							Param     = $null
							Detail    = $null
							Text      = $null
							Template  = $null
						}
					}
				}
			}

			# Sort cells by column
			$rowCells = $rowCells | Sort-Object { $_.Col }

		} elseif ($row.rowStyle) {
			# Row with only rowStyle, no explicit cells — fill non-rowspan columns
			$rowHasContent = $true
			$gapFmtIdx = Register-CellFormat -styleName $row.rowStyle -fillType ""
			for ($c = 1; $c -le $rowColumns; $c++) {
				if ($rowspanOccupied.ContainsKey($c)) { continue }
				$rowCells += @{
					Col       = $c - 1
					FormatIdx = $gapFmtIdx
					Param     = $null
					Detail    = $null
					Text      = $null
					Template  = $null
				}
			}
		}

		# Emit rowsItem
		X "`t<rowsItem>"
		X "`t`t<index>$globalRow</index>"
		X "`t`t<row>"

		if ($rowColumnSet) { X "`t`t`t<columnsID>$($columnSets[$rowColumnSet].Id)</columnsID>" }

		if ($rowFormatIdx -gt 0) {
			X "`t`t`t<formatIndex>$rowFormatIdx</formatIndex>"
		}

		if (-not $rowHasContent) {
			X "`t`t`t<empty>true</empty>"
		} else {
			# Индекс колонки платформа пишет только при разрыве: ячейки, идущие подряд от
			# начала строки, нумеруются по порядку следования.
			$expectedCol = 0
			foreach ($cellInfo in $rowCells) {
				X "`t`t`t<c>"
				if ($cellInfo.Col -ne $expectedCol) {
					X "`t`t`t`t<i>$($cellInfo.Col)</i>"
				}
				$expectedCol = [int]$cellInfo.Col + 1
				X "`t`t`t`t<c>"
				X "`t`t`t`t`t<f>$($cellInfo.FormatIdx)</f>"

				if ($cellInfo.Param) {
					X "`t`t`t`t`t<parameter>$($cellInfo.Param)</parameter>"
					if ($cellInfo.Detail) {
						X "`t`t`t`t`t<detailParameter>$($cellInfo.Detail)</detailParameter>"
					}
				}

				if ($cellInfo.Text) {
					X "`t`t`t`t`t<tl>"
					foreach ($ti in (Get-TextItems $cellInfo.Text)) {
						X "`t`t`t`t`t`t<v8:item>"
						X "`t`t`t`t`t`t`t<v8:lang>$($ti.Lang)</v8:lang>"
						X "`t`t`t`t`t`t`t<v8:content>$(Esc-Xml $ti.Content)</v8:content>"
						X "`t`t`t`t`t`t</v8:item>"
					}
					X "`t`t`t`t`t</tl>"
				}

				if ($cellInfo.Template) {
					X "`t`t`t`t`t<tl>"
					foreach ($ti in (Get-TextItems $cellInfo.Template)) {
						X "`t`t`t`t`t`t<v8:item>"
						X "`t`t`t`t`t`t`t<v8:lang>$($ti.Lang)</v8:lang>"
						X "`t`t`t`t`t`t`t<v8:content>$(Esc-Xml $ti.Content)</v8:content>"
						X "`t`t`t`t`t`t</v8:item>"
					}
					X "`t`t`t`t`t</tl>"
				}

				X "`t`t`t`t</c>"
				X "`t`t`t</c>"
			}
		}

		X "`t`t</row>"
		X "`t</rowsItem>"

		$localRow++
		$globalRow++
	}

	$areaEndRow = $globalRow - 1
	# Безымянная область - это строки самого документа: именованной области у них нет.
	if ($areaName) {
		$namedItems += @{
			Name        = $areaName
			Type        = "Rows"
			BeginRow    = $areaStartRow
			EndRow      = $areaEndRow
			BeginColumn = -1
			EndColumn   = -1
		}
	}
}

# Именованная область задается и координатами: вид выводится из того, какие оси заданы.
$naIndex = 0
foreach ($na in @($def.namedAreas | Where-Object { $null -ne $_ })) {
	$naIndex++
	$naName = "$($na.name)"
	$hasRows = $null -ne $na.rows -and "$($na.rows)" -ne ""
	$hasCols = $null -ne $na.cols -and "$($na.cols)" -ne ""
	if (-not $hasRows -and -not $hasCols) {
		[Console]::Error.WriteLine("namedAreas: at least one of 'rows'/'cols' is required: namedAreas[$naIndex] `"$naName`"")
		exit 1
	}
	$rowRange = if ($hasRows) { Get-NamedAreaRange -value $na.rows -axis "rows" -index $naIndex -name $naName } else { $null }
	$colRange = if ($hasCols) { Get-NamedAreaRange -value $na.cols -axis "cols" -index $naIndex -name $naName } else { $null }
	$naType = if ($rowRange -and $colRange) { "Rectangle" } elseif ($rowRange) { "Rows" } else { "Columns" }
	$namedItems += @{
		Name        = $naName
		Type        = $naType
		BeginRow    = if ($rowRange) { $rowRange.Begin - 1 } else { -1 }
		EndRow      = if ($rowRange) { $rowRange.End - 1 } else { -1 }
		BeginColumn = if ($colRange) { $colRange.Begin - 1 } else { -1 }
		EndColumn   = if ($colRange) { $colRange.End - 1 } else { -1 }
	}
}

$totalRowCount = $globalRow

# 7e. Scalar metadata
X "`t<templateMode>true</templateMode>"
X "`t<defaultFormatIndex>$defaultFormatIndex</defaultFormatIndex>"
X "`t<height>$totalRowCount</height>"
X "`t<vgRows>$totalRowCount</vgRows>"

# 7f. Merges
foreach ($m in $merges) {
	X "`t<merge>"
	X "`t`t<r>$($m.R)</r>"
	X "`t`t<c>$($m.C)</c>"
	if ($m.H) { X "`t`t<h>$($m.H)</h>" }
	X "`t`t<w>$($m.W)</w>"
	X "`t</merge>"
}

# 7g. Named items
foreach ($ni in $namedItems) {
	X "`t<namedItem xsi:type=`"NamedItemCells`">"
	X "`t`t<name>$(Esc-Xml $ni.Name)</name>"
	X "`t`t<area>"
	X "`t`t`t<type>$($ni.Type)</type>"
	X "`t`t`t<beginRow>$($ni.BeginRow)</beginRow>"
	X "`t`t`t<endRow>$($ni.EndRow)</endRow>"
	X "`t`t`t<beginColumn>$($ni.BeginColumn)</beginColumn>"
	X "`t`t`t<endColumn>$($ni.EndColumn)</endColumn>"
	X "`t`t</area>"
	X "`t</namedItem>"
}

# 7h. Line palette
if ($hasThinBorders) {
	X "`t<line width=`"1`" gap=`"false`">"
	X "`t`t<v8ui:style xsi:type=`"v8ui:SpreadsheetDocumentCellLineType`">Solid</v8ui:style>"
	X "`t</line>"
}
if ($hasThickBorders) {
	X "`t<line width=`"2`" gap=`"false`">"
	X "`t`t<v8ui:style xsi:type=`"v8ui:SpreadsheetDocumentCellLineType`">Solid</v8ui:style>"
	X "`t</line>"
}

# 7i. Font palette
foreach ($fe in $fontEntries) {
	if ($fe.Ref) {
		# Объявление пространства имен идет первым атрибутом - так пишет платформа.
		$nsAttr = ""
		if ($fe.Namespace) {
			foreach ($np in $fe.Namespace.PSObject.Properties) {
				$nsAttr += " xmlns:$($np.Name)=`"$(Esc-Xml "$($np.Value)")`""
			}
		}
		X "`t<font$nsAttr ref=`"$(Esc-Xml $fe.Ref)`" kind=`"$($fe.Kind)`"/>"
		continue
	}
	X "`t<font faceName=`"$($fe.Face)`" height=`"$($fe.Size)`" bold=`"$($fe.Bold)`" italic=`"$($fe.Italic)`" underline=`"$($fe.Underline)`" strikeout=`"$($fe.Strikeout)`" kind=`"Absolute`" scale=`"100`"/>"
}

# 7j. Format palette
foreach ($key in $formatRegistry.Keys) {
	$fmt = $formatRegistry[$key]
	X "`t<format>"

	if ($fmt.Hidden -eq $true) {
		X "`t`t<hidden>true</hidden>"
	}
	if ($fmt.FontIdx -ne $null -and $fmt.FontIdx -ge 0) {
		X "`t`t<font>$($fmt.FontIdx)</font>"
	}
	if ($fmt.TextColor) {
		X "`t`t<textColor>$(Esc-Xml $fmt.TextColor)</textColor>"
	}
	# Рамка со всех сторон одной линией пишется одним тегом - так делает платформа.
	$sameBorder = ($fmt.LB -ne $null -and $fmt.LB -ge 0 -and
		$fmt.LB -eq $fmt.TB -and $fmt.LB -eq $fmt.RB -and $fmt.LB -eq $fmt.BB)
	if ($sameBorder) {
		X "`t`t<border>$($fmt.LB)</border>"
	}
	if (-not $sameBorder -and $fmt.LB -ne $null -and $fmt.LB -ge 0) {
		X "`t`t<leftBorder>$($fmt.LB)</leftBorder>"
	}
	if (-not $sameBorder -and $fmt.TB -ne $null -and $fmt.TB -ge 0) {
		X "`t`t<topBorder>$($fmt.TB)</topBorder>"
	}
	if (-not $sameBorder -and $fmt.RB -ne $null -and $fmt.RB -ge 0) {
		X "`t`t<rightBorder>$($fmt.RB)</rightBorder>"
	}
	if (-not $sameBorder -and $fmt.BB -ne $null -and $fmt.BB -ge 0) {
		X "`t`t<bottomBorder>$($fmt.BB)</bottomBorder>"
	}
	if ($fmt.Width) {
		X "`t`t<width>$($fmt.Width)</width>"
	}
	if ($fmt.Height) {
		X "`t`t<height>$($fmt.Height)</height>"
	}
	if ($fmt.HA) {
		X "`t`t<horizontalAlignment>$($fmt.HA)</horizontalAlignment>"
	}
	if ($fmt.VA) {
		X "`t`t<verticalAlignment>$($fmt.VA)</verticalAlignment>"
	}
	if ($fmt.Wrap -eq $true) {
		X "`t`t<textPlacement>Wrap</textPlacement>"
	}
	if ($fmt.FillType) {
		X "`t`t<fillType>$($fmt.FillType)</fillType>"
	}
	if ($fmt.NumberFormat) {
		X "`t`t<format>"
		X "`t`t`t<v8:item>"
		X "`t`t`t`t<v8:lang>ru</v8:lang>"
		X "`t`t`t`t<v8:content>$(Esc-Xml $fmt.NumberFormat)</v8:content>"
		X "`t`t`t</v8:item>"
		X "`t`t</format>"
	}

	X "`t</format>"
}

# 7k. Close document
X '</document>'

# --- 8. Write output ---

$enc = New-Object System.Text.UTF8Encoding($true)
$resolvedPath = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path (Get-Location) $OutputPath }
Assert-EditAllowed $resolvedPath "editable"
# Платформа не оставляет перевод строки после закрывающего тега - лишний перевод
# дает расхождение в первой же сверке с выгрузкой Конфигуратора.
$outDir = [System.IO.Path]::GetDirectoryName($resolvedPath)
if ($outDir -and -not (Test-Path $outDir)) {
	New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
[System.IO.File]::WriteAllText($resolvedPath, $xml.ToString().TrimEnd("`r", "`n"), $enc)

# --- 9. Summary ---

Write-Host "[OK] Compiled: $OutputPath"
if ($def.page) {
	Write-Host "     Page: $pageName -> target $targetWidth, defaultWidth=$defaultWidth"
}
Write-Host "     Areas: $($namedItems.Count), Rows: $totalRowCount, Columns: $totalColumns"
Write-Host "     Fonts: $($fontEntries.Count), Lines: $lineCount, Formats: $($formatRegistry.Count)"
Write-Host "     Merges: $($merges.Count)"
