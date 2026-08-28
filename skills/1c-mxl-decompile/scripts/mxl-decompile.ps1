# mxl-decompile v1.0 - Decompile 1C spreadsheet to JSON
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$TemplatePath,

	[string]$OutputPath
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- 1. Load and parse XML ---

if (-not (Test-Path $TemplatePath)) {
	Write-Error "File not found: $TemplatePath"
	exit 1
}

$xmlDoc = New-Object System.Xml.XmlDocument
$xmlDoc.PreserveWhitespace = $false
$xmlDoc.Load((Resolve-Path $TemplatePath).Path)

$root = $xmlDoc.DocumentElement
$ns = New-Object System.Xml.XmlNamespaceManager($xmlDoc.NameTable)
$ns.AddNamespace("d", "http://v8.1c.ru/8.2/data/spreadsheet")
$ns.AddNamespace("v8", "http://v8.1c.ru/8.1/data/core")
$ns.AddNamespace("v8ui", "http://v8.1c.ru/8.1/data/ui")
$ns.AddNamespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

# --- 2. Extract font palette ---

$rawFonts = @()
foreach ($fNode in $root.SelectNodes("d:font", $ns)) {
	$fontNs = @{}
	foreach ($attr in $fNode.Attributes) {
		if ($attr.Prefix -eq "xmlns") { $fontNs[$attr.LocalName] = $attr.Value }
	}
	$rawFonts += @{
		# Шрифт задается либо своими свойствами, либо ссылкой на элемент стиля или
		# системный шрифт - тогда у него есть ref, kind и объявление префикса.
		Ref       = $fNode.GetAttribute("ref")
		Kind      = $fNode.GetAttribute("kind")
		Namespace = $fontNs
		Face      = $fNode.GetAttribute("faceName")
		# Размер шрифта бывает дробным: целое сохраняется целым, чтобы описание
		# не менялось на ровном месте.
		Size      = $(
			$raw = [double]("0" + $fNode.GetAttribute("height"))
			if ($raw -eq [math]::Truncate($raw)) { [int]$raw } else { $raw }
		)
		Bold      = $fNode.GetAttribute("bold") -eq "true"
		Italic    = $fNode.GetAttribute("italic") -eq "true"
		Underline = $fNode.GetAttribute("underline") -eq "true"
		Strikeout = $fNode.GetAttribute("strikeout") -eq "true"
	}
}

# --- 3. Extract line palette ---

$rawLines = @()
foreach ($lNode in $root.SelectNodes("d:line", $ns)) {
	$rawLines += @{ Width = [int]$lNode.GetAttribute("width") }
}

# --- 4. Extract format palette ---

$rawFormats = @()
foreach ($fmtNode in $root.SelectNodes("d:format", $ns)) {
	$fmt = @{
		FontIdx = -1
		LB = -1; TB = -1; RB = -1; BB = -1
		Width = 0; Height = 0
		HA = ""; VA = ""
		Wrap = $false; FillType = ""; DataFormat = ""
		TextColor = ""; Hidden = $false
	}

	$n = $fmtNode.SelectSingleNode("d:font", $ns)
	if ($n) { $fmt.FontIdx = [int]$n.InnerText }
	# Рамка со всех сторон одной линией записана одним тегом.
	$n = $fmtNode.SelectSingleNode("d:border", $ns)
	if ($n) {
		$all = [int]$n.InnerText
		$fmt.LB = $all; $fmt.TB = $all; $fmt.RB = $all; $fmt.BB = $all
	}
	$n = $fmtNode.SelectSingleNode("d:leftBorder", $ns)
	if ($n) { $fmt.LB = [int]$n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:topBorder", $ns)
	if ($n) { $fmt.TB = [int]$n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:rightBorder", $ns)
	if ($n) { $fmt.RB = [int]$n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:bottomBorder", $ns)
	if ($n) { $fmt.BB = [int]$n.InnerText }

	$n = $fmtNode.SelectSingleNode("d:textColor", $ns)
	if ($n) { $fmt.TextColor = $n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:hidden", $ns)
	if ($n -and $n.InnerText -eq "true") { $fmt.Hidden = $true }
	$n = $fmtNode.SelectSingleNode("d:width", $ns)
	if ($n) { $fmt.Width = [int]$n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:height", $ns)
	if ($n) { $fmt.Height = [int]$n.InnerText }

	$n = $fmtNode.SelectSingleNode("d:horizontalAlignment", $ns)
	if ($n) { $fmt.HA = $n.InnerText }
	$n = $fmtNode.SelectSingleNode("d:verticalAlignment", $ns)
	if ($n) { $fmt.VA = $n.InnerText }

	$n = $fmtNode.SelectSingleNode("d:textPlacement", $ns)
	if ($n -and $n.InnerText -eq "Wrap") { $fmt.Wrap = $true }

	$n = $fmtNode.SelectSingleNode("d:fillType", $ns)
	if ($n) { $fmt.FillType = $n.InnerText }

	$n = $fmtNode.SelectSingleNode("d:format/v8:item/v8:content", $ns)
	if ($n) { $fmt.DataFormat = $n.InnerText }

	$rawFormats += $fmt
}

function Get-Format {
	param([int]$idx)
	if ($idx -le 0 -or $idx -gt $rawFormats.Count) { return $null }
	return $rawFormats[$idx - 1]
}

$script:SetNamePrefix = 'nabor'

# --- 5. Extract columns and default width ---

$colNodes = @($root.SelectNodes("d:columns", $ns))
$colNode = $colNodes[0]
$totalColumns = [int]$colNode.SelectSingleNode("d:size", $ns).InnerText

$colFormatIndices = @{}
foreach ($ci in $colNode.SelectNodes("d:columnsItem", $ns)) {
	$colIdx = [int]$ci.SelectSingleNode("d:index", $ns).InnerText
	$fmtIdx = [int]$ci.SelectSingleNode("d:column/d:formatIndex", $ns).InnerText
	$colFormatIndices[$colIdx] = $fmtIdx
}

$defaultFmtIdx = 0
$n = $root.SelectSingleNode("d:defaultFormatIndex", $ns)
if ($n) { $defaultFmtIdx = [int]$n.InnerText }

$defaultWidth = 10
if ($defaultFmtIdx -gt 0) {
	$defFmt = Get-Format $defaultFmtIdx
	if ($defFmt -and $defFmt.Width -gt 0) { $defaultWidth = $defFmt.Width }
}

# Build column width map (1-based col → width), only non-default
$colWidthMap = [ordered]@{}
foreach ($col0 in ($colFormatIndices.Keys | Sort-Object)) {
	$fmt = Get-Format $colFormatIndices[$col0]
	if ($fmt -and $fmt.Width -gt 0 -and $fmt.Width -ne $defaultWidth) {
		$col1 = [string]($col0 + 1)
		$colWidthMap.Add($col1, $fmt.Width)
	}
}

# Блок колонок с идентификатором - это набор: своя раскладка ширин для части строк.
# Имя набора выводится из его порядка: в файле у набора есть идентификатор, но нет имени,
# а описанию имя нужно.
$columnSetsOut = [ordered]@{}
$setNameById = @{}
for ($si = 1; $si -lt $colNodes.Count; $si++) {
	$cn = $colNodes[$si]
	$idNode = $cn.SelectSingleNode("d:id", $ns)
	if (-not $idNode) { continue }
	$setId = $idNode.InnerText.Trim()
	$setName = "$($script:SetNamePrefix)$si"
	$entry = [ordered]@{ id = $setId; columns = [int]$cn.SelectSingleNode("d:size", $ns).InnerText }
	$setWidths = [ordered]@{}
	foreach ($ci in $cn.SelectNodes("d:columnsItem", $ns)) {
		$c0 = [int]$ci.SelectSingleNode("d:index", $ns).InnerText
		$fmt = Get-Format ([int]$ci.SelectSingleNode("d:column/d:formatIndex", $ns).InnerText)
		if ($fmt -and $fmt.Width -gt 0) { $setWidths["$($c0 + 1)"] = $fmt.Width }
	}
	if ($setWidths.Count -gt 0) { $entry["columnWidths"] = $setWidths }
	$columnSetsOut[$setName] = $entry
	$setNameById[$setId] = $setName
}

# --- 6. Extract merges ---

$mergeMap = @{}
foreach ($mNode in $root.SelectNodes("d:merge", $ns)) {
	$r = [int]$mNode.SelectSingleNode("d:r", $ns).InnerText
	$c = [int]$mNode.SelectSingleNode("d:c", $ns).InnerText
	$w = [int]$mNode.SelectSingleNode("d:w", $ns).InnerText
	$hNode = $mNode.SelectSingleNode("d:h", $ns)
	$h = if ($hNode) { [int]$hNode.InnerText } else { 0 }
	$mergeMap["$r,$c"] = @{ W = $w; H = $h }
}

# --- 7. Extract named items ---

$namedAreas = @()
$coordAreas = @()
foreach ($niNode in $root.SelectNodes("d:namedItem", $ns)) {
	$xsiType = $niNode.GetAttribute("type", "http://www.w3.org/2001/XMLSchema-instance")
	if ($xsiType -ne "NamedItemCells") { continue }

	$areaNode = $niNode.SelectSingleNode("d:area", $ns)
	$areaType = $areaNode.SelectSingleNode("d:type", $ns).InnerText
	$niName = $niNode.SelectSingleNode("d:name", $ns).InnerText
	$beginRow = [int]$areaNode.SelectSingleNode("d:beginRow", $ns).InnerText
	$endRow = [int]$areaNode.SelectSingleNode("d:endRow", $ns).InnerText
	$beginColNode = $areaNode.SelectSingleNode("d:beginColumn", $ns)
	$endColNode = $areaNode.SelectSingleNode("d:endColumn", $ns)
	$beginCol = if ($beginColNode) { [int]$beginColNode.InnerText } else { -1 }
	$endCol = if ($endColNode) { [int]$endColNode.InnerText } else { -1 }

	# Область строк без колоночных границ описывает содержимое; все прочие виды - это
	# координатные области, они сохраняются отдельным разделом описания.
	if ($areaType -eq "Rows" -and $beginCol -lt 0 -and $endCol -lt 0) {
		$namedAreas += @{
			Name     = $niName
			BeginRow = $beginRow
			EndRow   = $endRow
		}
		continue
	}

	$coordArea = [ordered]@{ name = $niName }
	if ($beginRow -ge 0) {
		$coordArea["rows"] = if ($beginRow -eq $endRow) { "$($beginRow + 1)" } else { "$($beginRow + 1)-$($endRow + 1)" }
	}
	if ($beginCol -ge 0) {
		$coordArea["cols"] = if ($beginCol -eq $endCol) { "$($beginCol + 1)" } else { "$($beginCol + 1)-$($endCol + 1)" }
	}
	$coordAreas += $coordArea
}

# --- 8. Extract rows ---

$rowData = @{}
# Языки, встреченные в тексте ячеек, в порядке первого появления.
$textLanguagesSeen = New-Object System.Collections.Generic.List[string]
foreach ($riNode in $root.SelectNodes("d:rowsItem", $ns)) {
	$rowIdx = [int]$riNode.SelectSingleNode("d:index", $ns).InnerText
	$rowNode = $riNode.SelectSingleNode("d:row", $ns)

	$indexTo = $rowIdx
	$itNode = $riNode.SelectSingleNode("d:indexTo", $ns)
	if ($itNode) { $indexTo = [int]$itNode.InnerText }

	$rowFmtIdx = 0
	$fmtNode = $rowNode.SelectSingleNode("d:formatIndex", $ns)
	if ($fmtNode) { $rowFmtIdx = [int]$fmtNode.InnerText }

	$rowSetName = $null
	$cidNode = $rowNode.SelectSingleNode("d:columnsID", $ns)
	if ($cidNode) { $rowSetName = $setNameById[$cidNode.InnerText.Trim()] }

	$isEmpty = $false
	$emptyNode = $rowNode.SelectSingleNode("d:empty", $ns)
	if ($emptyNode -and $emptyNode.InnerText -eq "true") { $isEmpty = $true }

	$cells = @()
	if (-not $isEmpty) {
		$col = -1
		foreach ($cGroup in $rowNode.SelectNodes("d:c", $ns)) {
			$iNode = $cGroup.SelectSingleNode("d:i", $ns)
			if ($iNode) { $col = [int]$iNode.InnerText }
			else { $col++ }

			$cContent = $cGroup.SelectSingleNode("d:c", $ns)
			if (-not $cContent) { continue }

			$cellFmtIdx = 0
			$fNode = $cContent.SelectSingleNode("d:f", $ns)
			if ($fNode) { $cellFmtIdx = [int]$fNode.InnerText }

			$param = $null
			$pNode = $cContent.SelectSingleNode("d:parameter", $ns)
			if ($pNode) { $param = $pNode.InnerText }

			$detail = $null
			$dNode = $cContent.SelectSingleNode("d:detailParameter", $ns)
			if ($dNode) { $detail = $dNode.InnerText }

			# Текст хранится по языкам: одноязычный вариант вернется строкой, разноязычный -
			# объектом, поэтому берутся все элементы, а не первый.
			$text = $null
			$textByLang = [ordered]@{}
			foreach ($tItem in $cContent.SelectNodes("d:tl/v8:item", $ns)) {
				$langNode = $tItem.SelectSingleNode("v8:lang", $ns)
				$contentNode = $tItem.SelectSingleNode("v8:content", $ns)
				if (-not $contentNode) { continue }
				$lang = if ($langNode) { $langNode.InnerText } else { "ru" }
				$textByLang[$lang] = $contentNode.InnerText
				if ($null -eq $text) { $text = $contentNode.InnerText }
				if (-not $textLanguagesSeen.Contains($lang)) { $textLanguagesSeen.Add($lang) | Out-Null }
			}

			$cells += @{
				Col        = $col
				FormatIdx  = $cellFmtIdx
				Param      = $param
				Detail     = $detail
				Text       = $text
				TextByLang = $textByLang
			}
		}
	}

	for ($r = $rowIdx; $r -le $indexTo; $r++) {
		$rowData[$r] = @{
			FormatIdx = $rowFmtIdx
			ColumnSet = $rowSetName
			Cells     = $cells
			Empty     = $isEmpty
		}
	}
}

# --- 9. Build style key (ignoring fillType) ---

function Get-BorderDesc {
	param($fmt)
	if (-not $fmt) { return @{ Border = "none"; Thick = $false } }

	$lb = $fmt.LB -ge 0; $tb = $fmt.TB -ge 0
	$rb = $fmt.RB -ge 0; $bb = $fmt.BB -ge 0

	if (-not $lb -and -not $tb -and -not $rb -and -not $bb) {
		return @{ Border = "none"; Thick = $false }
	}

	$thick = $false
	foreach ($bIdx in @($fmt.LB, $fmt.TB, $fmt.RB, $fmt.BB)) {
		if ($bIdx -ge 0 -and $bIdx -lt $rawLines.Count -and $rawLines[$bIdx].Width -ge 2) {
			$thick = $true; break
		}
	}

	if ($lb -and $tb -and $rb -and $bb) {
		return @{ Border = "all"; Thick = $thick }
	}

	$sides = @()
	if ($tb) { $sides += "top" }
	if ($bb) { $sides += "bottom" }
	if ($lb) { $sides += "left" }
	if ($rb) { $sides += "right" }

	return @{ Border = ($sides -join ","); Thick = $thick }
}

function Get-StyleKey {
	param($fmt)
	if (-not $fmt) { return "empty" }
	# Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры: подмена
	# навязывала бы его ячейкам, у которых шрифта не было.
	$fi = if ($fmt.FontIdx -ge 0) { $fmt.FontIdx } else { -1 }
	$bd = Get-BorderDesc $fmt
	return "f=$fi|b=$($bd.Border)|bw=$($bd.Thick)|ha=$($fmt.HA)|va=$($fmt.VA)|wr=$($fmt.Wrap)|df=$($fmt.DataFormat)|tc=$($fmt.TextColor)"
}

# --- 10. Name fonts ---

$fontNames = @{}
$fontDefs = [ordered]@{}

# Шрифт-ссылка именуется по самой ссылке: свойств, из которых собирается имя, у него нет.
function Get-RefFontName {
	param($f)
	$v = "$($f.Ref)"
	$i = $v.IndexOf(":")
	if ($i -ge 0) { return $v.Substring($i + 1) }
	return $v
}

# Имя default означает шрифт, который сборка подставит стилю без явного шрифта. Если в
# макете есть оформленный формат БЕЗ шрифта, такого умолчания у документа нет: первый
# шрифт палитры именуется как остальные, иначе сборка навяжет его тем ячейкам, у которых
# шрифта не было.
$hasFontlessFormat = $false
foreach ($fmt in $rawFormats) {
	if ($fmt.FontIdx -ge 0) { continue }
	if ($fmt.LB -ge 0 -or $fmt.TB -ge 0 -or $fmt.RB -ge 0 -or $fmt.BB -ge 0 -or
		$fmt.HA -or $fmt.VA -or $fmt.Wrap -or $fmt.FillType -or
		$fmt.DataFormat -or $fmt.TextColor -or $fmt.Hidden) {
		$hasFontlessFormat = $true
		break
	}
}


function Get-FontKey {
	param($f)
	$ns = (@($f.Namespace.Keys | Sort-Object | ForEach-Object { "$_=$($f.Namespace[$_])" }) -join ";")
	return "$($f.Ref)|$($f.Kind)|$ns|$($f.Face)|$($f.Size)|$($f.Bold)|$($f.Italic)|$($f.Underline)|$($f.Strikeout)"
}

$fontKeyMap = @{}

for ($i = 0; $i -lt $rawFonts.Count; $i++) {
	$f = $rawFonts[$i]
	$df = $rawFonts[0]

	# Dedup: if identical font already named, reuse
	$fKey = Get-FontKey $f
	if ($fontKeyMap.ContainsKey($fKey)) {
		$fontNames[$i] = $fontKeyMap[$fKey]
		continue
	}

	$name = $null

	if ($f.Ref) { $name = Get-RefFontName $f }

	if (-not $name -and $f.Face -eq $df.Face -and $f.Size -eq $df.Size) {
		if ($f.Bold -and -not $df.Bold -and -not $f.Italic -and -not $f.Underline -and -not $f.Strikeout) {
			$name = "bold"
		} elseif ($f.Italic -and -not $df.Italic -and -not $f.Bold) {
			$name = "italic"
		} elseif ($f.Underline -and -not $df.Underline -and -not $f.Bold -and -not $f.Italic) {
			$name = "underline"
		}
	} elseif ($f.Face -eq $df.Face -and $f.Size -gt $df.Size -and $f.Bold) {
		$name = "header"
	} elseif ($f.Face -eq $df.Face -and $f.Size -lt $df.Size) {
		$name = "small"
	}

	if (-not $name -and $i -eq 0 -and -not $hasFontlessFormat) { $name = "default" }

	if (-not $name) {
		$parts = @()
		if ($f.Face -and $f.Face -ne $df.Face) { $parts += $f.Face.ToLower() }
		$parts += "$($f.Size)"
		if ($f.Bold) { $parts += "bold" }
		if ($f.Italic) { $parts += "italic" }
		if ($f.Underline) { $parts += "underline" }
		if ($f.Strikeout) { $parts += "strikeout" }
		$name = $parts -join "-"
	}

	$baseName = $name; $suffix = 2
	while ($fontDefs.Contains($name)) { $name = "$baseName$suffix"; $suffix++ }

	$fontNames[$i] = $name
	$fontDefs[$name] = $f
	$fontKeyMap[$fKey] = $name
}

# --- 11. Collect and name styles ---

$styleKeys = [ordered]@{}
$formatToStyleKey = @{}

# Собственный формат строки тоже дает стиль: высота и скрытие в стиль не входят, а шрифт
# и оформление - входят.
function Test-RowFormatStyled {
	param($fmt)
	if (-not $fmt) { return $false }
	return ($fmt.FontIdx -ge 0 -or $fmt.LB -ge 0 -or $fmt.TB -ge 0 -or $fmt.RB -ge 0 -or
		$fmt.BB -ge 0 -or $fmt.HA -or $fmt.VA -or $fmt.Wrap -or
		$fmt.DataFormat -or $fmt.TextColor)
}

foreach ($r in $rowData.Values) {
	$rowFmtOwn = Get-Format $r.FormatIdx
	if (Test-RowFormatStyled $rowFmtOwn) {
		$rowKey = Get-StyleKey $rowFmtOwn
		if (-not $styleKeys.Contains($rowKey)) { $styleKeys[$rowKey] = $rowFmtOwn }
		$formatToStyleKey[$r.FormatIdx] = $rowKey
	}
	foreach ($cell in $r.Cells) {
		$fmt = Get-Format $cell.FormatIdx
		if (-not $fmt) { continue }
		$key = Get-StyleKey $fmt
		if (-not $styleKeys.Contains($key)) { $styleKeys[$key] = $fmt }
		$formatToStyleKey[$cell.FormatIdx] = $key
	}
}

function Name-Style {
	param($fmt)
	if (-not $fmt) { return "default" }
	$parts = @()

	# Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры: подмена
	# навязывала бы его ячейкам, у которых шрифта не было.
	$fi = if ($fmt.FontIdx -ge 0) { $fmt.FontIdx } else { -1 }
	if ($fontNames.ContainsKey($fi) -and $fontNames[$fi] -ne "default") {
		$parts += $fontNames[$fi]
	}

	$bd = Get-BorderDesc $fmt
	if ($bd.Border -ne "none") {
		if ($bd.Border -eq "all") { $parts += "bordered" }
		else { $parts += "border-$($bd.Border)" }
	}

	if ($fmt.HA -eq "Center") { $parts += "center" }
	elseif ($fmt.HA -eq "Right") { $parts += "right" }
	if ($fmt.VA -eq "Center") { $parts += "vcenter" }
	elseif ($fmt.VA -eq "Top") { $parts += "vtop" }
	if ($fmt.Wrap) { $parts += "wrap" }
	if ($fmt.TextColor -and $parts.Count -eq 0) { $parts += "colored" }
	if ($fmt.DataFormat) { $parts += "fmt" }

	if ($parts.Count -eq 0) { return "default" }
	return ($parts -join "-")
}

$styleNames = [ordered]@{}
$styleDefs = [ordered]@{}

foreach ($key in $styleKeys.Keys) {
	$fmt = $styleKeys[$key]
	$name = Name-Style $fmt

	$baseName = $name; $suffix = 2
	while ($styleDefs.Contains($name)) { $name = "$baseName$suffix"; $suffix++ }

	$styleNames[$key] = $name

	$sDef = [ordered]@{}
	# Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры: подмена
	# навязывала бы его ячейкам, у которых шрифта не было.
	$fi = if ($fmt.FontIdx -ge 0) { $fmt.FontIdx } else { -1 }
	if ($fontNames.ContainsKey($fi) -and $fontNames[$fi] -ne "default") {
		$sDef["font"] = $fontNames[$fi]
	}
	if ($fmt.HA) {
		$a = switch ($fmt.HA) { "Left" { "left" } "Center" { "center" } "Right" { "right" } "Justify" { "justify" } }
		if ($a) { $sDef["align"] = $a }
	}
	if ($fmt.VA) {
		$a = switch ($fmt.VA) { "Top" { "top" } "Center" { "center" } "Bottom" { "bottom" } }
		if ($a) { $sDef["valign"] = $a }
	}
	if ($fmt.TextColor) { $sDef["textColor"] = $fmt.TextColor }
	$bd = Get-BorderDesc $fmt
	if ($bd.Border -ne "none") {
		$sDef["border"] = $bd.Border
		if ($bd.Thick) { $sDef["borderWidth"] = "thick" }
	}
	if ($fmt.Wrap) { $sDef["wrap"] = $true }
	if ($fmt.DataFormat) { $sDef["format"] = $fmt.DataFormat }

	$styleDefs[$name] = $sDef
}

function Get-StyleName {
	param([int]$fmtIdx)
	$key = $formatToStyleKey[$fmtIdx]
	if ($key -and $styleNames.Contains($key)) { return $styleNames[$key] }
	return "default"
}

# Одноязычный текст возвращается строкой, разноязычный - объектом "язык: текст".
# Одинаковый текст на всех встреченных языках - это тоже строка: ее развернет обратно
# textLanguages при сборке.
function Get-TextValue {
	param($cell)
	$byLang = $cell.TextByLang
	if (-not $byLang -or $byLang.Count -eq 0) { return $cell.Text }
	# Строкой текст записывается только тогда, когда он одинаков и покрывает ВЕСЬ состав
	# языков вывода: иначе обратная сборка добавит ячейке язык, которого в ней не было.
	$distinct = @($byLang.Values | Sort-Object -Unique)
	$cellLangs = @($byLang.Keys | Sort-Object) -join ","
	$allLangs = @($textLanguagesSeen | Sort-Object) -join ","
	if ($distinct.Count -eq 1 -and $cellLangs -eq $allLangs) { return $cell.Text }
	$obj = [ordered]@{}
	foreach ($k in $byLang.Keys) { $obj[$k] = $byLang[$k] }
	return $obj
}

# Строка, у которой все ячейки простые, записывается массивом значений по колонкам - так
# описание читается и правится быстрее, чем набором объектов.
function ConvertTo-ShorthandRow($row) {
	$keys = @($row.Keys)
	if ($keys.Count -ne 1 -or $keys[0] -ne "cells") { return $null }
	$cells = @($row["cells"])
	if ($cells.Count -eq 0) { return $null }
	$slots = @{}
	$maxCol = 0
	foreach ($c in $cells) {
		foreach ($k in @($c.Keys)) {
			if ($k -notin @("col", "span", "text", "param", "template")) { return $null }
		}
		$content = @(@("text", "param", "template") | Where-Object { $c.Contains($_) })
		if ($content.Count -ne 1) { return $null }
		$kind = $content[0]
		$value = $c[$kind]
		if ($value -isnot [string]) { return $null }
		if ($kind -eq "param") {
			if ($value.Contains("{") -or $value.Contains("}")) { return $null }
			$token = "{" + $value + "}"
		} elseif ($kind -eq "template") {
			if ($value -notmatch '\[.+\]') { return $null }
			$token = $value
		} else {
			if ($value -eq ">" -or $value -eq "|" -or $value -match '^\{.+\}$' -or $value -match '\[.+\]') { return $null }
			$token = $value
		}
		$col = [int]$c["col"]
		$span = if ($c.Contains("span")) { [int]$c["span"] } else { 1 }
		if ($col -lt 1 -or $span -lt 1 -or $slots.ContainsKey($col)) { return $null }
		$slots[$col] = $token
		for ($k = 1; $k -lt $span; $k++) {
			if ($slots.ContainsKey($col + $k)) { return $null }
			$slots[$col + $k] = ">"
		}
		if ($col + $span - 1 -gt $maxCol) { $maxCol = $col + $span - 1 }
	}
	$out = New-Object System.Collections.Generic.List[object]
	for ($i = 1; $i -le $maxCol; $i++) {
		if ($slots.ContainsKey($i)) { [void]$out.Add($slots[$i]) } else { [void]$out.Add($null) }
	}
	return ,$out.ToArray()
}

# Область с вертикальными объединениями не сокращается: они выражаются знаком | и связывают
# соседние строки, а посвязной разбор здесь не окупается.
function ConvertTo-ShorthandRows($compressedRows) {
	foreach ($r in $compressedRows) {
		if (-not $r.Contains("cells")) { continue }
		foreach ($c in @($r["cells"])) {
			if ($c.Contains("rowspan")) { return ,$compressedRows }
		}
	}
	$out = New-Object System.Collections.Generic.List[object]
	foreach ($r in $compressedRows) {
		$short = ConvertTo-ShorthandRow $r
		if ($null -eq $short) { [void]$out.Add($r) } else { [void]$out.Add($short) }
	}
	return ,$out.ToArray()
}

# Свой формат есть и у строки без ячеек: высота, скрытие и стиль строки от отсутствия
# содержимого не пропадают.
function Get-RowOwnProperties {
	param($rd)
	$out = [ordered]@{}
	if (-not $rd) { return $out }
	if ($rd.ColumnSet) { $out["columnSet"] = $rd.ColumnSet }
	if ($rd.FormatIdx -gt 0) {
		$fmtOwn = Get-Format $rd.FormatIdx
		if ($fmtOwn -and $fmtOwn.Height -gt 0) { $out["height"] = $fmtOwn.Height }
		if ($fmtOwn -and $fmtOwn.Hidden) { $out["hidden"] = $true }
		if (Test-RowFormatStyled $fmtOwn) {
			$keyOwn = $formatToStyleKey[$rd.FormatIdx]
			if ($keyOwn -and $styleNames.Contains($keyOwn)) {
				$out["style"] = $styleNames[$keyOwn]
			}
		}
	}
	return $out
}

# --- 12. Build areas ---

$dslAreas = @()
$sheetRows = $null

# Строки, не попавшие ни в одну именованную область, тоже принадлежат документу.
# Они разбиваются на отрезки между областями, чтобы порядок строк сохранился.
$lastRow = -1
foreach ($rowIndex in $rowData.Keys) { if ([int]$rowIndex -gt $lastRow) { $lastRow = [int]$rowIndex } }
$sheetAreas = @()
$cursor = 0
foreach ($area in @($namedAreas | Sort-Object @{ Expression = { $_.BeginRow } }, @{ Expression = { $_.EndRow } })) {
	if ($area.BeginRow -gt $cursor) {
		$sheetAreas += [pscustomobject]@{ Name = ''; BeginRow = $cursor; EndRow = $area.BeginRow - 1 }
	}
	$sheetAreas += [pscustomobject]@{ Name = $area.Name; BeginRow = $area.BeginRow; EndRow = $area.EndRow }
	if ($area.EndRow + 1 -gt $cursor) { $cursor = $area.EndRow + 1 }
}
if ($cursor -le $lastRow) {
	$sheetAreas += [pscustomobject]@{ Name = ''; BeginRow = $cursor; EndRow = $lastRow }
}

foreach ($area in $sheetAreas) {
	$areaRows = @()

	for ($globalRow = $area.BeginRow; $globalRow -le $area.EndRow; $globalRow++) {
		$rd = $rowData[$globalRow]

		if (-not $rd -or $rd.Empty) {
			$areaRows += (Get-RowOwnProperties $rd)
			continue
		}

		$dslRow = Get-RowOwnProperties $rd

		# Separate content cells from gap-fill cells
		$contentCells = @()
		$gapCells = @()

		foreach ($cell in $rd.Cells) {
			$hasContent = $cell.Param -or $cell.Text
			$hasMerge = $mergeMap.ContainsKey("$globalRow,$($cell.Col)")

			if ($hasContent -or $hasMerge) {
				$contentCells += $cell
			} else {
				$gapCells += $cell
			}
		}

		# Detect rowStyle
		$rowStyleName = $null
		$rowStyleKey = $null

		if ($gapCells.Count -gt 0) {
			$gapKeys = @{}
			foreach ($gc in $gapCells) {
				$fmt = Get-Format $gc.FormatIdx
				$gapKeys[(Get-StyleKey $fmt)] = $true
			}

			if ($gapKeys.Count -eq 1) {
				$rowStyleKey = @($gapKeys.Keys)[0]
				if ($styleNames.Contains($rowStyleKey)) {
					$rowStyleName = $styleNames[$rowStyleKey]
				}
			}
		}

		if ($rowStyleName -and $rowStyleName -ne "default") { $dslRow["rowStyle"] = $rowStyleName }

		# Build cell list
		$dslCells = @()

		foreach ($cell in ($contentCells | Sort-Object { $_.Col })) {
			$dslCell = [ordered]@{ col = $cell.Col + 1 }

			# Span/rowspan from merge
			$mk = "$globalRow,$($cell.Col)"
			if ($mergeMap.ContainsKey($mk)) {
				$m = $mergeMap[$mk]
				if ($m.W -gt 0) { $dslCell["span"] = $m.W + 1 }
				if ($m.H -gt 0) { $dslCell["rowspan"] = $m.H + 1 }
			}

			# Style
			$cellFmt = Get-Format $cell.FormatIdx
			$cellStyleKey = Get-StyleKey $cellFmt

			if ($rowStyleKey -and $cellStyleKey -eq $rowStyleKey) {
				# Inherits rowStyle
			} else {
				# Нулевой формат означает, что оформление у ячейки не задано: стиль ей не нужен,
				# иначе обратная сборка завела бы формат, которого в исходнике нет.
				if ([int]$cell.FormatIdx -gt 0) {
					$sn = Get-StyleName $cell.FormatIdx
					if ($sn -ne "default" -or -not $rowStyleName) {
						$dslCell["style"] = $sn
					}
				}
			}

			# Content
			$fillType = if ($cellFmt) { $cellFmt.FillType } else { "" }

			if ($cell.Param) {
				$dslCell["param"] = $cell.Param
				if ($cell.Detail) { $dslCell["detail"] = $cell.Detail }
			} elseif ($fillType -eq "Template" -and $cell.Text) {
				$dslCell["template"] = Get-TextValue $cell
			} elseif ($cell.Text) {
				$dslCell["text"] = Get-TextValue $cell
			}

			$dslCells += $dslCell
		}

		if ($dslCells.Count -gt 0) { $dslRow["cells"] = [array]$dslCells }
		$areaRows += $dslRow
	}

	# Compress consecutive empty rows ({}) into { empty = N }
	$compressedRows = @()
	$emptyRun = 0
	foreach ($r in $areaRows) {
		if ($r.Count -eq 0) {
			$emptyRun++
		} else {
			if ($emptyRun -gt 0) {
				if ($emptyRun -eq 1) { $compressedRows += [ordered]@{} }
				else { $compressedRows += [ordered]@{ empty = $emptyRun } }
				$emptyRun = 0
			}
			$compressedRows += $r
		}
	}
	if ($emptyRun -gt 0) {
		if ($emptyRun -eq 1) { $compressedRows += [ordered]@{} }
		else { $compressedRows += [ordered]@{ empty = $emptyRun } }
	}

	# Без единой именованной области строки документа выносятся на верхний уровень;
	# иначе безымянный отрезок остается областью без имени и держит свое место.
	$compressedRows = ConvertTo-ShorthandRows $compressedRows
	if ($namedAreas.Count -eq 0) {
		$sheetRows = [array]$compressedRows
	} elseif ($area.Name) {
		$dslAreas += [ordered]@{
			name = $area.Name
			rows = [array]$compressedRows
		}
	} else {
		$dslAreas += [ordered]@{ rows = [array]$compressedRows }
	}
}

# --- 13. Compress columnWidths ---

$compressedWidths = [ordered]@{}
if ($colWidthMap.Count -gt 0) {
	$grouped = $colWidthMap.Keys | Group-Object { $colWidthMap[$_] }
	foreach ($g in $grouped) {
		$width = [int]$g.Name
		$cols = @($g.Group | Sort-Object { [int]$_ })

		$ranges = @()
		$rangeStart = $cols[0]; $rangePrev = $cols[0]

		for ($i = 1; $i -lt $cols.Count; $i++) {
			if ([int]$cols[$i] -eq [int]$rangePrev + 1) {
				$rangePrev = $cols[$i]
			} else {
				if ($rangeStart -eq $rangePrev) { $ranges += "$rangeStart" }
				else { $ranges += "$rangeStart-$rangePrev" }
				$rangeStart = $cols[$i]; $rangePrev = $cols[$i]
			}
		}
		if ($rangeStart -eq $rangePrev) { $ranges += "$rangeStart" }
		else { $ranges += "$rangeStart-$rangePrev" }

		foreach ($range in $ranges) { $compressedWidths[$range] = $width }
	}
}

# --- 14. Build fonts output ---

$fontsOut = [ordered]@{}
foreach ($name in $fontDefs.Keys) {
	$f = $fontDefs[$name]
	if ($f.Ref) {
		$fOut = [ordered]@{}
		if ($f.Namespace -and $f.Namespace.Count -gt 0) {
			$nsOut = [ordered]@{}
			foreach ($k in $f.Namespace.Keys) { $nsOut[$k] = $f.Namespace[$k] }
			$fOut["namespace"] = $nsOut
		}
		$fOut["ref"] = $f.Ref
		$fOut["kind"] = $f.Kind
		$fontsOut[$name] = $fOut
		continue
	}
	$fOut = [ordered]@{ face = $f.Face; size = $f.Size }
	if ($f.Bold) { $fOut["bold"] = $true }
	if ($f.Italic) { $fOut["italic"] = $true }
	if ($f.Underline) { $fOut["underline"] = $true }
	if ($f.Strikeout) { $fOut["strikeout"] = $true }
	$fontsOut[$name] = $fOut
}

# --- 15. Assemble result ---

# Состав языков сохраняется: у макета их бывает несколько, и обратная сборка обязана
# воспроизвести тот же список.
$languagesOut = @()
$langSettings = $root.SelectSingleNode("d:languageSettings", $ns)
$currentLanguage = ""
$defaultLanguage = ""
if ($langSettings) {
	$curNode = $langSettings.SelectSingleNode("d:currentLanguage", $ns)
	if ($curNode) { $currentLanguage = $curNode.InnerText.Trim() }
	$defNode = $langSettings.SelectSingleNode("d:defaultLanguage", $ns)
	if ($defNode) { $defaultLanguage = $defNode.InnerText.Trim() }
	foreach ($li in $langSettings.SelectNodes("d:languageInfo", $ns)) {
		$idNode = $li.SelectSingleNode("d:id", $ns)
		$codeNode = $li.SelectSingleNode("d:code", $ns)
		$descNode = $li.SelectSingleNode("d:description", $ns)
		$languagesOut += [ordered]@{
			id = if ($idNode) { $idNode.InnerText.Trim() } else { "" }
			code = if ($codeNode) { $codeNode.InnerText.Trim() } else { "" }
			description = if ($descNode) { $descNode.InnerText.Trim() } else { "" }
		}
	}
}

$result = [ordered]@{
	columns      = $totalColumns
	defaultWidth = $defaultWidth
}
if ($compressedWidths.Count -gt 0) { $result["columnWidths"] = $compressedWidths }
# Умолчание навыка - один русский язык; всякий иной состав записывается.
$onlyRussianText = ($textLanguagesSeen.Count -eq 1 -and $textLanguagesSeen[0] -eq "ru")
if ($textLanguagesSeen.Count -gt 0 -and -not $onlyRussianText) { $result["textLanguages"] = @($textLanguagesSeen) }
# В описание не выносится ровно то, что навык подставит сам: один русский язык. Любой
# другой одиночный язык записывается, иначе обратная сборка сделает макет русским.
$russianDefault = ($languagesOut.Count -eq 1 -and
	$languagesOut[0].id -eq "ru" -and $languagesOut[0].code -eq "Русский" -and
	$languagesOut[0].description -eq "Русский" -and
	($currentLanguage -eq "" -or $currentLanguage -eq "ru") -and
	($defaultLanguage -eq "" -or $defaultLanguage -eq "ru"))
if ($languagesOut.Count -gt 0 -and -not $russianDefault) {
	$result["languages"] = [array]$languagesOut
	if ($currentLanguage) { $result["currentLanguage"] = $currentLanguage }
	if ($defaultLanguage) { $result["defaultLanguage"] = $defaultLanguage }
}
# Remove empty "default" style
if ($styleDefs.Contains("default") -and $styleDefs["default"].Count -eq 0) {
	$styleDefs.Remove("default")
}

# Remove unused styles
$usedStyles = @{}
$styleScanRows = @()
foreach ($a in $dslAreas) { $styleScanRows += @($a.rows) }
if ($sheetRows) { $styleScanRows += @($sheetRows) }
foreach ($r in $styleScanRows) {
	# Строка, записанная массивом, стилей не несет.
	if ($r -isnot [System.Collections.IDictionary]) { continue }
	if ($r.rowStyle) { $usedStyles[$r.rowStyle] = $true }
	if ($r.style) { $usedStyles[$r.style] = $true }
	if ($r.cells) { foreach ($c in $r.cells) { if ($c.style) { $usedStyles[$c.style] = $true } } }
}
$toRemove = @($styleDefs.Keys | Where-Object { -not $usedStyles.ContainsKey($_) })
foreach ($s in $toRemove) { $styleDefs.Remove($s)
}

$result["fonts"] = $fontsOut
$result["styles"] = $styleDefs
if ($dslAreas.Count -gt 0) { $result["areas"] = [array]$dslAreas }
if ($sheetRows) { $result["rows"] = $sheetRows }
if ($coordAreas.Count -gt 0) { $result["namedAreas"] = [array]$coordAreas }
if ($columnSetsOut.Count -gt 0) { $result["columnSets"] = $columnSetsOut }

# --- 16. Convert to JSON ---

# Описание пишется в том виде, в каком его удобно править руками: компактно там, где
# это не мешает читать.

# --- Черновой JSON (общий блок, версия 2) ---
# Ширина строки, после которой контейнер разворачивается по элементу на строку.
$script:draftJsonWidth = 400

function ConvertTo-JsonStringLiteral($s) {
	$sb = New-Object System.Text.StringBuilder
	[void]$sb.Append('"')
	foreach ($ch in ([string]$s).ToCharArray()) {
		if ($ch -eq '"') { [void]$sb.Append('\"') }
		elseif ($ch -eq '\') { [void]$sb.Append('\\') }
		elseif ($ch -eq "`n") { [void]$sb.Append('\n') }
		elseif ($ch -eq "`r") { [void]$sb.Append('\r') }
		elseif ($ch -eq "`t") { [void]$sb.Append('\t') }
		elseif ([int]$ch -lt 32) { [void]$sb.Append('\u' + ([int]$ch).ToString('x4')) }
		else { [void]$sb.Append($ch) }
	}
	[void]$sb.Append('"')
	return $sb.ToString()
}

function ConvertTo-InlineJson($v) {
	if ($null -eq $v) { return 'null' }
	if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
	if ($v -is [int] -or $v -is [int64] -or $v -is [double] -or $v -is [decimal]) {
		return [System.Convert]::ToString($v, [System.Globalization.CultureInfo]::InvariantCulture)
	}
	if ($v -is [string]) { return ConvertTo-JsonStringLiteral $v }
	if ($v -is [System.Collections.IDictionary]) {
		if ($v.Count -eq 0) { return '{}' }
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($k in $v.Keys) {
			[void]$parts.Add((ConvertTo-JsonStringLiteral ([string]$k)) + ': ' + (ConvertTo-InlineJson $v[$k]))
		}
		return '{ ' + ($parts -join ', ') + ' }'
	}
	if ($v -is [System.Collections.IEnumerable]) {
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($it in $v) { [void]$parts.Add((ConvertTo-InlineJson $it)) }
		if ($parts.Count -eq 0) { return '[]' }
		return '[' + ($parts -join ', ') + ']'
	}
	return ConvertTo-JsonStringLiteral ([string]$v)
}

# Описание пишется в том виде, в каком его удобно править руками: контейнер идет одной
# строкой, пока в нее помещается, и разворачивается, когда перестает.
function ConvertTo-DraftJson($v, $indent) {
	$rendered = ConvertTo-InlineJson $v
	$isContainer = ($v -is [System.Collections.IDictionary]) -or
		(($v -is [System.Collections.IEnumerable]) -and ($v -isnot [string]))
	if (-not $isContainer -or ($indent.Length + $rendered.Length) -le $script:draftJsonWidth) {
		return $rendered
	}
	$inner = $indent + '  '
	if ($v -is [System.Collections.IDictionary]) {
		if ($v.Count -eq 0) { return '{}' }
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($k in $v.Keys) {
			[void]$parts.Add($inner + (ConvertTo-JsonStringLiteral ([string]$k)) + ': ' + (ConvertTo-DraftJson $v[$k] $inner))
		}
		return "{`n" + ($parts -join ",`n") + "`n" + $indent + '}'
	}
	$parts = New-Object System.Collections.Generic.List[object]
	foreach ($it in $v) { [void]$parts.Add($inner + (ConvertTo-DraftJson $it $inner)) }
	if ($parts.Count -eq 0) { return '[]' }
	return "[`n" + ($parts -join ",`n") + "`n" + $indent + ']'
}
# --- Конец общего блока чернового JSON ---

$json = ConvertTo-DraftJson $result ''

# --- 17. Output ---

if ($OutputPath) {
	$enc = New-Object System.Text.UTF8Encoding($false)
	# Абсолютный путь берется как есть: приклеивание текущего каталога давало
	# несуществующий путь вида "E:\проект\C:\каталог\файл.json".
	$outResolved = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path (Get-Location) $OutputPath }
	[System.IO.File]::WriteAllText($outResolved, $json, $enc)
	Write-Host "[OK] Decompiled: $OutputPath"
} else {
	Write-Output $json
}

Write-Host "     Areas: $($namedAreas.Count), Rows: $($rowData.Count), Columns: $totalColumns" -ForegroundColor DarkGray
Write-Host "     Fonts: $($fontDefs.Count), Styles: $($styleDefs.Count), Merges: $($mergeMap.Count)" -ForegroundColor DarkGray
