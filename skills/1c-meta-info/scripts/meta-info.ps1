# meta-info v1.1 - Compact summary of 1C metadata object
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory=$true)][string]$ObjectPath,
	[ValidateSet("overview","brief","full")]
	[string]$Mode = "overview",
	[string]$Name,
	[int]$Limit = 150,
	[int]$Offset = 0,
	[string]$OutFile
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Output helper (always collect, paginate at the end) ---
$script:lines = @()
function Out([string]$text) { $script:lines += $text }

# --- Resolve path ---
if (-not [System.IO.Path]::IsPathRooted($ObjectPath)) {
	$ObjectPath = Join-Path (Get-Location).Path $ObjectPath
}

# Directory -> find XML inside or as sibling
if (Test-Path $ObjectPath -PathType Container) {
	$dirName = Split-Path $ObjectPath -Leaf
	$candidate = Join-Path $ObjectPath "$dirName.xml"
	$sibling = Join-Path (Split-Path $ObjectPath) "$dirName.xml"
	if (Test-Path $candidate) {
		$ObjectPath = $candidate
	} elseif (Test-Path $sibling) {
		$ObjectPath = $sibling
	} else {
		$xmlFiles = @(Get-ChildItem $ObjectPath -Filter "*.xml" -File | Select-Object -First 1)
		if ($xmlFiles.Count -gt 0) {
			$ObjectPath = $xmlFiles[0].FullName
		} else {
			Write-Host "[ERROR] No XML file found in directory: $ObjectPath"
			exit 1
		}
	}
}

# File not found - check Dir/Name/Name.xml → Dir/Name.xml (common LLM mistake)
if (-not (Test-Path $ObjectPath)) {
	$fileName = [System.IO.Path]::GetFileNameWithoutExtension($ObjectPath)
	$parentDir = Split-Path $ObjectPath
	$parentDirName = Split-Path $parentDir -Leaf
	if ($fileName -eq $parentDirName) {
		$candidate = Join-Path (Split-Path $parentDir) "$fileName.xml"
		if (Test-Path $candidate) { $ObjectPath = $candidate }
	}
}
if (-not (Test-Path $ObjectPath)) {
	Write-Host "[ERROR] File not found: $ObjectPath"
	exit 1
}

# --- Load XML ---
[xml]$xmlDoc = Get-Content -Path $ObjectPath -Encoding UTF8
$ns = New-Object System.Xml.XmlNamespaceManager($xmlDoc.NameTable)
$ns.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")
$ns.AddNamespace("v8", "http://v8.1c.ru/8.1/data/core")
$ns.AddNamespace("xr", "http://v8.1c.ru/8.3/xcf/readable")
$ns.AddNamespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
$ns.AddNamespace("xs", "http://www.w3.org/2001/XMLSchema")
$ns.AddNamespace("cfg", "http://v8.1c.ru/8.1/data/enterprise/current-config")
$ns.AddNamespace("app", "http://v8.1c.ru/8.2/managed-application/core")

$mdRoot = $xmlDoc.SelectSingleNode("/md:MetaDataObject", $ns)
if (-not $mdRoot) {
	Write-Host "[ERROR] Not a valid 1C metadata XML file"
	exit 1
}

# --- Detect object type ---
$typeNode = $null
$mdType = ""
foreach ($child in $mdRoot.ChildNodes) {
	if ($child.NodeType -eq 'Element' -and $child.NamespaceURI -eq "http://v8.1c.ru/8.3/MDClasses") {
		$typeNode = $child
		$mdType = $child.LocalName
		break
	}
}

if (-not $typeNode) {
	Write-Host "[ERROR] Cannot detect metadata type"
	exit 1
}

# --- Type name maps ---
$typeNameMap = @{
	"Catalog"="Справочник"; "Document"="Документ"; "Enum"="Перечисление"
	"Constant"="Константа"; "InformationRegister"="Регистр сведений"
	"AccumulationRegister"="Регистр накопления"; "AccountingRegister"="Регистр бухгалтерии"
	"CalculationRegister"="Регистр расчета"; "ChartOfAccounts"="План счетов"
	"ChartOfCharacteristicTypes"="План видов характеристик"
	"ChartOfCalculationTypes"="План видов расчета"; "BusinessProcess"="Бизнес-процесс"
	"Task"="Задача"; "ExchangePlan"="План обмена"; "DocumentJournal"="Журнал документов"
	"Report"="Отчет"; "DataProcessor"="Обработка"
	"DefinedType"="Определяемый тип"; "CommonModule"="Общий модуль"
	"ScheduledJob"="Регламентное задание"; "EventSubscription"="Подписка на событие"
	"HTTPService"="HTTP-сервис"; "WebService"="Веб-сервис"
}

$refTypeMap = @{
	"CatalogRef"="СправочникСсылка"; "DocumentRef"="ДокументСсылка"
	"EnumRef"="ПеречислениеСсылка"; "ChartOfAccountsRef"="ПланСчетовСсылка"
	"ChartOfCharacteristicTypesRef"="ПВХСсылка"; "ChartOfCalculationTypesRef"="ПВРСсылка"
	"ExchangePlanRef"="ПланОбменаСсылка"; "BusinessProcessRef"="БизнесПроцессСсылка"
	"TaskRef"="ЗадачаСсылка"
}

$regTypeMap = @{
	"AccumulationRegister"="РН"; "AccountingRegister"="РБ"; "CalculationRegister"="РР"
	"InformationRegister"="РС"
}

$periodMap = @{
	"Nonperiodical"="Непериодический"; "Day"="День"; "Month"="Месяц"
	"Quarter"="Квартал"; "Year"="Год"; "Second"="Секунда"
}

$writeModeMap = @{
	"Independent"="независимая"; "RecorderSubordinate"="подчинение регистратору"
}

$reuseMap = @{
	"DontUse"="нет"; "DuringRequest"="на время вызова"; "DuringSession"="на время сеанса"
}

$eventMap = @{
	"BeforeWrite"="ПередЗаписью"; "OnWrite"="ПриЗаписи"; "AfterWrite"="ПослеЗаписи"
	"BeforeDelete"="ПередУдалением"; "Posting"="ОбработкаПроведения"
	"UndoPosting"="ОбработкаУдаленияПроведения"
	"OnReadAtServer"="ПриЧтенииНаСервере"
	"FillCheckProcessing"="ОбработкаПроверкиЗаполнения"
}

$objectTypeMap = @{
	"CatalogObject"="СправочникОбъект"; "DocumentObject"="ДокументОбъект"
	"ChartOfAccountsObject"="ПланСчетовОбъект"
	"ChartOfCharacteristicTypesObject"="ПВХОбъект"
	"BusinessProcessObject"="БизнесПроцессОбъект"; "TaskObject"="ЗадачаОбъект"
	"ExchangePlanObject"="ПланОбменаОбъект"
	"InformationRegisterRecordSet"="НаборЗаписейРС"
	"AccumulationRegisterRecordSet"="НаборЗаписейРН"
	"AccountingRegisterRecordSet"="НаборЗаписейРБ"
}

$numberPeriodMap = @{
	"Year"="по году"; "Quarter"="по кварталу"; "Month"="по месяцу"; "Day"="по дню"
	"WholeCatalog"="сквозная"
}

$ruTypeName = if ($typeNameMap.ContainsKey($mdType)) { $typeNameMap[$mdType] } else { $mdType }

# --- Helpers ---

function Get-MLText($node) {
	if (-not $node) { return "" }
	$c = $node.SelectSingleNode("v8:item[v8:lang='ru']/v8:content", $ns)
	if ($c) { return $c.InnerText }
	$c = $node.SelectSingleNode("v8:item/v8:content", $ns)
	if ($c) { return $c.InnerText }
	$text = $node.InnerText.Trim()
	if ($text) { return $text }
	return ""
}

function Format-Type($typeNode) {
	if (-not $typeNode) { return "" }
	$types = @()
	foreach ($t in $typeNode.SelectNodes("v8:Type", $ns)) {
		$raw = $t.InnerText
		$types += Format-SingleType $raw $typeNode
	}
	foreach ($t in $typeNode.SelectNodes("v8:TypeSet", $ns)) {
		$raw = $t.InnerText
		if ($raw -match '^cfg:DefinedType\.(.+)$') {
			$types += "ОпределяемыйТип.$($Matches[1])"
		} elseif ($raw -match '^cfg:Characteristic\.(.+)$') {
			$types += "Характеристика.$($Matches[1])"
		} else {
			$types += $raw
		}
	}
	if ($types.Count -eq 0) { return "" }
	if ($types.Count -eq 1) { return $types[0] }
	return ($types -join " | ")
}

# Типы узла по одному: свернутая запись и разбор по -Name считают их сами.
function Format-TypeList($typeNode) {
	if (-not $typeNode) { return @() }
	$items = New-Object System.Collections.Generic.List[string]
	foreach ($t in $typeNode.SelectNodes("v8:Type", $ns)) {
		[void]$items.Add((Format-SingleType $t.InnerText $typeNode))
	}
	foreach ($t in $typeNode.SelectNodes("v8:TypeSet", $ns)) {
		[void]$items.Add((Format-SingleType $t.InnerText $typeNode))
	}
	return $items
}

function Format-SingleType([string]$raw, $parentNode) {
	switch -Wildcard ($raw) {
		"xs:string" {
			$sq = $parentNode.SelectSingleNode("v8:StringQualifiers/v8:Length", $ns)
			$len = if ($sq) { $sq.InnerText } else { "" }
			if ($len) { return "Строка($len)" } else { return "Строка" }
		}
		"xs:decimal" {
			$dg = $parentNode.SelectSingleNode("v8:NumberQualifiers/v8:Digits", $ns)
			$fr = $parentNode.SelectSingleNode("v8:NumberQualifiers/v8:FractionDigits", $ns)
			$d = if ($dg) { $dg.InnerText } else { "" }
			$f = if ($fr) { $fr.InnerText } else { "0" }
			if ($d) { return "Число($d,$f)" } else { return "Число" }
		}
		"xs:boolean" { return "Булево" }
		"xs:dateTime" {
			$dq = $parentNode.SelectSingleNode("v8:DateQualifiers/v8:DateFractions", $ns)
			if ($dq) {
				switch ($dq.InnerText) {
					"Date" { return "Дата" }
					"Time" { return "Время" }
					"DateTime" { return "ДатаВремя" }
					default { return "Дата" }
				}
			}
			return "ДатаВремя"
		}
		"v8:ValueStorage" { return "ХранилищеЗначения" }
		"v8:UUID" { return "УникальныйИдентификатор" }
		"v8:Null" { return "Null" }
		default {
			# Normalize d5p1:/dNpN: -> cfg:
			$raw = $raw -replace '^d\d+p\d+:', 'cfg:'
			# cfg:CatalogRef.Xxx -> СправочникСсылка.Xxx
			if ($raw -match '^cfg:(\w+)Ref\.(.+)$') {
				$prefix = "$($Matches[1])Ref"
				$objn = $Matches[2]
				if ($refTypeMap.ContainsKey($prefix)) {
					return "$($refTypeMap[$prefix]).$objn"
				}
			}
			if ($raw -match '^cfg:(\w+)Ref$') {
				$bare = "$($Matches[1])Ref"
				if ($refTypeMap.ContainsKey($bare)) { return $refTypeMap[$bare] }
			}
			# cfg:EnumRef.Xxx
			if ($raw -match '^cfg:EnumRef\.(.+)$') {
				return "ПеречислениеСсылка.$($Matches[1])"
			}
			# cfg:Characteristic.Xxx
			if ($raw -match '^cfg:Characteristic\.(.+)$') {
				return "Характеристика.$($Matches[1])"
			}
			# cfg:DefinedType.Xxx
			if ($raw -match '^cfg:DefinedType\.(.+)$') {
				return "ОпределяемыйТип.$($Matches[1])"
			}
			# Strip cfg: prefix for unknown
			if ($raw -match '^cfg:(.+)$') {
				return $Matches[1]
			}
			return $raw
		}
	}
}

function Format-Flags($propsNode, [bool]$isDimension = $false) {
	$flags = @()
	$fc = $propsNode.SelectSingleNode("md:FillChecking", $ns)
	if ($fc -and $fc.InnerText -eq "ShowError") { $flags += "обязательный" }

	$idx = $propsNode.SelectSingleNode("md:Indexing", $ns)
	if ($idx) {
		switch ($idx.InnerText) {
			"Index" { $flags += "индекс" }
			"IndexWithAdditionalOrder" { $flags += "индекс+доп" }
		}
	}

	if ($isDimension) {
		$master = $propsNode.SelectSingleNode("md:Master", $ns)
		if ($master -and $master.InnerText -eq "true") { $flags += "ведущее" }
	}

	$ml = $propsNode.SelectSingleNode("md:MultiLine", $ns)
	if ($ml -and $ml.InnerText -eq "true") { $flags += "многострочный" }

	$use = $propsNode.SelectSingleNode("md:Use", $ns)
	if ($use) {
		switch ($use.InnerText) {
			"ForFolder" { $flags += "для папок" }
			"ForFolderAndItem" { $flags += "для папок и элементов" }
		}
	}

	if ($flags.Count -eq 0) { return "" }
	return "  [$($flags -join ', ')]"
}

function Get-Attributes($parentNode, [string]$childTag = "Attribute", [bool]$isDimension = $false) {
	$result = @()
	foreach ($attr in $parentNode.SelectNodes("md:$childTag", $ns)) {
		$aprops = $attr.SelectSingleNode("md:Properties", $ns)
		if (-not $aprops) { continue }
		$attrName = $aprops.SelectSingleNode("md:Name", $ns).InnerText
		$typeStr = Format-Type $aprops.SelectSingleNode("md:Type", $ns)
		$aflags = Format-Flags $aprops $isDimension
		$result += @{ Name=$attrName; Type=$typeStr; Flags=$aflags; Props=$aprops }
	}
	return $result
}

function Get-TabularSections($parentNode) {
	$result = @()
	foreach ($ts in $parentNode.SelectNodes("md:TabularSection", $ns)) {
		$tprops = $ts.SelectSingleNode("md:Properties", $ns)
		$tsName = $tprops.SelectSingleNode("md:Name", $ns).InnerText
		$tchildObjs = $ts.SelectSingleNode("md:ChildObjects", $ns)
		$cols = @()
		if ($tchildObjs) { $cols = @(Get-Attributes $tchildObjs) }
		$result += @{ Name=$tsName; Columns=$cols; ColCount=$cols.Count }
	}
	return $result
}

function Format-AttrLine([hashtable]$attr, [int]$maxNameLen = 30) {
	$padded = $attr.Name.PadRight($maxNameLen)
	return "  $padded $($attr.Type)$($attr.Flags)"
}

function Get-MaxNameLen($attrs) {
	$max = 10
	foreach ($a in $attrs) {
		if ($a.Name.Length -gt $max) { $max = $a.Name.Length }
	}
	return [Math]::Min($max + 2, 40)
}

function Get-SimpleChildren($parentNode, [string]$tag) {
	$result = @()
	foreach ($child in $parentNode.SelectNodes("md:$tag", $ns)) {
		$result += $child.InnerText
	}
	return $result
}

function Sort-AttrsRefFirst($attrs) {
	$refs = @()
	$prims = @()
	foreach ($a in $attrs) {
		$t = $a.Type
		if ($t -match 'Ссылка\.' -or $t -match 'Характеристика\.' -or $t -match 'ОпределяемыйТип\.' -or $t -match 'ПланСчетовСсылка' -or $t -match 'ПВХСсылка' -or $t -match 'ПВРСсылка') {
			$refs += $a
		} else {
			$prims += $a
		}
	}
	return @($refs) + @($prims)
}

function Decline-Cols([int]$n) {
	$m = $n % 10
	$h = $n % 100
	if ($h -ge 11 -and $h -le 19) { return "колонок" }
	if ($m -eq 1) { return "колонка" }
	if ($m -ge 2 -and $m -le 4) { return "колонки" }
	return "колонок"
}

function Format-SourceType([string]$raw) {
	$raw = $raw -replace '^d\d+p\d+:', 'cfg:'
	if ($raw -match '^cfg:(\w+)\.(.+)$') {
		$prefix = $Matches[1]; $name = $Matches[2]
		if ($objectTypeMap.ContainsKey($prefix)) { return "$($objectTypeMap[$prefix]).$name" }
	}
	if ($raw -match '^cfg:(.+)$') { return $Matches[1] }
	return $raw
}

function Get-HTTPEndpoints($childObjs) {
	$result = @()
	foreach ($tpl in $childObjs.SelectNodes("md:URLTemplate", $ns)) {
		$tp = $tpl.SelectSingleNode("md:Properties", $ns)
		$tplName = $tp.SelectSingleNode("md:Name", $ns).InnerText
		$template = $tp.SelectSingleNode("md:Template", $ns).InnerText
		$methods = @()
		$tplCO = $tpl.SelectSingleNode("md:ChildObjects", $ns)
		if ($tplCO) {
			foreach ($m in $tplCO.SelectNodes("md:Method", $ns)) {
				$mp = $m.SelectSingleNode("md:Properties", $ns)
				$httpMethod = $mp.SelectSingleNode("md:HTTPMethod", $ns).InnerText
				$handler = $mp.SelectSingleNode("md:Handler", $ns).InnerText
				$methods += @{ HTTPMethod=$httpMethod; Handler=$handler; Name=$mp.SelectSingleNode("md:Name",$ns).InnerText }
			}
		}
		$result += @{ Name=$tplName; Template=$template; Methods=$methods }
	}
	return $result
}

function Get-WSOperations($childObjs) {
	$result = @()
	foreach ($op in $childObjs.SelectNodes("md:Operation", $ns)) {
		$oprops = $op.SelectSingleNode("md:Properties", $ns)
		$opName = $oprops.SelectSingleNode("md:Name", $ns).InnerText
		$retType = $oprops.SelectSingleNode("md:XDTOReturningValueType", $ns)
		$retStr = if ($retType -and $retType.InnerText) { $retType.InnerText } else { "void" }
		$procName = $oprops.SelectSingleNode("md:ProcedureName", $ns)
		$params = @()
		$opCO = $op.SelectSingleNode("md:ChildObjects", $ns)
		if ($opCO) {
			foreach ($p in $opCO.SelectNodes("md:Parameter", $ns)) {
				$pp = $p.SelectSingleNode("md:Properties", $ns)
				$pName = $pp.SelectSingleNode("md:Name", $ns).InnerText
				$pType = $pp.SelectSingleNode("md:XDTOValueType", $ns)
				$pTypeStr = if ($pType) { $pType.InnerText } else { "?" }
				$dir = $pp.SelectSingleNode("md:TransferDirection", $ns)
				$dirStr = if ($dir -and $dir.InnerText -ne "In") { " [$($dir.InnerText.ToLower())]" } else { "" }
				$params += "${pName}: ${pTypeStr}${dirStr}"
			}
		}
		$paramStr = $params -join ", "
		$result += @{ Name=$opName; Params=$paramStr; ReturnType=$retStr; ProcName=$(if ($procName) { $procName.InnerText } else { "" }) }
	}
	return $result
}

# --- Extract metadata ---
$props = $typeNode.SelectSingleNode("md:Properties", $ns)
$childObjs = $typeNode.SelectSingleNode("md:ChildObjects", $ns)
$objName = $props.SelectSingleNode("md:Name", $ns).InnerText
$synNode = $props.SelectSingleNode("md:Synonym", $ns)
$synonym = Get-MLText $synNode

# --- Handle -Name drill-down ---
$drillDone = $false
if ($Name) {
	# Стандартный реквизит не лежит в ChildObjects: его состав задан свойствами объекта.
	$drillOwners = New-Object System.Collections.Generic.List[string]
	$ownersNode = $props.SelectSingleNode("md:Owners", $ns)
	if ($ownersNode) {
		foreach ($ownerItem in $ownersNode.ChildNodes) {
			if ($ownerItem.InnerText.Trim()) { [void]$drillOwners.Add($ownerItem.InnerText.Trim()) }
		}
	}
	$stdTypes = New-Object System.Collections.Generic.List[string]
	$stdFlags = New-Object System.Collections.Generic.List[string]
	if ($Name -in @("Владелец", "Owner") -and $drillOwners.Count -gt 0) {
		foreach ($ownerRef in $drillOwners) {
			$kind = $ownerRef.Split('.')[0]
			$oname = $ownerRef.Split('.')[-1]
			$prefix = if ($kind -eq 'Catalog') { 'СправочникСсылка' } else { $kind }
			[void]$stdTypes.Add("$prefix.$oname")
		}
		[void]$stdFlags.Add('обязательный')
	} elseif ($Name -in @("ТипЗначения", "ValueType") -and $mdType -eq 'ChartOfCharacteristicTypes') {
		$stdTypes = Format-TypeList $props.SelectSingleNode("md:Type", $ns)
	} elseif ($Name -in @("Родитель", "Parent")) {
		$hier = $props.SelectSingleNode("md:Hierarchical", $ns)
		if ($hier -and $hier.InnerText -eq 'true') {
			$selfRef = if ($mdType -eq 'ChartOfCharacteristicTypes') { 'ПВХСсылка' } else { 'СправочникСсылка' }
			[void]$stdTypes.Add("$selfRef.$objName")
		}
	}
	if ($stdTypes.Count -gt 0) {
		Out "Стандартный реквизит: $Name"
		Out "  Типы ($($stdTypes.Count)):"
		foreach ($stdType in $stdTypes) { Out "    $stdType" }
		if ($stdFlags.Count -gt 0) { Out "  Свойства: $($stdFlags -join ', ')" }
		$drillDone = $true
	}
}

if ($Name -and -not $drillDone -and $childObjs) {
	# Search in attributes/dimensions/resources
	$attrTags = @("Attribute","Dimension","Resource")
	foreach ($tag in $attrTags) {
		if ($drillDone) { break }
		foreach ($attr in $childObjs.SelectNodes("md:$tag", $ns)) {
			$ap = $attr.SelectSingleNode("md:Properties", $ns)
			if (-not $ap) { continue }
			$an = $ap.SelectSingleNode("md:Name", $ns).InnerText
			if ($an -eq $Name) {
				$tagRu = switch ($tag) {
					"Attribute" { "Реквизит" }
					"Dimension" { "Измерение" }
					"Resource" { "Ресурс" }
				}
				Out "$($tagRu): $an"
				$typeStr = Format-Type $ap.SelectSingleNode("md:Type", $ns)
				Out "  Тип: $typeStr"
				$fc = $ap.SelectSingleNode("md:FillChecking", $ns)
				Out "  Обязательный: $(if ($fc -and $fc.InnerText -eq 'ShowError') { 'да' } else { 'нет' })"
				$idx = $ap.SelectSingleNode("md:Indexing", $ns)
				$idxRu = if (-not $idx -or $idx.InnerText -eq 'DontIndex') { 'нет' }
					elseif ($idx.InnerText -eq 'Index') { 'Индекс' }
					elseif ($idx.InnerText -eq 'IndexWithAdditionalOrder') { 'Индекс с доп. упорядочиванием' }
					else { $idx.InnerText }
				Out "  Индексирование: $idxRu"
				$ml = $ap.SelectSingleNode("md:MultiLine", $ns)
				if ($ml -and $ml.InnerText -eq "true") { Out "  Многострочный: да" }
				$use = $ap.SelectSingleNode("md:Use", $ns)
				if ($use -and $use.InnerText -ne "ForItem") {
					$useRu = switch ($use.InnerText) {
						"ForFolder" { "для папок" }
						"ForFolderAndItem" { "для папок и элементов" }
						default { $use.InnerText }
					}
					Out "  Использование: $useRu"
				}
				$fv = $ap.SelectSingleNode("md:FillValue", $ns)
				if ($fv -and -not ($fv.GetAttribute("nil", "http://www.w3.org/2001/XMLSchema-instance") -eq "true") -and $fv.InnerText) {
					$fvText = $fv.InnerText
					if ($fvText -match '\.EmptyRef$') { $fvText = "Пустая ссылка" }
					elseif ($fvText -eq "false") { $fvText = "Ложь" }
					elseif ($fvText -eq "true") { $fvText = "Истина" }
					Out "  Значение заполнения: $fvText"
				} else {
					Out "  Значение заполнения: -"
				}
				if ($tag -eq "Dimension") {
					$master = $ap.SelectSingleNode("md:Master", $ns)
					Out "  Ведущее: $(if ($master -and $master.InnerText -eq 'true') { 'да' } else { 'нет' })"
					$mf = $ap.SelectSingleNode("md:MainFilter", $ns)
					Out "  Основной отбор: $(if ($mf -and $mf.InnerText -eq 'true') { 'да' } else { 'нет' })"
				}
				$synA = $ap.SelectSingleNode("md:Synonym", $ns)
				$synText = Get-MLText $synA
				if ($synText -and $synText -ne $an) { Out "  Синоним: $synText" }
				$drillDone = $true
				break
			}
		}
	}

	# Search in tabular sections
	if (-not $drillDone) {
		foreach ($ts in $childObjs.SelectNodes("md:TabularSection", $ns)) {
			$tp = $ts.SelectSingleNode("md:Properties", $ns)
			$tn = $tp.SelectSingleNode("md:Name", $ns).InnerText
			if ($tn -eq $Name) {
				$tsCO = $ts.SelectSingleNode("md:ChildObjects", $ns)
				$cols = @()
				if ($tsCO) { $cols = @(Get-Attributes $tsCO) }
				Out "ТЧ: $tn ($($cols.Count) $(Decline-Cols $cols.Count)):"
				if ($cols.Count -gt 0) {
					$ml = Get-MaxNameLen $cols
					foreach ($c in $cols) { Out (Format-AttrLine $c $ml) }
				}
				$drillDone = $true
				break
			}
		}
	}

	# Search in enum values
	if (-not $drillDone) {
		foreach ($ev in $childObjs.SelectNodes("md:EnumValue", $ns)) {
			$ep = $ev.SelectSingleNode("md:Properties", $ns)
			$en = $ep.SelectSingleNode("md:Name", $ns).InnerText
			if ($en -eq $Name) {
				$synE = $ep.SelectSingleNode("md:Synonym", $ns)
				$synText = Get-MLText $synE
				Out "Значение перечисления: $en"
				if ($synText) { Out "  Синоним: `"$synText`"" }
				$cm = $ep.SelectSingleNode("md:Comment", $ns)
				if ($cm -and $cm.InnerText) { Out "  Комментарий: $($cm.InnerText)" }
				$drillDone = $true
				break
			}
		}
	}

	# Search in HTTPService URLTemplates
	if (-not $drillDone -and $mdType -eq "HTTPService" -and $childObjs) {
		foreach ($tpl in $childObjs.SelectNodes("md:URLTemplate", $ns)) {
			$tp = $tpl.SelectSingleNode("md:Properties", $ns)
			if ($tp.SelectSingleNode("md:Name", $ns).InnerText -eq $Name) {
				$template = $tp.SelectSingleNode("md:Template", $ns).InnerText
				Out "Шаблон URL: $Name"
				Out "  Путь: $template"
				$tplCO = $tpl.SelectSingleNode("md:ChildObjects", $ns)
				if ($tplCO) {
					foreach ($m in $tplCO.SelectNodes("md:Method", $ns)) {
						$mp = $m.SelectSingleNode("md:Properties", $ns)
						$httpMethod = $mp.SelectSingleNode("md:HTTPMethod", $ns).InnerText
						$handler = $mp.SelectSingleNode("md:Handler", $ns).InnerText
						Out "  $httpMethod → $handler"
					}
				}
				$drillDone = $true; break
			}
		}
	}

	# Search in WebService Operations
	if (-not $drillDone -and $mdType -eq "WebService" -and $childObjs) {
		foreach ($op in $childObjs.SelectNodes("md:Operation", $ns)) {
			$oprops = $op.SelectSingleNode("md:Properties", $ns)
			if ($oprops.SelectSingleNode("md:Name", $ns).InnerText -eq $Name) {
				Out "Операция: $Name"
				$retType = $oprops.SelectSingleNode("md:XDTOReturningValueType", $ns)
				Out "  Возвращает: $(if ($retType -and $retType.InnerText) { $retType.InnerText } else { 'void' })"
				$procName = $oprops.SelectSingleNode("md:ProcedureName", $ns)
				if ($procName -and $procName.InnerText) { Out "  Процедура: $($procName.InnerText)" }
				$comment = $oprops.SelectSingleNode("md:Comment", $ns)
				if ($comment -and $comment.InnerText) { Out "  Комментарий: $($comment.InnerText)" }
				$opCO = $op.SelectSingleNode("md:ChildObjects", $ns)
				if ($opCO) {
					$params = $opCO.SelectNodes("md:Parameter", $ns)
					if ($params.Count -gt 0) {
						Out "  Параметры:"
						foreach ($p in $params) {
							$pp = $p.SelectSingleNode("md:Properties", $ns)
							$pName = $pp.SelectSingleNode("md:Name", $ns).InnerText
							$pType = $pp.SelectSingleNode("md:XDTOValueType", $ns)
							$dir = $pp.SelectSingleNode("md:TransferDirection", $ns)
							$dirStr = if ($dir -and $dir.InnerText -ne "In") { " [$($dir.InnerText.ToLower())]" } else { "" }
							Out "    ${pName}: $(if ($pType) { $pType.InnerText } else { '?' })${dirStr}"
						}
					}
				}
				$drillDone = $true; break
			}
		}
	}

	if (-not $drillDone) {
		Write-Host "[ERROR] '$Name' not found in $objName"
		exit 1
	}
}

# --- Main output (not drill-down) ---
if (-not $drillDone) {

	# --- Build header ---
	$header = "=== $ruTypeName`: $objName"
	if ($synonym -and $synonym -ne $objName) { $header += " - `"$synonym`"" }
	$header += " ==="
	Out $header

	# --- Стандартные реквизиты ---
	# Набор задан типом объекта, а характеристики - его свойствами: длина и тип кода,
	# длина наименования, владельцы и вид подчинения, периодичность и способ нумерации.
	function Out-StandardAttributes($props, [string]$mdType, $owners) {
		$rows = @()

		$codeLen = $props.SelectSingleNode("md:CodeLength", $ns)
		$codeType = $props.SelectSingleNode("md:CodeType", $ns)
		if ($codeLen -and [int]$codeLen.InnerText -gt 0) {
			$typeName = if ($codeType -and $codeType.InnerText -eq "Number") { "Число" } else { "Строка" }
			$rows += "  Код: $typeName($($codeLen.InnerText))"
		}

		$descLen = $props.SelectSingleNode("md:DescriptionLength", $ns)
		if ($descLen -and [int]$descLen.InnerText -gt 0) {
			$rows += "  Наименование: Строка($($descLen.InnerText))"
		}

		if ($owners -and $owners.Count -gt 0) {
			$ownerTypes = @($owners | ForEach-Object {
				$kind = ($_ -split '\.')[0]
				$name = ($_ -split '\.')[-1]
				$prefix = if ($kind -eq "Catalog") { "СправочникСсылка" } else { $kind }
				"$prefix.$name"
			})
			$rows += "  Владелец: $($ownerTypes -join ', ') - обязательный"
			$subUse = $props.SelectSingleNode("md:SubordinationUse", $ns)
			if ($subUse) {
				$subText = switch ($subUse.InnerText) {
					"ToItems" { "элементам" }
					"ToFolders" { "группам" }
					"ToFoldersAndItems" { "группам и элементам" }
					default { $subUse.InnerText }
				}
				$rows += "  Подчинение: $subText"
			}
		}

		# Родитель есть у иерархического объекта и ссылается на него самого.
		$hierNode = $props.SelectSingleNode("md:Hierarchical", $ns)
		if ($hierNode -and $hierNode.InnerText -eq "true") {
			$selfName = $props.SelectSingleNode("md:Name", $ns).InnerText
			$selfRef = if ($mdType -eq "ChartOfCharacteristicTypes") { "ПВХСсылка" } else { "СправочникСсылка" }
			$rows += "  Родитель: $selfRef.$selfName"
		}

		if ($mdType -eq "ChartOfCharacteristicTypes") {
			$valueTypes = Format-TypeList $props.SelectSingleNode("md:Type", $ns)
			if ($valueTypes.Count -gt 1) {
				# Полный состав уводится в разбор по -Name: в обзоре он занимал бы всю строку.
				$rows += "  ТипЗначения: Составной ($($valueTypes.Count))"
				$rows += "  Полный состав типов: -Name ТипЗначения"
			} elseif ($valueTypes.Count -eq 1) {
				$rows += "  ТипЗначения: $($valueTypes[0])"
			}
		}

		if ($mdType -in @("Document", "BusinessProcess", "Task")) {
			$rows += "  Дата - Дата, обязательный"

			# Номер описывается одной строкой: тип, периодичность и способ нумерации - его
			# характеристики, а не отдельные реквизиты.
			$numParts = @()
			$numLen = $props.SelectSingleNode("md:NumberLength", $ns)
			$numType = $props.SelectSingleNode("md:NumberType", $ns)
			if ($numLen -and [int]$numLen.InnerText -gt 0) {
				$numTypeName = if ($numType -and $numType.InnerText -eq "Number") { "Число" } else { "Строка" }
				$numParts += "$numTypeName($($numLen.InnerText))"
			}
			$numPeriod = $props.SelectSingleNode("md:NumberPeriodicity", $ns)
			if ($numPeriod) {
				$periodText = switch ($numPeriod.InnerText) {
					"Year" { "по году" }
					"Quarter" { "по кварталу" }
					"Month" { "по месяцу" }
					"Day" { "по дню" }
					"Nonperiodical" { "непериодический" }
					default { $numPeriod.InnerText }
				}
				$numParts += $periodText
			}
			$autoNum = $props.SelectSingleNode("md:Autonumbering", $ns)
			if ($autoNum -and $autoNum.InnerText -eq "true") { $numParts += "авто" }
			if ($numParts.Count -gt 0) { $rows += "  Номер - $($numParts -join ', ')" }
		}

		if ($rows.Count -gt 0) {
			Out "Стандартные реквизиты:"
			foreach ($row in $rows) { Out $row }
		}
	}

	# --- Mode: brief ---
	if ($Mode -eq "brief") {
		# Подчиненность идет первой строкой: она определяет, как объект вообще заводится.
		$briefOwners = @()
		$briefOwnersNode = $props.SelectSingleNode("md:Owners", $ns)
		if ($briefOwnersNode) {
			foreach ($item in $briefOwnersNode.ChildNodes) {
				if ($item.NodeType -eq 'Element' -and $item.InnerText.Trim()) {
					$briefOwners += ($item.InnerText.Trim() -split '\.')[-1]
				}
			}
		}
		if ($briefOwners.Count -gt 0) { Out "Подчинен: $($briefOwners -join ', ')" }

		# Attributes
		$attrs = @()
		if ($childObjs) { $attrs = @(Get-Attributes $childObjs) }
		if ($attrs.Count -gt 0) {
			$names = ($attrs | ForEach-Object { $_.Name }) -join ", "
			Out "Реквизиты ($($attrs.Count)): $names"
		}

		# Dimensions/Resources for registers
		if ($mdType -match "Register$") {
			$dims = @()
			if ($childObjs) { $dims = @(Get-Attributes $childObjs "Dimension" $true) }
			if ($dims.Count -gt 0) {
				$names = ($dims | ForEach-Object { $_.Name }) -join ", "
				Out "Измерения ($($dims.Count)): $names"
			}
			$res = @()
			if ($childObjs) { $res = @(Get-Attributes $childObjs "Resource") }
			if ($res.Count -gt 0) {
				$names = ($res | ForEach-Object { $_.Name }) -join ", "
				Out "Ресурсы ($($res.Count)): $names"
			}
		}

		# Tabular sections
		$tss = @()
		if ($childObjs) { $tss = @(Get-TabularSections $childObjs) }
		if ($tss.Count -gt 0) {
			$tsParts = $tss | ForEach-Object { "$($_.Name)($($_.ColCount))" }
			Out "ТЧ ($($tss.Count)): $($tsParts -join ', ')"
		}

		# Enum values
		if ($mdType -eq "Enum") {
			$vals = @()
			if ($childObjs) {
				foreach ($ev in $childObjs.SelectNodes("md:EnumValue", $ns)) {
					$ep = $ev.SelectSingleNode("md:Properties", $ns)
					$vals += $ep.SelectSingleNode("md:Name", $ns).InnerText
				}
			}
			if ($vals.Count -gt 0) {
				Out "Значения ($($vals.Count)): $($vals -join ', ')"
			}
		}

		# DefinedType brief
		if ($mdType -eq "DefinedType") {
			$typeNode2 = $props.SelectSingleNode("md:Type", $ns)
			if ($typeNode2) {
				$types = @()
				foreach ($t in $typeNode2.SelectNodes("v8:Type", $ns)) {
					$types += Format-SingleType $t.InnerText $typeNode2
				}
				if ($types.Count -gt 0) {
					Out "Типы ($($types.Count)): $($types -join ', ')"
				}
			}
		}

		# CommonModule brief (same as overview - already compact)
		if ($mdType -eq "CommonModule") {
			$flags = @()
			if ($props.SelectSingleNode("md:Global", $ns).InnerText -eq "true") { $flags += "Глобальный" }
			if ($props.SelectSingleNode("md:Server", $ns).InnerText -eq "true") { $flags += "Сервер" }
			if ($props.SelectSingleNode("md:ServerCall", $ns).InnerText -eq "true") { $flags += "Вызов сервера" }
			if ($props.SelectSingleNode("md:ClientManagedApplication", $ns).InnerText -eq "true") { $flags += "Клиент управляемое" }
			if ($props.SelectSingleNode("md:ClientOrdinaryApplication", $ns).InnerText -eq "true") { $flags += "Обычный клиент" }
			if ($props.SelectSingleNode("md:ExternalConnection", $ns).InnerText -eq "true") { $flags += "Внешнее соединение" }
			if ($props.SelectSingleNode("md:Privileged", $ns).InnerText -eq "true") { $flags += "Привилегированный" }
			$reuse = $props.SelectSingleNode("md:ReturnValuesReuse", $ns)
			if ($reuse -and $reuse.InnerText -ne "DontUse") {
				$reuseRu = if ($reuseMap.ContainsKey($reuse.InnerText)) { $reuseMap[$reuse.InnerText] } else { $reuse.InnerText }
				$flags += "Повторное использование: $reuseRu"
			}
			if ($flags.Count -gt 0) { Out ($flags -join " | ") }
		}

		# ScheduledJob brief (same as overview - already compact)
		if ($mdType -eq "ScheduledJob") {
			$method = $props.SelectSingleNode("md:MethodName", $ns)
			if ($method -and $method.InnerText) {
				$mName = $method.InnerText
				if ($mName -match '^CommonModule\.(.+)$') { $mName = $Matches[1] }
				Out "Метод: $mName"
			}
			$sjParts = @()
			$use = $props.SelectSingleNode("md:Use", $ns)
			$sjParts += "Использование: $(if ($use -and $use.InnerText -eq 'true') { 'да' } else { 'нет' })"
			$predef = $props.SelectSingleNode("md:Predefined", $ns)
			$sjParts += "Предопределенное: $(if ($predef -and $predef.InnerText -eq 'true') { 'да' } else { 'нет' })"
			$restartCnt = $props.SelectSingleNode("md:RestartCountOnFailure", $ns)
			$restartInt = $props.SelectSingleNode("md:RestartIntervalOnFailure", $ns)
			if ($restartCnt -and [int]$restartCnt.InnerText -gt 0) {
				$sjParts += "Перезапуск: $($restartCnt.InnerText) (через $($restartInt.InnerText) сек)"
			}
			Out ($sjParts -join " | ")
		}

		# EventSubscription brief
		if ($mdType -eq "EventSubscription") {
			$esParts = @()
			$event = $props.SelectSingleNode("md:Event", $ns)
			if ($event -and $event.InnerText) {
				$evRu = if ($eventMap.ContainsKey($event.InnerText)) { $eventMap[$event.InnerText] } else { $event.InnerText }
				$esParts += "Событие: $evRu"
			}
			$handler = $props.SelectSingleNode("md:Handler", $ns)
			if ($handler -and $handler.InnerText) {
				$hName = $handler.InnerText
				if ($hName -match '^CommonModule\.(.+)$') { $hName = $Matches[1] }
				$esParts += "Обработчик: $hName"
			}
			$source = $props.SelectSingleNode("md:Source", $ns)
			if ($source) {
				$srcCount = $source.SelectNodes("v8:Type", $ns).Count
				if ($srcCount -gt 0) { $esParts += "Источники: $srcCount" }
			}
			if ($esParts.Count -gt 0) { Out ($esParts -join " | ") }
		}

		# HTTPService brief
		if ($mdType -eq "HTTPService") {
			$rootURL = $props.SelectSingleNode("md:RootURL", $ns)
			if ($rootURL -and $rootURL.InnerText) { Out "Корневой URL: /$($rootURL.InnerText)" }
			if ($childObjs) {
				$endpoints = @(Get-HTTPEndpoints $childObjs)
				if ($endpoints.Count -gt 0) {
					$totalMethods = ($endpoints | ForEach-Object { $_.Methods.Count } | Measure-Object -Sum).Sum
					Out "Шаблоны: $($endpoints.Count) | Методы: $totalMethods"
				}
			}
		}

		# WebService brief
		if ($mdType -eq "WebService") {
			$nsUrl = $props.SelectSingleNode("md:Namespace", $ns)
			if ($nsUrl -and $nsUrl.InnerText) { Out "Пространство имен: $($nsUrl.InnerText)" }
			if ($childObjs) {
				$ops = @(Get-WSOperations $childObjs)
				if ($ops.Count -gt 0) { Out "Операции: $($ops.Count)" }
			}
		}
	} else {
		# --- Mode: overview / full ---

		# Document-specific header properties
		if ($mdType -eq "Document") {
			# Номер описан в блоке стандартных реквизитов ниже: в шапке остается то, что
			# относится к самому документу.
			$posting = $props.SelectSingleNode("md:Posting", $ns)

			$parts = @()
			if ($posting) {
				$parts += "Проведение: $(if ($posting.InnerText -eq 'Allow') { 'да' } else { 'нет' })"
			}
			if ($parts.Count -gt 0) { Out ($parts -join " | ") }
		}

		# Свойства, общие для справочника и плана видов характеристик: иерархия, длины кода
		# и наименования, владельцы. У плана видов характеристик они те же.
		if ($mdType -in @("Catalog", "ChartOfCharacteristicTypes")) {
			$parts = @()
			$hier = $props.SelectSingleNode("md:Hierarchical", $ns)
			if ($hier -and $hier.InnerText -eq "true") {
				$ht = $props.SelectSingleNode("md:HierarchyType", $ns)
				$htText = if ($ht -and $ht.InnerText -eq "HierarchyFoldersAndItems") { "группы и элементы" } else { "элементы" }
				$limitNode = $props.SelectSingleNode("md:LimitLevelCount", $ns)
				$levelNode = $props.SelectSingleNode("md:LevelCount", $ns)
				if ($limitNode -and $limitNode.InnerText -eq "true" -and $levelNode) {
					$htText += ", уровней: $($levelNode.InnerText)"
				} else {
					$htText += ", без ограничения уровней"
				}
				$parts += "Иерархический: $htText"
			}
			$owners = @()
			$ownersNode = $props.SelectSingleNode("md:Owners", $ns)
			if ($ownersNode) {
				foreach ($item in $ownersNode.ChildNodes) {
					if ($item.NodeType -eq 'Element' -and $item.InnerText.Trim()) {
						$owners += $item.InnerText.Trim()
					}
				}
			}
			if ($owners.Count -gt 0) {
				$ownerNames = @($owners | ForEach-Object { ($_ -split '\.')[-1] })
				$parts += "Подчинен: $($ownerNames -join ', ')"
			}
			if ($parts.Count -gt 0) { Out ($parts -join " | ") }
		}

		# Владельцы нужны блоку: у подчиненного справочника это стандартный реквизит.
		Out-StandardAttributes $props $mdType $owners

		# Register-specific header properties
		if ($mdType -match "Register$") {
			$parts = @()
			if ($mdType -eq "InformationRegister") {
				$per = $props.SelectSingleNode("md:InformationRegisterPeriodicity", $ns)
				if ($per) {
					$perRu = if ($periodMap.ContainsKey($per.InnerText)) { $periodMap[$per.InnerText] } else { $per.InnerText }
					$parts += "Периодичность: $perRu"
				}
				$wm = $props.SelectSingleNode("md:WriteMode", $ns)
				if ($wm) {
					$wmRu = if ($writeModeMap.ContainsKey($wm.InnerText)) { $writeModeMap[$wm.InnerText] } else { $wm.InnerText }
					$parts += "Запись: $wmRu"
				}
			}
			if ($mdType -eq "AccumulationRegister") {
				$regKind = $props.SelectSingleNode("md:RegisterType", $ns)
				if ($regKind) {
					$rkRu = switch ($regKind.InnerText) {
						"Balances" { "остатки" }
						"Turnovers" { "обороты" }
						default { $regKind.InnerText }
					}
					$parts += "Вид: $rkRu"
				}
			}
			if ($parts.Count -gt 0) { Out ($parts -join " | ") }
		}

		# Constant-specific: show type
		if ($mdType -eq "Constant") {
			$typeStr = Format-Type $props.SelectSingleNode("md:Type", $ns)
			if ($typeStr) { Out "Тип: $typeStr" }
		}

		# Report-specific: MainDataCompositionSchema
		if ($mdType -eq "Report") {
			$mainDCS = $props.SelectSingleNode("md:MainDataCompositionSchema", $ns)
			if ($mainDCS -and $mainDCS.InnerText) {
				$dcsName = $mainDCS.InnerText
				if ($dcsName -match '\.Template\.(.+)$') { $dcsName = $Matches[1] }
				Out "Основная СКД: $dcsName"
			}
		}

		# DefinedType: show types
		if ($mdType -eq "DefinedType") {
			$typeNode2 = $props.SelectSingleNode("md:Type", $ns)
			if ($typeNode2) {
				$types = @()
				foreach ($t in $typeNode2.SelectNodes("v8:Type", $ns)) {
					$types += Format-SingleType $t.InnerText $typeNode2
				}
				if ($types.Count -gt 0) {
					Out "Типы ($($types.Count)):"
					foreach ($t in $types) { Out "  $t" }
				}
			}
		}

		# CommonModule: show flags
		if ($mdType -eq "CommonModule") {
			$flags = @()
			if ($props.SelectSingleNode("md:Global", $ns).InnerText -eq "true") { $flags += "Глобальный" }
			if ($props.SelectSingleNode("md:Server", $ns).InnerText -eq "true") { $flags += "Сервер" }
			if ($props.SelectSingleNode("md:ServerCall", $ns).InnerText -eq "true") { $flags += "Вызов сервера" }
			if ($props.SelectSingleNode("md:ClientManagedApplication", $ns).InnerText -eq "true") { $flags += "Клиент управляемое" }
			if ($props.SelectSingleNode("md:ClientOrdinaryApplication", $ns).InnerText -eq "true") { $flags += "Обычный клиент" }
			if ($props.SelectSingleNode("md:ExternalConnection", $ns).InnerText -eq "true") { $flags += "Внешнее соединение" }
			if ($props.SelectSingleNode("md:Privileged", $ns).InnerText -eq "true") { $flags += "Привилегированный" }
			$reuse = $props.SelectSingleNode("md:ReturnValuesReuse", $ns)
			if ($reuse -and $reuse.InnerText -ne "DontUse") {
				$reuseRu = if ($reuseMap.ContainsKey($reuse.InnerText)) { $reuseMap[$reuse.InnerText] } else { $reuse.InnerText }
				$flags += "Повторное использование: $reuseRu"
			}
			if ($flags.Count -gt 0) { Out ($flags -join " | ") }
		}

		# ScheduledJob: show method and flags
		if ($mdType -eq "ScheduledJob") {
			$method = $props.SelectSingleNode("md:MethodName", $ns)
			if ($method -and $method.InnerText) {
				$mName = $method.InnerText
				if ($mName -match '^CommonModule\.(.+)$') { $mName = $Matches[1] }
				Out "Метод: $mName"
			}
			$sjParts = @()
			$use = $props.SelectSingleNode("md:Use", $ns)
			$sjParts += "Использование: $(if ($use -and $use.InnerText -eq 'true') { 'да' } else { 'нет' })"
			$predef = $props.SelectSingleNode("md:Predefined", $ns)
			$sjParts += "Предопределенное: $(if ($predef -and $predef.InnerText -eq 'true') { 'да' } else { 'нет' })"
			$restartCnt = $props.SelectSingleNode("md:RestartCountOnFailure", $ns)
			$restartInt = $props.SelectSingleNode("md:RestartIntervalOnFailure", $ns)
			if ($restartCnt -and [int]$restartCnt.InnerText -gt 0) {
				$sjParts += "Перезапуск: $($restartCnt.InnerText) (через $($restartInt.InnerText) сек)"
			}
			Out ($sjParts -join " | ")
		}

		# EventSubscription: show event, handler, sources
		if ($mdType -eq "EventSubscription") {
			$event = $props.SelectSingleNode("md:Event", $ns)
			if ($event -and $event.InnerText) {
				$evRu = if ($eventMap.ContainsKey($event.InnerText)) { $eventMap[$event.InnerText] } else { $event.InnerText }
				Out "Событие: $evRu"
			}
			$handler = $props.SelectSingleNode("md:Handler", $ns)
			if ($handler -and $handler.InnerText) {
				$hName = $handler.InnerText
				if ($hName -match '^CommonModule\.(.+)$') { $hName = $Matches[1] }
				Out "Обработчик: $hName"
			}
			$source = $props.SelectSingleNode("md:Source", $ns)
			if ($source) {
				$srcTypes = @()
				foreach ($t in $source.SelectNodes("v8:Type", $ns)) {
					$srcTypes += Format-SourceType $t.InnerText
				}
				if ($srcTypes.Count -gt 0) {
					if ($Mode -eq "full") {
						Out "Источники ($($srcTypes.Count)):"
						foreach ($s in $srcTypes) { Out "  $s" }
					} else {
						Out "Источники ($($srcTypes.Count))"
					}
				}
			}
		}

		# HTTPService: show root URL and endpoints
		if ($mdType -eq "HTTPService") {
			$rootURL = $props.SelectSingleNode("md:RootURL", $ns)
			if ($rootURL -and $rootURL.InnerText) { Out "Корневой URL: /$($rootURL.InnerText)" }
			if ($childObjs) {
				$endpoints = @(Get-HTTPEndpoints $childObjs)
				if ($endpoints.Count -gt 0) {
					Out ""
					Out "Шаблоны URL ($($endpoints.Count)):"
					foreach ($ep in $endpoints) {
						Out "  $($ep.Template)"
						foreach ($m in $ep.Methods) {
							Out "    $($m.HTTPMethod.PadRight(6)) → $($m.Handler)"
						}
					}
				}
			}
		}

		# WebService: show namespace and operations
		if ($mdType -eq "WebService") {
			$nsUrl = $props.SelectSingleNode("md:Namespace", $ns)
			if ($nsUrl -and $nsUrl.InnerText) { Out "Пространство имен: $($nsUrl.InnerText)" }
			if ($childObjs) {
				$ops = @(Get-WSOperations $childObjs)
				if ($ops.Count -gt 0) {
					Out ""
					Out "Операции ($($ops.Count)):"
					foreach ($op in $ops) {
						Out "  $($op.Name)($($op.Params)) → $($op.ReturnType)"
					}
				}
			}
		}

		# --- Enum values ---
		if ($mdType -eq "Enum" -and $childObjs) {
			$vals = @()
			foreach ($ev in $childObjs.SelectNodes("md:EnumValue", $ns)) {
				$ep = $ev.SelectSingleNode("md:Properties", $ns)
				$vName = $ep.SelectSingleNode("md:Name", $ns).InnerText
				$vSyn = Get-MLText $ep.SelectSingleNode("md:Synonym", $ns)
				$vals += @{ Name=$vName; Synonym=$vSyn }
			}
			if ($vals.Count -gt 0) {
				Out ""
				Out "Значения ($($vals.Count)):"
				$ml = Get-MaxNameLen $vals
				foreach ($v in $vals) {
					$padded = $v.Name.PadRight($ml)
					$synText = if ($v.Synonym -and $v.Synonym -ne $v.Name) { "`"$($v.Synonym)`"" } else { "" }
					Out "  $padded $synText"
				}
			}
		}

		# --- Dimensions (registers) ---
		if ($mdType -match "Register$" -and $childObjs) {
			$dims = @(Get-Attributes $childObjs "Dimension" $true)
			if ($dims.Count -gt 0) {
				Out ""
				Out "Измерения ($($dims.Count)):"
				$ml = Get-MaxNameLen $dims
				foreach ($d in $dims) { Out (Format-AttrLine $d $ml) }
			}
		}

		# --- Resources (registers) ---
		if ($mdType -match "Register$" -and $childObjs) {
			$res = @(Get-Attributes $childObjs "Resource")
			if ($res.Count -gt 0) {
				Out ""
				Out "Ресурсы ($($res.Count)):"
				$ml = Get-MaxNameLen $res
				foreach ($r in $res) { Out (Format-AttrLine $r $ml) }
			}
		}

		# --- Attributes ---
		if ($childObjs -and $mdType -ne "Enum") {
			$attrs = @(Get-Attributes $childObjs)
			if ($attrs.Count -gt 0) {
				Out ""
				Out "Реквизиты ($($attrs.Count)):"
				$sorted = Sort-AttrsRefFirst $attrs
				$ml = Get-MaxNameLen $sorted
				foreach ($a in $sorted) { Out (Format-AttrLine $a $ml) }
			}
		}

		# --- Tabular sections ---
		if ($childObjs -and $mdType -ne "Enum") {
			$tss = @(Get-TabularSections $childObjs)
			if ($tss.Count -gt 0) {
				if ($Mode -eq "full") {
					foreach ($ts in $tss) {
						Out ""
						Out "ТЧ $($ts.Name) ($($ts.ColCount) $(Decline-Cols $ts.ColCount)):"
						if ($ts.ColCount -gt 0) {
							$sortedCols = Sort-AttrsRefFirst $ts.Columns
							$ml = Get-MaxNameLen $sortedCols
							foreach ($c in $sortedCols) { Out (Format-AttrLine $c $ml) }
						}
					}
				} else {
					# overview - just names with column counts
					Out ""
					$tsParts = $tss | ForEach-Object { "$($_.Name)($($_.ColCount))" }
					Out "ТЧ ($($tss.Count)): $($tsParts -join ', ')"
				}
			}
		}

		# Forms/Templates/Commands in overview for Reports & DataProcessors
		if ($Mode -eq "overview" -and $childObjs -and ($mdType -eq "Report" -or $mdType -eq "DataProcessor")) {
			$forms = @(Get-SimpleChildren $childObjs "Form")
			if ($forms.Count -gt 0) { Out "Формы: $($forms -join ', ')" }
			$templates = @(Get-SimpleChildren $childObjs "Template")
			if ($templates.Count -gt 0) { Out "Макеты: $($templates -join ', ')" }
			$commands = @(Get-SimpleChildren $childObjs "Command")
			if ($commands.Count -gt 0) { Out "Команды: $($commands -join ', ')" }
		}

		# --- Full mode: additional sections ---
		if ($Mode -eq "full" -and $childObjs) {
			# Register records (documents)
			if ($mdType -eq "Document") {
				$regRecs = @()
				foreach ($item in $props.SelectNodes("md:RegisterRecords/xr:Item", $ns)) {
					$raw = $item.InnerText
					if ($raw -match '^(\w+)\.(.+)$') {
						$prefix = $Matches[1]
						$rname = $Matches[2]
						$short = if ($regTypeMap.ContainsKey($prefix)) { $regTypeMap[$prefix] } else { $prefix }
						$regRecs += "$short.$rname"
					} else {
						$regRecs += $raw
					}
				}
				if ($regRecs.Count -gt 0) {
					Out ""
					Out "Движения ($($regRecs.Count)): $($regRecs -join ', ')"
				}

				# BasedOn
				$basedOn = @()
				foreach ($item in $props.SelectNodes("md:BasedOn/xr:Item", $ns)) {
					$raw = $item.InnerText
					if ($raw -match '^\w+\.(.+)$') { $basedOn += $Matches[1] } else { $basedOn += $raw }
				}
				if ($basedOn.Count -gt 0) {
					Out "Ввод на основании: $($basedOn -join ', ')"
				}
			}

			# Forms
			$forms = @(Get-SimpleChildren $childObjs "Form")
			if ($forms.Count -gt 0) {
				Out "Формы: $($forms -join ', ')"
			}

			# Templates
			$templates = @(Get-SimpleChildren $childObjs "Template")
			if ($templates.Count -gt 0) {
				Out "Макеты: $($templates -join ', ')"
			}

			# Commands
			$commands = @(Get-SimpleChildren $childObjs "Command")
			if ($commands.Count -gt 0) {
				Out "Команды: $($commands -join ', ')"
			}
		}
	}
}

# --- Pagination and output ---
$totalLines = $script:lines.Count
$outLines = $script:lines

if ($Offset -gt 0) {
	if ($Offset -ge $totalLines) {
		Write-Host "[INFO] Offset $Offset exceeds total lines ($totalLines). Nothing to show."
		exit 0
	}
	$outLines = $outLines[$Offset..($totalLines - 1)]
}

if ($Limit -gt 0 -and $outLines.Count -gt $Limit) {
	$shown = $outLines[0..($Limit - 1)]
	$remaining = $totalLines - $Offset - $Limit
	$shown += ""
	$shown += "[ОБРЕЗАНО] Показано $Limit из $totalLines строк. Используйте -Offset $($Offset + $Limit) для продолжения."
	$outLines = $shown
}

if ($OutFile) {
	if (-not [System.IO.Path]::IsPathRooted($OutFile)) {
		$OutFile = Join-Path (Get-Location).Path $OutFile
	}
	$utf8 = New-Object System.Text.UTF8Encoding($true)
	[System.IO.File]::WriteAllLines($OutFile, $outLines, $utf8)
	Write-Host "Output written to $OutFile"
} else {
	foreach ($l in $outLines) { Write-Host $l }
}
