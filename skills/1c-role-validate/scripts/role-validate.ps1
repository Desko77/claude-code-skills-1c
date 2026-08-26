# role-validate v1.1 — Validate 1C role structure
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$RightsPath,

	[string]$OutFile,

	[switch]$Detailed,

	[int]$MaxErrors = 30,

	[string]$IndexPath
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- 1. Known rights per object type ---

# Типы метаданных, у которых прав в роли нет вовсе (таблица типов, docs/1c-configuration-spec.md).
# Блок прав на такой тип платформа не примет, поэтому это ошибка, а не предупреждение.
$script:typesWithoutRights = @(
	"CommandGroup","CommonModule","CommonPicture","CommonTemplate","DefinedType",
	"DocumentNumerator","Enum","EventSubscription","FunctionalOption",
	"FunctionalOptionsParameter","Language","Role","ScheduledJob","SettingsStorage",
	"Style","StyleItem","WSReference","XDTOPackage"
)

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
	"CalculationRegister" = @("Read","View")
	"Constant" = @(
		"Read","Update","View","Edit",
		"ReadDataHistory","ViewDataHistory","UpdateDataHistory",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment",
		"EditDataHistoryVersionComment","SwitchToDataHistoryVersion"
	)
	"ChartOfAccounts" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData",
		"ReadDataHistory","ReadDataHistoryOfMissingData",
		"UpdateDataHistory","UpdateDataHistoryOfMissingData",
		"UpdateDataHistorySettings","UpdateDataHistoryVersionComment"
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
		"InteractiveDelete",
		"InteractiveDeletePredefinedData","InteractiveSetDeletionMarkPredefinedData",
		"InteractiveClearDeletionMarkPredefinedData","InteractiveDeleteMarkedPredefinedData"
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
		"InteractiveDelete","InteractiveActivate","InteractiveStart"
	)
	"Task" = @(
		"Read","Insert","Update","Delete","View","Edit","InputByString",
		"Execute","InteractiveInsert","InteractiveSetDeletionMark","InteractiveClearDeletionMark",
		"InteractiveDelete","InteractiveActivate","InteractiveExecute"
	)
	"DataProcessor" = @("Use","View")
	"Report" = @("Use","View")
	"CommonForm" = @("View")
	"CommonCommand" = @("View")
	"Subsystem" = @("View")
	"FilterCriterion" = @("View")
	"DocumentJournal" = @("Read","View")
	"Sequence" = @("Read","Update")
	"WebService" = @("Use")
	"HTTPService" = @("Use")
	"IntegrationService" = @("Use")
	"SessionParameter" = @("Get","Set")
	"CommonAttribute" = @("View","Edit")
}

$script:nestedRights = @("View","Edit")

# Права вложенных объектов зависят от вида: у операции веб-сервиса и метода HTTP-сервиса это
# Use, у реквизита - View и Edit, у перерасчета - Read и Update. Карта совпадает с role-compile.
$script:nestedRightsByKind = @{
	"Attribute" = @("View","Edit")
	"TabularSection" = @("View","Edit")
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

# Типы, права которых не замерены: имя признается, набор прав не проверяется.
$script:typesRightsNotChecked = @("ExternalDataSource")
$script:channelRights = @("Use")
$script:commandRights = @("View")

# --- 2. Output helpers ---

$script:errors = 0
$script:warnings = 0
$script:okCount = 0
$script:stopped = $false
$script:output = New-Object System.Text.StringBuilder 8192

function Out-Line {
	param([string]$msg)
	$script:output.AppendLine($msg) | Out-Null
}

function Report-OK {
	param([string]$msg)
	$script:okCount++
	if ($Detailed) { Out-Line "[OK]    $msg" }
}

function Report-Error {
	param([string]$msg)
	$script:errors++
	Out-Line "[ERROR] $msg"
	if ($script:errors -ge $MaxErrors) {
		$script:stopped = $true
	}
}

function Report-Warn {
	param([string]$msg)
	$script:warnings++
	Out-Line "[WARN]  $msg"
}

function Get-ObjectType {
	param([string]$name)
	$dotIdx = $name.IndexOf(".")
	if ($dotIdx -lt 0) { return $name }
	return $name.Substring(0, $dotIdx)
}

function Is-NestedObject {
	param([string]$name)
	return ($name.Split(".").Count -ge 3)
}

function Find-Similar {
	param([string]$needle, [string[]]$haystack)
	$result = @($haystack | Where-Object {
		$_ -like "*$needle*" -or $needle -like "*$_*"
	})
	if ($result.Count -gt 3) { $result = $result[0..2] }
	return $result
}

# --- Resolve path ---
if (-not [System.IO.Path]::IsPathRooted($RightsPath)) {
	$RightsPath = Join-Path (Get-Location).Path $RightsPath
}
# A: Directory → Ext/Rights.xml
if (Test-Path $RightsPath -PathType Container) {
	$RightsPath = Join-Path (Join-Path $RightsPath "Ext") "Rights.xml"
}
# B1: Missing Ext/ (e.g. Roles/МояРоль/Rights.xml → Roles/МояРоль/Ext/Rights.xml)
if (-not (Test-Path $RightsPath)) {
	$fn = [System.IO.Path]::GetFileName($RightsPath)
	if ($fn -eq "Rights.xml") {
		$c = Join-Path (Join-Path (Split-Path $RightsPath) "Ext") $fn
		if (Test-Path $c) { $RightsPath = $c }
	}
}

# --- 3. Validate Rights.xml ---

if (-not (Test-Path $RightsPath)) {
	Report-Error "File not found: $RightsPath"
	$result = $script:output.ToString()
	Write-Host $result
	if ($OutFile) {
		$outPath = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
		$outDir = [System.IO.Path]::GetDirectoryName($outPath)
		if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
		$utf8Bom = New-Object System.Text.UTF8Encoding $true
		[System.IO.File]::WriteAllText($outPath, $result, $utf8Bom)
		Write-Host "Written to: $outPath"
	}
	exit 1
}

# Auto-detect metadata: Roles/Name/Ext/Rights.xml → Roles/Name.xml
$resolvedRights = (Resolve-Path $RightsPath).Path
$extDir = Split-Path $resolvedRights -Parent
$roleDir = Split-Path $extDir -Parent
$rolesDir = Split-Path $roleDir -Parent
$roleDirName = Split-Path $roleDir -Leaf
$MetadataPath = Join-Path $rolesDir "$roleDirName.xml"

# 3a. Parse XML
try {
	[xml]$xml = Get-Content -Path $RightsPath -Encoding UTF8
	Report-OK "XML well-formed"
} catch {
	Report-Error "XML parse error: $($_.Exception.Message)"
	$result = $script:output.ToString()
	Write-Host $result
	if ($OutFile) {
		$outPath = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
		$outDir = [System.IO.Path]::GetDirectoryName($outPath)
		if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
		$utf8Bom = New-Object System.Text.UTF8Encoding $true
		[System.IO.File]::WriteAllText($outPath, $result, $utf8Bom)
		Write-Host "Written to: $outPath"
	}
	exit 1
}

$root = $xml.DocumentElement
$rightsNs = "http://v8.1c.ru/8.2/roles"

# 3b. Check root element
if ($root.LocalName -ne "Rights") {
	Report-Error "Root element is '$($root.LocalName)', expected 'Rights'"
} elseif ($root.NamespaceURI -ne $rightsNs) {
	Report-Warn "Namespace is '$($root.NamespaceURI)', expected '$rightsNs'"
} else {
	Report-OK "Root element: <Rights> with correct namespace"
}

# 3c. Global flags
$flagNames = @("setForNewObjects","setForAttributesByDefault","independentRightsOfChildObjects")
$flagsFound = 0
foreach ($fn in $flagNames) {
	$node = $root.GetElementsByTagName($fn, $rightsNs)
	if ($node.Count -gt 0) {
		$val = $node[0].InnerText
		if ($val -ne "true" -and $val -ne "false") {
			Report-Warn "$fn = '$val' (expected 'true' or 'false')"
		}
		$flagsFound++
	} else {
		Report-Warn "Missing global flag: $fn"
	}
}
if ($flagsFound -eq 3) {
	Report-OK "3 global flags present"
}

# 3d. Objects
$objects = $root.GetElementsByTagName("object", $rightsNs)
$objCount = $objects.Count
$rightCount = 0
$rlsCount = 0
$rightsObjectNames = [System.Collections.ArrayList]::new()

foreach ($obj in $objects) {
	$objName = ""
	foreach ($child in $obj.ChildNodes) {
		if ($child.LocalName -eq "name") {
			$objName = $child.InnerText
			break
		}
	}

	if (-not $objName) {
		Report-Error "Object without <name>"
		continue
	}
	[void]$rightsObjectNames.Add($objName)

	$objectType = Get-ObjectType $objName
	$isNested = Is-NestedObject $objName

	# Check object type is known
	if (-not $isNested -and -not $script:knownRights.ContainsKey($objectType) -and $objectType -notin $script:typesRightsNotChecked) {
		if ($objectType -in $script:typesWithoutRights) {
			Report-Error "${objName}: тип '$objectType' не имеет прав в роли"
		} else {
			Report-Warn "${objName}: неизвестный тип объекта '$objectType'"
		}
	}

	# Check rights
	foreach ($child in $obj.ChildNodes) {
		if ($child.LocalName -ne "right") { continue }

		$rName = ""
		$rValue = ""
		$hasRLS = $false

		foreach ($rc in $child.ChildNodes) {
			if ($rc.LocalName -eq "name") { $rName = $rc.InnerText }
			if ($rc.LocalName -eq "value") { $rValue = $rc.InnerText }
			if ($rc.LocalName -eq "restrictionByCondition") {
				$hasRLS = $true
				$rlsCount++
				# Check condition not empty
				$condNode = $null
				foreach ($rcc in $rc.ChildNodes) {
					if ($rcc.LocalName -eq "condition") { $condNode = $rcc }
				}
				if (-not $condNode -or -not $condNode.InnerText) {
					Report-Warn "${objName}: RLS condition for '$rName' is empty"
				}
			}
		}

		if (-not $rName) {
			Report-Error "${objName}: <right> without <name>"
			continue
		}

		if ($rValue -ne "true" -and $rValue -ne "false") {
			Report-Error "${objName}: right '$rName' has invalid value '$rValue'"
			continue
		}

		$rightCount++

		# Validate right name
		if ($isNested) {
			# Вид вложенности - предпоследний сегмент имени: пары идут как "вид.имя".
			$kind = $objName.Split(".")[-2]
			if ($kind -notin $script:nestedKindsRightsNotChecked -and $script:nestedRightsByKind.ContainsKey($kind)) {
				$allowedNested = $script:nestedRightsByKind[$kind]
				if ($rName -notin $allowedNested) {
					Report-Warn "${objName}: право '$rName' не существует у вида '$kind' (допустимо: $($allowedNested -join ', '))"
				}
			}
		} elseif ($script:knownRights.ContainsKey($objectType)) {
			$validRights = $script:knownRights[$objectType]
			if ($rName -notin $validRights) {
				$similar = Find-Similar -needle $rName -haystack $validRights
				$sugStr = if ($similar.Count -gt 0) { " Did you mean: $($similar -join ', ')?" } else { "" }
				Report-Warn "${objName}: unknown right '$rName'.$sugStr"
			}
		}
	}
}

Report-OK "$objCount objects, $rightCount rights"
if ($rlsCount -gt 0) {
	Report-OK "$rlsCount RLS restrictions"
}

# 3e. Templates
$templates = $root.GetElementsByTagName("restrictionTemplate", $rightsNs)
if ($templates.Count -gt 0) {
	$tplNames = @()
	foreach ($tpl in $templates) {
		$tName = ""
		$tCond = ""
		foreach ($child in $tpl.ChildNodes) {
			if ($child.LocalName -eq "name") { $tName = $child.InnerText }
			if ($child.LocalName -eq "condition") { $tCond = $child.InnerText }
		}
		if (-not $tName) {
			Report-Warn "Restriction template without <name>"
		} else {
			$parenIdx = $tName.IndexOf("(")
			$shortName = if ($parenIdx -gt 0) { $tName.Substring(0, $parenIdx) } else { $tName }
			$tplNames += $shortName
		}
		if (-not $tCond) {
			Report-Warn "Template '$tName': empty <condition>"
		}
	}
	Report-OK "$($templates.Count) templates: $($tplNames -join ', ')"
}

# --- 4. Validate metadata ---

if (Test-Path $MetadataPath) {
	Out-Line ""
	try {
		[xml]$metaXml = Get-Content -Path $MetadataPath -Encoding UTF8
		$roleNode = $metaXml.DocumentElement.SelectSingleNode("//*[local-name()='Role']")
		if (-not $roleNode) {
			Report-Error "Metadata: <Role> element not found"
		} else {
			$uuid = $roleNode.GetAttribute("uuid")
			if ($uuid -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
				Report-OK "Metadata: UUID valid ($uuid)"
			} else {
				Report-Error "Metadata: invalid UUID format '$uuid'"
			}

			$nameNode = $roleNode.SelectSingleNode(".//*[local-name()='Name']")
			if ($nameNode -and $nameNode.InnerText) {
				Report-OK "Metadata: Name = $($nameNode.InnerText)"
			} else {
				Report-Error "Metadata: <Name> is empty or missing"
			}

			$synNode = $roleNode.SelectSingleNode(".//*[local-name()='Synonym']")
			if ($synNode -and $synNode.InnerXml) {
				Report-OK "Metadata: Synonym present"
			} else {
				Report-Warn "Metadata: <Synonym> is empty"
			}
		}
	} catch {
		Report-Error "Metadata XML parse error: $($_.Exception.Message)"
	}
}

# --- 5. Check registration in Configuration.xml ---

$configDir = Split-Path $rolesDir -Parent
$configXmlPath = Join-Path $configDir "Configuration.xml"
$inferredRoleName = $roleDirName

# Use metadata name if available
if (Test-Path $MetadataPath) {
	try {
		[xml]$metaXml2 = Get-Content -Path $MetadataPath -Encoding UTF8
		$nameNode2 = $metaXml2.DocumentElement.SelectSingleNode("//*[local-name()='Role']//*[local-name()='Name']")
		if ($nameNode2 -and $nameNode2.InnerText) {
			$inferredRoleName = $nameNode2.InnerText
		}
	} catch { }
}

if (Test-Path $configXmlPath) {
	Out-Line ""
	try {
		[xml]$cfgXml = Get-Content -Path $configXmlPath -Encoding UTF8
		$cfgNs = New-Object System.Xml.XmlNamespaceManager($cfgXml.NameTable)
		$cfgNs.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")
		$childObj = $cfgXml.SelectSingleNode("//md:Configuration/md:ChildObjects", $cfgNs)
		if ($childObj) {
			$roleNodes = $childObj.SelectNodes("md:Role", $cfgNs)
			$found = $false
			foreach ($rn in $roleNodes) {
				if ($rn.InnerText -eq $inferredRoleName) {
					$found = $true
					break
				}
			}
			if ($found) {
				Report-OK "Configuration.xml: <Role>$inferredRoleName</Role> registered"
			} else {
				Report-Warn "Configuration.xml: <Role>$inferredRoleName</Role> NOT found in ChildObjects"
			}
		}
	} catch {
		Report-Warn "Configuration.xml: parse error — $($_.Exception.Message)"
	}
}

# --- 7. Right objects exist in the configuration ---
# Имена в правах те же, что ключи индекса (Catalog.Контрагенты), плюс вложенные сущности
# через Attribute / TabularSection / Command. Разбираем 2, 4 и 6 частей, остальное не трогаем.

function Get-RoleOwnFieldNames($obj) {
	$names = New-Object 'System.Collections.Generic.HashSet[string]'
	foreach ($bucket in @("attributes", "dimensions", "resources", "addressingAttributes", "accountingFlags", "extDimensionAccountingFlags")) {
		if ($obj.$bucket) { foreach ($p in $obj.$bucket.PSObject.Properties) { [void]$names.Add($p.Name) } }
	}
	if ($obj.standardAttributes) { foreach ($n in $obj.standardAttributes) { [void]$names.Add([string]$n) } }
	return $names
}

if ($IndexPath) {
	$indexObjects = $null
	$indexLenient = $false
	try {
		$idxData = [System.IO.File]::ReadAllText($IndexPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
		if ($idxData.format -ne 1) {
			Report-Warn "7. Index format $($idxData.format) is not supported, object check skipped"
		} else {
			$indexObjects = @{}
			foreach ($p in $idxData.objects.PSObject.Properties) { $indexObjects[$p.Name] = $p.Value }
			$indexLenient = ($idxData.kind -eq "extension")
		}
	} catch {
		Report-Warn "7. Index could not be read ($($_.Exception.Message)), object check skipped"
	}

	if ($null -ne $indexObjects) {
		$missingRightsObjects = 0
		$checkedRightsObjects = 0
		foreach ($name in $rightsObjectNames) {
			$parts = $name.Split(".")
			if ($parts.Count -lt 2) { continue }
			$ownerKey = $parts[0] + "." + $parts[1]
			$checkedRightsObjects++
			if (-not $indexObjects.ContainsKey($ownerKey)) {
				$missingRightsObjects++
				if ($indexLenient) {
					Report-Warn "7. Права: объекта '$ownerKey' нет в этой выгрузке - ожидается в основной конфигурации"
				} else {
					Report-Warn "7. Права: объекта '$ownerKey' нет в конфигурации"
				}
				continue
			}
			$obj = $indexObjects[$ownerKey]
			$known = $null
			if ($parts.Count -eq 4) {
				$childKind = $parts[2]
				$childName = $parts[3]
				if ($childKind -eq "Attribute" -or $childKind -eq "StandardAttribute") {
					$known = (Get-RoleOwnFieldNames $obj).Contains($childName)
				} elseif ($childKind -eq "TabularSection") {
					$known = ($null -ne $obj.tabularSections.$childName) -or ($null -ne $obj.standardTabularSections.$childName)
				} elseif ($childKind -eq "Command") {
					$known = ($obj.commands -contains $childName)
				} elseif ($childKind -eq "Form") {
					$known = ($obj.forms -contains $childName)
				} elseif ($childKind -eq "Template") {
					$known = ($obj.templates -contains $childName)
				} else {
					continue
				}
			} elseif ($parts.Count -eq 6 -and $parts[2] -eq "TabularSection" -and $parts[4] -eq "Attribute") {
				$ts = $obj.tabularSections.($parts[3])
				if ($null -eq $ts) { continue }
				$known = ($null -ne $ts.attributes.($parts[5])) -or ($ts.standardAttributes -contains $parts[5])
			} else {
				continue
			}
			if ($known) { continue }
			$missingRightsObjects++
			$nested = ($parts[2..($parts.Count - 1)] -join ".")
			if ($indexLenient) {
				Report-Warn "7. Права: у $ownerKey нет '$nested' в этой выгрузке - ожидается в основной конфигурации"
			} else {
				Report-Warn "7. Права: у $ownerKey нет '$nested'"
			}
		}
		if ($missingRightsObjects -eq 0) {
			Report-OK "7. Right objects: $checkedRightsObjects checked against index, all exist"
		}
	}
}

# --- 6. Summary ---

# Insert header
$script:output.Insert(0, "=== Validation: Role.$inferredRoleName ===$([Environment]::NewLine)") | Out-Null

$checks = $script:okCount + $script:errors + $script:warnings
if ($script:errors -eq 0 -and $script:warnings -eq 0 -and -not $Detailed) {
	$result = "=== Validation OK: Role.$inferredRoleName ($checks checks) ==="
} else {
	Out-Line ""
	Out-Line "=== Result: $($script:errors) errors, $($script:warnings) warnings ($checks checks) ==="
	$result = $script:output.ToString()
}
Write-Host $result

if ($OutFile) {
	$outPath = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
	$outDir = [System.IO.Path]::GetDirectoryName($outPath)
	if (-not (Test-Path $outDir)) {
		New-Item -ItemType Directory -Path $outDir -Force | Out-Null
	}
	$utf8Bom = New-Object System.Text.UTF8Encoding $true
	[System.IO.File]::WriteAllText($outPath, $result, $utf8Bom)
	Write-Host "Written to: $outPath"
}

if ($script:errors -gt 0) { exit 1 } else { exit 0 }
