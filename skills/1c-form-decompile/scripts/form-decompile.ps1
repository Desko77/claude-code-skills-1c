# form-decompile v1.0 - Decompile 1C managed form (Form.xml) to JSON DSL draft
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$InputFile,

	[string]$OutputFile
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# XML tag -> DSL type key (form-dsl-spec.md, section 4.3)
$ELEMENT_MAP = @{
	"UsualGroup"        = "group"
	"InputField"        = "input"
	"CheckBoxField"     = "check"
	"LabelDecoration"   = "label"
	"LabelField"        = "labelField"
	"Table"             = "table"
	"Pages"             = "pages"
	"Page"              = "page"
	"Button"            = "button"
	"PictureDecoration" = "picture"
	"PictureField"      = "picField"
	"CalendarField"     = "calendar"
	"CommandBar"        = "cmdBar"
	"Popup"             = "popup"
}

# Reverse of form-compile PROP_MAP; fallback is first-char lowercase
$PROP_REVERSE = @{
	"AutoTitle"              = "autoTitle"
	"WindowOpeningMode"      = "windowOpeningMode"
	"CommandBarLocation"     = "commandBarLocation"
	"SaveDataInSettings"     = "saveDataInSettings"
	"AutoSaveDataInSettings" = "autoSaveDataInSettings"
	"AutoTime"               = "autoTime"
	"UsePostingMode"         = "usePostingMode"
	"RepostOnWrite"          = "repostOnWrite"
	"AutoURL"                = "autoURL"
	"AutoFillCheck"          = "autoFillCheck"
	"Customizable"           = "customizable"
	"EnterKeyBehavior"       = "enterKeyBehavior"
	"VerticalScroll"         = "verticalScroll"
	"ScalingMode"            = "scalingMode"
	"UseForFoldersAndItems"  = "useForFoldersAndItems"
	"ReportResult"           = "reportResult"
	"DetailsData"            = "detailsData"
	"ReportFormType"         = "reportFormType"
	"AutoShowState"          = "autoShowState"
	"Width"                  = "width"
	"Height"                 = "height"
	"Group"                  = "group"
}

$FORM_STRUCTURAL_TAGS = @(
	"Title", "CommandSet", "AutoCommandBar", "Events", "ChildItems",
	"Attributes", "Parameters", "Commands", "CommandInterface",
	"ConditionalAppearance", "MobileDeviceCommandBarContent"
)

$GROUP_ORIENTATION_REVERSE = @{
	"Horizontal"       = "horizontal"
	"Vertical"         = "vertical"
	"AlwaysHorizontal" = "alwaysHorizontal"
	"AlwaysVertical"   = "alwaysVertical"
}

$GROUP_REPRESENTATION_REVERSE = @{
	"None"             = "none"
	"NormalSeparation" = "normal"
	"WeakSeparation"   = "weak"
	"StrongSeparation" = "strong"
}

$TITLE_LOCATION_REVERSE = @{
	"None" = "none"; "Left" = "left"; "Right" = "right"; "Top" = "top"; "Bottom" = "bottom"
}

$BUTTON_TYPE_REVERSE = @{
	"UsualButton" = "usual"; "Hyperlink" = "hyperlink"; "CommandBarButton" = "commandBar"
}

$PLATFORM_TYPE_REVERSE = @{
	"v8:ValueTable"                       = "ValueTable"
	"v8:ValueTree"                        = "ValueTree"
	"v8:ValueListType"                    = "ValueList"
	"v8:TypeDescription"                  = "TypeDescription"
	"v8:Universal"                        = "Universal"
	"v8:FixedArray"                       = "FixedArray"
	"v8:FixedStructure"                   = "FixedStructure"
	"v8:UUID"                             = "UUID"
	"v8ui:FormattedString"                = "FormattedString"
	"v8ui:Picture"                        = "Picture"
	"v8ui:Color"                          = "Color"
	"v8ui:Font"                           = "Font"
	"dcsset:DataCompositionSettings"      = "DataCompositionSettings"
	"dcssch:DataCompositionSchema"        = "DataCompositionSchema"
	"dcscor:DataCompositionComparisonType" = "DataCompositionComparisonType"
}

# Same table as in form-compile: auto handler = element name + suffix
$EVENT_SUFFIX_MAP = @{
	"OnChange"            = "ПриИзменении"
	"StartChoice"         = "НачалоВыбора"
	"ChoiceProcessing"    = "ОбработкаВыбора"
	"AutoComplete"        = "АвтоПодбор"
	"Clearing"            = "Очистка"
	"Opening"             = "Открытие"
	"Click"               = "Нажатие"
	"OnActivateRow"       = "ПриАктивизацииСтроки"
	"BeforeAddRow"        = "ПередНачаломДобавления"
	"BeforeDeleteRow"     = "ПередУдалением"
	"BeforeRowChange"     = "ПередНачаломИзменения"
	"OnStartEdit"         = "ПриНачалеРедактирования"
	"OnEndEdit"           = "ПриОкончанииРедактирования"
	"Selection"           = "ВыборСтроки"
	"OnCurrentPageChange" = "ПриСменеСтраницы"
	"TextEditEnd"         = "ОкончаниеВводаТекста"
	"URLProcessing"       = "ОбработкаНавигационнойСсылки"
	"DragStart"           = "НачалоПеретаскивания"
	"Drag"                = "Перетаскивание"
	"DragCheck"           = "ПроверкаПеретаскивания"
	"Drop"                = "Помещение"
	"AfterDeleteRow"      = "ПослеУдаления"
}

$script:TodoCount = 0

function Get-ElemChildren($node) {
	$result = @()
	foreach ($ch in $node.ChildNodes) {
		if ($ch.NodeType -eq [System.Xml.XmlNodeType]::Element) { $result += $ch }
	}
	return ,$result
}

function Add-Todo($todos, [string]$msg) {
	$script:TodoCount++
	[void]$todos.Add($msg)
	[Console]::Error.WriteLine("[TODO] " + $msg)
}

function Test-EmptyNode($node) {
	$children = Get-ElemChildren $node
	if ($children.Count -gt 0) { return $false }
	return -not ($node.InnerText.Trim())
}

function ConvertTo-Bool([string]$text) {
	return ($text.Trim() -eq "true")
}

function Convert-Scalar([string]$text) {
	$t = $text.Trim()
	if ($t -eq "true") { return $true }
	if ($t -eq "false") { return $false }
	if ($t -match '^-?\d+$') {
		$parsed = [long]0
		if ([long]::TryParse($t, [ref]$parsed)) { return $parsed }
		return $t
	}
	return $t
}

# Дополнения командной панели динамического списка: тег в XML - ключ типа в DSL.
$script:AdditionTags = @{
	"SearchStringAddition"  = "searchString"
	"ViewStatusAddition"    = "viewStatus"
	"SearchControlAddition" = "searchControl"
}

# Положение в панели: основное написание платформы в ключ DSL.
$script:LocationBack = @{ "Left" = "left"; "Right" = "right"; "Center" = "center" }

function Read-Addition {
	param($node, [string]$tableName)
	# Спутники не переносятся: компилятор выдает их сам по имени дополнения.
	$kind = $script:AdditionTags[$node.LocalName]
	$el = [ordered]@{ $kind = $node.GetAttribute("name") }
	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName
		if ($ln -eq "AdditionSource") {
			$source = ""
			foreach ($sub in (Get-ElemChildren $ch)) {
				if ($sub.LocalName -eq "Item") { $source = Get-NodeText $sub }
			}
			if ($source -and $source -ne $tableName) { $el["source"] = $source }
		} elseif ($ln -eq "Title") {
			$title = Get-MLText $ch @() "Дополнение"
			if ($null -ne $title) { $el["title"] = $title }
		} elseif ($ln -eq "Width") {
			$el["width"] = Convert-Scalar (Get-NodeText $ch)
		} elseif ($ln -eq "HorizontalStretch") {
			$el["horizontalStretch"] = ConvertTo-Bool (Get-NodeText $ch)
		} elseif ($ln -eq "HorizontalLocation") {
			$value = Get-NodeText $ch
			if ($script:LocationBack.ContainsKey($value)) { $el["horizontalLocation"] = $script:LocationBack[$value] }
			else { $el["horizontalLocation"] = $value }
		} elseif ($ln -eq "Visible") {
			$el["visible"] = ConvertTo-Bool (Get-NodeText $ch)
		}
	}
	return $el
}

function Get-NodeText($node) {
	return $node.InnerText.Trim()
}

function Get-MLText($node, $todos, [string]$owner) {
	$ruVal = $null
	$firstVal = $null
	$items = 0
	foreach ($item in (Get-ElemChildren $node)) {
		if ($item.LocalName -ne "item") { continue }
		$lang = $null
		$content = $null
		foreach ($sub in (Get-ElemChildren $item)) {
			if ($sub.LocalName -eq "lang") { $lang = $sub.InnerText.Trim() }
			elseif ($sub.LocalName -eq "content") { $content = $sub.InnerText }
		}
		if ($null -eq $content) { continue }
		$items++
		if ($null -eq $firstVal) { $firstVal = $content }
		if (($lang -eq "ru") -and ($null -eq $ruVal)) { $ruVal = $content }
	}
	if ($items -gt 1) {
		Add-Todo $todos ($owner + ": мультиязычный текст, взят один язык (ru или первый)")
	}
	$best = $firstVal
	if ($null -ne $ruVal) { $best = $ruVal }
	if ($null -ne $best) { return $best }
	$t = $node.InnerText.Trim()
	if ($t) { return $t }
	return $null
}

function Get-BaseTypeToken([string]$raw) {
	if ($raw -eq "xs:string") { return "string" }
	if ($raw -eq "xs:decimal") { return "decimal" }
	if ($raw -eq "xs:boolean") { return "boolean" }
	if ($raw -eq "xs:dateTime") { return "dateTime" }
	if ($raw.StartsWith("cfg:")) { return $raw.Substring(4) }
	if ($PLATFORM_TYPE_REVERSE.ContainsKey($raw)) { return $PLATFORM_TYPE_REVERSE[$raw] }
	return $raw
}

function Convert-TypeNode($typeNode, $todos, [string]$owner) {
	$parts = New-Object System.Collections.ArrayList
	foreach ($ch in (Get-ElemChildren $typeNode)) {
		$ln = $ch.LocalName
		if ($ln -eq "Type") {
			[void]$parts.Add((Get-BaseTypeToken (Get-NodeText $ch)))
		}
		elseif ($ln -eq "StringQualifiers") {
			$length = "0"
			$allowed = ""
			foreach ($q in (Get-ElemChildren $ch)) {
				if ($q.LocalName -eq "Length") { $length = Get-NodeText $q }
				elseif ($q.LocalName -eq "AllowedLength") { $allowed = Get-NodeText $q }
			}
			if (($parts.Count -gt 0) -and ($parts[$parts.Count - 1] -eq "string") -and ($length -ne "") -and ($length -ne "0")) {
				$parts[$parts.Count - 1] = "string(" + $length + ")"
			}
			if ($allowed -eq "Fixed") {
				Add-Todo $todos ($owner + ": AllowedLength=Fixed не выражается в DSL")
			}
		}
		elseif ($ln -eq "NumberQualifiers") {
			$digits = "0"
			$fraction = "0"
			$sign = ""
			foreach ($q in (Get-ElemChildren $ch)) {
				if ($q.LocalName -eq "Digits") { $digits = Get-NodeText $q }
				elseif ($q.LocalName -eq "FractionDigits") { $fraction = Get-NodeText $q }
				elseif ($q.LocalName -eq "AllowedSign") { $sign = Get-NodeText $q }
			}
			if (($parts.Count -gt 0) -and ($parts[$parts.Count - 1] -eq "decimal")) {
				$suffix = ""
				if ($sign -eq "Nonnegative") { $suffix = ",nonneg" }
				$parts[$parts.Count - 1] = "decimal(" + $digits + "," + $fraction + $suffix + ")"
			}
		}
		elseif ($ln -eq "DateQualifiers") {
			$fractions = ""
			foreach ($q in (Get-ElemChildren $ch)) {
				if ($q.LocalName -eq "DateFractions") { $fractions = Get-NodeText $q }
			}
			$dfMap = @{ "Date" = "date"; "Time" = "time"; "DateTime" = "dateTime" }
			if (($parts.Count -gt 0) -and ($parts[$parts.Count - 1] -eq "dateTime") -and $dfMap.ContainsKey($fractions)) {
				$parts[$parts.Count - 1] = $dfMap[$fractions]
			}
		}
		elseif (($ln -eq "TypeSet") -or ($ln -eq "TypeId")) {
			Add-Todo $todos ($owner + ": <v8:" + $ln + "> (" + (Get-NodeText $ch) + ") не выражается в DSL")
		}
		else {
			Add-Todo $todos ($owner + ": узел типа " + $ln + " не разобран")
		}
	}
	$fixed = @()
	foreach ($p in $parts) {
		if ($p -eq "decimal") { $fixed += "decimal(0,0)" }
		elseif ($p) { $fixed += $p }
	}
	return ($fixed -join " | ")
}

function Get-PictureRef($node, $todos, [string]$owner) {
	$ref = $null
	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName
		if ($ln -eq "Ref") { $ref = Get-NodeText $ch }
		elseif ($ln -eq "LoadTransparent") { }
		else {
			Add-Todo $todos ($owner + ": картинка задана не ссылкой xr:Ref (" + $ln + ")")
		}
	}
	return $ref
}

function Read-ElementEvents($node, [string]$elName, $el) {
	$on = New-Object System.Collections.ArrayList
	$handlers = [ordered]@{}
	foreach ($ev in (Get-ElemChildren $node)) {
		if ($ev.LocalName -ne "Event") { continue }
		$evName = $ev.GetAttribute("name")
		$handler = $ev.InnerText.Trim()
		if ((-not $evName) -or (-not $handler)) { continue }
		[void]$on.Add($evName)
		$suffix = $EVENT_SUFFIX_MAP[$evName]
		if ($suffix) { $auto = $elName + $suffix } else { $auto = $elName + $evName }
		if ($handler -cne $auto) {
			$handlers[$evName] = $handler
		}
	}
	if ($on.Count -gt 0) { $el["on"] = $on }
	if ($handlers.Count -gt 0) { $el["handlers"] = $handlers }
}

function Invoke-CommonChild($ch, [string]$ln, $el, [string]$name, $todos) {
	# Returns $true if the child was consumed by a common rule
	if ($ln -eq "Title") {
		$t = Get-MLText $ch $todos ("Элемент '" + $name + "'")
		if ($null -ne $t) { $el["title"] = $t }
		return $true
	}
	if ($ln -eq "Visible") {
		if ((Get-NodeText $ch) -eq "false") { $el["hidden"] = $true }
		return $true
	}
	if ($ln -eq "Enabled") {
		if ((Get-NodeText $ch) -eq "false") { $el["disabled"] = $true }
		return $true
	}
	if ($ln -eq "ReadOnly") {
		if ((Get-NodeText $ch) -eq "true") { $el["readOnly"] = $true }
		return $true
	}
	if ($ln -eq "UserVisible") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			if ($sub.LocalName -eq "Common") {
				if ((Get-NodeText $sub) -eq "false") { $el["userVisible"] = $false }
			}
			else {
				Add-Todo $todos ("Элемент '" + $name + "': UserVisible по ролям не поддержан DSL")
			}
		}
		return $true
	}
	if ($ln -eq "Events") {
		Read-ElementEvents $ch $name $el
		return $true
	}
	if (@("ContextMenu", "ExtendedTooltip", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition") -contains $ln) {
		if (Test-EmptyNode $ch) { return $true }
		# Штатное дополнение таблицы с содержимым: пустое дополнение компилятор выдает сам,
		# поэтому переносятся только отличия от умолчания.
		if ($script:AdditionTags.ContainsKey($ln)) {
			$kind = $script:AdditionTags[$ln]
			$settings = Read-Addition -node $ch -tableName $name
			$settings.Remove($kind)
			if ($settings.Count -gt 0) {
				if (-not $el.Contains("additions")) { $el["additions"] = [ordered]@{} }
				$el["additions"][$kind] = $settings
			}
			return $true
		}
		Add-Todo $todos ("Элемент '" + $name + "': служебный элемент " + $ln + " с содержимым не перенесен (генерируется заново)")
		return $true
	}
	return $false
}

function Add-UnknownChild($ch, [string]$ln, [string]$name, $todos) {
	$children = Get-ElemChildren $ch
	if ($children.Count -eq 0) {
		Add-Todo $todos ("Элемент '" + $name + "': свойство " + $ln + "=" + (Get-NodeText $ch) + " не поддержано DSL")
	}
	else {
		Add-Todo $todos ("Элемент '" + $name + "': узел " + $ln + " не поддержан DSL")
	}
}

function Read-ChildItems($node, [string]$containerKey, $el) {
	$items = New-Object System.Collections.ArrayList
	foreach ($sub in (Get-ElemChildren $node)) {
		$parsed = Read-Element $sub
		if ($null -ne $parsed) { [void]$items.Add($parsed) }
	}
	$el[$containerKey] = $items
}

function Test-ExtraAttrs($node, [string]$name, $todos) {
	foreach ($attr in $node.Attributes) {
		$an = $attr.LocalName
		if (($an -eq "name") -or ($an -eq "id")) { continue }
		Add-Todo $todos ("Элемент '" + $name + "': XML-атрибут " + $an + "=" + $attr.Value + " не поддержан DSL")
	}
}

function Read-Element($node) {
	$tag = $node.LocalName
	$name = $node.GetAttribute("name")
	$todos = New-Object System.Collections.ArrayList

	if (-not $ELEMENT_MAP.ContainsKey($tag)) {
		Add-Todo $todos ("Элемент " + $tag + " '" + $name + "' не поддержан DSL 1c-form-compile - создать вручную")
		$placeholder = [ordered]@{}
		$placeholder["name"] = $name
		$placeholder["_todo"] = $todos
		return $placeholder
	}

	$key = $ELEMENT_MAP[$tag]
	$el = [ordered]@{}

	if ($key -eq "group") {
		$orientation = ""
		$collapsible = $false
		foreach ($ch in (Get-ElemChildren $node)) {
			$ln = $ch.LocalName
			if ($ln -eq "Group") {
				$v = Get-NodeText $ch
				if ($GROUP_ORIENTATION_REVERSE.ContainsKey($v)) { $orientation = $GROUP_ORIENTATION_REVERSE[$v] } else { $orientation = $v }
			}
			elseif (($ln -eq "Behavior") -and ((Get-NodeText $ch) -eq "Collapsible")) {
				$collapsible = $true
			}
		}
		if ($collapsible) { $orientation = "collapsible" }
		elseif (-not $orientation) { $orientation = "vertical" }
		$el["group"] = $orientation
		$el["name"] = $name
	}
	else {
		$el[$key] = $name
	}

	Test-ExtraAttrs $node $name $todos

	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName

		if (($key -eq "group") -and (($ln -eq "Group") -or ($ln -eq "Behavior"))) { continue }
		if (Invoke-CommonChild $ch $ln $el $name $todos) { continue }

		if ($key -eq "group") {
			if ($ln -eq "Representation") {
				$v = Get-NodeText $ch
				if ($GROUP_REPRESENTATION_REVERSE.ContainsKey($v)) { $el["representation"] = $GROUP_REPRESENTATION_REVERSE[$v] } else { $el["representation"] = $v }
			}
			elseif ($ln -eq "ShowTitle") { $el["showTitle"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "United") { $el["united"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "children" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "input") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			elseif ($ln -eq "TitleLocation") {
				$v = Get-NodeText $ch
				if ($TITLE_LOCATION_REVERSE.ContainsKey($v)) { $el["titleLocation"] = $TITLE_LOCATION_REVERSE[$v] } else { $el["titleLocation"] = $v }
			}
			elseif ($ln -eq "MultiLine") { $el["multiLine"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "PasswordMode") { $el["passwordMode"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ChoiceButton") { $el["choiceButton"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ClearButton") { $el["clearButton"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "SpinButton") { $el["spinButton"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "DropListButton") { $el["dropListButton"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "AutoMarkIncomplete") { $el["markIncomplete"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "SkipOnInput") { $el["skipOnInput"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "AutoMaxWidth") { $el["autoMaxWidth"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "AutoMaxHeight") { $el["autoMaxHeight"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "Width") { $el["width"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "Height") { $el["height"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "HorizontalStretch") { $el["horizontalStretch"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "VerticalStretch") { $el["verticalStretch"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "InputHint") {
				$t = Get-MLText $ch $todos ("Элемент '" + $name + "'")
				if ($null -ne $t) { $el["inputHint"] = $t }
			}
			elseif ($ln -eq "EditMode") { $el["editMode"] = Get-NodeText $ch }
			elseif ($ln -eq "Wrap") { $el["wrap"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ChooseType") { $el["chooseType"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "TextEdit") { $el["textEdit"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "TypeDomainEnabled") { $el["typeDomainEnabled"] = ConvertTo-Bool (Get-NodeText $ch) }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "check") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			elseif ($ln -eq "TitleLocation") { $el["titleLocation"] = Get-NodeText $ch }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "label") {
			if ($ln -eq "Hyperlink") { $el["hyperlink"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "AutoMaxWidth") { $el["autoMaxWidth"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "AutoMaxHeight") { $el["autoMaxHeight"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "Width") { $el["width"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "Height") { $el["height"] = Convert-Scalar (Get-NodeText $ch) }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "labelField") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			elseif ($ln -eq "Hyperlink") { $el["hyperlink"] = ConvertTo-Bool (Get-NodeText $ch) }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "table") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			elseif ($ln -eq "Representation") { $el["representation"] = Get-NodeText $ch }
			elseif ($ln -eq "ChangeRowSet") { $el["changeRowSet"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ChangeRowOrder") { $el["changeRowOrder"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "HeightInTableRows") { $el["height"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "Header") { $el["header"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "Footer") { $el["footer"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "CommandBarLocation") { $el["commandBarLocation"] = Get-NodeText $ch }
			elseif ($ln -eq "SearchStringLocation") { $el["searchStringLocation"] = Get-NodeText $ch }
			elseif ($ln -eq "TitleLocation") { $el["titleLocation"] = Get-NodeText $ch }
			elseif ($ln -eq "ChoiceMode") { $el["choiceMode"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "InitialTreeView") { $el["initialTreeView"] = Get-NodeText $ch }
			elseif ($ln -eq "EnableStartDrag") { $el["enableStartDrag"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "EnableDrag") { $el["enableDrag"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "RowPictureDataPath") { $el["rowPictureDataPath"] = Get-NodeText $ch }
			elseif ($ln -eq "AutoCommandBar") {
				foreach ($sub in (Get-ElemChildren $ch)) {
					if ($sub.LocalName -eq "Autofill") { $el["tableAutofill"] = ConvertTo-Bool (Get-NodeText $sub) }
					elseif ($sub.LocalName -eq "ChildItems") {
						$bar = @()
						foreach ($item in (Get-ElemChildren $sub)) {
							if ($script:AdditionTags.ContainsKey($item.LocalName)) {
								$bar += (Read-Addition -node $item -tableName $name)
							} else {
								$parsed = Read-Element $item
								if ($null -ne $parsed) { $bar += $parsed }
							}
						}
						if ($bar.Count -gt 0) { $el["commandBar"] = $bar }
					}
					else { Add-Todo $todos ("Элемент '" + $name + "': содержимое AutoCommandBar (" + $sub.LocalName + ") не поддержано DSL") }
				}
			}
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "columns" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "pages") {
			if ($ln -eq "PagesRepresentation") { $el["pagesRepresentation"] = Get-NodeText $ch }
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "children" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "page") {
			if ($ln -eq "Group") {
				$v = Get-NodeText $ch
				if ($GROUP_ORIENTATION_REVERSE.ContainsKey($v)) { $el["group"] = $GROUP_ORIENTATION_REVERSE[$v] } else { $el["group"] = $v }
			}
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "children" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "button") {
			if ($ln -eq "Type") {
				$v = Get-NodeText $ch
				if ($BUTTON_TYPE_REVERSE.ContainsKey($v)) { $el["type"] = $BUTTON_TYPE_REVERSE[$v] } else { $el["type"] = $v }
			}
			elseif ($ln -eq "CommandName") {
				$cn = Get-NodeText $ch
				if ($cn -match '^Form\.Item\.(.+)\.StandardCommand\.(.+)$') {
					$el["stdCommand"] = $Matches[1] + "." + $Matches[2]
				}
				elseif ($cn -match '^Form\.StandardCommand\.(.+)$') {
					$el["stdCommand"] = $Matches[1]
				}
				elseif ($cn -match '^Form\.Command\.(.+)$') {
					$el["command"] = $Matches[1]
				}
				else {
					Add-Todo $todos ("Элемент '" + $name + "': CommandName '" + $cn + "' не распознан")
				}
			}
			elseif ($ln -eq "DefaultButton") { $el["defaultButton"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "Picture") {
				$ref = Get-PictureRef $ch $todos ("Элемент '" + $name + "'")
				if ($ref) { $el["picture"] = $ref }
			}
			elseif ($ln -eq "Representation") { $el["representation"] = Get-NodeText $ch }
			elseif ($ln -eq "LocationInCommandBar") { $el["locationInCommandBar"] = Get-NodeText $ch }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "picture") {
			if ($ln -eq "Picture") {
				$ref = Get-PictureRef $ch $todos ("Элемент '" + $name + "'")
				if ($ref) { $el["src"] = $ref }
			}
			elseif ($ln -eq "Hyperlink") { $el["hyperlink"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "Width") { $el["width"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "Height") { $el["height"] = Convert-Scalar (Get-NodeText $ch) }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "picField") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			elseif ($ln -eq "Width") { $el["width"] = Convert-Scalar (Get-NodeText $ch) }
			elseif ($ln -eq "Height") { $el["height"] = Convert-Scalar (Get-NodeText $ch) }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "calendar") {
			if ($ln -eq "DataPath") { $el["path"] = Get-NodeText $ch }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "cmdBar") {
			if ($ln -eq "Autofill") { $el["autofill"] = ConvertTo-Bool (Get-NodeText $ch) }
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "children" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		elseif ($key -eq "popup") {
			if ($ln -eq "Picture") {
				$ref = Get-PictureRef $ch $todos ("Элемент '" + $name + "'")
				if ($ref) { $el["picture"] = $ref }
			}
			elseif ($ln -eq "Representation") { $el["representation"] = Get-NodeText $ch }
			elseif ($ln -eq "ChildItems") { Read-ChildItems $ch "children" $el }
			else { Add-UnknownChild $ch $ln $name $todos }
		}
		else {
			Add-UnknownChild $ch $ln $name $todos
		}
	}

	if ($todos.Count -gt 0) { $el["_todo"] = $todos }
	return $el
}

function Read-Attribute($node) {
	$name = $node.GetAttribute("name")
	$todos = New-Object System.Collections.ArrayList
	Test-ExtraAttrs $node $name $todos
	$title = $null
	$typeStr = $null
	$main = $false
	$savedData = $false
	$fillChecking = $null
	$columns = $null
	$settings = $null

	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName
		if ($ln -eq "Title") {
			$title = Get-MLText $ch $todos ("Реквизит '" + $name + "'")
		}
		elseif ($ln -eq "Type") {
			$typeStr = Convert-TypeNode $ch $todos ("Реквизит '" + $name + "'")
		}
		elseif ($ln -eq "MainAttribute") {
			$main = ConvertTo-Bool (Get-NodeText $ch)
		}
		elseif ($ln -eq "SavedData") {
			$savedData = ConvertTo-Bool (Get-NodeText $ch)
		}
		elseif ($ln -eq "FillChecking") {
			$fillChecking = Get-NodeText $ch
		}
		elseif ($ln -eq "Columns") {
			$columns = New-Object System.Collections.ArrayList
			foreach ($col in (Get-ElemChildren $ch)) {
				if ($col.LocalName -ne "Column") {
					Add-Todo $todos ("Реквизит '" + $name + "': узел Columns/" + $col.LocalName + " не разобран")
					continue
				}
				$c = [ordered]@{}
				$c["name"] = $col.GetAttribute("name")
				foreach ($cc in (Get-ElemChildren $col)) {
					$cn = $cc.LocalName
					if ($cn -eq "Title") {
						$t = Get-MLText $cc $todos ("Колонка '" + $c["name"] + "'")
						if ($null -ne $t) { $c["title"] = $t }
					}
					elseif ($cn -eq "Type") {
						$ct = Convert-TypeNode $cc $todos ("Колонка '" + $c["name"] + "'")
						if ($ct) { $c["type"] = $ct }
					}
					else {
						Add-Todo $todos ("Колонка '" + $c["name"] + "': узел " + $cn + " не поддержан DSL")
					}
				}
				[void]$columns.Add($c)
			}
		}
		elseif ($ln -eq "Settings") {
			$xsiType = $ch.GetAttribute("type", $XSI_NS)
			if ($xsiType.EndsWith("DynamicList")) {
				$settings = [ordered]@{}
				foreach ($sc in (Get-ElemChildren $ch)) {
					$sn = $sc.LocalName
					if ($sn -eq "MainTable") { $settings["mainTable"] = Get-NodeText $sc }
					elseif ($sn -eq "DynamicDataRead") { $settings["dynamicDataRead"] = ConvertTo-Bool (Get-NodeText $sc) }
					elseif ($sn -eq "ManualQuery") {
						if (ConvertTo-Bool (Get-NodeText $sc)) { $settings["manualQuery"] = $true }
					}
					elseif ($sn -eq "Query") {
						Add-Todo $todos ("Реквизит '" + $name + "': текст запроса динамического списка не поддержан DSL: " + $sc.InnerText.Trim())
					}
					else {
						Add-Todo $todos ("Реквизит '" + $name + "': Settings/" + $sn + " не поддержан DSL")
					}
				}
			}
			else {
				Add-Todo $todos ("Реквизит '" + $name + "': Settings xsi:type='" + $xsiType + "' не поддержан DSL")
			}
		}
		else {
			Add-Todo $todos ("Реквизит '" + $name + "': узел " + $ln + " не поддержан DSL")
		}
	}

	$a = [ordered]@{}
	$a["name"] = $name
	if ($typeStr) { $a["type"] = $typeStr }
	if ($main) { $a["main"] = $true }
	if ($null -ne $title) { $a["title"] = $title }
	if ($savedData) { $a["savedData"] = $true }
	if ($fillChecking) { $a["fillChecking"] = $fillChecking }
	if ($null -ne $columns) { $a["columns"] = $columns }
	if ($null -ne $settings) { $a["settings"] = $settings }
	if ($todos.Count -gt 0) { $a["_todo"] = $todos }
	return $a
}

function Read-Parameter($node) {
	$name = $node.GetAttribute("name")
	$todos = New-Object System.Collections.ArrayList
	Test-ExtraAttrs $node $name $todos
	$p = [ordered]@{}
	$p["name"] = $name
	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName
		if ($ln -eq "Type") {
			$t = Convert-TypeNode $ch $todos ("Параметр '" + $name + "'")
			if ($t) { $p["type"] = $t }
		}
		elseif ($ln -eq "KeyParameter") {
			if (ConvertTo-Bool (Get-NodeText $ch)) { $p["key"] = $true }
		}
		else {
			Add-Todo $todos ("Параметр '" + $name + "': узел " + $ln + " не поддержан DSL")
		}
	}
	if ($todos.Count -gt 0) { $p["_todo"] = $todos }
	return $p
}

function Read-Command($node) {
	$name = $node.GetAttribute("name")
	$todos = New-Object System.Collections.ArrayList
	Test-ExtraAttrs $node $name $todos
	$action = $null
	$title = $null
	$shortcut = $null
	$picture = $null
	$representation = $null

	foreach ($ch in (Get-ElemChildren $node)) {
		$ln = $ch.LocalName
		if ($ln -eq "Action") { $action = Get-NodeText $ch }
		elseif ($ln -eq "Title") { $title = Get-MLText $ch $todos ("Команда '" + $name + "'") }
		elseif ($ln -eq "Shortcut") { $shortcut = Get-NodeText $ch }
		elseif ($ln -eq "Picture") { $picture = Get-PictureRef $ch $todos ("Команда '" + $name + "'") }
		elseif ($ln -eq "Representation") { $representation = Get-NodeText $ch }
		else { Add-Todo $todos ("Команда '" + $name + "': узел " + $ln + " не поддержан DSL") }
	}

	$c = [ordered]@{}
	$c["name"] = $name
	if ($action) { $c["action"] = $action }
	if ($null -ne $title) { $c["title"] = $title }
	if ($shortcut) { $c["shortcut"] = $shortcut }
	if ($picture) { $c["picture"] = $picture }
	if ($representation) { $c["representation"] = $representation }
	if ($todos.Count -gt 0) { $c["_todo"] = $todos }
	return $c
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

# --- Черновой JSON (общий блок, версия 2) ---
# Ширина строки, после которой контейнер разворачивается по элементу на строку.
$script:draftJsonWidth = 400

function ConvertTo-JsonStringLiteral($s) {
	$sb = New-Object System.Text.StringBuilder
	[void]$sb.Append('"')
	foreach ($ch in ([string]$s).ToCharArray()) {
		if ($ch -eq '"') { [void]$sb.Append('\"') }
		elseif ($ch -eq '\') { [void]$sb.Append('\\') }
		elseif ($ch -eq "`n") { [void]$sb.Append('\n') }
		elseif ($ch -eq "`r") { [void]$sb.Append('\r') }
		elseif ($ch -eq "`t") { [void]$sb.Append('\t') }
		elseif ([int]$ch -lt 32) { [void]$sb.Append('\u' + ([int]$ch).ToString('x4')) }
		else { [void]$sb.Append($ch) }
	}
	[void]$sb.Append('"')
	return $sb.ToString()
}

function ConvertTo-InlineJson($v) {
	if ($null -eq $v) { return 'null' }
	if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
	if ($v -is [int] -or $v -is [int64] -or $v -is [double] -or $v -is [decimal]) {
		return [System.Convert]::ToString($v, [System.Globalization.CultureInfo]::InvariantCulture)
	}
	if ($v -is [string]) { return ConvertTo-JsonStringLiteral $v }
	if ($v -is [System.Collections.IDictionary]) {
		if ($v.Count -eq 0) { return '{}' }
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($k in $v.Keys) {
			[void]$parts.Add((ConvertTo-JsonStringLiteral ([string]$k)) + ': ' + (ConvertTo-InlineJson $v[$k]))
		}
		return '{ ' + ($parts -join ', ') + ' }'
	}
	if ($v -is [System.Collections.IEnumerable]) {
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($it in $v) { [void]$parts.Add((ConvertTo-InlineJson $it)) }
		if ($parts.Count -eq 0) { return '[]' }
		return '[' + ($parts -join ', ') + ']'
	}
	return ConvertTo-JsonStringLiteral ([string]$v)
}

# Описание пишется в том виде, в каком его удобно править руками: контейнер идет одной
# строкой, пока в нее помещается, и разворачивается, когда перестает.
function ConvertTo-DraftJson($v, $indent) {
	$rendered = ConvertTo-InlineJson $v
	$isContainer = ($v -is [System.Collections.IDictionary]) -or
		(($v -is [System.Collections.IEnumerable]) -and ($v -isnot [string]))
	if (-not $isContainer -or ($indent.Length + $rendered.Length) -le $script:draftJsonWidth) {
		return $rendered
	}
	$inner = $indent + '  '
	if ($v -is [System.Collections.IDictionary]) {
		if ($v.Count -eq 0) { return '{}' }
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($k in $v.Keys) {
			[void]$parts.Add($inner + (ConvertTo-JsonStringLiteral ([string]$k)) + ': ' + (ConvertTo-DraftJson $v[$k] $inner))
		}
		return "{`n" + ($parts -join ",`n") + "`n" + $indent + '}'
	}
	$parts = New-Object System.Collections.Generic.List[object]
	foreach ($it in $v) { [void]$parts.Add($inner + (ConvertTo-DraftJson $it $inner)) }
	if ($parts.Count -eq 0) { return '[]' }
	return "[`n" + ($parts -join ",`n") + "`n" + $indent + ']'
}
# --- Конец общего блока чернового JSON ---

# --- Main ---

if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
	[Console]::Error.WriteLine("File not found: " + $InputFile)
	exit 1
}
$inputAbs = (Resolve-Path -LiteralPath $InputFile).Path

if (-not $OutputFile) {
	$dir = [System.IO.Path]::GetDirectoryName($inputAbs)
	$base = [System.IO.Path]::GetFileNameWithoutExtension($inputAbs)
	$OutputFile = [System.IO.Path]::Combine($dir, $base + ".form.json")
}

$xmlDoc = New-Object System.Xml.XmlDocument
$xmlDoc.PreserveWhitespace = $false
try {
	$xmlDoc.Load($inputAbs)
}
catch {
	[Console]::Error.WriteLine("XML parse error: " + $_.Exception.Message)
	exit 1
}

$root = $xmlDoc.DocumentElement
if ($root.LocalName -ne "Form") {
	[Console]::Error.WriteLine("Корневой элемент <" + $root.LocalName + "> не <Form> - это не файл управляемой формы (выгрузка Конфигуратора)")
	exit 1
}

$rootTodos = New-Object System.Collections.ArrayList
$title = $null
$properties = [ordered]@{}
$excludedCommands = New-Object System.Collections.ArrayList
$events = [ordered]@{}
$elements = New-Object System.Collections.ArrayList
$attributes = New-Object System.Collections.ArrayList
$parameters = New-Object System.Collections.ArrayList
$commands = New-Object System.Collections.ArrayList

foreach ($ch in (Get-ElemChildren $root)) {
	$ln = $ch.LocalName
	if ($ln -eq "Title") {
		$title = Get-MLText $ch $rootTodos "Форма"
	}
	elseif ($ln -eq "CommandSet") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			if ($sub.LocalName -eq "ExcludedCommand") { [void]$excludedCommands.Add((Get-NodeText $sub)) }
			else { Add-Todo $rootTodos ("Форма: CommandSet/" + $sub.LocalName + " не поддержан DSL") }
		}
	}
	elseif ($ln -eq "AutoCommandBar") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			if (($sub.LocalName -eq "ChildItems") -and (-not (Test-EmptyNode $sub))) {
				Add-Todo $rootTodos "Форма: командная панель формы содержит элементы - не поддержано DSL"
			}
		}
	}
	elseif ($ln -eq "Events") {
		foreach ($ev in (Get-ElemChildren $ch)) {
			if ($ev.LocalName -ne "Event") { continue }
			$evName = $ev.GetAttribute("name")
			$handler = $ev.InnerText.Trim()
			if ($evName -and $handler) { $events[$evName] = $handler }
		}
	}
	elseif ($ln -eq "ChildItems") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			$parsed = Read-Element $sub
			if ($null -ne $parsed) { [void]$elements.Add($parsed) }
		}
	}
	elseif ($ln -eq "Attributes") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			$sn = $sub.LocalName
			if ($sn -eq "Attribute") { [void]$attributes.Add((Read-Attribute $sub)) }
			elseif ($sn -eq "ConditionalAppearance") {
				if (-not (Test-EmptyNode $sub)) {
					Add-Todo $rootTodos "Форма: условное оформление (ConditionalAppearance) не поддержано DSL"
				}
			}
			else { Add-Todo $rootTodos ("Форма: Attributes/" + $sn + " не разобран") }
		}
	}
	elseif ($ln -eq "Parameters") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			if ($sub.LocalName -eq "Parameter") { [void]$parameters.Add((Read-Parameter $sub)) }
		}
	}
	elseif ($ln -eq "Commands") {
		foreach ($sub in (Get-ElemChildren $ch)) {
			if ($sub.LocalName -eq "Command") { [void]$commands.Add((Read-Command $sub)) }
		}
	}
	elseif ($ln -eq "CommandInterface") {
		if (-not (Test-EmptyNode $ch)) {
			Add-Todo $rootTodos "Форма: командный интерфейс (CommandInterface) не поддержан DSL"
		}
	}
	elseif ($ln -eq "ConditionalAppearance") {
		if (-not (Test-EmptyNode $ch)) {
			Add-Todo $rootTodos "Форма: условное оформление (ConditionalAppearance) не поддержано DSL"
		}
	}
	elseif ($ln -eq "MobileDeviceCommandBarContent") {
		if (-not (Test-EmptyNode $ch)) {
			Add-Todo $rootTodos "Форма: MobileDeviceCommandBarContent не поддержан DSL"
		}
	}
	elseif ($FORM_STRUCTURAL_TAGS -contains $ln) {
	}
	else {
		$children = Get-ElemChildren $ch
		if ($children.Count -eq 0) {
			if ($PROP_REVERSE.ContainsKey($ln)) { $propKey = $PROP_REVERSE[$ln] }
			else { $propKey = $ln.Substring(0, 1).ToLowerInvariant() + $ln.Substring(1) }
			$properties[$propKey] = Convert-Scalar (Get-NodeText $ch)
		}
		else {
			Add-Todo $rootTodos ("Форма: сложное свойство " + $ln + " не поддержано DSL")
		}
	}
}

$result = [ordered]@{}
if ($rootTodos.Count -gt 0) { $result["_todo"] = $rootTodos }
if ($null -ne $title) { $result["title"] = $title }
# Заданный заголовок сам выключает автоматический - form-compile пишет этот признак
# без указания. В описании он лишний: сборка вернет тот же файл и без него.
if ($null -ne $title -and $properties.Contains('autoTitle') -and $properties['autoTitle'] -eq $false) {
	$properties.Remove('autoTitle')
}
if ($properties.Count -gt 0) { $result["properties"] = $properties }
if ($excludedCommands.Count -gt 0) { $result["excludedCommands"] = $excludedCommands }
if ($events.Count -gt 0) { $result["events"] = $events }
if ($elements.Count -gt 0) { $result["elements"] = $elements }
if ($attributes.Count -gt 0) { $result["attributes"] = $attributes }
if ($parameters.Count -gt 0) { $result["parameters"] = $parameters }
if ($commands.Count -gt 0) { $result["commands"] = $commands }

$json = ConvertTo-DraftJson $result

$outAbs = $OutputFile
if (-not [System.IO.Path]::IsPathRooted($outAbs)) {
	$outAbs = [System.IO.Path]::Combine((Get-Location).Path, $outAbs)
}
$outDir = [System.IO.Path]::GetDirectoryName($outAbs)
if ($outDir -and (-not (Test-Path -LiteralPath $outDir))) {
	[void](New-Item -ItemType Directory -Path $outDir -Force)
}
$enc = New-Object System.Text.UTF8Encoding($false)
# Хвостового перевода строки в описании нет - так же пишет skd-decompile.
[System.IO.File]::WriteAllText($outAbs, $json, $enc)

Write-Output ("[OK] Decompiled: " + $OutputFile)
[Console]::Error.WriteLine("     Elements: " + $elements.Count + ", Attributes: " + $attributes.Count + ", Commands: " + $commands.Count + ", Parameters: " + $parameters.Count)
if ($script:TodoCount -gt 0) {
	[Console]::Error.WriteLine("     TODO: " + $script:TodoCount + " - черновик требует ручной доработки (ключи _todo)")
}
exit 0
