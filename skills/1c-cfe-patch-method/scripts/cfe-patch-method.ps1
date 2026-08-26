# cfe-patch-method v1.2 - Generate and resync method interceptors for 1C extension (CFE)
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$ExtensionPath,

	# Не обязателен в режимах -Check и -Actualize: там обходится все расширение.
	[string]$ModulePath,

	[string]$MethodName,

	# Набор значений проверяется ниже: в батч-режимах параметр не передается,
	# а ValidateSet отвергает и пустую строку.
	[string]$InterceptorType,

	# Путь к исходникам основной конфигурации: оттуда берется сигнатура, тело и
	# директива компиляции перехватываемого метода. Расширение об этом не знает.
	[string]$ConfigPath,

	[string]$Context = "НаСервере",

	[switch]$IsFunction,

	# Сверить перехватчики ИзменениеИКонтроль с оригиналами, ничего не записывая.
	[switch]$Check,

	# То же плюс перенос правок в новую редакцию оригинала.
	[switch]$Actualize
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$MARK_INS_START = "#Вставка"
$MARK_INS_END = "#КонецВставки"
$MARK_DEL_START = "#Удаление"
$MARK_DEL_END = "#КонецУдаления"

$typeDirMap = @{
	"Catalog"="Catalogs"; "Document"="Documents"; "Enum"="Enums"
	"CommonModule"="CommonModules"; "Report"="Reports"; "DataProcessor"="DataProcessors"
	"ExchangePlan"="ExchangePlans"; "ChartOfAccounts"="ChartsOfAccounts"
	"ChartOfCharacteristicTypes"="ChartsOfCharacteristicTypes"
	"ChartOfCalculationTypes"="ChartsOfCalculationTypes"
	"BusinessProcess"="BusinessProcesses"; "Task"="Tasks"
	"InformationRegister"="InformationRegisters"; "AccumulationRegister"="AccumulationRegisters"
	"AccountingRegister"="AccountingRegisters"; "CalculationRegister"="CalculationRegisters"
	"Catalogs"="Catalogs"; "Documents"="Documents"; "Enums"="Enums"
	"CommonModules"="CommonModules"; "Reports"="Reports"; "DataProcessors"="DataProcessors"
	"ExchangePlans"="ExchangePlans"; "ChartsOfAccounts"="ChartsOfAccounts"
	"ChartsOfCharacteristicTypes"="ChartsOfCharacteristicTypes"
	"ChartsOfCalculationTypes"="ChartsOfCalculationTypes"
	"BusinessProcesses"="BusinessProcesses"; "Tasks"="Tasks"
	"InformationRegisters"="InformationRegisters"; "AccumulationRegisters"="AccumulationRegisters"
	"AccountingRegisters"="AccountingRegisters"; "CalculationRegisters"="CalculationRegisters"
}

$dirTypeMap = @{
	"CommonModules"="CommonModule"; "Catalogs"="Catalog"; "Documents"="Document"
	"Enums"="Enum"; "Reports"="Report"; "DataProcessors"="DataProcessor"
	"ExchangePlans"="ExchangePlan"; "ChartsOfAccounts"="ChartOfAccounts"
	"ChartsOfCharacteristicTypes"="ChartOfCharacteristicTypes"
	"ChartsOfCalculationTypes"="ChartOfCalculationTypes"
	"BusinessProcesses"="BusinessProcess"; "Tasks"="Task"
	"InformationRegisters"="InformationRegister"; "AccumulationRegisters"="AccumulationRegister"
	"AccountingRegisters"="AccountingRegister"; "CalculationRegisters"="CalculationRegister"
}

$enc = New-Object System.Text.UTF8Encoding($true)

# ============================== Общие функции ==============================

function Read-Bsl {
	param([string]$Path)
	return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Split-Lines {
	param([string]$Text)
	if ($null -eq $Text) { return @() }
	return @($Text -split "`r?`n")
}

function Get-Meaningful {
	param([string[]]$Lines, [switch]$KeepComments)
	$out = @()
	foreach ($l in $Lines) {
		$t = $l.Trim()
		if ($t -eq "") { continue }
		if (-not $KeepComments -and $t.StartsWith("//")) { continue }
		$out += $t
	}
	return ,$out
}

# Ищет метод в тексте модуля. Возвращает сигнатуру, тело, директиву компиляции и
# охватывающее условие препроцессора - все, что перехватчик обязан повторить.
function Find-Method {
	param([string]$Text, [string]$Name)

	$lines = Split-Lines $Text
	$headPattern = "^[ `t]*(Процедура|Функция)\s+" + [regex]::Escape($Name) + "\s*\("
	$startIdx = -1
	$declEnd = -1
	$isFunc = $false
	$params = ""
	for ($i = 0; $i -lt $lines.Count; $i++) {
		$m = [regex]::Match($lines[$i], $headPattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
		if (-not $m.Success) { continue }
		# Список параметров переносится на несколько строк - объявление читается
		# до закрывающей скобки, а не в пределах одной строки.
		$decl = $lines[$i]
		$j = $i
		while ($decl.IndexOf(")") -lt 0 -and $j + 1 -lt $lines.Count) {
			$j++
			$decl += " " + $lines[$j].Trim()
		}
		$closeIdx = $decl.IndexOf(")")
		if ($closeIdx -lt 0) { continue }
		$openIdx = $decl.IndexOf("(")
		$startIdx = $i
		$declEnd = $j
		$isFunc = ($m.Groups[1].Value -match "^Ф")
		$params = $decl.Substring($openIdx + 1, $closeIdx - $openIdx - 1).Trim()
		break
	}
	if ($startIdx -lt 0) { return $null }

	$endWord = if ($isFunc) { "КонецФункции" } else { "КонецПроцедуры" }
	$endIdx = -1
	for ($i = $declEnd + 1; $i -lt $lines.Count; $i++) {
		if ($lines[$i].Trim() -like "$endWord*") { $endIdx = $i; break }
	}
	if ($endIdx -lt 0) { $endIdx = $lines.Count }

	$body = @()
	for ($i = $declEnd + 1; $i -lt $endIdx; $i++) { $body += $lines[$i] }

	# Директива компиляции стоит непосредственно над сигнатурой; аннотации перехвата
	# (они начинаются с тех же &) в оригинале встретиться не могут.
	$directive = ""
	for ($i = $startIdx - 1; $i -ge 0; $i--) {
		$t = $lines[$i].Trim()
		if ($t -eq "" -or $t.StartsWith("//")) { continue }
		if ($t.StartsWith("&")) { $directive = $t }
		break
	}

	# Условие препроцессора вокруг метода: перехватчик компилируется в тех же режимах.
	$preproc = ""
	for ($i = $startIdx - 1; $i -ge 0; $i--) {
		$t = $lines[$i].Trim()
		if ($t -match "^#Если\s+(.+?)\s+Тогда$") {
			$cond = $Matches[1]
			for ($j = $endIdx + 1; $j -lt $lines.Count; $j++) {
				if ($lines[$j].Trim() -eq "#КонецЕсли") { $preproc = $cond; break }
			}
			break
		}
	}

	return @{
		IsFunction = $isFunc
		Params     = $params
		Body       = $body
		Directive  = $directive
		Preproc    = $preproc
		StartLine  = $startIdx
		DeclEnd    = $declEnd
		EndLine    = $endIdx
	}
}

# ============================== Ресинк ==============================

# Делит тело перехватчика на участки: код оригинала, вставки разработчика и
# отключенные им фрагменты оригинала.
function Split-InterceptorBody {
	param([string[]]$Lines)

	$segments = @()
	$current = @{ Kind = "base"; Lines = @() }
	foreach ($line in $Lines) {
		$t = $line.Trim()
		if ($t -eq $MARK_INS_START -or $t -eq $MARK_DEL_START) {
			if ($current.Lines.Count -gt 0) { $segments += $current }
			$kind = if ($t -eq $MARK_INS_START) { "insert" } else { "delete" }
			$current = @{ Kind = $kind; Lines = @() }
			continue
		}
		if ($t -eq $MARK_INS_END -or $t -eq $MARK_DEL_END) {
			$segments += $current
			$current = @{ Kind = "base"; Lines = @() }
			continue
		}
		$current.Lines += $line
	}
	if ($current.Lines.Count -gt 0) { $segments += $current }
	return ,$segments
}

# Идут ли строки блока подряд в проверяемом тексте. Пустые строки и комментарии
# при сравнении не учитываются: они не меняют смысл кода.
function Test-BlockPresent {
	param([string[]]$Hay, [string[]]$Needle)

	$n = Get-Meaningful $Needle
	if ($n.Count -eq 0) { return $false }
	$h = Get-Meaningful $Hay -KeepComments
	$h = @($h | Where-Object { -not $_.StartsWith("//") })
	if ($n.Count -gt $h.Count) { return $false }
	for ($i = 0; $i -le $h.Count - $n.Count; $i++) {
		$ok = $true
		for ($j = 0; $j -lt $n.Count; $j++) {
			if ($h[$i + $j] -ne $n[$j]) { $ok = $false; break }
		}
		if ($ok) { return $true }
	}
	return $false
}

# С какой строки в тексте начинается блок; пустые строки и комментарии не учитываются.
function Find-BlockStart {
	param([System.Collections.Generic.List[string]]$Lines, [string[]]$Block)

	$n = Get-Meaningful $Block
	if ($n.Count -eq 0) { return -1 }
	for ($i = 0; $i -lt $Lines.Count; $i++) {
		if ($Lines[$i].Trim() -ne $n[0]) { continue }
		$ok = $true
		$k = $i
		foreach ($needle in $n) {
			while ($k -lt $Lines.Count -and $Lines[$k].Trim() -eq "") { $k++ }
			if ($k -ge $Lines.Count -or $Lines[$k].Trim() -ne $needle) { $ok = $false; break }
			$k++
		}
		if ($ok) { return $i }
	}
	return -1
}

function Get-LineIndexes {
	param([string[]]$Lines, [string]$Value)
	$res = @()
	for ($i = 0; $i -lt $Lines.Count; $i++) {
		if ($Lines[$i].Trim() -eq $Value) { $res += $i }
	}
	return ,$res
}

# Переносит правки разработчика в новую редакцию тела метода.
function Merge-Edits {
	param([object[]]$Segments, [string[]]$OrigBody)

	$edits = @()
	$oldBase = @()
	foreach ($seg in $Segments) {
		if ($seg.Kind -eq "base") {
			$oldBase += $seg.Lines
			continue
		}
		$edit = @{
			Kind   = $seg.Kind
			Lines  = $seg.Lines
			Before = ""
			After  = ""
			Index  = $oldBase.Count
		}
		for ($i = $oldBase.Count - 1; $i -ge 0; $i--) {
			if ($oldBase[$i].Trim() -ne "") { $edit.Before = $oldBase[$i].Trim(); break }
		}
		$edits += $edit
		# Отключенный фрагмент был частью оригинала - он входит в прежнюю редакцию тела.
		if ($seg.Kind -eq "delete") { $oldBase += $seg.Lines }
	}

	# Нижний якорь известен только после того, как собрана вся прежняя редакция.
	foreach ($edit in $edits) {
		$idx = $edit.Index
		if ($edit.Kind -eq "delete") { $idx += $edit.Lines.Count }
		for ($i = $idx; $i -lt $oldBase.Count; $i++) {
			if ($oldBase[$i].Trim() -ne "") { $edit.After = $oldBase[$i].Trim(); break }
		}
	}

	$sameBase = (Get-Meaningful $oldBase -KeepComments) -join "`n"
	$sameOrig = (Get-Meaningful $OrigBody -KeepComments) -join "`n"

	$result = [System.Collections.Generic.List[string]]::new()
	foreach ($l in $OrigBody) { [void]$result.Add($l) }

	$kept = 0
	$transferred = 0
	$orphan = @()
	$conflicts = @()

	foreach ($edit in $edits) {
		$present = Test-BlockPresent $OrigBody $edit.Lines
		if ($edit.Kind -eq "insert" -and $present) {
			# Правка попала в основную конфигурацию: держать ее в расширении незачем.
			$transferred++
			$comments = @($edit.Lines | Where-Object { $_.Trim().StartsWith("//") })
			foreach ($c in $comments) {
				if (-not (Test-BlockPresent $OrigBody @($c) )) { $orphan += $c.Trim() }
			}
			continue
		}
		if ($edit.Kind -eq "delete" -and -not $present) {
			$transferred++
			continue
		}
		if ($edit.Kind -eq "delete" -and $present) {
			$at = Find-BlockStart $result $edit.Lines
			if ($at -ge 0) {
				$count = (Get-Meaningful $edit.Lines).Count
				$result.Insert($at + $count, $MARK_DEL_END)
				$result.Insert($at, $MARK_DEL_START)
				$kept++
				continue
			}
			$conflicts += $edit
			continue
		}

		$pos = -1
		if ($edit.After -ne "") {
			$hits = Get-LineIndexes $result $edit.After
			if ($hits.Count -eq 1) { $pos = $hits[0] }
		}
		if ($pos -lt 0 -and $edit.Before -ne "") {
			$hits = Get-LineIndexes $result $edit.Before
			if ($hits.Count -eq 1) { $pos = $hits[0] + 1 }
		}
		if ($pos -lt 0) { $conflicts += $edit; continue }

		$block = Format-Edit $edit
		$result.InsertRange($pos, [string[]]$block)
		$kept++
	}

	if ($conflicts.Count -gt 0) {
		[void]$result.Add("`t// [РЕСИНК-КОНФЛИКТ] блоки ниже не легли автоматически - перенесите вручную.")
		$num = 0
		foreach ($edit in $conflicts) {
			$num++
			$word = if ($edit.Kind -eq "insert") { "вставка" } else { "удаление" }
			[void]$result.Add("`t// [РЕСИНК-КОНФЛИКТ №$num] $word - исходный якорь изменен в новом оригинале.")
			foreach ($l in (Format-Edit $edit)) { [void]$result.Add($l) }
		}
	}

	return @{
		Lines       = $result.ToArray()
		Kept        = $kept
		Transferred = $transferred
		Conflicts   = $conflicts.Count
		Orphan      = $orphan
		Unchanged   = ($sameBase -eq $sameOrig)
	}
}

function Format-Edit {
	param($Edit)
	$open = if ($Edit.Kind -eq "insert") { $MARK_INS_START } else { $MARK_DEL_START }
	$close = if ($Edit.Kind -eq "insert") { $MARK_INS_END } else { $MARK_DEL_END }
	$out = @($open)
	$out += $Edit.Lines
	$out += $close
	return ,$out
}

# Сверяет один перехватчик ИзменениеИКонтроль с оригиналом и, если разрешено, переписывает его.
function Resync-Interceptor {
	param(
		[string]$ExtFile,
		[string]$OrigFile,
		[string]$Method,
		[string]$ProcName,
		[switch]$Apply
	)

	if (-not (Test-Path $OrigFile)) {
		return @{ Status = "no-original" }
	}
	$origInfo = Find-Method (Read-Bsl $OrigFile) $Method
	if ($null -eq $origInfo) {
		return @{ Status = "no-original" }
	}

	$extText = Read-Bsl $ExtFile
	$extInfo = Find-Method $extText $ProcName
	if ($null -eq $extInfo) {
		return @{ Status = "no-interceptor" }
	}

	$merge = Merge-Edits (Split-InterceptorBody $extInfo.Body) $origInfo.Body
	$sameSignature = ($extInfo.Params -eq $origInfo.Params) -and ($extInfo.IsFunction -eq $origInfo.IsFunction)
	if ($merge.Unchanged -and $sameSignature) {
		return @{ Status = "actual"; Kept = 0; Transferred = 0; Conflicts = 0; Orphan = @() }
	}

	if ($Apply) {
		$lines = Split-Lines $extText
		$head = @()
		for ($i = 0; $i -lt $extInfo.StartLine; $i++) { $head += $lines[$i] }
		# Объявление пересобирается по оригиналу: смена списка параметров или вида метода
		# разрывает связь перехватчика с перехватываемым методом.
		$keyword = if ($origInfo.IsFunction) { "Функция" } else { "Процедура" }
		$indent = [regex]::Match($lines[$extInfo.StartLine], "^[ `t]*").Value
		$head += "$indent$keyword $ProcName($($origInfo.Params))"
		$tail = @()
		$endWord = if ($origInfo.IsFunction) { "КонецФункции" } else { "КонецПроцедуры" }
		for ($i = $extInfo.EndLine; $i -lt $lines.Count; $i++) {
			if ($i -eq $extInfo.EndLine) { $tail += "$indent$endWord" } else { $tail += $lines[$i] }
		}
		$newText = (($head + $merge.Lines + $tail) -join "`r`n")
		[System.IO.File]::WriteAllText($ExtFile, $newText, $enc)
	}

	$status = if ($merge.Conflicts -gt 0) {
		"partial"
	} elseif ($merge.Kept -eq 0 -and $merge.Transferred -gt 0 -and $sameSignature) {
		"transferred"
	} else {
		"updated"
	}
	return @{
		Status      = $status
		Kept        = $merge.Kept
		Transferred = $merge.Transferred
		Conflicts   = $merge.Conflicts
		Orphan      = $merge.Orphan
	}
}

# Перечисляет перехватчики ИзменениеИКонтроль во всех модулях расширения.
function Get-ControlledMethods {
	param([string]$Root)
	$found = @()
	foreach ($file in (Get-ChildItem -Path $Root -Recurse -Filter "*.bsl" -File)) {
		$text = Read-Bsl $file.FullName
		foreach ($m in [regex]::Matches($text, '&ИзменениеИКонтроль\("([^"]+)"\)\s*\r?\n\s*(?:&[^\r\n]+\r?\n\s*)?(?:Процедура|Функция)\s+([^\s(]+)')) {
			$found += @{
				File     = $file.FullName
				Method   = $m.Groups[1].Value
				ProcName = $m.Groups[2].Value
			}
		}
	}
	return ,$found
}

function Get-OriginalPathFor {
	param([string]$ExtFile, [string]$ExtRoot, [string]$CfgRoot)
	$rel = $ExtFile.Substring($ExtRoot.Length).TrimStart([char]92, [char]47)
	return (Join-Path $CfgRoot $rel)
}

# ============================== Подготовка путей ==============================

if (-not [System.IO.Path]::IsPathRooted($ExtensionPath)) {
	$ExtensionPath = Join-Path (Get-Location).Path $ExtensionPath
}
if (Test-Path $ExtensionPath -PathType Leaf) {
	$ExtensionPath = Split-Path $ExtensionPath -Parent
}
$cfgFile = Join-Path $ExtensionPath "Configuration.xml"
if (-not (Test-Path $cfgFile)) {
	Write-Error "Configuration.xml not found in: $ExtensionPath"
	exit 1
}

$configRoot = ""
if ($ConfigPath) {
	$configRoot = if ([System.IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath } else { Join-Path (Get-Location).Path $ConfigPath }
}

# --- NamePrefix из Configuration.xml ---
$cfgDoc = New-Object System.Xml.XmlDocument
$cfgDoc.PreserveWhitespace = $false
$cfgDoc.Load($cfgFile)
$cfgNs = New-Object System.Xml.XmlNamespaceManager($cfgDoc.NameTable)
$cfgNs.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")
$propsNode = $cfgDoc.SelectSingleNode("//md:Configuration/md:Properties", $cfgNs)
$prefixNode = if ($propsNode) { $propsNode.SelectSingleNode("md:NamePrefix", $cfgNs) } else { $null }
$namePrefix = if ($prefixNode -and $prefixNode.InnerText) { $prefixNode.InnerText } else { "Расш_" }

# ============================== Батч: -Check / -Actualize ==============================

if ($Check -or $Actualize) {
	if (-not $configRoot) {
		[Console]::Error.WriteLine("Ошибка: для -Check и -Actualize нужен -ConfigPath")
		exit 1
	}
	$controlled = Get-ControlledMethods $ExtensionPath
	$total = $controlled.Count
	$drift = 0
	$broken = 0
	$fixed = 0
	$details = @()

	foreach ($item in $controlled) {
		$origFile = Get-OriginalPathFor $item.File $ExtensionPath $configRoot
		$res = Resync-Interceptor -ExtFile $item.File -OrigFile $origFile -Method $item.Method -ProcName $item.ProcName -Apply:$Actualize
		if ($res.Status -eq "actual") { continue }
		if ($res.Status -eq "no-original") {
			# Метод или его модуль исчезли из основной конфигурации: перехватчик мертв,
			# и молчать об этом нельзя - ради такого случая проверка и нужна.
			$broken++
			$details += "$($item.Method) (оригинал не найден)"
			continue
		}
		if ($res.Status -eq "no-interceptor") { continue }
		$drift++
		if ($Actualize) { $fixed++ }
		$details += "$($item.Method) ($($res.Status))"
	}

	if ($Actualize -and $broken -eq 0) {
		Write-Host "[OK] Контролируемых методов: $total, актуализировано: $fixed"
		foreach ($d in $details) { Write-Host "     $d" }
		exit 0
	}

	if ($drift -eq 0 -and $broken -eq 0) {
		Write-Host "[OK] Контролируемые методы: $total/$total актуальны"
		exit 0
	}
	if ($broken -gt 0) {
		[Console]::Error.WriteLine("Оригинал не найден: $broken из $total; дрейф: $drift")
	} else {
		[Console]::Error.WriteLine("Дрейф оригинала: $drift из $total")
	}
	foreach ($d in $details) { [Console]::Error.WriteLine("     $d") }
	exit 1
}

# ============================== Одиночный режим ==============================

foreach ($req in @("ModulePath","MethodName","InterceptorType")) {
	if (-not (Get-Variable -Name $req -ValueOnly)) {
		[Console]::Error.WriteLine("Ошибка: параметр -$req обязателен (без -Check и -Actualize)")
		exit 1
	}
}
$knownTypes = @("Before","After","Instead","ModificationAndControl")
if ($knownTypes -notcontains $InterceptorType) {
	[Console]::Error.WriteLine("Ошибка: -InterceptorType принимает $($knownTypes -join ', '), получено: $InterceptorType")
	exit 1
}

# ModulePath принимается и как имя объекта, и как путь к файлу модуля.
$isFormModule = $false
$objType = ""
$objName = ""
$relPath = ""

if ($ModulePath -match "[\\/]" -or $ModulePath -match "\.bsl$") {
	$norm = $ModulePath -replace "\\", "/"
	$relPath = $norm
	$segs = @($norm -split "/" | Where-Object { $_ -ne "" })
	if ($segs.Count -lt 2 -or -not $dirTypeMap.ContainsKey($segs[0])) {
		Write-Error "Unknown object type: $ModulePath"
		exit 1
	}
	$objType = $dirTypeMap[$segs[0]]
	$objName = $segs[1]
	$isFormModule = ($norm -match "/Forms/")
} else {
	$parts = $ModulePath.Split(".")
	if ($parts.Count -lt 2) {
		Write-Error "Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module or CommonModule.Name"
		exit 1
	}
	$objType = $parts[0]
	$objName = $parts[1]
	if (-not $typeDirMap.ContainsKey($objType)) {
		Write-Error "Unknown object type: $objType"
		exit 1
	}
	$dirName = $typeDirMap[$objType]

	if ($objType -eq "CommonModule" -or $objType -eq "CommonModules") {
		$relPath = "$dirName/$objName/Ext/Module.bsl"
	} elseif ($parts.Count -ge 4 -and $parts[2] -eq "Form") {
		$isFormModule = $true
		$relPath = "$dirName/$objName/Forms/$($parts[3])/Ext/Form/Module.bsl"
	} elseif ($parts.Count -ge 3) {
		$moduleFileName = switch ($parts[2]) {
			"ObjectModule"    { "ObjectModule.bsl" }
			"ManagerModule"   { "ManagerModule.bsl" }
			"RecordSetModule" { "RecordSetModule.bsl" }
			"CommandModule"   { "CommandModule.bsl" }
			default           { "$($parts[2]).bsl" }
		}
		$relPath = "$dirName/$objName/Ext/$moduleFileName"
	} else {
		Write-Error "Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module, Type.Name.Form.FormName, or CommonModule.Name"
		exit 1
	}
}

$bslFile = Join-Path $ExtensionPath ($relPath -replace "/", [string][char]92)
$origFile = if ($configRoot) { Join-Path $configRoot ($relPath -replace "/", [string][char]92) } else { "" }

# --- Оригинал: сигнатура, тело, директива, препроцессор ---
$origParams = ""
$origBody = @()
$origIsFunction = $IsFunction.IsPresent
$origDirective = ""
$origPreproc = ""
if ($origFile) {
	if (-not (Test-Path $origFile)) {
		[Console]::Error.WriteLine("Ошибка: модуль основной конфигурации не найден: $origFile")
		exit 1
	}
	$info = Find-Method (Read-Bsl $origFile) $MethodName
	if ($null -eq $info) {
		[Console]::Error.WriteLine("Ошибка: метод $MethodName не найден в $origFile")
		exit 1
	}
	$origIsFunction = $info.IsFunction
	$origParams = $info.Params
	$origBody = $info.Body
	$origDirective = $info.Directive
	$origPreproc = $info.Preproc
}

# Платформа не поддерживает Перед и После у функции: перехватчик обязан вернуть значение,
# а эти виды его не возвращают. Для функции применимы Вместо и ИзменениеИКонтроль.
if ($origIsFunction -and @("Before", "After") -contains $InterceptorType) {
	[Console]::Error.WriteLine("Ошибка: функция перехватывается только видами Instead и ModificationAndControl, а не $InterceptorType")
	exit 1
}

$decorator = switch ($InterceptorType) {
	"Before"                  { "&Перед" }
	"After"                   { "&После" }
	"Instead"                 { "&Вместо" }
	"ModificationAndControl"  { "&ИзменениеИКонтроль" }
}

$procName = "${namePrefix}${MethodName}"

# --- Ресинк, если перехватчик уже стоит ---
if ((Test-Path $bslFile) -and $InterceptorType -eq "ModificationAndControl") {
	$existingText = Read-Bsl $bslFile
	if ($existingText -match ([regex]::Escape("$decorator(`"$MethodName`")"))) {
		$res = Resync-Interceptor -ExtFile $bslFile -OrigFile $origFile -Method $MethodName -ProcName $procName -Apply
		switch ($res.Status) {
			"actual" {
				Write-Host "[АКТУАЛЕН] $objType.$objName.$MethodName - оригинал не менялся"
				exit 0
			}
			"transferred" {
				Write-Host "[ПЕРЕНЕСЕНО В ОСНОВНУЮ] $objType.$objName.$MethodName"
				Write-Host "     перенесено в основную конфигурацию: $($res.Transferred)"
				foreach ($c in $res.Orphan) { Write-Host "     [!] комментарий не перенесен: $c" }
				exit 0
			}
			"partial" {
				Write-Host "[АКТУАЛИЗИРОВАН-ЧАСТИЧНО] $objType.$objName.$MethodName"
				Write-Host "     правок сохранено: $($res.Kept)"
				Write-Host "     перенесено в основную конфигурацию: $($res.Transferred)"
				Write-Host "     конфликтов: $($res.Conflicts)"
				exit 0
			}
			"updated" {
				Write-Host "[АКТУАЛИЗИРОВАН] $objType.$objName.$MethodName"
				Write-Host "     правок сохранено: $($res.Kept)"
				Write-Host "     перенесено в основную конфигурацию: $($res.Transferred)"
				foreach ($c in $res.Orphan) { Write-Host "     [!] комментарий не перенесен: $c" }
				exit 0
			}
			default {
				[Console]::Error.WriteLine("Ошибка: оригинал метода $MethodName не найден в основной конфигурации")
				exit 1
			}
		}
	}
}

# --- Директива компиляции ---
# У модуля формы она берется из оригинала: обработчик, объявленный на клиенте, на сервере
# не свяжется. У прочих модулей директива не пишется вовсе.
if ($isFormModule) {
	if ($origDirective) {
		$contextAnnotation = $origDirective
	} else {
		if (-not $PSBoundParameters.ContainsKey('Context')) { $Context = "НаКлиенте" }
		$contextAnnotation = if ($Context.StartsWith("&")) { $Context } else { "&$Context" }
	}
} else {
	$contextAnnotation = if ($Context.StartsWith("&")) { $Context } else { "&$Context" }
}

# --- Тело перехватчика ---
$keyword = if ($origIsFunction) { "Функция" } else { "Процедура" }
$endKeyword = if ($origIsFunction) { "КонецФункции" } else { "КонецПроцедуры" }

$bodyLines = @()
switch ($InterceptorType) {
	"Before" {
		$bodyLines += "`t// TODO: код перед вызовом оригинального метода"
	}
	"After" {
		$bodyLines += "`t// TODO: код после вызова оригинального метода"
	}
	"Instead" {
		# Оригинал вызывается явно: платформа передает его через ПродолжитьВызов.
		$callArgs = if ($origParams) {
			(($origParams -split ",") | ForEach-Object { ($_ -split "=")[0].Trim() -replace "^Знач\s+", "" }) -join ", "
		} else { "" }
		if ($origIsFunction) {
			$bodyLines += "`tРезультат = ПродолжитьВызов($callArgs);"
			$bodyLines += "`t// TODO: доработать поведение"
			$bodyLines += "`tВозврат Результат;"
		} else {
			$bodyLines += "`tПродолжитьВызов($callArgs);"
			$bodyLines += "`t// TODO: доработать поведение"
		}
	}
	"ModificationAndControl" {
		if ($origBody.Count -gt 0) {
			$bodyLines += $origBody
		} else {
			$bodyLines += "`t// Скопируйте тело оригинального метода и внесите правки,"
			$bodyLines += "`t// используя маркеры $MARK_INS_START / $MARK_DEL_START"
		}
	}
}

$bslCode = @()
if ($isFormModule) { $bslCode += $contextAnnotation }
$bslCode += "${decorator}(`"$MethodName`")"
$bslCode += "$keyword ${procName}($origParams)"
$bslCode += $bodyLines
$bslCode += "$endKeyword"

# Область зависит от вида модуля - так же, как ее заводит Конфигуратор.
$regionName = if ($isFormModule) {
	"ОбработчикиСобытийФормы"
} elseif ($objType -eq "CommonModule") {
	"ПрограммныйИнтерфейс"
} else {
	"ОбработчикиСобытий"
}

# --- Предупреждение о незаимствованной форме ---
if ($isFormModule) {
	$formSegs = @(($relPath -replace "\\", "/") -split "/")
	$formIdx = [array]::IndexOf($formSegs, "Forms")
	if ($formIdx -ge 0 -and $formSegs.Count -gt $formIdx + 1) {
		$formName = $formSegs[$formIdx + 1]
		$formsRoot = Join-Path (Join-Path (Join-Path $ExtensionPath $typeDirMap[$objType]) $objName) "Forms"
		$formMetaFile = Join-Path $formsRoot "${formName}.xml"
		$formXmlFile = Join-Path (Join-Path $formsRoot $formName) "Ext/Form.xml"
		if (-not (Test-Path $formMetaFile) -or -not (Test-Path $formXmlFile)) {
			Write-Host "[WARN] Form '$formName' metadata or Form.xml not found in extension."
			Write-Host "       Run /cfe-borrow first:"
			Write-Host "       /cfe-borrow -ExtensionPath $ExtensionPath -ConfigPath <ConfigPath> -Object `"$objType.$objName.Form.$formName`""
			Write-Host ""
		}
	}
}

# --- Размещение в модуле расширения ---
$bslDir = Split-Path $bslFile -Parent
if (-not (Test-Path $bslDir)) {
	New-Item -ItemType Directory -Path $bslDir -Force | Out-Null
}

$placement = ""
$hasContent = (Test-Path $bslFile) -and ((Read-Bsl $bslFile).Trim() -ne "")
if ($hasContent) {
	$lines = [System.Collections.Generic.List[string]]::new()
	foreach ($l in (Split-Lines (Read-Bsl $bslFile))) { [void]$lines.Add($l) }

	# Хвостовой перевод строки дает пустой элемент - он мешает искать конец региона.
	while ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -eq "") { $lines.RemoveAt($lines.Count - 1) }

	$regionIdx = -1
	for ($i = 0; $i -lt $lines.Count; $i++) {
		if ($lines[$i].Trim() -eq "#Область $regionName") { $regionIdx = $i; break }
	}

	# Условие препроцессора вокруг оригинала должно охватывать и перехватчик. Если файл
	# такого условия не содержит, метод оборачивается отдельно.
	$fileHasPreproc = $false
	if ($origPreproc) {
		foreach ($l in $lines) {
			if ($l.Trim() -eq "#Если $origPreproc Тогда") { $fileHasPreproc = $true; break }
		}
		if (-not $fileHasPreproc) {
			$bslCode = @("#Если $origPreproc Тогда", "") + $bslCode + @("", "#КонецЕсли")
		}
	}

	if ($regionIdx -ge 0) {
		$endIdx = -1
		for ($i = $regionIdx + 1; $i -lt $lines.Count; $i++) {
			if ($lines[$i].Trim() -eq "#КонецОбласти") { $endIdx = $i; break }
		}
		if ($endIdx -lt 0) { $endIdx = $lines.Count }
		while ($endIdx -gt $regionIdx + 1 -and $lines[$endIdx - 1].Trim() -eq "") { $endIdx-- }
		$insert = @("") + $bslCode
		$lines.InsertRange($endIdx, [string[]]$insert)
		$placement = "в существующий регион $regionName"
	} else {
		$block = @("", "#Область $regionName", "") + $bslCode + @("", "#КонецОбласти")
		# Внутри условия препроцессора регион ставится до его закрытия.
		$closeIdx = -1
		for ($i = $lines.Count - 1; $i -ge 0; $i--) {
			if ($lines[$i].Trim() -eq "#КонецЕсли") { $closeIdx = $i; break }
		}
		if ($closeIdx -ge 0) {
			$lines.InsertRange($closeIdx, [string[]]$block)
		} else {
			$lines.AddRange([string[]]$block)
		}
		$placement = "в новый регион $regionName"
	}
	$newContent = ($lines -join "`r`n") + "`r`n"
	[System.IO.File]::WriteAllText($bslFile, $newContent, $enc)
	Write-Host "[OK] Добавлен перехватчик $placement"
} else {
	$wrapped = @()
	if ($origPreproc) {
		$wrapped += "#Если $origPreproc Тогда"
		$wrapped += ""
	}
	$wrapped += "#Область $regionName"
	$wrapped += ""
	$wrapped += $bslCode
	$wrapped += ""
	$wrapped += "#КонецОбласти"
	if ($origPreproc) {
		$wrapped += ""
		$wrapped += "#КонецЕсли"
	}
	$bslText = ($wrapped -join "`r`n") + "`r`n"
	[System.IO.File]::WriteAllText($bslFile, $bslText, $enc)
	Write-Host "[OK] Создан файл модуля"
}

Write-Host "     Файл:         $bslFile"
Write-Host "     Декоратор:    $decorator(`"$MethodName`")"
Write-Host "     Процедура:    ${procName}()"
if ($origPreproc) { Write-Host "     Препроцессор: #Если:$origPreproc" }
Write-Host "     Контекст:   $contextAnnotation"
