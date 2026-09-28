# change-package v1.0 - Build a manual-change package for 1C modules edited outside the sources
# Source: https://github.com/Desko77/claude-code-skills-1c
# Строит пакет ручного внесения правок по двум версиям модулей 1С: блоки "Найти" и
# "Заменить целиком на" по методам, добавленные и удаленные методы, изменения вне методов
# и список файлов для правки руками в Конфигураторе.
param(
	[string]$Before = "",
	[string]$After = "",
	[string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Справочники имен ---

# Каталог выгрузки -> русское имя типа объекта. Незнакомый каталог описания не дает.
$script:typeTitles = @{
	"AccountingRegisters" = "Регистр бухгалтерии"
	"AccumulationRegisters" = "Регистр накопления"
	"Bots" = "Бот"
	"BusinessProcesses" = "Бизнес-процесс"
	"CalculationRegisters" = "Регистр расчета"
	"Catalogs" = "Справочник"
	"ChartsOfAccounts" = "План счетов"
	"ChartsOfCalculationTypes" = "План видов расчета"
	"ChartsOfCharacteristicTypes" = "План видов характеристик"
	"CommonAttributes" = "Общий реквизит"
	"CommonCommands" = "Общая команда"
	"CommonForms" = "Общая форма"
	"CommonModules" = "Общий модуль"
	"CommonPictures" = "Общая картинка"
	"CommonTemplates" = "Общий макет"
	"Constants" = "Константа"
	"DataProcessors" = "Обработка"
	"DefinedTypes" = "Определяемый тип"
	"DocumentJournals" = "Журнал документов"
	"DocumentNumerators" = "Нумератор документов"
	"Documents" = "Документ"
	"Enums" = "Перечисление"
	"EventSubscriptions" = "Подписка на событие"
	"ExchangePlans" = "План обмена"
	"FilterCriteria" = "Критерий отбора"
	"FunctionalOptions" = "Функциональная опция"
	"HTTPServices" = "HTTP-сервис"
	"InformationRegisters" = "Регистр сведений"
	"IntegrationServices" = "Сервис интеграции"
	"Languages" = "Язык"
	"Reports" = "Отчет"
	"Roles" = "Роль"
	"ScheduledJobs" = "Регламентное задание"
	"Sequences" = "Последовательность"
	"SessionParameters" = "Параметр сеанса"
	"SettingsStorages" = "Хранилище настроек"
	"StyleItems" = "Элемент стиля"
	"Subsystems" = "Подсистема"
	"Tasks" = "Задача"
	"WebServices" = "Web-сервис"
	"WSReferences" = "WS-ссылка"
	"XDTOPackages" = "Пакет XDTO"
}

# Имя файла модуля -> вид модуля. Пустая строка там, где вид уже назван типом объекта
# (общий модуль, модуль формы): иначе вышло бы "Общий модуль Товары, модуль".
$script:moduleTitles = @{
	"CommandModule.bsl" = "модуль команды"
	"ManagerModule.bsl" = "модуль менеджера"
	"Module.bsl" = ""
	"ObjectModule.bsl" = "модуль объекта"
	"RecordSetModule.bsl" = "модуль набора записей"
	"ValueManagerModule.bsl" = "модуль менеджера значения"
}

# Корневые модули конфигурации лежат в Ext/ рядом с Configuration.xml.
$script:rootModuleTitles = @{
	"ExternalConnectionModule.bsl" = "Модуль внешнего соединения"
	"ManagedApplicationModule.bsl" = "Модуль управляемого приложения"
	"OrdinaryApplicationModule.bsl" = "Модуль обычного приложения"
	"SessionModule.bsl" = "Модуль сеанса"
}

# Ключевые слова читаются в обоих написаниях: модуль может быть русским или английским.
$script:declaration = [regex]'^[ \t]*(Процедура|Procedure|Функция|Function)[ \t]+(\w+)[ \t]*\('
$script:functionWords = @("Функция", "Function")
$script:endProcWords = @("КонецПроцедуры", "EndProcedure")
$script:endFuncWords = @("КонецФункции", "EndFunction")
$script:counters = @("changed", "added", "removed", "outside")

# --- Чтение файлов ---

# Текст модуля в unicode: UTF-8, а при отказе разбора - CP1251. Метка порядка байтов снимается.
function Read-PkgText([string]$path) {
	$bytes = [System.IO.File]::ReadAllBytes($path)
	$text = ""
	try {
		$strict = New-Object System.Text.UTF8Encoding($false, $true)
		$text = $strict.GetString($bytes)
	} catch {
		$text = [System.Text.Encoding]::GetEncoding(1251).GetString($bytes)
	}
	if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
	return $text
}

# Строки текста независимо от вида перевода строки.
function Split-PkgLines([string]$text) {
	return ($text -split "\r\n|\r|\n")
}

# Слепок текста для сравнения: хвостовые пробелы и пустые строки не учитываются.
function Get-PkgNormalized($lines) {
	$out = New-Object System.Collections.Generic.List[string]
	foreach ($line in $lines) {
		$trimmed = $line.TrimEnd()
		if ($trimmed.Trim().Length -gt 0) { $out.Add($trimmed) }
	}
	return ,$out.ToArray()
}

# Два файла различаются по содержимому.
function Test-PkgFilesDiffer([string]$first, [string]$second) {
	$leftInfo = New-Object System.IO.FileInfo($first)
	$rightInfo = New-Object System.IO.FileInfo($second)
	if ($leftInfo.Length -ne $rightInfo.Length) { return $true }
	$left = [System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes($first))
	$right = [System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes($second))
	return ($left -cne $right)
}

# --- Разбор методов ---

# Слово совпадает с одним из написаний без учета регистра.
function Test-PkgWord([string]$word, [string[]]$words) {
	$folded = $word.ToLowerInvariant()
	foreach ($other in $words) {
		if ($folded -ceq $other.ToLowerInvariant()) { return $true }
	}
	return $false
}

# Строка начинается с ключевого слова, а следом пробел, табуляция или комментарий.
function Test-PkgOpenWord([string]$line, [string[]]$words) {
	$text = $line.Trim().ToLowerInvariant()
	foreach ($word in $words) {
		$head = $word.ToLowerInvariant()
		if ($text -ceq $head) { return $true }
		if ($text.StartsWith($head, [System.StringComparison]::Ordinal) -and $text.Length -gt $head.Length) {
			$next = $text.Substring($head.Length, 1)
			if ($next -eq " " -or $next -eq "`t" -or $next -eq "/") { return $true }
		}
	}
	return $false
}

# Строка примыкает к объявлению метода: директива компиляции или комментарий.
function Test-PkgAttachment([string]$line) {
	$text = $line.Trim()
	if ($text.StartsWith("&", [System.StringComparison]::Ordinal)) { return $true }
	return $text.StartsWith("//", [System.StringComparison]::Ordinal)
}

# Методы модуля в порядке следования: имя, границы и ключ сопоставления версий.
# Ключ - имя без учета регистра плюс номер повторения: одноименные методы в BSL
# невозможны, но битый модуль не должен из-за этого терять методы.
function Get-PkgMethods($lines) {
	$methods = New-Object System.Collections.Generic.List[psobject]
	$seen = @{}
	$index = 0
	while ($index -lt $lines.Count) {
		$match = $script:declaration.Match([string]$lines[$index])
		if (-not $match.Success) { $index++; continue }
		$name = $match.Groups[2].Value
		$start = $index
		while ($start -gt 0 -and (Test-PkgAttachment ([string]$lines[$start - 1]))) { $start-- }
		$endWords = $script:endProcWords
		if (Test-PkgWord $match.Groups[1].Value $script:functionWords) { $endWords = $script:endFuncWords }
		$end = $index + 1
		while ($end -lt $lines.Count -and -not (Test-PkgOpenWord ([string]$lines[$end]) $endWords)) { $end++ }
		if ($end -ge $lines.Count) { $end = $lines.Count - 1 }
		$folded = $name.ToLowerInvariant()
		$repeat = 0
		if ($seen.ContainsKey($folded)) { $repeat = $seen[$folded] }
		$seen[$folded] = $repeat + 1
		$methods.Add([pscustomobject]@{
			Key = $folded + "|" + $repeat
			Name = $name
			Start = $start
			Decl = $index
			End = $end
		})
		$index = $end + 1
	}
	return ,$methods.ToArray()
}

# Текст метода целиком: директивы и комментарий перед объявлением, тело, закрывающее слово.
function Get-PkgMethodText($method, $lines) {
	return $lines[$method.Start..$method.End]
}

# Строки модуля, не попавшие ни в один метод: переменные модуля и основной код.
function Get-PkgOutsideText($lines, $methods) {
	$covered = New-Object System.Collections.Generic.HashSet[int]
	foreach ($method in $methods) {
		for ($i = $method.Start; $i -le $method.End; $i++) { [void]$covered.Add($i) }
	}
	$out = New-Object System.Collections.Generic.List[string]
	for ($i = 0; $i -lt $lines.Count; $i++) {
		if (-not $covered.Contains($i)) { $out.Add([string]$lines[$i]) }
	}
	return ,$out.ToArray()
}

# --- Описание модуля человеческим языком ---

# Части описания через запятую, пустые части отбрасываются.
function Join-PkgTitle([string[]]$parts) {
	$kept = New-Object System.Collections.Generic.List[string]
	foreach ($part in $parts) {
		if ($part -and $part.Length -gt 0) { $kept.Add($part) }
	}
	return ($kept -join ", ")
}

# Название объекта по каталогу выгрузки: "Справочник Товары".
function Get-PkgObjectTitle([string]$dirName, [string]$name) {
	if (-not $script:typeTitles.ContainsKey($dirName)) { return "" }
	return $script:typeTitles[$dirName] + " " + $name
}

# Описание модуля по пути в выгрузке: "Справочник Товары, модуль объекта".
function Get-PkgModuleTitle([string]$rel) {
	$parts = $rel.Replace("\", "/").Split("/")
	$fileName = $parts[$parts.Count - 1]
	$kind = ""
	if ($script:moduleTitles.ContainsKey($fileName)) { $kind = $script:moduleTitles[$fileName] }

	if ($parts.Count -eq 2 -and $parts[0] -eq "Ext") {
		if ($script:rootModuleTitles.ContainsKey($fileName)) { return $script:rootModuleTitles[$fileName] }
		return ""
	}

	$formIndex = [System.Array]::IndexOf($parts, "Forms")
	if ($formIndex -ge 0) {
		$formName = ""
		if ($formIndex + 1 -lt $parts.Count) { $formName = $parts[$formIndex + 1] }
		$title = ""
		if ($formIndex -ge 2) { $title = Get-PkgObjectTitle $parts[0] $parts[1] }
		$formPart = ""
		if ($formName.Length -gt 0) { $formPart = "форма " + $formName }
		return (Join-PkgTitle @($title, $formPart, $kind))
	}

	if ($parts.Count -ge 2) { return (Join-PkgTitle @((Get-PkgObjectTitle $parts[0] $parts[1]), $kind)) }
	return $kind
}

# --- Сбор файлов ---

# Относительные пути всех файлов каталога по возрастанию, разделитель - косая черта.
function Get-PkgFiles([string]$root) {
	$rootFull = [System.IO.Path]::GetFullPath($root)
	$list = New-Object System.Collections.Generic.List[string]
	foreach ($file in [System.IO.Directory]::EnumerateFiles($rootFull, "*", [System.IO.SearchOption]::AllDirectories)) {
		$rel = $file.Substring($rootFull.Length).TrimStart("\").Replace("\", "/")
		$list.Add($rel)
	}
	$array = $list.ToArray()
	[System.Array]::Sort($array, [System.StringComparer]::Ordinal)
	return ,$array
}

# --- Отрисовка пакета ---

# Текст в ограде bsl с закрывающей пустой строкой пункта.
function Format-PkgFence($lines) {
	$out = New-Object System.Collections.Generic.List[string]
	$out.Add('```bsl')
	$body = New-Object System.Collections.Generic.List[string]
	foreach ($line in $lines) { $body.Add([string]$line) }
	while ($body.Count -gt 0 -and $body[$body.Count - 1].Trim().Length -eq 0) { $body.RemoveAt($body.Count - 1) }
	foreach ($line in $body) { $out.Add($line) }
	$out.Add('```')
	$out.Add("")
	return ,$out.ToArray()
}

# Пункт пакета с парой блоков: что найти и на что заменить целиком.
function New-PkgChange([string]$head, $beforeLines, $afterLines) {
	$out = New-Object System.Collections.Generic.List[string]
	$out.Add($head)
	$out.Add("")
	$out.Add("Найти:")
	$out.Add("")
	$out.AddRange((Format-PkgFence $beforeLines))
	$out.Add("Заменить целиком на:")
	$out.Add("")
	$out.AddRange((Format-PkgFence $afterLines))
	return ,$out.ToArray()
}

# Пункт пакета с одним блоком: добавление или удаление метода.
function New-PkgSingle([string]$head, [string]$caption, $lines) {
	$out = New-Object System.Collections.Generic.List[string]
	$out.Add($head)
	$out.Add("")
	$out.Add($caption)
	$out.Add("")
	$out.AddRange((Format-PkgFence $lines))
	return ,$out.ToArray()
}

# Пункты пакета по одному модулю: измененные методы, добавленные, удаленные, код вне методов.
function New-PkgModuleSection([string]$rel, $beforeLines, $afterLines, $beforeMethods, $afterMethods) {
	$items = New-Object System.Collections.Generic.List[string]
	$afterKeys = New-Object System.Collections.Generic.HashSet[string]
	foreach ($method in $afterMethods) { [void]$afterKeys.Add($method.Key) }
	$beforeByKey = @{}
	foreach ($method in $beforeMethods) { $beforeByKey[$method.Key] = $method }

	for ($position = 0; $position -lt $afterMethods.Count; $position++) {
		$method = $afterMethods[$position]
		if (-not $beforeByKey.ContainsKey($method.Key)) {
			$head = "### Добавить метод " + $method.Name + " в начало модуля"
			if ($position -gt 0) {
				$head = "### Добавить метод " + $method.Name + " после метода " + $afterMethods[$position - 1].Name
			}
			$items.AddRange((New-PkgSingle $head "Текст метода:" (Get-PkgMethodText $method $afterLines)))
			continue
		}
		$old = $beforeByKey[$method.Key]
		$oldText = Get-PkgNormalized (Get-PkgMethodText $old $beforeLines)
		$newText = Get-PkgNormalized (Get-PkgMethodText $method $afterLines)
		if (($oldText -join "`n") -cne ($newText -join "`n")) {
			$items.AddRange((New-PkgChange ("### Изменить метод " + $method.Name) (Get-PkgMethodText $old $beforeLines) (Get-PkgMethodText $method $afterLines)))
		}
	}

	foreach ($method in $beforeMethods) {
		if (-not $afterKeys.Contains($method.Key)) {
			$items.AddRange((New-PkgSingle ("### Удалить метод " + $method.Name) "Удалить целиком:" (Get-PkgMethodText $method $beforeLines)))
		}
	}

	$oldOutside = Get-PkgOutsideText $beforeLines $beforeMethods
	$newOutside = Get-PkgOutsideText $afterLines $afterMethods
	if (((Get-PkgNormalized $oldOutside) -join "`n") -cne ((Get-PkgNormalized $newOutside) -join "`n")) {
		$items.AddRange((New-PkgChange "### Изменить код вне методов" $oldOutside $newOutside))
	}

	if ($items.Count -eq 0) { return ,([string[]]@()) }
	$section = New-Object System.Collections.Generic.List[string]
	$head = "## " + $rel
	$title = Get-PkgModuleTitle $rel
	if ($title.Length -gt 0) { $head = $head + " - " + $title }
	$section.Add($head)
	$section.Add("")
	$section.AddRange($items)
	return ,$section.ToArray()
}

# Счетчики пунктов в готовом разделе модуля.
function Get-PkgCounts($section) {
	$counts = @{ changed = 0; added = 0; removed = 0; outside = 0 }
	foreach ($line in $section) {
		if ($line.StartsWith("### Изменить метод", [System.StringComparison]::Ordinal)) { $counts["changed"]++ }
		elseif ($line.StartsWith("### Добавить метод", [System.StringComparison]::Ordinal)) { $counts["added"]++ }
		elseif ($line.StartsWith("### Удалить метод", [System.StringComparison]::Ordinal)) { $counts["removed"]++ }
		elseif ($line.StartsWith("### Изменить код вне методов", [System.StringComparison]::Ordinal)) { $counts["outside"]++ }
	}
	return $counts
}

# Раздел модуля: парсит методы обеих версий и отрисовывает пункты.
function New-PkgSection([string]$rel, $beforeLines, $afterLines) {
	$beforeMethods = Get-PkgMethods $beforeLines
	$afterMethods = Get-PkgMethods $afterLines
	return ,(New-PkgModuleSection $rel $beforeLines $afterLines $beforeMethods $afterMethods)
}

# Нулевые счетчики пакета.
function New-PkgTotals {
	return @{ modules = 0; changed = 0; added = 0; removed = 0; outside = 0 }
}

# Прибавить счетчики одного модуля к счетчикам пакета.
function Add-PkgCounts($totals, $counts) {
	foreach ($name in $script:counters) { $totals[$name] = $totals[$name] + $counts[$name] }
	return $totals
}

# Пакет markdown целиком: шапка со счетчиками, разделы модулей, файлы для ручной правки.
function Format-PkgPackage([string]$beforeArg, [string]$afterArg, $sections, $manual, $totals) {
	$out = New-Object System.Collections.Generic.List[string]
	$out.Add("# Пакет ручного внесения изменений")
	$out.Add("")
	$out.Add("До: " + $beforeArg)
	$out.Add("После: " + $afterArg)
	$out.Add("")
	if ($sections.Count -eq 0 -and $manual.Count -eq 0) {
		$out.Add("Различий между версиями нет.")
		return ($out -join "`n") + "`n"
	}
	$out.Add("Модулей с правками: " + $totals["modules"] + ", методов изменено: " + $totals["changed"] +
		", добавлено: " + $totals["added"] + ", удалено: " + $totals["removed"] +
		", правок вне методов: " + $totals["outside"])
	if ($manual.Count -gt 0) { $out.Add("Файлов для правки вручную: " + $manual.Count) }
	$out.Add("")
	foreach ($section in $sections) { $out.AddRange($section) }
	if ($manual.Count -gt 0) {
		$out.Add("## Файлы для правки вручную")
		$out.Add("")
		foreach ($entry in $manual) {
			$out.Add("- Изменить вручную в Конфигураторе: " + $entry.Path + $entry.Mark)
		}
		$out.Add("")
	}
	return ($out -join "`n") + "`n"
}

# --- Сравнение версий ---

# Разбор двух каталогов выгрузки: разделы пакета и список файлов для ручной правки.
function Compare-PkgDirectories([string]$beforeRoot, [string]$afterRoot) {
	$beforeFiles = Get-PkgFiles $beforeRoot
	$afterFiles = Get-PkgFiles $afterRoot
	$beforeSet = New-Object System.Collections.Generic.HashSet[string]
	foreach ($rel in $beforeFiles) { [void]$beforeSet.Add($rel) }
	$afterSet = New-Object System.Collections.Generic.HashSet[string]
	foreach ($rel in $afterFiles) { [void]$afterSet.Add($rel) }

	$sections = New-Object System.Collections.Generic.List[psobject]
	$manual = New-Object System.Collections.Generic.List[psobject]
	$totals = New-PkgTotals

	$common = New-Object System.Collections.Generic.List[string]
	foreach ($rel in $beforeFiles) { if ($afterSet.Contains($rel)) { $common.Add($rel) } }
	$commonArray = $common.ToArray()
	[System.Array]::Sort($commonArray, [System.StringComparer]::Ordinal)

	foreach ($rel in $commonArray) {
		$first = [System.IO.Path]::Combine($beforeRoot, $rel.Replace("/", "\"))
		$second = [System.IO.Path]::Combine($afterRoot, $rel.Replace("/", "\"))
		if (-not (Test-PkgFilesDiffer $first $second)) { continue }
		if (-not $rel.ToLowerInvariant().EndsWith(".bsl", [System.StringComparison]::Ordinal)) {
			$manual.Add([pscustomobject]@{ Mark = ""; Path = $rel })
			continue
		}
		$section = New-PkgSection $rel (Split-PkgLines (Read-PkgText $first)) (Split-PkgLines (Read-PkgText $second))
		if ($section.Count -eq 0) { continue }
		$sections.Add($section)
		$totals["modules"]++
		$totals = Add-PkgCounts $totals (Get-PkgCounts $section)
	}

	$newOnly = New-Object System.Collections.Generic.List[string]
	foreach ($rel in $afterFiles) { if (-not $beforeSet.Contains($rel)) { $newOnly.Add($rel) } }
	$newArray = $newOnly.ToArray()
	[System.Array]::Sort($newArray, [System.StringComparer]::Ordinal)
	foreach ($rel in $newArray) {
		$mark = " (новый файл)"
		if ($rel.ToLowerInvariant().EndsWith(".bsl", [System.StringComparison]::Ordinal)) { $mark = " (новый модуль)" }
		$manual.Add([pscustomobject]@{ Mark = $mark; Path = $rel })
	}

	$goneOnly = New-Object System.Collections.Generic.List[string]
	foreach ($rel in $beforeFiles) { if (-not $afterSet.Contains($rel)) { $goneOnly.Add($rel) } }
	$goneArray = $goneOnly.ToArray()
	[System.Array]::Sort($goneArray, [System.StringComparer]::Ordinal)
	foreach ($rel in $goneArray) {
		$mark = " (удаленный файл)"
		if ($rel.ToLowerInvariant().EndsWith(".bsl", [System.StringComparison]::Ordinal)) { $mark = " (удаленный модуль)" }
		$manual.Add([pscustomobject]@{ Mark = $mark; Path = $rel })
	}

	return [pscustomobject]@{ Sections = $sections; Manual = $manual; Totals = $totals }
}

# Разбор двух одиночных файлов: модуль разбирается по методам, прочий файл идет в ручную правку.
# Заголовок раздела - путь в том виде, как его задал пользователь: относительного пути
# внутри выгрузки у одиночного файла нет.
function Compare-PkgFiles([string]$beforeArg, [string]$beforePath, [string]$afterPath) {
	$sections = New-Object System.Collections.Generic.List[psobject]
	$manual = New-Object System.Collections.Generic.List[psobject]
	$totals = New-PkgTotals
	if (-not (Test-PkgFilesDiffer $beforePath $afterPath)) {
		return [pscustomobject]@{ Sections = $sections; Manual = $manual; Totals = $totals }
	}
	if (-not $beforePath.ToLowerInvariant().EndsWith(".bsl", [System.StringComparison]::Ordinal) -or
		-not $afterPath.ToLowerInvariant().EndsWith(".bsl", [System.StringComparison]::Ordinal)) {
		$manual.Add([pscustomobject]@{ Mark = ""; Path = $beforeArg })
		return [pscustomobject]@{ Sections = $sections; Manual = $manual; Totals = $totals }
	}
	$section = New-PkgSection $beforeArg (Split-PkgLines (Read-PkgText $beforePath)) (Split-PkgLines (Read-PkgText $afterPath))
	if ($section.Count -eq 0) {
		return [pscustomobject]@{ Sections = $sections; Manual = $manual; Totals = $totals }
	}
	$sections.Add($section)
	$totals["modules"] = 1
	$totals = Add-PkgCounts $totals (Get-PkgCounts $section)
	return [pscustomobject]@{ Sections = $sections; Manual = $manual; Totals = $totals }
}

# --- Точка входа ---

# Запись пакета: UTF-8 без BOM, перевод строки LF - одинаково с портом Python.
function Write-PkgOut([string]$path, [string]$text) {
	$directory = [System.IO.Path]::GetDirectoryName($path)
	if ($directory -and -not (Test-Path -LiteralPath $directory)) {
		New-Item -ItemType Directory -Path $directory -Force | Out-Null
	}
	[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
}

# Путь к файлу или каталогу: абсолютный берется как есть, относительный - от текущего каталога.
function Resolve-PkgPath([string]$value) {
	if ([System.IO.Path]::IsPathRooted($value)) { return [System.IO.Path]::GetFullPath($value) }
	return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $value))
}

# Строки отчета в stdout после записи файла.
function Write-PkgSummary($totals, $manual) {
	if ($totals["modules"] -gt 0 -or $manual.Count -gt 0) {
		[Console]::Out.Write("[OK]    Модулей с правками: " + $totals["modules"] + ", методов изменено: " +
			$totals["changed"] + ", добавлено: " + $totals["added"] + ", удалено: " + $totals["removed"] +
			", правок вне методов: " + $totals["outside"] + "`n")
	}
	if ($manual.Count -gt 0) { [Console]::Out.Write("[WARN]  Файлов для правки вручную: " + $manual.Count + "`n") }
}

if (-not $Before -or -not $After) {
	[Console]::Error.Write("[ERROR] Укажите -Before и -After`n")
	exit 2
}

$beforePath = Resolve-PkgPath $Before
$afterPath = Resolve-PkgPath $After
foreach ($path in @($beforePath, $afterPath)) {
	if (-not (Test-Path -LiteralPath $path)) {
		[Console]::Error.Write("[ERROR] Путь не найден: " + $path + "`n")
		exit 1
	}
}
if ((Test-Path -LiteralPath $beforePath -PathType Container) -ne (Test-Path -LiteralPath $afterPath -PathType Container)) {
	[Console]::Error.Write("[ERROR] До и после должны быть либо двумя файлами, либо двумя каталогами`n")
	exit 1
}

if (Test-Path -LiteralPath $beforePath -PathType Container) {
	$result = Compare-PkgDirectories $beforePath $afterPath
} else {
	$result = Compare-PkgFiles $Before $beforePath $afterPath
}

$text = Format-PkgPackage $Before $After $result.Sections $result.Manual $result.Totals

if (-not $OutFile) {
	[Console]::Out.Write($text)
	exit 0
}

$outPath = Resolve-PkgPath $OutFile
try {
	Write-PkgOut $outPath $text
} catch {
	[Console]::Error.Write("[ERROR] Пакет не записан: " + $_.Exception.Message + "`n")
	exit 1
}
[Console]::Out.Write("[OK]    Пакет записан: " + $outPath + "`n")
Write-PkgSummary $result.Totals $result.Manual
exit 0
