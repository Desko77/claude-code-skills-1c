# config-index v1.0 - Build a JSON index of a 1C configuration dump
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)][string]$ConfigPath,
	[string]$OutFile,
	[switch]$Detailed
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Type -> directory map (canonical, docs/1c-configuration-spec.md) ---

$childTypeDirMap = @{
	"Language"="Languages"; "Subsystem"="Subsystems"; "StyleItem"="StyleItems"; "Style"="Styles"
	"CommonPicture"="CommonPictures"; "SessionParameter"="SessionParameters"; "Role"="Roles"
	"CommonTemplate"="CommonTemplates"; "FilterCriterion"="FilterCriteria"; "CommonModule"="CommonModules"
	"CommonAttribute"="CommonAttributes"; "ExchangePlan"="ExchangePlans"; "XDTOPackage"="XDTOPackages"
	"WebService"="WebServices"; "HTTPService"="HTTPServices"; "WSReference"="WSReferences"
	"EventSubscription"="EventSubscriptions"; "ScheduledJob"="ScheduledJobs"
	"SettingsStorage"="SettingsStorages"; "FunctionalOption"="FunctionalOptions"
	"FunctionalOptionsParameter"="FunctionalOptionsParameters"; "DefinedType"="DefinedTypes"
	"CommonCommand"="CommonCommands"; "CommandGroup"="CommandGroups"; "Constant"="Constants"
	"CommonForm"="CommonForms"; "Catalog"="Catalogs"; "Document"="Documents"
	"DocumentNumerator"="DocumentNumerators"; "Sequence"="Sequences"
	"DocumentJournal"="DocumentJournals"; "Enum"="Enums"; "Report"="Reports"
	"DataProcessor"="DataProcessors"; "InformationRegister"="InformationRegisters"
	"AccumulationRegister"="AccumulationRegisters"
	"ChartOfCharacteristicTypes"="ChartsOfCharacteristicTypes"
	"ChartOfAccounts"="ChartsOfAccounts"; "AccountingRegister"="AccountingRegisters"
	"ChartOfCalculationTypes"="ChartsOfCalculationTypes"
	"CalculationRegister"="CalculationRegisters"
	"BusinessProcess"="BusinessProcesses"; "Task"="Tasks"
	"IntegrationService"="IntegrationServices"
}

# Child elements of ChildObjects that carry a name and a type, grouped by the index bucket
# they fill. Everything not listed here is recorded by name only or ignored on purpose.
$idxTypedBuckets = @{
	"Attribute"="attributes"; "Dimension"="dimensions"; "Resource"="resources"
	"AddressingAttribute"="addressingAttributes"; "AccountingFlag"="accountingFlags"
	"ExtDimensionAccountingFlag"="extDimensionAccountingFlags"
}
$idxNamedBuckets = @{
	"Form"="forms"; "Template"="templates"; "Command"="commands"; "Subsystem"="subsystems"
	"EnumValue"="enumValues"; "Recalculation"="recalculations"; "Column"="columns"
	"Operation"="operations"; "URLTemplate"="urlTemplates"
}
# Object properties worth carrying into the index: later checks read them, the rest is noise.
$idxKeptProps = @(
	"Hierarchical", "HierarchyType", "CodeLength", "DescriptionLength", "Periodicity",
	"RegisterType", "WriteMode", "InformationRegisterPeriodicity", "ObjectBelonging",
	"Global", "Server", "ClientManagedApplication", "ClientOrdinaryApplication",
	"ExternalConnection", "ServerCall", "Privileged", "ReturnValuesReuse"
)

# --- Output infrastructure ---

$script:output = New-Object System.Text.StringBuilder 4096
function Out-Line([string]$msg) { $script:output.AppendLine($msg) | Out-Null }

# --- XML helpers (navigate by LocalName: the dump uses many prefixes) ---

function Get-IdxChild($node, [string]$localName) {
	if ($null -eq $node) { return $null }
	foreach ($c in $node.ChildNodes) {
		if ($c.NodeType -eq [System.Xml.XmlNodeType]::Element -and $c.LocalName -eq $localName) { return $c }
	}
	return $null
}

function Get-IdxChildren($node, [string]$localName) {
	$found = [System.Collections.ArrayList]::new()
	if ($null -eq $node) { return ,$found }
	foreach ($c in $node.ChildNodes) {
		if ($c.NodeType -eq [System.Xml.XmlNodeType]::Element -and $c.LocalName -eq $localName) { [void]$found.Add($c) }
	}
	return ,$found
}

# Свойств у объекта под сотню, а достать из них надо два десятка. Без карты каждое обращение
# перебирало бы весь список заново: на конфигурации в тысячи объектов это минута против секунд.
function Get-IdxMap($node) {
	$map = @{}
	if ($null -eq $node) { return $map }
	foreach ($c in $node.ChildNodes) {
		$ln = $c.LocalName
		if (-not $map.ContainsKey($ln)) { $map[$ln] = $c }
	}
	return $map
}

function Get-IdxMapText($map, [string]$localName) {
	$c = $map[$localName]
	if ($null -eq $c) { return "" }
	return $c.InnerText
}

function Get-IdxText($node, [string]$localName) {
	$c = Get-IdxChild $node $localName
	if ($null -eq $c) { return "" }
	return $c.InnerText
}

# Type list of an attribute-like node. Namespace prefixes are dropped: only the local part
# carries meaning ("d5p1:CatalogRef.X" -> "CatalogRef.X", "xs:string" -> "string").
# The " + " form comes from DefinedType written by meta-compile as one string; the platform
# writes one element per type. Both are accepted.
function Get-IdxTypes($propsMap) {
	$types = [System.Collections.ArrayList]::new()
	$holder = $propsMap["Type"]
	if ($null -eq $holder) { $holder = $propsMap["ValueType"] }
	if ($null -eq $holder) { return ,$types }
	foreach ($c in $holder.ChildNodes) {
		if ($c.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
		if ($c.LocalName -ne "Type" -and $c.LocalName -ne "TypeSet") { continue }
		foreach ($part in ($c.InnerText -split " \+ ")) {
			$t = $part.Trim()
			if ($t -eq "") { continue }
			$colon = $t.IndexOf(":")
			if ($colon -ge 0) { $t = $t.Substring($colon + 1) }
			[void]$types.Add($t)
		}
	}
	return ,$types
}

# Литерал ИЛИ комментарий: что началось раньше, то и поглощает второе. Закрывающая кавычка
# необязательна - незакрытый литерал гасит остаток файла.
$idxNoiseRe = [regex]'"(?:[^"]|"")*"?|//[^\n]*'

# Гасит строковые литералы и комментарии ЗА ОДИН проход, сохраняя длину текста.
#
# Гасить их по очереди неверно в обе стороны, и обе ошибки встречаются в типовом коде: литералы
# первыми - нечетная кавычка в комментарии открывает мнимый литерал и съедает следующие за ним
# объявления методов; комментарии первыми - "TCP://" в литерале обрубит строку. Кто из двух начался
# раньше, решает чередование в самом образце: движок идет слева направо, и внутри уже начавшегося
# литерала двойной слеш ему не виден.
#
# Длина сохраняется, переводы строк внутри литерала тоже: вызывающий код ходит по тексту по
# позициям, а литерал в BSL занимает несколько строк.
function Get-IdxBlankNoise([string]$text) {
	return $idxNoiseRe.Replace($text, {
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

# --- BSL: exported methods of a module ---
# Comments are blanked together with string literals. A commented-out procedure would otherwise
# become a phantom export - and a phantom export only makes a later check MISS a call, never
# invent one.
function Get-IdxExports([string]$text) {
	$names = [System.Collections.ArrayList]::new()
	$src = (Get-IdxBlankNoise $text) + "`n"
	$re = [regex]"(?im)^[ \t]*(?:(?:Асинх|Async)[ \t]+)?(?:Процедура|Функция|Procedure|Function)[ \t]+([A-Za-z_\u0410-\u044F\u0401\u0451][A-Za-z0-9_\u0410-\u044F\u0401\u0451]*)[ \t]*\("
	foreach ($m in $re.Matches($src)) {
		# Walk past the parameter list counting nesting: default values contain parens too.
		$i = $m.Index + $m.Length
		$depth = 1
		while ($i -lt $src.Length -and $depth -gt 0) {
			if ($src[$i] -eq "(") { $depth++ }
			elseif ($src[$i] -eq ")") { $depth-- }
			$i++
		}
		if ($depth -ne 0) { continue }
		$tailEnd = [Math]::Min($src.Length, $i + 40)
		$tail = $src.Substring($i, $tailEnd - $i)
		# Экспорт может стоять на следующей строке - список параметров нередко переносят.
		if ($tail -match "^\s*(Экспорт|Export)\b") { [void]$names.Add($m.Groups[1].Value) }
	}
	return ,$names
}

# Properties holding a list of <xr:Item> references to other objects.
$idxRefListProps = @("Content", "RegisterRecords", "Owners", "BasedOn", "Registers")

# Стандартные реквизиты объект несет сам: <xr:StandardAttribute name="Description">. Читаем их
# из выгрузки, а не держим свою таблицу - таблица разошлась бы с платформой молча.
function Get-IdxStandardNames($holder) {
	$names = [System.Collections.ArrayList]::new()
	if ($null -eq $holder) { return ,$names }
	foreach ($c in $holder.ChildNodes) {
		if ($c.LocalName -ne "StandardAttribute") { continue }
		$n = $c.GetAttribute("name")
		if ($n -ne "") { [void]$names.Add($n) }
	}
	return ,$names
}

function Get-IdxRefList($propsMap, [string]$propName) {
	$refs = [System.Collections.ArrayList]::new()
	$holder = $propsMap[$propName]
	if ($null -eq $holder) { return ,$refs }
	foreach ($item in (Get-IdxChildren $holder "Item")) {
		$v = $item.InnerText.Trim()
		if ($v -ne "") { [void]$refs.Add($v) }
	}
	return ,$refs
}

# --- One metadata object -> index entry ---

function Read-IdxObject([string]$path, [string]$kind, $typesSink) {
	$doc = New-Object System.Xml.XmlDocument
	$doc.PreserveWhitespace = $false
	$doc.Load($path)
	$objNode = Get-IdxChild $doc.DocumentElement $kind
	if ($null -eq $objNode) { return $null }

	$internal = Get-IdxChild $objNode "InternalInfo"
	foreach ($gt in (Get-IdxChildren $internal "GeneratedType")) {
		$gtName = $gt.GetAttribute("name")
		if ($gtName -ne "") { [void]$typesSink.Add($gtName) }
	}

	$propsMap = Get-IdxMap (Get-IdxChild $objNode "Properties")
	$entry = [ordered]@{}
	$entry["kind"] = $kind
	$entry["name"] = (Get-IdxMapText $propsMap "Name")

	$typed = [ordered]@{}
	$named = [ordered]@{}
	foreach ($b in $idxTypedBuckets.Values) { $typed[$b] = [ordered]@{} }
	foreach ($b in $idxNamedBuckets.Values) { $named[$b] = [System.Collections.ArrayList]::new() }
	$tabular = [ordered]@{}

	$children = Get-IdxChild $objNode "ChildObjects"
	if ($null -ne $children) {
		foreach ($c in $children.ChildNodes) {
			if ($c.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
			$cPropsNode = Get-IdxChild $c "Properties"
			$cProps = Get-IdxMap $cPropsNode
			$cName = Get-IdxMapText $cProps "Name"
			if ($cName -eq "" -and $null -eq $cPropsNode) { $cName = $c.InnerText.Trim() }
			if ($cName -eq "") { continue }
			if ($idxTypedBuckets.ContainsKey($c.LocalName)) {
				$typed[$idxTypedBuckets[$c.LocalName]][$cName] = (Get-IdxTypes $cProps)
			}
			elseif ($idxNamedBuckets.ContainsKey($c.LocalName)) {
				[void]$named[$idxNamedBuckets[$c.LocalName]].Add($cName)
			}
			elseif ($c.LocalName -eq "TabularSection") {
				$tsAttrs = [ordered]@{}
				$tsChildren = Get-IdxChild $c "ChildObjects"
				foreach ($a in (Get-IdxChildren $tsChildren "Attribute")) {
					$aProps = Get-IdxMap (Get-IdxChild $a "Properties")
					$aName = Get-IdxMapText $aProps "Name"
					if ($aName -ne "") { $tsAttrs[$aName] = (Get-IdxTypes $aProps) }
				}
				$tsEntry = [ordered]@{}
				$tsEntry["attributes"] = $tsAttrs
				$tsStd = Get-IdxStandardNames $cProps["StandardAttributes"]
				if ($tsStd.Count) { $tsEntry["standardAttributes"] = $tsStd }
				$tabular[$cName] = $tsEntry
			}
		}
	}

	# Only non-empty buckets are written: an index of thousands of objects should not carry
	# thousands of empty braces.
	foreach ($b in @("attributes")) { if ($typed[$b].Count) { $entry[$b] = $typed[$b] } }
	$std = Get-IdxStandardNames $propsMap["StandardAttributes"]
	if ($std.Count) { $entry["standardAttributes"] = $std }
	if ($tabular.Count) { $entry["tabularSections"] = $tabular }
	$stdTabular = [ordered]@{}
	foreach ($sts in (Get-IdxChildren $propsMap["StandardTabularSections"] "StandardTabularSection")) {
		$stsName = $sts.GetAttribute("name")
		if ($stsName -eq "") { continue }
		$stdTabular[$stsName] = (Get-IdxStandardNames (Get-IdxChild $sts "StandardAttributes"))
	}
	if ($stdTabular.Count) { $entry["standardTabularSections"] = $stdTabular }
	foreach ($b in @("dimensions", "resources", "addressingAttributes", "accountingFlags", "extDimensionAccountingFlags")) {
		if ($typed[$b].Count) { $entry[$b] = $typed[$b] }
	}
	foreach ($b in @("enumValues", "forms", "templates", "commands", "subsystems", "recalculations", "columns", "operations", "urlTemplates")) {
		if ($named[$b].Count) { $entry[$b] = $named[$b] }
	}

	$valueTypes = Get-IdxTypes $propsMap
	if ($valueTypes.Count) { $entry["valueType"] = $valueTypes }

	$flags = [ordered]@{}
	foreach ($p in $idxKeptProps) {
		$v = $propsMap[$p]
		if ($null -ne $v -and $v.InnerText -ne "") { $flags[$p] = $v.InnerText }
	}
	if ($flags.Count) { $entry["props"] = $flags }

	$refs = [ordered]@{}
	foreach ($p in $idxRefListProps) {
		$list = Get-IdxRefList $propsMap $p
		if ($list.Count) { $refs[$p] = $list }
	}
	if ($refs.Count) { $entry["refs"] = $refs }

	return $entry
}

# --- Custom JSON serializer: predictable on PS 5.1, raw non-ASCII, 2-space indent ---

function ConvertTo-JsonEscaped([string]$s) {
	$sb = New-Object System.Text.StringBuilder
	foreach ($ch in $s.ToCharArray()) {
		$code = [int]$ch
		if ($ch -eq '"') { [void]$sb.Append('\"') }
		elseif ($ch -eq '\') { [void]$sb.Append('\\') }
		elseif ($code -eq 8) { [void]$sb.Append('\b') }
		elseif ($code -eq 12) { [void]$sb.Append('\f') }
		elseif ($code -eq 10) { [void]$sb.Append('\n') }
		elseif ($code -eq 13) { [void]$sb.Append('\r') }
		elseif ($code -eq 9) { [void]$sb.Append('\t') }
		elseif ($code -lt 32) { [void]$sb.Append('\u' + $code.ToString("x4")) }
		else { [void]$sb.Append($ch) }
	}
	return $sb.ToString()
}

function ConvertTo-JsonText($value, [string]$indent) {
	if ($null -eq $value) { return "null" }
	if ($value -is [bool]) {
		if ($value) { return "true" } else { return "false" }
	}
	if (($value -is [int]) -or ($value -is [long]) -or ($value -is [double]) -or ($value -is [decimal])) {
		return $value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
	}
	if ($value -is [System.Collections.IDictionary]) {
		if ($value.Count -eq 0) { return "{}" }
		$childIndent = $indent + "  "
		$parts = @()
		foreach ($k in $value.Keys) {
			$parts += ($childIndent + '"' + (ConvertTo-JsonEscaped ([string]$k)) + '": ' + (ConvertTo-JsonText $value[$k] $childIndent))
		}
		return "{`n" + ($parts -join ",`n") + "`n" + $indent + "}"
	}
	if (($value -is [System.Collections.IEnumerable]) -and ($value -isnot [string])) {
		$items = @($value)
		if ($items.Count -eq 0) { return "[]" }
		$childIndent = $indent + "  "
		$parts = @()
		foreach ($it in $items) {
			$parts += ($childIndent + (ConvertTo-JsonText $it $childIndent))
		}
		return "[`n" + ($parts -join ",`n") + "`n" + $indent + "]"
	}
	return '"' + (ConvertTo-JsonEscaped ([string]$value)) + '"'
}

# --- Resolve the configuration root ---

if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
	$ConfigPath = Join-Path (Get-Location).Path $ConfigPath
}
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
	$ConfigPath = [System.IO.Path]::GetDirectoryName($ConfigPath)
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Container)) {
	[Console]::Error.WriteLine("Configuration directory not found: " + $ConfigPath)
	exit 1
}
$configRoot = (Resolve-Path -LiteralPath $ConfigPath).Path
$configXml = Join-Path $configRoot "Configuration.xml"
if (-not (Test-Path -LiteralPath $configXml -PathType Leaf)) {
	[Console]::Error.WriteLine("Configuration.xml not found in: " + $configRoot)
	exit 1
}

$started = Get-Date

# --- Configuration.xml: identity and the declared object list ---

$cfgDoc = New-Object System.Xml.XmlDocument
$cfgDoc.PreserveWhitespace = $false
$cfgDoc.Load($configXml)
$cfgNode = Get-IdxChild $cfgDoc.DocumentElement "Configuration"
if ($null -eq $cfgNode) {
	[Console]::Error.WriteLine("Configuration.xml has no <Configuration> element")
	exit 1
}
$cfgProps = Get-IdxChild $cfgNode "Properties"
$extPurpose = Get-IdxText $cfgProps "ConfigurationExtensionPurpose"

$index = [ordered]@{}
$index["format"] = 1
if ($extPurpose -ne "") { $index["kind"] = "extension" } else { $index["kind"] = "configuration" }
$index["name"] = (Get-IdxText $cfgProps "Name")
$index["version"] = (Get-IdxText $cfgProps "Version")
if ($extPurpose -ne "") {
	$index["extensionPurpose"] = $extPurpose
	$index["namePrefix"] = (Get-IdxText $cfgProps "NamePrefix")
}

$declared = [ordered]@{}
$cfgChildren = Get-IdxChild $cfgNode "ChildObjects"
if ($null -ne $cfgChildren) {
	foreach ($c in $cfgChildren.ChildNodes) {
		if ($c.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
		$n = $c.InnerText.Trim()
		if ($n -eq "") { continue }
		if (-not $declared.Contains($c.LocalName)) { $declared[$c.LocalName] = [System.Collections.ArrayList]::new() }
		[void]$declared[$c.LocalName].Add($n)
	}
}
$index["declared"] = $declared

# --- Walk the declared objects ---

$script:objects = [ordered]@{}
$script:allTypes = [System.Collections.ArrayList]::new()
$script:missing = [System.Collections.ArrayList]::new()
$script:fileCount = 0
$unknownKinds = [System.Collections.ArrayList]::new()
$commonModules = [ordered]@{}

# Subsystems nest: Subsystems/Родитель/Subsystems/Ребенок.xml, и ребенок объявлен в ChildObjects
# родителя. Ключ несет весь путь, потому что так подсистема адресуется во всей конфигурации.
function Add-IdxSubsystems([string]$dir, [string]$prefix, $names) {
	foreach ($sub in $names) {
		$file = [System.IO.Path]::Combine($dir, $sub + ".xml")
		$key = $prefix + "Subsystem." + $sub
		if (-not [System.IO.File]::Exists($file)) {
			[void]$script:missing.Add($key)
			continue
		}
		$entry = Read-IdxObject $file "Subsystem" $script:allTypes
		$script:fileCount++
		if ($null -eq $entry) { continue }
		$script:objects[$key] = $entry
		$nested = $entry["subsystems"]
		if ($null -ne $nested -and $nested.Count) {
			Add-IdxSubsystems ([System.IO.Path]::Combine($dir, $sub, "Subsystems")) ($key + ".") $nested
		}
	}
}

foreach ($kind in $declared.Keys) {
	if ($kind -eq "Language") { continue }
	if (-not $childTypeDirMap.ContainsKey($kind)) {
		[void]$unknownKinds.Add($kind)
		continue
	}
	$dir = Join-Path $configRoot $childTypeDirMap[$kind]
	if ($kind -eq "Subsystem") {
		Add-IdxSubsystems $dir "" $declared[$kind]
		continue
	}
	foreach ($name in $declared[$kind]) {
		$file = [System.IO.Path]::Combine($dir, $name + ".xml")
		$key = $kind + "." + $name
		if (-not [System.IO.File]::Exists($file)) {
			[void]$script:missing.Add($key)
			continue
		}
		$entry = Read-IdxObject $file $kind $script:allTypes
		$script:fileCount++
		if ($null -eq $entry) { continue }
		$script:objects[$key] = $entry
		if ($kind -eq "CommonModule") {
			$modFile = [System.IO.Path]::Combine($dir, $name, "Ext", "Module.bsl")
			$mod = [ordered]@{}
			if ([System.IO.File]::Exists($modFile)) {
				$text = [System.IO.File]::ReadAllText($modFile, [System.Text.Encoding]::UTF8)
				$mod["exported"] = (Get-IdxExports $text)
			} else {
				$mod["exported"] = @()
				$mod["moduleMissing"] = $true
			}
			$commonModules[$name] = $mod
		}
	}
}

$index["objects"] = $script:objects
$index["types"] = $script:allTypes
if ($commonModules.Count) { $index["commonModules"] = $commonModules }
if ($script:missing.Count) { $index["missing"] = $script:missing }
if ($unknownKinds.Count) { $index["unknownKinds"] = $unknownKinds }

$json = (ConvertTo-JsonText $index "") + "`n"

$elapsed = [int]((Get-Date) - $started).TotalMilliseconds
Out-Line ("[OK]    Индекс собран: объектов " + $script:objects.Count + ", типов " + $script:allTypes.Count + ", файлов прочитано " + $script:fileCount)
if ($commonModules.Count) { Out-Line ("[OK]    Общих модулей: " + $commonModules.Count) }
if ($script:missing.Count) { Out-Line ("[WARN]  Объявлено в Configuration.xml, но файла нет: " + $script:missing.Count) }
if ($unknownKinds.Count) { Out-Line ("[WARN]  Неизвестные типы в ChildObjects: " + ($unknownKinds -join ", ")) }
if ($Detailed) {
	foreach ($m in $script:missing) { Out-Line ("        нет файла: " + $m) }
	Out-Line ("[INFO]  Время сборки, мс: " + $elapsed)
}

if ($OutFile) {
	if (-not [System.IO.Path]::IsPathRooted($OutFile)) { $OutFile = Join-Path (Get-Location).Path $OutFile }
	$outDir = [System.IO.Path]::GetDirectoryName($OutFile)
	if ($outDir -and -not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
	[System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding $false))
	Out-Line ("[INFO]  Записан: " + $OutFile)
	Write-Host $script:output.ToString().TrimEnd()
} else {
	Write-Host $json.TrimEnd()
}
exit 0
