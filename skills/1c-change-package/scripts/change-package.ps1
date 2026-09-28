# change-package v1.0 - Build a manual-change package for 1C modules edited outside the sources
# Source: https://github.com/Desko77/claude-code-skills-1c
# Строит пакет ручного внесения правок по двум версиям модулей 1С: блоки "Найти" и
# "Заменить целиком на" по методам, добавленные и удаленные методы, участки вне методов
# и список файлов для правки руками в Конфигураторе.
#
# Блок "Найти" обязан встречаться в старой версии ровно один раз и быть непрерывным куском
# модуля. Там, где такой фрагмент построить нельзя - разъехались участки вне методов,
# метод разобран неоднозначно, добавлять метод не к чему - пакет предлагает замену модуля
# целиком: один пункт с полным текстом обеих версий.
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
# Асинхронный метод объявляется словом Асинх (Async) перед ключевым словом метода.
$script:declaration = [regex]'^[ \t]*(?:(?:Асинх|Async)[ \t]+)?(Процедура|Procedure|Функция|Function)[ \t]+(\w+)[ \t]*\('
$script:functionWords = @("Функция", "Function")
$script:endProcWords = @("КонецПроцедуры", "EndProcedure")
$script:endFuncWords = @("КонецФункции", "EndFunction")

# Директивы препроцессора: ветка #Если охватывает метод и дает ему второе закрывающее слово.
$script:ifWords = @("#Если", "#If")
$script:endIfWords = @("#КонецЕсли", "#EndIf")

# Привязка участка вне методов: до первого метода, после последнего, после названного.
$script:startAnchor = "start"
$script:endAnchor = "end"

$script:counters = @("changed", "added", "removed", "outside", "replaced")

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

# Начало метода: примыкающие комментарии, директивы и ветка препроцессора над объявлением.
# Пустая строка между двумя примыкающими строками границу не рвет: иначе комментарий
# отрывался бы от метода из-за одной пустой строки и показывался отдельным пунктом.
function Get-PkgMethodStart($lines, [int]$decl) {
	$start = $decl
	$branches = 0
	while ($start -gt 0) {
		$previous = [string]$lines[$start - 1]
		if (Test-PkgAttachment $previous) { $start--; continue }
		if (Test-PkgOpenWord $previous $script:ifWords) { $branches++; $start--; continue }
		if ($previous.Trim().Length -eq 0) {
			$above = $start - 1
			while ($above -ge 0 -and ([string]$lines[$above]).Trim().Length -eq 0) { $above-- }
			if ($above -ge 0 -and (Test-PkgOpenWord ([string]$lines[$above]) $script:ifWords)) {
				$branches++
				$start = $above
				continue
			}
			if ($above -ge 0 -and (Test-PkgAttachment ([string]$lines[$above]))) {
				$start = $above
				continue
			}
		}
		break
	}
	return [pscustomobject]@{ Start = $start; Branches = $branches }
}

# Конец метода: закрывающее слово с учетом веток препроцессора. Ветки #Если/#Иначе дают
# методу два закрывающих слова, поэтому метод кончается строкой #КонецЕсли, закрывшей
# последнюю ветку. Resolved = $false - границы метода определить нельзя.
function Get-PkgMethodEnd($lines, [int]$decl, [int]$branches, [string[]]$endWords, [string[]]$otherWords) {
	$depth = $branches
	$inner = -1
	$index = $decl + 1
	while ($index -lt $lines.Count) {
		$line = [string]$lines[$index]
		if (Test-PkgOpenWord $line $script:ifWords) {
			$depth++
		} elseif (Test-PkgOpenWord $line $script:endIfWords) {
			$depth--
			if ($depth -lt 0) { return [pscustomobject]@{ End = $lines.Count - 1; Resolved = $false } }
			if ($depth -eq 0) {
				if ($inner -lt 0) { return [pscustomobject]@{ End = $lines.Count - 1; Resolved = $false } }
				return [pscustomobject]@{ End = $index; Resolved = $true }
			}
		} elseif (Test-PkgOpenWord $line $endWords) {
			if ($depth -eq 0) { return [pscustomobject]@{ End = $index; Resolved = $true } }
			$inner = $index
		} elseif (Test-PkgOpenWord $line $otherWords) {
			return [pscustomobject]@{ End = $lines.Count - 1; Resolved = $false }
		}
		$index++
	}
	return [pscustomobject]@{ End = $lines.Count - 1; Resolved = $false }
}

# Методы модуля в порядке следования: имя, границы и ключ сопоставления версий.
# Ключ - имя без учета регистра плюс номер повторения: одноименные методы в BSL
# невозможны, но битый модуль не должен из-за этого терять методы. Parsed = $false -
# хоть один метод разобрать не удалось.
function Get-PkgMethods($lines) {
	$methods = New-Object System.Collections.Generic.List[psobject]
	$seen = @{}
	$index = 0
	$parsed = $true
	while ($index -lt $lines.Count) {
		$match = $script:declaration.Match([string]$lines[$index])
		if (-not $match.Success) { $index++; continue }
		$keyword = $match.Groups[1].Value
		$name = $match.Groups[2].Value
		$startInfo = Get-PkgMethodStart $lines $index
		$endWords = $script:endProcWords
		$otherWords = $script:endFuncWords
		if (Test-PkgWord $keyword $script:functionWords) {
			$endWords = $script:endFuncWords
			$otherWords = $script:endProcWords
		}
		$endInfo = Get-PkgMethodEnd $lines $index $startInfo.Branches $endWords $otherWords
		if (-not $endInfo.Resolved) { $parsed = $false }
		$folded = $name.ToLowerInvariant()
		$repeat = 0
		if ($seen.ContainsKey($folded)) { $repeat = $seen[$folded] }
		$seen[$folded] = $repeat + 1
		$methods.Add([pscustomobject]@{
			Key = $folded + "|" + $repeat
			Name = $name
			Start = $startInfo.Start
			Decl = $index
			End = $endInfo.End
		})
		$index = $endInfo.End + 1
	}
	return [pscustomobject]@{ Methods = $methods.ToArray(); Parsed = $parsed }
}

# Текст метода целиком: директивы и комментарий перед объявлением, тело, закрывающее слово.
function Get-PkgMethodText($method, $lines) {
	return @($lines[$method.Start..$method.End])
}

# В модуле есть методы с повторяющимся именем: разбор по именам ненадежен.
function Test-PkgRepeats($methods) {
	$names = New-Object System.Collections.Generic.HashSet[string]
	$total = 0
	foreach ($method in $methods) {
		$total++
		[void]$names.Add($method.Key.Split("|")[0])
	}
	return ($names.Count -ne $total)
}

# Строки без пустых строк в конце: ровно то, что попадает в блок пакета.
function Format-PkgTrimBlank($lines) {
	$body = New-Object System.Collections.Generic.List[string]
	foreach ($line in $lines) { $body.Add([string]$line) }
	while ($body.Count -gt 0 -and $body[$body.Count - 1].Trim().Length -eq 0) { $body.RemoveAt($body.Count - 1) }
	return ,$body.ToArray()
}

# Сколько раз блок встречается в модуле: блок "Найти" обязан быть единственным.
function Get-PkgCountBlock($lines, $block) {
	$body = Format-PkgTrimBlank $block
	if ($body.Count -eq 0) { return 0 }
	$total = 0
	for ($start = 0; $start -le $lines.Count - $body.Count; $start++) {
		$same = $true
		for ($offset = 0; $offset -lt $body.Count; $offset++) {
			if ([string]$lines[$start + $offset] -cne [string]$body[$offset]) { $same = $false; break }
		}
		if ($same) { $total++ }
	}
	return $total
}

# Привязка участка вне методов: начало модуля, конец модуля или метод перед ним.
function Get-PkgRunAnchor($start, $methods) {
	$previous = $null
	$following = 0
	foreach ($method in $methods) {
		if ($method.End -lt $start) { $previous = $method }
		if ($method.Start -gt $start) { $following++ }
	}
	if ($null -eq $previous) { return [pscustomobject]@{ Key = $script:startAnchor; Label = "в начале модуля" } }
	if ($following -eq 0) { return [pscustomobject]@{ Key = $script:endAnchor; Label = "в конце модуля" } }
	return [pscustomobject]@{ Key = "after:" + $previous.Key; Label = "после метода " + $previous.Name }
}

# Смежные участки модуля вне методов, каждый со своей привязкой. Участок - непрерывный
# кусок модуля: ровно то, что человек найдет в Конфигураторе одним поиском. Пустые участки
# в список не попадают: перестановка пустых строк правкой не считается, а привязка такого
# участка меняется от добавления любого метода.
function Get-PkgOutsideRuns($lines, $methods) {
	$covered = New-Object System.Collections.Generic.HashSet[int]
	foreach ($method in $methods) {
		for ($i = $method.Start; $i -le $method.End; $i++) { [void]$covered.Add($i) }
	}
	$runs = New-Object System.Collections.Generic.List[psobject]
	$index = 0
	while ($index -lt $lines.Count) {
		if ($covered.Contains($index)) { $index++; continue }
		$first = $index
		while ($index -lt $lines.Count -and -not $covered.Contains($index)) { $index++ }
		$block = New-Object System.Collections.Generic.List[string]
		for ($i = $first; $i -lt $index; $i++) { $block.Add([string]$lines[$i]) }
		if ((Get-PkgNormalized $block.ToArray()).Count -eq 0) { continue }
		$anchor = Get-PkgRunAnchor $first $methods
		$runs.Add([pscustomobject]@{ Key = $anchor.Key; Label = $anchor.Label; Lines = $block.ToArray() })
	}
	return ,$runs.ToArray()
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

# Заголовок пункта добавления метода: привязка к методу, который есть в старой версии.
# Заголовок "в начало модуля" поставил бы метод выше переменных модуля и вне веток
# препроцессора, поэтому место задает соседний метод старой версии. Пустой возврат -
# привязать не к чему, модуль придется заменять целиком.
function Get-PkgAddedHead($afterMethods, [int]$position, $beforeKeys) {
	$name = $afterMethods[$position].Name
	for ($index = $position + 1; $index -lt $afterMethods.Count; $index++) {
		if ($beforeKeys.Contains($afterMethods[$index].Key)) {
			return "### Добавить метод " + $name + " перед методом " + $afterMethods[$index].Name
		}
	}
	for ($index = $position - 1; $index -ge 0; $index--) {
		if ($beforeKeys.Contains($afterMethods[$index].Key)) {
			return "### Добавить метод " + $name + " после метода " + $afterMethods[$index].Name
		}
	}
	return ""
}

# Пункты по участкам вне методов; $null - участки версий друг другу не отвечают.
function Get-PkgOutsideItems($beforeLines, $afterLines, $beforeMethods, $afterMethods) {
	$oldByKey = @{}
	foreach ($run in (Get-PkgOutsideRuns $beforeLines $beforeMethods)) {
		$oldByKey[$run.Key] = $run
	}
	$newRuns = Get-PkgOutsideRuns $afterLines $afterMethods
	$newRuns = @($newRuns)
	if ($oldByKey.Count -ne $newRuns.Count) { return $null }
	$items = New-Object System.Collections.Generic.List[string]
	foreach ($run in $newRuns) {
		if (-not $oldByKey.ContainsKey($run.Key)) { return $null }
		$old = $oldByKey[$run.Key]
		if (((Get-PkgNormalized $old.Lines) -join "`n") -ceq ((Get-PkgNormalized $run.Lines) -join "`n")) { continue }
		if ((Get-PkgCountBlock $beforeLines $old.Lines) -ne 1) { return $null }
		$items.AddRange([string[]](New-PkgChange ("### Изменить код вне методов " + $run.Label) $old.Lines $run.Lines))
	}
	return ,$items.ToArray()
}

# Сообщение о перестановке методов: блоков замены у перестановки нет.
function Get-PkgReorderNote {
	return ,([string[]](
		"### Порядок методов изменен",
		"",
		"Методы расположены в другом порядке, чем в старой версии: перенести целиком, без правки текста."))
}

# Порядок общих методов в новой версии отличается от старой.
function Test-PkgReordered($beforeMethods, $afterMethods) {
	$afterKeys = New-Object System.Collections.Generic.HashSet[string]
	foreach ($method in $afterMethods) { [void]$afterKeys.Add($method.Key) }
	$beforeKeys = New-Object System.Collections.Generic.HashSet[string]
	foreach ($method in $beforeMethods) { [void]$beforeKeys.Add($method.Key) }
	$oldOrder = New-Object System.Collections.Generic.List[string]
	foreach ($method in $beforeMethods) {
		if ($afterKeys.Contains($method.Key)) { $oldOrder.Add($method.Key) }
	}
	$newOrder = New-Object System.Collections.Generic.List[string]
	foreach ($method in $afterMethods) {
		if ($beforeKeys.Contains($method.Key)) { $newOrder.Add($method.Key) }
	}
	return (($oldOrder -join "`n") -cne ($newOrder -join "`n"))
}

# Пункты по одному модулю: измененные методы, добавленные, удаленные, участки вне методов.
# $null - однозначных фрагментов "Найти" не построить, нужна замена модуля целиком.
function Get-PkgSectionItems($beforeLines, $afterLines, $beforeMethods, $afterMethods) {
	$items = New-Object System.Collections.Generic.List[string]
	$beforeKeys = New-Object System.Collections.Generic.HashSet[string]
	foreach ($method in $beforeMethods) { [void]$beforeKeys.Add($method.Key) }
	$afterKeys = New-Object System.Collections.Generic.HashSet[string]
	foreach ($method in $afterMethods) { [void]$afterKeys.Add($method.Key) }
	$beforeByKey = @{}
	foreach ($method in $beforeMethods) { $beforeByKey[$method.Key] = $method }

	for ($position = 0; $position -lt $afterMethods.Count; $position++) {
		$method = $afterMethods[$position]
		if (-not $beforeByKey.ContainsKey($method.Key)) {
			$head = Get-PkgAddedHead $afterMethods $position $beforeKeys
			if (-not $head) { return $null }
			$items.AddRange([string[]](New-PkgSingle $head "Текст метода:" (Get-PkgMethodText $method $afterLines)))
			continue
		}
		$old = $beforeByKey[$method.Key]
		$oldText = Get-PkgMethodText $old $beforeLines
		$newText = Get-PkgMethodText $method $afterLines
		if (((Get-PkgNormalized $oldText) -join "`n") -ceq ((Get-PkgNormalized $newText) -join "`n")) { continue }
		if ((Get-PkgCountBlock $beforeLines $oldText) -ne 1) { return $null }
		$items.AddRange([string[]](New-PkgChange ("### Изменить метод " + $method.Name) $oldText $newText))
	}

	foreach ($method in $beforeMethods) {
		if ($afterKeys.Contains($method.Key)) { continue }
		$text = Get-PkgMethodText $method $beforeLines
		if ((Get-PkgCountBlock $beforeLines $text) -ne 1) { return $null }
		$items.AddRange([string[]](New-PkgSingle ("### Удалить метод " + $method.Name) "Удалить целиком:" $text))
	}

	$outside = Get-PkgOutsideItems $beforeLines $afterLines $beforeMethods $afterMethods
	if ($null -eq $outside) { return $null }
	$items.AddRange([string[]]($outside))

	if (Test-PkgReordered $beforeMethods $afterMethods) { $items.AddRange([string[]](Get-PkgReorderNote)) }
	return ,$items.ToArray()
}

# Пункт замены модуля целиком: один блок вместо разрозненных фрагментов.
function Get-PkgWholeModuleItems($beforeLines, $afterLines) {
	return ,(New-PkgChange "### Заменить модуль целиком" $beforeLines $afterLines)
}

# Счетчики пунктов в готовом разделе модуля.
function Get-PkgCounts($section) {
	$counts = @{}
	foreach ($name in $script:counters) { $counts[$name] = 0 }
	foreach ($line in $section) {
		if ($line.StartsWith("### Изменить метод", [System.StringComparison]::Ordinal)) { $counts["changed"]++ }
		elseif ($line.StartsWith("### Добавить метод", [System.StringComparison]::Ordinal)) { $counts["added"]++ }
		elseif ($line.StartsWith("### Удалить метод", [System.StringComparison]::Ordinal)) { $counts["removed"]++ }
		elseif ($line.StartsWith("### Изменить код вне методов", [System.StringComparison]::Ordinal)) { $counts["outside"]++ }
		elseif ($line.StartsWith("### Заменить модуль целиком", [System.StringComparison]::Ordinal)) { $counts["replaced"]++ }
	}
	return $counts
}

# Раздел модуля: разбор методов обеих версий и отрисовка пунктов одним вызовом, чтобы
# порядок пунктов не разъезжался с подсчетом.
function New-PkgSection([string]$rel, $beforeLines, $afterLines) {
	$before = Get-PkgMethods $beforeLines
	$after = Get-PkgMethods $afterLines
	$items = $null
	if ($before.Parsed -and $after.Parsed -and
		-not (Test-PkgRepeats $before.Methods) -and -not (Test-PkgRepeats $after.Methods)) {
		$items = Get-PkgSectionItems $beforeLines $afterLines $before.Methods $after.Methods
	}
	if ($null -eq $items) { $items = Get-PkgWholeModuleItems $beforeLines $afterLines }
	$items = @($items)
	if ($items.Count -eq 0) { return ,([string[]]@()) }
	$section = New-Object System.Collections.Generic.List[string]
	$head = "## " + $rel
	$title = Get-PkgModuleTitle $rel
	if ($title.Length -gt 0) { $head = $head + " - " + $title }
	$section.Add($head)
	$section.Add("")
	$section.AddRange([string[]]$items)
	return ,$section.ToArray()
}

# Нулевые счетчики пакета.
function New-PkgTotals {
	$totals = @{ modules = 0 }
	foreach ($name in $script:counters) { $totals[$name] = 0 }
	return $totals
}

# Прибавить счетчики одного модуля к счетчикам пакета.
function Add-PkgCounts($totals, $counts) {
	foreach ($name in $script:counters) { $totals[$name] = $totals[$name] + $counts[$name] }
	return $totals
}

# Хвост строки счетчиков: модулей, заменяемых целиком. Ноль в отчет не попадает.
function Format-PkgReplacedPart($totals) {
	if (-not $totals["replaced"]) { return "" }
	return ", замен целиком: " + $totals["replaced"]
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
		", правок вне методов: " + $totals["outside"] + (Format-PkgReplacedPart $totals))
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
			", правок вне методов: " + $totals["outside"] + (Format-PkgReplacedPart $totals) + "`n")
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
