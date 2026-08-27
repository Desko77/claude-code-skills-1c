# cf-edit v1.1 — Edit 1C configuration root (Configuration.xml)
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)][string]$ConfigPath,
	[string]$DefinitionFile,
	[ValidateSet("modify-property","add-childObject","remove-childObject","add-defaultRole","remove-defaultRole","set-defaultRoles","set-home-page","set-panels")]
	[string]$Operation,
	[string]$Value,
	[switch]$NoValidate
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Support guard (Ext/ParentConfigurations.bin) ---
# See docs/1c-support-state-spec.md. Blocks edits of vendor objects "на замке" /
# read-only configs unless allowed. Trigger = bin present; reaction from
# .v8-project.json editingAllowedCheck (deny|warn|off, default deny). Never
# throws — guard errors degrade to allow.
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
			if ($null -ne $best -and $best -ne 2) { $blocked = $true; $code = "not-removed"; $reason = "объект не снят с поддержки — удаление сломает обновления" }
		}
		else {
			if ($null -ne $best -and $best -eq 0) { $blocked = $true; $code = "locked"; $reason = "объект на замке — редактирование сломает обновления" }
		}
		if (-not $blocked) { return }
		$mode = Get-EditMode $cfgDir
		if ($mode -eq 'off') { return }
		# Use Console.Error (not Write-Error) — under ErrorActionPreference=Stop the
		# latter throws and would be swallowed by this function's own catch.
		if ($mode -eq 'warn') { [Console]::Error.WriteLine("[support-guard] ПРЕДУПРЕЖДЕНИЕ: $reason. Цель: $rp"); return }
		$head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
		$cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) — состояние поддержки менять не нужно, обновления вендора сохраняются."
		$offNote = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
		if ($code -eq "capability-off") {
			$state = "Состояние: у всей конфигурации выключена возможность изменения (режим read-only «из коробки») — поэтому объект «$rp» редактировать нельзя."
			$fix = "Либо снять защиту явно (навык support-edit, два шага):`n  1. support-edit -Path ""$cfgDir"" -Capability on — включить возможность изменения (объекты пока остаются на замке);`n  2. support-edit -Path ""$rp"" -Set editable — открыть этот объект для редактирования.`n  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
		} elseif ($code -eq "not-removed") {
			$state = "Состояние: объект «$rp» на поддержке (не снят с поддержки) — его удаление разорвёт обновления вендора."
			$fix = "Либо сначала снять объект с поддержки, затем удалять:`n  support-edit -Path ""$rp"" -Set off-support — объект уходит из-под обновлений, после этого удаление безопасно."
		} else {
			$state = "Состояние: объект «$rp» на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
			$fix = "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):`n  support-edit -Path ""$rp"" -Set editable — редактировать и дальше получать обновления вендора (возможны конфликты слияния);`n  support-edit -Path ""$rp"" -Set off-support — снять с поддержки: обновления по объекту больше не приходят."
		}
		[Console]::Error.WriteLine("$head`n$state`n$cfe`n$fix`n$offNote")
		exit 1
	} catch { return }
}
# --- Конец общего блока гарда поддержки ---

# Скрипт соседнего навыка. Каталог навыка назван с префиксом 1c-, без него пути нет.
function Get-SiblingSkillScript {
	param([string]$name, [string]$scriptName)
	foreach ($folder in @("1c-$name", $name)) {
		$candidate = Join-Path (Join-Path $PSScriptRoot "..\..\$folder") "scripts\$scriptName"
		$candidate = [System.IO.Path]::GetFullPath($candidate)
		if (Test-Path $candidate) { return $candidate }
	}
	return ""
}


# --- Mode validation ---
if ($DefinitionFile -and $Operation) { Write-Error "Cannot use both -DefinitionFile and -Operation"; exit 1 }
if (-not $DefinitionFile -and -not $Operation) { Write-Error "Either -DefinitionFile or -Operation is required"; exit 1 }

# --- Resolve path ---
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
	$ConfigPath = Join-Path (Get-Location).Path $ConfigPath
}
if (Test-Path $ConfigPath -PathType Container) {
	$candidate = Join-Path $ConfigPath "Configuration.xml"
	if (Test-Path $candidate) { $ConfigPath = $candidate }
	else { Write-Error "No Configuration.xml in directory"; exit 1 }
}
if (-not (Test-Path $ConfigPath)) { Write-Error "File not found: $ConfigPath"; exit 1 }
$resolvedPath = (Resolve-Path $ConfigPath).Path
$script:configDir = [System.IO.Path]::GetDirectoryName($resolvedPath)

Assert-EditAllowed $resolvedPath "editable"

# --- Load XML with PreserveWhitespace ---
$script:xmlDoc = New-Object System.Xml.XmlDocument
$script:xmlDoc.PreserveWhitespace = $true
$script:xmlDoc.Load($resolvedPath)

$script:addCount = 0
$script:removeCount = 0
$script:modifyCount = 0

function Info([string]$msg) { Write-Host "[INFO] $msg" }
function Warn([string]$msg) { Write-Host "[WARN] $msg" }

# --- Detect structure ---
$root = $script:xmlDoc.DocumentElement
$script:mdNs = "http://v8.1c.ru/8.3/MDClasses"
$script:xrNs = "http://v8.1c.ru/8.3/xcf/readable"
$script:xsiNs = "http://www.w3.org/2001/XMLSchema-instance"
$script:v8Ns = "http://v8.1c.ru/8.1/data/core"

$script:cfgEl = $null
foreach ($child in $root.ChildNodes) {
	if ($child.NodeType -eq 'Element' -and $child.LocalName -eq "Configuration") {
		$script:cfgEl = $child; break
	}
}
if (-not $script:cfgEl) { Write-Error "No <Configuration> element found"; exit 1 }

$script:propsEl = $null
$script:childObjsEl = $null
foreach ($child in $script:cfgEl.ChildNodes) {
	if ($child.NodeType -ne 'Element') { continue }
	if ($child.LocalName -eq "Properties") { $script:propsEl = $child }
	if ($child.LocalName -eq "ChildObjects") { $script:childObjsEl = $child }
}

$script:objName = ""
foreach ($child in $script:propsEl.ChildNodes) {
	if ($child.NodeType -eq 'Element' -and $child.LocalName -eq "Name") {
		$script:objName = $child.InnerText.Trim(); break
	}
}
Info "Configuration: $($script:objName)"

# --- Canonical type order for ChildObjects (44 types) ---
$script:typeOrder = @(
	"Language","Subsystem","StyleItem","Style",
	"CommonPicture","SessionParameter","Role","CommonTemplate",
	"FilterCriterion","CommonModule","CommonAttribute","ExchangePlan",
	"XDTOPackage","WebService","HTTPService","WSReference",
	"EventSubscription","ScheduledJob","SettingsStorage","FunctionalOption",
	"FunctionalOptionsParameter","DefinedType","CommonCommand","CommandGroup",
	"Constant","CommonForm","Catalog","Document",
	"DocumentNumerator","Sequence","DocumentJournal","Enum",
	"Report","DataProcessor","InformationRegister","AccumulationRegister",
	"ChartOfCharacteristicTypes","ChartOfAccounts","AccountingRegister",
	"ChartOfCalculationTypes","CalculationRegister",
	"BusinessProcess","Task","IntegrationService","Bot"
)

# --- Type → on-disk directory name (plural) ---
$script:typeToDir = @{
	"Language"="Languages"; "Subsystem"="Subsystems"; "StyleItem"="StyleItems"; "Style"="Styles"
	"CommonPicture"="CommonPictures"; "SessionParameter"="SessionParameters"; "Role"="Roles"; "CommonTemplate"="CommonTemplates"
	"FilterCriterion"="FilterCriteria"; "CommonModule"="CommonModules"; "CommonAttribute"="CommonAttributes"; "ExchangePlan"="ExchangePlans"
	"XDTOPackage"="XDTOPackages"; "WebService"="WebServices"; "HTTPService"="HTTPServices"; "WSReference"="WSReferences"
	"EventSubscription"="EventSubscriptions"; "ScheduledJob"="ScheduledJobs"; "SettingsStorage"="SettingsStorages"; "FunctionalOption"="FunctionalOptions"
	"FunctionalOptionsParameter"="FunctionalOptionsParameters"; "DefinedType"="DefinedTypes"; "CommonCommand"="CommonCommands"; "CommandGroup"="CommandGroups"
	"Constant"="Constants"; "CommonForm"="CommonForms"; "Catalog"="Catalogs"; "Document"="Documents"
	"DocumentNumerator"="DocumentNumerators"; "Sequence"="Sequences"; "DocumentJournal"="DocumentJournals"; "Enum"="Enums"
	"Report"="Reports"; "DataProcessor"="DataProcessors"; "InformationRegister"="InformationRegisters"; "AccumulationRegister"="AccumulationRegisters"
	"ChartOfCharacteristicTypes"="ChartsOfCharacteristicTypes"; "ChartOfAccounts"="ChartsOfAccounts"; "AccountingRegister"="AccountingRegisters"
	"ChartOfCalculationTypes"="ChartsOfCalculationTypes"; "CalculationRegister"="CalculationRegisters"
	"BusinessProcess"="BusinessProcesses"; "Task"="Tasks"; "IntegrationService"="IntegrationServices"
	"Bot"="Bots"
}

# --- XML manipulation helpers (from subsystem-edit pattern) ---
function Get-ChildIndent($container) {
	foreach ($child in $container.ChildNodes) {
		if ($child.NodeType -eq 'Whitespace' -or $child.NodeType -eq 'SignificantWhitespace') {
			if ($child.Value -match '^\r?\n(\t+)$') { return $Matches[1] }
			if ($child.Value -match '^\r?\n(\t+)') { return $Matches[1] }
		}
	}
	$depth = 0; $current = $container
	while ($current -and $current -ne $script:xmlDoc.DocumentElement) { $depth++; $current = $current.ParentNode }
	return "`t" * ($depth + 1)
}

function Insert-BeforeElement($container, $newNode, $refNode, $childIndent) {
	$ws = $script:xmlDoc.CreateWhitespace("`r`n$childIndent")
	if ($refNode) {
		$container.InsertBefore($ws, $refNode) | Out-Null
		$container.InsertBefore($newNode, $ws) | Out-Null
	} else {
		$trailing = $container.LastChild
		if ($trailing -and ($trailing.NodeType -eq 'Whitespace' -or $trailing.NodeType -eq 'SignificantWhitespace')) {
			$container.InsertBefore($ws, $trailing) | Out-Null
			$container.InsertBefore($newNode, $trailing) | Out-Null
		} else {
			$container.AppendChild($ws) | Out-Null
			$container.AppendChild($newNode) | Out-Null
			$parentIndent = if ($childIndent.Length -gt 1) { $childIndent.Substring(0, $childIndent.Length - 1) } else { "" }
			$closeWs = $script:xmlDoc.CreateWhitespace("`r`n$parentIndent")
			$container.AppendChild($closeWs) | Out-Null
		}
	}
}

function Remove-NodeWithWhitespace($node) {
	$parent = $node.ParentNode
	$prev = $node.PreviousSibling
	$next = $node.NextSibling
	if ($prev -and ($prev.NodeType -eq 'Whitespace' -or $prev.NodeType -eq 'SignificantWhitespace')) {
		$parent.RemoveChild($prev) | Out-Null
	} elseif ($next -and ($next.NodeType -eq 'Whitespace' -or $next.NodeType -eq 'SignificantWhitespace')) {
		$parent.RemoveChild($next) | Out-Null
	}
	$parent.RemoveChild($node) | Out-Null
}

function Expand-SelfClosingElement($container, $parentIndent) {
	if (-not $container.HasChildNodes -or $container.IsEmpty) {
		$closeWs = $script:xmlDoc.CreateWhitespace("`r`n$parentIndent")
		$container.AppendChild($closeWs) | Out-Null
	}
}

function Import-Fragment([string]$xmlString) {
	$wrapper = "<_W xmlns=`"$($script:mdNs)`" xmlns:xsi=`"$($script:xsiNs)`" xmlns:v8=`"$($script:v8Ns)`" xmlns:xr=`"$($script:xrNs)`" xmlns:xs=`"http://www.w3.org/2001/XMLSchema`">$xmlString</_W>"
	$frag = New-Object System.Xml.XmlDocument
	$frag.PreserveWhitespace = $true
	$frag.LoadXml($wrapper)
	$nodes = @()
	foreach ($child in $frag.DocumentElement.ChildNodes) {
		if ($child.NodeType -eq 'Element') {
			$nodes += $script:xmlDoc.ImportNode($child, $true)
		}
	}
	return ,$nodes
}

# --- Parse batch value (split by ;;) ---
function Parse-BatchValue([string]$val) {
	$items = @()
	foreach ($part in $val.Split(";;")) {
		$trimmed = $part.Trim()
		if ($trimmed) { $items += $trimmed }
	}
	return ,$items
}

# --- LocalString properties ---
$mlProps = @("Synonym","BriefInformation","DetailedInformation","Copyright","VendorInformationAddress","ConfigurationInformationAddress")
# Scalar properties
$scalarProps = @("Name","Version","Vendor","Comment","NamePrefix","UpdateCatalogAddress")
# Ref properties
$refProps = @("DefaultLanguage")

# --- Operation: modify-property ---
function Do-ModifyProperty([string]$batchVal) {
	$items = Parse-BatchValue $batchVal
	foreach ($item in $items) {
		$eqIdx = $item.IndexOf("=")
		if ($eqIdx -lt 1) {
			Write-Error "Invalid property format '$item', expected 'Key=Value'"
			exit 1
		}
		$propName = $item.Substring(0, $eqIdx).Trim()
		$propValue = $item.Substring($eqIdx + 1).Trim()

		# Find property element
		$propEl = $null
		foreach ($child in $script:propsEl.ChildNodes) {
			if ($child.NodeType -eq 'Element' -and $child.LocalName -eq $propName) {
				$propEl = $child; break
			}
		}
		if (-not $propEl) {
			Write-Error "Property '$propName' not found in Properties"
			exit 1
		}

		if ($mlProps -contains $propName) {
			# LocalString
			if (-not $propValue) {
				$propEl.InnerXml = ""
			} else {
				$indent = Get-ChildIndent $script:propsEl
				$escaped = [System.Security.SecurityElement]::Escape($propValue)
				$mlXml = "`r`n$indent`t<v8:item>`r`n$indent`t`t<v8:lang>ru</v8:lang>`r`n$indent`t`t<v8:content>$escaped</v8:content>`r`n$indent`t</v8:item>`r`n$indent"
				$propEl.InnerXml = $mlXml
			}
		} elseif ($scalarProps -contains $propName -or $refProps -contains $propName) {
			# Simple text
			if (-not $propValue) { $propEl.InnerXml = "" }
			else { $propEl.InnerText = $propValue }
		} else {
			# Enum or other — just set text
			$propEl.InnerText = $propValue
		}

		$script:modifyCount++
		Info "Set $propName = `"$propValue`""
	}
}

# --- Operation: add-childObject ---
function Do-AddChildObject([string]$batchVal) {
	if (-not $script:childObjsEl) { Write-Error "No <ChildObjects> element found"; exit 1 }

	$items = Parse-BatchValue $batchVal
	$cfgIndent = Get-ChildIndent $script:cfgEl

	# Expand self-closing if needed
	if (-not $script:childObjsEl.HasChildNodes -or $script:childObjsEl.IsEmpty) {
		Expand-SelfClosingElement $script:childObjsEl $cfgIndent
	}
	$childIndent = Get-ChildIndent $script:childObjsEl

	foreach ($item in $items) {
		$dotIdx = $item.IndexOf(".")
		if ($dotIdx -lt 1) {
			Write-Error "Invalid format '$item', expected 'Type.Name'"
			exit 1
		}
		$typeName = $item.Substring(0, $dotIdx)
		$objNameVal = $item.Substring($dotIdx + 1)

		# Check type is valid
		$typeIdx = $script:typeOrder.IndexOf($typeName)
		if ($typeIdx -lt 0) {
			Write-Error "Unknown type '$typeName'"
			exit 1
		}

		# Check that the referenced object actually exists on disk.
		# cf-edit add-childObject is a low-level operation for rare scenarios
		# (e.g. restoring a rolled-back Configuration.xml when object files are intact).
		# For creating NEW objects, meta-compile/role-compile/subsystem-compile already
		# auto-register in Configuration.xml — calling cf-edit add-childObject there is
		# unnecessary and error-prone.
		$typeDir = $script:typeToDir[$typeName]
		$objFile = Join-Path (Join-Path $script:configDir $typeDir) "$objNameVal.xml"
		if (-not (Test-Path $objFile)) {
			$hintSkill = switch ($typeName) {
				"Subsystem" { "subsystem-compile" }
				"Role"      { "role-compile" }
				default     { "meta-compile" }
			}
			Write-Error @"
Object file not found: $typeDir/$objNameVal.xml
cf-edit add-childObject only references objects that already exist on disk.
To create a new $typeName, use $hintSkill (auto-registers in Configuration.xml):
  /$hintSkill with {"type":"$typeName","name":"$objNameVal"}
"@
			exit 1
		}

		# Dedup check
		$existing = $false
		foreach ($child in $script:childObjsEl.ChildNodes) {
			if ($child.NodeType -eq 'Element' -and $child.LocalName -eq $typeName -and $child.InnerText -eq $objNameVal) {
				$existing = $true; break
			}
		}
		if ($existing) {
			Warn "Already exists: $typeName.$objNameVal"
			continue
		}

		# Find insertion point: after last element of same type, or after last element of preceding type
		$insertBefore = $null
		$lastSameType = $null
		$lastPrecedingType = $null
		$currentTypeIdx = -1

		foreach ($child in $script:childObjsEl.ChildNodes) {
			if ($child.NodeType -ne 'Element') { continue }
			$childTypeIdx = $script:typeOrder.IndexOf($child.LocalName)
			if ($childTypeIdx -lt 0) { continue }

			if ($child.LocalName -eq $typeName) {
				# Same type — check alphabetical order
				if ($child.InnerText -gt $objNameVal -and -not $insertBefore) {
					# Insert before this element (alphabetical)
					$insertBefore = $child
				}
				$lastSameType = $child
			} elseif ($childTypeIdx -lt $typeIdx) {
				$lastPrecedingType = $child
			} elseif ($childTypeIdx -gt $typeIdx -and -not $insertBefore) {
				# First element of a later type — insert before it
				$insertBefore = $child
			}
		}

		# Create element
		$newEl = $script:xmlDoc.CreateElement($typeName, $script:mdNs)
		$newEl.InnerText = $objNameVal

		if ($insertBefore) {
			Insert-BeforeElement $script:childObjsEl $newEl $insertBefore $childIndent
		} else {
			# Append at end (or after last same/preceding type)
			Insert-BeforeElement $script:childObjsEl $newEl $null $childIndent
		}

		$script:addCount++
		Info "Added: $typeName.$objNameVal"
	}
}

# --- Operation: remove-childObject ---
function Do-RemoveChildObject([string]$batchVal) {
	if (-not $script:childObjsEl) { Write-Error "No <ChildObjects> element found"; exit 1 }

	$items = Parse-BatchValue $batchVal
	foreach ($item in $items) {
		$dotIdx = $item.IndexOf(".")
		if ($dotIdx -lt 1) {
			Write-Error "Invalid format '$item', expected 'Type.Name'"
			exit 1
		}
		$typeName = $item.Substring(0, $dotIdx)
		$objNameVal = $item.Substring($dotIdx + 1)

		$found = $false
		foreach ($child in @($script:childObjsEl.ChildNodes)) {
			if ($child.NodeType -eq 'Element' -and $child.LocalName -eq $typeName -and $child.InnerText -eq $objNameVal) {
				Remove-NodeWithWhitespace $child
				$script:removeCount++
				Info "Removed: $typeName.$objNameVal"
				$found = $true
				break
			}
		}
		if (-not $found) { Warn "Not found: $typeName.$objNameVal" }
	}
}

# --- Operation: add-defaultRole ---
function Do-AddDefaultRole([string]$batchVal) {
	$items = Parse-BatchValue $batchVal

	# Find DefaultRoles element
	$rolesEl = $null
	foreach ($child in $script:propsEl.ChildNodes) {
		if ($child.NodeType -eq 'Element' -and $child.LocalName -eq "DefaultRoles") {
			$rolesEl = $child; break
		}
	}
	if (-not $rolesEl) { Write-Error "No <DefaultRoles> element found in Properties"; exit 1 }

	$propsIndent = Get-ChildIndent $script:propsEl
	if (-not $rolesEl.HasChildNodes -or $rolesEl.IsEmpty) {
		Expand-SelfClosingElement $rolesEl $propsIndent
	}
	$roleIndent = Get-ChildIndent $rolesEl

	foreach ($item in $items) {
		$roleName = $item
		if (-not $roleName.StartsWith("Role.")) { $roleName = "Role.$roleName" }

		# Dedup
		$existing = $false
		foreach ($child in $rolesEl.ChildNodes) {
			if ($child.NodeType -eq 'Element' -and $child.InnerText.Trim() -eq $roleName) {
				$existing = $true; break
			}
		}
		if ($existing) {
			Warn "DefaultRole already exists: $roleName"
			continue
		}

		$fragXml = "<xr:Item xsi:type=`"xr:MDObjectRef`">$roleName</xr:Item>"
		$nodes = Import-Fragment $fragXml
		if ($nodes.Count -gt 0) {
			Insert-BeforeElement $rolesEl $nodes[0] $null $roleIndent
			$script:addCount++
			Info "Added DefaultRole: $roleName"
		}
	}
}

# --- Operation: remove-defaultRole ---
function Do-RemoveDefaultRole([string]$batchVal) {
	$items = Parse-BatchValue $batchVal

	$rolesEl = $null
	foreach ($child in $script:propsEl.ChildNodes) {
		if ($child.NodeType -eq 'Element' -and $child.LocalName -eq "DefaultRoles") {
			$rolesEl = $child; break
		}
	}
	if (-not $rolesEl) { Write-Error "No <DefaultRoles> element found"; exit 1 }

	foreach ($item in $items) {
		$roleName = $item
		if (-not $roleName.StartsWith("Role.")) { $roleName = "Role.$roleName" }

		$found = $false
		foreach ($child in @($rolesEl.ChildNodes)) {
			if ($child.NodeType -eq 'Element' -and $child.InnerText.Trim() -eq $roleName) {
				Remove-NodeWithWhitespace $child
				$script:removeCount++
				Info "Removed DefaultRole: $roleName"
				$found = $true
				break
			}
		}
		if (-not $found) { Warn "DefaultRole not found: $roleName" }
	}
}

# --- Operation: set-defaultRoles ---
function Do-SetDefaultRoles([string]$batchVal) {
	$items = Parse-BatchValue $batchVal

	$rolesEl = $null
	foreach ($child in $script:propsEl.ChildNodes) {
		if ($child.NodeType -eq 'Element' -and $child.LocalName -eq "DefaultRoles") {
			$rolesEl = $child; break
		}
	}
	if (-not $rolesEl) { Write-Error "No <DefaultRoles> element found"; exit 1 }

	# Clear all existing children
	while ($rolesEl.HasChildNodes) {
		$rolesEl.RemoveChild($rolesEl.FirstChild) | Out-Null
	}

	if ($items.Count -eq 0) {
		$script:modifyCount++
		Info "Cleared DefaultRoles"
		return
	}

	$propsIndent = Get-ChildIndent $script:propsEl
	$roleIndent = "$propsIndent`t"

	# Add closing whitespace
	$closeWs = $script:xmlDoc.CreateWhitespace("`r`n$propsIndent")
	$rolesEl.AppendChild($closeWs) | Out-Null

	foreach ($item in $items) {
		$roleName = $item
		if (-not $roleName.StartsWith("Role.")) { $roleName = "Role.$roleName" }

		$fragXml = "<xr:Item xsi:type=`"xr:MDObjectRef`">$roleName</xr:Item>"
		$nodes = Import-Fragment $fragXml
		if ($nodes.Count -gt 0) {
			Insert-BeforeElement $rolesEl $nodes[0] $null $roleIndent
		}
	}

	$script:modifyCount++
	Info "Set DefaultRoles: $($items.Count) roles"
}

# Значение операции - объект. Из -Value оно приходит строкой, разбираем JSON.
function ConvertTo-ObjectValue {
	param([string]$opName, $value)
	if ($value -isnot [string]) { return $value }
	if (-not [string]::IsNullOrWhiteSpace($value)) {
		try { return ($value | ConvertFrom-Json) }
		catch { Write-Error "${opName}: -Value is not valid JSON: $($_.Exception.Message)"; exit 1 }
	}
	Write-Error "$opName value must be an object"
	exit 1
}

# Конец строки существующего файла; у нового - канонический CRLF.
function Get-FileEol {
	param([string]$path)
	if (-not (Test-Path $path)) { return "`r`n" }
	$text = [System.IO.File]::ReadAllText($path)
	if ($text.Contains("`r`n") -or -not $text.Contains("`n")) { return "`r`n" }
	return "`n"
}

function Esc-Xml {
	param([string]$s)
	return $s.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

# Панели интерфейса клиентского приложения. Имени панели в файле нет: платформа опознает
# панель по ПОЗИЦИИ в списке panelDef. Порядок замерен на выгрузках - он одинаков в
# конфигурациях с разными uuid панелей.
$script:panelSlots = @("sections", "favorites", "history", "open", "functions")

# Зоны раскладки идут в файле в этом порядке; пустая зона не записывается.
$script:panelZones = @("top", "left", "right", "bottom")

# Русские имена типов в ссылке на форму. Значения - канонические имена ChildObjects.
$script:ruTypeMap = @{
	"Справочник"="Catalog"; "Документ"="Document"; "Перечисление"="Enum"
	"Отчет"="Report"; "Обработка"="DataProcessor"; "Константа"="Constant"
	"РегистрСведений"="InformationRegister"; "РегистрНакопления"="AccumulationRegister"
	"РегистрБухгалтерии"="AccountingRegister"; "РегистрРасчета"="CalculationRegister"
	"ПланСчетов"="ChartOfAccounts"; "ПланВидовХарактеристик"="ChartOfCharacteristicTypes"
	"ПланВидовРасчета"="ChartOfCalculationTypes"; "ПланОбмена"="ExchangePlan"
	"БизнесПроцесс"="BusinessProcess"; "Задача"="Task"; "ЖурналДокументов"="DocumentJournal"
	"ОбщаяФорма"="CommonForm"; "Подсистема"="Subsystem"
}

# Ссылка на форму приводится к виду Тип.Имя.Form.ИмяФормы. Принимается и краткая запись
# без сегмента Form, и русское имя типа: платформа пишет только канонический вид.
function Normalize-FormRef {
	param([string]$ref)
	$parts = @($ref -split '\.' | Where-Object { $_ -ne '' })
	if ($parts.Count -eq 0) { return $ref }
	if ($script:ruTypeMap.ContainsKey($parts[0])) { $parts[0] = $script:ruTypeMap[$parts[0]] }
	if ($parts.Count -eq 3) {
		$parts = @($parts[0], $parts[1], 'Form', $parts[2])
	} elseif ($parts.Count -ge 4 -and ($parts[2] -ceq 'Форма' -or $parts[2] -ceq 'form')) {
		$parts[2] = 'Form'
	}
	return ($parts -join '.')
}

# Идентификаторы panelDef в порядке файла - это и есть порядок $script:panelSlots.
function Read-PanelDefs {
	param([string]$path)
	$text = [System.IO.File]::ReadAllText($path)
	$ids = New-Object System.Collections.Generic.List[string]
	foreach ($m in [regex]::Matches($text, '<panelDef id="([^"]+)"')) {
		[void]$ids.Add($m.Groups[1].Value)
	}
	return $ids
}

function Do-SetHomePage {
	param($spec)
	$spec = ConvertTo-ObjectValue "set-home-page" $spec
	$version = $script:xmlDoc.DocumentElement.GetAttribute('version')
	if (-not $version) { $version = '2.17' }
	$template = if ($spec.template) { "$($spec.template)" } else { 'TwoColumnsVariableWidth' }
	$lines = New-Object System.Collections.Generic.List[string]
	[void]$lines.Add('<?xml version="1.0" encoding="UTF-8"?>')
	[void]$lines.Add('<HomePageWorkArea xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="' + $version + '">')
	[void]$lines.Add("`t<WorkingAreaTemplate>$(Esc-Xml $template)</WorkingAreaTemplate>")
	$itemCount = 0
	foreach ($pair in @(@('left','LeftColumn'), @('right','RightColumn'))) {
		$column = @($spec.$($pair[0]))
		if ($column.Count -eq 0 -or $null -eq $column[0]) { continue }
		[void]$lines.Add("`t<$($pair[1])>")
		foreach ($entry in $column) {
			$form = $null; $height = 10; $visible = $true; $roles = $null
			if ($entry -is [string]) {
				$form = $entry
			} else {
				$form = "$($entry.form)"
				if ($null -ne $entry.height) { $height = [int]$entry.height }
				if ($null -ne $entry.visibility) { $visible = [bool]$entry.visibility }
				$roles = $entry.roles
			}
			$form = Normalize-FormRef $form
			[void]$lines.Add("`t`t<Item>")
			[void]$lines.Add("`t`t`t<Form>$(Esc-Xml $form)</Form>")
			[void]$lines.Add("`t`t`t<Height>$height</Height>")
			[void]$lines.Add("`t`t`t<Visibility>")
			$commonFlag = if ($visible) { 'true' } else { 'false' }
			[void]$lines.Add("`t`t`t`t<xr:Common>$commonFlag</xr:Common>")
			if ($roles) {
				foreach ($prop in $roles.PSObject.Properties) {
					$roleName = $prop.Name
					if (-not $roleName.StartsWith('Role.')) { $roleName = "Role.$roleName" }
					$allowed = if ([bool]$prop.Value) { 'true' } else { 'false' }
					[void]$lines.Add("`t`t`t`t<xr:Value name=`"$(Esc-Xml $roleName)`">$allowed</xr:Value>")
				}
			}
			[void]$lines.Add("`t`t`t</Visibility>")
			[void]$lines.Add("`t`t</Item>")
			$itemCount++
		}
		[void]$lines.Add("`t</$($pair[1])>")
	}
	[void]$lines.Add('</HomePageWorkArea>')
	$extDir = Join-Path (Split-Path -Parent $script:resolvedPath) 'Ext'
	$target = Join-Path $extDir 'HomePageWorkArea.xml'
	[void]$script:pendingWrites.Add([pscustomobject]@{ Path = $target; Text = ($lines -join (Get-FileEol $target)) })
	$script:modifyCount++
	Info "Home page work area: $template, $itemCount form(s)"
}

function Do-SetPanels {
	param($spec)
	$spec = ConvertTo-ObjectValue "set-panels" $spec
	$interfacePath = Join-Path (Join-Path (Split-Path -Parent $script:resolvedPath) 'Ext') 'ClientApplicationInterface.xml'
	if (-not (Test-Path $interfacePath)) {
		Write-Error "Ext/ClientApplicationInterface.xml not found next to $script:resolvedPath"
		exit 1
	}
	$panelDefs = Read-PanelDefs $interfacePath
	if ($panelDefs.Count -ne $script:panelSlots.Count) {
		Write-Error "Ext/ClientApplicationInterface.xml: expected $($script:panelSlots.Count) panelDef, found $($panelDefs.Count)"
		exit 1
	}
	$slotUuid = @{}
	for ($i = 0; $i -lt $script:panelSlots.Count; $i++) { $slotUuid[$script:panelSlots[$i]] = $panelDefs[$i] }
	$lines = New-Object System.Collections.Generic.List[string]
	[void]$lines.Add('<?xml version="1.0" encoding="UTF-8"?>')
	[void]$lines.Add('<ClientApplicationInterface xmlns="http://v8.1c.ru/8.2/managed-application/core" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="InterfaceLayouter">')
	$placed = 0
	foreach ($zone in $script:panelZones) {
		$entries = @($spec.$zone)
		if ($entries.Count -eq 0 -or $null -eq $entries[0]) { continue }
		[void]$lines.Add("`t<$zone>")
		foreach ($entry in $entries) {
			$group = if ($entry -is [string]) { $null } else { $entry.group }
			if ($group) {
				# Группа - стек панелей в одной зоне: внешний group с id, внутри по одному
				# безымянному group на каждую панель.
				[void]$lines.Add("`t`t<group id=`"$([guid]::NewGuid())`">")
				foreach ($member in @($group)) {
					[void]$lines.Add("`t`t`t<group>")
					foreach ($line in (Get-PanelLines $member $slotUuid 4)) { [void]$lines.Add($line) }
					[void]$lines.Add("`t`t`t</group>")
					$placed++
				}
				[void]$lines.Add("`t`t</group>")
			} else {
				foreach ($line in (Get-PanelLines "$entry" $slotUuid 2)) { [void]$lines.Add($line) }
				$placed++
			}
		}
		[void]$lines.Add("`t</$zone>")
	}
	foreach ($panelId in $panelDefs) { [void]$lines.Add("`t<panelDef id=`"$panelId`"/>") }
	[void]$lines.Add('</ClientApplicationInterface>')
	[void]$script:pendingWrites.Add([pscustomobject]@{ Path = $interfacePath; Text = ($lines -join (Get-FileEol $interfacePath)) })
	$script:modifyCount++
	Info "Client application interface: $placed panel(s) placed"
}

function Get-PanelLines {
	param([string]$name, $slotUuid, [int]$indent)
	if (-not $slotUuid.ContainsKey($name)) {
		Write-Error "Unknown panel '$name'. Known: $($script:panelSlots -join ', ')"
		exit 1
	}
	$pad = "`t" * $indent
	return @("$pad<panel id=`"$([guid]::NewGuid())`">",
		"$pad`t<uuid>$($slotUuid[$name])</uuid>",
		"$pad</panel>")
}

# Пакет применяется целиком: побочные файлы пишутся после того, как прошли все операции.
# Иначе отказ на второй операции оставлял первый файл уже записанным.
$script:pendingWrites = New-Object System.Collections.Generic.List[object]

# --- Execute operations ---
$operations = @()
if ($DefinitionFile) {
	if (-not [System.IO.Path]::IsPathRooted($DefinitionFile)) {
		$DefinitionFile = Join-Path (Get-Location).Path $DefinitionFile
	}
	$jsonText = Get-Content -Raw -Encoding UTF8 $DefinitionFile
	$ops = $jsonText | ConvertFrom-Json
	if ($ops -is [System.Array]) {
		foreach ($op in $ops) { $operations += $op }
	} else {
		$operations += $ops
	}
} else {
	$operations += @{ operation = $Operation; value = $Value }
}

foreach ($op in $operations) {
	$opName = if ($op.operation) { "$($op.operation)" } else { "$Operation" }
	# Значение операции бывает объектом (set-home-page, set-panels) - строкой его тогда
	# не приводим, иначе структура теряется.
	$opRaw = if ($null -ne $op.value) { $op.value } else { $Value }
	$opValue = if ($opRaw -is [string] -or $null -eq $opRaw) { "$opRaw" } else { $opRaw }

	switch ($opName) {
		"modify-property"    { Do-ModifyProperty $opValue }
		"add-childObject"    { Do-AddChildObject $opValue }
		"remove-childObject" { Do-RemoveChildObject $opValue }
		"add-defaultRole"    { Do-AddDefaultRole $opValue }
		"remove-defaultRole" { Do-RemoveDefaultRole $opValue }
		"set-defaultRoles"   { Do-SetDefaultRoles $opValue }
		"set-home-page"      { Do-SetHomePage $opValue }
		"set-panels"         { Do-SetPanels $opValue }
		default              { Write-Error "Unknown operation: $opName"; exit 1 }
	}
}

# --- Save ---
$settings = New-Object System.Xml.XmlWriterSettings
$settings.Encoding = New-Object System.Text.UTF8Encoding($true)
$settings.Indent = $false
$settings.NewLineHandling = [System.Xml.NewLineHandling]::None

$memStream = New-Object System.IO.MemoryStream
$writer = [System.Xml.XmlWriter]::Create($memStream, $settings)
$script:xmlDoc.Save($writer)
$writer.Flush(); $writer.Close()

$bytes = $memStream.ToArray()
$memStream.Close()
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
$text = $text.Replace('encoding="utf-8"', 'encoding="UTF-8"')
# Пустой элемент: XmlWriter отдает `<a />`, Конфигуратор пишет `<a/>`. Внутри
# CDATA/комментария или значения атрибута ` />` может быть содержимым,
# поэтому они идут первыми ветками альтернации и возвращаются как есть.
$text = [regex]::Replace($text, '(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|<([A-Za-z0-9_:.\-]+)((?:\s+[A-Za-z0-9_:.\-]+="[^"]*")*)\s+/>', { param($m) if ($m.Groups[1].Success) { '<' + $m.Groups[1].Value + $m.Groups[2].Value + '/>' } else { $m.Value } })

# Концы строк берутся из ФАЙЛА, который правим: объекты конфигурации хранятся в CRLF,
# схемы компоновки в LF. Форсировать один вид нельзя - навык испортит чужой формат.
$origText = if (Test-Path $resolvedPath) { [System.IO.File]::ReadAllText($resolvedPath) } else { "" }
$origCrlf = $origText.Contains("`r`n")
$text = $text.Replace("`r`n", "`n")
if ($origCrlf) { $text = $text.Replace("`n", "`r`n") }
# Хвостовой перевод исходного файла тоже сохраняется: универсального правила нет,
# часть навыков его пишет, часть нет - правка не должна это менять.
if ($origText.EndsWith("`n") -and -not $text.EndsWith("`n")) {
	$text += if ($origCrlf) { "`r`n" } else { "`n" }
}

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($resolvedPath, $text, $utf8Bom)
Info "Saved: $resolvedPath"
foreach ($pending in $script:pendingWrites) {
	$dir = Split-Path -Parent $pending.Path
	if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
	[System.IO.File]::WriteAllText($pending.Path, $pending.Text, (New-Object System.Text.UTF8Encoding($true)))
}

# --- Auto-validate ---
if (-not $NoValidate) {
	$validateScript = Get-SiblingSkillScript "cf-validate" "cf-validate.ps1"
	if ($validateScript) {
		Write-Host ""
		Write-Host "--- Running cf-validate ---"
		& powershell.exe -NoProfile -File $validateScript -ConfigPath $resolvedPath
	}
}

# --- Summary ---
Write-Host ""
Write-Host "=== cf-edit summary ==="
Write-Host "  Configuration: $($script:objName)"
Write-Host "  Added:         $($script:addCount)"
Write-Host "  Removed:       $($script:removeCount)"
Write-Host "  Modified:      $($script:modifyCount)"
exit 0
