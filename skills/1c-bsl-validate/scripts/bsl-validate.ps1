# bsl-validate v1.0 - Check BSL module calls against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)][string]$ModulePath,
	[string]$IndexPath = "",
	[switch]$UnknownCalls,
	[switch]$Detailed,
	[int]$MaxErrors = 30,
	[switch]$Catalog,
	[string]$RuleId = "",
	[switch]$Json
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$bslIdent = '[A-Za-z_А-я\u0401\u0451][A-Za-z0-9_А-я\u0401\u0451]*'
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

# --- Режим -Catalog: lint по каталогу дефектов ---
#
# Правила лежат в реестре catalog-rules.json рядом со скриптом: массив объектов id/title/kind.
# kind = regex (паттерн по строкам модуля; scope code - с погашенными литералами и
# комментариями, raw - по исходным строкам), query-regex (паттерн по строкам запросных
# литералов) и structure (многошаговая проверка по имени check). Логика зеркалит
# bsl-validate.py: одни и те же правила обязаны давать одинаковые находки на обоих портах,
# что сверяет гард tests/skills/check-lint-catalog.mjs.

$catalogRulesPath = Join-Path $PSScriptRoot "catalog-rules.json"

# Обработчики событий, внутри которых платформа уже держит транзакцию (карточка TXN-06).
$txnEventHandlers = @("ПередЗаписью", "ПриЗаписи", "ОбработкаПроведения")
# Имена вызовов с побочными эффектами, которым не место внутри транзакции (карточка
# TXN-10): диалоги с пользователем, сетевые обращения, работа с файлами. Сопоставление
# по целому идентификатору вызова: подстрока давала ложные находки на
# ПолучитьИмяВременногоФайла и ВводНаОсновании.
$txnSlowCallNames = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($n in @(
	"вопрос", "предупреждение", "открытьзначение", "сообщить", "уведомить",
	"отправитьзапроснаружу", "копироватьфайл", "переместитьфайл", "удалитьфайл",
	"найтифайлы")) { [void]$txnSlowCallNames.Add($n) }
# Слова обоснования законной блокировки без отбора: комментарий над вызовом (карточка TXN-08).
$txn08CommentMarkers = @("отбор", "пересчет", "все записи")

$catRe = @{
	try          = [regex]'\bПопытка\b'
	except       = [regex]'\bИсключение\b'
	endtry       = [regex]'\bКонецПопытки\b'
	raise        = [regex]'\bВызватьИсключение\b'
	begin_txn    = [regex]'\bНачатьТранзакцию\s*\('
	commit_txn   = [regex]'\bЗафиксироватьТранзакцию\s*\('
	rollback_txn = [regex]'\bОтменитьТранзакцию\s*\('
	endproc      = [regex]'\bКонецПроцедуры\b|\bКонецФункции\b'
	lock_new     = [regex]'\b(\w+)\s*=\s*Новый\s+БлокировкаДанных\b'
	lock_add     = [regex]'\b(\w+)\s*\.\s*Добавить\s*\(\s*"[^"]*"\s*\)'
	write_posting = [regex]'Записать\s*\([^)]*РежимЗаписиДокумента\s*\.\s*Проведение'
	const_read   = [regex]'\bКонстанты\s*\.\s*\w+\s*\.\s*Получить\s*\('
	loop_open    = [regex]'\bДля\s+Каждого\b|\bПока\b|\bДля\s+\w+\s*='
	loop_close   = [regex]'\bКонецЦикла\b'
	if_open      = [regex]'\bЕсли\b'
	elseif       = [regex]'\bИначеЕсли\b'
	else         = [regex]'\bИначе\b'
	endif        = [regex]'\bКонецЕсли\b'
	call         = [regex]'\b(\w+)\s*\('
}

# Кириллические ключевые слова в этих шаблонах не зависят от регистра: в BSL и языке
# запросов регистр незначим, поэтому у разборных регексов стоит (?i).
foreach ($k in @('try','except','endtry','raise','begin_txn','commit_txn','rollback_txn',
	'endproc','lock_new','lock_add','write_posting','const_read','loop_open','loop_close',
	'if_open','elseif','else','endif','call')) {
	$catRe[$k] = [regex]::new($catRe[$k].ToString(), [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}
$catRe['event_proc'] = [regex]::new("\b(?:Процедура|Функция)\s+(?:" + ($txnEventHandlers -join "|") + ")\s*\(",
	[System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

function Split-BslLines([string]$text) {
	return @($text -split "`n" | ForEach-Object { $_.TrimEnd("`r") })
}

# Запросные литералы файла: @(содержимое без кавычек, номер строки начала).
function Get-QueryLiterals([string]$text) {
	$out = @()
	foreach ($m in $bslNoiseRe.Matches($text)) {
		$s = $m.Value
		if ($s.Length -eq 0 -or $s[0] -ne '"') { continue }
		$closed = $s.Length -ge 2 -and $s[$s.Length - 1] -eq '"'
		$inner = if ($closed) { $s.Substring(1, $s.Length - 2) } else { $s.Substring(1) }
		if ($inner -match '(?i)\bВЫБРАТЬ\b') {
			$startLine = 1
			for ($p = 0; $p -lt $m.Index; $p++) { if ($text[$p] -eq "`n") { $startLine++ } }
			$out += ,@($inner, $startLine)
		}
	}
	return ,$out
}

# Секции Попытка..(Исключение|КонецПопытки): пары (первая строка, строка конца).
function Get-TrySections($q) {
	$sections = @()
	for ($i = 0; $i -lt $q.Count; $i++) {
		if (-not $catRe['try'].IsMatch($q[$i])) { continue }
		$end = $q.Count
		for ($j = $i + 1; $j -lt $q.Count; $j++) {
			$s = $q[$j].Trim()
			if ($catRe['except'].IsMatch($s) -or $catRe['endtry'].IsMatch($s)) { $end = $j; break }
		}
		$sections += ,@($i, $end)
	}
	return ,$sections
}

# Секции Исключение..КонецПопытки: пары (строка Исключение, строка за концом).
function Get-ExceptSections($q) {
	$sections = @()
	for ($i = 0; $i -lt $q.Count; $i++) {
		if (-not $catRe['except'].IsMatch($q[$i]) -or $catRe['raise'].IsMatch($q[$i])) { continue }
		$end = $q.Count
		for ($j = $i + 1; $j -lt $q.Count; $j++) {
			if ($catRe['endtry'].IsMatch($q[$j])) { $end = $j; break }
		}
		$sections += ,@($i, $end)
	}
	return ,$sections
}

# Первый непустой оператор в диапазоне строк либо -1.
function Get-FirstMeaningful($q, $lo, $hi) {
	for ($k = $lo; $k -lt $hi; $k++) { if ($q[$k].Trim()) { return $k } }
	return -1
}

# TXN-01: НачатьТранзакцию() внутри Попытка - репорт на строке вызова.
function Check-Txn01($ctx) {
	$out = @()
	$stack = New-Object System.Collections.ArrayList
	for ($i = 0; $i -lt $ctx.q.Count; $i++) {
		$s = $ctx.q[$i].Trim()
		if ($catRe['try'].IsMatch($s)) { [void]$stack.Add("try") }
		if ($catRe['except'].IsMatch($s) -and $stack.Count -gt 0 -and $stack[$stack.Count - 1] -eq "try") {
			$stack[$stack.Count - 1] = "except"
		}
		if ($catRe['begin_txn'].IsMatch($s) -and $stack.Count -gt 0 -and $stack[$stack.Count - 1] -eq "try") {
			$out += $i + 1
		}
		if ($catRe['endtry'].IsMatch($s) -and $stack.Count -gt 0) { $stack.RemoveAt($stack.Count - 1) }
	}
	return ,$out
}

# TXN-02: операторы между НачатьТранзакцию() и Попытка - репорт на первом из них.
function Check-Txn02($ctx) {
	$out = @()
	$q = $ctx.q
	for ($i = 0; $i -lt $q.Count; $i++) {
		if (-not $catRe['begin_txn'].IsMatch($q[$i])) { continue }
		$hit = -1
		for ($j = $i + 1; $j -lt $q.Count; $j++) {
			$s = $q[$j].Trim()
			if ($catRe['endproc'].IsMatch($s)) { break }
			if ($catRe['try'].IsMatch($s)) { $hit = $j; break }
		}
		if ($hit -lt 0) { continue }
		$k = Get-FirstMeaningful $q ($i + 1) $hit
		if ($k -ge 0) { $out += $k + 1 }
	}
	return ,$out
}

# TXN-03: операторы после ЗафиксироватьТранзакцию() в Попытка - репорт на первом.
function Check-Txn03($ctx) {
	$out = @()
	$q = $ctx.q
	foreach ($sec in (Get-TrySections $q)) {
		$i, $end = $sec
		for ($j = $i + 1; $j -lt $end; $j++) {
			if ($catRe['commit_txn'].IsMatch($q[$j])) {
				$k = Get-FirstMeaningful $q ($j + 1) $end
				if ($k -ge 0) { $out += $k + 1 }
				break
			}
		}
	}
	return ,$out
}

# TXN-04: операторы в Исключении до ОтменитьТранзакцию() - репорт на первом.
function Check-Txn04($ctx) {
	$out = @()
	$q = $ctx.q
	foreach ($sec in (Get-ExceptSections $q)) {
		$i, $end = $sec
		$body = ($q[$i..($end - 1)] -join "`n")
		if (-not $catRe['rollback_txn'].IsMatch($body)) { continue }
		$k = Get-FirstMeaningful $q ($i + 1) $end
		if ($k -ge 0 -and -not $catRe['rollback_txn'].IsMatch($q[$k])) { $out += $k + 1 }
	}
	return ,$out
}

# TXN-05: Исключение с ОтменитьТранзакцию, но без ВызватьИсключение - репорт на Исключение.
function Check-Txn05($ctx) {
	$out = @()
	$q = $ctx.q
	foreach ($sec in (Get-ExceptSections $q)) {
		$i, $end = $sec
		$body = ($q[$i..($end - 1)] -join "`n")
		if ($catRe['rollback_txn'].IsMatch($body) -and -not $catRe['raise'].IsMatch($body)) { $out += $i + 1 }
	}
	return ,$out
}

# TXN-06: НачатьТранзакцию() в ПередЗаписью/ПриЗаписи/ОбработкаПроведения.
function Check-Txn06($ctx) {
	$out = @()
	$q = $ctx.q
	$i = 0
	while ($i -lt $q.Count) {
		if (-not $catRe['event_proc'].IsMatch($q[$i])) { $i++; continue }
		$j = $i + 1
		while ($j -lt $q.Count -and -not $catRe['endproc'].IsMatch($q[$j])) {
			if ($catRe['begin_txn'].IsMatch($q[$j])) { $out += $j + 1 }
			$j++
		}
		$i = $j
	}
	return ,$out
}

# TXN-08: Добавить("таблица") без отбора у БлокировкаДанных, без обоснования.
#
# Законные формы карточки: блокировка всей таблицы с поясняющим комментарием в двух
# строках над вызовом и отбор по измерениям - УстановитьЗначение у элемента в
# следующих строках. Комментарий ищется по исходным строкам, остальное - по погашенным.
function Check-Txn08($ctx) {
	$q = $ctx.q
	$lockvars = New-Object 'System.Collections.Generic.HashSet[string]'
	foreach ($ln in $q) {
		$m = $catRe['lock_new'].Match($ln)
		if ($m.Success) { [void]$lockvars.Add($m.Groups[1].Value.ToLower()) }
	}
	if ($lockvars.Count -eq 0) { return ,@() }
	$setvalRe = [regex]'(?i)\.\s*УстановитьЗначение\s*\('
	$out = @()
	for ($i = 0; $i -lt $q.Count; $i++) {
		$m = $catRe['lock_add'].Match($q[$i])
		if (-not $m.Success -or -not $lockvars.Contains($m.Groups[1].Value.ToLower())) { continue }
		$suppressed = $false
		foreach ($k in @(($i - 1), ($i - 2))) {
			if ($k -lt 0) { continue }
			$src = $ctx.raw[$k].ToLower()
			if ($src.Contains("//")) {
				foreach ($mk in $txn08CommentMarkers) {
					if ($src.Contains($mk)) { $suppressed = $true; break }
				}
				if ($suppressed) { break }
			}
		}
		if (-not $suppressed) {
			$hi = [Math]::Min($i + 4, $q.Count)
			for ($k = $i + 1; $k -lt $hi; $k++) {
				if ($setvalRe.IsMatch($q[$k])) { $suppressed = $true; break }
			}
		}
		if (-not $suppressed) { $out += $i + 1 }
	}
	return ,$out
}

# TXN-10: диалоги, сеть и файлы между НачатьТранзакцию() и фиксацией/отменой.
# Вызов сопоставляется со списком имен целиком ($txnSlowCallNames), не подстрокой.
function Check-Txn10($ctx) {
	$out = @()
	$q = $ctx.q
	$i = 0
	while ($i -lt $q.Count) {
		if (-not $catRe['begin_txn'].IsMatch($q[$i])) { $i++; continue }
		$j = $i + 1
		while ($j -lt $q.Count -and -not ($catRe['commit_txn'].IsMatch($q[$j]) -or $catRe['rollback_txn'].IsMatch($q[$j]))) {
			foreach ($m in $catRe['call'].Matches($q[$j])) {
				if ($txnSlowCallNames.Contains($m.Groups[1].Value.ToLower())) { $out += $j + 1; break }
			}
			$j++
		}
		$i = $j
	}
	return ,$out
}

# TXN-11: явная транзакция вокруг Записать(РежимЗаписиДокумента.Проведение).
function Check-Txn11($ctx) {
	$out = @()
	$q = $ctx.q
	$i = 0
	while ($i -lt $q.Count) {
		if (-not $catRe['begin_txn'].IsMatch($q[$i])) { $i++; continue }
		$j = $i + 1
		$posting = $false
		while ($j -lt $q.Count -and -not ($catRe['commit_txn'].IsMatch($q[$j]) -or $catRe['rollback_txn'].IsMatch($q[$j]))) {
			if ($catRe['write_posting'].IsMatch($q[$j])) { $posting = $true }
			$j++
		}
		if ($posting) { $out += $i + 1 }
		if ($j -gt $i) { $i = $j } else { $i++ }
	}
	return ,$out
}

# PERF-05: чтение Константы.<Имя>.Получить() внутри цикла.
function Check-Perf05($ctx) {
	$out = @()
	$depth = 0
	for ($i = 0; $i -lt $ctx.q.Count; $i++) {
		$depth += $catRe['loop_open'].Matches($ctx.q[$i]).Count
		if ($depth -gt 0 -and $catRe['const_read'].IsMatch($ctx.q[$i])) { $out += $i + 1 }
		$depth -= $catRe['loop_close'].Matches($ctx.q[$i]).Count
		if ($depth -lt 0) { $depth = 0 }
	}
	return ,$out
}

# MODEL-14: Если-ИначеЕсли из трех и более ветвей без Иначе - репорт на КонецЕсли.
function Check-Model14($ctx) {
	$out = @()
	$stack = New-Object System.Collections.ArrayList
	for ($i = 0; $i -lt $ctx.q.Count; $i++) {
		$ln = $ctx.q[$i]
		if ($catRe['if_open'].IsMatch($ln)) { [void]$stack.Add(@{elseif = 0; else = $false }) }
		if ($catRe['elseif'].IsMatch($ln) -and $stack.Count -gt 0) {
			$stack[$stack.Count - 1].elseif++
		}
		if ($catRe['else'].IsMatch($ln) -and $stack.Count -gt 0) {
			$stack[$stack.Count - 1].else = $true
		}
		if ($catRe['endif'].IsMatch($ln) -and $stack.Count -gt 0) {
			$top = $stack[$stack.Count - 1]
			$stack.RemoveAt($stack.Count - 1)
			if ($top.elseif -ge 2 -and -not $top.else) { $out += $i + 1 }
		}
	}
	return ,$out
}

# Пакеты запроса по ';': список сегментов @(номер строки, текст).
function Get-QueryPacks($inner, $start) {
	$packs = New-Object System.Collections.ArrayList
	$cur = New-Object System.Collections.ArrayList
	$lines = Split-BslLines $inner
	for ($k = 0; $k -lt $lines.Count; $k++) {
		[void]$cur.Add(@(($start + $k), $lines[$k]))
		if ($lines[$k].Contains(";")) {
			[void]$packs.Add($cur)
			$cur = New-Object System.Collections.ArrayList
		}
	}
	if ($cur.Count -gt 0) { [void]$packs.Add($cur) }
	return ,$packs
}

# QUERY-18: ПЕРВЫЕ без УПОРЯДОЧИТЬ ПО в пакете - репорт на строках ПЕРВЫЕ.
function Check-Query18($ctx) {
	$out = @()
	foreach ($lit in $ctx.literals) {
		$inner, $start = $lit
		foreach ($pack in (Get-QueryPacks $inner $start)) {
			$text = (($pack | ForEach-Object { $_[1] }) -join "`n")
			if ($text -notmatch '(?i)\bПЕРВЫЕ\b') { continue }
			if ($text -match '(?i)\bУПОРЯДОЧИТЬ\b') { continue }
			foreach ($pair in $pack) {
				if ($pair[1] -match '(?i)\bПЕРВЫЕ\b') { $out += $pair[0] }
			}
		}
	}
	return ,$out
}

# QUERY-08: ИЛИ по полям таблицы внутри секции ГДЕ.
function Check-Query08($ctx) {
	$out = @()
	$sectionRe = [regex]'(?i)\b(?:УПОРЯДОЧИТЬ|СГРУППИРОВАТЬ|ИМЕЮЩИЕ|ОБЪЕДИНИТЬ|ИТОГИ)\b|;'
	$whereRe = [regex]'(?i)(?:^|\|)\s*ГДЕ\b'
	$orRe = [regex]'(?i)(?:^|\|)\s*ИЛИ\s+\w+\.'
	foreach ($lit in $ctx.literals) {
		$inner, $start = $lit
		$inWhere = $false
		$lines = Split-BslLines $inner
		for ($k = 0; $k -lt $lines.Count; $k++) {
			$ln = $lines[$k]
			if ($whereRe.IsMatch($ln)) { $inWhere = $true; continue }
			if (-not $inWhere) { continue }
			if ($sectionRe.IsMatch($ln)) { $inWhere = $false; continue }
			if ($orRe.IsMatch($ln)) { $out += $start + $k }
		}
	}
	return ,$out
}

# QUERY-13: Колонки.Добавить("Имя") без типа у переменной-параметра запроса.
#
# Колонка ловится только когда ее имя фигурирует в тексте запроса модуля: нестроковые
# колонки без типа соединение не ломают, и чистый признак - сама колонка в запросе.
function Check-Query13($ctx) {
	$paramVars = New-Object 'System.Collections.Generic.HashSet[string]'
	$paramRe = [regex]'(?i)УстановитьПараметр\s*\(\s*"[^"]*"\s*,\s*(\w+)'
	foreach ($ln in $ctx.raw) {
		$m = $paramRe.Match($ln)
		if ($m.Success) { [void]$paramVars.Add($m.Groups[1].Value.ToLower()) }
	}
	if ($paramVars.Count -eq 0) { return ,@() }
	$words = New-Object 'System.Collections.Generic.HashSet[string]'
	foreach ($lit in $ctx.literals) {
		foreach ($w in [regex]::Matches($lit[0], '\w+')) { [void]$words.Add($w.Value.ToLower()) }
	}
	$addRe = [regex]'(?i)\b(\w+)\s*\.\s*Колонки\s*\.\s*Добавить\s*\(\s*"([^"]+)"\s*\)'
	$out = @()
	for ($i = 0; $i -lt $ctx.raw.Count; $i++) {
		foreach ($m in $addRe.Matches($ctx.raw[$i])) {
			if ($paramVars.Contains($m.Groups[1].Value.ToLower()) -and $words.Contains($m.Groups[2].Value.ToLower())) {
				$out += $i + 1
				break
			}
		}
	}
	return ,$out
}

# Подзапросы (ВЫБРАТЬ...) со ссылкой на псевдоним внешнего запроса: пары
# (позиция открытия, массив позиций внешних ссылок внутри). Псевдонимы внешнего
# запроса - КАК <Имя> вне скобок подзапроса; ссылка - <псевдоним>. внутри.
# Некоррелированный подзапрос (законная форма QUERY-01) пары не дает.
function Get-CorrelatedSubqueries([string]$inner) {
	$aliasRe = [regex]'(?i)\bКАК\s+(\w+)'
	# Подзапрос открывается скобкой, за которой до ВЫБРАТЬ возможны переводы строк и
	# линии продолжения | - многострочный подзапрос в литерале запроса.
	$subRe = [regex]'(?i)\(\s*(?:\|\s*)*ВЫБРАТЬ'
	$refRe = [regex]'\b(\w+)\s*\.'
	$aliases = @()
	foreach ($m in $aliasRe.Matches($inner)) { $aliases += ,@($m.Groups[1].Value.ToLower(), $m.Index) }
	$result = @()
	foreach ($m in $subRe.Matches($inner)) {
		$openPos = $m.Index
		$depth = 0
		$closePos = $inner.Length
		for ($p = $openPos; $p -lt $inner.Length; $p++) {
			if ($inner[$p] -eq "(") { $depth++ }
			elseif ($inner[$p] -eq ")") {
				$depth--
				if ($depth -eq 0) { $closePos = $p; break }
			}
		}
		$outer = New-Object 'System.Collections.Generic.HashSet[string]'
		foreach ($a in $aliases) {
			if ($a[1] -lt $openPos -or $a[1] -ge $closePos) { [void]$outer.Add($a[0]) }
		}
		if ($outer.Count -eq 0) { continue }
		$used = @()
		$sub = $inner.Substring($openPos + 1, $closePos - $openPos - 1)
		foreach ($um in $refRe.Matches($sub)) {
			if ($outer.Contains($um.Groups[1].Value.ToLower())) { $used += ($openPos + 1 + $um.Index) }
		}
		if ($used.Count -gt 0) { $result += ,@($openPos, $used) }
	}
	return ,$result
}

# Позиция первого вхождения слова вне скобок либо -1.
function Get-TopLevelKeywordPos([string]$inner, [string]$word) {
	foreach ($m in [regex]::Matches($inner, '(?i)\b' + $word + '\b')) {
		$before = $inner.Substring(0, $m.Index)
		if (($before.Split("(").Count - 1) -eq ($before.Split(")").Count - 1)) { return $m.Index }
	}
	return -1
}

# Строки коррелированных подзапросов: открытие и внешние ссылки. $fieldsOnly - только
# подзапросы секции полей (до первого ИЗ верхнего уровня, карточка QUERY-01), иначе
# все подзапросы (карточка QUERY-14).
function Get-CorrelatedLines($ctx, [bool]$fieldsOnly) {
	$out = @()
	foreach ($lit in $ctx.literals) {
		$inner, $start = $lit
		$lineStarts = @(0)
		for ($p = 0; $p -lt $inner.Length; $p++) { if ($inner[$p] -eq "`n") { $lineStarts += $p + 1 } }
		$iz = Get-TopLevelKeywordPos $inner "ИЗ"
		foreach ($pair in (Get-CorrelatedSubqueries $inner)) {
			$openPos = $pair[0]
			if ($fieldsOnly -and $iz -ge 0 -and $openPos -gt $iz) { continue }
			foreach ($pos in @($openPos) + $pair[1]) {
				$lo = 0
				for ($x = 0; $x -lt $lineStarts.Count; $x++) { if ($lineStarts[$x] -le $pos) { $lo = $x } }
				$out += $start + $lo
			}
		}
	}
	return ,(@($out | Sort-Object -Unique))
}

# QUERY-01: коррелированный подзапрос в списке полей - репорт на открытии и ссылках.
# В ГДЕ коррелированный подзапрос - карточка QUERY-14, здесь он не репортится.
function Check-Query01($ctx) {
	return ,(Get-CorrelatedLines $ctx $true)
}

# QUERY-14: подзапрос в скобках использует псевдоним внешнего запроса.
# Репорт на строке открытия подзапроса и на строках внешних ссылок внутри него.
function Check-Query14($ctx) {
	return ,(Get-CorrelatedLines $ctx $false)
}

# QUERY-15: ВТ помещена без ИНДЕКСИРОВАТЬ ПО и соединяется в следующем пакете.
function Check-Query15($ctx) {
	$out = @()
	foreach ($lit in $ctx.literals) {
		$inner, $start = $lit
		$packs = Get-QueryPacks $inner $start
		if ($packs.Count -lt 2) { continue }
		for ($pi = 0; $pi -lt $packs.Count; $pi++) {
			$pack = $packs[$pi]
			$text = (($pack | ForEach-Object { $_[1] }) -join "`n")
			$m = [regex]::Match($text, '(?i)\bПОМЕСТИТЬ\s+(\w+)')
			if (-not $m.Success) { continue }
			if ($text -match '(?i)\bИНДЕКСИРОВАТЬ\b') { continue }
			$vt = $m.Groups[1].Value
			$restParts = @()
			for ($pj = $pi + 1; $pj -lt $packs.Count; $pj++) {
				foreach ($pair in $packs[$pj]) { $restParts += $pair[1] }
			}
			$rest = $restParts -join "`n"
			if ($rest -match ('(?i)\bСОЕДИНЕНИЕ\s+' + [regex]::Escape($vt) + '\b')) {
				foreach ($pair in $pack) {
					if ($pair[1] -match '(?i)\bПОМЕСТИТЬ\b') { $out += $pair[0]; break }
				}
			}
		}
	}
	return ,$out
}

# SEC-01: значение конкатенацией в литерал текста запроса вместо параметра.
# Литералы запроса многострочны, поэтому признак ищется по файлу целиком: литерал
# с ключевым словом запроса закрывается кавычкой, за которой сразу идет + и идентификатор.
# Репорт на строке закрытия литерала.
function Check-Sec01($ctx) {
	$kw = [regex]::new('\b(?:ВЫБРАТЬ|ГДЕ|ИЗ|ПОДОБНО|СОЕДИНЕНИЕ|УПОРЯДОЧИТЬ|СГРУППИРОВАТЬ|ПОМЕСТИТЬ)\b',
		[System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
	$concat = [regex]'^[ \t]*\+[ \t]*\w'
	$out = @()
	$text = $ctx.text
	foreach ($m in $bslNoiseRe.Matches($text)) {
		$s = $m.Value
		if ($s.Length -eq 0 -or $s[0] -ne '"' -or $s.Length -lt 2 -or $s[$s.Length - 1] -ne '"') { continue }
		if (-not $kw.IsMatch($s.Substring(1, $s.Length - 2))) { continue }
		$tailLen = [Math]::Min(60, $text.Length - $m.Index - $s.Length)
		if ($tailLen -gt 0) {
			$tail = $text.Substring($m.Index + $s.Length, $tailLen)
			if ($concat.IsMatch($tail)) {
				$nl = 1
				for ($p = 0; $p -lt ($m.Index + $s.Length); $p++) { if ($text[$p] -eq "`n") { $nl++ } }
				$out += $nl
			}
		}
	}
	return ,$out
}

# MODEL-18: пустой блок Исключение - репорт на строке Исключения.
# Пустота определяется по исходному тексту: блок из одного поясняющего комментария
# карточкой разрешен и пустым не считается, а после Remove-BslNoise он выглядит пустым.
function Check-Model18($ctx) {
	$out = @()
	$q = $ctx.q
	for ($i = 0; $i -lt $q.Count; $i++) {
		if (-not $catRe["except"].IsMatch($q[$i])) { continue }
		if ($catRe["raise"].IsMatch($q[$i])) { continue }
		$end = $q.Count
		for ($j = $i + 1; $j -lt $q.Count; $j++) {
			if ($catRe["endtry"].IsMatch($q[$j])) { $end = $j; break }
		}
		$empty = $true
		for ($j = $i + 1; $j -lt $end; $j++) {
			if ($ctx.raw[$j].Trim().Length -gt 0) { $empty = $false; break }
		}
		if ($empty) { $out += $i + 1 }
	}
	return ,$out
}

# MODEL-22: удаление элемента коллекции внутри обхода этой же коллекции - репорт
# на строке вызова Удалить. Конец тела ищется по счетчику вложенности Для/Пока -
# КонецЦикла, иначе вложенный цикл обрезает тело. Коллекция захватывается целиком
# вместе с путем через точку: Объект.Строки.Удалить находится для обхода
# Из Объект.Строки.
function Check-Model22($ctx) {
	$out = @()
	$text = $ctx.q -join "`n"
	$head = [regex]::new("\bДля\s+Каждого\s+(\w+)\s+Из\s+([\w.]+)\b",
		[System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
	$kw = [regex]::new("\b(?:Для|Пока|КонецЦикла)\b",
		[System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
	foreach ($m in $head.Matches($text)) {
		$item = $m.Groups[1].Value
		$coll = $m.Groups[2].Value
		$lineNo = 1
		foreach ($ch in $text.Substring(0, $m.Index).ToCharArray()) {
			if ($ch -eq "`n") { $lineNo++ }
		}
		$rest = $text.Substring($m.Index + $m.Length)
		$scopeText = $rest
		$depth = 0
		foreach ($km in $kw.Matches($rest)) {
			if ($km.Value.ToLower() -ne "конеццикла") { $depth++ }
			elseif ($depth -eq 0) { $scopeText = $rest.Substring(0, $km.Index); break }
			else { $depth-- }
		}
		$parts = @($coll.Split('.') | ForEach-Object { [regex]::Escape($_) })
		$pat = '\b' + ($parts -join '\s*\.\s*') + '\s*\.\s*Удалить\s*\(\s*' + [regex]::Escape($item) + '\s*\)'
		$del = [regex]::new($pat, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
		$dm = $del.Match($scopeText)
		if ($dm.Success) {
			$nl = 0
			foreach ($ch in $scopeText.Substring(0, $dm.Index).ToCharArray()) {
				if ($ch -eq "`n") { $nl++ }
			}
			$out += $lineNo + $nl
		}
	}
	return ,(@($out | Sort-Object -Unique))
}

$structureChecks = @{
	"model-14"  = ${function:Check-Model14}
	"model-18"  = ${function:Check-Model18}
	"model-22"  = ${function:Check-Model22}
	"perf-05"   = ${function:Check-Perf05}
	"query-01"  = ${function:Check-Query01}
	"query-08"  = ${function:Check-Query08}
	"query-13"  = ${function:Check-Query13}
	"query-14"  = ${function:Check-Query14}
	"query-15"  = ${function:Check-Query15}
	"query-18"  = ${function:Check-Query18}
	"sec-01"    = ${function:Check-Sec01}
	"txn-01"    = ${function:Check-Txn01}
	"txn-02"    = ${function:Check-Txn02}
	"txn-03"    = ${function:Check-Txn03}
	"txn-04"    = ${function:Check-Txn04}
	"txn-05"    = ${function:Check-Txn05}
	"txn-06"    = ${function:Check-Txn06}
	"txn-08"    = ${function:Check-Txn08}
	"txn-10"    = ${function:Check-Txn10}
	"txn-11"    = ${function:Check-Txn11}
}

function ConvertTo-FlatJsonString([string]$s) {
	$sb = New-Object System.Text.StringBuilder
	[void]$sb.Append('"')
	foreach ($ch in $s.ToCharArray()) {
		$code = [int]$ch
		if ($ch -eq '"') { [void]$sb.Append('\"') }
		elseif ($ch -eq '\') { [void]$sb.Append('\\') }
		elseif ($code -lt 32) { [void]$sb.AppendFormat('\u{0:x4}', $code) }
		else { [void]$sb.Append($ch) }
	}
	[void]$sb.Append('"')
	return $sb.ToString()
}

function Invoke-CatalogLint {
	$rules = $null
	try {
		$rules = [System.IO.File]::ReadAllText($catalogRulesPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
	} catch {
		[Console]::Error.WriteLine("Catalog rules registry not readable: $catalogRulesPath ($($_.Exception.Message))")
		return 2
	}
	if ($null -eq $rules -or $rules.Count -eq 0) {
		[Console]::Error.WriteLine("Catalog rules registry must be a non-empty array")
		return 2
	}
	$rulesById = @{}
	foreach ($rule in $rules) {
		if (-not $rule.id -or -not $rule.kind) {
			[Console]::Error.WriteLine("Catalog rule without id or kind")
			return 2
		}
		if ($rulesById.ContainsKey($rule.id)) {
			[Console]::Error.WriteLine("Catalog rule $($rule.id) listed twice")
			return 2
		}
		if ($rule.kind -eq "structure") {
			if (-not $structureChecks.ContainsKey($rule.check)) {
				[Console]::Error.WriteLine("Catalog rule $($rule.id): unknown check $($rule.check)")
				return 2
			}
		} elseif ($rule.kind -in @("regex", "query-regex")) {
			if (-not $rule.pattern) {
				[Console]::Error.WriteLine("Catalog rule $($rule.id): regex rule without pattern")
				return 2
			}
			try { [void][regex]::new($rule.pattern) } catch {
				[Console]::Error.WriteLine("Catalog rule $($rule.id): pattern not compiled ($($_.Exception.Message))")
				return 2
			}
			if ($rule.kind -eq "regex" -and $rule.scope -notin @("code", "raw")) {
				[Console]::Error.WriteLine("Catalog rule $($rule.id): scope must be code or raw")
				return 2
			}
		} else {
			[Console]::Error.WriteLine("Catalog rule $($rule.id): unknown kind $($rule.kind)")
			return 2
		}
		$rulesById[$rule.id] = $rule
	}
	$ruleIds = @($rulesById.Keys | Sort-Object)
	if ($RuleId -ne "") {
		if (-not $rulesById.ContainsKey($RuleId)) {
			[Console]::Error.WriteLine("Rule '$RuleId' is not in the catalog registry")
			return 2
		}
		$ruleIds = @($RuleId)
	}

	if (-not [System.IO.Path]::IsPathRooted($ModulePath)) { $ModulePath = Join-Path (Get-Location).Path $ModulePath }
	$root = $ModulePath
	if ([System.IO.Directory]::Exists($ModulePath)) {
		$modules = [System.IO.Directory]::GetFiles($ModulePath, "*.bsl", [System.IO.SearchOption]::AllDirectories)
		[Array]::Sort($modules, [StringComparer]::Ordinal)
	} elseif ([System.IO.File]::Exists($ModulePath)) {
		$modules = @($ModulePath)
	} else {
		[Console]::Error.WriteLine("Module path not found: " + $ModulePath)
		return 2
	}

	$findings = New-Object System.Collections.ArrayList
	$sha = [System.Security.Cryptography.SHA256]::Create()
	$enc = [System.Text.Encoding]::UTF8
	$oneNul = [byte[]]@(0)
	foreach ($path in $modules) {
		$rel = if ([System.IO.Directory]::Exists($root)) {
			$full = [System.IO.Path]::GetFullPath($path)
			$r = $full.Substring([System.IO.Path]::GetFullPath($root).Length).TrimStart('\', '/') -replace '\\', '/'
			if ($r -eq "") { [System.IO.Path]::GetFileName($path) } else { $r }
		} else {
			[System.IO.Path]::GetFileName($path)
		}
		$relBytes = $enc.GetBytes($rel)
		[void]$sha.TransformBlock($relBytes, 0, $relBytes.Length, $null, 0)
		[void]$sha.TransformBlock($oneNul, 0, 1, $null, 0)
		[void]$sha.TransformBlock([System.IO.File]::ReadAllBytes($path), 0, (Get-Item -LiteralPath $path).Length, $null, 0)
		[void]$sha.TransformBlock($oneNul, 0, 1, $null, 0)
		$raw = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
		$quiet = Remove-BslNoise $raw
		$q = Split-BslLines $quiet
		$src = Split-BslLines $raw
		$literals = Get-QueryLiterals $raw
		$ctx = @{ q = $q; raw = $src; literals = $literals; text = $raw }
		$found = New-Object 'System.Collections.Generic.HashSet[string]'
		$nul = [char]0
		foreach ($rid in $ruleIds) {
			$rule = $rulesById[$rid]
			if ($rule.kind -eq "regex") {
				$rx = [regex]::new($rule.pattern)
				$target = if ($rule.scope -eq "raw") { $src } else { $q }
				for ($i = 0; $i -lt $target.Count; $i++) {
					if ($target[$i] -and $rx.IsMatch($target[$i])) {
						[void]$found.Add($rid + $nul + ($i + 1))
					}
				}
				continue
			}
			if ($rule.kind -eq "query-regex") {
				# Матч по тексту литерала целиком: скобка и ВЫБРАТЬ на разных строках
				# построчному поиску не видны. Номер строки - по смещению совпадения.
				$rx = [regex]::new($rule.pattern)
				foreach ($lit in $literals) {
					$inner, $start = $lit
					foreach ($m in $rx.Matches($inner)) {
						$nl = 0
						for ($p = 0; $p -lt $m.Index; $p++) { if ($inner[$p] -eq "`n") { $nl++ } }
						[void]$found.Add($rid + $nul + ($start + $nl))
					}
				}
				continue
			}
			$fn = $structureChecks[$rule.check]
			if ($null -eq $fn) { continue }
			foreach ($line in (& $fn $ctx)) {
				if ($line -is [int] -or "$line" -match '^\d+$') { [void]$found.Add($rid + $nul + $line) }
			}
		}
		foreach ($key in ($found | Sort-Object)) {
			$sep = $key.IndexOf($nul)
			$rid = $key.Substring(0, $sep)
			$lineNo = [int]$key.Substring($sep + 1)
			$fragment = ""
			if ($lineNo -le $src.Count) { $fragment = $src[$lineNo - 1].Trim() }
			if ($fragment.Length -gt 100) { $fragment = $fragment.Substring(0, 100) }
			[void]$findings.Add([pscustomobject]@{ id = $rid; file = $rel; line = $lineNo; match = $fragment })
		}
	}

	# Сортировка находок: файл, строка, идентификатор - тот же порядок, что в Python-порте.
	$sorted = @($findings | Sort-Object @{Expression = { $_.file }}, @{Expression = { $_.line }}, @{Expression = { $_.id }})
	$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
	$hex = ($sha.Hash | ForEach-Object { $_.ToString("x2") }) -join ""
	$sha.Dispose()
	$inputHash = $hex
	$status = if ($sorted.Count -gt 0) { "findings" } else { "pass" }

	# ids - карточки-находки (не проверенные правила): на чистом файле список пуст.
	$foundIds = @($sorted | ForEach-Object { $_.id } | Sort-Object -Unique)
	$jsonIds = ($foundIds | ForEach-Object { ConvertTo-FlatJsonString $_ }) -join ","
	$jsonFindings = ($sorted | ForEach-Object {
		'{' + '"id":' + (ConvertTo-FlatJsonString $_.id) + ',"file":' + (ConvertTo-FlatJsonString $_.file) +
		',"line":' + $_.line + ',"match":' + (ConvertTo-FlatJsonString $_.match) + '}'
	}) -join ","
	$jsonPayload = '{"check":"bsl_validate@configurator","ids":[' + $jsonIds + '],"inputHash":' +
		(ConvertTo-FlatJsonString $inputHash) + ',"status":"' + $status + '","findings":[' + $jsonFindings + ']}'

	if ($Json) {
		# Перевод строки - всегда "`n" (а не WriteLine с Environment.NewLine): вывод
		# обоих портов сверяется гардом байт в байт.
		[Console]::Out.Write($jsonPayload + "`n")
		return $(if ($sorted.Count -gt 0) { 1 } else { 0 })
	}

	$lines = [System.Collections.ArrayList]::new()
	[void]$lines.Add("=== BSL catalog lint: $($modules.Count) module(s), $($ruleIds.Count) rule(s) ===")
	[void]$lines.Add("")
	foreach ($f in $sorted) { [void]$lines.Add("[$($f.id)] $($f.file):$($f.line)  $($f.match)") }
	[void]$lines.Add("")
	[void]$lines.Add("=== Result: $($sorted.Count) finding(s) ===")
	[void]$lines.Add("EVIDENCE " + $jsonPayload)
	[Console]::Out.Write(($lines -join "`n") + "`n")
	return $(if ($sorted.Count -gt 0) { 1 } else { 0 })
}

# --- Вход ---

if ($RuleId -ne "" -and -not $Catalog) {
	[Console]::Error.WriteLine("-RuleId имеет смысл только вместе с -Catalog")
	exit 2
}
if ($Catalog) { exit (Invoke-CatalogLint) }
if ($IndexPath -eq "") {
	[Console]::Error.WriteLine("the following arguments are required: -IndexPath (или режим -Catalog, где индекс не нужен)")
	exit 2
}

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
