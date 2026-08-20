# bsl-validate v1.0 - Check BSL module calls against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)][string]$ModulePath,
	[Parameter(Mandatory)][string]$IndexPath,
	[switch]$UnknownCalls,
	[switch]$Detailed,
	[int]$MaxErrors = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$bslIdent = '[A-Za-z_А-яЁё][A-Za-z0-9_А-яЁё]*'
$callRe = [regex]("\b($bslIdent)\s*\.\s*($bslIdent)\s*\(")
$varRe = [regex]("(?ims)^[ \t]*(?:Перем|Var)[ \t]+(.+?);")
$methodRe = [regex]("(?im)^[ \t]*(?:(?:Асинх|Async)[ \t]+)?(?:Процедура|Функция|Procedure|Function)[ \t]+$bslIdent[ \t]*\(")
# Присваивание бывает не только с начала строки: "Если Истина Тогда М = Новый Массив;".
$assignRe = [regex]("(?im)(?:^|;|\bТогда\b|\bThen\b|\bЦикл\b|\bDo\b)[ \t]*($bslIdent)[ \t]*=[^=]")
$foreachRe = [regex]("(?i)\b(?:Для[ \t]+Каждого|For[ \t]+Each)[ \t]+($bslIdent)\b")
$forRe = [regex]("(?i)\b(?:Для|For)[ \t]+($bslIdent)[ \t]*=")

# Глобальные коллекции и объекты платформы, к которым обращаются через точку. Список заведомо
# НЕПОЛНЫЙ - платформа их сотни. Поэтому проверка неизвестных имен и включается флагом: без него
# отсутствие имени в этом списке ни на что не влияет.
$knownGlobalRoots = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($g in @(
	"Справочники", "Catalogs", "Документы", "Documents", "Перечисления", "Enums",
	"РегистрыСведений", "InformationRegisters", "РегистрыНакопления", "AccumulationRegisters",
	"РегистрыБухгалтерии", "AccountingRegisters", "РегистрыРасчета", "CalculationRegisters",
	"ПланыСчетов", "ChartsOfAccounts", "ПланыВидовХарактеристик", "ChartsOfCharacteristicTypes",
	"ПланыВидовРасчета", "ChartsOfCalculationTypes", "ПланыОбмена", "ExchangePlans",
	"БизнесПроцессы", "BusinessProcesses", "Задачи", "Tasks", "Отчеты", "Reports",
	"Обработки", "DataProcessors", "Константы", "Constants",
	"ЖурналыДокументов", "DocumentJournals", "Последовательности", "Sequences",
	"КритерииОтбора", "FilterCriteria", "ХранилищаНастроек", "SettingsStorages",
	"WSСсылки", "WSReferences", "WebСервисы", "WebServices", "HTTPСервисы", "HTTPServices",
	"ОбщиеМодули", "CommonModules", "ПараметрыСеанса", "SessionParameters",
	"РегламентныеЗадания", "ScheduledJobs", "ОпределяемыеТипы", "DefinedTypes",
	"ФункциональныеОпции", "ВнешниеИсточникиДанных", "ExternalDataSources",
	"Метаданные", "Metadata", "ЭтотОбъект", "ThisObject",
	"БиблиотекаКартинок", "PictureLib", "БиблиотекаМакетов", "ЦветаСтиля", "StyleColors",
	"ШрифтыСтиля", "StyleFonts", "РамкиСтиля", "StyleBorders",
	"ФабрикаXDTO", "XDTOFactory", "СериализаторXDTO", "XDTOSerializer",
	"ПолнотекстовыйПоиск", "FullTextSearch",
	"ВнешниеОбработки", "ExternalDataProcessors", "ВнешниеОтчеты", "ExternalReports",
	"ПользователиИнформационнойБазы", "InfoBaseUsers",
	"ХранилищеСистемныхНастроек", "SystemSettingsStorage",
	"ХранилищеОбщихНастроек", "CommonSettingsStorage",
	"ИсторияДанных", "DataHistory", "ФункциональныеОпции", "FunctionalOptions",
	"КриптоМенеджер", "ОбменДаннымиСервер", "ДокументыHTTP",
	"ХранилищеВариантовОтчетов", "ReportsVariantsStorage",
	"ХранилищеНастроекДанныхФорм", "FormDataSettingsStorage",
	"ХранилищеПользовательскихНастроекДинамическихСписков", "DynamicListsUserSettingsStorage")) { [void]$knownGlobalRoots.Add($g) }

# Литерал ИЛИ комментарий: что началось раньше, то и поглощает второе. Закрывающая кавычка
# необязательна - незакрытый литерал гасит остаток файла.
$bslNoiseRe = [regex]'"(?:[^"]|"")*"?|//[^\n]*'

# Комментарии и строковые литералы гасятся ЗА ОДИН проход, с сохранением длины.
#
# Гасить их нужно: тексты запросов внутри строк полны точек, и без этого каждая вторая строка
# запроса стала бы вызовом. Но по очереди нельзя - неверно в обе стороны. Литералы первыми:
# нечетная кавычка в комментарии открывает мнимый литерал и съедает следом идущий код вместе
# с вызовами. Комментарии первыми: "TCP://" в литерале обрубит строку. Кто из двух начался
# раньше, решает чередование в самом образце: движок идет слева направо, и внутри уже
# начавшегося литерала двойной слеш ему не виден.
#
# Длина сохраняется, переводы строк внутри литерала тоже: проверка корня вызова смотрит на
# символ ПЕРЕД совпадением, а литерал в BSL занимает несколько строк.
function Remove-BslNoise([string]$text) {
	return $bslNoiseRe.Replace($text, {
		param($m)
		$s = $m.Value
		if ($s[0] -eq "/") { return [string]::new([char]" ", $s.Length) }
		$closed = $s.Length -ge 2 -and $s[$s.Length - 1] -eq '"'
		$inner = if ($closed) { $s.Substring(1, $s.Length - 2) } else { $s.Substring(1) }
		if ($inner.IndexOf("`n") -lt 0) {
			$body = [string]::new([char]" ", $inner.Length)
		} else {
			$chars = $inner.ToCharArray()
			for ($k = 0; $k -lt $chars.Length; $k++) { if ($chars[$k] -ne "`n") { $chars[$k] = " " } }
			$body = [string]::new($chars)
		}
		if ($closed) { return '"' + $body + '"' }
		return '"' + $body
	})
}

# Имена, объявленные в самом модуле: переменные, параметры методов, цели присваивания,
# переменные циклов. Косвенный вызов через переменную не должен давать ложной ошибки.
function Get-BslLocalNames([string]$text) {
	$names = New-Object 'System.Collections.Generic.HashSet[string]'
	foreach ($m in $varRe.Matches($text)) {
		foreach ($part in $m.Groups[1].Value.Split(",")) {
			$words = @($part.Trim() -split '\s+' | Where-Object { $_ })
			if ($words.Count -eq 0) { continue }
			if ($words[0].ToLower() -eq "экспорт" -or $words[0].ToLower() -eq "export") {
				[void]$names.Add($words[$words.Count - 1])
			} else {
				[void]$names.Add($words[0])
			}
		}
	}
	foreach ($m in $methodRe.Matches($text)) {
		$i = $m.Index + $m.Length
		$start = $i
		$depth = 1
		while ($i -lt $text.Length -and $depth -gt 0) {
			if ($text[$i] -eq "(") { $depth++ }
			elseif ($text[$i] -eq ")") { $depth-- }
			$i++
		}
		if ($i -le $start) { continue }
		$params = $text.Substring($start, $i - $start - 1)
		foreach ($part in $params.Split(",")) {
			$clean = ($part -split "=")[0].Trim()
			$words = @($clean -split '\s+' | Where-Object { $_ })
			if ($words.Count -gt 0) { [void]$names.Add($words[$words.Count - 1]) }
		}
	}
	foreach ($rx in @($assignRe, $foreachRe, $forRe)) {
		foreach ($m in $rx.Matches($text)) { [void]$names.Add($m.Groups[1].Value) }
	}
	return $names
}

# --- Вход ---

if (-not [System.IO.Path]::IsPathRooted($ModulePath)) { $ModulePath = Join-Path (Get-Location).Path $ModulePath }
if ([System.IO.Directory]::Exists($ModulePath)) {
	$modules = [System.IO.Directory]::GetFiles($ModulePath, "*.bsl", [System.IO.SearchOption]::AllDirectories)
	[Array]::Sort($modules, [StringComparer]::Ordinal)
} elseif ([System.IO.File]::Exists($ModulePath)) {
	$modules = @($ModulePath)
} else {
	[Console]::Error.WriteLine("Module path not found: " + $ModulePath)
	exit 1
}

if (-not [System.IO.Path]::IsPathRooted($IndexPath)) { $IndexPath = Join-Path (Get-Location).Path $IndexPath }
if (-not [System.IO.File]::Exists($IndexPath)) {
	[Console]::Error.WriteLine("Index file not found: " + $IndexPath)
	exit 1
}
$indexData = [System.IO.File]::ReadAllText($IndexPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
if ($indexData.format -ne 1) {
	[Console]::Error.WriteLine("Index format $($indexData.format) is not supported")
	exit 1
}
$commonModules = @{}
if ($indexData.commonModules) {
	foreach ($p in $indexData.commonModules.PSObject.Properties) { $commonModules[$p.Name] = $p.Value }
}
$lenient = ($indexData.kind -eq "extension")

$warnings = [System.Collections.ArrayList]::new()
function Add-BslWarn([string]$msg) {
	if ($script:warnings.Count -lt $MaxErrors) { [void]$script:warnings.Add($msg) }
}

$commonModulesLower = @{}
foreach ($k in $commonModules.Keys) { $commonModulesLower[$k.ToLower()] = $commonModules[$k] }
$knownGlobalsLower = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($g in $knownGlobalRoots) { [void]$knownGlobalsLower.Add($g.ToLower()) }
$missingModulesReported = New-Object 'System.Collections.Generic.HashSet[string]'

$checkedCalls = 0
$checkedModules = 0

foreach ($path in $modules) {
	try {
		$raw = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
	} catch {
		Add-BslWarn ("$([System.IO.Path]::GetFileName($path)): не прочитан ($($_.Exception.Message))")
		continue
	}
	$checkedModules++
	$text = Remove-BslNoise $raw
	$label = [System.IO.Path]::GetFileName([System.IO.Path]::GetDirectoryName([System.IO.Path]::GetDirectoryName($path)))
	if (-not $label) { $label = [System.IO.Path]::GetFileName($path) }
	# Общий модуль - единственное место, где список имен ЗАМКНУТ: контекста формы или объекта
	# у него нет, поэтому неизвестное имя действительно подозрительно.
	# Разделитель приводится к одному виду: путь могли передать и через прямой слеш.
	$normPath = $path.Replace("\", "/")
	$isCommon = $normPath.Contains("/CommonModules/")
	# Локальные имена нужны ВСЕГДА, а не только под флагом: параметр или переменная могут
	# называться как общий модуль, и тогда вызов идет через нее, а не через модуль.
	$localsLower = New-Object 'System.Collections.Generic.HashSet[string]'
	foreach ($n in (Get-BslLocalNames $text)) { [void]$localsLower.Add($n.ToLower()) }

	foreach ($m in $callRe.Matches($text)) {
		# Цепочка Справочники.Номенклатура.СоздатьЭлемент() дала бы ложный корень
		# "Номенклатура": образец ловит ЛЮБЫЕ два звена. Корнем считается только звено,
		# перед которым нет точки.
		$back = $text.Substring(0, $m.Index).TrimEnd()
		if ($back.EndsWith(".")) { continue }
		$root = $m.Groups[1].Value
		$method = $m.Groups[2].Value
		# BSL регистронезависим: общиеФункции.заполнено() - тот же вызов.
		$rootLower = $root.ToLower()
		if ($localsLower.Contains($rootLower)) { continue }
		if ($commonModulesLower.ContainsKey($rootLower)) {
			$checkedCalls++
			$info = $commonModulesLower[$rootLower]
			$found = $false
			foreach ($e in $info.exported) { if ([string]$e -and ([string]$e).ToLower() -eq $method.ToLower()) { $found = $true; break } }
			if ($found) { continue }
			if ($info.moduleMissing) {
				if ($missingModulesReported.Add($rootLower)) {
					Add-BslWarn "${label}: у общего модуля '$root' нет файла модуля, вызовы к нему не проверялись"
				}
				continue
			}
			if ($lenient) {
				Add-BslWarn "${label}: '$root.$method' - в этой выгрузке метод не экспортный и его нет в модуле; возможно, он в основной конфигурации"
			} else {
				Add-BslWarn "${label}: '$root.$method' - метод не экспортный или его нет в модуле"
			}
			continue
		}
		if (-not $UnknownCalls -or -not $isCommon) { continue }
		if ($knownGlobalsLower.Contains($rootLower)) { continue }
		$checkedCalls++
		if ($lenient) {
			Add-BslWarn "${label}: имя '$root' не объявлено в модуле и не является общим модулем этой выгрузки - возможно, оно в основной конфигурации"
		} else {
			Add-BslWarn "${label}: имя '$root' не объявлено в модуле и не является общим модулем"
		}
	}
}

$lines = [System.Collections.ArrayList]::new()
[void]$lines.Add("=== BSL check: $checkedModules module(s) ===")
[void]$lines.Add("")
foreach ($w in $warnings) { [void]$lines.Add("[WARN]  $w") }
if ($Detailed -or $warnings.Count -eq 0) {
	[void]$lines.Add("[OK]    Общих модулей в индексе: $($commonModules.Count)")
	[void]$lines.Add("[OK]    Вызовов проверено: $checkedCalls")
}
[void]$lines.Add("")
[void]$lines.Add("=== Result: $($warnings.Count) warnings ===")
Write-Host ($lines -join "`n")
exit 0
