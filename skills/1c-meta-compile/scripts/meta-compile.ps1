# meta-compile v1.10 - Compile 1C metadata object from JSON
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$JsonPath,

	[Parameter(Mandatory)]
	[string]$OutputDir
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

# --- 1. Load and validate JSON ---

if (-not (Test-Path $JsonPath)) {
	Write-Error "File not found: $JsonPath"
	exit 1
}

$json = Get-Content -Raw -Encoding UTF8 $JsonPath
$def = $json | ConvertFrom-Json

# --- Batch mode: JSON array of objects ---
if ($def -is [array] -or ($null -ne $def -and $def.GetType().BaseType.Name -eq 'Array')) {
	$batchOk = 0
	$batchFail = 0
	$idx = 0
	foreach ($item in $def) {
		$idx++
		# Имя временного файла уникально по процессу: два одновременных пакетных
		# запуска иначе пишут в один и тот же файл и портят друг другу вход.
		$tmpJson = Join-Path ([System.IO.Path]::GetTempPath()) "meta-compile-batch-$PID-$idx-$([guid]::NewGuid().ToString('N')).json"
		try {
			$item | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $tmpJson
			# Тот же интерпретатор, что запустил этот скрипт: имя powershell.exe выбирает версию 5.1,
			# которая иначе разбирает кириллицу в передаваемом определении.
			$hostExe = (Get-Process -Id $PID).Path
			if (-not $hostExe) { $hostExe = "pwsh.exe" }
			$proc = Start-Process -FilePath $hostExe -ArgumentList "-NoProfile -File `"$PSCommandPath`" -JsonPath `"$tmpJson`" -OutputDir `"$OutputDir`"" -NoNewWindow -Wait -PassThru
			if ($proc.ExitCode -eq 0) { $batchOk++ } else { $batchFail++ }
		} finally {
			Remove-Item $tmpJson -Force -ErrorAction SilentlyContinue
		}
	}
	Write-Host ""
	Write-Host "=== Batch: $idx objects, $batchOk compiled, $batchFail failed ==="
	if ($batchFail -gt 0) { exit 1 }
	exit 0
}

# Normalize field synonyms: accept "objectType" as alias for "type"
if (-not $def.type -and $def.objectType) {
	$def | Add-Member -NotePropertyName "type" -NotePropertyValue $def.objectType
}

# Object type synonyms (Russian → English)
$script:objectTypeSynonyms = @{
	"Справочник"              = "Catalog"
	"Каталог"                 = "Catalog"
	"Документ"                = "Document"
	"Перечисление"            = "Enum"
	"Константа"               = "Constant"
	"РегистрСведений"         = "InformationRegister"
	"РегистрНакопления"       = "AccumulationRegister"
	"РегистрБухгалтерии"      = "AccountingRegister"
	"РегистрРасчёта"          = "CalculationRegister"
	"РегистрРасчета"          = "CalculationRegister"
	"ПланСчетов"              = "ChartOfAccounts"
	"ПланВидовХарактеристик"  = "ChartOfCharacteristicTypes"
	"ПланВидовРасчёта"        = "ChartOfCalculationTypes"
	"ПланВидовРасчета"        = "ChartOfCalculationTypes"
	"БизнесПроцесс"           = "BusinessProcess"
	"Задача"                  = "Task"
	"ПланОбмена"              = "ExchangePlan"
	"ЖурналДокументов"        = "DocumentJournal"
	"Отчёт"                   = "Report"
	"Отчет"                   = "Report"
	"Обработка"               = "DataProcessor"
	"ОбщийМодуль"             = "CommonModule"
	"РегламентноеЗадание"     = "ScheduledJob"
	"ПодпискаНаСобытие"       = "EventSubscription"
	"HTTPСервис"              = "HTTPService"
	"ВебСервис"               = "WebService"
	"ОпределяемыйТип"         = "DefinedType"
	"ОбщийРеквизит"           = "CommonAttribute"
	"ОбщаяКоманда"            = "CommonCommand"
	"ГруппаКоманд"            = "CommandGroup"
	"ОбщаяФорма"              = "CommonForm"
	"ОбщийМакет"              = "CommonTemplate"
	"ОбщаяКартинка"           = "CommonPicture"
	"КритерийОтбора"          = "FilterCriterion"
	"Последовательность"      = "Sequence"
	"НумераторДокументов"     = "DocumentNumerator"
	"ПараметрСеанса"          = "SessionParameter"
	"ХранилищеНастроек"       = "SettingsStorage"
	"ФункциональнаяОпция"     = "FunctionalOption"
	"ПараметрФункциональныхОпций" = "FunctionalOptionsParameter"
	"WSСсылка"                = "WSReference"
}

# Enum property value synonyms - model often gets these slightly wrong
$script:enumValueAliases = @{
	# RegisterType (AccumulationRegister)
	"Balances"  = "Balance";  "Остатки" = "Balance";  "Обороты" = "Turnovers"
	# WriteMode (InformationRegister)
	"RecordSubordinate" = "RecorderSubordinate"; "Subordinate" = "RecorderSubordinate"
	"ПодчинениеРегистратору" = "RecorderSubordinate"; "Независимый" = "Independent"
	# DependenceOnCalculationTypes (ChartOfCalculationTypes)
	"NotDependOnCalculationTypes" = "DontUse"; "NoDependence" = "DontUse"; "NotUsed" = "DontUse"
	"Depend" = "OnActionPeriod"; "ПоПериодуДействия" = "OnActionPeriod"
	# InformationRegisterPeriodicity
	"None" = "Nonperiodical"; "Daily" = "Day"; "Monthly" = "Month"
	"Quarterly" = "Quarter"; "Yearly" = "Year"
	"Непериодический" = "Nonperiodical"; "Секунда" = "Second"; "День" = "Day"
	"Месяц" = "Month"; "Квартал" = "Quarter"; "Год" = "Year"
	"ПозицияРегистратора" = "RecorderPosition"
	# DataLockControlMode
	"Автоматический" = "Automatic"; "Управляемый" = "Managed"
	# FullTextSearch
	"Использовать" = "Use"; "НеИспользовать" = "DontUse"
	# Posting
	"Разрешить" = "Allow"; "Запретить" = "Deny"
	# EditType
	"ВДиалоге" = "InDialog"; "ВСписке" = "InList"; "ОбаСпособа" = "BothWays"
	# DefaultPresentation
	"ВВидеНаименования" = "AsDescription"; "ВВидеКода" = "AsCode"
	# FillChecking
	"НеПроверять" = "DontCheck"; "Ошибка" = "ShowError"; "Предупреждение" = "ShowWarning"
	# Indexing
	"НеИндексировать" = "DontIndex"; "Индексировать" = "Index"
	"ИндексироватьСДопУпорядочиванием" = "IndexWithAdditionalOrder"
}

# Valid enum values per property (from meta-validate)
$script:validEnumValues = @{
	"RegisterType"                   = @("Balance","Turnovers")
	"WriteMode"                      = @("Independent","RecorderSubordinate")
	"InformationRegisterPeriodicity" = @("Nonperiodical","Second","Day","Month","Quarter","Year","RecorderPosition")
	"DependenceOnCalculationTypes"   = @("DontUse","OnActionPeriod")
	"DataLockControlMode"            = @("Automatic","Managed")
	"FullTextSearch"                 = @("Use","DontUse")
	"DataHistory"                    = @("Use","DontUse")
	"DefaultPresentation"            = @("AsDescription","AsCode")
	"Posting"                        = @("Allow","Deny")
	"RealTimePosting"                = @("Allow","Deny")
	"EditType"                       = @("InDialog","InList","BothWays")
	"HierarchyType"                  = @("HierarchyFoldersAndItems","HierarchyItemsOnly")
	"CodeType"                       = @("String","Number")
	"CodeAllowedLength"              = @("Variable","Fixed")
	"NumberType"                     = @("String","Number")
	"NumberAllowedLength"            = @("Variable","Fixed")
	"RegisterRecordsDeletion"        = @("AutoDelete","AutoDeleteOnUnpost","AutoDeleteOff")
	"RegisterRecordsWritingOnPost"   = @("WriteModified","WriteSelected","WriteAll")
	"ReturnValuesReuse"              = @("DontUse","DuringRequest","DuringSession")
	"ReuseSessions"                  = @("DontUse","Use","AutoUse")
	"FillChecking"                   = @("DontCheck","ShowError","ShowWarning")
	"Indexing"                       = @("DontIndex","Index","IndexWithAdditionalOrder")
	"SubordinationUse"               = @("ToItems","ToFolders","ToFoldersAndItems")
	"CodeSeries"                     = @("WholeCatalog","WithinSubordination")
	"ChoiceMode"                     = @("BothWays","QuickChoice","FromForm")
}

function Normalize-EnumValue {
	param([string]$propName, [string]$value)
	# 1. Check alias dictionary - silent auto-correct
	if ($script:enumValueAliases.ContainsKey($value)) {
		return $script:enumValueAliases[$value]
	}
	# 2. Case-insensitive match against valid values - silent
	$valid = $script:validEnumValues[$propName]
	if ($valid) {
		foreach ($v in $valid) {
			if ($v -ieq $value) { return $v }
		}
		# 3. Known property, unknown value - error with hint
		Write-Error "Invalid value '$value' for property '$propName'. Valid values: $($valid -join ', ')"
		exit 1
	}
	# 4. Unknown property - pass-through (no validation data)
	return $value
}

# Helper: read enum property from $def with default and normalization
function Get-EnumProp {
	param([string]$propName, [string]$fieldName, [string]$default)
	$val = $def.$fieldName
	$raw = if ($val) { "$val" } else { $default }
	return (Normalize-EnumValue $propName $raw)
}

if (-not $def.type) {
	Write-Error "JSON must have 'type' field"
	exit 1
}

# Resolve type synonym
$objType = "$($def.type)"
if ($script:objectTypeSynonyms.ContainsKey($objType)) {
	$objType = $script:objectTypeSynonyms[$objType]
}

$validTypes = @("Catalog","Document","Enum","Constant","InformationRegister","AccumulationRegister",
	"AccountingRegister","CalculationRegister","ChartOfAccounts","ChartOfCharacteristicTypes",
	"ChartOfCalculationTypes","BusinessProcess","Task","ExchangePlan","DocumentJournal",
	"Report","DataProcessor","CommonModule","ScheduledJob","EventSubscription",
	"HTTPService","WebService","DefinedType",
	"CommonAttribute","CommonCommand","CommandGroup","CommonForm","CommonTemplate",
	"CommonPicture","FilterCriterion","Sequence","DocumentNumerator","SessionParameter",
	"SettingsStorage","FunctionalOption","FunctionalOptionsParameter","WSReference")
if ($objType -notin $validTypes) {
	Write-Error "Unsupported type: $objType. Valid: $($validTypes -join ', ')"
	exit 1
}
# Регистр имени типа приводится к каноническому. Сравнение выше регистронезависимо, поэтому
# "catalog" его проходит - и раньше уходило в XML как <catalog>. Платформа на таком теге не
# ругается, а МОЛЧА выбрасывает объект: "не является подчиненным для объекта Configuration",
# код возврата 0, объекта в базе нет. Замерено на 8.3.27.
$canonicalType = $validTypes | Where-Object { $_ -ieq $objType } | Select-Object -First 1
if ($canonicalType) { $objType = $canonicalType }

if (-not $def.name) {
	Write-Error "JSON must have 'name' field"
	exit 1
}

$objName = "$($def.name)"

# --- 2. XML helpers ---

$script:xml = New-Object System.Text.StringBuilder 32768

function X {
	param([string]$text)
	$script:xml.AppendLine($text) | Out-Null
}

function Esc-Xml {
	param([string]$s)
	return $s.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

function Emit-MLText {
	param([string]$indent, [string]$tag, $text)
	if (-not $text) {
		X "$indent<$tag/>"
		return
	}
	# Значение бывает строкой (тогда это русский вариант) и объектом { ru = "..."; en = "..." }.
	# Раньше параметр был [string], объект приводился к "@{ru=...; en=...}" и уезжал в XML целиком.
	$mlItems = @()
	if ($text -is [string]) {
		$mlItems += @{ lang = "ru"; content = $text }
	} else {
		foreach ($mlProp in $text.PSObject.Properties) {
			$mlItems += @{ lang = $mlProp.Name; content = "$($mlProp.Value)" }
		}
	}
	X "$indent<$tag>"
	foreach ($mlItem in $mlItems) {
		X "$indent`t<v8:item>"
		# Пустой язык платформа пишет одиночным тегом: пара с пустым содержимым не совпадает
		# с выгрузкой.
		if ($mlItem.lang) {
			X "$indent`t`t<v8:lang>$($mlItem.lang)</v8:lang>"
		} else {
			X "$indent`t`t<v8:lang/>"
		}
		X "$indent`t`t<v8:content>$(Esc-Xml $mlItem.content)</v8:content>"
		X "$indent`t</v8:item>"
	}
	X "$indent</$tag>"
}

function New-Guid-String {
	return [System.Guid]::NewGuid().ToString()
}

# --- 3. CamelCase splitter ---

function Split-CamelCase {
	param([string]$name)
	if (-not $name) { return $name }
	# Insert space before uppercase that follows lowercase (Cyrillic + Latin)
	$result = [regex]::Replace($name, '([а-яё])([А-ЯЁ])', '$1 $2')
	$result = [regex]::Replace($result, '([a-z])([A-Z])', '$1 $2')
	# Регистр понижается только у одиночной заглавной: аббревиатура из нескольких
	# заглавных подряд (API, НДС) остается как написана.
	if ($result.Length -gt 1) {
		$tail = [regex]::Replace($result.Substring(1), '(?<![А-ЯЁA-Z])([А-ЯЁA-Z])(?![А-ЯЁA-Z])', { param($m) $m.Groups[1].Value.ToLower() })
		$result = $result.Substring(0,1) + $tail
	}
	return $result
}

# Auto-synonym
$synonym = if ($def.synonym) { $def.synonym } else { Split-CamelCase $objName }
$comment = if ($def.comment) { "$($def.comment)" } else { "" }

# --- 4. Type system ---

$script:typeSynonyms = New-Object System.Collections.Hashtable
$script:typeSynonyms["число"]    = "Number"
$script:typeSynonyms["строка"]   = "String"
$script:typeSynonyms["булево"]   = "Boolean"
$script:typeSynonyms["дата"]     = "Date"
$script:typeSynonyms["датавремя"]= "DateTime"
$script:typeSynonyms["number"]   = "Number"
$script:typeSynonyms["string"]   = "String"
$script:typeSynonyms["boolean"]  = "Boolean"
$script:typeSynonyms["date"]     = "Date"
$script:typeSynonyms["datetime"] = "DateTime"
$script:typeSynonyms["bool"]     = "Boolean"
# Reference synonyms (Russian, lowercase)
$script:typeSynonyms["справочникссылка"]             = "CatalogRef"
$script:typeSynonyms["документссылка"]               = "DocumentRef"
$script:typeSynonyms["перечислениессылка"]            = "EnumRef"
$script:typeSynonyms["плансчетовссылка"]              = "ChartOfAccountsRef"
$script:typeSynonyms["планвидовхарактеристикссылка"]  = "ChartOfCharacteristicTypesRef"
$script:typeSynonyms["планвидоврасчётассылка"]         = "ChartOfCalculationTypesRef"
$script:typeSynonyms["планвидоврасчетассылка"]         = "ChartOfCalculationTypesRef"
$script:typeSynonyms["планобменассылка"]               = "ExchangePlanRef"
$script:typeSynonyms["бизнеспроцессссылка"]            = "BusinessProcessRef"
$script:typeSynonyms["задачассылка"]                   = "TaskRef"
$script:typeSynonyms["определяемыйтип"]              = "DefinedType"
$script:typeSynonyms["definedtype"]                   = "DefinedType"
# English lowercase ref synonyms
$script:typeSynonyms["catalogref"]                    = "CatalogRef"
$script:typeSynonyms["documentref"]                   = "DocumentRef"
$script:typeSynonyms["enumref"]                       = "EnumRef"

function Resolve-TypeStr {
	param([string]$typeStr)
	if (-not $typeStr) { return $typeStr }

	# Тип, скопированный из выгрузки, несет префикс пространства имен: cfg:, d5p1:, d4p1:.
	# В описании он лишний - имя типа платформа читает без него.
	# Срезается только префикс выгрузки конфигурации: схемные префиксы (v8:, xs:, v8ui:)
	# часть имени типа, и без них тип не разрешается.
	if ($typeStr -match '^(?:cfg|d\d+p\d+):(.+)$') { $typeStr = $Matches[1] }

	# Check for parameterized types: Number(15,2), Строка(100), etc.
	if ($typeStr -match '^([^(]+)\((.+)\)$') {
		$baseName = $Matches[1].Trim()
		$params = $Matches[2]
		$resolved = $script:typeSynonyms[$baseName.ToLower()]
		if ($resolved) { return "$resolved($params)" }
		return $typeStr
	}

	# Check for reference types: СправочникСсылка.Организации → CatalogRef.Организации
	if ($typeStr.Contains('.')) {
		$dotIdx = $typeStr.IndexOf('.')
		$prefix = $typeStr.Substring(0, $dotIdx)
		$suffix = $typeStr.Substring($dotIdx)  # includes the dot
		$resolved = $script:typeSynonyms[$prefix.ToLower()]
		if ($resolved) { return "$resolved$suffix" }
		return $typeStr
	}

	# Simple name lookup
	$resolved = $script:typeSynonyms[$typeStr.ToLower()]
	if ($resolved) { return $resolved }

	return $typeStr
}

# --- 4a. Metadata path normalization ---

# Путь к метаданным приходит по-русски или по-английски вперемешку:
# "Документ.Реализация.Реквизит.Склад" и "Document.Реализация.Attribute.Склад" - одно и то же.
# Переводятся только четные сегменты (вид объекта), имена остаются как написаны.
$script:mdKindSynonyms = @{
	"Реквизит"                = "Attribute"
	"ТабличнаяЧасть"          = "TabularSection"
	"Измерение"               = "Dimension"
	"Ресурс"                  = "Resource"
	"Графа"                   = "Column"
	"ЗначениеПеречисления"    = "EnumValue"
	"Форма"                   = "Form"
	"Макет"                   = "Template"
	"Команда"                 = "Command"
	"ПризнакУчета"            = "AccountingFlag"
	"ПризнакУчетаСубконто"    = "ExtDimensionAccountingFlag"
	"РеквизитАдресации"       = "AddressingAttribute"
}
foreach ($kindKey in $script:objectTypeSynonyms.Keys) {
	$script:mdKindSynonyms[$kindKey] = $script:objectTypeSynonyms[$kindKey]
}

function Resolve-MDPath {
	param([string]$path)
	if (-not $path) { return $path }
	$parts = $path.Split('.')
	for ($idx = 0; $idx -lt $parts.Count; $idx += 2) {
		$syn = $script:mdKindSynonyms[$parts[$idx]]
		if ($syn) { $parts[$idx] = $syn }
	}
	return ($parts -join '.')
}

# $CfgPrefix - ссылочный тип пишется как cfg:CatalogRef.X вместо локального d5p1:.
# Платформа использует обе формы: у реквизитов объектов - d5p1, у параметров сеанса,
# общих реквизитов, критериев отбора и команд - cfg. Форма задается вызывающим.
function Emit-TypeContent {
	param([string]$indent, [string]$typeStr, [switch]$CfgPrefix)
	if (-not $typeStr) { return }

	# Составной тип платформа пишет блоками: сперва все типы, затем наборы типов, затем
	# квалификаторы по одному на вид - числовой, строковый, дата. Наш вывод шел парами
	# тип-квалификатор, и файл расходился с выгрузкой на каждом составном типе.
	if ($typeStr.Contains(' + ')) {
		$parts = $typeStr -split '\s*\+\s*'
		$typeLines = New-Object System.Collections.Generic.List[string]
		$setLines = New-Object System.Collections.Generic.List[string]
		$qualBlocks = [ordered]@{}
		foreach ($part in $parts) {
			$start = $script:xml.Length
			Emit-TypeContent $indent $part.Trim() -CfgPrefix:$CfgPrefix
			$chunk = $script:xml.ToString($start, $script:xml.Length - $start)
			$script:xml.Length = $start
			$openKind = $null
			foreach ($line in ($chunk -split "`r?`n")) {
				if ($line.Trim() -eq '') { continue }
				$trimmed = $line.Trim()
				if ($openKind) {
					[void]$qualBlocks[$openKind].Add($line)
					if ($trimmed -eq "</v8:$openKind>") { $openKind = $null }
				} elseif ($trimmed -match '^<v8:(\w+Qualifiers)>$') {
					$openKind = $Matches[1]
					if (-not $qualBlocks.Contains($openKind)) { $qualBlocks[$openKind] = New-Object System.Collections.Generic.List[string] }
					[void]$qualBlocks[$openKind].Add($line)
				} elseif ($trimmed.StartsWith('<v8:TypeSet')) {
					[void]$setLines.Add($line)
				} else {
					[void]$typeLines.Add($line)
				}
			}
		}
		foreach ($line in $typeLines) { X $line }
		foreach ($line in $setLines) { X $line }
		$ordered = @('NumberQualifiers', 'StringQualifiers', 'DateQualifiers')
		$rest = @($qualBlocks.Keys | Where-Object { $ordered -notcontains $_ })
		foreach ($kind in ($ordered + $rest)) {
			if ($qualBlocks.Contains($kind)) {
				foreach ($line in $qualBlocks[$kind]) { X $line }
			}
		}
		return
	}

	$typeStr = Resolve-TypeStr $typeStr

	# Boolean
	if ($typeStr -eq "Boolean") {
		X "$indent<v8:Type>xs:boolean</v8:Type>"
		return
	}

	# String or String(N)
	if ($typeStr -match '^String(\((\d+)\))?$') {
		$len = if ($Matches[2]) { $Matches[2] } else { "10" }
		X "$indent<v8:Type>xs:string</v8:Type>"
		X "$indent<v8:StringQualifiers>"
		X "$indent`t<v8:Length>$len</v8:Length>"
		X "$indent`t<v8:AllowedLength>Variable</v8:AllowedLength>"
		X "$indent</v8:StringQualifiers>"
		return
	}

	# Number without params → Number(10,0)
	if ($typeStr -eq "Number") {
		X "$indent<v8:Type>xs:decimal</v8:Type>"
		X "$indent<v8:NumberQualifiers>"
		X "$indent`t<v8:Digits>10</v8:Digits>"
		X "$indent`t<v8:FractionDigits>0</v8:FractionDigits>"
		X "$indent`t<v8:AllowedSign>Any</v8:AllowedSign>"
		X "$indent</v8:NumberQualifiers>"
		return
	}

	# Number(D,F) or Number(D,F,nonneg)
	if ($typeStr -match '^Number\((\d+),(\d+)(,nonneg)?\)$') {
		$digits = $Matches[1]
		$fraction = $Matches[2]
		$sign = if ($Matches[3]) { "Nonnegative" } else { "Any" }
		X "$indent<v8:Type>xs:decimal</v8:Type>"
		X "$indent<v8:NumberQualifiers>"
		X "$indent`t<v8:Digits>$digits</v8:Digits>"
		X "$indent`t<v8:FractionDigits>$fraction</v8:FractionDigits>"
		X "$indent`t<v8:AllowedSign>$sign</v8:AllowedSign>"
		X "$indent</v8:NumberQualifiers>"
		return
	}

	# Date / DateTime
	if ($typeStr -eq "Date") {
		X "$indent<v8:Type>xs:dateTime</v8:Type>"
		X "$indent<v8:DateQualifiers>"
		X "$indent`t<v8:DateFractions>Date</v8:DateFractions>"
		X "$indent</v8:DateQualifiers>"
		return
	}
	if ($typeStr -eq "DateTime") {
		X "$indent<v8:Type>xs:dateTime</v8:Type>"
		X "$indent<v8:DateQualifiers>"
		X "$indent`t<v8:DateFractions>DateTime</v8:DateFractions>"
		X "$indent</v8:DateQualifiers>"
		return
	}

	# DefinedType
	if ($typeStr -match '^DefinedType\.(.+)$') {
		$dtName = $Matches[1]
		X "$indent<v8:TypeSet>cfg:DefinedType.$dtName</v8:TypeSet>"
		return
	}

	# ValueStorage
	if ($typeStr -eq "ValueStorage") {
		X "$indent<v8:Type>xs:base64Binary</v8:Type>"
		return
	}

	# Reference types - use local xmlns declaration for 1C compatibility
	if ($typeStr -match '^(CatalogRef|DocumentRef|EnumRef|ChartOfAccountsRef|ChartOfCharacteristicTypesRef|ChartOfCalculationTypesRef|ExchangePlanRef|BusinessProcessRef|TaskRef)\.(.+)$') {
		if ($CfgPrefix) {
			X "$indent<v8:Type>cfg:$typeStr</v8:Type>"
		} else {
			X "$indent<v8:Type xmlns:d5p1=`"http://v8.1c.ru/8.1/data/enterprise/current-config`">d5p1:$typeStr</v8:Type>"
		}
		return
	}

	# Ссылочный тип без имени объекта - это НАБОР типов, а не тип: любой справочник,
	# любой документ. Платформа пишет его элементом TypeSet.
	if ($typeStr -match '^(CatalogRef|DocumentRef|EnumRef|ChartOfAccountsRef|ChartOfCharacteristicTypesRef|ChartOfCalculationTypesRef|ExchangePlanRef|BusinessProcessRef|TaskRef)$') {
		X "$indent<v8:TypeSet>cfg:$typeStr</v8:TypeSet>"
		return
	}

	# Fallback - emit as-is
	X "$indent<v8:Type>$typeStr</v8:Type>"
}

function Emit-ValueType {
	# Измерения и ресурсы регистров платформа выгружает через объявленный в шапке префикс
	# cfg, а не локальным объявлением - замерено на эталоне регистра сведений.
	param([string]$indent, [string]$typeStr)
	X "$indent<Type>"
	Emit-TypeContent "$indent`t" $typeStr -CfgPrefix
	X "$indent</Type>"
}

function Emit-FillValue {
	param([string]$indent, [string]$typeStr)
	if (-not $typeStr) {
		X "$indent<FillValue xsi:nil=`"true`"/>"
		return
	}

	$typeStr = Resolve-TypeStr $typeStr

	if ($typeStr -eq "Boolean") {
		X "$indent<FillValue xsi:type=`"xs:boolean`">false</FillValue>"
		return
	}
	if ($typeStr -match '^String') {
		X "$indent<FillValue xsi:type=`"xs:string`"/>"
		return
	}
	if ($typeStr -match '^Number') {
		X "$indent<FillValue xsi:type=`"xs:decimal`">0</FillValue>"
		return
	}
	if ($typeStr -match '^(Date|DateTime)$') {
		X "$indent<FillValue xsi:nil=`"true`"/>"
		return
	}
	# References and others
	X "$indent<FillValue xsi:nil=`"true`"/>"
}

# --- 5. Attribute shorthand parser ---

function Build-TypeStr {
	param($obj)
	$t = if ($obj.valueType) { "$($obj.valueType)" } elseif ($obj.type) { "$($obj.type)" } else { "" }
	if ($t -and -not $t.Contains('(')) {
		if ($t -eq "String" -and $obj.length) {
			$t = "String($($obj.length))"
		} elseif ($t -eq "Number" -and $obj.length) {
			$p = if ($obj.precision) { $obj.precision } else { 0 }
			$nn = if ($obj.nonneg -or $obj.nonnegative) { ",nonneg" } else { "" }
			$t = "Number($($obj.length),$p$nn)"
		}
	}
	return $t
}

function Parse-AttributeShorthand {
	param($val)

	if ($val -is [string]) {
		$str = "$val"
		$parsed = @{
			name = ""
			type = ""
			synonym = ""
			comment = ""
			flags = @()
		}

		# Split by | for flags
		$parts = $str -split '\|', 2
		$mainPart = $parts[0].Trim()
		if ($parts.Count -gt 1) {
			$flagStr = $parts[1].Trim()
			$parsed.flags = @($flagStr -split ',' | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })
		}

		# Split by : for name and type
		$colonParts = $mainPart -split ':', 2
		$parsed.name = $colonParts[0].Trim()
		if ($colonParts.Count -gt 1) {
			$parsed.type = $colonParts[1].Trim()
		}

		$parsed.synonym = Split-CamelCase $parsed.name
		return $parsed
	}

	# Object form
	$name = "$($val.name)"
	return @{
		name    = $name
		type    = Build-TypeStr $val
		synonym = if ($val.synonym) { $val.synonym } else { Split-CamelCase $name }
		comment = if ($val.comment) { "$($val.comment)" } else { "" }
		flags   = @(if ($val.flags) { $val.flags } else { @() })
		fillChecking = if ($val.fillChecking) { "$($val.fillChecking)" } else { "" }
		indexing = if ($val.indexing) { "$($val.indexing)" } else { "" }
		multiLine = if ($val.multiLine -eq $true) { $true } else { $false }
	}
}

function Parse-EnumValueShorthand {
	param($val)

	if ($val -is [string]) {
		$name = "$val"
		return @{
			name    = $name
			synonym = Split-CamelCase $name
			comment = ""
		}
	}

	$name = "$($val.name)"
	return @{
		name    = $name
		synonym = if ($val.synonym) { $val.synonym } else { Split-CamelCase $name }
		comment = if ($val.comment) { "$($val.comment)" } else { "" }
	}
}

# --- 6. GeneratedType categories ---

$script:generatedTypes = @{
	"Catalog" = @(
		@{ prefix = "CatalogObject";    category = "Object" }
		@{ prefix = "CatalogRef";       category = "Ref" }
		@{ prefix = "CatalogSelection"; category = "Selection" }
		@{ prefix = "CatalogList";      category = "List" }
		@{ prefix = "CatalogManager";   category = "Manager" }
	)
	"Document" = @(
		@{ prefix = "DocumentObject";    category = "Object" }
		@{ prefix = "DocumentRef";       category = "Ref" }
		@{ prefix = "DocumentSelection"; category = "Selection" }
		@{ prefix = "DocumentList";      category = "List" }
		@{ prefix = "DocumentManager";   category = "Manager" }
	)
	"Enum" = @(
		@{ prefix = "EnumRef";     category = "Ref" }
		@{ prefix = "EnumManager"; category = "Manager" }
		@{ prefix = "EnumList";    category = "List" }
	)
	"Constant" = @(
		@{ prefix = "ConstantManager";      category = "Manager" }
		@{ prefix = "ConstantValueManager"; category = "ValueManager" }
		@{ prefix = "ConstantValueKey";     category = "ValueKey" }
	)
	"InformationRegister" = @(
		@{ prefix = "InformationRegisterRecord";        category = "Record" }
		@{ prefix = "InformationRegisterManager";       category = "Manager" }
		@{ prefix = "InformationRegisterSelection";     category = "Selection" }
		@{ prefix = "InformationRegisterList";          category = "List" }
		@{ prefix = "InformationRegisterRecordSet";     category = "RecordSet" }
		@{ prefix = "InformationRegisterRecordKey";     category = "RecordKey" }
		@{ prefix = "InformationRegisterRecordManager"; category = "RecordManager" }
	)
	"AccumulationRegister" = @(
		@{ prefix = "AccumulationRegisterRecord";    category = "Record" }
		@{ prefix = "AccumulationRegisterManager";   category = "Manager" }
		@{ prefix = "AccumulationRegisterSelection"; category = "Selection" }
		@{ prefix = "AccumulationRegisterList";      category = "List" }
		@{ prefix = "AccumulationRegisterRecordSet"; category = "RecordSet" }
		@{ prefix = "AccumulationRegisterRecordKey"; category = "RecordKey" }
	)
	"AccountingRegister" = @(
		@{ prefix = "AccountingRegisterRecord";         category = "Record" }
		@{ prefix = "AccountingRegisterExtDimensions";  category = "ExtDimensions" }
		@{ prefix = "AccountingRegisterRecordSet";      category = "RecordSet" }
		@{ prefix = "AccountingRegisterRecordKey";      category = "RecordKey" }
		@{ prefix = "AccountingRegisterSelection";      category = "Selection" }
		@{ prefix = "AccountingRegisterList";           category = "List" }
		@{ prefix = "AccountingRegisterManager";        category = "Manager" }
	)
	"CalculationRegister" = @(
		@{ prefix = "CalculationRegisterRecord";    category = "Record" }
		@{ prefix = "CalculationRegisterManager";   category = "Manager" }
		@{ prefix = "CalculationRegisterSelection"; category = "Selection" }
		@{ prefix = "CalculationRegisterList";      category = "List" }
		@{ prefix = "CalculationRegisterRecordSet"; category = "RecordSet" }
		@{ prefix = "CalculationRegisterRecordKey"; category = "RecordKey" }
		@{ prefix = "RecalculationsManager";        category = "Recalcs" }
	)
	"ChartOfAccounts" = @(
		@{ prefix = "ChartOfAccountsObject";              category = "Object" }
		@{ prefix = "ChartOfAccountsRef";                 category = "Ref" }
		@{ prefix = "ChartOfAccountsSelection";           category = "Selection" }
		@{ prefix = "ChartOfAccountsList";                category = "List" }
		@{ prefix = "ChartOfAccountsManager";             category = "Manager" }
		@{ prefix = "ChartOfAccountsExtDimensionTypes";   category = "ExtDimensionTypes" }
		@{ prefix = "ChartOfAccountsExtDimensionTypesRow"; category = "ExtDimensionTypesRow" }
	)
	"ChartOfCharacteristicTypes" = @(
		@{ prefix = "ChartOfCharacteristicTypesObject";         category = "Object" }
		@{ prefix = "ChartOfCharacteristicTypesRef";            category = "Ref" }
		@{ prefix = "ChartOfCharacteristicTypesSelection";      category = "Selection" }
		@{ prefix = "ChartOfCharacteristicTypesList";           category = "List" }
		# Префикс именно "Characteristic", без имени типа: так пишет платформа. Замерено круговым
		# прогоном через 8.3.27 и подтверждено выгрузкой типовой конфигурации.
		@{ prefix = "Characteristic"; category = "Characteristic" }
		@{ prefix = "ChartOfCharacteristicTypesManager";        category = "Manager" }
	)
	"ChartOfCalculationTypes" = @(
		@{ prefix = "ChartOfCalculationTypesObject";    category = "Object" }
		@{ prefix = "ChartOfCalculationTypesRef";       category = "Ref" }
		@{ prefix = "ChartOfCalculationTypesSelection"; category = "Selection" }
		@{ prefix = "ChartOfCalculationTypesList";      category = "List" }
		@{ prefix = "ChartOfCalculationTypesManager";   category = "Manager" }
		@{ prefix = "DisplacingCalculationTypes";       category = "DisplacingCalculationTypes" }
		@{ prefix = "DisplacingCalculationTypesRow";    category = "DisplacingCalculationTypesRow" }
		@{ prefix = "BaseCalculationTypes";             category = "BaseCalculationTypes" }
		@{ prefix = "BaseCalculationTypesRow";          category = "BaseCalculationTypesRow" }
		@{ prefix = "LeadingCalculationTypes";          category = "LeadingCalculationTypes" }
		@{ prefix = "LeadingCalculationTypesRow";       category = "LeadingCalculationTypesRow" }
	)
	"BusinessProcess" = @(
		@{ prefix = "BusinessProcessObject";        category = "Object" }
		@{ prefix = "BusinessProcessRef";            category = "Ref" }
		@{ prefix = "BusinessProcessSelection";      category = "Selection" }
		@{ prefix = "BusinessProcessList";           category = "List" }
		@{ prefix = "BusinessProcessManager";        category = "Manager" }
		@{ prefix = "BusinessProcessRoutePointRef";  category = "RoutePointRef" }
	)
	"Task" = @(
		@{ prefix = "TaskObject";    category = "Object" }
		@{ prefix = "TaskRef";       category = "Ref" }
		@{ prefix = "TaskSelection"; category = "Selection" }
		@{ prefix = "TaskList";      category = "List" }
		@{ prefix = "TaskManager";   category = "Manager" }
	)
	"ExchangePlan" = @(
		@{ prefix = "ExchangePlanObject";    category = "Object" }
		@{ prefix = "ExchangePlanRef";       category = "Ref" }
		@{ prefix = "ExchangePlanSelection"; category = "Selection" }
		@{ prefix = "ExchangePlanList";      category = "List" }
		@{ prefix = "ExchangePlanManager";   category = "Manager" }
	)
	"DefinedType" = @(
		@{ prefix = "DefinedType"; category = "DefinedType" }
	)
	"DocumentJournal" = @(
		@{ prefix = "DocumentJournalSelection"; category = "Selection" }
		@{ prefix = "DocumentJournalList";      category = "List" }
		@{ prefix = "DocumentJournalManager";   category = "Manager" }
	)
	"Report" = @(
		@{ prefix = "ReportObject";  category = "Object" }
		@{ prefix = "ReportManager"; category = "Manager" }
	)
	"DataProcessor" = @(
		@{ prefix = "DataProcessorObject";  category = "Object" }
		@{ prefix = "DataProcessorManager"; category = "Manager" }
	)
	"SettingsStorage" = @(
		@{ prefix = "SettingsStorageManager"; category = "Manager" }
	)
	"Sequence" = @(
		@{ prefix = "SequenceRecord";    category = "Record" }
		@{ prefix = "SequenceManager";   category = "Manager" }
		@{ prefix = "SequenceRecordSet"; category = "RecordSet" }
	)
	"FilterCriterion" = @(
		@{ prefix = "FilterCriterionManager"; category = "Manager" }
		@{ prefix = "FilterCriterionList";    category = "List" }
	)
	"WSReference" = @(
		@{ prefix = "WSReferenceManager"; category = "Manager" }
	)
}

function Emit-InternalInfo {
	param([string]$indent, [string]$objectType, [string]$objectName)
	$types = $script:generatedTypes[$objectType]
	if (-not $types) { return }

	X "$indent<InternalInfo>"
	# ExchangePlan: ThisNode UUID before GeneratedTypes
	if ($objectType -eq "ExchangePlan") {
		X "$indent`t<xr:ThisNode>$(New-Guid-String)</xr:ThisNode>"
	}
	foreach ($gt in $types) {
		$fullName = "$($gt.prefix).$objectName"
		X "$indent`t<xr:GeneratedType name=`"$fullName`" category=`"$($gt.category)`">"
		X "$indent`t`t<xr:TypeId>$(New-Guid-String)</xr:TypeId>"
		X "$indent`t`t<xr:ValueId>$(New-Guid-String)</xr:ValueId>"
		X "$indent`t</xr:GeneratedType>"
	}
	X "$indent</InternalInfo>"
}

# --- 7. StandardAttributes ---

$script:standardAttributesByType = @{
	"Catalog" = @("PredefinedDataName","Predefined","Ref","DeletionMark","IsFolder","Owner","Parent","Description","Code")
	"Document" = @("Posted","Ref","DeletionMark","Date","Number")
	"Enum" = @("Order","Ref")
	"InformationRegister" = @("Active","LineNumber","Recorder","Period")
	"AccumulationRegister" = @("Active","LineNumber","Recorder","Period")
	"AccountingRegister" = @("Active","Period","Recorder","LineNumber","Account")
	"CalculationRegister" = @("RegistrationPeriod","ReversingEntry","Active","EndOfBasePeriod","BegOfBasePeriod","EndOfActionPeriod","BegOfActionPeriod","ActionPeriod","CalculationType","LineNumber","Recorder")
	"ChartOfAccounts" = @("PredefinedDataName","Predefined","Ref","DeletionMark","Description","Code","Parent","Order","Type","OffBalance")
	"ChartOfCharacteristicTypes" = @("PredefinedDataName","Predefined","Ref","DeletionMark","Description","Code","Parent","ValueType")
	"ChartOfCalculationTypes" = @("PredefinedDataName","Predefined","Ref","DeletionMark","Description","Code","ActionPeriodIsBasic")
	"BusinessProcess" = @("Ref","DeletionMark","Date","Number","Started","Completed","HeadTask")
	"Task" = @("Ref","DeletionMark","Date","Number","Executed","Description","RoutePoint","BusinessProcess")
	"ExchangePlan" = @("Ref","DeletionMark","Code","Description","ThisNode","SentNo","ReceivedNo")
	"DocumentJournal" = @("Type","Ref","Date","Posted","DeletionMark","Number")
}

function Emit-StandardAttribute {
	param([string]$indent, [string]$attrName, [bool]$required = $false)

	# Настройки приходят ключом standardAttributes: заданное свойство заменяет умолчание,
	# остальные печатаются как есть. Блок и выгружается платформой только когда в нем есть
	# отличия от умолчания.
	$cfg = $null
	if ($def.standardAttributes) {
		foreach ($p in $def.standardAttributes.PSObject.Properties) {
			if ($p.Name -eq $attrName) { $cfg = $p.Value; break }
		}
	}

	X "$indent<xr:StandardAttribute name=`"$attrName`">"
	X "$indent`t<xr:LinkByType/>"
	# Владелец подчиненного справочника обязателен к заполнению - платформа выставляет это
	# сама. Владелец и родитель заполняются из значения заполнения.
	$defaultChecking = if ($attrName -eq "Owner" -or $required) { "ShowError" } else { "DontCheck" }
	$fillChecking = if ($cfg -and $cfg.fillChecking) { Normalize-EnumValue "FillChecking" "$($cfg.fillChecking)" } else { $defaultChecking }
	X "$indent`t<xr:FillChecking>$fillChecking</xr:FillChecking>"
	X "$indent`t<xr:MultiLine>false</xr:MultiLine>"
	$fromFillingValue = if ($attrName -eq "Owner" -or $attrName -eq "Parent") { "true" } else { "false" }
	X "$indent`t<xr:FillFromFillingValue>$fromFillingValue</xr:FillFromFillingValue>"
	X "$indent`t<xr:CreateOnInput>Auto</xr:CreateOnInput>"
	# Свойство появилось в формате 2.18. У владельца справочника тип задан списком владельцев,
	# и приведение значений платформа запрещает.
	if ([double]::Parse($script:formatVersion, [System.Globalization.CultureInfo]::InvariantCulture) -ge 2.18) {
		$reduction = if ($attrName -eq "Owner") { "Deny" } else { "TransformValues" }
		X "$indent`t<xr:TypeReductionMode>$reduction</xr:TypeReductionMode>"
	}
	X "$indent`t<xr:MaxValue xsi:nil=`"true`"/>"
	if ($cfg -and $cfg.tooltip) {
		Emit-MLText "$indent`t" "xr:ToolTip" $cfg.tooltip
	} else {
		X "$indent`t<xr:ToolTip/>"
	}
	X "$indent`t<xr:ExtendedEdit>false</xr:ExtendedEdit>"
	X "$indent`t<xr:Format/>"
	X "$indent`t<xr:ChoiceForm/>"
	X "$indent`t<xr:QuickChoice>Auto</xr:QuickChoice>"
	X "$indent`t<xr:ChoiceHistoryOnInput>Auto</xr:ChoiceHistoryOnInput>"
	X "$indent`t<xr:EditFormat/>"
	X "$indent`t<xr:PasswordMode>false</xr:PasswordMode>"
	X "$indent`t<xr:DataHistory>Use</xr:DataHistory>"
	X "$indent`t<xr:MarkNegatives>false</xr:MarkNegatives>"
	X "$indent`t<xr:MinValue xsi:nil=`"true`"/>"
	if ($cfg -and $cfg.synonym) {
		Emit-MLText "$indent`t" "xr:Synonym" $cfg.synonym
	} else {
		X "$indent`t<xr:Synonym/>"
	}
	if ($cfg -and $cfg.comment) {
		X "$indent`t<xr:Comment>$(Esc-Xml "$($cfg.comment)")</xr:Comment>"
	} else {
		X "$indent`t<xr:Comment/>"
	}
	X "$indent`t<xr:FullTextSearch>Use</xr:FullTextSearch>"
	# Составные свойства стандартного реквизита (связи и параметры выбора, значение
	# заполнения) навык пока печатает умолчанием: генератора для них в префиксе xr нет.
	X "$indent`t<xr:ChoiceParameterLinks/>"
	X "$indent`t<xr:FillValue xsi:nil=`"true`"/>"
	if ($cfg -and $cfg.mask) {
		X "$indent`t<xr:Mask>$(Esc-Xml "$($cfg.mask)")</xr:Mask>"
	} else {
		X "$indent`t<xr:Mask/>"
	}
	X "$indent`t<xr:ChoiceParameters/>"
	X "$indent</xr:StandardAttribute>"
}

function Emit-StandardAttributes {
	param([string]$indent, [string]$objectType)
	$attrs = $script:standardAttributesByType[$objectType]
	if (-not $attrs) { return }
	# У ссылочных объектов платформа выгружает блок, только когда у стандартного реквизита
	# изменено хотя бы одно свойство. У наборов записей он есть всегда - это часть описания
	# самого набора.
	$alwaysHasBlock = @("Enum","InformationRegister","AccumulationRegister","AccountingRegister","CalculationRegister")
	if ($objectType -notin $alwaysHasBlock -and -not $def.standardAttributes) { return }
	X "$indent<StandardAttributes>"
	foreach ($a in $attrs) {
		Emit-StandardAttribute "$indent`t" $a
	}
	X "$indent</StandardAttributes>"
}

# TabularSection standard attributes (just LineNumber)
function Emit-TabularStandardAttributes {
	param([string]$indent)
	X "$indent<StandardAttributes>"
	Emit-StandardAttribute "$indent`t" "LineNumber"
	X "$indent</StandardAttributes>"
}

# --- 8. Attribute emitter ---

# Имена стандартных реквизитов по типу объекта, обе формы записи. Набор совпадает с составом,
# который выпускает meta-compile: имени вне этого набора платформа не запрещает, и общего
# для всех типов списка нет - у обработки нет Ссылки, у документа нет Предопределенного.
$script:reservedAttributesByType = @{
	"Catalog" = @("PredefinedDataName","ИмяПредопределенныхДанных","Predefined","Предопределенный","Ref","Ссылка","DeletionMark","ПометкаУдаления","IsFolder","ЭтоГруппа","Owner","Владелец","Parent","Родитель","Description","Наименование","Code","Код")
	"Document" = @("Ref","Ссылка","DeletionMark","ПометкаУдаления","Date","Дата","Number","Номер","Posted","Проведен")
	"Enum" = @("Ref","Ссылка","Order","Порядок")
	"InformationRegister" = @("Period","Период","Recorder","Регистратор","LineNumber","НомерСтроки","Active","Активность")
	"AccumulationRegister" = @("Period","Период","Recorder","Регистратор","LineNumber","НомерСтроки","Active","Активность")
	"AccountingRegister" = @("Period","Период","Recorder","Регистратор","LineNumber","НомерСтроки","Active","Активность","Account","Счет")
	"CalculationRegister" = @("Recorder","Регистратор","LineNumber","НомерСтроки","Active","Активность","RegistrationPeriod","ПериодРегистрации","CalculationType","ВидРасчета","ReversingEntry","СторноЗапись")
	"ChartOfAccounts" = @("PredefinedDataName","ИмяПредопределенныхДанных","Predefined","Предопределенный","Ref","Ссылка","DeletionMark","ПометкаУдаления","Description","Наименование","Code","Код","Parent","Родитель","Order","Порядок","Type","Тип","OffBalance","Забалансовый")
	"ChartOfCharacteristicTypes" = @("PredefinedDataName","ИмяПредопределенныхДанных","Predefined","Предопределенный","Ref","Ссылка","DeletionMark","ПометкаУдаления","Description","Наименование","Code","Код","Parent","Родитель","IsFolder","ЭтоГруппа","ValueType","ТипЗначения")
	"ChartOfCalculationTypes" = @("PredefinedDataName","ИмяПредопределенныхДанных","Predefined","Предопределенный","Ref","Ссылка","DeletionMark","ПометкаУдаления","Description","Наименование","Code","Код","ActionPeriodIsBasic","БазовыйПериодЯвляетсяОсновным")
	"BusinessProcess" = @("Ref","Ссылка","DeletionMark","ПометкаУдаления","Date","Дата","Number","Номер","Started","Стартован","Completed","Завершен","HeadTask","ВедущаяЗадача")
	"Task" = @("Ref","Ссылка","DeletionMark","ПометкаУдаления","Date","Дата","Number","Номер","Description","Наименование","Executed","Выполнена","RoutePoint","ТочкаМаршрута","BusinessProcess","БизнесПроцесс")
	"ExchangePlan" = @("Ref","Ссылка","DeletionMark","ПометкаУдаления","Code","Код","Description","Наименование","ThisNode","ЭтотУзел","SentNo","НомерОтправленного","ReceivedNo","НомерПринятого")
	"DocumentJournal" = @("Ref","Ссылка","Type","Тип","Date","Дата","Number","Номер","Posted","Проведен","DeletionMark","ПометкаУдаления")
	"TabularSection" = @("LineNumber","НомерСтроки")
}

function Assert-AttributeNameAllowed {
	param([string]$Name, [string]$OwnerType)
	if (-not $Name) { return }
	$normalized = $Name.Replace([char]0x451, [char]0x435).Replace([char]0x401, [char]0x415)
	if (-not $script:reservedAttributesByType.ContainsKey($OwnerType)) { return }
	foreach ($standard in $script:reservedAttributesByType[$OwnerType]) {
		if ($standard -ieq $normalized) {
			Write-Error "Имя '$Name' зарезервировано стандартным реквизитом платформы у типа '$OwnerType'"
			exit 1
		}
	}
}

function Emit-Attribute {
	param([string]$indent, $parsed, [string]$context)
	# $context: "catalog", "document", "object", "processor", "tabular", "processor-tabular", "register"
	$attrName = $parsed.name
	$owner = if ($context -in @("tabular", "processor-tabular")) { "TabularSection" } else { $objType }
	Assert-AttributeNameAllowed $attrName $owner
	$uuid = New-Guid-String
	X "$indent<Attribute uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $parsed.name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $parsed.synonym
	X "$indent`t`t<Comment/>"

	# Type
	$typeStr = $parsed.type
	if ($typeStr) {
		Emit-ValueType "$indent`t`t" $typeStr
	} else {
		# Default: unqualified string
		X "$indent`t`t<Type>"
		X "$indent`t`t`t<v8:Type>xs:string</v8:Type>"
		X "$indent`t`t</Type>"
	}

	X "$indent`t`t<PasswordMode>false</PasswordMode>"
	X "$indent`t`t<Format/>"
	X "$indent`t`t<EditFormat/>"
	X "$indent`t`t<ToolTip/>"
	X "$indent`t`t<MarkNegatives>false</MarkNegatives>"
	X "$indent`t`t<Mask/>"
	$multiLine = if ($parsed.multiLine -eq $true -or $parsed.flags -contains "multiline") { "true" } else { "false" }
	X "$indent`t`t<MultiLine>$multiLine</MultiLine>"
	X "$indent`t`t<ExtendedEdit>false</ExtendedEdit>"
	X "$indent`t`t<MinValue xsi:nil=`"true`"/>"
	X "$indent`t`t<MaxValue xsi:nil=`"true`"/>"

	# Заполнение по значению не пишется у табличной части, обработки и регистров кроме
	# сведений. Планы счетов и видов расчета его пишут - сверено с выгрузкой.
	# (Chart*, AccumulationRegister/AccountingRegister/CalculationRegister don't support these)
	if ($context -notin @("tabular", "processor", "register-other")) {
		X "$indent`t`t<FillFromFillingValue>false</FillFromFillingValue>"
	}

	# FillValue - same restriction
	if ($context -notin @("tabular", "processor", "register-other")) {
		Emit-FillValue "$indent`t`t" $typeStr
	}

	# FillChecking
	$fillChecking = "DontCheck"
	if ($parsed.flags -contains "req") { $fillChecking = "ShowError" }
	if ($parsed.fillChecking) { $fillChecking = $parsed.fillChecking }
	X "$indent`t`t<FillChecking>$fillChecking</FillChecking>"

	X "$indent`t`t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$indent`t`t<ChoiceParameterLinks/>"
	X "$indent`t`t<ChoiceParameters/>"
	X "$indent`t`t<QuickChoice>Auto</QuickChoice>"
	X "$indent`t`t<CreateOnInput>Auto</CreateOnInput>"
	X "$indent`t`t<ChoiceForm/>"
	X "$indent`t`t<LinkByType/>"
	X "$indent`t`t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"

	# Use - only for catalog top-level attributes
	if ($context -eq "catalog") {
		X "$indent`t`t<Use>ForItem</Use>"
	}

	# Indexing/FullTextSearch/DataHistory - not for non-stored objects (processor, processor-tabular)
	if ($context -notin @("processor", "processor-tabular")) {
		$indexing = "DontIndex"
		if ($parsed.flags -contains "index") { $indexing = "Index" }
		if ($parsed.flags -contains "indexadditional") { $indexing = "IndexWithAdditionalOrder" }
		if ($parsed.indexing) { $indexing = $parsed.indexing }
		X "$indent`t`t<Indexing>$indexing</Indexing>"

		X "$indent`t`t<FullTextSearch>Use</FullTextSearch>"
		# DataHistory - not for Chart* types and non-InformationRegister register family
		if ($context -ne "register-other") {
			X "$indent`t`t<DataHistory>Use</DataHistory>"
		}
	}

	X "$indent`t</Properties>"
	X "$indent</Attribute>"
}

# --- 9. TabularSection emitter ---

function Emit-TabularSection {
	param([string]$indent, [string]$tsName, $columns, [string]$objectType, [string]$objectName, $options)
	$uuid = New-Guid-String
	X "$indent<TabularSection uuid=`"$uuid`">"

	# InternalInfo for TabularSection
	$typePrefix = "${objectType}TabularSection"
	$rowPrefix = "${objectType}TabularSectionRow"

	X "$indent`t<InternalInfo>"
	X "$indent`t`t<xr:GeneratedType name=`"$typePrefix.$objectName.$tsName`" category=`"TabularSection`">"
	X "$indent`t`t`t<xr:TypeId>$(New-Guid-String)</xr:TypeId>"
	X "$indent`t`t`t<xr:ValueId>$(New-Guid-String)</xr:ValueId>"
	X "$indent`t`t</xr:GeneratedType>"
	X "$indent`t`t<xr:GeneratedType name=`"$rowPrefix.$objectName.$tsName`" category=`"TabularSectionRow`">"
	X "$indent`t`t`t<xr:TypeId>$(New-Guid-String)</xr:TypeId>"
	X "$indent`t`t`t<xr:ValueId>$(New-Guid-String)</xr:ValueId>"
	X "$indent`t`t</xr:GeneratedType>"
	X "$indent`t</InternalInfo>"

	$tsSynonym = if ($options -and $options.synonym) { $options.synonym } else { Split-CamelCase $tsName }

	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $tsName)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $tsSynonym
	X "$indent`t`t<Comment/>"
	X "$indent`t`t<ToolTip/>"
	X "$indent`t`t<FillChecking>DontCheck</FillChecking>"
	Emit-TabularStandardAttributes "$indent`t`t"
	# Use=ForItem only for Catalog tabular sections (Document does not have Use)
	if ($objectType -eq "Catalog") {
		X "$indent`t`t<Use>ForItem</Use>"
	}
	# Свойство появилось в формате 2.20. Значение по умолчанию задает режим совместимости
	# конфигурации: начиная с 8.3.27 это 9, до него - 5. У обработки и отчета его нет:
	# их табличные части в базе не хранятся.
	if ($objectType -notin @("DataProcessor","Report") -and
		[double]::Parse($script:formatVersion, [System.Globalization.CultureInfo]::InvariantCulture) -ge 2.20) {
		$lineNumberLength = if ($script:compatibilityMode -ge "Version8_3_27") { 9 } else { 5 }
		if ($options -and $null -ne $options.lineNumberLength) { $lineNumberLength = [int]$options.lineNumberLength }
		X "$indent`t`t<LineNumberLength>$lineNumberLength</LineNumberLength>"
	}
	X "$indent`t</Properties>"

	$tsContext = if ($objectType -in @("DataProcessor","Report")) { "processor-tabular" } else { "tabular" }
	X "$indent`t<ChildObjects>"
	foreach ($col in $columns) {
		$parsed = Parse-AttributeShorthand $col
		Emit-Attribute "$indent`t`t" $parsed $tsContext
	}
	X "$indent`t</ChildObjects>"

	X "$indent</TabularSection>"
}

# --- 10. EnumValue emitter ---

# Версии формата сравниваются по составным частям, а не как десятичная дробь:
# 2.9 старее, чем 2.21, хотя как число больше.
function Get-FormatVersionRank {
	param([string]$Version)
	if ($Version -match '^(\d+)\.(\d+)$') { return [int]$Matches[1] * 100 + [int]$Matches[2] }
	return 0
}

function Emit-EnumValue {
	param([string]$indent, $parsed)
	$uuid = New-Guid-String
	X "$indent<EnumValue uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $parsed.name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $parsed.synonym
	X "$indent`t`t<Comment/>"
	# Цвет значения перечисления появился в формате 2.21 (8.5); значение auto означает, что
	# цвет выбирает платформа.
	if ((Get-FormatVersionRank $script:formatVersion) -ge 221) {
		X "$indent`t`t<Color>auto</Color>"
	}
	X "$indent`t</Properties>"
	X "$indent</EnumValue>"
}

# --- 11. Dimension emitter ---

function Emit-Dimension {
	param([string]$indent, $parsed, [string]$registerType)
	# $registerType: "InformationRegister" or "AccumulationRegister"
	$uuid = New-Guid-String
	X "$indent<Dimension uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $parsed.name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $parsed.synonym
	X "$indent`t`t<Comment/>"

	$typeStr = $parsed.type
	if ($typeStr) {
		Emit-ValueType "$indent`t`t" $typeStr
	} else {
		X "$indent`t`t<Type>"
		X "$indent`t`t`t<v8:Type>xs:string</v8:Type>"
		X "$indent`t`t</Type>"
	}

	X "$indent`t`t<PasswordMode>false</PasswordMode>"
	X "$indent`t`t<Format/>"
	X "$indent`t`t<EditFormat/>"
	X "$indent`t`t<ToolTip/>"
	X "$indent`t`t<MarkNegatives>false</MarkNegatives>"
	X "$indent`t`t<Mask/>"
	$multiLine = if ($parsed.multiLine -eq $true -or $parsed.flags -contains "multiline") { "true" } else { "false" }
	X "$indent`t`t<MultiLine>$multiLine</MultiLine>"
	X "$indent`t`t<ExtendedEdit>false</ExtendedEdit>"
	X "$indent`t`t<MinValue xsi:nil=`"true`"/>"
	X "$indent`t`t<MaxValue xsi:nil=`"true`"/>"

	# InformationRegister dimensions have FillFromFillingValue
	if ($registerType -eq "InformationRegister") {
		$fillFrom = if ($parsed.flags -contains "master") { "true" } else { "false" }
		X "$indent`t`t<FillFromFillingValue>$fillFrom</FillFromFillingValue>"
		X "$indent`t`t<FillValue xsi:nil=`"true`"/>"
	}

	$fillChecking = "DontCheck"
	if ($parsed.flags -contains "req") { $fillChecking = "ShowError" }
	X "$indent`t`t<FillChecking>$fillChecking</FillChecking>"

	X "$indent`t`t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$indent`t`t<ChoiceParameterLinks/>"
	X "$indent`t`t<ChoiceParameters/>"
	X "$indent`t`t<QuickChoice>Auto</QuickChoice>"
	X "$indent`t`t<CreateOnInput>Auto</CreateOnInput>"
	X "$indent`t`t<ChoiceForm/>"
	X "$indent`t`t<LinkByType/>"
	X "$indent`t`t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"

	# InformationRegister dimensions: Master, MainFilter, DenyIncompleteValues
	if ($registerType -eq "InformationRegister") {
		$master = if ($parsed.flags -contains "master") { "true" } else { "false" }
		$mainFilter = if ($parsed.flags -contains "mainfilter") { "true" } else { "false" }
		$denyIncomplete = if ($parsed.flags -contains "denyincomplete") { "true" } else { "false" }
		X "$indent`t`t<Master>$master</Master>"
		X "$indent`t`t<MainFilter>$mainFilter</MainFilter>"
		X "$indent`t`t<DenyIncompleteValues>$denyIncomplete</DenyIncompleteValues>"
	}

	# AccumulationRegister dimensions: DenyIncompleteValues
	if ($registerType -eq "AccumulationRegister") {
		$denyIncomplete = if ($parsed.flags -contains "denyincomplete") { "true" } else { "false" }
		X "$indent`t`t<DenyIncompleteValues>$denyIncomplete</DenyIncompleteValues>"
	}

	$indexing = "DontIndex"
	if ($parsed.flags -contains "index") { $indexing = "Index" }
	X "$indent`t`t<Indexing>$indexing</Indexing>"

	X "$indent`t`t<FullTextSearch>Use</FullTextSearch>"

	# AccumulationRegister dimensions: UseInTotals
	if ($registerType -eq "AccumulationRegister") {
		$useInTotals = if ($parsed.flags -contains "nouseintotals") { "false" } else { "true" }
		X "$indent`t`t<UseInTotals>$useInTotals</UseInTotals>"
	}

	# InformationRegister dimensions: DataHistory
	if ($registerType -eq "InformationRegister") {
		X "$indent`t`t<DataHistory>Use</DataHistory>"
		# Свойство появилось в формате 2.18.
		if ([double]::Parse($script:formatVersion, [System.Globalization.CultureInfo]::InvariantCulture) -ge 2.18) {
			X "$indent`t`t<TypeReductionMode>TransformValues</TypeReductionMode>"
		}
	}

	X "$indent`t</Properties>"
	X "$indent</Dimension>"
}

# --- 12. Resource emitter ---

function Emit-Resource {
	param([string]$indent, $parsed, [string]$registerType)
	$uuid = New-Guid-String
	X "$indent<Resource uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $parsed.name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $parsed.synonym
	X "$indent`t`t<Comment/>"

	$typeStr = $parsed.type
	if ($typeStr) {
		Emit-ValueType "$indent`t`t" $typeStr
	} else {
		X "$indent`t`t<Type>"
		X "$indent`t`t`t<v8:Type>xs:decimal</v8:Type>"
		X "$indent`t`t`t<v8:NumberQualifiers>"
		X "$indent`t`t`t`t<v8:Digits>15</v8:Digits>"
		X "$indent`t`t`t`t<v8:FractionDigits>2</v8:FractionDigits>"
		X "$indent`t`t`t`t<v8:AllowedSign>Any</v8:AllowedSign>"
		X "$indent`t`t`t</v8:NumberQualifiers>"
		X "$indent`t`t</Type>"
	}

	X "$indent`t`t<PasswordMode>false</PasswordMode>"
	X "$indent`t`t<Format/>"
	X "$indent`t`t<EditFormat/>"
	X "$indent`t`t<ToolTip/>"
	X "$indent`t`t<MarkNegatives>false</MarkNegatives>"
	X "$indent`t`t<Mask/>"
	$multiLine = if ($parsed.multiLine -eq $true -or $parsed.flags -contains "multiline") { "true" } else { "false" }
	X "$indent`t`t<MultiLine>$multiLine</MultiLine>"
	X "$indent`t`t<ExtendedEdit>false</ExtendedEdit>"
	X "$indent`t`t<MinValue xsi:nil=`"true`"/>"
	X "$indent`t`t<MaxValue xsi:nil=`"true`"/>"

	# У ресурса регистра сведений значение заполнения соответствует типу: у числа это ноль,
	# у строки пустая строка. Пустая ссылка на значение остается неопределенной.
	if ($registerType -eq "InformationRegister") {
		X "$indent`t`t<FillFromFillingValue>false</FillFromFillingValue>"
		Emit-FillValue "$indent`t`t" $parsed.type
	}

	$fillChecking = "DontCheck"
	if ($parsed.flags -contains "req") { $fillChecking = "ShowError" }
	X "$indent`t`t<FillChecking>$fillChecking</FillChecking>"

	X "$indent`t`t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$indent`t`t<ChoiceParameterLinks/>"
	X "$indent`t`t<ChoiceParameters/>"
	X "$indent`t`t<QuickChoice>Auto</QuickChoice>"
	X "$indent`t`t<CreateOnInput>Auto</CreateOnInput>"
	X "$indent`t`t<ChoiceForm/>"
	X "$indent`t`t<LinkByType/>"
	X "$indent`t`t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"

	# InformationRegister resources: Indexing, FullTextSearch, DataHistory
	if ($registerType -eq "InformationRegister") {
		X "$indent`t`t<Indexing>DontIndex</Indexing>"
		X "$indent`t`t<FullTextSearch>Use</FullTextSearch>"
		X "$indent`t`t<DataHistory>Use</DataHistory>"
	}

	# AccumulationRegister resources: FullTextSearch (no Indexing, no DataHistory)
	if ($registerType -eq "AccumulationRegister") {
		X "$indent`t`t<FullTextSearch>Use</FullTextSearch>"
	}

	X "$indent`t</Properties>"
	X "$indent</Resource>"
}

# --- 13. Property emitters per type ---

function Emit-CatalogProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	$hierarchical = if ($def.hierarchical -eq $true) { "true" } else { "false" }
	$hierarchyType = Get-EnumProp "HierarchyType" "hierarchyType" "HierarchyFoldersAndItems"
	X "$i<Hierarchical>$hierarchical</Hierarchical>"
	X "$i<HierarchyType>$hierarchyType</HierarchyType>"
	$limitLevelCount = if ($def.limitLevelCount -eq $true) { "true" } else { "false" }
	$levelCount = if ($null -ne $def.levelCount) { "$($def.levelCount)" } else { "2" }
	$foldersOnTop = if ($def.foldersOnTop -eq $false) { "false" } else { "true" }
	X "$i<LimitLevelCount>$limitLevelCount</LimitLevelCount>"
	X "$i<LevelCount>$levelCount</LevelCount>"
	X "$i<FoldersOnTop>$foldersOnTop</FoldersOnTop>"
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	if ($def.owners -and $def.owners.Count -gt 0) {
		X "$i<Owners>"
		foreach ($ownerRef in $def.owners) {
			$fullRef = if ("$ownerRef" -match '\.') { "$ownerRef" } else { "Catalog.$ownerRef" }
			X "$i`t<xr:Item xsi:type=`"xr:MDObjectRef`">$fullRef</xr:Item>"
		}
		X "$i</Owners>"
	} else {
		X "$i<Owners/>"
	}
	$subordinationUse = Get-EnumProp "SubordinationUse" "subordinationUse" "ToItems"
	X "$i<SubordinationUse>$subordinationUse</SubordinationUse>"

	$codeLength = if ($null -ne $def.codeLength) { "$($def.codeLength)" } else { "9" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "25" }
	$codeType = Get-EnumProp "CodeType" "codeType" "String"
	$codeAllowedLength = Get-EnumProp "CodeAllowedLength" "codeAllowedLength" "Variable"
	$autonumbering = if ($def.autonumbering -eq $false) { "false" } else { "true" }
	$checkUnique = if ($def.checkUnique -eq $true) { "true" } else { "false" }

	X "$i<CodeLength>$codeLength</CodeLength>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"
	X "$i<CodeType>$codeType</CodeType>"
	X "$i<CodeAllowedLength>$codeAllowedLength</CodeAllowedLength>"
	$codeSeries = Get-EnumProp "CodeSeries" "codeSeries" "WholeCatalog"
	X "$i<CodeSeries>$codeSeries</CodeSeries>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	X "$i<Autonumbering>$autonumbering</Autonumbering>"

	$defaultPresentation = Get-EnumProp "DefaultPresentation" "defaultPresentation" "AsDescription"
	X "$i<DefaultPresentation>$defaultPresentation</DefaultPresentation>"

	Emit-StandardAttributes $i "Catalog"
	X "$i<Characteristics/>"
	X "$i<PredefinedDataUpdate>Auto</PredefinedDataUpdate>"
	X "$i<EditType>InDialog</EditType>"
	# Быстрый выбор у справочника по умолчанию выключен - так его выгружает платформа.
	$quickChoice = if ($def.quickChoice -eq $true) { "true" } else { "false" }
	$choiceMode = Get-EnumProp "ChoiceMode" "choiceMode" "BothWays"
	X "$i<QuickChoice>$quickChoice</QuickChoice>"
	X "$i<ChoiceMode>$choiceMode</ChoiceMode>"
	# Нулевая длина означает, что реквизита у объекта нет: ссылка на него ломает загрузку.
	$inputFields = New-Object System.Collections.Generic.List[string]
	if ($descriptionLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>Catalog.$objName.StandardAttribute.Description</xr:Field>") }
	if ($codeLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>Catalog.$objName.StandardAttribute.Code</xr:Field>") }
	if ($inputFields.Count -gt 0) {
		X "$i<InputByString>"
		foreach ($fieldLine in $inputFields) { X $fieldLine }
		X "$i</InputByString>"
	} else {
		X "$i<InputByString/>"
	}
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultFolderForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<DefaultFolderChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryFolderForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<AuxiliaryFolderChoiceForm/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<BasedOn/>"
	X "$i<DataLockFields/>"

	# Управляемые блокировки - режим по умолчанию у нового справочника в выгрузке платформы.
	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<CreateOnInput>Use</CreateOnInput>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-DocumentProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<Numerator/>"

	$numberType = Get-EnumProp "NumberType" "numberType" "String"
	$numberLength = if ($null -ne $def.numberLength) { "$($def.numberLength)" } else { "11" }
	$numberAllowedLength = Get-EnumProp "NumberAllowedLength" "numberAllowedLength" "Variable"
	$numberPeriodicity = if ($def.numberPeriodicity) { "$($def.numberPeriodicity)" } else { "Year" }
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }
	$autonumbering = if ($def.autonumbering -eq $false) { "false" } else { "true" }

	X "$i<NumberType>$numberType</NumberType>"
	X "$i<NumberLength>$numberLength</NumberLength>"
	X "$i<NumberAllowedLength>$numberAllowedLength</NumberAllowedLength>"
	X "$i<NumberPeriodicity>$numberPeriodicity</NumberPeriodicity>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	X "$i<Autonumbering>$autonumbering</Autonumbering>"

	Emit-StandardAttributes $i "Document"
	X "$i<Characteristics/>"

	X "$i<BasedOn/>"
	X "$i<InputByString>"
	X "$i`t<xr:Field>Document.$objName.StandardAttribute.Number</xr:Field>"
	X "$i</InputByString>"
	X "$i<CreateOnInput>Use</CreateOnInput>"
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"

	$posting = Get-EnumProp "Posting" "posting" "Allow"
	$realTimePosting = Get-EnumProp "RealTimePosting" "realTimePosting" "Deny"
	$registerRecordsDeletion = Get-EnumProp "RegisterRecordsDeletion" "registerRecordsDeletion" "AutoDelete"
	$registerRecordsWritingOnPost = Get-EnumProp "RegisterRecordsWritingOnPost" "registerRecordsWritingOnPost" "WriteSelected"
	$sequenceFilling = if ($def.sequenceFilling) { "$($def.sequenceFilling)" } else { "AutoFill" }
	$postInPrivilegedMode = if ($def.postInPrivilegedMode -eq $false) { "false" } else { "true" }
	$unpostInPrivilegedMode = if ($def.unpostInPrivilegedMode -eq $false) { "false" } else { "true" }

	X "$i<Posting>$posting</Posting>"
	X "$i<RealTimePosting>$realTimePosting</RealTimePosting>"
	X "$i<RegisterRecordsDeletion>$registerRecordsDeletion</RegisterRecordsDeletion>"
	X "$i<RegisterRecordsWritingOnPost>$registerRecordsWritingOnPost</RegisterRecordsWritingOnPost>"
	X "$i<SequenceFilling>$sequenceFilling</SequenceFilling>"

	# RegisterRecords
	$regRecords = @()
	if ($def.registerRecords) {
		foreach ($rr in $def.registerRecords) {
			$rrStr = "$rr"
			# Resolve Russian synonyms in register records
			if ($rrStr.Contains('.')) {
				$dotIdx = $rrStr.IndexOf('.')
				$rrPrefix = $rrStr.Substring(0, $dotIdx)
				$rrSuffix = $rrStr.Substring($dotIdx + 1)
				if ($script:objectTypeSynonyms.ContainsKey($rrPrefix)) {
					$rrPrefix = $script:objectTypeSynonyms[$rrPrefix]
				}
				$regRecords += "$rrPrefix.$rrSuffix"
			} else {
				$regRecords += $rrStr
			}
		}
	}

	if ($regRecords.Count -gt 0) {
		X "$i<RegisterRecords>"
		foreach ($rr in $regRecords) {
			X "$i`t<xr:Item xsi:type=`"xr:MDObjectRef`">$rr</xr:Item>"
		}
		X "$i</RegisterRecords>"
	} else {
		X "$i<RegisterRecords/>"
	}

	X "$i<PostInPrivilegedMode>$postInPrivilegedMode</PostInPrivilegedMode>"
	X "$i<UnpostInPrivilegedMode>$unpostInPrivilegedMode</UnpostInPrivilegedMode>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-EnumProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>false</UseStandardCommands>"

	Emit-StandardAttributes $i "Enum"
	X "$i<Characteristics/>"

	X "$i<QuickChoice>true</QuickChoice>"
	X "$i<ChoiceMode>BothWays</ChoiceMode>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
}

function Emit-ConstantProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	# Type
	# Build-TypeStr рассчитан на реквизиты, где `type` и есть тип данных. У определения ОБЪЕКТА
	# `type` означает тип метаданных, поэтому общий откат тут не годится: без valueType в тип
	# значения попадало слово Constant, и платформа отвергала загрузку с "Неизвестное имя типа".
	$valueType = if ($def.valueType) { Build-TypeStr $def } else { "String" }
	Emit-ValueType $i $valueType

	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<DefaultForm/>"
	X "$i<ExtendedPresentation/>"
	X "$i<Explanation/>"
	X "$i<PasswordMode>false</PasswordMode>"
	X "$i<Format/>"
	X "$i<EditFormat/>"
	X "$i<ToolTip/>"
	X "$i<MarkNegatives>false</MarkNegatives>"
	X "$i<Mask/>"
	X "$i<MultiLine>false</MultiLine>"
	X "$i<ExtendedEdit>false</ExtendedEdit>"
	X "$i<MinValue xsi:nil=`"true`"/>"
	X "$i<MaxValue xsi:nil=`"true`"/>"
	X "$i<FillChecking>DontCheck</FillChecking>"
	X "$i<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$i<ChoiceParameterLinks/>"
	X "$i<ChoiceParameters/>"
	X "$i<QuickChoice>Auto</QuickChoice>"
	X "$i<ChoiceForm/>"
	X "$i<LinkByType/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-InformationRegisterProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<EditType>InDialog</EditType>"
	X "$i<DefaultRecordForm/>"
	X "$i<DefaultListForm/>"
	X "$i<AuxiliaryRecordForm/>"
	X "$i<AuxiliaryListForm/>"

	Emit-StandardAttributes $i "InformationRegister"

	$periodicity = Get-EnumProp "InformationRegisterPeriodicity" "periodicity" "Nonperiodical"
	$writeMode = Get-EnumProp "WriteMode" "writeMode" "Independent"

	# Основной отбор по периоду платформа по умолчанию не включает - ни при какой
	# периодичности. Значение задается ключом mainFilterOnPeriod.
	$mainFilterOnPeriod = "false"
	if ($null -ne $def.mainFilterOnPeriod) {
		$mainFilterOnPeriod = if ($def.mainFilterOnPeriod -eq $true) { "true" } else { "false" }
	}

	X "$i<InformationRegisterPeriodicity>$periodicity</InformationRegisterPeriodicity>"
	X "$i<WriteMode>$writeMode</WriteMode>"
	X "$i<MainFilterOnPeriod>$mainFilterOnPeriod</MainFilterOnPeriod>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<EnableTotalsSliceFirst>false</EnableTotalsSliceFirst>"
	X "$i<EnableTotalsSliceLast>false</EnableTotalsSliceLast>"
	X "$i<RecordPresentation/>"
	X "$i<ExtendedRecordPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-AccumulationRegisterProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<DefaultListForm/>"
	X "$i<AuxiliaryListForm/>"

	$registerType = Get-EnumProp "RegisterType" "registerType" "Balance"
	X "$i<RegisterType>$registerType</RegisterType>"

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	Emit-StandardAttributes $i "AccumulationRegister"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	$enableTotalsSplitting = if ($def.enableTotalsSplitting -eq $false) { "false" } else { "true" }
	X "$i<EnableTotalsSplitting>$enableTotalsSplitting</EnableTotalsSplitting>"

	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

# --- 13a. Wave 1: DefinedType, CommonModule, ScheduledJob, EventSubscription ---

function Emit-DefinedTypeProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	# Type - composite type with multiple v8:Type entries (accept both valueType and valueTypes)
	$valueTypes = @()
	if ($def.valueTypes) {
		$valueTypes = @($def.valueTypes)
	} elseif ($def.valueType) {
		$valueTypes = @($def.valueType)
	}
	if ($valueTypes.Count -gt 0) {
		X "$i<Type>"
		foreach ($vt in $valueTypes) {
			$resolved = Resolve-TypeStr "$vt"
			if ($resolved -match '^(CatalogRef|DocumentRef|EnumRef|ChartOfAccountsRef|ChartOfCharacteristicTypesRef|ChartOfCalculationTypesRef|ExchangePlanRef|BusinessProcessRef|TaskRef)\.') {
				X "$i`t<v8:Type xmlns:d5p1=`"http://v8.1c.ru/8.1/data/enterprise/current-config`">d5p1:$resolved</v8:Type>"
			} elseif ($resolved -eq "Boolean") {
				X "$i`t<v8:Type>xs:boolean</v8:Type>"
			} elseif ($resolved -match '^String') {
				X "$i`t<v8:Type>xs:string</v8:Type>"
				X "$i`t<v8:StringQualifiers>"
				X "$i`t`t<v8:Length>0</v8:Length>"
				X "$i`t`t<v8:AllowedLength>Variable</v8:AllowedLength>"
				X "$i`t</v8:StringQualifiers>"
			} else {
				X "$i`t<v8:Type>cfg:$resolved</v8:Type>"
			}
		}
		X "$i</Type>"
	} else {
		X "$i<Type/>"
	}
}

function Emit-CommonModuleProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	# Context shortcuts
	$context = if ($def.context) { "$($def.context)" } else { "" }

	$global = if ($def.global -eq $true) { "true" } else { "false" }
	$server = "false"; $serverCall = "false"; $clientManaged = "false"
	$clientOrdinary = "false"; $externalConnection = "false"; $privileged = "false"

	switch ($context) {
		"server"       { $server = "true"; $serverCall = "true" }
		"serverCall"   { $server = "true"; $serverCall = "true" }
		"client"       { $clientManaged = "true" }
		"serverClient" { $server = "true"; $clientManaged = "true" }
		default {
			if ($def.server -eq $true) { $server = "true" }
			if ($def.serverCall -eq $true) { $serverCall = "true" }
			if ($def.clientManagedApplication -eq $true) { $clientManaged = "true" }
			if ($def.clientOrdinaryApplication -eq $true) { $clientOrdinary = "true" }
			if ($def.externalConnection -eq $true) { $externalConnection = "true" }
			if ($def.privileged -eq $true) { $privileged = "true" }
		}
	}

	X "$i<Global>$global</Global>"
	X "$i<ClientManagedApplication>$clientManaged</ClientManagedApplication>"
	X "$i<Server>$server</Server>"
	X "$i<ExternalConnection>$externalConnection</ExternalConnection>"
	X "$i<ClientOrdinaryApplication>$clientOrdinary</ClientOrdinaryApplication>"
	X "$i<ServerCall>$serverCall</ServerCall>"
	X "$i<Privileged>$privileged</Privileged>"

	$returnValuesReuse = Get-EnumProp "ReturnValuesReuse" "returnValuesReuse" "DontUse"
	X "$i<ReturnValuesReuse>$returnValuesReuse</ReturnValuesReuse>"
}

function Emit-ScheduledJobProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	$methodName = if ($def.methodName) { "$($def.methodName)" } else { "" }
	# Ensure CommonModule. prefix
	if ($methodName -and -not $methodName.StartsWith("CommonModule.")) {
		$methodName = "CommonModule.$methodName"
	}
	X "$i<MethodName>$(Esc-Xml $methodName)</MethodName>"

	$description = if ($def.description) { "$($def.description)" } else { $synonym }
	X "$i<Description>$(Esc-Xml $description)</Description>"

	$key = if ($def.key) { "$($def.key)" } else { "" }
	X "$i<Key>$(Esc-Xml $key)</Key>"

	$use = if ($def.use -eq $true) { "true" } else { "false" }
	X "$i<Use>$use</Use>"

	$predefined = if ($def.predefined -eq $true) { "true" } else { "false" }
	X "$i<Predefined>$predefined</Predefined>"

	$restartCount = if ($null -ne $def.restartCountOnFailure) { "$($def.restartCountOnFailure)" } else { "3" }
	$restartInterval = if ($null -ne $def.restartIntervalOnFailure) { "$($def.restartIntervalOnFailure)" } else { "10" }
	X "$i<RestartCountOnFailure>$restartCount</RestartCountOnFailure>"
	X "$i<RestartIntervalOnFailure>$restartInterval</RestartIntervalOnFailure>"
}

function Emit-EventSubscriptionProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	# Source - array of v8:Type
	$sources = @()
	if ($def.source) { $sources = @($def.source) }
	if ($sources.Count -gt 0) {
		X "$i<Source>"
		foreach ($src in $sources) {
			$resolved = Resolve-TypeStr "$src"
			X "$i`t<v8:Type xmlns:d5p1=`"http://v8.1c.ru/8.1/data/enterprise/current-config`">d5p1:$resolved</v8:Type>"
		}
		X "$i</Source>"
	} else {
		X "$i<Source/>"
	}

	$event = if ($def.event) { "$($def.event)" } else { "BeforeWrite" }
	X "$i<Event>$event</Event>"

	$handler = if ($def.handler) { "$($def.handler)" } else { "" }
	# Ensure CommonModule. prefix
	if ($handler -and -not $handler.StartsWith("CommonModule.")) {
		$handler = "CommonModule.$handler"
	}
	X "$i<Handler>$(Esc-Xml $handler)</Handler>"
}

# --- 13b. Wave 2: Report, DataProcessor ---

function Emit-ReportProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$defaultForm = if ($def.defaultForm) { "$($def.defaultForm)" } else { "" }
	if ($defaultForm) { X "$i<DefaultForm>$defaultForm</DefaultForm>" } else { X "$i<DefaultForm/>" }

	$auxForm = if ($def.auxiliaryForm) { "$($def.auxiliaryForm)" } else { "" }
	if ($auxForm) { X "$i<AuxiliaryForm>$auxForm</AuxiliaryForm>" } else { X "$i<AuxiliaryForm/>" }

	$mainDCS = if ($def.mainDataCompositionSchema) { "$($def.mainDataCompositionSchema)" } else { "" }
	if ($mainDCS) { X "$i<MainDataCompositionSchema>$mainDCS</MainDataCompositionSchema>" } else { X "$i<MainDataCompositionSchema/>" }

	$defSettings = if ($def.defaultSettingsForm) { "$($def.defaultSettingsForm)" } else { "" }
	if ($defSettings) { X "$i<DefaultSettingsForm>$defSettings</DefaultSettingsForm>" } else { X "$i<DefaultSettingsForm/>" }

	$auxSettings = if ($def.auxiliarySettingsForm) { "$($def.auxiliarySettingsForm)" } else { "" }
	if ($auxSettings) { X "$i<AuxiliarySettingsForm>$auxSettings</AuxiliarySettingsForm>" } else { X "$i<AuxiliarySettingsForm/>" }

	$defVariant = if ($def.defaultVariantForm) { "$($def.defaultVariantForm)" } else { "" }
	if ($defVariant) { X "$i<DefaultVariantForm>$defVariant</DefaultVariantForm>" } else { X "$i<DefaultVariantForm/>" }

	X "$i<VariantsStorage/>"
	X "$i<SettingsStorage/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<ExtendedPresentation/>"
	X "$i<Explanation/>"
}

function Emit-DataProcessorProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	# Стандартные команды обработки платформа включает по умолчанию.
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$defaultForm = if ($def.defaultForm) { "$($def.defaultForm)" } else { "" }
	if ($defaultForm) { X "$i<DefaultForm>$defaultForm</DefaultForm>" } else { X "$i<DefaultForm/>" }

	$auxForm = if ($def.auxiliaryForm) { "$($def.auxiliaryForm)" } else { "" }
	if ($auxForm) { X "$i<AuxiliaryForm>$auxForm</AuxiliaryForm>" } else { X "$i<AuxiliaryForm/>" }

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<ExtendedPresentation/>"
	X "$i<Explanation/>"
}

# --- 13c. Wave 3: ExchangePlan, ChartOfCharacteristicTypes, DocumentJournal ---

function Emit-ExchangePlanProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$codeLength = if ($null -ne $def.codeLength) { "$($def.codeLength)" } else { "9" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "100" }
	$codeAllowedLength = Get-EnumProp "CodeAllowedLength" "codeAllowedLength" "Variable"

	X "$i<CodeLength>$codeLength</CodeLength>"
	X "$i<CodeAllowedLength>$codeAllowedLength</CodeAllowedLength>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"
	X "$i<DefaultPresentation>AsDescription</DefaultPresentation>"
	X "$i<EditType>InDialog</EditType>"

	Emit-StandardAttributes $i "ExchangePlan"

	$distributed = if ($def.distributedInfoBase -eq $true) { "true" } else { "false" }
	$includeExt = if ($def.includeConfigurationExtensions -eq $true) { "true" } else { "false" }
	X "$i<DistributedInfoBase>$distributed</DistributedInfoBase>"
	X "$i<IncludeConfigurationExtensions>$includeExt</IncludeConfigurationExtensions>"

	X "$i<BasedOn/>"
	X "$i<QuickChoice>true</QuickChoice>"
	X "$i<ChoiceMode>BothWays</ChoiceMode>"
	# Нулевая длина означает, что реквизита у объекта нет: ссылка на него ломает загрузку.
	$inputFields = New-Object System.Collections.Generic.List[string]
	if ($descriptionLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ExchangePlan.$objName.StandardAttribute.Description</xr:Field>") }
	if ($codeLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ExchangePlan.$objName.StandardAttribute.Code</xr:Field>") }
	if ($inputFields.Count -gt 0) {
		X "$i<InputByString>"
		foreach ($fieldLine in $inputFields) { X $fieldLine }
		X "$i</InputByString>"
	} else {
		X "$i<InputByString/>"
	}
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<CreateOnInput>Use</CreateOnInput>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-ChartOfCharacteristicTypesProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	$charExtValues = if ($def.characteristicExtValues) { "$($def.characteristicExtValues)" } else { "" }
	if ($charExtValues) { X "$i<CharacteristicExtValues>$charExtValues</CharacteristicExtValues>" }
	else { X "$i<CharacteristicExtValues/>" }

	# Type - composite type of allowed characteristic value types
	$valueTypes = @()
	if ($def.valueTypes) { $valueTypes = @($def.valueTypes) }
	elseif ($def.valueType) { $valueTypes = @($def.valueType) }
	if ($valueTypes.Count -gt 0) {
		X "$i<Type>"
		foreach ($vt in $valueTypes) {
			Emit-TypeContent "$i`t" "$vt"
		}
		X "$i</Type>"
	} else {
		X "$i<Type>"
		X "$i`t<v8:Type>xs:boolean</v8:Type>"
		X "$i`t<v8:Type>xs:string</v8:Type>"
		X "$i`t<v8:StringQualifiers>"
		X "$i`t`t<v8:Length>100</v8:Length>"
		X "$i`t`t<v8:AllowedLength>Variable</v8:AllowedLength>"
		X "$i`t</v8:StringQualifiers>"
		X "$i`t<v8:Type>xs:decimal</v8:Type>"
		X "$i`t<v8:NumberQualifiers>"
		X "$i`t`t<v8:Digits>15</v8:Digits>"
		X "$i`t`t<v8:FractionDigits>2</v8:FractionDigits>"
		X "$i`t`t<v8:AllowedSign>Any</v8:AllowedSign>"
		X "$i`t</v8:NumberQualifiers>"
		X "$i`t<v8:Type>xs:dateTime</v8:Type>"
		X "$i`t<v8:DateQualifiers>"
		X "$i`t`t<v8:DateFractions>DateTime</v8:DateFractions>"
		X "$i`t</v8:DateQualifiers>"
		X "$i</Type>"
	}

	$hierarchical = if ($def.hierarchical -eq $true) { "true" } else { "false" }
	X "$i<Hierarchical>$hierarchical</Hierarchical>"
	X "$i<FoldersOnTop>true</FoldersOnTop>"

	$codeLength = if ($null -ne $def.codeLength) { "$($def.codeLength)" } else { "9" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "100" }
	$codeAllowedLength = Get-EnumProp "CodeAllowedLength" "codeAllowedLength" "Variable"
	$autonumbering = if ($def.autonumbering -eq $false) { "false" } else { "true" }
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }

	$codeSeries = if ($def.codeSeries) { "$($def.codeSeries)" } else { "WholeCharacteristicKind" }
	X "$i<CodeLength>$codeLength</CodeLength>"
	X "$i<CodeAllowedLength>$codeAllowedLength</CodeAllowedLength>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"
	X "$i<CodeSeries>$codeSeries</CodeSeries>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	X "$i<Autonumbering>$autonumbering</Autonumbering>"
	X "$i<DefaultPresentation>AsDescription</DefaultPresentation>"

	# CharacteristicExtValues

	Emit-StandardAttributes $i "ChartOfCharacteristicTypes"
	X "$i<Characteristics/>"
	X "$i<PredefinedDataUpdate>Auto</PredefinedDataUpdate>"
	X "$i<EditType>InDialog</EditType>"
	$quickChoice = if ($def.quickChoice -eq $true) { "true" } else { "false" }
	X "$i<QuickChoice>$quickChoice</QuickChoice>"
	X "$i<ChoiceMode>BothWays</ChoiceMode>"
	# Нулевая длина означает, что реквизита у объекта нет: ссылка на него ломает загрузку.
	$inputFields = New-Object System.Collections.Generic.List[string]
	if ($descriptionLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfCharacteristicTypes.$objName.StandardAttribute.Description</xr:Field>") }
	if ($codeLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfCharacteristicTypes.$objName.StandardAttribute.Code</xr:Field>") }
	if ($inputFields.Count -gt 0) {
		X "$i<InputByString>"
		foreach ($fieldLine in $inputFields) { X $fieldLine }
		X "$i</InputByString>"
	} else {
		X "$i<InputByString/>"
	}
	$createOnInput = Get-EnumProp "CreateOnInput" "createOnInput" "DontUse"
	X "$i<CreateOnInput>$createOnInput</CreateOnInput>"
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultFolderForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<DefaultFolderChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryFolderForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<AuxiliaryFolderChoiceForm/>"
	X "$i<BasedOn/>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-DocumentJournalProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	$defaultForm = if ($def.defaultForm) { "$($def.defaultForm)" } else { "" }
	if ($defaultForm) { X "$i<DefaultForm>$defaultForm</DefaultForm>" } else { X "$i<DefaultForm/>" }

	$auxForm = if ($def.auxiliaryForm) { "$($def.auxiliaryForm)" } else { "" }
	if ($auxForm) { X "$i<AuxiliaryForm>$auxForm</AuxiliaryForm>" } else { X "$i<AuxiliaryForm/>" }

	X "$i<UseStandardCommands>true</UseStandardCommands>"

	# RegisteredDocuments
	$regDocs = @()
	if ($def.registeredDocuments) { $regDocs = @($def.registeredDocuments) }
	if ($regDocs.Count -gt 0) {
		X "$i<RegisteredDocuments>"
		foreach ($rd in $regDocs) {
			$rdStr = "$rd"
			# Resolve Russian synonyms: Документ.Xxx → Document.Xxx
			if ($rdStr.Contains('.')) {
				$dotIdx = $rdStr.IndexOf('.')
				$rdPrefix = $rdStr.Substring(0, $dotIdx)
				$rdSuffix = $rdStr.Substring($dotIdx + 1)
				if ($script:objectTypeSynonyms.ContainsKey($rdPrefix)) {
					$rdPrefix = $script:objectTypeSynonyms[$rdPrefix]
				}
				$rdStr = "$rdPrefix.$rdSuffix"
			}
			X "$i`t<xr:Item xsi:type=`"xr:MDObjectRef`">$rdStr</xr:Item>"
		}
		X "$i</RegisteredDocuments>"
	} else {
		X "$i<RegisteredDocuments/>"
	}

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	Emit-StandardAttributes $i "DocumentJournal"

	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

# --- 13d. Wave 4: ChartOfAccounts, AccountingRegister, ChartOfCalculationTypes, CalculationRegister ---

function Emit-ChartOfAccountsProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<BasedOn/>"

	# ExtDimensionTypes
	$extDimTypes = if ($def.extDimensionTypes) { "$($def.extDimensionTypes)" } else { "" }
	if ($extDimTypes) { X "$i<ExtDimensionTypes>$extDimTypes</ExtDimensionTypes>" }
	else { X "$i<ExtDimensionTypes/>" }

	# Счетчик субконто по умолчанию зависит от того, задан ли план видов характеристик. Без него
	# ненулевой счетчик дает объект, который платформа не грузит: "У плана счетов с количеством
	# субконто не равным 0 должен быть установлен план видов характеристик".
	$defaultMaxExtDim = if ($extDimTypes) { "3" } else { "0" }
	$maxExtDim = if ($null -ne $def.maxExtDimensionCount) { "$($def.maxExtDimensionCount)" } else { $defaultMaxExtDim }
	if (-not $extDimTypes -and $maxExtDim -ne "0") {
		[Console]::Error.WriteLine("Warning: MaxExtDimensionCount=$maxExtDim without extDimensionTypes - the platform will refuse to load this chart of accounts. Set extDimensionTypes to a ChartOfCharacteristicTypes reference or leave the count at 0.")
	}
	X "$i<MaxExtDimensionCount>$maxExtDim</MaxExtDimensionCount>"

	$codeMask = if ($def.codeMask) { "$($def.codeMask)" } else { "" }
	if ($codeMask) { X "$i<CodeMask>$codeMask</CodeMask>" } else { X "$i<CodeMask/>" }

	$codeLength = if ($null -ne $def.codeLength) { "$($def.codeLength)" } else { "8" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "120" }
	$codeSeries = if ($def.codeSeries) { "$($def.codeSeries)" } else { "WholeChartOfAccounts" }
	$autoOrder = if ($def.autoOrderByCode -eq $false) { "false" } else { "true" }
	$orderLength = if ($null -ne $def.orderLength) { "$($def.orderLength)" } else { "9" }

	X "$i<CodeLength>$codeLength</CodeLength>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"
	X "$i<CodeSeries>$codeSeries</CodeSeries>"
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	$defaultPresentation = Get-EnumProp "DefaultPresentation" "defaultPresentation" "AsCode"
	X "$i<DefaultPresentation>$defaultPresentation</DefaultPresentation>"

	Emit-StandardAttributes $i "ChartOfAccounts"

	# StandardTabularSections - ExtDimensionTypes

	X "$i<Characteristics/>"
	X "$i<StandardTabularSections>"
	X "$i`t<xr:StandardTabularSection name=`"ExtDimensionTypes`">"
	# Стандартная табличная часть несет свой заголовок и проверку заполнения - платформа
	# пишет их перед составом реквизитов.
	X "$i`t`t<xr:Synonym>"
	X "$i`t`t`t<v8:item>"
	X "$i`t`t`t`t<v8:lang/>"
	X "$i`t`t`t`t<v8:content>Виды субконто</v8:content>"
	X "$i`t`t`t</v8:item>"
	X "$i`t`t</xr:Synonym>"
	X "$i`t`t<xr:Comment/>"
	X "$i`t`t<xr:ToolTip/>"
	X "$i`t`t<xr:FillChecking>DontCheck</xr:FillChecking>"
	X "$i`t`t<xr:StandardAttributes>"
	foreach ($stAttr in @("TurnoversOnly","Predefined","ExtDimensionType","LineNumber")) {
		# Вид субконто заполняется обязательно: без него строка табличной части бессмысленна.
		$required = $stAttr -eq "ExtDimensionType"
		Emit-StandardAttribute "$i`t`t`t" $stAttr $required
	}
	X "$i`t`t</xr:StandardAttributes>"
	X "$i`t</xr:StandardTabularSection>"
	X "$i</StandardTabularSections>"
	X "$i<PredefinedDataUpdate>Auto</PredefinedDataUpdate>"
	X "$i<EditType>InDialog</EditType>"
	$quickChoice = if ($def.quickChoice -eq $true) { "true" } else { "false" }
	X "$i<QuickChoice>$quickChoice</QuickChoice>"
	X "$i<ChoiceMode>BothWays</ChoiceMode>"
	# Нулевая длина означает, что реквизита у объекта нет: ссылка на него ломает загрузку.
	$inputFields = New-Object System.Collections.Generic.List[string]
	if ($descriptionLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfAccounts.$objName.StandardAttribute.Description</xr:Field>") }
	if ($codeLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfAccounts.$objName.StandardAttribute.Code</xr:Field>") }
	if ($inputFields.Count -gt 0) {
		X "$i<InputByString>"
		foreach ($fieldLine in $inputFields) { X $fieldLine }
		X "$i</InputByString>"
	} else {
		X "$i<InputByString/>"
	}
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	$createOnInput = Get-EnumProp "CreateOnInput" "createOnInput" "DontUse"
	X "$i<CreateOnInput>$createOnInput</CreateOnInput>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"

	X "$i<AutoOrderByCode>$autoOrder</AutoOrderByCode>"
	X "$i<OrderLength>$orderLength</OrderLength>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

function Emit-AccountingRegisterProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<DefaultListForm/>"
	X "$i<AuxiliaryListForm/>"

	$chartOfAccounts = if ($def.chartOfAccounts) { "$($def.chartOfAccounts)" } else { "" }
	if ($chartOfAccounts) { X "$i<ChartOfAccounts>$chartOfAccounts</ChartOfAccounts>" }
	else { X "$i<ChartOfAccounts/>" }

	$correspondence = if ($def.correspondence -eq $true) { "true" } else { "false" }
	X "$i<Correspondence>$correspondence</Correspondence>"

	$periodAdjLen = if ($null -ne $def.periodAdjustmentLength) { "$($def.periodAdjustmentLength)" } else { "0" }
	X "$i<PeriodAdjustmentLength>$periodAdjLen</PeriodAdjustmentLength>"

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	Emit-StandardAttributes $i "AccountingRegister"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

function Emit-ChartOfCalculationTypesProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$codeLength = if ($null -ne $def.codeLength) { "$($def.codeLength)" } else { "5" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "100" }
	$codeType = Get-EnumProp "CodeType" "codeType" "String"
	$codeAllowedLength = Get-EnumProp "CodeAllowedLength" "codeAllowedLength" "Variable"

	X "$i<CodeLength>$codeLength</CodeLength>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"
	X "$i<CodeType>$codeType</CodeType>"
	X "$i<CodeAllowedLength>$codeAllowedLength</CodeAllowedLength>"
	X "$i<DefaultPresentation>AsDescription</DefaultPresentation>"


	Emit-StandardAttributes $i "ChartOfCalculationTypes"
	X "$i<EditType>InDialog</EditType>"
	$quickChoice = if ($def.quickChoice -eq $true) { "true" } else { "false" }
	X "$i<QuickChoice>$quickChoice</QuickChoice>"
	X "$i<ChoiceMode>BothWays</ChoiceMode>"
	# Нулевая длина означает, что реквизита у объекта нет: ссылка на него ломает загрузку.
	$inputFields = New-Object System.Collections.Generic.List[string]
	if ($descriptionLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfCalculationTypes.$objName.StandardAttribute.Description</xr:Field>") }
	if ($codeLength -ne '0') { [void]$inputFields.Add("$i`t<xr:Field>ChartOfCalculationTypes.$objName.StandardAttribute.Code</xr:Field>") }
	if ($inputFields.Count -gt 0) {
		X "$i<InputByString>"
		foreach ($fieldLine in $inputFields) { X $fieldLine }
		X "$i</InputByString>"
	} else {
		X "$i<InputByString/>"
	}
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	$createOnInput = Get-EnumProp "CreateOnInput" "createOnInput" "DontUse"
	X "$i<CreateOnInput>$createOnInput</CreateOnInput>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<BasedOn/>"

	$dependence = Get-EnumProp "DependenceOnCalculationTypes" "dependenceOnCalculationTypes" "DontUse"
	X "$i<DependenceOnCalculationTypes>$dependence</DependenceOnCalculationTypes>"

	# BaseCalculationTypes
	$baseTypes = @()
	if ($def.baseCalculationTypes) { $baseTypes = @($def.baseCalculationTypes) }
	if ($baseTypes.Count -gt 0) {
		X "$i<BaseCalculationTypes>"
		foreach ($bt in $baseTypes) {
			X "$i`t<xr:Item xsi:type=`"xr:MDObjectRef`">$bt</xr:Item>"
		}
		X "$i</BaseCalculationTypes>"
	} else {
		X "$i<BaseCalculationTypes/>"
	}

	$actionPeriodUse = if ($def.actionPeriodUse -eq $true) { "true" } else { "false" }
	X "$i<ActionPeriodUse>$actionPeriodUse</ActionPeriodUse>"
	X "$i<Characteristics/>"
	# Стандартные табличные части плана видов расчета: ведущие, вытесняющие и базовые виды.
	# Состав задан платформой, настройке не подлежит.
	X "$i<StandardTabularSections>"
	X "$i`t<xr:StandardTabularSection name=`"LeadingCalculationTypes`">"
	X "$i`t`t<xr:Synonym>"
	X "$i`t`t`t<v8:item>"
	X "$i`t`t`t`t<v8:lang/>"
	X "$i`t`t`t`t<v8:content>Ведущие виды расчета</v8:content>"
	X "$i`t`t`t</v8:item>"
	X "$i`t`t</xr:Synonym>"
	X "$i`t`t<xr:Comment/>"
	X "$i`t`t<xr:ToolTip/>"
	X "$i`t`t<xr:FillChecking>DontCheck</xr:FillChecking>"
	X "$i`t`t<xr:StandardAttributes>"
	foreach ($stAttr in @("Predefined","CalculationType","LineNumber")) {
		Emit-StandardAttribute "$i`t`t`t" $stAttr ($stAttr -eq "CalculationType")
	}
	X "$i`t`t</xr:StandardAttributes>"
	X "$i`t</xr:StandardTabularSection>"
	X "$i`t<xr:StandardTabularSection name=`"DisplacingCalculationTypes`">"
	X "$i`t`t<xr:Synonym>"
	X "$i`t`t`t<v8:item>"
	X "$i`t`t`t`t<v8:lang/>"
	X "$i`t`t`t`t<v8:content>Вытесняющие виды расчета</v8:content>"
	X "$i`t`t`t</v8:item>"
	X "$i`t`t</xr:Synonym>"
	X "$i`t`t<xr:Comment/>"
	X "$i`t`t<xr:ToolTip/>"
	X "$i`t`t<xr:FillChecking>DontCheck</xr:FillChecking>"
	X "$i`t`t<xr:StandardAttributes>"
	foreach ($stAttr in @("Predefined","CalculationType","LineNumber")) {
		Emit-StandardAttribute "$i`t`t`t" $stAttr ($stAttr -eq "CalculationType")
	}
	X "$i`t`t</xr:StandardAttributes>"
	X "$i`t</xr:StandardTabularSection>"
	X "$i`t<xr:StandardTabularSection name=`"BaseCalculationTypes`">"
	X "$i`t`t<xr:Synonym>"
	X "$i`t`t`t<v8:item>"
	X "$i`t`t`t`t<v8:lang/>"
	X "$i`t`t`t`t<v8:content>Базовые виды расчета</v8:content>"
	X "$i`t`t`t</v8:item>"
	X "$i`t`t</xr:Synonym>"
	X "$i`t`t<xr:Comment/>"
	X "$i`t`t<xr:ToolTip/>"
	X "$i`t`t<xr:FillChecking>DontCheck</xr:FillChecking>"
	X "$i`t`t<xr:StandardAttributes>"
	foreach ($stAttr in @("Predefined","CalculationType","LineNumber")) {
		Emit-StandardAttribute "$i`t`t`t" $stAttr ($stAttr -eq "CalculationType")
	}
	X "$i`t`t</xr:StandardAttributes>"
	X "$i`t</xr:StandardTabularSection>"
	X "$i</StandardTabularSections>"
	X "$i<PredefinedDataUpdate>Auto</PredefinedDataUpdate>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<DataLockFields/>"
	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"
	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"


	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"




}

function Emit-CalculationRegisterProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"
	X "$i<DefaultListForm/>"
	X "$i<AuxiliaryListForm/>"


	$periodicity = Get-EnumProp "InformationRegisterPeriodicity" "periodicity" "Month"
	X "$i<Periodicity>$periodicity</Periodicity>"

	$actionPeriod = if ($def.actionPeriod -eq $true) { "true" } else { "false" }
	X "$i<ActionPeriod>$actionPeriod</ActionPeriod>"

	$basePeriod = if ($def.basePeriod -eq $true) { "true" } else { "false" }
	X "$i<BasePeriod>$basePeriod</BasePeriod>"

	$schedule = if ($def.schedule) { "$($def.schedule)" } else { "" }
	if ($schedule) { X "$i<Schedule>$schedule</Schedule>" } else { X "$i<Schedule/>" }

	$scheduleValue = if ($def.scheduleValue) { "$($def.scheduleValue)" } else { "" }
	if ($scheduleValue) { X "$i<ScheduleValue>$scheduleValue</ScheduleValue>" } else { X "$i<ScheduleValue/>" }

	$scheduleDate = if ($def.scheduleDate) { "$($def.scheduleDate)" } else { "" }
	if ($scheduleDate) { X "$i<ScheduleDate>$scheduleDate</ScheduleDate>" } else { X "$i<ScheduleDate/>" }
	$chartOfCalcTypes = if ($def.chartOfCalculationTypes) { "$($def.chartOfCalculationTypes)" } else { "" }
	if ($chartOfCalcTypes) { X "$i<ChartOfCalculationTypes>$chartOfCalcTypes</ChartOfCalculationTypes>" }
	else { X "$i<ChartOfCalculationTypes/>" }

	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"

	Emit-StandardAttributes $i "CalculationRegister"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

# --- 13e. Wave 5: BusinessProcess, Task ---

function Emit-BusinessProcessProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$editType = Get-EnumProp "EditType" "editType" "InDialog"
	X "$i<EditType>$editType</EditType>"

	$numberType = Get-EnumProp "NumberType" "numberType" "String"
	$numberLength = if ($null -ne $def.numberLength) { "$($def.numberLength)" } else { "11" }
	$numberAllowedLength = Get-EnumProp "NumberAllowedLength" "numberAllowedLength" "Variable"
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }
	$autonumbering = if ($def.autonumbering -eq $false) { "false" } else { "true" }

	X "$i<NumberType>$numberType</NumberType>"
	X "$i<NumberLength>$numberLength</NumberLength>"
	X "$i<NumberAllowedLength>$numberAllowedLength</NumberAllowedLength>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	X "$i<Autonumbering>$autonumbering</Autonumbering>"

	Emit-StandardAttributes $i "BusinessProcess"
	X "$i<Characteristics/>"

	$task = if ($def.task) { "$($def.task)" } else { "" }
	if ($task) {
		X "$i<Task>$task</Task>"
	} else {
		X "$i<Task/>"
	}

	X "$i<BasedOn/>"
	X "$i<InputByString>"
	X "$i`t<xr:Field>BusinessProcess.$objName.StandardAttribute.Number</xr:Field>"
	X "$i</InputByString>"
	X "$i<CreateOnInput>Use</CreateOnInput>"
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

function Emit-TaskProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i
	X "$i<UseStandardCommands>true</UseStandardCommands>"

	$numberType = Get-EnumProp "NumberType" "numberType" "String"
	$numberLength = if ($null -ne $def.numberLength) { "$($def.numberLength)" } else { "14" }
	$numberAllowedLength = Get-EnumProp "NumberAllowedLength" "numberAllowedLength" "Variable"
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }
	$autonumbering = if ($def.autonumbering -eq $false) { "false" } else { "true" }

	$taskNumberAutoPrefix = if ($def.taskNumberAutoPrefix) { "$($def.taskNumberAutoPrefix)" } else { "BusinessProcessNumber" }
	$descriptionLength = if ($null -ne $def.descriptionLength) { "$($def.descriptionLength)" } else { "150" }

	X "$i<NumberType>$numberType</NumberType>"
	X "$i<NumberLength>$numberLength</NumberLength>"
	X "$i<NumberAllowedLength>$numberAllowedLength</NumberAllowedLength>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
	X "$i<Autonumbering>$autonumbering</Autonumbering>"
	X "$i<TaskNumberAutoPrefix>$taskNumberAutoPrefix</TaskNumberAutoPrefix>"
	X "$i<DescriptionLength>$descriptionLength</DescriptionLength>"

	# Addressing
	$addressing = if ($def.addressing) { "$($def.addressing)" } else { "" }
	if ($addressing) { X "$i<Addressing>$addressing</Addressing>" } else { X "$i<Addressing/>" }

	$mainAddressing = if ($def.mainAddressingAttribute) { "$($def.mainAddressingAttribute)" } else { "" }
	if ($mainAddressing) { X "$i<MainAddressingAttribute>$mainAddressing</MainAddressingAttribute>" } else { X "$i<MainAddressingAttribute/>" }

	$currentPerformer = if ($def.currentPerformer) { "$($def.currentPerformer)" } else { "" }
	if ($currentPerformer) { X "$i<CurrentPerformer>$currentPerformer</CurrentPerformer>" } else { X "$i<CurrentPerformer/>" }

	Emit-StandardAttributes $i "Task"
	X "$i<Characteristics/>"

	X "$i<BasedOn/>"
	X "$i<InputByString>"
	X "$i`t<xr:Field>Task.$objName.StandardAttribute.Number</xr:Field>"
	X "$i</InputByString>"
	X "$i<CreateOnInput>Use</CreateOnInput>"
	X "$i<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>"
	X "$i<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>"
	X "$i<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>"
	X "$i<DefaultObjectForm/>"
	X "$i<DefaultListForm/>"
	X "$i<DefaultChoiceForm/>"
	X "$i<AuxiliaryObjectForm/>"
	X "$i<AuxiliaryListForm/>"
	X "$i<AuxiliaryChoiceForm/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	X "$i<DataLockFields/>"

	$dataLockControlMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$dataLockControlMode</DataLockControlMode>"

	$fullTextSearch = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fullTextSearch</FullTextSearch>"

	X "$i<ObjectPresentation/>"
	X "$i<ExtendedObjectPresentation/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$i<DataHistory>DontUse</DataHistory>"
	X "$i<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>"
	X "$i<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>"
}

# --- 13f. Wave 6: HTTPService, WebService ---

function Emit-HTTPServiceProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	$rootURL = if ($def.rootURL) { "$($def.rootURL)" } else { $objName.ToLower() }
	X "$i<RootURL>$(Esc-Xml $rootURL)</RootURL>"

	$reuseSessions = Get-EnumProp "ReuseSessions" "reuseSessions" "DontUse"
	X "$i<ReuseSessions>$reuseSessions</ReuseSessions>"

	$sessionMaxAge = if ($null -ne $def.sessionMaxAge) { "$($def.sessionMaxAge)" } else { "20" }
	X "$i<SessionMaxAge>$sessionMaxAge</SessionMaxAge>"
}

function Emit-WebServiceProperties {
	param([string]$indent)
	$i = $indent

	X "$i<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $i "Synonym" $synonym
	Emit-Comment $i

	$namespace = if ($def.namespace) { "$($def.namespace)" } else { "" }
	X "$i<Namespace>$(Esc-Xml $namespace)</Namespace>"

	# Пакеты уходят списком значений. Замер на платформе 8.3.27.2214: плоскую строку
	# платформа отвергает при загрузке с ошибкой чтения свойства XDTOPackages как
	# ValueList, а принимает элементы xr:Item. Выгрузка платформы содержит у каждого
	# элемента Presentation, CheckState и Value.
	$packages = @()
	if ($def.xdtoPackages -is [System.Collections.IEnumerable] -and $def.xdtoPackages -isnot [string]) {
		$packages = @($def.xdtoPackages | ForEach-Object { "$_" } | Where-Object { $_ })
	} elseif ($def.xdtoPackages) {
		$packages = @("$($def.xdtoPackages)".Split(" ", [StringSplitOptions]::RemoveEmptyEntries))
	}
	if ($packages.Count -gt 0) {
		X "$i<XDTOPackages>"
		foreach ($pkg in $packages) {
			X "$i`t<xr:Item>"
			X "$i`t`t<xr:Presentation/>"
			X "$i`t`t<xr:CheckState>0</xr:CheckState>"
			X "$i`t`t<xr:Value xsi:type=`"xs:string`">$(Esc-Xml $pkg)</xr:Value>"
			X "$i`t</xr:Item>"
		}
		X "$i</XDTOPackages>"
	} else {
		X "$i<XDTOPackages/>"
	}

	# Имя файла описания сервиса платформа выводит из имени объекта.
	$descriptor = if ($def.descriptorFileName) { "$($def.descriptorFileName)" } else { "$objName.1cws" }
	X "$i<DescriptorFileName>$(Esc-Xml $descriptor)</DescriptorFileName>"

	$reuseSessions = Get-EnumProp "ReuseSessions" "reuseSessions" "DontUse"
	X "$i<ReuseSessions>$reuseSessions</ReuseSessions>"

	$sessionMaxAge = if ($null -ne $def.sessionMaxAge) { "$($def.sessionMaxAge)" } else { "20" }
	X "$i<SessionMaxAge>$sessionMaxAge</SessionMaxAge>"
}

# --- 13g. ChildObjects emitters for new types ---

function Emit-Column {
	param([string]$indent, $colDef)
	$uuid = New-Guid-String

	$name = ""
	$synonym = ""
	$indexing = "DontIndex"
	$references = @()

	if ($colDef -is [string]) {
		$name = "$colDef"
		$synonym = Split-CamelCase $name
	} else {
		$name = "$($colDef.name)"
		$synonym = if ($colDef.synonym) { $colDef.synonym } else { Split-CamelCase $name }
		if ($colDef.indexing) { $indexing = "$($colDef.indexing)" }
		if ($colDef.references) { $references = @($colDef.references) }
	}

	X "$indent<Column uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $synonym
	X "$indent`t`t<Comment/>"
	X "$indent`t`t<Indexing>$indexing</Indexing>"
	if ($references.Count -gt 0) {
		X "$indent`t`t<References>"
		foreach ($ref in $references) {
			X "$indent`t`t`t<xr:Item xsi:type=`"xr:MDObjectRef`">$ref</xr:Item>"
		}
		X "$indent`t`t</References>"
	} else {
		X "$indent`t`t<References/>"
	}
	X "$indent`t</Properties>"
	X "$indent</Column>"
}

function Emit-AccountingFlagProps {
	param([string]$indent, $flag, [string]$tag)
	# Признак учета и признак учета субконто различаются только именем элемента.
	$flagName = if ($flag -is [string]) { $flag } else { "$($flag.name)" }
	$flagSynonym = if ($flag -isnot [string] -and $flag.synonym) { "$($flag.synonym)" } else { Split-CamelCase $flagName }
	$flagTooltip = if ($flag -isnot [string] -and $flag.tooltip) { "$($flag.tooltip)" } else { '' }
	$flagFill = if ($flag -is [string]) { $null } else { $flag.fillValue }
	$uid = New-Guid-String
	X "$indent<$tag uuid=`"$uid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $flagName)</Name>"
	Emit-MLText "$indent`t`t" 'Synonym' $flagSynonym
	X "$indent`t`t<Comment/>"
	X "$indent`t`t<Type>"
	X "$indent`t`t`t<v8:Type>xs:boolean</v8:Type>"
	X "$indent`t`t</Type>"
	X "$indent`t`t<PasswordMode>false</PasswordMode>"
	X "$indent`t`t<Format/>"
	X "$indent`t`t<EditFormat/>"
	Emit-MLText "$indent`t`t" 'ToolTip' $flagTooltip
	X "$indent`t`t<MarkNegatives>false</MarkNegatives>"
	X "$indent`t`t<Mask/>"
	X "$indent`t`t<MultiLine>false</MultiLine>"
	X "$indent`t`t<ExtendedEdit>false</ExtendedEdit>"
	X "$indent`t`t<MinValue xsi:nil=`"true`"/>"
	X "$indent`t`t<MaxValue xsi:nil=`"true`"/>"
	X "$indent`t`t<FillFromFillingValue>false</FillFromFillingValue>"
	if ($flagFill -eq $true) {
		X "$indent`t`t<FillValue xsi:type=`"xs:boolean`">true</FillValue>"
	} elseif ($flagFill -eq $false) {
		X "$indent`t`t<FillValue xsi:type=`"xs:boolean`">false</FillValue>"
	} else {
		# Незаданное значение заполнения платформа пишет пустой строкой, а не признаком nil.
		X "$indent`t`t<FillValue xsi:type=`"xs:string`"/>"
	}
	X "$indent`t`t<FillChecking>DontCheck</FillChecking>"
	X "$indent`t`t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$indent`t`t<ChoiceParameterLinks/>"
	X "$indent`t`t<ChoiceParameters/>"
	X "$indent`t`t<QuickChoice>Auto</QuickChoice>"
	X "$indent`t`t<CreateOnInput>Auto</CreateOnInput>"
	X "$indent`t`t<ChoiceForm/>"
	X "$indent`t`t<LinkByType/>"
	X "$indent`t`t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"
	X "$indent`t`t<DataHistory>Use</DataHistory>"
	X "$indent`t</Properties>"
	X "$indent</$tag>"
}

function Emit-AccountingFlag {
	param([string]$indent, $flag)
	Emit-AccountingFlagProps $indent $flag 'AccountingFlag'
}

function Emit-ExtDimensionAccountingFlag {
	param([string]$indent, $flag)
	Emit-AccountingFlagProps $indent $flag 'ExtDimensionAccountingFlag'
}


function Emit-URLTemplate {
	param([string]$indent, [string]$tmplName, $tmplDef)
	$uuid = New-Guid-String
	$tmplSynonym = Split-CamelCase $tmplName

	$template = ""
	$tmplComment = ""
	# Порядок объявления значим (для операции это ее сигнатура), поэтому упорядоченный словарь:
	# обычная хеш-таблица PowerShell отдает ключи в произвольном порядке.
	$methods = [ordered]@{}

	if ($tmplDef -is [string]) {
		$template = "$tmplDef"
	} else {
		$template = if ($tmplDef.template) { "$($tmplDef.template)" } else { "/$($tmplName.ToLower())" }
		if ($tmplDef.synonym) { $tmplSynonym = $tmplDef.synonym }
		if ($tmplDef.comment) { $tmplComment = "$($tmplDef.comment)" }
		if ($tmplDef.methods) {
			$tmplDef.methods.PSObject.Properties | ForEach-Object {
				# Метод задается кратко строкой с видом запроса или объектом с обработчиком.
				$methods[$_.Name] = $_.Value
			}
		}
	}

	X "$indent<URLTemplate uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $tmplName)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $tmplSynonym
	if ($tmplComment) { X "$indent`t`t<Comment>$(Esc-Xml $tmplComment)</Comment>" } else { X "$indent`t`t<Comment/>" }
	X "$indent`t`t<Template>$(Esc-Xml $template)</Template>"
	X "$indent`t</Properties>"

	if ($methods.Count -gt 0) {
		X "$indent`t<ChildObjects>"
		foreach ($methodName in $methods.Keys) {
			$methodUuid = New-Guid-String
			$methodDef = $methods[$methodName]
			$methodSynonym = Split-CamelCase $methodName
			$methodComment = ""
			if ($methodDef -is [string]) {
				$httpMethod = "$methodDef"
				$handler = "${tmplName}${methodName}"
			} else {
				$httpMethod = if ($methodDef.httpMethod) { "$($methodDef.httpMethod)" } else { "GET" }
				$handler = if ($methodDef.handler) { "$($methodDef.handler)" } else { "${tmplName}${methodName}" }
				if ($methodDef.synonym) { $methodSynonym = $methodDef.synonym }
				if ($methodDef.comment) { $methodComment = "$($methodDef.comment)" }
			}

			X "$indent`t`t<Method uuid=`"$methodUuid`">"
			X "$indent`t`t`t<Properties>"
			X "$indent`t`t`t`t<Name>$(Esc-Xml $methodName)</Name>"
			Emit-MLText "$indent`t`t`t`t" "Synonym" $methodSynonym
			if ($methodComment) { X "$indent`t`t`t`t<Comment>$(Esc-Xml $methodComment)</Comment>" } else { X "$indent`t`t`t`t<Comment/>" }
			X "$indent`t`t`t`t<HTTPMethod>$httpMethod</HTTPMethod>"
			X "$indent`t`t`t`t<Handler>$(Esc-Xml $handler)</Handler>"
			X "$indent`t`t`t</Properties>"
			X "$indent`t`t</Method>"
		}
		X "$indent`t</ChildObjects>"
	} else {
		X "$indent`t<ChildObjects/>"
	}

	X "$indent</URLTemplate>"
}

function Emit-Operation {
	param([string]$indent, [string]$opName, $opDef)
	$uuid = New-Guid-String
	$opSynonym = Split-CamelCase $opName

	$returnType = "xs:string"
	$nillable = "false"
	$transactioned = "false"
	$handler = $opName
	# Порядок объявления значим (для операции это ее сигнатура), поэтому упорядоченный словарь:
	# обычная хеш-таблица PowerShell отдает ключи в произвольном порядке.
	$params = [ordered]@{}

	if ($opDef -is [string]) {
		$returnType = "$opDef"
	} else {
		if ($opDef.returnType) { $returnType = "$($opDef.returnType)" }
		if ($opDef.nillable -eq $true) { $nillable = "true" }
		if ($opDef.transactioned -eq $true) { $transactioned = "true" }
		if ($opDef.handler) { $handler = "$($opDef.handler)" }
		if ($opDef.parameters) {
			$opDef.parameters.PSObject.Properties | ForEach-Object {
				$params[$_.Name] = $_.Value
			}
		}
	}

	X "$indent<Operation uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $opName)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $opSynonym
	X "$indent`t`t<Comment/>"
	X "$indent`t`t<XDTOReturningValueType>$returnType</XDTOReturningValueType>"
	X "$indent`t`t<Nillable>$nillable</Nillable>"
	X "$indent`t`t<Transactioned>$transactioned</Transactioned>"
	X "$indent`t`t<ProcedureName>$(Esc-Xml $handler)</ProcedureName>"
	X "$indent`t</Properties>"

	if ($params.Count -gt 0) {
		X "$indent`t<ChildObjects>"
		foreach ($paramName in $params.Keys) {
			$paramUuid = New-Guid-String
			$paramDef = $params[$paramName]
			$paramSynonym = Split-CamelCase $paramName
			$paramType = "xs:string"
			$paramNillable = "true"
			$paramDir = "In"

			if ($paramDef -is [string]) {
				$paramType = "$paramDef"
			} else {
				if ($paramDef.type) { $paramType = "$($paramDef.type)" }
				if ($paramDef.nillable -eq $false) { $paramNillable = "false" }
				if ($paramDef.direction) { $paramDir = "$($paramDef.direction)" }
			}

			X "$indent`t`t<Parameter uuid=`"$paramUuid`">"
			X "$indent`t`t`t<Properties>"
			X "$indent`t`t`t`t<Name>$(Esc-Xml $paramName)</Name>"
			Emit-MLText "$indent`t`t`t`t" "Synonym" $paramSynonym
			X "$indent`t`t`t`t<XDTOValueType>$paramType</XDTOValueType>"
			X "$indent`t`t`t`t<Nillable>$paramNillable</Nillable>"
			X "$indent`t`t`t`t<TransferDirection>$paramDir</TransferDirection>"
			X "$indent`t`t`t</Properties>"
			X "$indent`t`t</Parameter>"
		}
		X "$indent`t</ChildObjects>"
	} else {
		X "$indent`t<ChildObjects/>"
	}

	X "$indent</Operation>"
}

function Emit-AddressingAttribute {
	param([string]$indent, $addrDef)
	$uuid = New-Guid-String

	$name = ""
	$attrSynonym = ""
	$typeStr = ""
	$addressingDimension = ""
	$indexing = "Index"

	$parsed = Parse-AttributeShorthand $addrDef
	$name = $parsed.name
	$attrSynonym = $parsed.synonym
	$typeStr = $parsed.type
	if ($addrDef -isnot [string]) {
		if ($addrDef.addressingDimension) { $addressingDimension = "$($addrDef.addressingDimension)" }
		if ($addrDef.indexing) { $indexing = "$($addrDef.indexing)" }
	}

	X "$indent<AddressingAttribute uuid=`"$uuid`">"
	X "$indent`t<Properties>"
	X "$indent`t`t<Name>$(Esc-Xml $name)</Name>"
	Emit-MLText "$indent`t`t" "Synonym" $attrSynonym
	X "$indent`t`t<Comment/>"

	if ($typeStr) {
		Emit-ValueType "$indent`t`t" $typeStr
	} else {
		X "$indent`t`t<Type>"
		X "$indent`t`t`t<v8:Type>xs:string</v8:Type>"
		X "$indent`t`t</Type>"
	}

	if ($addressingDimension) {
		X "$indent`t`t<AddressingDimension>$addressingDimension</AddressingDimension>"
	} else {
		X "$indent`t`t<AddressingDimension/>"
	}

	X "$indent`t`t<Indexing>$indexing</Indexing>"
	X "$indent`t`t<FullTextSearch>Use</FullTextSearch>"
	X "$indent`t`t<DataHistory>Use</DataHistory>"
	X "$indent`t</Properties>"
	X "$indent</AddressingAttribute>"
}

# --- Команды объекта ---
# Группа обязательна: без нее платформа не знает, где показывать команду. Секционные группы
# командного интерфейса параметра команды не принимают.
$commandGroupSynonyms = @{
	"панельнавигации.важное"        = "NavigationPanelImportant"
	"панельнавигации.обычное"       = "NavigationPanelOrdinary"
	"панельнавигации.смтакже"       = "NavigationPanelSeeAlso"
	"панельдействий.важное"         = "ActionsPanelImportant"
	"панельдействий.обычное"        = "ActionsPanelOrdinary"
	"панельдействий.смтакже"        = "ActionsPanelSeeAlso"
	"панельдействий.создать"        = "ActionsPanelCreate"
	"панельдействий.сервис"         = "ActionsPanelTools"
	"команднаяпанельформы.важное"   = "FormCommandBarImportant"
	"команднаяпанельформы.обычное"  = "FormCommandBarOrdinary"
	"команднаяпанельформы.смтакже"  = "FormCommandBarSeeAlso"
	"команднаяпанельформы.создать"  = "FormCommandBarCreate"
	"панельнавигацииформы.важное"   = "FormNavigationPanelImportant"
	"панельнавигацииформы.обычное"  = "FormNavigationPanelOrdinary"
	"панельнавигацииформы.перейти"  = "FormNavigationPanelGoTo"
	"панельнавигацииформы.смтакже"  = "FormNavigationPanelSeeAlso"
}

# Группа задается предопределенным именем или ссылкой на собственную группу команд.
function Resolve-CommandGroup {
	param([string]$group)
	if (-not $group) { return "" }
	$key = ($group -replace '\s', '').ToLower()
	if ($commandGroupSynonyms.ContainsKey($key)) { return $commandGroupSynonyms[$key] }
	if ($group -match '^(ГруппаКоманд|CommandGroup)\.(.+)$') { return "CommandGroup.$($Matches[2])" }
	return $group
}

$commandSectionGroups = @(
	"NavigationPanelImportant","NavigationPanelOrdinary","NavigationPanelSeeAlso"
	"ActionsPanelImportant","ActionsPanelOrdinary","ActionsPanelSeeAlso","ActionsPanelCreate"
	"CommandBar","CommandStatusBar"
)

function Emit-ObjectCommand {
	param([string]$indent, [string]$cmdName, $cmdDef)

	$uuid = New-Guid-String
	$cmdSynonym = if ($cmdDef.synonym) { $cmdDef.synonym } else { Split-CamelCase $cmdName }
	$rawGroup = if ($cmdDef.group) { "$($cmdDef.group)" } else { "" }
	$group = Resolve-CommandGroup $rawGroup
	if (-not $group) {
		[Console]::Error.WriteLine("Ошибка: команде '$cmdName' не задана группа. Укажите group, например FormCommandBarImportant")
		exit 1
	}
	$paramType = if ($cmdDef.commandParameterType) { "$($cmdDef.commandParameterType)" } else { "" }
	if ($paramType -and $commandSectionGroups -contains $group) {
		[Console]::Error.WriteLine("Ошибка: у команды '$cmdName' параметр команды недоступен для группы $group - секционные группы командного интерфейса принимают команды без параметра")
		exit 1
	}

	X "$indent<Command uuid=`"$uuid`">"
	$i = "$indent`t`t"
	X "$indent`t<Properties>"
	X "$i<Name>$(Esc-Xml $cmdName)</Name>"
	Emit-MLText $i "Synonym" $cmdSynonym
	if ($cmdDef.comment) { X "$i<Comment>$(Esc-Xml "$($cmdDef.comment)")</Comment>" } else { X "$i<Comment/>" }
	X "$i<Group>$group</Group>"
	if ($paramType) {
		X "$i<CommandParameterType>"
		Emit-TypeContent "$i`t" $paramType -CfgPrefix
		X "$i</CommandParameterType>"
	} else {
		X "$i<CommandParameterType/>"
	}
	$useMode = if ($cmdDef.parameterUseMode) { "$($cmdDef.parameterUseMode)" } else { "Single" }
	X "$i<ParameterUseMode>$useMode</ParameterUseMode>"
	$modifies = if ($cmdDef.modifiesData -eq $true) { "true" } else { "false" }
	X "$i<ModifiesData>$modifies</ModifiesData>"
	$representation = if ($cmdDef.representation) { "$($cmdDef.representation)" } else { "Auto" }
	X "$i<Representation>$representation</Representation>"
	if ($cmdDef.tooltip) { Emit-MLText $i "ToolTip" $cmdDef.tooltip } else { X "$i<ToolTip/>" }

	# Картинка задается именем или объектом с прозрачным пикселем.
	$picture = $cmdDef.picture
	if ($picture) {
		$picRef = if ($picture -is [string]) { "$picture" } else { "$($picture.src)" }
		X "$i<Picture>"
		X "$i`t<xr:Ref>$(Esc-Xml $picRef)</xr:Ref>"
		$loadTransparent = if ($cmdDef.loadTransparent -eq $false) { "false" } else { "true" }
		X "$i`t<xr:LoadTransparent>$loadTransparent</xr:LoadTransparent>"
		if ($picture -isnot [string] -and $picture.transparentPixel) {
			X "$i`t<xr:TransparentPixel x=`"$($picture.transparentPixel.x)`" y=`"$($picture.transparentPixel.y)`"/>"
		}
		X "$i</Picture>"
	} else {
		X "$i<Picture/>"
	}
	$shortcut = if ($cmdDef.shortcut) { "$($cmdDef.shortcut)" } else { "" }
	if ($shortcut) { X "$i<Shortcut>$(Esc-Xml $shortcut)</Shortcut>" } else { X "$i<Shortcut/>" }
	$unavailable = if ($cmdDef.onMainServerUnavalableBehavior) { "$($cmdDef.onMainServerUnavalableBehavior)" } else { "Auto" }
	X "$i<OnMainServerUnavalableBehavior>$unavailable</OnMainServerUnavalableBehavior>"
	X "$indent`t</Properties>"
	X "$indent</Command>"
}

# --- 13h. Wave 7: конфигурационные объекты без собственных данных ---

# Комментарий объекта: у большинства типов он пустой, но там, где задан, пишется как есть.
function Emit-Comment {
	param([string]$indent)
	if ($comment) {
		X "$indent<Comment>$(Esc-Xml $comment)</Comment>"
	} else {
		X "$indent<Comment/>"
	}
}

# Голова свойств, одинаковая у всех типов: имя, синоним, комментарий.
function Emit-CommonHead {
	param([string]$indent)
	X "$indent<Name>$(Esc-Xml $objName)</Name>"
	Emit-MLText $indent "Synonym" $synonym
	Emit-Comment $indent
}

# Список ссылок на метаданные: <xr:Item xsi:type="xr:MDObjectRef">Document.X</xr:Item>
function Emit-MDRefList {
	param([string]$indent, [string]$tag, $items)
	$refs = @(@($items) | Where-Object { $_ })
	if ($refs.Count -eq 0) {
		X "$indent<$tag/>"
		return
	}
	X "$indent<$tag>"
	foreach ($ref in $refs) {
		X "$indent`t<xr:Item xsi:type=`"xr:MDObjectRef`">$(Resolve-MDPath "$ref")</xr:Item>"
	}
	X "$indent</$tag>"
}

function Emit-SessionParameterProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	if ($def.valueType) {
		X "$i<Type>"
		Emit-TypeContent "$i`t" "$($def.valueType)" -CfgPrefix
		X "$i</Type>"
	} else {
		X "$i<Type/>"
	}
}

function Emit-SettingsStorageProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	X "$i<DefaultSaveForm/>"
	X "$i<DefaultLoadForm/>"
	X "$i<AuxiliarySaveForm/>"
	X "$i<AuxiliaryLoadForm/>"
}

function Emit-CommonPictureProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$forChoice = if ($def.availabilityForChoice -eq $true) { "true" } else { "false" }
	$forAppearance = if ($def.availabilityForAppearance -eq $true) { "true" } else { "false" }
	X "$i<AvailabilityForChoice>$forChoice</AvailabilityForChoice>"
	X "$i<AvailabilityForAppearance>$forAppearance</AvailabilityForAppearance>"
}

function Emit-CommonTemplateProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$tmplType = if ($def.templateType) { "$($def.templateType)" } else { "SpreadsheetDocument" }
	X "$i<TemplateType>$tmplType</TemplateType>"
}

function Emit-DocumentNumeratorProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$numType = Get-EnumProp "NumberType" "numberType" "String"
	$numLen  = if ($null -ne $def.numberLength) { "$($def.numberLength)" } else { "9" }
	$numAllowed = Get-EnumProp "NumberAllowedLength" "numberAllowedLength" "Variable"
	$numPeriod  = if ($def.numberPeriodicity) { "$($def.numberPeriodicity)" } else { "Year" }
	$checkUnique = if ($def.checkUnique -eq $false) { "false" } else { "true" }
	X "$i<NumberType>$numType</NumberType>"
	X "$i<NumberLength>$numLen</NumberLength>"
	X "$i<NumberAllowedLength>$numAllowed</NumberAllowedLength>"
	X "$i<NumberPeriodicity>$numPeriod</NumberPeriodicity>"
	X "$i<CheckUnique>$checkUnique</CheckUnique>"
}

function Emit-WSReferenceProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$url = if ($def.locationURL) { "$($def.locationURL)" } else { "" }
	if ($url) { X "$i<LocationURL>$(Esc-Xml $url)</LocationURL>" } else { X "$i<LocationURL/>" }
}

function Emit-FunctionalOptionProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	if ($def.location) {
		X "$i<Location>$(Resolve-MDPath "$($def.location)")</Location>"
	} else {
		X "$i<Location/>"
	}
	$privileged = if ($def.privilegedGetMode -eq $false) { "false" } else { "true" }
	X "$i<PrivilegedGetMode>$privileged</PrivilegedGetMode>"
	# Состав функциональной опции - это xr:Object, а не xr:Item, как у остальных списков
	$content = @(@($def.content) | Where-Object { $_ })
	if ($content.Count -gt 0) {
		X "$i<Content>"
		foreach ($c in $content) {
			X "$i`t<xr:Object>$(Resolve-MDPath "$c")</xr:Object>"
		}
		X "$i</Content>"
	} else {
		X "$i<Content/>"
	}
}

function Emit-FunctionalOptionsParameterProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	Emit-MDRefList $i "Use" $def.use
}

function Emit-FilterCriterionProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	if ($def.valueType) {
		X "$i<Type>"
		Emit-TypeContent "$i`t" "$($def.valueType)" -CfgPrefix
		X "$i</Type>"
	} else {
		X "$i<Type/>"
	}
	$useStdCmd = if ($def.useStandardCommands -eq $false) { "false" } else { "true" }
	X "$i<UseStandardCommands>$useStdCmd</UseStandardCommands>"
	Emit-MDRefList $i "Content" $def.content
	X "$i<DefaultForm/>"
	X "$i<AuxiliaryForm/>"
	X "$i<ListPresentation/>"
	X "$i<ExtendedListPresentation/>"
	X "$i<Explanation/>"
}

function Emit-SequenceProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$moveBoundary = if ($def.moveBoundaryOnPosting) { "$($def.moveBoundaryOnPosting)" } else { "DontMove" }
	X "$i<MoveBoundaryOnPosting>$moveBoundary</MoveBoundaryOnPosting>"
	Emit-MDRefList $i "Documents" $def.documents
	Emit-MDRefList $i "RegisterRecords" $def.registerRecords
	$lockMode = Get-EnumProp "DataLockControlMode" "dataLockControlMode" "Managed"
	X "$i<DataLockControlMode>$lockMode</DataLockControlMode>"
}

# Измерение последовательности: тип плюс карты соответствия документам и движениям.
function Emit-SequenceDimension {
	param([string]$indent, $dim)
	$i = $indent
	$dimName = "$($dim.name)"
	$dimSynonym = if ($dim.synonym) { "$($dim.synonym)" } else { Split-CamelCase $dimName }
	X "$i<Dimension uuid=`"$(New-Guid-String)`">"
	X "$i`t<Properties>"
	X "$i`t`t<Name>$(Esc-Xml $dimName)</Name>"
	Emit-MLText "$i`t`t" "Synonym" $dimSynonym
	X "$i`t`t<Comment/>"
	if ($dim.type) {
		X "$i`t`t<Type>"
		Emit-TypeContent "$i`t`t`t" "$($dim.type)" -CfgPrefix
		X "$i`t`t</Type>"
	} else {
		X "$i`t`t<Type/>"
	}
	Emit-MDRefList "$i`t`t" "DocumentMap" $dim.documentMap
	Emit-MDRefList "$i`t`t" "RegisterRecordsMap" $dim.registerRecordsMap
	X "$i`t</Properties>"
	X "$i</Dimension>"
}

function Emit-CommonAttributeProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	if ($def.valueType) {
		X "$i<Type>"
		Emit-TypeContent "$i`t" "$($def.valueType)" -CfgPrefix
		X "$i</Type>"
	} else {
		X "$i<Type/>"
	}
	X "$i<PasswordMode>false</PasswordMode>"
	X "$i<Format/>"
	X "$i<EditFormat/>"
	X "$i<ToolTip/>"
	X "$i<MarkNegatives>false</MarkNegatives>"
	X "$i<Mask/>"
	X "$i<MultiLine>false</MultiLine>"
	X "$i<ExtendedEdit>false</ExtendedEdit>"
	X "$i<MinValue xsi:nil=`"true`"/>"
	X "$i<MaxValue xsi:nil=`"true`"/>"
	X "$i<FillFromFillingValue>false</FillFromFillingValue>"
	X "$i<FillValue xsi:nil=`"true`"/>"
	X "$i<FillChecking>DontCheck</FillChecking>"
	X "$i<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
	X "$i<ChoiceParameterLinks/>"
	X "$i<ChoiceParameters/>"
	X "$i<QuickChoice>Auto</QuickChoice>"
	X "$i<CreateOnInput>Auto</CreateOnInput>"
	X "$i<ChoiceForm/>"
	X "$i<LinkByType/>"
	X "$i<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>"

	# Состав: строка "Документ.X" либо объект { metadata, use }
	$content = @(@($def.content) | Where-Object { $_ })
	if ($content.Count -gt 0) {
		X "$i<Content>"
		foreach ($c in $content) {
			$mdRef = if ($c -is [string]) { "$c" } else { "$($c.metadata)" }
			$mdUse = if ($c -isnot [string] -and $c.use) { "$($c.use)" } else { "Use" }
			X "$i`t<xr:Item>"
			X "$i`t`t<xr:Metadata>$(Resolve-MDPath $mdRef)</xr:Metadata>"
			X "$i`t`t<xr:Use>$mdUse</xr:Use>"
			X "$i`t`t<xr:ConditionalSeparation/>"
			X "$i`t</xr:Item>"
		}
		X "$i</Content>"
	} else {
		X "$i<Content/>"
	}

	$autoUse = if ($def.autoUse) { "$($def.autoUse)" } else { "DontUse" }
	X "$i<AutoUse>$autoUse</AutoUse>"
	X "$i<DataSeparation>DontUse</DataSeparation>"
	X "$i<SeparatedDataUse>Independently</SeparatedDataUse>"
	X "$i<DataSeparationValue/>"
	X "$i<DataSeparationUse/>"
	X "$i<ConditionalSeparation/>"
	X "$i<UsersSeparation>DontUse</UsersSeparation>"
	X "$i<AuthenticationSeparation>DontUse</AuthenticationSeparation>"
	X "$i<ConfigurationExtensionsSeparation>DontUse</ConfigurationExtensionsSeparation>"
	$indexing = Get-EnumProp "Indexing" "indexing" "DontIndex"
	X "$i<Indexing>$indexing</Indexing>"
	$fts = Get-EnumProp "FullTextSearch" "fullTextSearch" "Use"
	X "$i<FullTextSearch>$fts</FullTextSearch>"
	$dataHistory = if ($def.dataHistory) { "$($def.dataHistory)" } else { "Use" }
	X "$i<DataHistory>$dataHistory</DataHistory>"
}

# Картинка команды или группы: либо ссылка на общую картинку, либо пустой тег.
function Emit-PictureRef {
	param([string]$indent, $picture)
	if (-not $picture) {
		X "$indent<Picture/>"
		return
	}
	$src = if ($picture -is [string]) { "$picture" } else { "$($picture.src)" }
	if (-not $src) {
		X "$indent<Picture/>"
		return
	}
	$transparent = if ($picture -isnot [string] -and $picture.loadTransparent -eq $true) { "true" } else { "false" }
	X "$indent<Picture>"
	X "$indent`t<xr:Ref>$(Resolve-MDPath $src)</xr:Ref>"
	X "$indent`t<xr:LoadTransparent>$transparent</xr:LoadTransparent>"
	X "$indent</Picture>"
}

function Emit-CommandGroupProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$repr = if ($def.representation) { "$($def.representation)" } else { "Auto" }
	X "$i<Representation>$repr</Representation>"
	X "$i<ToolTip/>"
	Emit-PictureRef $i $def.picture
	$category = if ($def.category) { "$($def.category)" } else { "NavigationPanel" }
	X "$i<Category>$category</Category>"
}

function Emit-CommonCommandProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	if ($def.group) { X "$i<Group>$($def.group)</Group>" } else { X "$i<Group/>" }
	$repr = if ($def.representation) { "$($def.representation)" } else { "Auto" }
	X "$i<Representation>$repr</Representation>"
	X "$i<ToolTip/>"
	Emit-PictureRef $i $def.picture
	X "$i<Shortcut/>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	if ($def.commandParameterType) {
		X "$i<CommandParameterType>"
		Emit-TypeContent "$i`t" "$($def.commandParameterType)" -CfgPrefix
		X "$i</CommandParameterType>"
	} else {
		X "$i<CommandParameterType/>"
	}
	$paramMode = if ($def.parameterUseMode) { "$($def.parameterUseMode)" } else { "Single" }
	X "$i<ParameterUseMode>$paramMode</ParameterUseMode>"
	$modifies = if ($def.modifiesData -eq $true) { "true" } else { "false" }
	X "$i<ModifiesData>$modifies</ModifiesData>"
	X "$i<OnMainServerUnavalableBehavior>Auto</OnMainServerUnavalableBehavior>"
}

function Emit-CommonFormProperties {
	param([string]$indent)
	$i = $indent
	Emit-CommonHead $i
	$formType = if ($def.formType) { "$($def.formType)" } else { "Managed" }
	X "$i<FormType>$formType</FormType>"
	X "$i<IncludeHelpInContents>false</IncludeHelpInContents>"
	$purposes = @(@($def.usePurposes) | Where-Object { $_ })
	if ($purposes.Count -eq 0) { $purposes = @("PlatformApplication") }
	X "$i<UsePurposes>"
	foreach ($p in $purposes) {
		X "$i`t<v8:Value xsi:type=`"app:ApplicationUsePurpose`">$p</v8:Value>"
	}
	X "$i</UsePurposes>"
	$useStdCmd = if ($def.useStandardCommands -eq $true) { "true" } else { "false" }
	X "$i<UseStandardCommands>$useStdCmd</UseStandardCommands>"
	X "$i<ExtendedPresentation/>"
	X "$i<Explanation/>"
}

# --- 14. Namespaces ---

$script:xmlnsDecl = 'xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'

# Палитра появляется в шапке с формата 2.21 (8.5) и встает между lf и style.
function Get-XmlnsDecl {
	if ((Get-FormatVersionRank $script:formatVersion) -ge 221) {
		return $script:xmlnsDecl.Replace('xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style=', 'xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette" xmlns:style=')
	}
	return $script:xmlnsDecl
}

# --- 14a. Detect format version from existing Configuration.xml ---

function Detect-FormatVersion([string]$dir) {
	$d = $dir
	while ($d) {
		$cfgPath = Join-Path $d "Configuration.xml"
		if (Test-Path $cfgPath) {
			$head = [System.IO.File]::ReadAllText($cfgPath, [System.Text.Encoding]::UTF8).Substring(0, [Math]::Min(2000, (Get-Item $cfgPath).Length))
			if ($head -match '<MetaDataObject[^>]+version="(\d+\.\d+)"') { return $Matches[1] }
		}
		$parent = Split-Path $d -Parent
		if ($parent -eq $d) { break }
		$d = $parent
	}
	return "2.17"
}

# Гард до определения версии и любой записи: объект добавляется в конфигурацию.
Assert-EditAllowed $OutputDir "editable"
function Detect-CompatibilityMode([string]$dir) {
	$d = $dir
	while ($d) {
		$cfgPath = Join-Path $d "Configuration.xml"
		if (Test-Path $cfgPath) {
			$cfgText = [System.IO.File]::ReadAllText($cfgPath, [System.Text.Encoding]::UTF8)
			if ($cfgText -match '<CompatibilityMode>([^<]+)</CompatibilityMode>') { return $Matches[1] }
		}
		$parent = Split-Path $d -Parent
		if ($parent -eq $d) { break }
		$d = $parent
	}
	return "Version8_3_24"
}

$script:formatVersion = Detect-FormatVersion $OutputDir
$script:compatibilityMode = Detect-CompatibilityMode $OutputDir

# --- 15. Main assembler ---

$uuid = New-Guid-String

# XML declaration
X '<?xml version="1.0" encoding="UTF-8"?>'
X "<MetaDataObject $(Get-XmlnsDecl) version=`"$($script:formatVersion)`">"
X "`t<$objType uuid=`"$uuid`">"

# InternalInfo
Emit-InternalInfo "`t`t" $objType $objName

# Properties
X "`t`t<Properties>"

switch ($objType) {
	"Catalog"                    { Emit-CatalogProperties "`t`t`t" }
	"Document"                   { Emit-DocumentProperties "`t`t`t" }
	"Enum"                       { Emit-EnumProperties "`t`t`t" }
	"Constant"                   { Emit-ConstantProperties "`t`t`t" }
	"InformationRegister"        { Emit-InformationRegisterProperties "`t`t`t" }
	"AccumulationRegister"       { Emit-AccumulationRegisterProperties "`t`t`t" }
	"DefinedType"                { Emit-DefinedTypeProperties "`t`t`t" }
	"CommonModule"               { Emit-CommonModuleProperties "`t`t`t" }
	"ScheduledJob"               { Emit-ScheduledJobProperties "`t`t`t" }
	"EventSubscription"          { Emit-EventSubscriptionProperties "`t`t`t" }
	"Report"                     { Emit-ReportProperties "`t`t`t" }
	"DataProcessor"              { Emit-DataProcessorProperties "`t`t`t" }
	"ExchangePlan"               { Emit-ExchangePlanProperties "`t`t`t" }
	"ChartOfCharacteristicTypes" { Emit-ChartOfCharacteristicTypesProperties "`t`t`t" }
	"DocumentJournal"            { Emit-DocumentJournalProperties "`t`t`t" }
	"ChartOfAccounts"            { Emit-ChartOfAccountsProperties "`t`t`t" }
	"AccountingRegister"         { Emit-AccountingRegisterProperties "`t`t`t" }
	"ChartOfCalculationTypes"    { Emit-ChartOfCalculationTypesProperties "`t`t`t" }
	"CalculationRegister"        { Emit-CalculationRegisterProperties "`t`t`t" }
	"BusinessProcess"            { Emit-BusinessProcessProperties "`t`t`t" }
	"Task"                       { Emit-TaskProperties "`t`t`t" }
	"HTTPService"                { Emit-HTTPServiceProperties "`t`t`t" }
	"WebService"                 { Emit-WebServiceProperties "`t`t`t" }
	"SessionParameter"           { Emit-SessionParameterProperties "`t`t`t" }
	"SettingsStorage"            { Emit-SettingsStorageProperties "`t`t`t" }
	"CommonPicture"              { Emit-CommonPictureProperties "`t`t`t" }
	"CommonTemplate"             { Emit-CommonTemplateProperties "`t`t`t" }
	"DocumentNumerator"          { Emit-DocumentNumeratorProperties "`t`t`t" }
	"WSReference"                { Emit-WSReferenceProperties "`t`t`t" }
	"FunctionalOption"           { Emit-FunctionalOptionProperties "`t`t`t" }
	"FunctionalOptionsParameter" { Emit-FunctionalOptionsParameterProperties "`t`t`t" }
	"FilterCriterion"            { Emit-FilterCriterionProperties "`t`t`t" }
	"Sequence"                   { Emit-SequenceProperties "`t`t`t" }
	"CommonAttribute"            { Emit-CommonAttributeProperties "`t`t`t" }
	"CommandGroup"               { Emit-CommandGroupProperties "`t`t`t" }
	"CommonCommand"              { Emit-CommonCommandProperties "`t`t`t" }
	"CommonForm"                 { Emit-CommonFormProperties "`t`t`t" }
}

X "`t`t</Properties>"

# ChildObjects
$hasChildren = $false

# --- Types with Attributes + TabularSections ---
	$objCommands = [ordered]@{}
	if ($def.commands) {
		foreach ($prop in $def.commands.PSObject.Properties) { $objCommands[$prop.Name] = $prop.Value }
	}

$typesWithAttrTS = @("Catalog","Document","Report","DataProcessor","ExchangePlan",
	"ChartOfCharacteristicTypes","ChartOfAccounts","ChartOfCalculationTypes",
	"BusinessProcess","Task")

if ($objType -in $typesWithAttrTS) {
	$attrs = @()
	if ($def.attributes) {
		foreach ($a in $def.attributes) {
			$attrs += Parse-AttributeShorthand $a
		}
	}
	$tsSections = [ordered]@{}
	$tsOptions = @{}
	if ($def.tabularSections) {
		# Normalize array format: [{name:"X", attributes:[...]}, ...] → {"X": [...]}
		if ($def.tabularSections -is [array] -or $def.tabularSections.GetType().Name -eq "Object[]") {
			foreach ($ts in $def.tabularSections) {
				$tsName = $ts.name
				$tsCols = if ($ts.attributes) { @($ts.attributes) } else { @() }
				$tsSections[$tsName] = $tsCols
			}
		} else {
			$def.tabularSections.PSObject.Properties | ForEach-Object {
				# Значение бывает списком колонок и объектом { synonym, attributes, ... }.
				# Объект раньше уходил в разбор колонки целиком: выходил один безымянный
				# реквизит, а объявленные колонки терялись молча.
				$tsVal = $_.Value
				if ($tsVal -is [array] -or $tsVal -is [string]) {
					$tsSections[$_.Name] = @($tsVal)
				} else {
					$tsSections[$_.Name] = @(@($tsVal.attributes) | Where-Object { $_ })
					$tsOptions[$_.Name] = $tsVal
					foreach ($tsKey in $tsVal.PSObject.Properties.Name) {
						if ($tsKey -notin @("attributes", "synonym", "comment")) {
							[Console]::Error.WriteLine("Warning: tabular section '$($_.Name)': property '$tsKey' is not supported and was ignored.")
						}
					}
				}
			}
		}
	}

	# ChartOfAccounts: AccountingFlags + ExtDimensionAccountingFlags
	$acctFlags = @()
	$extDimFlags = @()
	if ($objType -eq "ChartOfAccounts") {
		if ($def.accountingFlags) { $acctFlags = @($def.accountingFlags) }
		if ($def.extDimensionAccountingFlags) { $extDimFlags = @($def.extDimensionAccountingFlags) }
	}

	# Task: AddressingAttributes
	$addrAttrs = @()
	if ($objType -eq "Task" -and $def.addressingAttributes) {
		$addrAttrs = @($def.addressingAttributes)
	}


	$childCount = $attrs.Count + $tsSections.Count + $acctFlags.Count + $extDimFlags.Count + $addrAttrs.Count + $objCommands.Count
	if ($childCount -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		$context = switch ($objType) {
			"Catalog"  { "catalog" }
			"Document" { "document" }
			{ $_ -in @("DataProcessor","Report") } { "processor" }
			{ $_ -in @("ChartOfAccounts","ChartOfCharacteristicTypes","ChartOfCalculationTypes") } { "chart" }
			default    { "object" }
		}
		foreach ($a in $attrs) {
			Emit-Attribute "`t`t`t" $a $context
		}
		foreach ($tsName in $tsSections.Keys) {
			$columns = $tsSections[$tsName]
			Emit-TabularSection "`t`t`t" $tsName $columns $objType $objName $tsOptions[$tsName]
		}
		foreach ($af in $acctFlags) {
			Emit-AccountingFlag "`t`t`t" $af
		}
		foreach ($edf in $extDimFlags) {
			Emit-ExtDimensionAccountingFlag "`t`t`t" $edf
		}
		foreach ($cmdName in $objCommands.Keys) {
			Emit-ObjectCommand "`t`t`t" $cmdName $objCommands[$cmdName]
		}
		foreach ($aa in $addrAttrs) {
			Emit-AddressingAttribute "`t`t`t" $aa
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- Enum: enum values ---
if ($objType -eq "Enum") {
	$values = @()
	if ($def.values) {
		foreach ($v in $def.values) {
			$values += Parse-EnumValueShorthand $v
		}
	}
	if ($values.Count -gt 0 -or $objCommands.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($v in $values) {
			Emit-EnumValue "`t`t`t" $v
		}
		foreach ($cmdName in $objCommands.Keys) {
			Emit-ObjectCommand "`t`t`t" $cmdName $objCommands[$cmdName]
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- Constant, DefinedType, ScheduledJob, EventSubscription: no ChildObjects ---

# --- Registers: dimensions + resources + attributes ---
if ($objType -in @("InformationRegister","AccumulationRegister","AccountingRegister","CalculationRegister")) {
	$dims = @()
	$resources = @()
	$regAttrs = @()
	if ($def.dimensions) {
		foreach ($d in $def.dimensions) {
			$dims += Parse-AttributeShorthand $d
		}
	}
	if ($def.resources) {
		foreach ($r in $def.resources) {
			$resources += Parse-AttributeShorthand $r
		}
	}
	if ($def.attributes) {
		foreach ($a in $def.attributes) {
			$regAttrs += Parse-AttributeShorthand $a
		}
	}

	if ($dims.Count -gt 0 -or $resources.Count -gt 0 -or $regAttrs.Count -gt 0 -or $objCommands.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($r in $resources) {
			Emit-Resource "`t`t`t" $r $objType
		}
		foreach ($d in $dims) {
			Emit-Dimension "`t`t`t" $d $objType
		}
		# InformationRegister.Attribute supports FillFromFillingValue/FillValue/DataHistory;
		# AccumulationRegister/AccountingRegister/CalculationRegister.Attribute do NOT.
		$regCtx = if ($objType -eq "InformationRegister") { "register-info" } else { "register-other" }
		foreach ($a in $regAttrs) {
			Emit-Attribute "`t`t`t" $a $regCtx
		}
		foreach ($cmdName in $objCommands.Keys) {
			Emit-ObjectCommand "`t`t`t" $cmdName $objCommands[$cmdName]
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- DocumentJournal: columns ---
if ($objType -eq "DocumentJournal") {
	$columns = @()
	if ($def.columns) { $columns = @($def.columns) }
	if ($columns.Count -gt 0 -or $objCommands.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($col in $columns) {
			Emit-Column "`t`t`t" $col
		}
		foreach ($cmdName in $objCommands.Keys) {
			Emit-ObjectCommand "`t`t`t" $cmdName $objCommands[$cmdName]
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- HTTPService: URLTemplates ---
if ($objType -eq "HTTPService") {
	# Порядок объявления значим (для операции это ее сигнатура), поэтому упорядоченный словарь:
	# обычная хеш-таблица PowerShell отдает ключи в произвольном порядке.
	$urlTemplates = [ordered]@{}
	if ($def.urlTemplates) {
		$def.urlTemplates.PSObject.Properties | ForEach-Object {
			$urlTemplates[$_.Name] = $_.Value
		}
	}
	if ($urlTemplates.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($tmplName in $urlTemplates.Keys) {
			Emit-URLTemplate "`t`t`t" $tmplName $urlTemplates[$tmplName]
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- WebService: Operations ---
if ($objType -eq "WebService") {
	# Порядок объявления значим (для операции это ее сигнатура), поэтому упорядоченный словарь:
	# обычная хеш-таблица PowerShell отдает ключи в произвольном порядке.
	$operations = [ordered]@{}
	if ($def.operations) {
		$def.operations.PSObject.Properties | ForEach-Object {
			$operations[$_.Name] = $_.Value
		}
	}
	if ($operations.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($opName in $operations.Keys) {
			Emit-Operation "`t`t`t" $opName $operations[$opName]
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- Sequence: dimensions ---
if ($objType -eq "Sequence") {
	$seqDims = @(@($def.dimensions) | Where-Object { $_ })
	if ($seqDims.Count -gt 0) {
		$hasChildren = $true
		X "`t`t<ChildObjects>"
		foreach ($sd in $seqDims) {
			Emit-SequenceDimension "`t`t`t" $sd
		}
		X "`t`t</ChildObjects>"
	} else {
		X "`t`t<ChildObjects/>"
	}
}

# --- SettingsStorage, FilterCriterion: контейнер форм, пока пустой ---
if ($objType -in @("SettingsStorage","FilterCriterion")) {
	X "`t`t<ChildObjects/>"
}

# --- CommonModule: no ChildObjects ---

X "`t</$objType>"
X "</MetaDataObject>"

# Платформа не оставляет перевод строки после закрывающего тега - лишний перевод
# дает расхождение в первой же сверке с выгрузкой Конфигуратора.
$metadataXml = $script:xml.ToString().TrimEnd("`r", "`n")

# --- 16. Write files ---

# Type → plural directory mapping
$script:typePluralMap = @{
	"Catalog"                   = "Catalogs"
	"Document"                  = "Documents"
	"Enum"                      = "Enums"
	"Constant"                  = "Constants"
	"InformationRegister"       = "InformationRegisters"
	"AccumulationRegister"      = "AccumulationRegisters"
	"AccountingRegister"        = "AccountingRegisters"
	"CalculationRegister"       = "CalculationRegisters"
	"ChartOfAccounts"           = "ChartsOfAccounts"
	"ChartOfCharacteristicTypes"= "ChartsOfCharacteristicTypes"
	"ChartOfCalculationTypes"   = "ChartsOfCalculationTypes"
	"BusinessProcess"           = "BusinessProcesses"
	"Task"                      = "Tasks"
	"ExchangePlan"              = "ExchangePlans"
	"DocumentJournal"           = "DocumentJournals"
	"Report"                    = "Reports"
	"DataProcessor"             = "DataProcessors"
	"CommonModule"              = "CommonModules"
	"ScheduledJob"              = "ScheduledJobs"
	"EventSubscription"         = "EventSubscriptions"
	"HTTPService"               = "HTTPServices"
	"WebService"                = "WebServices"
	"DefinedType"               = "DefinedTypes"
	"CommonAttribute"           = "CommonAttributes"
	"CommonCommand"             = "CommonCommands"
	"CommandGroup"              = "CommandGroups"
	"CommonForm"                = "CommonForms"
	"CommonTemplate"            = "CommonTemplates"
	"CommonPicture"             = "CommonPictures"
	"FilterCriterion"           = "FilterCriteria"
	"Sequence"                  = "Sequences"
	"DocumentNumerator"         = "DocumentNumerators"
	"SessionParameter"          = "SessionParameters"
	"SettingsStorage"           = "SettingsStorages"
	"FunctionalOption"          = "FunctionalOptions"
	"FunctionalOptionsParameter"= "FunctionalOptionsParameters"
	"WSReference"               = "WSReferences"
}

$typePlural = $script:typePluralMap[$objType]
$typeDir = Join-Path $OutputDir $typePlural

# Main XML file: {OutputDir}/{TypePlural}/{Name}.xml
$mainXmlPath = Join-Path $typeDir "$objName.xml"

# Types that don't have subdirectory structure (no Ext/, no modules)
$typesNoSubDir = @("DefinedType","ScheduledJob","EventSubscription",
	"CommonAttribute","CommandGroup","CommonTemplate","CommonPicture",
	"FilterCriterion","Sequence","DocumentNumerator","SessionParameter",
	"SettingsStorage","FunctionalOption","FunctionalOptionsParameter","WSReference")

# Object subdirectory: {OutputDir}/{TypePlural}/{Name}/Ext/
$objSubDir = Join-Path $typeDir $objName
$extDir = Join-Path $objSubDir "Ext"

if (-not (Test-Path $typeDir)) {
	New-Item -ItemType Directory -Path $typeDir -Force | Out-Null
}
if ($objType -notin $typesNoSubDir) {
	if (-not (Test-Path $objSubDir)) {
		New-Item -ItemType Directory -Path $objSubDir -Force | Out-Null
	}
}

$enc = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($mainXmlPath, $metadataXml, $enc)

# --- Предопределенные элементы ---
# Платформа хранит их отдельным файлом Ext/Predefined.xml, а не внутри описания объекта.
# Состав полей зависит от вида объекта: у плана счетов это признаки учета и субконто,
# у плана видов расчета - признак базового периода действия.

$predefinedRootType = @{
	"Catalog"                    = "CatalogPredefinedItems"
	"ChartOfAccounts"            = "ChartOfAccountsPredefinedItems"
	"ChartOfCharacteristicTypes" = "PlanOfCharacteristicKindPredefinedItems"
	"ChartOfCalculationTypes"    = "CalculationTypePredefinedItems"
}

function Parse-PredefinedItem {
	param($raw)

	if ($raw -isnot [string]) {
		$item = @{}
		foreach ($prop in $raw.PSObject.Properties) { $item[$prop.Name] = $prop.Value }
		if (-not $item.ContainsKey("description")) { $item["description"] = Split-CamelCase "$($item['name'])" }
		return $item
	}

	# Краткая запись: "(код) Имя [описание]: Тип" - все, кроме имени, необязательно.
	$pattern = '^\s*(?:\((?<code>[^)]*)\)\s*)?(?<name>[^\[\]:]+?)\s*(?:\[(?<desc>[^\]]*)\])?\s*(?::\s*(?<type>.+))?\s*$'
	$m = [regex]::Match("$raw", $pattern)
	if (-not $m.Success) { return @{ name = "$raw"; description = Split-CamelCase "$raw" } }

	$item = @{ name = $m.Groups["name"].Value.Trim() }
	if ($m.Groups["code"].Success) { $item["code"] = $m.Groups["code"].Value }
	if ($m.Groups["desc"].Success) {
		$item["description"] = $m.Groups["desc"].Value
	} else {
		$item["description"] = Split-CamelCase $item["name"]
	}
	if ($m.Groups["type"].Success) { $item["type"] = $m.Groups["type"].Value.Trim() }
	return $item
}

function Emit-PredefinedCode {
	param($item, [string]$indent)

	$code = if ($item.ContainsKey("code")) { "$($item['code'])" } else { "" }
	if (-not $code) {
		X "$indent<Code/>"
		return
	}
	# Числовой код платформа помечает типом; строковый пишется как есть.
	if ($script:predefinedCodeIsNumber) {
		X "$indent<Code xsi:type=`"xs:decimal`">$code</Code>"
	} else {
		X "$indent<Code>$(Esc-Xml $code)</Code>"
	}
}

function Emit-PredefinedFlags {
	param($item, [string]$indent, [string]$flagKind, $declared, [string]$key)

	if (-not $declared -or $declared.Count -eq 0) { return }
	$enabled = @()
	if ($item.ContainsKey($key) -and $item[$key]) { $enabled = @($item[$key] | ForEach-Object { "$_" }) }
	X "$indent<AccountingFlags>"
	foreach ($flag in $declared) {
		$value = if ($enabled -contains $flag) { "true" } else { "false" }
		X "$indent`t<Flag ref=`"ChartOfAccounts.$objName.$flagKind.$flag`">$value</Flag>"
	}
	X "$indent</AccountingFlags>"
}

function Emit-PredefinedItem {
	param($item, [string]$indent)

	$script:predefinedIndex++
	$uuid = New-Guid-String
	X "$indent<Item id=`"$uuid`">"
	$i = "$indent`t"
	X "$i<Name>$(Esc-Xml "$($item['name'])")</Name>"
	Emit-PredefinedCode $item $i
	$desc = if ($item.ContainsKey("description")) { "$($item['description'])" } else { "" }
	if ($desc) { X "$i<Description>$(Esc-Xml $desc)</Description>" } else { X "$i<Description/>" }

	if ($objType -eq "ChartOfCharacteristicTypes") {
		$typeStr = if ($item.ContainsKey("type")) { "$($item['type'])" } else { "" }
		if ($typeStr) {
			X "$i<Type>"
			Emit-TypeContent "$i`t" $typeStr
			X "$i</Type>"
		}
	}

	if ($objType -eq "ChartOfAccounts") {
		$accountType = if ($item.ContainsKey("accountType")) { "$($item['accountType'])" } else { "ActivePassive" }
		X "$i<AccountType>$accountType</AccountType>"
		$offBalance = if ($item.ContainsKey("offBalance") -and $item["offBalance"] -eq $true) { "true" } else { "false" }
		X "$i<OffBalance>$offBalance</OffBalance>"
		if ($item.ContainsKey("order")) { X "$i<Order>$(Esc-Xml "$($item['order'])")</Order>" }
		Emit-PredefinedFlags $item $i "AccountingFlag" $script:declaredAccountingFlags "flags"
		Emit-PredefinedSubconto $item $i
	}

	if ($objType -eq "ChartOfCalculationTypes") {
		$actionBase = if ($item.ContainsKey("actionPeriodIsBase") -and $item["actionPeriodIsBase"] -eq $true) { "true" } else { "false" }
		X "$i<ActionPeriodIsBase>$actionBase</ActionPeriodIsBase>"
	}

	# Признак группы есть у справочника и плана видов характеристик; у плана счетов
	# иерархия задается кодом, и платформа этот признак не выгружает.
	$hasFolderFlag = @("Catalog","ChartOfCharacteristicTypes") -contains $objType
	$isFolder = if ($item.ContainsKey("isFolder") -and $item["isFolder"] -eq $true) { "true" } else { "false" }
	# У справочника и плана видов характеристик признак группы идет до вложенных элементов,
	# у плана счетов - после: так их выгружает платформа.
	$children = @()
	if ($item.ContainsKey("childItems") -and $item["childItems"]) { $children = @($item["childItems"]) }
	if ($hasFolderFlag) { X "$i<IsFolder>$isFolder</IsFolder>" }
	if ($children.Count -gt 0) {
		X "$i<ChildItems>"
		foreach ($child in $children) {
			Emit-PredefinedItem (Parse-PredefinedItem $child) "$i`t"
		}
		X "$i</ChildItems>"
	}


	X "$indent</Item>"
}

function Emit-PredefinedSubconto {
	param($item, [string]$indent)

	$subconto = @()
	if ($item.ContainsKey("subconto") -and $item["subconto"]) { $subconto = @($item["subconto"]) }
	if ($subconto.Count -eq 0) {
		X "$indent<ExtDimensionTypes/>"
		return
	}
	X "$indent<ExtDimensionTypes>"
	foreach ($entry in $subconto) {
		# Запись субконто: "ВидСубконто | Turnover, Признак1, Признак2".
		$parts = "$entry" -split '\|'
		$dimName = $parts[0].Trim()
		$attrs = @()
		if ($parts.Count -gt 1) { $attrs = @($parts[1] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
		$turnover = if ($attrs -contains "Turnover" -or $attrs -contains "Оборотный") { "true" } else { "false" }
		$flags = @($attrs | Where-Object { $_ -ne "Turnover" -and $_ -ne "Оборотный" })
		X "$indent`t<ExtDimensionType name=`"$script:extDimensionOwner.$dimName`">"
		X "$indent`t`t<Turnover>$turnover</Turnover>"
		Emit-PredefinedFlags @{ flags = $flags } "$indent`t`t" "ExtDimensionAccountingFlag" $script:declaredExtDimensionFlags "flags"
		X "$indent`t</ExtDimensionType>"
	}
	X "$indent</ExtDimensionTypes>"
}

# Module files
$modulesCreated = @()

# Helper: create Ext/ only when needed (avoids empty Ext/ for Constant, Enum, etc.)
function Ensure-ExtDir {
	if (-not (Test-Path $extDir)) {
		New-Item -ItemType Directory -Path $extDir -Force | Out-Null
	}
}

# Types with ObjectModule.bsl
$typesWithObjectModule = @("Catalog","Document","Report","DataProcessor","ExchangePlan",
	"ChartOfAccounts","ChartOfCharacteristicTypes","ChartOfCalculationTypes",
	"BusinessProcess","Task")
# Types with RecordSetModule.bsl
$typesWithRecordSetModule = @("InformationRegister","AccumulationRegister","AccountingRegister","CalculationRegister")
# Types with ManagerModule.bsl
$typesWithManagerModule = @("Report","DataProcessor","Constant","Enum")
# Types with ValueManagerModule.bsl
$typesWithValueManagerModule = @("Constant")
# Types with Module.bsl (general)
$typesWithModule = @("CommonModule","HTTPService","WebService")

# Предопределенные элементы платформа держит отдельным файлом.
if ($def.predefined -and $def.predefined -isnot [bool] -and $predefinedRootType.ContainsKey($objType)) {
	$predefinedItems = @($def.predefined)
	if ($predefinedItems.Count -gt 0) {
		$script:predefinedIndex = 0
		$script:predefinedCodeIsNumber = ((Get-EnumProp "CodeType" "codeType" "String") -eq "Number")
		$script:declaredAccountingFlags = @()
		$script:declaredExtDimensionFlags = @()
		$script:extDimensionOwner = ""
		if ($objType -eq "ChartOfAccounts") {
			foreach ($flag in @($def.accountingFlags)) {
				$script:declaredAccountingFlags += if ($flag -is [string]) { "$flag" } else { "$($flag.name)" }
			}
			foreach ($flag in @($def.extDimensionAccountingFlags)) {
				$script:declaredExtDimensionFlags += if ($flag -is [string]) { "$flag" } else { "$($flag.name)" }
			}
			$script:extDimensionOwner = "$($def.extDimensionTypes)"
		}

		$script:xml = New-Object System.Text.StringBuilder 8192
		X '<?xml version="1.0" encoding="UTF-8"?>'
		X "<PredefinedData xmlns=`"http://v8.1c.ru/8.3/xcf/predef`" xmlns:v8=`"http://v8.1c.ru/8.1/data/core`" xmlns:xr=`"http://v8.1c.ru/8.3/xcf/readable`" xmlns:xs=`"http://www.w3.org/2001/XMLSchema`" xmlns:xsi=`"http://www.w3.org/2001/XMLSchema-instance`" xsi:type=`"$($predefinedRootType[$objType])`" version=`"$($script:formatVersion)`">"
		foreach ($raw in $predefinedItems) {
			Emit-PredefinedItem (Parse-PredefinedItem $raw) "`t"
		}
		X "</PredefinedData>"

		Ensure-ExtDir
		$predefinedPath = Join-Path $extDir "Predefined.xml"
		[System.IO.File]::WriteAllText($predefinedPath, $script:xml.ToString().TrimEnd("`r", "`n"), $enc)
		$modulesCreated += $predefinedPath
	}
}

# Модуль команды: платформа заводит его у каждой команды объекта.
if ($objCommands -and $objCommands.Count -gt 0) {
	foreach ($cmdName in $objCommands.Keys) {
		$cmdDir = Join-Path (Join-Path (Join-Path $objSubDir "Commands") $cmdName) "Ext"
		if (-not (Test-Path $cmdDir)) { New-Item -ItemType Directory -Path $cmdDir -Force | Out-Null }
		$cmdModule = Join-Path $cmdDir "CommandModule.bsl"
		if (-not (Test-Path $cmdModule)) {
			$cmdText = "&НаКлиенте`nПроцедура ОбработкаКоманды(ПараметрКоманды, ПараметрыВыполненияКоманды)`n`n`t// Вставьте обработчик команды.`n`nКонецПроцедуры`n"
			[System.IO.File]::WriteAllText($cmdModule, $cmdText, (New-Object System.Text.UTF8Encoding($false)))
			$modulesCreated += $cmdModule
		}
	}
}

if ($objType -in $typesWithObjectModule) {
	$modulePath = Join-Path $extDir "ObjectModule.bsl"
	if (-not (Test-Path $modulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($modulePath, "", $enc)
		$modulesCreated += $modulePath
	}
}
if ($objType -in $typesWithManagerModule) {
	$modulePath = Join-Path $extDir "ManagerModule.bsl"
	if (-not (Test-Path $modulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($modulePath, "", $enc)
		$modulesCreated += $modulePath
	}
}
if ($objType -in $typesWithValueManagerModule) {
	$modulePath = Join-Path $extDir "ValueManagerModule.bsl"
	if (-not (Test-Path $modulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($modulePath, "", $enc)
		$modulesCreated += $modulePath
	}
}
if ($objType -in $typesWithRecordSetModule) {
	$modulePath = Join-Path $extDir "RecordSetModule.bsl"
	if (-not (Test-Path $modulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($modulePath, "", $enc)
		$modulesCreated += $modulePath
	}
}
if ($objType -in $typesWithModule) {
	$modulePath = Join-Path $extDir "Module.bsl"
	if (-not (Test-Path $modulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($modulePath, "", $enc)
		$modulesCreated += $modulePath
	}
}

# CommonCommand: модуль команды
if ($objType -eq "CommonCommand") {
	$cmdModulePath = Join-Path $extDir "CommandModule.bsl"
	if (-not (Test-Path $cmdModulePath)) {
		Ensure-ExtDir
		[System.IO.File]::WriteAllText($cmdModulePath, "", $enc)
		$modulesCreated += $cmdModulePath
	}
}

# CommonForm: заготовка управляемой формы и ее модуль.
# Пространства имен у формы свои - это не тот же набор, что у объектов метаданных.
if ($objType -eq "CommonForm") {
	Ensure-ExtDir
	$formXmlPath = Join-Path $extDir "Form.xml"
	if (-not (Test-Path $formXmlPath)) {
		# Начиная с формата 2.21 (8.5) в шапке формы объявляется палитра - между lf и style.
		$formPal = ''
		if ((Get-FormatVersionRank $script:formatVersion) -ge 221) {
			$formPal = ' xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"'
		}
		$formNs = 'xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"' + $formPal + ' xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
		$formLines = @(
			'<?xml version="1.0" encoding="UTF-8"?>'
			"<Form $formNs version=`"$($script:formatVersion)`">"
			"`t<AutoCommandBar name=`"ФормаКоманднаяПанель`" id=`"-1`">"
			"`t`t<Autofill>true</Autofill>"
			"`t</AutoCommandBar>"
			"`t<ChildItems/>"
			"</Form>"
		)
		[System.IO.File]::WriteAllText($formXmlPath, ($formLines -join "`r`n"), $enc)
		$modulesCreated += $formXmlPath
	}
	$formModuleDir = Join-Path $extDir "Form"
	if (-not (Test-Path $formModuleDir)) {
		New-Item -ItemType Directory -Path $formModuleDir -Force | Out-Null
	}
	$formModulePath = Join-Path $formModuleDir "Module.bsl"
	if (-not (Test-Path $formModulePath)) {
		[System.IO.File]::WriteAllText($formModulePath, "", $enc)
		$modulesCreated += $formModulePath
	}
}

# Special files
if ($objType -eq "ExchangePlan") {
	$contentPath = Join-Path $extDir "Content.xml"
	if (-not (Test-Path $contentPath)) {
		Ensure-ExtDir
		$contentXml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?>`r`n<ExchangePlanContent xmlns=`"http://v8.1c.ru/8.3/xcf/extrnprops`" xmlns:xr=`"http://v8.1c.ru/8.3/xcf/readable`" version=`"$($script:formatVersion)`"/>`r`n"
		[System.IO.File]::WriteAllText($contentPath, $contentXml, $enc)
		$modulesCreated += $contentPath
	}
}
if ($objType -eq "BusinessProcess") {
	$flowchartPath = Join-Path $extDir "Flowchart.xml"
	if (-not (Test-Path $flowchartPath)) {
		Ensure-ExtDir
		$flowchartXml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?>`r`n<Flowchart xmlns=`"http://v8.1c.ru/8.3/MDClasses`" version=`"$($script:formatVersion)`"/>`r`n"
		[System.IO.File]::WriteAllText($flowchartPath, $flowchartXml, $enc)
		$modulesCreated += $flowchartPath
	}
}

# --- 17. Register in Configuration.xml ---

$configXmlPath = Join-Path $OutputDir "Configuration.xml"
$regResult = $null

# XML tag name for Configuration.xml ChildObjects
$childTag = $objType

if (Test-Path $configXmlPath) {
	$configDoc = New-Object System.Xml.XmlDocument
	$configDoc.PreserveWhitespace = $true
	$configDoc.Load($configXmlPath)
	# Концы строк берутся из ФАЙЛА, который правим: регистрация не меняет его стиль.
	$origCfgCrlf = [System.IO.File]::ReadAllText($configXmlPath).Contains("`r`n")

	$nsMgr = New-Object System.Xml.XmlNamespaceManager($configDoc.NameTable)
	$nsMgr.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")

	$childObjects = $configDoc.SelectSingleNode("//md:Configuration/md:ChildObjects", $nsMgr)
	if ($childObjects) {
		$existing = $childObjects.SelectNodes("md:$childTag", $nsMgr)
		$alreadyExists = $false
		foreach ($e in $existing) {
			if ($e.InnerText -eq $objName) {
				$alreadyExists = $true
				break
			}
		}

		if ($alreadyExists) {
			$regResult = "already"
		} else {
			$newElem = $configDoc.CreateElement($childTag, "http://v8.1c.ru/8.3/MDClasses")
			$newElem.InnerText = $objName

			if ($existing.Count -gt 0) {
				# Insert after last existing element of same type
				$lastElem = $existing[$existing.Count - 1]
				$newWs = $configDoc.CreateWhitespace("`n`t`t`t")
				$childObjects.InsertAfter($newWs, $lastElem) | Out-Null
				$childObjects.InsertAfter($newElem, $newWs) | Out-Null
			} else {
				# No existing elements of this type - insert before closing whitespace
				$lastChild = $childObjects.LastChild
				if ($lastChild.NodeType -eq [System.Xml.XmlNodeType]::Whitespace) {
					$newWs = $configDoc.CreateWhitespace("`n`t`t`t")
					$childObjects.InsertBefore($newWs, $lastChild) | Out-Null
					$childObjects.InsertBefore($newElem, $lastChild) | Out-Null
				} else {
					$childObjects.AppendChild($configDoc.CreateWhitespace("`n`t`t`t")) | Out-Null
					$childObjects.AppendChild($newElem) | Out-Null
					$childObjects.AppendChild($configDoc.CreateWhitespace("`n`t`t")) | Out-Null
				}
			}

			# Save
			$cfgSettings = New-Object System.Xml.XmlWriterSettings
			$cfgSettings.Encoding = New-Object System.Text.UTF8Encoding($true)
			$cfgSettings.Indent = $false
			$stream = New-Object System.IO.FileStream($configXmlPath, [System.IO.FileMode]::Create)
			$writer = [System.Xml.XmlWriter]::Create($stream, $cfgSettings)
			$configDoc.Save($writer)
			$writer.Close()
			$stream.Close()
			# Пустой элемент: XmlWriter отдает `<a />`, Конфигуратор пишет `<a/>`. Внутри
			# CDATA/комментария или значения атрибута ` />` может быть содержимым,
			# поэтому они идут первыми ветками альтернации и возвращаются как есть.
			$tightPath = $configXmlPath
			$tightText = [System.IO.File]::ReadAllText($tightPath, [System.Text.Encoding]::UTF8)
			$tightText = $tightText.Replace('encoding="utf-8"', 'encoding="UTF-8"')
			$tightText = [regex]::Replace($tightText, '(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|<([A-Za-z0-9_:.\-]+)((?:\s+[A-Za-z0-9_:.\-]+="[^"]*")*)\s+/>', { param($m) if ($m.Groups[1].Success) { '<' + $m.Groups[1].Value + $m.Groups[2].Value + '/>' } else { $m.Value } })
			$tightText = $tightText.Replace("`r`n", "`n")
			if ($origCfgCrlf) { $tightText = $tightText.Replace("`n", "`r`n") }
			[System.IO.File]::WriteAllText($tightPath, $tightText, (New-Object System.Text.UTF8Encoding($true)))

			$regResult = "added"
		}
	} else {
		$regResult = "no-childobj"
	}
} else {
	$regResult = "no-config"
}

# --- 18. Summary ---

$attrCount = 0
$tsCount = 0
$dimCount = 0
$resCount = 0
$valCount = 0
$colCount = 0

if ($def.attributes) { $attrCount = @($def.attributes).Count }
if ($def.tabularSections) {
	if ($def.tabularSections -is [array] -or $def.tabularSections.GetType().Name -eq "Object[]") {
		$tsCount = @($def.tabularSections).Count
	} else {
		$tsCount = @($def.tabularSections.PSObject.Properties).Count
	}
}
if ($def.dimensions) { $dimCount = @($def.dimensions).Count }
if ($def.resources) { $resCount = @($def.resources).Count }
if ($def.values) { $valCount = @($def.values).Count }
if ($def.columns) { $colCount = @($def.columns).Count }

Write-Host "[OK] $objType '$objName' compiled"
Write-Host "     UUID: $uuid"
Write-Host "     File: $mainXmlPath"

$details = @()
if ($attrCount -gt 0) { $details += "Attributes: $attrCount" }
if ($tsCount -gt 0)   { $details += "TabularSections: $tsCount" }
if ($dimCount -gt 0)  { $details += "Dimensions: $dimCount" }
if ($resCount -gt 0)  { $details += "Resources: $resCount" }
if ($valCount -gt 0)  { $details += "Values: $valCount" }
if ($colCount -gt 0)  { $details += "Columns: $colCount" }

if ($details.Count -gt 0) {
	Write-Host "     $($details -join ', ')"
}

foreach ($mc in $modulesCreated) {
	Write-Host "     Module: $mc"
}

switch ($regResult) {
	"added"       { Write-Host "     Configuration.xml: <$childTag>$objName</$childTag> added to ChildObjects" }
	"already"     { Write-Host "     Configuration.xml: <$childTag>$objName</$childTag> already registered" }
	"no-childobj" { Write-Warning "Configuration.xml found but <ChildObjects> not found" }
	"no-config"   { Write-Host "     Configuration.xml: not found at $configXmlPath (register manually)" }
}

# Cross-reference hints
if ($objType -eq "AccountingRegister" -and -not $def.chartOfAccounts) {
	Write-Host "[HINT] AccountingRegister requires ChartOfAccounts reference:"
	Write-Host "       /meta-edit -Operation modify-property -Value `"ChartOfAccounts=ChartOfAccounts.XXX`""
}
if ($objType -eq "CalculationRegister" -and -not $def.chartOfCalculationTypes) {
	Write-Host "[HINT] CalculationRegister requires ChartOfCalculationTypes reference:"
	Write-Host "       /meta-edit -Operation modify-property -Value `"ChartOfCalculationTypes=ChartOfCalculationTypes.XXX`""
}
if ($objType -eq "BusinessProcess" -and -not $def.task) {
	Write-Host "[HINT] BusinessProcess requires Task reference:"
	Write-Host "       /meta-edit -Operation modify-property -Value `"Task=Task.XXX`""
}
if ($objType -eq "ChartOfAccounts") {
	$maxExtDim = if ($null -ne $def.maxExtDimensionCount) { [int]$def.maxExtDimensionCount } else { 0 }
	if ($maxExtDim -gt 0 -and -not $def.extDimensionTypes) {
		Write-Host "[HINT] ChartOfAccounts with MaxExtDimensionCount>0 requires ExtDimensionTypes:"
		Write-Host "       /meta-edit -Operation modify-property -Value `"ExtDimensionTypes=ChartOfCharacteristicTypes.XXX`""
	}
}
