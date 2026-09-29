# role-edit v1.0 - точечная правка существующей роли 1С
param(
    [Parameter(Mandatory)]
    [string]$RolePath,
    [string]$DefinitionFile,
    [string]$Operation,
    [string]$Object,
    [string]$Rights,
    [string]$Right,
    [string]$Template,
    [string]$Condition,
    [string]$Property,
    [string]$Value,
    [switch]$NoValidate
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Support guard (Ext/ParentConfigurations.bin) ---
# See docs/1c-support-state-spec.md. Blocks edits of vendor objects "на замке" /
# read-only configs unless allowed. Trigger = bin present; reaction from
# .v8-project.json editingAllowedCheck (deny|warn|off, default deny). Never
# throws - guard errors degrade to allow.
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
			if ($null -ne $best -and $best -ne 2) { $blocked = $true; $code = "not-removed"; $reason = "объект не снят с поддержки - удаление сломает обновления" }
		}
		else {
			if ($null -ne $best -and $best -eq 0) { $blocked = $true; $code = "locked"; $reason = "объект на замке - редактирование сломает обновления" }
		}
		if (-not $blocked) { return }
		$mode = Get-EditMode $cfgDir
		if ($mode -eq 'off') { return }
		# Use Console.Error (not Write-Error) - under ErrorActionPreference=Stop the
		# latter throws and would be swallowed by this function's own catch.
		if ($mode -eq 'warn') { [Console]::Error.WriteLine("[support-guard] ПРЕДУПРЕЖДЕНИЕ: $reason. Цель: $rp"); return }
		$head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
		$cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) - состояние поддержки менять не нужно, обновления вендора сохраняются."
		$offNote = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
		if ($code -eq "capability-off") {
			$state = "Состояние: у всей конфигурации выключена возможность изменения (режим read-only 'из коробки') - поэтому объект '$rp' редактировать нельзя."
			$fix = "Либо снять защиту явно (навык support-edit, два шага):`n  1. support-edit -Path ""$cfgDir"" -Capability on - включить возможность изменения (объекты пока остаются на замке);`n  2. support-edit -Path ""$rp"" -Set editable - открыть этот объект для редактирования.`n  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
		} elseif ($code -eq "not-removed") {
			$state = "Состояние: объект '$rp' на поддержке (не снят с поддержки) - его удаление разорвет обновления вендора."
			$fix = "Либо сначала снять объект с поддержки, затем удалять:`n  support-edit -Path ""$rp"" -Set off-support - объект уходит из-под обновлений, после этого удаление безопасно."
		} else {
			$state = "Состояние: объект '$rp' на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
			$fix = "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):`n  support-edit -Path ""$rp"" -Set editable - редактировать и дальше получать обновления вендора (возможны конфликты слияния);`n  support-edit -Path ""$rp"" -Set off-support - снять с поддержки: обновления по объекту больше не приходят."
		}
		[Console]::Error.WriteLine("$head`n$state`n$cfe`n$fix`n$offNote")
		exit 1
	} catch { return }
}
# --- Конец общего блока гарда поддержки ---

# --- Таблица прав и замыкание (общий блок, версия 2) ---
# --- 3. Russian synonyms → canonical English names ---

$script:typeAliases = @{
	"Справочник" = "Catalog"
	"Документ" = "Document"
	"РегистрСведений" = "InformationRegister"
	"РегистрНакопления" = "AccumulationRegister"
	"РегистрБухгалтерии" = "AccountingRegister"
	"РегистрРасчета" = "CalculationRegister"
	"Константа" = "Constant"
	"ПланСчетов" = "ChartOfAccounts"
	"ПланВидовХарактеристик" = "ChartOfCharacteristicTypes"
	"ПланВидовРасчета" = "ChartOfCalculationTypes"
	"ПланОбмена" = "ExchangePlan"
	"БизнесПроцесс" = "BusinessProcess"
	"Задача" = "Task"
	"Обработка" = "DataProcessor"
	"Отчет" = "Report"
	"ОбщаяФорма" = "CommonForm"
	"ОбщаяКоманда" = "CommonCommand"
	"Подсистема" = "Subsystem"
	"КритерийОтбора" = "FilterCriterion"
	"ЖурналДокументов" = "DocumentJournal"
	"Последовательность" = "Sequence"
	"ВебСервис" = "WebService"
	"HTTPСервис" = "HTTPService"
	"СервисИнтеграции" = "IntegrationService"
	"ПараметрСеанса" = "SessionParameter"
	"ОбщийРеквизит" = "CommonAttribute"
	"Конфигурация" = "Configuration"
	"Перечисление" = "Enum"
	# Nested
	"Реквизит" = "Attribute"
	"СтандартныйРеквизит" = "StandardAttribute"
	"ТабличнаяЧасть" = "TabularSection"
	"Измерение" = "Dimension"
	"Ресурс" = "Resource"
	"Команда" = "Command"
	"РеквизитАдресации" = "AddressingAttribute"
}

$script:rightAliases = @{
	"Чтение" = "Read"
	"Добавление" = "Insert"
	"Изменение" = "Update"
	"Удаление" = "Delete"
	"Просмотр" = "View"
	"Редактирование" = "Edit"
	"ВводПоСтроке" = "InputByString"
	"Проведение" = "Posting"
	"ОтменаПроведения" = "UndoPosting"
	"ИнтерактивноеДобавление" = "InteractiveInsert"
	"ИнтерактивнаяПометкаУдаления" = "InteractiveSetDeletionMark"
	"ИнтерактивноеСнятиеПометкиУдаления" = "InteractiveClearDeletionMark"
	"ИнтерактивноеУдаление" = "InteractiveDelete"
	"ИнтерактивноеУдалениеПомеченных" = "InteractiveDeleteMarked"
	"ИнтерактивноеПроведение" = "InteractivePosting"
	"ИнтерактивноеПроведениеНеоперативное" = "InteractivePostingRegular"
	"ИнтерактивнаяОтменаПроведения" = "InteractiveUndoPosting"
	"ИнтерактивноеИзменениеПроведенных" = "InteractiveChangeOfPosted"
	"Использование" = "Use"
	"Получение" = "Get"
	"Установка" = "Set"
	"Старт" = "Start"
	"ИнтерактивныйСтарт" = "InteractiveStart"
	"ИнтерактивнаяАктивация" = "InteractiveActivate"
	"Выполнение" = "Execute"
	"ИнтерактивноеВыполнение" = "InteractiveExecute"
	"УправлениеИтогами" = "TotalsControl"
	"Администрирование" = "Administration"
	"АдминистрированиеДанных" = "DataAdministration"
	"ТонкийКлиент" = "ThinClient"
	"ВебКлиент" = "WebClient"
	"ТолстыйКлиент" = "ThickClient"
	"ВнешнееСоединение" = "ExternalConnection"
	"Вывод" = "Output"
	"СохранениеДанныхПользователя" = "SaveUserData"
	"МобильныйКлиент" = "MobileClient"
}

# Translate Russian object name to English (e.g. "Справочник.Контрагенты" → "Catalog.Контрагенты")
function Translate-ObjectName {
	param([string]$name)
	$parts = $name.Split(".")
	$result = @()
	foreach ($p in $parts) {
		# Написание с точками над е и без них равноправно: пользователь пишет как привык, а в
		# карте алиасов ключ один. Имя самого объекта не нормализуется - оно идет как есть.
		$normalized = $p.Replace('ё', 'е').Replace('Ё', 'Е')
		if ($script:typeAliases.ContainsKey($normalized)) {
			$result += $script:typeAliases[$normalized]
		} else {
			$result += $p
		}
	}
	return $result -join "."
}

# Translate Russian right name to English (e.g. "Чтение" → "Read")
function Translate-RightName {
	param([string]$name)
	if ($script:rightAliases.ContainsKey($name)) {
		return $script:rightAliases[$name]
	}
	return $name
}

# --- 4. Known rights per object type (source: docs/1c-role-spec.md) ---

$script:knownRights = @{
	"Configuration" = @(
		"Administration","DataAdministration","UpdateDataBaseConfiguration",
		"ConfigurationExtensionsAdministration","ActiveUsers","EventLog","ExclusiveMode",
		"ThinClient","ThickClient","WebClient","MobileClient","ExternalConnection",
		"Automation","Output","SaveUserData","TechnicalSpecialistMode",
		"InteractiveOpenExtDataProcessors","InteractiveOpenExtReports",
		"AnalyticsSystemClient","CollaborationSystemInfoBaseRegistration",
		"MainWindowModeNormal","MainWindowModeWorkplace",
		"MainWindowModeEmbeddedWorkplace","MainWindowModeFullscreenWorkplace","MainWindowModeKiosk"
	)
	"Catalog" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"UpdateDataHistoryOfMissingData","ReadDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"Document" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"Posting","UndoPosting",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"InteractivePosting","InteractivePostingRegular","InteractiveUndoPosting",
		"InteractiveChangeOfPosted",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"UpdateDataHistoryOfMissingData","ReadDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"InformationRegister" = @(
		"Read","Update","View","Edit","TotalsControl",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"UpdateDataHistoryOfMissingData","ReadDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"AccumulationRegister" = @("Read","Update","View","Edit","TotalsControl")
	"AccountingRegister" = @("Read","Update","View","Edit","TotalsControl")
	# Замер 8.3.27: у регистра расчета есть Update и Edit, а TotalsControl - нет.
	"CalculationRegister" = @("Read","Update","View","Edit")
	"Constant" = @(
		"Read","Update","View","Edit",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"ChartOfAccounts" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
		"ReadDataHistory","ReadDataHistoryOfMissingData",
		"UpdateDataHistory","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"ViewDataHistory","EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"ChartOfCharacteristicTypes" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"ReadDataHistoryOfMissingData","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"ChartOfCalculationTypes" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"ReadDataHistoryOfMissingData","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"ExchangePlan" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"ReadDataHistoryOfMissingData","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"BusinessProcess" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"Start","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked","InteractiveActivate","InteractiveStart",
		"ReadDataHistory","ReadDataHistoryOfMissingData",
		"UpdateDataHistory","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"ViewDataHistory","EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"Task" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"Execute","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveDeleteMarked","InteractiveActivate","InteractiveExecute",
		"ReadDataHistory","ReadDataHistoryOfMissingData",
		"UpdateDataHistory","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"ViewDataHistory","EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"DataProcessor" = @("Use","View")
	"Report" = @("Use","View")
	"CommonForm" = @("View")
	"CommonCommand" = @("View")
	"Subsystem" = @("View")
	"FilterCriterion" = @("View")
	"DocumentJournal" = @("Read","View")
	"Sequence" = @("Read","Update")
	# Замер 8.3.27: у самих веб- и HTTP-сервисов прав нет - платформа отбрасывает блок
	# при загрузке. Право Use живет на операции (WebService...Operation.*) и методе
	# (HTTPService...URLTemplate.*.Method.*).
	"WebService" = @()
	"HTTPService" = @()
	# Замер 8.3.27: у самого сервиса интеграции прав нет - платформа отбрасывает блок
	# при загрузке. Право Use живет на канале
	# (IntegrationService...IntegrationServiceChannel.*).
	"IntegrationService" = @()
	"SessionParameter" = @("Get","Set")
	"CommonAttribute" = @("View","Edit")
}

# --- Замыкание прав по зависимостям ---
#
# Платформа при загрузке роли дописывает права, без которых заданные не действуют:
# после первой загрузки файл роли и база расходятся, если писать ровно заданный набор.
# Замер круговым прогоном на 8.3.27.2214: роль с единственным правом R загружается в
# пустую базу и выгружается обратно; в выгрузке - полный набор, который держит R.
# Замыкание одноименных прав объединяется (проверено сверкой с выгрузкой полного набора).

$script:globalRightImpl = @{
	"Insert" = @("Read")
	"Update" = @("Read")
	"Delete" = @("Read")
	"View" = @("Read")
	"Edit" = @("Read","Update","View")
	"InputByString" = @("Read","View")
	"InteractiveInsert" = @("Read","Insert","Update","View","Edit")
	"InteractiveDelete" = @("Read","Update","Delete","View","Edit")
	"InteractiveDeleteMarked" = @("Read","Update","Delete","View","Edit")
	"InteractiveSetDeletionMark" = @("Read","Update","View","Edit")
	"InteractiveClearDeletionMark" = @("Read","Update","View","Edit")
	"InteractiveDeletePredefinedData" = @("Read","Update","Delete","View","Edit","InteractiveDelete")
	"InteractiveSetDeletionMarkPredefinedData" = @("Read","Update","View","Edit","InteractiveSetDeletionMark")
	"InteractiveClearDeletionMarkPredefinedData" = @("Read","Update","View","Edit","InteractiveClearDeletionMark")
	"InteractiveDeleteMarkedPredefinedData" = @("Read","Update","Delete","View","Edit","InteractiveDeleteMarked")
	"Posting" = @("Read","Update")
	"UndoPosting" = @("Read","Update")
	"InteractivePosting" = @("Read","Update","Posting","View","Edit")
	"InteractivePostingRegular" = @("InteractivePosting")
	"InteractiveUndoPosting" = @("Read","Update","UndoPosting","View","Edit")
	"InteractiveChangeOfPosted" = @("Read","Update","View","Edit")
	"ReadDataHistory" = @("Read")
	"ReadDataHistoryOfMissingData" = @("Read","ReadDataHistory")
	"UpdateDataHistory" = @("Read","ReadDataHistory")
	"UpdateDataHistoryOfMissingData" = @("Read","ReadDataHistory","ReadDataHistoryOfMissingData","UpdateDataHistory")
	"UpdateDataHistoryVersionComment" = @("Read","ReadDataHistory")
	"ViewDataHistory" = @("Read","View","ReadDataHistory")
	"EditDataHistoryVersionComment" = @("Read","View","ReadDataHistory","UpdateDataHistoryVersionComment")
	"SwitchToDataHistoryVersion" = @("Read","View")
	"Start" = @("Read","Update")
	"InteractiveStart" = @("Read","Update","Start")
	"InteractiveActivate" = @("Read","Update")
	"Execute" = @("Read","Update")
	"InteractiveExecute" = @("Read","Update","Execute")
	"Administration" = @("DataAdministration")
}

# Отклонения от глобальных правил, снятые тем же замером.
$script:rightImplByType = @{
	# У плана счетов блок истории данных не тянет за собой Read.
	"ChartOfAccounts" = @{
		"ReadDataHistory" = @()
		"ReadDataHistoryOfMissingData" = @("ReadDataHistory")
		"UpdateDataHistory" = @("ReadDataHistory")
		"UpdateDataHistoryOfMissingData" = @("ReadDataHistory","ReadDataHistoryOfMissingData","UpdateDataHistory")
		"UpdateDataHistoryVersionComment" = @("ReadDataHistory")
		"ViewDataHistory" = @("View","ReadDataHistory")
		"EditDataHistoryVersionComment" = @("View","ReadDataHistory","UpdateDataHistoryVersionComment")
		"SwitchToDataHistoryVersion" = @("View")
	}
	# У регистра сведений история отсутствующих данных не входит в замыкание.
	"InformationRegister" = @{
		"UpdateDataHistoryOfMissingData" = @("Read","ReadDataHistory","UpdateDataHistory")
	}
	# У обработки и отчета просмотр требует использования, а не чтения.
	"DataProcessor" = @{ "View" = @("Use") }
	"Report" = @{ "View" = @("Use") }
}

function Get-ImplFor {
	param([string]$ObjectType, [string]$Right)

	# Импликации права у конкретного типа: переопределение или глобальные,
	# пересеченные с правами типа (импликация имеет смысл только для существующих прав).
	if ($script:rightImplByType.ContainsKey($ObjectType) -and
		$script:rightImplByType[$ObjectType].ContainsKey($Right)) {
		return @($script:rightImplByType[$ObjectType][$Right])
	}
	$implied = @()
	if ($script:globalRightImpl.ContainsKey($Right)) { $implied = @($script:globalRightImpl[$Right]) }
	if (-not $script:knownRights.ContainsKey($ObjectType)) { return $implied }
	$typeRights = @($script:knownRights[$ObjectType])
	return @($implied | Where-Object { $_ -in $typeRights })
}

function Close-Rights {
	# Транзитивное замыкание включенных прав по зависимостям: платформа при загрузке
	# дописывает те же права, поэтому замкнутый файл совпадает с выгрузкой после
	# первой загрузки.
	param([string]$ObjectType, [string[]]$RightNames)

	$result = [System.Collections.Generic.HashSet[string]]::new([string[]]$RightNames)
	$frontier = [System.Collections.Generic.Queue[string]]::new()
	foreach ($r in $RightNames) { $frontier.Enqueue($r) }
	while ($frontier.Count -gt 0) {
		$r = $frontier.Dequeue()
		foreach ($imp in (Get-ImplFor -ObjectType $ObjectType -Right $r)) {
			if ($result.Add($imp)) { $frontier.Enqueue($imp) }
		}
	}
	return @($result)
}

# --- Канонический порядок прав ---
#
# Платформа выгружает права объекта в одном порядке по всем типам. Порядок снят с
# выгрузки полного набора и сверен: порядок каждого типа - подпоследовательность этого
# списка. Права вне списка (незамеренные вложенные виды) идут в конце в порядке ввода.
$script:rightOrder = @(
	# Configuration
	"Administration","DataAdministration","UpdateDataBaseConfiguration",
	"ExclusiveMode","ActiveUsers","EventLog",
	"ThinClient","WebClient","MobileClient","ThickClient","ExternalConnection",
	"Automation","TechnicalSpecialistMode","CollaborationSystemInfoBaseRegistration",
	"MainWindowModeNormal","MainWindowModeWorkplace","MainWindowModeEmbeddedWorkplace",
	"MainWindowModeFullscreenWorkplace","MainWindowModeKiosk","AnalyticsSystemClient",
	"SaveUserData","ConfigurationExtensionsAdministration",
	"InteractiveOpenExtDataProcessors","InteractiveOpenExtReports","Output",
	# объектные
	"Read","Insert","Update","Delete","Posting","UndoPosting",
	"Use","View","Get","Set",
	"InteractiveInsert","Edit","InteractiveDelete","InteractiveSetDeletionMark",
	"InteractiveClearDeletionMark","InteractiveDeleteMarked",
	"InteractivePosting","InteractivePostingRegular","InteractiveUndoPosting",
	"InteractiveChangeOfPosted","InputByString",
	"InteractiveActivate","Start","InteractiveStart","Execute","InteractiveExecute",
	"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
	"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
	"TotalsControl",
	"ReadDataHistory","ReadDataHistoryOfMissingData","UpdateDataHistory",
	"UpdateDataHistoryOfMissingData","UpdateDataHistorySettings",
	"UpdateDataHistoryVersionComment","ViewDataHistory","EditDataHistoryVersionComment",
	"SwitchToDataHistoryVersion"
)
$script:rightOrderPos = @{}
for ($i = 0; $i -lt $script:rightOrder.Count; $i++) { $script:rightOrderPos[$script:rightOrder[$i]] = $i }

# Виды, у которых View и Edit подчиняются флажку setForAttributesByDefault.
# Замер 8.3.27.2214: выгрузка оставляет право, только если оно не совпадает с умолчанием.
# setForAttributesByDefault=true - умолчание true (явный true пропадает, false остается).
# setForAttributesByDefault=false - умолчание false (явный false пропадает, true остается).
# independentRightsOfChildObjects и наличие прав на сам объект выгрузку не меняют.
# Измерения и ресурсы регистров подчиняются тому же правилу; измерения куба внешнего источника не замерены.
$script:nestedDefaultKinds = @("Attribute", "TabularSection", "StandardAttribute", "Dimension", "Resource")

# Условие ограничения доступа на вложенном праве, замер 8.3.27.2214: у стандартного реквизита
# выгрузка сохраняет условие и право с ним при любом значении; у реквизита, измерения и ресурса
# условие не сохраняется.
$script:nestedConditionKeptKinds = @("StandardAttribute")
$script:nestedConditionDroppedKinds = @("Attribute", "Dimension", "Resource")

function Test-NestedDefaultRightKept {
	# Вложенное право остается в выгрузке, если несет сохраняемое условие или не дублирует умолчание.
	param([string]$ObjectName, [string]$RightName, [string]$Value, [bool]$SetForAttributesByDefault, [string]$Condition)
	$parts = $ObjectName.Split(".")
	$kind = $parts[$parts.Count - 2]
	if ($parts[0] -eq "ExternalDataSource" -or $kind -notin $script:nestedDefaultKinds -or $RightName -notin @("View", "Edit")) {
		return $true
	}
	if ($Condition -and $kind -in $script:nestedConditionKeptKinds) {
		return $true
	}
	$defaultValue = if ($SetForAttributesByDefault) { "true" } else { "false" }
	return ($Value.ToLower() -ne $defaultValue)
}

function Close-NestedViewEdit {
	# Согласует View и Edit вложенного права так, как их приводит загрузка платформы.
	# Замер 8.3.27.2214: явный Edit=true при View=false дает View=true; View=false при Edit
	# по умолчанию дает Edit=false. Возвращает новый список, исходный не меняется.
	param([string]$ObjectName, $Rights, [bool]$SetForAttributesByDefault)
	$result = New-Object System.Collections.ArrayList
	foreach ($right in @($Rights)) {
		if ($null -eq $right) { continue }
		[void]$result.Add(@{ Name = "$($right.Name)"; Value = "$($right.Value)"; Condition = $right.Condition })
	}
	$parts = $ObjectName.Split(".")
	if ($parts[0] -eq "ExternalDataSource" -or $parts[$parts.Count - 2] -notin $script:nestedDefaultKinds) {
		return $result.ToArray()
	}
	$defaultValue = if ($SetForAttributesByDefault) { "true" } else { "false" }
	$viewRight = $null
	$editRight = $null
	foreach ($right in $result) {
		if ($right.Name -eq "View") { $viewRight = $right }
		if ($right.Name -eq "Edit") { $editRight = $right }
	}
	$view = if ($viewRight) { $viewRight.Value.ToLower() } else { $defaultValue }
	$edit = if ($editRight) { $editRight.Value.ToLower() } else { $defaultValue }
	if ($view -ne "false" -or $edit -ne "true") { return $result.ToArray() }
	if ($editRight) {
		if ($viewRight) {
			$viewRight.Value = "true"
		} else {
			$result.Insert($result.IndexOf($editRight), @{ Name = "View"; Value = "true"; Condition = $null })
		}
	} else {
		[void]$result.Add(@{ Name = "Edit"; Value = "false"; Condition = $null })
	}
	return $result.ToArray()
}

# --- Конец общего блока таблицы прав и замыкания ---

# Nested objects: Attribute, StandardAttribute, TabularSection, Dimension, Resource, AddressingAttribute
$script:nestedRights = @("View","Edit")
$script:commandRights = @("View")

# Права вложенных объектов зависят от вида: у операции веб-сервиса и метода HTTP-сервиса это
# Use, у реквизита - View и Edit, у перерасчета - Read и Update.
$script:nestedRightsByKind = @{
	"Attribute" = @("View","Edit")
	"TabularSection" = @("View","Edit")
	"StandardAttribute" = @("View","Edit")
	"Resource" = @("View","Edit")
	"Field" = @("View","Edit")
	"Command" = @("View")
	"Subsystem" = @("View")
	"Operation" = @("Use")
	"Method" = @("Use")
	"URLTemplate" = @("Use")
	"IntegrationServiceChannel" = @("Use")
	"Recalculation" = @("Read","Update")
}

# Виды, набор прав которых этим навыком не замерен: имя признается, права не проверяются.
$script:nestedKindsRightsNotChecked = @("Table","Cube","Dimension","ResourceField","Function")

# Типы метаданных, у которых прав в роли нет вовсе (таблица типов, docs/1c-configuration-spec.md).
# Блок прав на такой тип платформа не примет, поэтому это отказ, а не предупреждение.
$script:typesWithoutRights = @(
	"CommandGroup","CommonModule","CommonPicture","CommonTemplate","DefinedType",
	"DocumentNumerator","Enum","EventSubscription","FunctionalOption",
	"FunctionalOptionsParameter","Language","Role","ScheduledJob","SettingsStorage",
	"Style","StyleItem","WSReference","XDTOPackage"
)

# Типы, права которых этим навыком не замерены: имя признается, набор прав не проверяется.
$script:typesRightsNotChecked = @("ExternalDataSource")

# Виды вложенности по владельцу. Ключ - тип объекта или вид предыдущего уровня: у HTTP-сервиса
# внутри шаблона URL лежит метод, у таблицы внешнего источника - поле, у куба - измерение.
$script:defaultNestedKinds = @("Attribute","TabularSection","StandardAttribute","Command")
$script:registerNestedKinds = @("Dimension","Resource","Attribute","StandardAttribute","Command")
$script:nestedKindsByOwner = @{
	"WebService" = @("Operation")
	"HTTPService" = @("URLTemplate")
	"URLTemplate" = @("Method")
	"IntegrationService" = @("IntegrationServiceChannel")
	"Subsystem" = @("Subsystem")
	"InformationRegister" = $script:registerNestedKinds
	"AccumulationRegister" = $script:registerNestedKinds
	"AccountingRegister" = $script:registerNestedKinds
	"CalculationRegister" = $script:registerNestedKinds + @("Recalculation")
	"ExternalDataSource" = @("Table","Cube","Function")
	"Table" = @("Field")
	"Cube" = @("Dimension","ResourceField")
}

# Ошибки ввода копятся до конца разбора: пользователь видит весь список сразу, а не по одной
# ошибке за прогон.
$script:inputErrors = @()

function Add-InputError {
	param([string]$Message)
	$script:inputErrors += $Message
}

# Ближайшее по написанию имя из списка - для подсказки при опечатке. Сравнение по общему
# префиксу и вхождению: этого хватает на реальные опечатки (Catalogg, Cataog).
function Find-SimilarName {
	param([string]$Name, [string[]]$Candidates)
	$best = $null
	$bestScore = 0
	foreach ($candidate in $Candidates) {
		$score = 0
		$limit = [Math]::Min($Name.Length, $candidate.Length)
		for ($i = 0; $i -lt $limit; $i++) {
			if ($Name[$i] -eq $candidate[$i]) { $score++ } else { break }
		}
		if ($candidate -like "*$Name*" -or $Name -like "*$candidate*") { $score += 2 }
		if ($score -gt $bestScore) { $bestScore = $score; $best = $candidate }
	}
	if ($bestScore -ge 3) { return $best }
	return $null
}

function Test-ObjectTypeKnown {
	param([string]$ObjectName)

	$objectType = Get-ObjectType $ObjectName
	if ($script:knownRights.ContainsKey($objectType) -or $objectType -in $script:typesRightsNotChecked) {
		return $true
	}
	if ($objectType -in $script:typesWithoutRights) {
		Add-InputError "${ObjectName}: тип '$objectType' не имеет прав в роли"
		return $false
	}
	$known = @($script:knownRights.Keys) + $script:typesWithoutRights + $script:typesRightsNotChecked
	$similar = Find-SimilarName -Name $objectType -Candidates $known
	$hint = if ($similar) { " Возможно: $($similar)?" } else { "" }
	Add-InputError "${ObjectName}: неизвестный тип объекта '$objectType'.$hint"
	return $false
}

# Владельцы, у которых такой вид вложенности законен, - для подсказки в сообщении об ошибке.
function Find-KindOwners {
	param([string]$Kind)
	foreach ($owner in $script:nestedKindsByOwner.Keys) {
		if ($Kind -in $script:nestedKindsByOwner[$owner]) { $owner }
	}
}

function Test-NestedKind {
	param([string]$ObjectName)

	$parts = $ObjectName.Split(".")
	# Имя идет парами "вид.имя", поэтому виды стоят на четных позициях начиная с третьей.
	for ($i = 2; $i -lt $parts.Count; $i += 2) {
		$kind = $parts[$i]
		$owner = if ($i -eq 2) { $parts[0] } else { $parts[$i - 2] }

		$allowed = if ($script:nestedKindsByOwner.ContainsKey($owner)) {
			$script:nestedKindsByOwner[$owner]
		} else {
			$script:defaultNestedKinds
		}
		if ($kind -in $allowed) { continue }

		$realOwners = if ($kind -in $script:defaultNestedKinds) { @() } else { @(Find-KindOwners $kind) }
		if ($realOwners.Count -gt 0) {
			# Владелец вида сам бывает видом: поле лежит в таблице, а таблица - во внешнем
			# источнике данных. В сообщении называется корень цепочки, он же тип объекта.
			$places = New-Object System.Collections.Generic.List[string]
			foreach ($realOwner in $realOwners) {
				$rootOwner = $realOwner
				$guard = 0
				while (@(Find-KindOwners $rootOwner).Count -gt 0 -and $guard -lt 10) {
					$rootOwner = @(Find-KindOwners $rootOwner)[0]
					$guard++
				}
				if ($rootOwner -ne $realOwner) { $places.Add("$rootOwner (внутри $realOwner)") } else { $places.Add($rootOwner) }
			}
			$placeArray = $places.ToArray()
			[Array]::Sort($placeArray, [StringComparer]::Ordinal)
			Add-InputError "${ObjectName}: вид вложенности '$kind' бывает только у $($placeArray -join ', '), а здесь владелец '$owner'"
		} else {
			Add-InputError "${ObjectName}: неизвестный вид вложенности '$kind' у '$owner'"
		}
		return $false
	}
	return $true
}

# --- 4. Presets (@view, @edit) ---

$script:presets = @{
	"view" = @{
		"Catalog" = @("Read","View","InputByString")
		"ExchangePlan" = @("Read","View","InputByString")
		"Document" = @("Read","View","InputByString")
		"ChartOfAccounts" = @("Read","View","InputByString")
		"ChartOfCharacteristicTypes" = @("Read","View","InputByString")
		"ChartOfCalculationTypes" = @("Read","View","InputByString")
		"BusinessProcess" = @("Read","View","InputByString")
		"Task" = @("Read","View","InputByString")
		"InformationRegister" = @("Read","View")
		"AccumulationRegister" = @("Read","View")
		"AccountingRegister" = @("Read","View")
		"CalculationRegister" = @("Read","View")
		"Constant" = @("Read","View")
		"DocumentJournal" = @("Read","View")
		"Sequence" = @("Read")
		"CommonForm" = @("View")
		"CommonCommand" = @("View")
		"Subsystem" = @("View")
		"FilterCriterion" = @("View")
		"SessionParameter" = @("Get")
		"CommonAttribute" = @("View")
		"DataProcessor" = @("Use","View")
		"Report" = @("Use","View")
		"Configuration" = @("ThinClient","WebClient","Output","SaveUserData","MainWindowModeNormal")
	}
	"edit" = @{
		"Catalog" = @("Read","Insert","Update","Delete","View","Edit","InputByString","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark")
		"ExchangePlan" = @("Read","Insert","Update","Delete","View","Edit","InputByString","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark")
		"Document" = @("Read","Insert","Update","Delete","View","Edit","InputByString","Posting","UndoPosting","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark","InteractivePosting","InteractivePostingRegular","InteractiveUndoPosting","InteractiveChangeOfPosted")
		"ChartOfAccounts" = @("Read","Insert","Update","Delete","View","Edit","InputByString","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark")
		"ChartOfCharacteristicTypes" = @("Read","Insert","Update","Delete","View","Edit","InputByString","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark")
		"ChartOfCalculationTypes" = @("Read","Insert","Update","Delete","View","Edit","InputByString","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark")
		"BusinessProcess" = @("Read","Insert","Update","Delete","View","Edit","InputByString","Start","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark","InteractiveActivate","InteractiveStart")
		"Task" = @("Read","Insert","Update","Delete","View","Edit","InputByString","Execute","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark","InteractiveActivate","InteractiveExecute")
		"InformationRegister" = @("Read","Update","View","Edit")
		"AccumulationRegister" = @("Read","Update","View","Edit")
		"AccountingRegister" = @("Read","Update","View","Edit")
		"CalculationRegister" = @("Read","Update","View","Edit")
		"Constant" = @("Read","Update","View","Edit")
		"DocumentJournal" = @("Read","View")
		"Sequence" = @("Read","Update")
		"SessionParameter" = @("Get","Set")
		"CommonAttribute" = @("View","Edit")
	}
}

# --- 5. Helpers ---

function Get-ObjectType {
	param([string]$objectName)
	$dotIdx = $objectName.IndexOf(".")
	if ($dotIdx -lt 0) { return $objectName }
	return $objectName.Substring(0, $dotIdx)
}

function Is-NestedObject {
	param([string]$objectName)
	return ($objectName.Split(".").Count -ge 3)
}

function Resolve-Preset {
	param([string]$objectType, [string]$presetName)

	$preset = $presetName.TrimStart('@')

	if (-not $script:presets.ContainsKey($preset)) {
		Write-Warning "Unknown preset '@$preset'. Known: @view, @edit"
		return @()
	}

	$typeMap = $script:presets[$preset]
	if (-not $typeMap.ContainsKey($objectType)) {
		$available = @()
		foreach ($k in $script:presets.Keys) {
			if ($script:presets[$k].ContainsKey($objectType)) {
				$available += "@$k"
			}
		}
		$availStr = if ($available.Count -gt 0) { $available -join ", " } else { "none" }
		Write-Warning "Preset '@$preset' not defined for type '$objectType'. Available: $availStr"
		return @()
	}

	return @($typeMap[$objectType])
}

function Validate-RightName {
	param([string]$objectName, [string]$rightName)

	$objectType = Get-ObjectType $objectName

	if (Is-NestedObject $objectName) {
		# Вид вложенности - предпоследний сегмент имени: пары идут как "вид.имя".
		$parts = $objectName.Split(".")
		$kind = $parts[$parts.Count - 2]
		if ($kind -in $script:nestedKindsRightsNotChecked) { return $true }
		if (-not $script:nestedRightsByKind.ContainsKey($kind)) { return $true }
		$allowed = $script:nestedRightsByKind[$kind]
		if ($rightName -notin $allowed) {
			Add-InputError "${objectName}: право '$rightName' не существует у вида '$kind' (допустимо: $($allowed -join ', '))"
			return $false
		}
		return $true
	}

	if (-not $script:knownRights.ContainsKey($objectType)) {
		# Тип уже разобран отдельной проверкой: здесь либо он без прав, либо права не замерены.
		return $true
	}

	$validRights = $script:knownRights[$objectType]
	if ($rightName -notin $validRights) {
		$similar = Find-SimilarName -Name $rightName -Candidates $validRights
		$hint = if ($similar) { " Возможно: $($similar)?" } else { "" }
		Add-InputError "${objectName}: право '$rightName' не существует у типа '$objectType'.$hint"
		return $false
	}

	return $true
}

# --- 6. Parse object entries ---

function Finish-Rights {
	# Замыкание включенных прав и канонический порядок выдачи. Замыкание применяется
	# только к объектам верхнего уровня с замеренным набором прав: у вложенных видов
	# платформа зависимостей не дописывает (замер 8.3.27).
	param([string]$ObjectName, $RightsMap)

	$objectType = Get-ObjectType $ObjectName
	$rightsOrder = @($RightsMap.Keys)
	if (-not (Is-NestedObject $ObjectName) -and $script:knownRights.ContainsKey($objectType)) {
		$enabled = @($rightsOrder | Where-Object { $RightsMap[$_].Value -eq "true" })
		$closed = Close-Rights -ObjectType $objectType -RightNames $enabled
		foreach ($r in $closed) {
			if (-not $RightsMap.Contains($r)) {
				$RightsMap[$r] = @{Value="true"; Condition=$null}
			}
		}
		$rightsOrder = @($RightsMap.Keys)
		foreach ($r in $rightsOrder) {
			if ($RightsMap[$r].Value -eq "false" -and $closed -contains $r) {
				$holders = @($closed | Where-Object { $_ -ne $r -and (Get-ImplFor -ObjectType $objectType -Right $_) -contains $r })
				[Console]::Error.WriteLine("WARNING: ${ObjectName}: право '$r' выключено явно, но право $($holders -join '/') требует его включенным - платформа отбросит весь блок объекта при загрузке")
			}
		}
	}
	$tailCount = $script:rightOrder.Count
	$rightsOrder = @($rightsOrder | Sort-Object `
		{ if ($script:rightOrderPos.ContainsKey($_)) { [int]$script:rightOrderPos[$_] } else { [int]($tailCount + 1) } },`
		{ [array]::IndexOf($rightsOrder, $_) })
	$rights = @()
	foreach ($k in $rightsOrder) {
		$rights += ,@{
			Name = $k
			Value = $RightsMap[$k].Value
			Condition = $RightsMap[$k].Condition
		}
	}
	return $rights
}


# Операции правки. Неизвестное имя - отказ.
$script:knownOps = @(
    'add-rights', 'set-rights', 'remove-rights', 'deny-rights',
    'set-rls', 'remove-rls',
    'add-template', 'set-template', 'remove-template',
    'modify-property'
)

# Признаки роли в Rights.xml.
$script:flagProps = @(
    'setForNewObjects', 'setForAttributesByDefault', 'independentRightsOfChildObjects'
)

$script:propMap = @{
    'synonym' = 'synonym'
    'comment' = 'comment'
    'setfornewobjects' = 'setForNewObjects'
    'setforattributesbydefault' = 'setForAttributesByDefault'
    'independentrightsofchildobjects' = 'independentRightsOfChildObjects'
    'синоним' = 'synonym'
    'комментарий' = 'comment'
}

# Отказ до записи: сообщение в stderr и код 1.
function Stop-RoleEdit([string]$Message) {
    [Console]::Error.WriteLine("Ошибка: $Message")
    exit 1
}

# Печатает накопленные ошибки ввода и завершает процесс, если они есть.
function Exit-InputErrors {
    if ($script:inputErrors.Count -eq 0) { return }
    foreach ($message in $script:inputErrors) {
        [Console]::Error.WriteLine("Ошибка: $message")
    }
    exit 1
}

# Экранирование текста для XML, как в выгрузке роли.
function Format-RoleXmlText([string]$Text) {
    if ($null -eq $Text) { return '' }
    return $Text.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;').Replace('"', '&quot;')
}

# Свойство JSON-объекта без учета регистра.
function Get-JsonProp($Obj, [string[]]$Names) {
    if ($null -eq $Obj) { return $null }
    foreach ($name in $Names) {
        $prop = $Obj.PSObject.Properties | Where-Object { $_.Name -ieq $name } | Select-Object -First 1
        if ($prop) { return $prop.Value }
    }
    return $null
}

# Истина для значения права.
function ConvertTo-RightOn($Value) {
    if ($Value -is [bool]) { return [bool]$Value }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) { return [int]$Value -ne 0 }
    $text = "$Value".Trim().ToLower()
    return $text -in @('true', '1', 'yes')
}

# true или false для признака роли. Пустая строка - значение не разобрано.
function ConvertTo-XmlBool($Value) {
    if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
    $text = "$Value".Trim().ToLower()
    if ($text -in @('true', '1')) { return 'true' }
    if ($text -in @('false', '0')) { return 'false' }
    return ''
}

# Пары имя права и true|false из строки, списка или словаря.
function ConvertTo-RightPairs($Spec) {
    $pairs = New-Object System.Collections.ArrayList
    if ($null -eq $Spec) { return ,$pairs }
    if ($Spec -is [string]) {
        foreach ($part in ($Spec -split ',')) {
            $name = $part.Trim()
            if ($name) { [void]$pairs.Add(@{ Name = (Translate-RightName $name); Value = 'true' }) }
        }
        return ,$pairs
    }
    if ($Spec -is [System.Array]) {
        foreach ($part in $Spec) {
            $name = "$part".Trim()
            if ($name) { [void]$pairs.Add(@{ Name = (Translate-RightName $name); Value = 'true' }) }
        }
        return ,$pairs
    }
    foreach ($prop in $Spec.PSObject.Properties) {
        $flag = 'false'
        if (ConvertTo-RightOn $prop.Value) { $flag = 'true' }
        [void]$pairs.Add(@{ Name = (Translate-RightName $prop.Name); Value = $flag })
    }
    return ,$pairs
}

# Каноническое имя операции.
function Get-OpName($Op) {
    $raw = Get-JsonProp $Op @('operation', 'op')
    if ($null -eq $raw) { return '' }
    return "$raw".Trim().ToLower()
}

# Имя объекта метаданных в каноническом написании.
function Get-OpObjectName($Op) {
    $name = Get-OpName $Op
    $raw = Get-JsonProp $Op @('object')
    if (-not $raw -and $name -notin @('add-template', 'set-template', 'remove-template', 'modify-property')) {
        $raw = Get-JsonProp $Op @('name')
    }
    if (-not $raw) { return '' }
    return Translate-ObjectName "$raw".Trim()
}

# Спецификация прав: поле rights, иначе value.
function Get-OpRightsSpec($Op) {
    $prop = $Op.PSObject.Properties | Where-Object { $_.Name -ieq 'rights' } | Select-Object -First 1
    if ($prop -and $null -ne $prop.Value) { return $prop.Value }
    $name = Get-OpName $Op
    if ($name -in @('add-rights', 'set-rights', 'remove-rights', 'deny-rights')) {
        $valueProp = $Op.PSObject.Properties | Where-Object { $_.Name -ieq 'value' } | Select-Object -First 1
        if ($valueProp -and $null -ne $valueProp.Value) { return $valueProp.Value }
    }
    return $null
}

# Имя одного права для операций RLS.
function Get-OpRightName($Op) {
    $raw = Get-JsonProp $Op @('right')
    if (-not $raw) {
        $rights = Get-JsonProp $Op @('rights')
        if ($rights -is [string]) { $raw = $rights }
    }
    if (-not $raw) { return '' }
    return Translate-RightName "$raw".Trim()
}

# Имя шаблона ограничения.
function Get-OpTemplateName($Op) {
    $raw = Get-JsonProp $Op @('template')
    if (-not $raw) { $raw = Get-JsonProp $Op @('name') }
    if (-not $raw) { return '' }
    return "$raw".Trim()
}

# Текст условия. $null - поле не задано.
function Get-OpCondition($Op) {
    $prop = $Op.PSObject.Properties | Where-Object { $_.Name -ieq 'condition' } | Select-Object -First 1
    if ($prop -and $null -ne $prop.Value) { return "$($prop.Value)" }
    $name = Get-OpName $Op
    if ($name -in @('set-rls', 'add-template', 'set-template')) {
        $valueProp = $Op.PSObject.Properties | Where-Object { $_.Name -ieq 'value' } | Select-Object -First 1
        if ($valueProp -and $null -ne $valueProp.Value) { return "$($valueProp.Value)" }
    }
    return $null
}

# Имя свойства роли и новое значение.
function Get-OpProperty($Op) {
    $prop = Get-JsonProp $Op @('property')
    $hasValue = $Op.PSObject.Properties | Where-Object { $_.Name -ieq 'value' } | Select-Object -First 1
    $value = $null
    if ($hasValue) { $value = $hasValue.Value }
    if (-not $prop -and $value -is [string] -and "$value".Contains('=')) {
        $split = "$value".Split('=', 2)
        $prop = $split[0]
        $value = $split[1]
    }
    if (-not $prop) { $prop = Get-JsonProp $Op @('name') }
    $key = $null
    if ($prop) {
        $lookup = "$prop".Trim().ToLower()
        if ($script:propMap.ContainsKey($lookup)) { $key = $script:propMap[$lookup] }
    }
    return @{ Key = $key; Raw = "$prop"; Value = $value; HasValue = [bool]$hasValue -or ($null -ne $value) }
}

# Читает JSON правки.
function ConvertTo-RoleOperations([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { Stop-RoleEdit "файл описания не найден: $Path" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $data = $raw | ConvertFrom-Json
    $items = $null
    if ($data -is [System.Array]) {
        $items = $data
    } elseif (Get-JsonProp $data @('operations')) {
        $items = @(Get-JsonProp $data @('operations'))
    } else {
        $items = @($data)
    }
    $ops = New-Object System.Collections.ArrayList
    foreach ($item in $items) {
        if ($null -eq $item) { Add-InputError 'операция: ожидался объект'; continue }
        [void]$ops.Add($item)
    }
    return ,$ops
}

# Одна операция из параметров командной строки.
function New-InlineOperation {
    $obj = [ordered]@{
        operation = $Operation
        object = $Object
        rights = $Rights
        right = $Right
        template = $Template
        condition = $Condition
        property = $Property
        value = $Value
    }
    return [pscustomobject]$obj
}

# Спецификация прав пустая: null, пустая строка, пустой список или пустой объект.
function Test-EmptySpec($Spec) {
    if ($null -eq $Spec) { return $true }
    if ($Spec -is [string] -and -not "$Spec".Trim()) { return $true }
    if ($Spec -is [System.Array] -and $Spec.Count -eq 0) { return $true }
    if ($Spec.PSObject.Properties.Count -eq 0 -and $Spec -isnot [System.Array] -and $Spec -isnot [string]) { return $true }
    return $false
}

# Проверяет операции до чтения роли.
function Test-RoleOperations($Ops) {
    if ($Ops.Count -eq 0) { Add-InputError 'нет операций'; return }
    $seen = @{}
    foreach ($op in $Ops) {
        $name = Get-OpName $op
        if ($name -notin $script:knownOps) {
            Add-InputError "неизвестная операция '$name'"
            continue
        }
        $needsObject = $name -in @('add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls')
        $obj = ''
        if ($needsObject) { $obj = Get-OpObjectName $op }
        if ($needsObject -and -not $obj) {
            Add-InputError "${name}: не задан объект"
            continue
        }
        $checkType = $name -in @('add-rights', 'set-rights', 'deny-rights', 'set-rls')
        if ($checkType -and -not $seen.ContainsKey($obj)) {
            Test-ObjectTypeKnown $obj | Out-Null
            Test-NestedKind $obj | Out-Null
            $seen[$obj] = $true
        }
        if ($name -in @('add-rights', 'set-rights', 'remove-rights', 'deny-rights')) {
            $spec = Get-OpRightsSpec $op
            if ((Test-EmptySpec $spec) -and -not ($name -eq 'set-rights' -and $null -ne $spec)) {
                Add-InputError "${name}: не заданы права"
                continue
            }
            if ($name -eq 'set-rights' -and (Test-EmptySpec $spec) -and $null -ne $spec) { continue }
            $pairs = ConvertTo-RightPairs $spec
            if ($name -ne 'remove-rights') {
                foreach ($pair in $pairs) { Validate-RightName -objectName $obj -rightName $pair.Name | Out-Null }
            }
            if ($name -in @('add-rights', 'deny-rights', 'remove-rights') -and $pairs.Count -eq 0) {
                Add-InputError "${name}: не заданы права"
            }
        } elseif ($name -eq 'set-rls') {
            $rightName = Get-OpRightName $op
            if (-not $rightName) { Add-InputError 'set-rls: не задано право' }
            else { Validate-RightName -objectName $obj -rightName $rightName | Out-Null }
            $rlsKind = if (Is-NestedObject $obj) { $obj.Split('.')[-2] } else { $null }
            if ($rlsKind -and $rlsKind -in $script:nestedConditionDroppedKinds) {
                Add-InputError "${obj}: платформа не хранит условие ограничения доступа у вида '$rlsKind'"
            }
            if ($null -eq (Get-OpCondition $op)) { Add-InputError 'set-rls: не задано условие' }
        } elseif ($name -eq 'remove-rls') {
            if (-not (Get-OpRightName $op)) { Add-InputError 'remove-rls: не задано право' }
        } elseif ($name -in @('add-template', 'set-template')) {
            if (-not (Get-OpTemplateName $op)) { Add-InputError "${name}: не задано имя шаблона" }
            if ($null -eq (Get-OpCondition $op)) { Add-InputError "${name}: не задано условие" }
        } elseif ($name -eq 'remove-template') {
            if (-not (Get-OpTemplateName $op)) { Add-InputError 'remove-template: не задано имя шаблона' }
        } elseif ($name -eq 'modify-property') {
            $parsed = Get-OpProperty $op
            if (-not $parsed.Key) { Add-InputError "неизвестное свойство '$($parsed.Raw)'" }
            elseif (-not $parsed.HasValue -or $null -eq $parsed.Value) { Add-InputError "$($parsed.Key): не задано значение" }
            elseif ($parsed.Key -in $script:flagProps -and -not (ConvertTo-XmlBool $parsed.Value)) {
                Add-InputError "$($parsed.Key): ожидалось true или false"
            }
        }
    }
}

# Текст файла, признак BOM и признак CRLF. Переводы строк внутри - LF.
function Read-RoleText([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $bom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $enc = New-Object System.Text.UTF8Encoding $false
    $start = 0
    if ($bom) { $start = 3 }
    $text = $enc.GetString($bytes, $start, $bytes.Length - $start)
    $crlf = $text.Contains("`r`n")
    return @{ Text = $text.Replace("`r`n", "`n"); Bom = $bom; Crlf = $crlf }
}

# Пишет текст в исходной кодировке файла.
function Write-RoleText([string]$Path, [string]$Text, [bool]$Bom, [bool]$Crlf) {
    if ($Crlf) { $Text = $Text.Replace("`n", "`r`n") }
    $enc = New-Object System.Text.UTF8Encoding $Bom
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

# Пара путей: файл метаданных роли и Ext/Rights.xml.
function Resolve-RolePaths([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $full -PathType Container) {
        if ([System.IO.Path]::GetFileName($full) -eq 'Ext') {
            return Resolve-RolePaths (Join-Path $full 'Rights.xml')
        }
        $name = [System.IO.Path]::GetFileName($full)
        $meta = Join-Path (Split-Path $full -Parent) ($name + '.xml')
        $rights = Join-Path $full 'Ext\Rights.xml'
        return @{ Meta = $meta; Rights = $rights }
    }
    if ([System.IO.Path]::GetFileName($full) -eq 'Rights.xml') {
        $roleDir = Split-Path (Split-Path $full -Parent) -Parent
        $name = Split-Path $roleDir -Leaf
        $meta = Join-Path (Split-Path $roleDir -Parent) ($name + '.xml')
        return @{ Meta = $meta; Rights = $full }
    }
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($full)
    $meta = $full
    if (-not $full.ToLower().EndsWith('.xml')) { $meta = $full + '.xml' }
    $rights = Join-Path (Join-Path (Split-Path $meta -Parent) $baseName) 'Ext\Rights.xml'
    return @{ Meta = $meta; Rights = $rights }
}

# Единица отступа файла.
function Get-IndentUnit([string]$Text) {
    $match = [regex]::Match($Text, '\n([ \t]+)<(?:object|setForNewObjects|restrictionTemplate)>')
    if ($match.Success) { return $match.Groups[1].Value }
    return "`t"
}

# Блоки object: имя, права и границы.
function Find-RoleObjects([string]$Text) {
    $found = New-Object System.Collections.ArrayList
    foreach ($match in [regex]::Matches($Text, '(?s)[ \t]*<object>.*?</object>')) {
        $block = $match.Value
        $nameMatch = [regex]::Match($block, '(?s)<name>(.*?)</name>')
        $rights = New-Object System.Collections.ArrayList
        foreach ($rightMatch in [regex]::Matches($block, '(?s)<right>\s*<name>(.*?)</name>\s*<value>(.*?)</value>(.*?)</right>')) {
            $condition = $null
            $condMatch = [regex]::Match($rightMatch.Groups[3].Value, '(?s)<condition>(.*?)</condition>')
            if ($condMatch.Success) {
                $condition = [System.Net.WebUtility]::HtmlDecode($condMatch.Groups[1].Value)
            }
            [void]$rights.Add(@{
                Name = [System.Net.WebUtility]::HtmlDecode($rightMatch.Groups[1].Value.Trim())
                Value = $rightMatch.Groups[2].Value.Trim()
                Condition = $condition
            })
        }
        $objName = ''
        if ($nameMatch.Success) { $objName = [System.Net.WebUtility]::HtmlDecode($nameMatch.Groups[1].Value.Trim()) }
        [void]$found.Add(@{
            start = $match.Index
            end = ($match.Index + $match.Length)
            name = $objName
            rights = $rights
        })
    }
    return ,$found
}

# Блок object в оформлении выгрузки.
function Render-RoleObject([string]$Name, $Rights, [string]$Unit) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("$Unit<object>")
    $lines.Add("$($Unit * 2)<name>$(Format-RoleXmlText $Name)</name>")
    foreach ($right in $Rights) {
        $lines.Add("$($Unit * 2)<right>")
        $lines.Add("$($Unit * 3)<name>$(Format-RoleXmlText $right.Name)</name>")
        $lines.Add("$($Unit * 3)<value>$($right.Value)</value>")
        if ($right.Condition) {
            $lines.Add("$($Unit * 3)<restrictionByCondition>")
            $lines.Add("$($Unit * 4)<condition>$(Format-RoleXmlText $right.Condition)</condition>")
            $lines.Add("$($Unit * 3)</restrictionByCondition>")
        }
        $lines.Add("$($Unit * 2)</right>")
    }
    $lines.Add("$Unit</object>")
    return ($lines -join "`n")
}

# Замыкание включенных прав и канонический порядок.
function Complete-RoleRights([string]$ObjectName, $Rights) {
    $map = [ordered]@{}
    foreach ($right in @($Rights)) {
        if (-not $map.Contains($right.Name)) {
            $map[$right.Name] = @{ Value = $right.Value; Condition = $right.Condition }
        }
    }
    return @(Finish-Rights -ObjectName $ObjectName -RightsMap $map)
}

# Возвращает прежние условия RLS правам, которые после замыкания остались включенными.
# Замыкание дописывает недостающее право с пустым условием; если это право в роли уже было
# с условием, ограничение сохраняется, а не снимается молча.
function Restore-RoleConditions($Current, $NewRights) {
    $old = @{}
    foreach ($right in @($Current)) { $old[$right.Name] = $right.Condition }
    foreach ($right in @($NewRights)) {
        if ($right.Value -eq 'true' -and -not $right.Condition -and $old[$right.Name]) {
            $right.Condition = $old[$right.Name]
        }
    }
    return @($NewRights)
}

# Подменяет отрезок. Пустой Block удаляет отрезок вместе с переводом перед ним.
function Splice-Span([string]$Text, [int]$Start, [int]$End, $Block) {
    if ($null -eq $Block) {
        if ($Start -gt 0 -and $Text[$Start - 1] -eq "`n") { $Start = $Start - 1 }
        return $Text.Substring(0, $Start) + $Text.Substring($End)
    }
    return $Text.Substring(0, $Start) + $Block + $Text.Substring($End)
}

# Вставляет блок перед первым тегом либо перед закрытием Rights.
function Insert-BeforeClose([string]$Text, [string]$Block, [string]$Tag) {
    $match = [regex]::Match($Text, "\n[ \t]*<$Tag>")
    if (-not $match.Success -and $Tag -ne '/Rights') {
        $match = [regex]::Match($Text, '\n[ \t]*</Rights>')
    }
    if (-not $match.Success) { Stop-RoleEdit 'Rights.xml: нет закрывающего тега Rights' }
    return $Text.Substring(0, $match.Index) + "`n" + $Block + $Text.Substring($match.Index)
}

# Одна операция над правами или RLS. Чужие объекты не переписываются.
function Apply-RightsOp([string]$Text, $Op) {
    $name = Get-OpName $Op
    $objName = Get-OpObjectName $Op
    $unit = Get-IndentUnit $Text
    $objects = Find-RoleObjects $Text
    $index = -1
    for ($i = 0; $i -lt $objects.Count; $i++) {
        if ($objects[$i].name -eq $objName) { $index = $i; break }
    }
    $current = @()
    if ($index -ge 0) { $current = @($objects[$index].rights) }

    if ($name -eq 'remove-rights') {
        if ($index -lt 0) { return $Text }
        $pairs = ConvertTo-RightPairs (Get-OpRightsSpec $Op)
        $drop = @{}
        foreach ($pair in $pairs) { $drop[$pair.Name] = $true }
        $kept = New-Object System.Collections.ArrayList
        foreach ($right in $current) {
            if (-not $drop.ContainsKey($right.Name)) { [void]$kept.Add($right) }
        }
        $newRights = @(Restore-RoleConditions $current @(Complete-RoleRights $objName $kept))
        foreach ($removed in @($drop.Keys)) {
            $back = $false
            foreach ($right in $newRights) {
                if ($right.Name -eq $removed -and $right.Value -eq 'true') { $back = $true }
            }
            if ($back) {
                [Console]::Error.WriteLine("WARNING: ${objName}: право '$removed' снято, но замыкание снова включает его")
            }
        }
        $block = $null
        if ($newRights.Count -gt 0) { $block = Render-RoleObject $objName $newRights $unit }
        return Splice-Span $Text $objects[$index].start $objects[$index].end $block
    }

    if ($name -eq 'remove-rls') {
        if ($index -lt 0) { return $Text }
        $rightName = Get-OpRightName $Op
        $changed = $false
        $newRights = New-Object System.Collections.ArrayList
        foreach ($right in $current) {
            $item = @{ Name = $right.Name; Value = $right.Value; Condition = $right.Condition }
            if ($item.Name -eq $rightName -and $item.Condition) {
                $item.Condition = $null
                $changed = $true
            }
            [void]$newRights.Add($item)
        }
        if (-not $changed) { return $Text }
        $block = Render-RoleObject $objName $newRights $unit
        return Splice-Span $Text $objects[$index].start $objects[$index].end $block
    }

    if ($name -eq 'set-rights') {
        $pairs = ConvertTo-RightPairs (Get-OpRightsSpec $Op)
        $old = @{}
        foreach ($right in $current) { $old[$right.Name] = $right }
        $map = [ordered]@{}
        foreach ($pair in $pairs) {
            if (-not $map.Contains($pair.Name)) {
                $cond = $null
                if ($old.ContainsKey($pair.Name)) { $cond = $old[$pair.Name].Condition }
                $map[$pair.Name] = @{ Value = $pair.Value; Condition = $cond }
            }
        }
        $newRights = @(Restore-RoleConditions $current @(Finish-Rights -ObjectName $objName -RightsMap $map))
    } elseif ($name -eq 'set-rls') {
        $map = [ordered]@{}
        foreach ($right in $current) {
            $map[$right.Name] = @{ Value = $right.Value; Condition = $right.Condition }
        }
        $rightName = Get-OpRightName $Op
        $condition = Get-OpCondition $Op
        if ($map.Contains($rightName)) {
            $map[$rightName].Value = 'true'
            $map[$rightName].Condition = $condition
        } else {
            $map[$rightName] = @{ Value = 'true'; Condition = $condition }
        }
        $newRights = @(Finish-Rights -ObjectName $objName -RightsMap $map)
    } else {
        $pairs = ConvertTo-RightPairs (Get-OpRightsSpec $Op)
        if ($name -eq 'deny-rights') {
            foreach ($pair in $pairs) { $pair.Value = 'false' }
        }
        $map = [ordered]@{}
        foreach ($right in $current) {
            $map[$right.Name] = @{ Value = $right.Value; Condition = $right.Condition }
        }
        foreach ($pair in $pairs) {
            if ($map.Contains($pair.Name)) { $map[$pair.Name].Value = $pair.Value }
            else { $map[$pair.Name] = @{ Value = $pair.Value; Condition = $null } }
        }
        $newRights = @(Finish-Rights -ObjectName $objName -RightsMap $map)
    }

    $block = $null
    if ($newRights.Count -gt 0) { $block = Render-RoleObject $objName $newRights $unit }
    if ($index -lt 0) {
        if ($null -eq $block) { return $Text }
        if ($objects.Count -gt 0) {
            $end = $objects[$objects.Count - 1].end
            return $Text.Substring(0, $end) + "`n" + $block + $Text.Substring($end)
        }
        return Insert-BeforeClose $Text $block 'restrictionTemplate'
    }
    return Splice-Span $Text $objects[$index].start $objects[$index].end $block
}

# Шаблоны ограничения.
function Find-RoleTemplates([string]$Text) {
    $found = New-Object System.Collections.ArrayList
    $pattern = '(?s)[ \t]*<restrictionTemplate>\s*<name>(.*?)</name>\s*<condition>(.*?)</condition>\s*</restrictionTemplate>'
    foreach ($match in [regex]::Matches($Text, $pattern)) {
        [void]$found.Add(@{
            start = $match.Index
            end = ($match.Index + $match.Length)
            name = [System.Net.WebUtility]::HtmlDecode($match.Groups[1].Value.Trim())
            condition = [System.Net.WebUtility]::HtmlDecode($match.Groups[2].Value)
        })
    }
    return ,$found
}

# Блок restrictionTemplate.
function Render-RoleTemplate([string]$Name, [string]$Condition, [string]$Unit) {
    $safeName = Format-RoleXmlText $Name
    $safeCond = Format-RoleXmlText $Condition
    return @(
        "$Unit<restrictionTemplate>",
        "$($Unit * 2)<name>$safeName</name>",
        "$($Unit * 2)<condition>$safeCond</condition>",
        "$Unit</restrictionTemplate>"
    ) -join "`n"
}

# Добавление, замена или снятие шаблона.
function Apply-TemplateOp([string]$Text, $Op) {
    $name = Get-OpName $Op
    $template = Get-OpTemplateName $Op
    $unit = Get-IndentUnit $Text
    $found = Find-RoleTemplates $Text
    $index = -1
    for ($i = 0; $i -lt $found.Count; $i++) {
        if ($found[$i].name -eq $template) { $index = $i; break }
    }
    if ($name -eq 'remove-template') {
        if ($index -lt 0) { return $Text }
        return Splice-Span $Text $found[$index].start $found[$index].end $null
    }
    $condition = Get-OpCondition $Op
    if ($index -ge 0 -and $found[$index].condition -eq $condition) { return $Text }
    if ($name -eq 'add-template' -and $index -ge 0) {
        Add-InputError "шаблон '$template' уже есть, для замены используйте set-template"
        return $Text
    }
    $block = Render-RoleTemplate $template $condition $unit
    if ($index -lt 0) { return Insert-BeforeClose $Text $block '/Rights' }
    return Splice-Span $Text $found[$index].start $found[$index].end $block
}

# Меняет русский синоним, не трогая uuid и остальные языки.
function Update-RoleSynonym([string]$Text, $Value) {
    $pattern = '(?s)(<Synonym\b[^>]*>.*?<v8:lang>\s*ru\s*</v8:lang>\s*<v8:content>)(.*?)(</v8:content>)'
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) { return $null }
    $safe = Format-RoleXmlText "$Value"
    $content = $match.Groups[2]
    return $Text.Substring(0, $content.Index) + $safe + $Text.Substring($content.Index + $content.Length)
}

# Меняет комментарий роли. Пустая строка записывается пустым тегом.
function Update-RoleComment([string]$Text, $Value) {
    $safe = Format-RoleXmlText "$Value"
    if ([regex]::IsMatch($Text, '<Comment\s*/>')) {
        if (-not $safe) { return $Text }
        $match = [regex]::Match($Text, '<Comment\s*/>')
        return $Text.Substring(0, $match.Index) + '<Comment>' + $safe + '</Comment>' + $Text.Substring($match.Index + $match.Length)
    }
    $full = [regex]::Match($Text, '(?s)<Comment\b[^>]*>.*?</Comment>')
    if ($full.Success) {
        if (-not $safe) {
            return $Text.Substring(0, $full.Index) + '<Comment/>' + $Text.Substring($full.Index + $full.Length)
        }
        $inner = [regex]::Match($Text, '(?s)(<Comment\b[^>]*>)(.*?)(</Comment>)')
        $content = $inner.Groups[2]
        return $Text.Substring(0, $content.Index) + $safe + $Text.Substring($content.Index + $content.Length)
    }
    return $null
}

# Меняет текст признака роли в Rights.xml.
function Update-RoleFlag([string]$Text, [string]$Tag, [string]$Value) {
    $pattern = "(<$Tag>)(\s*)(true|false)(\s*)(</$Tag>)"
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) { return $null }
    $flag = $match.Groups[3]
    return $Text.Substring(0, $flag.Index) + $Value + $Text.Substring($flag.Index + $flag.Length)
}

# Меняет синоним, комментарий или признак.
function Apply-PropertyOp([string]$Rights, [string]$Meta, $Op) {
    $parsed = Get-OpProperty $Op
    if ($parsed.Key -in @('synonym', 'comment')) {
        if ($parsed.Key -eq 'synonym') { $updated = Update-RoleSynonym $Meta $parsed.Value }
        else {
            $comment = ''
            if ($null -ne $parsed.Value) { $comment = "$($parsed.Value)" }
            $updated = Update-RoleComment $Meta $comment
        }
        if ($null -eq $updated) {
            Add-InputError "$($parsed.Key): в файле роли нет этого свойства"
            return @{ Rights = $Rights; Meta = $Meta }
        }
        return @{ Rights = $Rights; Meta = $updated }
    }
    $flag = ConvertTo-XmlBool $parsed.Value
    $updated = Update-RoleFlag $Rights $parsed.Key $flag
    if ($null -eq $updated) {
        Add-InputError "$($parsed.Key): в Rights.xml нет этого признака"
        return @{ Rights = $Rights; Meta = $Meta }
    }
    return @{ Rights = $updated; Meta = $Meta }
}

function Update-NestedDefaults([string]$Text) {
	# Приводит вложенные права к тому, что оставляет выгрузка платформы.
	$sfab = $true
	$flag = [regex]::Match($Text, '<setForAttributesByDefault>(.*?)</setForAttributesByDefault>')
	if ($flag.Success) { $sfab = $flag.Groups[1].Value.Trim().ToLower() -eq 'true' }
	$unit = Get-IndentUnit $Text
	$objects = Find-RoleObjects $Text
	for ($i = $objects.Count - 1; $i -ge 0; $i--) {
		$obj = $objects[$i]
		if (-not (Is-NestedObject $obj.name)) { continue }
		$kept = New-Object System.Collections.ArrayList
		foreach ($right in @(Close-NestedViewEdit -ObjectName $obj.name -Rights @($obj.rights) -SetForAttributesByDefault $sfab)) {
			if (Test-NestedDefaultRightKept -ObjectName $obj.name -RightName $right.Name -Value "$($right.Value)" -SetForAttributesByDefault $sfab -Condition "$($right.Condition)") {
				[void]$kept.Add($right)
			}
		}
		$keptKey = (@($kept) | ForEach-Object { "$($_.Name)=$($_.Value)|$($_.Condition)" }) -join ';'
		$currentKey = (@($obj.rights) | ForEach-Object { "$($_.Name)=$($_.Value)|$($_.Condition)" }) -join ';'
		if ($keptKey -eq $currentKey) { continue }
		$block = $null
		if ($kept.Count -gt 0) { $block = Render-RoleObject $obj.name $kept $unit }
		$Text = Splice-Span $Text ([int]$obj.start) ([int]$obj.end) $block
	}
	return $Text
}

function Write-FieldWithoutObjectWarning([string]$Text) {
	# Предупреждает, если при обычных флажках остались права на поля без прав на объект.
	$sfab = $true
	$irco = $false
	$sfabMatch = [regex]::Match($Text, '<setForAttributesByDefault>(.*?)</setForAttributesByDefault>')
	$ircoMatch = [regex]::Match($Text, '<independentRightsOfChildObjects>(.*?)</independentRightsOfChildObjects>')
	if ($sfabMatch.Success) { $sfab = $sfabMatch.Groups[1].Value.Trim().ToLower() -eq 'true' }
	if ($ircoMatch.Success) { $irco = $ircoMatch.Groups[1].Value.Trim().ToLower() -eq 'true' }
	if (-not $sfab -or $irco) { return }
	$objects = Find-RoleObjects $Text
	$parents = @{}
	foreach ($obj in $objects) {
		if (-not (Is-NestedObject $obj.name)) { $parents[$obj.name] = $true }
	}
	$seen = @{}
	$fieldKinds = @('Attribute', 'TabularSection', 'StandardAttribute')
	foreach ($obj in $objects) {
		$parts = @($obj.name -split '\.')
		if ($parts.Count -lt 4) { continue }
		$isField = $false
		for ($i = 2; $i -lt $parts.Count; $i += 2) {
			if ($parts[$i] -in $fieldKinds) { $isField = $true }
		}
		if (-not $isField) { continue }
		$parent = "$($parts[0]).$($parts[1])"
		if ($parents.ContainsKey($parent) -or $seen.ContainsKey($parent)) { continue }
		$seen[$parent] = $true
		[Console]::Error.WriteLine("WARNING: ${parent}: права на поля без прав на объект при setForAttributesByDefault=true и independentRightsOfChildObjects=false (#std532)")
	}
}

# Применяет операции по порядку.
function Apply-RoleOps([string]$Rights, [string]$Meta, $Ops) {
    foreach ($op in $Ops) {
        $name = Get-OpName $op
        if ($name -in @('add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls')) {
            $Rights = Apply-RightsOp $Rights $op
        } elseif ($name -in @('add-template', 'set-template', 'remove-template')) {
            $Rights = Apply-TemplateOp $Rights $op
        } elseif ($name -eq 'modify-property') {
            $pair = Apply-PropertyOp $Rights $Meta $op
            $Rights = $pair.Rights
            $Meta = $pair.Meta
        }
        if ($script:inputErrors.Count -gt 0) { break }
    }
    return @{ Rights = $Rights; Meta = $Meta }
}

# Имя роли из метаданных, иначе из имени файла.
function Get-RoleLabel([string]$MetaText, [string]$MetaPath) {
    $match = [regex]::Match($MetaText, '<Name>(.*?)</Name>')
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return [System.IO.Path]::GetFileNameWithoutExtension($MetaPath)
}

# --- Точка входа ---
if ($DefinitionFile -and $Operation) { Stop-RoleEdit '-DefinitionFile и -Operation вместе не задают' }
if (-not $DefinitionFile -and -not $Operation) { Stop-RoleEdit 'укажите -DefinitionFile или -Operation' }

if ($DefinitionFile) {
    $ops = ConvertTo-RoleOperations $DefinitionFile
} else {
    $ops = New-Object System.Collections.ArrayList
    [void]$ops.Add((New-InlineOperation))
}

Test-RoleOperations $ops
Exit-InputErrors

$paths = Resolve-RolePaths $RolePath
if (-not (Test-Path -LiteralPath $paths.Meta)) { Stop-RoleEdit "файл роли не найден: $($paths.Meta)" }
if (-not (Test-Path -LiteralPath $paths.Rights)) { Stop-RoleEdit "файл прав не найден: $($paths.Rights)" }
Assert-EditAllowed -targetPath $paths.Meta -require 'editable'

$rightsFile = Read-RoleText $paths.Rights
$metaFile = Read-RoleText $paths.Meta
$edited = Apply-RoleOps $rightsFile.Text $metaFile.Text $ops
if ($script:inputErrors.Count -eq 0) {
	$edited.Rights = Update-NestedDefaults $edited.Rights
	Write-FieldWithoutObjectWarning $edited.Rights
}
Exit-InputErrors

if ($edited.Rights -ne $rightsFile.Text) {
    Write-RoleText $paths.Rights $edited.Rights $rightsFile.Bom $rightsFile.Crlf
}
if ($edited.Meta -ne $metaFile.Text) {
    Write-RoleText $paths.Meta $edited.Meta $metaFile.Bom $metaFile.Crlf
}

$label = Get-RoleLabel $edited.Meta $paths.Meta
[Console]::Out.WriteLine("role-edit: $label, операций $($ops.Count)")

if (-not $NoValidate) {
    $validateScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '1c-role-validate\scripts\role-validate.ps1'
    if (Test-Path -LiteralPath $validateScript) {
        [Console]::Out.WriteLine('--- role-validate ---')
        & powershell.exe -NoProfile -File $validateScript -RightsPath $paths.Rights
    }
}

