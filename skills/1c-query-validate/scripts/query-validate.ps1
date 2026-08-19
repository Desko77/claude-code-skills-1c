# query-validate v1.0 - Check 1C query text against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[string]$QueryPath,
	[string]$Query,
	[Parameter(Mandatory)][string]$IndexPath,
	[switch]$Detailed,
	[int]$MaxErrors = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Имя таблицы в запросе -> тип метаданных. Оба языка запроса: конфигурация может быть написана
# и по-русски, и по-английски, а проверять надо обе.
$queryTablePrefixMap = @{
	"Справочник"="Catalog"; "Catalog"="Catalog"
	"Документ"="Document"; "Document"="Document"
	"Перечисление"="Enum"; "Enum"="Enum"
	"РегистрСведений"="InformationRegister"; "InformationRegister"="InformationRegister"
	"РегистрНакопления"="AccumulationRegister"; "AccumulationRegister"="AccumulationRegister"
	"РегистрБухгалтерии"="AccountingRegister"; "AccountingRegister"="AccountingRegister"
	"РегистрРасчета"="CalculationRegister"; "CalculationRegister"="CalculationRegister"
	"ПланСчетов"="ChartOfAccounts"; "ChartOfAccounts"="ChartOfAccounts"
	"ПланВидовХарактеристик"="ChartOfCharacteristicTypes"
	"ChartOfCharacteristicTypes"="ChartOfCharacteristicTypes"
	"ПланВидовРасчета"="ChartOfCalculationTypes"; "ChartOfCalculationTypes"="ChartOfCalculationTypes"
	"ПланОбмена"="ExchangePlan"; "ExchangePlan"="ExchangePlan"
	"БизнесПроцесс"="BusinessProcess"; "BusinessProcess"="BusinessProcess"
	"Задача"="Task"; "Task"="Task"
	"Константа"="Constant"; "Constant"="Constant"
	"ЖурналДокументов"="DocumentJournal"; "DocumentJournal"="DocumentJournal"
	"Последовательность"="Sequence"; "Sequence"="Sequence"
	"КритерийОтбора"="FilterCriterion"; "FilterCriterion"="FilterCriterion"
}

# Виртуальные таблицы по виду регистра. Список закрытый: имя вне его - повод предупредить,
# потому что платформа такую таблицу не найдет.
$virtualTables = @{
	"AccumulationRegister" = @("Остатки", "Balance", "Обороты", "Turnovers", "ОстаткиИОбороты", "BalanceAndTurnovers")
	"InformationRegister" = @("СрезПоследних", "SliceLast", "СрезПервых", "SliceFirst")
	"AccountingRegister" = @("Остатки", "Balance", "Обороты", "Turnovers", "ОстаткиИОбороты", "BalanceAndTurnovers", "ДвиженияССубконто", "RecordsWithExtDimensions", "ОборотыДтКт", "DrCrTurnovers")
	"CalculationRegister" = @("ДанныеГрафика", "ScheduleData", "БазаПоВидуРасчета", "BaseCalculationType", "ФактическийПериодДействия", "ActualActionPeriod", "Перерасчет", "Recalc")
}

# Стандартные поля таблиц в тексте запроса. Внутренние имена английские, в запросе пишут русские -
# принимаются оба. Набор ОБЩИЙ, не по видам объектов: неверная привязка поля к виду дала бы
# ложное срабатывание, а лишнее имя в наборе - всего лишь пропуск.
$standardQueryFields = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($f in @(
	"Ссылка", "Ref", "Код", "Code", "Наименование", "Description",
	"ПометкаУдаления", "DeletionMark", "ЭтоГруппа", "IsFolder", "Родитель", "Parent",
	"Владелец", "Owner", "Предопределенный", "Predefined",
	"ИмяПредопределенныхДанных", "PredefinedDataName",
	"Проведен", "Posted", "Дата", "Date", "Номер", "Number",
	"Период", "Period", "Регистратор", "Recorder", "НомерСтроки", "LineNumber",
	"Активность", "Active", "ВидДвижения", "RecordType",
	"Счет", "Account", "Порядок", "Order", "Вид", "Type", "Забалансовый", "OffBalance",
	"ТипЗначения", "ValueType", "ЭтотУзел", "ThisNode",
	"НомерОтправленного", "SentNo", "НомерПринятого", "ReceivedNo",
	"Стартован", "Started", "Завершен", "Completed", "ВедущаяЗадача", "HeadTask",
	"Выполнена", "Executed", "ТочкаМаршрута", "RoutePoint", "БизнесПроцесс", "BusinessProcess",
	"ПериодРегистрации", "RegistrationPeriod", "ВидРасчета", "CalculationType",
	"Сторно", "ReversingEntry",
	"ПериодДействия", "ActionPeriod", "ПериодДействияНачало", "BegOfActionPeriod",
	"ПериодДействияКонец", "EndOfActionPeriod",
	"БазовыйПериодНачало", "BegOfBasePeriod", "БазовыйПериодКонец", "EndOfBasePeriod",
	"ПериодДействияБазовый", "ActionPeriodIsBasic",
	"МоментВремени", "PointInTime", "Представление", "Presentation",
	"ВерсияДанных", "DataVersion", "Значение", "Value")) { [void]$standardQueryFields.Add($f) }

$ident = '[A-Za-z_А-яЁё][A-Za-z0-9_А-яЁё]*'
$tableRe = [regex]("\b($ident)\.($ident)(?:\.($ident))?")
$fromRe = [regex]("(?i)\b(?:ИЗ|FROM|СОЕДИНЕНИЕ|JOIN)\s+($ident)\.($ident)(?:\.($ident))?\s*(?:\([^()]*\))?(?:\s*(?:КАК|AS)\s+($ident))?")
$fieldRe = [regex]("\b($ident)\.($ident)\b")

# Строковые литералы и комментарии выкидываются: внутри них Справочник.Чего-Нибудь - просто
# текст, а не имя таблицы.
function Remove-QueryNoise([string]$text) {
	$t = [regex]::Replace($text, '/\*.*?\*/', ' ', [System.Text.RegularExpressions.RegexOptions]::Singleline)
	$t = [regex]::Replace($t, '//[^\n]*', ' ')
	$t = [regex]::Replace($t, '"(?:[^"]|"")*"', ' ')
	return $t
}

# Поля виртуальной таблицы выводятся из ресурсов по суффиксам. Незнакомая таблица дает $null -
# поля такого псевдонима не проверяются вовсе.
#
# У регистров бухгалтерии и расчета суффиксного правила НЕТ: там СуммаОстатокДт, СуммаОборотКт,
# развернутые остатки, корреспонденции. Выводить их этим способом нельзя - будут ложные
# срабатывания на существующие поля, поэтому такие таблицы объявляются непрозрачными.
function Get-VirtualTableFields([string]$kind, [string]$vtName, $obj) {
	if ($kind -eq "AccountingRegister" -or $kind -eq "CalculationRegister") { return $null }
	$fields = New-Object 'System.Collections.Generic.HashSet[string]'
	$res = @()
	if ($obj.resources) { foreach ($p in $obj.resources.PSObject.Properties) { $res += $p.Name } }
	if ($obj.dimensions) { foreach ($p in $obj.dimensions.PSObject.Properties) { [void]$fields.Add($p.Name) } }
	if ($vtName -eq "Остатки" -or $vtName -eq "Balance") {
		foreach ($r in $res) { [void]$fields.Add($r + "Остаток"); [void]$fields.Add($r + "Balance") }
	} elseif ($vtName -eq "Обороты" -or $vtName -eq "Turnovers") {
		foreach ($r in $res) {
			[void]$fields.Add($r + "Оборот"); [void]$fields.Add($r + "Приход"); [void]$fields.Add($r + "Расход")
			[void]$fields.Add($r + "Turnover"); [void]$fields.Add($r + "Receipt"); [void]$fields.Add($r + "Expense")
		}
	} elseif ($vtName -eq "ОстаткиИОбороты" -or $vtName -eq "BalanceAndTurnovers") {
		foreach ($r in $res) {
			foreach ($sfx in @("НачальныйОстаток", "КонечныйОстаток", "Приход", "Расход", "Оборот",
				"OpeningBalance", "ClosingBalance", "Receipt", "Expense", "Turnover")) { [void]$fields.Add($r + $sfx) }
		}
	} elseif ($vtName -in @("СрезПоследних", "SliceLast", "СрезПервых", "SliceFirst")) {
		foreach ($r in $res) { [void]$fields.Add($r) }
		if ($obj.attributes) { foreach ($p in $obj.attributes.PSObject.Properties) { [void]$fields.Add($p.Name) } }
	} else {
		return $null
	}
	return $fields
}

# --- Вход ---

if (-not $QueryPath -and -not $Query) {
	[Console]::Error.WriteLine("Either -QueryPath or -Query is required")
	exit 1
}

if ($QueryPath) {
	if (-not [System.IO.Path]::IsPathRooted($QueryPath)) { $QueryPath = Join-Path (Get-Location).Path $QueryPath }
	if (-not [System.IO.File]::Exists($QueryPath)) {
		[Console]::Error.WriteLine("Query file not found: " + $QueryPath)
		exit 1
	}
	$queryText = [System.IO.File]::ReadAllText($QueryPath, [System.Text.Encoding]::UTF8)
	$sourceLabel = [System.IO.Path]::GetFileName($QueryPath)
} else {
	$queryText = $Query
	$sourceLabel = "(inline)"
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
$objects = @{}
foreach ($p in $indexData.objects.PSObject.Properties) { $objects[$p.Name] = $p.Value }
$lenient = ($indexData.kind -eq "extension")

$warnings = [System.Collections.ArrayList]::new()
function Add-QueryWarn([string]$msg) {
	if ($script:warnings.Count -lt $MaxErrors) { [void]$script:warnings.Add($msg) }
}

$clean = Remove-QueryNoise $queryText

# --- Таблицы в позиции ИЗ / СОЕДИНЕНИЕ: разбираются полностью, вместе с третьей частью ---

$aliases = @{}
$aliasNames = New-Object 'System.Collections.Generic.HashSet[string]'   # ВСЕ псевдонимы, даже неразрешенные
$tableSpans = [System.Collections.ArrayList]::new()                     # куски текста, уже разобранные как имя таблицы
$seenMissing = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($m in $fromRe.Matches($clean)) {
	$prefix = $m.Groups[1].Value
	$name = $m.Groups[2].Value
	$third = if ($m.Groups[3].Success) { $m.Groups[3].Value } else { $null }
	$alias = if ($m.Groups[4].Success) { $m.Groups[4].Value } else { $null }
	if ($alias) { [void]$aliasNames.Add($alias) }
	$kind = $queryTablePrefixMap[$prefix]
	if (-not $kind) { continue }
	# Позиция самого имени таблицы: сюда не должен лезть проход по полям, иначе
	# "ИЗ Документ.Накладная КАК Документ" прочтется как поле Накладная у псевдонима Документ.
	$nameStart = $clean.IndexOf($prefix, $m.Index)
	$nameEnd = if ($null -eq $third) { $m.Groups[2].Index + $m.Groups[2].Length } else { $m.Groups[3].Index + $m.Groups[3].Length }
	[void]$tableSpans.Add(@($nameStart, $nameEnd))
	$key = "$kind.$name"
	if (-not $objects.ContainsKey($key)) {
		if ($seenMissing.Add($key)) {
			if ($lenient) {
				Add-QueryWarn "Таблицы '$prefix.$name' нет в этой выгрузке - ожидается в основной конфигурации"
			} else {
				Add-QueryWarn "Таблицы '$prefix.$name' нет в конфигурации"
			}
		}
		continue
	}
	$obj = $objects[$key]
	if ($null -eq $third) {
		$fields = New-Object 'System.Collections.Generic.HashSet[string]'
		foreach ($bucket in @("attributes", "dimensions", "resources", "addressingAttributes", "accountingFlags", "tabularSections", "standardTabularSections")) {
			if ($obj.$bucket) { foreach ($p in $obj.$bucket.PSObject.Properties) { [void]$fields.Add($p.Name) } }
		}
		if ($obj.standardAttributes) { foreach ($n in $obj.standardAttributes) { [void]$fields.Add([string]$n) } }
		if ($alias) { $aliases[$alias] = @{ label = $key; fields = $fields } }
	} elseif ($virtualTables.ContainsKey($kind)) {
		if ($virtualTables[$kind] -notcontains $third) {
			Add-QueryWarn "Виртуальной таблицы '$third' нет у $key"
			continue
		}
		$vtFields = Get-VirtualTableFields $kind $third $obj
		if ($null -eq $vtFields) {
			if ($alias) { $aliases[$alias] = @{ label = "$key.$third"; fields = $null } }
		} else {
			if ($alias) { $aliases[$alias] = @{ label = "$key.$third"; fields = $vtFields } }
		}
	} else {
		$ts = $null
		if ($obj.tabularSections) { $ts = $obj.tabularSections.$third }
		if ($null -ne $ts) {
			$fields = New-Object 'System.Collections.Generic.HashSet[string]'
			if ($ts.attributes) { foreach ($p in $ts.attributes.PSObject.Properties) { [void]$fields.Add($p.Name) } }
			if ($ts.standardAttributes) { foreach ($n in $ts.standardAttributes) { [void]$fields.Add([string]$n) } }
			if ($alias) { $aliases[$alias] = @{ label = "$key.$third"; fields = $fields } }
			continue
		}
		$stdTs = $null
		if ($obj.standardTabularSections) { $stdTs = $obj.standardTabularSections.$third }
		if ($null -ne $stdTs) {
			$fields = New-Object 'System.Collections.Generic.HashSet[string]'
			foreach ($n in $stdTs) { [void]$fields.Add([string]$n) }
			if ($obj.extDimensionAccountingFlags) { foreach ($p in $obj.extDimensionAccountingFlags.PSObject.Properties) { [void]$fields.Add($p.Name) } }
			if ($alias) { $aliases[$alias] = @{ label = "$key.$third"; fields = $fields } }
			continue
		}
		Add-QueryWarn "У $key нет табличной части '$third'"
	}
}

# --- Все двухчастные имена метаданных где угодно: объект обязан существовать ---

$checkedObjects = 0
$seenObjects = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($m in $tableRe.Matches($clean)) {
	$prefix = $m.Groups[1].Value
	$name = $m.Groups[2].Value
	# Псевдоним запроса может называться как тип метаданных: "ИЗ Документ.Накладная КАК
	# Документ". Тогда Документ.Дата - это ПОЛЕ, а не таблица, и трогать его тут нельзя.
	if ($aliasNames.Contains($prefix)) { continue }
	$kind = $queryTablePrefixMap[$prefix]
	if (-not $kind) { continue }
	$key = "$kind.$name"
	if ($seenMissing.Contains($key)) { continue }
	if (-not $seenObjects.Add($key)) { continue }
	$checkedObjects++
	if (-not $objects.ContainsKey($key)) {
		if ($lenient) {
			Add-QueryWarn "Таблицы '$prefix.$name' нет в этой выгрузке - ожидается в основной конфигурации"
		} else {
			Add-QueryWarn "Таблицы '$prefix.$name' нет в конфигурации"
		}
	}
}

# --- Поля по псевдонимам ---

$checkedFields = 0
$seenFields = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($m in $fieldRe.Matches($clean)) {
	$alias = $m.Groups[1].Value
	$field = $m.Groups[2].Value
	if (-not $aliases.ContainsKey($alias)) { continue }
	$inTable = $false
	foreach ($span in $tableSpans) {
		if ($m.Index -ge $span[0] -and $m.Index -lt $span[1]) { $inTable = $true; break }
	}
	if ($inTable) { continue }
	$binding = $aliases[$alias]
	if ($null -eq $binding.fields) { continue }
	if (-not $seenFields.Add("$alias`t$field")) { continue }
	$checkedFields++
	if ($binding.fields.Contains($field) -or $standardQueryFields.Contains($field)) { continue }
	if ($lenient) {
		Add-QueryWarn "У таблицы $($binding.label) нет поля '$field' в этой выгрузке - ожидается в основной конфигурации"
	} else {
		Add-QueryWarn "У таблицы $($binding.label) нет поля '$field'"
	}
}

# --- Итог ---

$lines = [System.Collections.ArrayList]::new()
[void]$lines.Add("=== Query check: $sourceLabel ===")
[void]$lines.Add("")
foreach ($w in $warnings) { [void]$lines.Add("[WARN]  $w") }
if ($Detailed -or $warnings.Count -eq 0) {
	[void]$lines.Add("[OK]    Таблиц проверено: $checkedObjects")
	[void]$lines.Add("[OK]    Псевдонимов связано: $($aliases.Count)")
	[void]$lines.Add("[OK]    Полей проверено: $checkedFields")
}
[void]$lines.Add("")
[void]$lines.Add("=== Result: $($warnings.Count) warnings ===")
Write-Host ($lines -join "`n")
exit 0
