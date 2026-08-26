# skd-decompile v1.0 - Decompile 1C DCS XML (DataCompositionSchema) to JSON DSL draft
# Source: https://github.com/Desko77/claude-code-skills-1c
# Canonical implementation; skd-decompile.py is the structural mirror (same algorithm).
param(
	# Имена параметров общие для семейства навыков по схемам компоновки и макетам:
	# skd-info, skd-edit, mxl-decompile принимают TemplatePath и OutputPath.
	[string]$TemplatePath,
	[string]$OutputPath,

	# Прежние имена приняты как синонимы: по ним написаны вызовы в чужих сценариях.
	[string]$InputFile,
	[string]$OutputFile
)

if (-not $TemplatePath -and $InputFile) { $TemplatePath = $InputFile }
if (-not $OutputPath -and $OutputFile) { $OutputPath = $OutputFile }

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:UriCfg = 'http://v8.1c.ru/8.1/data/enterprise/current-config'
$script:UriStyle = 'http://v8.1c.ru/8.1/data/ui/style'
$script:UriWeb = 'http://v8.1c.ru/8.1/data/ui/colors/web'
$script:UriWin = 'http://v8.1c.ru/8.1/data/ui/colors/windows'
$script:XsiUri = 'http://www.w3.org/2001/XMLSchema-instance'

$script:ComparisonOps = @{
	'Equal' = '='; 'NotEqual' = '<>'; 'Greater' = '>'; 'GreaterOrEqual' = '>='
	'Less' = '<'; 'LessOrEqual' = '<='; 'InList' = 'in'; 'NotInList' = 'notIn'
	'InHierarchy' = 'inHierarchy'; 'InListByHierarchy' = 'inListByHierarchy'
	'Contains' = 'contains'; 'NotContains' = 'notContains'
	'BeginsWith' = 'beginsWith'; 'NotBeginsWith' = 'notBeginsWith'
	'Filled' = 'filled'; 'NotFilled' = 'notFilled'
}

$script:AggFuncs = @(
	'Сумма', 'Количество', 'Минимум', 'Максимум', 'Среднее',
	'Sum', 'Count', 'Min', 'Max', 'Avg', 'Minimum', 'Maximum', 'Average'
)

$script:PeriodVariants = @(
	'Custom', 'Today', 'ThisWeek', 'ThisTenDays', 'ThisMonth', 'ThisQuarter',
	'ThisHalfYear', 'ThisYear', 'FromBeginningOfThisWeek', 'FromBeginningOfThisTenDays',
	'FromBeginningOfThisMonth', 'FromBeginningOfThisQuarter', 'FromBeginningOfThisHalfYear',
	'FromBeginningOfThisYear', 'LastWeek', 'LastTenDays', 'LastMonth', 'LastQuarter',
	'LastHalfYear', 'LastYear', 'NextDay', 'NextWeek', 'NextTenDays', 'NextMonth',
	'NextQuarter', 'NextHalfYear', 'NextYear', 'TillEndOfThisWeek', 'TillEndOfThisTenDays',
	'TillEndOfThisMonth', 'TillEndOfThisQuarter', 'TillEndOfThisHalfYear', 'TillEndOfThisYear'
)

$script:DefaultSourceName = 'ИсточникДанных1'
$script:NameBegin = 'НачалоПериода'
$script:NameEnd = 'КонецПериода'
$script:ExprBeginSuffix = '.ДатаНачала'
$script:ExprEndSuffix = '.ДатаОкончания'
$script:VariantMain = 'Основной'
$script:ZeroDate = '0001-01-01T00:00:00'
$script:StructureExtraTodo = @('userSettingPresentation', 'itemsViewMode', 'columnsViewMode',
	'rowsViewMode', 'pointsViewMode', 'seriesViewMode')

$script:Warnings = New-Object System.Collections.Generic.List[object]
$script:DroppedSettingIds = 0

function Test-SimpleName($s) {
	if ($null -eq $s -or $s -ceq '') { return $false }
	return [regex]::IsMatch($s, '^[^\s:@#\[\]=]+$')
}

function Get-Kids($el, $name) {
	$out = New-Object System.Collections.Generic.List[object]
	if ($null -ne $el) {
		foreach ($c in $el.ChildNodes) {
			if ($c.NodeType -eq 'Element' -and $c.LocalName -ceq $name) { [void]$out.Add($c) }
		}
	}
	return ,$out
}

function Get-Kid($el, $name) {
	if ($null -eq $el) { return $null }
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $c.LocalName -ceq $name) { return $c }
	}
	return $null
}

function Get-Text($el) {
	if ($null -eq $el) { return '' }
	return [string]$el.InnerText
}

function Get-XsiLocal($el) {
	if ($null -eq $el) { return '' }
	$t = $el.GetAttribute('type', $script:XsiUri)
	if ([string]::IsNullOrEmpty($t)) { return '' }
	$parts = $t.Split(':')
	return $parts[$parts.Length - 1]
}

function Get-XsiNil($el) {
	if ($null -eq $el) { return $false }
	return ($el.GetAttribute('nil', $script:XsiUri) -ceq 'true')
}

function Add-Todo($node, $msg) {
	if (-not $node.Contains('_todo')) {
		$node['_todo'] = New-Object System.Collections.Generic.List[object]
	}
	[void]$node['_todo'].Add($msg)
	[void]$script:Warnings.Add($msg)
}

function Get-MlText($el, $todoNode) {
	$items = Get-Kids $el 'item'
	if ($items.Count -eq 0) { return Get-Text $el }
	$langs = [ordered]@{}
	foreach ($it in $items) {
		$lang = (Get-Text (Get-Kid $it 'lang')).Trim()
		$langs[$lang] = Get-Text (Get-Kid $it 'content')
	}
	if ($langs.Count -gt 1 -and $null -ne $todoNode) {
		Add-Todo $todoNode 'многоязычный текст: сохранен только ru'
	}
	if ($langs.Contains('ru')) { return $langs['ru'] }
	foreach ($v in $langs.Values) { return $v }
	return ''
}

function Resolve-ColorValue($raw, $ctxEl) {
	$raw = ([string]$raw).Trim()
	if ($raw.Contains(':')) {
		$idx = $raw.IndexOf(':')
		$pfx = $raw.Substring(0, $idx)
		$loc = $raw.Substring($idx + 1)
		$uri = ''
		if ($null -ne $ctxEl) { $uri = [string]$ctxEl.GetNamespaceOfPrefix($pfx) }
		if ($uri -ceq $script:UriStyle -or $pfx -ceq 'style') { return 'style:' + $loc }
		if ($uri -ceq $script:UriWeb -or $pfx -ceq 'web') { return 'web:' + $loc }
		if ($uri -ceq $script:UriWin -or $pfx -ceq 'win') { return 'win:' + $loc }
	}
	return $raw
}

function Get-TypeShorthand($vtEl, $node) {
	$types = Get-Kids $vtEl 'Type'
	if ((Get-Kids $vtEl 'TypeSet').Count -gt 0) {
		Add-Todo $node 'valueType: TypeSet не поддержан нашим DSL'
	}
	if ($types.Count -eq 0) { return $null }
	if ($types.Count -gt 1) {
		$names = New-Object System.Collections.Generic.List[object]
		foreach ($t in $types) { [void]$names.Add((Get-Text $t).Trim()) }
		Add-Todo $node ('составной тип не поддержан: ' + ($names -join ', '))
		return $null
	}
	$raw = (Get-Text $types[0]).Trim()
	$uri = ''
	$loc = $raw
	if ($raw.Contains(':')) {
		$idx = $raw.IndexOf(':')
		$pfx = $raw.Substring(0, $idx)
		$loc = $raw.Substring($idx + 1)
		$uri = [string]$types[0].GetNamespaceOfPrefix($pfx)
	}
	if ($uri -ceq $script:UriCfg) { return $loc }
	if ($loc -ceq 'StandardPeriod') { return 'StandardPeriod' }
	if ($loc -ceq 'ValueStorage') {
		Add-Todo $node 'тип ValueStorage не поддержан нашим DSL'
		return $null
	}
	if ($loc -ceq 'boolean') { return 'boolean' }
	if ($loc -ceq 'string') {
		$q = Get-Kid $vtEl 'StringQualifiers'
		if ($null -eq $q) { return 'string' }
		$length = (Get-Text (Get-Kid $q 'Length')).Trim()
		if ($length -ceq '') { $length = '0' }
		$allowed = (Get-Text (Get-Kid $q 'AllowedLength')).Trim()
		if ($allowed -cne '' -and $allowed -cne 'Variable') {
			Add-Todo $node ('StringQualifiers AllowedLength=' + $allowed + ' не поддержан (принят Variable)')
		}
		if ($length -ceq '0') { return 'string' }
		return 'string(' + $length + ')'
	}
	if ($loc -ceq 'decimal') {
		$q = Get-Kid $vtEl 'NumberQualifiers'
		if ($null -eq $q) { return $raw }
		$digits = (Get-Text (Get-Kid $q 'Digits')).Trim()
		if ($digits -ceq '') { $digits = '0' }
		$frac = (Get-Text (Get-Kid $q 'FractionDigits')).Trim()
		if ($frac -ceq '') { $frac = '0' }
		$sign = (Get-Text (Get-Kid $q 'AllowedSign')).Trim()
		if ($sign -ceq 'Nonnegative') { return 'decimal(' + $digits + ',' + $frac + ',nonneg)' }
		return 'decimal(' + $digits + ',' + $frac + ')'
	}
	if ($loc -ceq 'dateTime') {
		$q = Get-Kid $vtEl 'DateQualifiers'
		$frac = 'DateTime'
		if ($null -ne $q) { $frac = (Get-Text (Get-Kid $q 'DateFractions')).Trim() }
		if ($frac -ceq 'Date') { return 'date' }
		if ($frac -ceq 'DateTime' -or $frac -ceq '') { return 'dateTime' }
		Add-Todo $node ('DateQualifiers DateFractions=' + $frac + ' не поддержан')
		return 'dateTime'
	}
	return $raw
}

function Get-RestrictionTokens($el) {
	$toks = New-Object System.Collections.Generic.List[object]
	if ($null -eq $el) { return ,$toks }
	$map = @{ 'field' = 'noField'; 'condition' = 'noFilter'; 'group' = 'noGroup'; 'order' = 'noOrder' }
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -ne 'Element') { continue }
		$n = $c.LocalName
		if ($map.ContainsKey($n) -and (Get-Text $c).Trim() -ceq 'true') {
			[void]$toks.Add($map[$n])
		}
	}
	return ,$toks
}

function Get-SettingValue($vEl, $todoNode, $pname) {
	if ($null -eq $vEl) { return '' }
	$xt = Get-XsiLocal $vEl
	if ($xt -ceq 'LocalStringType') { return Get-MlText $vEl $todoNode }
	if ($xt -ceq 'Color') { return Resolve-ColorValue (Get-Text $vEl) $vEl }
	if ($xt -ceq 'Font' -or $xt -ceq 'Line') {
		Add-Todo $todoNode ('оформление "' + $pname + '": тип значения ' + $xt + ' не поддержан нашим DSL')
		return (Get-Text $vEl).Trim()
	}
	return Get-Text $vEl
}

function Get-AppearanceMap($appEl, $todoNode) {
	$result = [ordered]@{}
	foreach ($it in (Get-Kids $appEl 'item')) {
		$p = (Get-Text (Get-Kid $it 'parameter')).Trim()
		if ($p -ceq '') { continue }
		$val = Get-SettingValue (Get-Kid $it 'value') $todoNode $p
		$useEl = Get-Kid $it 'use'
		if ($null -ne $useEl -and (Get-Text $useEl).Trim() -ceq 'false') {
			$wrapped = [ordered]@{}
			$wrapped['value'] = $val
			$wrapped['use'] = $false
			$result[$p] = $wrapped
		} else {
			$result[$p] = $val
		}
	}
	return $result
}

# === Fields ===

function Build-Field($fieldEl) {
	$xt = Get-XsiLocal $fieldEl
	$node = [ordered]@{}
	if ($xt -ceq 'DataSetFieldFolder') {
		$node['dataPath'] = Get-Text (Get-Kid $fieldEl 'dataPath')
		Add-Todo $node 'папка полей (DataSetFieldFolder) не поддержана нашим DSL'
		return $node
	}
	if ($xt -cne 'DataSetFieldField' -and $xt -cne '') {
		Add-Todo $node ('неподдержанный тип поля: ' + $xt)
		return $node
	}

	$dataPath = Get-Text (Get-Kid $fieldEl 'dataPath')
	$field = Get-Text (Get-Kid $fieldEl 'field')
	$title = ''
	$tEl = Get-Kid $fieldEl 'title'
	if ($null -ne $tEl) { $title = Get-MlText $tEl $node }

	$roles = New-Object System.Collections.Generic.List[object]
	$roleExtra = [ordered]@{}
	$rEl = Get-Kid $fieldEl 'role'
	if ($null -ne $rEl) {
		$periodNum = ''
		$periodType = ''
		foreach ($rc in $rEl.ChildNodes) {
			if ($rc.NodeType -ne 'Element') { continue }
			$rl = $rc.LocalName
			$rv = (Get-Text $rc).Trim()
			if (($rl -ceq 'dimension' -or $rl -ceq 'account' -or $rl -ceq 'balance') -and $rv -ceq 'true') {
				[void]$roles.Add($rl)
			} elseif ($rl -ceq 'periodNumber') {
				$periodNum = $rv
			} elseif ($rl -ceq 'periodType') {
				$periodType = $rv
			} elseif ($rl -ceq 'accountTypeExpression' -or $rl -ceq 'balanceGroup') {
				$roleExtra[$rl] = $rv
			} else {
				Add-Todo $node ('элемент роли не поддержан: ' + $rl)
			}
		}
		if ($periodNum -ceq '1' -and $periodType -ceq 'Main') {
			[void]$roles.Add('period')
		} elseif ($periodNum -cne '' -or $periodType -cne '') {
			Add-Todo $node ('роль периода не свернута: periodNumber=' + $periodNum + ', periodType=' + $periodType)
		}
	}

	$restrict = Get-RestrictionTokens (Get-Kid $fieldEl 'useRestriction')
	$attrRestrict = Get-RestrictionTokens (Get-Kid $fieldEl 'attributeUseRestriction')
	$vtEl = Get-Kid $fieldEl 'valueType'
	$typeStr = $null
	if ($null -ne $vtEl) { $typeStr = Get-TypeShorthand $vtEl $node }
	$appEl = Get-Kid $fieldEl 'appearance'
	$appearance = $null
	if ($null -ne $appEl) { $appearance = Get-AppearanceMap $appEl $node }
	$presExpr = Get-Text (Get-Kid $fieldEl 'presentationExpression')

	$handled = @('dataPath', 'field', 'title', 'role', 'useRestriction',
		'attributeUseRestriction', 'valueType', 'appearance', 'presentationExpression')
	foreach ($c in $fieldEl.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент поля не поддержан: ' + $c.LocalName)
		}
	}

	$canShort = ((Test-SimpleName $dataPath) -and
		($field -ceq '' -or $field -ceq $dataPath) -and
		$title -ceq '' -and $roleExtra.Count -eq 0 -and $attrRestrict.Count -eq 0 -and
		($null -eq $appearance -or $appearance.Count -eq 0) -and $presExpr -ceq '' -and
		(-not $node.Contains('_todo')) -and
		($null -eq $typeStr -or (Test-SimpleName $typeStr)))
	if ($canShort) {
		$s = $dataPath
		if ($null -ne $typeStr) { $s += ': ' + $typeStr }
		foreach ($r in $roles) { $s += ' @' + $r }
		foreach ($t in $restrict) { $s += ' #' + $t }
		return $s
	}

	$obj = [ordered]@{}
	$obj['dataPath'] = $dataPath
	if ($field -cne '' -and $field -cne $dataPath) { $obj['field'] = $field }
	if ($title -cne '') { $obj['title'] = $title }
	if ($null -ne $typeStr) { $obj['type'] = $typeStr }
	if ($roles.Count -gt 0 -or $roleExtra.Count -gt 0) {
		if ($roles.Count -eq 1 -and $roleExtra.Count -eq 0) {
			$obj['role'] = $roles[0]
		} else {
			$ro = [ordered]@{}
			foreach ($r in $roles) { $ro[$r] = $true }
			foreach ($k in $roleExtra.Keys) { $ro[$k] = $roleExtra[$k] }
			$obj['role'] = $ro
		}
	}
	if ($restrict.Count -gt 0) { $obj['restrict'] = $restrict }
	if ($attrRestrict.Count -gt 0) { $obj['attrRestrict'] = $attrRestrict }
	if ($null -ne $appearance -and $appearance.Count -gt 0) { $obj['appearance'] = $appearance }
	if ($presExpr -cne '') { $obj['presentationExpression'] = $presExpr }
	if ($node.Contains('_todo')) { $obj['_todo'] = $node['_todo'] }
	return $obj
}

# === DataSets ===

function Build-DataSet($el, $defaultSource) {
	$node = [ordered]@{}
	$node['name'] = Get-Text (Get-Kid $el 'name')
	$xt = Get-XsiLocal $el
	$src = Get-Text (Get-Kid $el 'dataSource')
	if ($xt -ceq 'DataSetQuery') {
		if ($src -cne '' -and $src -cne $defaultSource) { $node['source'] = $src }
		$node['query'] = Get-Text (Get-Kid $el 'query')
		$aff = Get-Kid $el 'autoFillFields'
		if ($null -ne $aff -and (Get-Text $aff).Trim() -ceq 'false') {
			$node['autoFillFields'] = $false
		}
	} elseif ($xt -ceq 'DataSetObject') {
		if ($src -cne '' -and $src -cne $defaultSource) { $node['source'] = $src }
		$node['objectName'] = Get-Text (Get-Kid $el 'objectName')
	} elseif ($xt -ceq 'DataSetUnion') {
		$items = New-Object System.Collections.Generic.List[object]
		foreach ($sub in (Get-Kids $el 'item')) { [void]$items.Add((Build-DataSet $sub $defaultSource)) }
		foreach ($sub in (Get-Kids $el 'dataSet')) { [void]$items.Add((Build-DataSet $sub $defaultSource)) }
		$node['items'] = $items
	} else {
		$label = $xt
		if ($label -ceq '') { $label = '(нет xsi:type)' }
		Add-Todo $node ('неподдержанный тип набора данных: ' + $label)
	}
	$handled = @('name', 'dataSource', 'field')
	if ($xt -ceq 'DataSetQuery') { $handled += @('query', 'autoFillFields') }
	elseif ($xt -ceq 'DataSetObject') { $handled += 'objectName' }
	elseif ($xt -ceq 'DataSetUnion') { $handled += @('item', 'dataSet') }
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент набора данных не поддержан: ' + $c.LocalName)
		}
	}
	$fields = New-Object System.Collections.Generic.List[object]
	foreach ($f in (Get-Kids $el 'field')) { [void]$fields.Add((Build-Field $f)) }
	if ($fields.Count -gt 0) { $node['fields'] = $fields }
	return $node
}

# === DataSetLinks ===

function Build-Link($el) {
	$node = [ordered]@{}
	$node['source'] = Get-Text (Get-Kid $el 'sourceDataSet')
	$node['dest'] = Get-Text (Get-Kid $el 'destinationDataSet')
	$node['sourceExpr'] = Get-Text (Get-Kid $el 'sourceExpression')
	$node['destExpr'] = Get-Text (Get-Kid $el 'destinationExpression')
	$p = Get-Kid $el 'parameter'
	if ($null -ne $p -and (Get-Text $p) -cne '') { $node['parameter'] = Get-Text $p }
	$handled = @('sourceDataSet', 'destinationDataSet', 'sourceExpression',
		'destinationExpression', 'parameter')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент связи наборов не поддержан: ' + $c.LocalName)
		}
	}
	return $node
}

# === CalculatedFields ===

function Build-CalcField($el) {
	$node = [ordered]@{}
	$dp = Get-Text (Get-Kid $el 'dataPath')
	$expr = Get-Text (Get-Kid $el 'expression')
	$title = ''
	$tEl = Get-Kid $el 'title'
	if ($null -ne $tEl) { $title = Get-MlText $tEl $node }
	$vtEl = Get-Kid $el 'valueType'
	$typeStr = $null
	if ($null -ne $vtEl) { $typeStr = Get-TypeShorthand $vtEl $node }
	$restrict = Get-RestrictionTokens (Get-Kid $el 'useRestriction')
	$appEl = Get-Kid $el 'appearance'
	$appearance = $null
	if ($null -ne $appEl) { $appearance = Get-AppearanceMap $appEl $node }

	$handled = @('dataPath', 'expression', 'title', 'valueType', 'useRestriction', 'appearance')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент вычисляемого поля не поддержан: ' + $c.LocalName)
		}
	}

	$canShort = ((-not $node.Contains('_todo')) -and
		($null -eq $appearance -or $appearance.Count -eq 0) -and
		(Test-SimpleName $dp) -and
		$expr -cne '' -and (-not $expr.Contains("`n")) -and
		(-not [regex]::IsMatch($expr, '#(noField|noFilter|noCondition|noGroup|noOrder)\b')) -and
		($title -ceq '' -or -not [regex]::IsMatch($title, '[\]=#@]')) -and
		($null -eq $typeStr -or (Test-SimpleName $typeStr)))
	if ($canShort) {
		$s = $dp
		if ($title -cne '') { $s += ' [' + $title + ']' }
		if ($null -ne $typeStr) { $s += ': ' + $typeStr }
		$s += ' = ' + $expr
		foreach ($t in $restrict) { $s += ' #' + $t }
		return $s
	}

	$obj = [ordered]@{}
	$obj['dataPath'] = $dp
	$obj['expression'] = $expr
	if ($title -cne '') { $obj['title'] = $title }
	if ($null -ne $typeStr) { $obj['type'] = $typeStr }
	if ($restrict.Count -gt 0) { $obj['restrict'] = $restrict }
	if ($null -ne $appearance -and $appearance.Count -gt 0) { $obj['appearance'] = $appearance }
	if ($node.Contains('_todo')) { $obj['_todo'] = $node['_todo'] }
	return $obj
}

# === TotalFields ===

function Build-TotalField($el) {
	$node = [ordered]@{}
	$dp = Get-Text (Get-Kid $el 'dataPath')
	$expr = Get-Text (Get-Kid $el 'expression')
	$groups = New-Object System.Collections.Generic.List[object]
	foreach ($g in (Get-Kids $el 'group')) { [void]$groups.Add((Get-Text $g)) }
	$handled = @('dataPath', 'expression', 'group')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент итогового поля не поддержан: ' + $c.LocalName)
		}
	}

	if ((-not $node.Contains('_todo')) -and $groups.Count -eq 0 -and $expr -cne '' -and
		(-not $expr.Contains("`n")) -and (Test-SimpleName $dp) -and
		($script:AggFuncs -cnotcontains $expr)) {
		$m = [regex]::Match($expr, '^(\w+)\((.+)\)$')
		if ($m.Success -and $script:AggFuncs -ccontains $m.Groups[1].Value -and $m.Groups[2].Value -ceq $dp) {
			return $dp + ': ' + $m.Groups[1].Value
		}
		return $dp + ': ' + $expr
	}

	$obj = [ordered]@{}
	$obj['dataPath'] = $dp
	$obj['expression'] = $expr
	if ($groups.Count -eq 1) { $obj['group'] = $groups[0] }
	elseif ($groups.Count -gt 1) { $obj['group'] = $groups }
	if ($node.Contains('_todo')) { $obj['_todo'] = $node['_todo'] }
	return $obj
}

# === Parameters ===

function Build-Parameter($el) {
	$node = [ordered]@{}
	$node['name'] = Get-Text (Get-Kid $el 'name')
	$tEl = Get-Kid $el 'title'
	if ($null -ne $tEl) {
		$title = Get-MlText $tEl $node
		if ($title -cne '') { $node['title'] = $title }
	}
	$vtEl = Get-Kid $el 'valueType'
	if ($null -ne $vtEl) {
		$ts = Get-TypeShorthand $vtEl $node
		if ($null -ne $ts) { $node['type'] = $ts }
	}
	$vEl = Get-Kid $el 'value'
	if ($null -ne $vEl -and -not (Get-XsiNil $vEl)) {
		$vxt = Get-XsiLocal $vEl
		if ($vxt -ceq 'StandardPeriod') {
			$node['value'] = (Get-Text (Get-Kid $vEl 'variant')).Trim()
			$sd = (Get-Text (Get-Kid $vEl 'startDate')).Trim()
			$ed = (Get-Text (Get-Kid $vEl 'endDate')).Trim()
			if (($sd -cne '' -and $sd -cne $script:ZeroDate) -or ($ed -cne '' -and $ed -cne $script:ZeroDate)) {
				Add-Todo $node ('нестандартные даты StandardPeriod потеряны: ' + $sd + ' / ' + $ed)
			}
		} elseif ($vxt -ceq 'boolean') {
			$node['value'] = (Get-Text $vEl).Trim()
		} else {
			$node['value'] = Get-Text $vEl
		}
	}
	if ((Get-Text (Get-Kid $el 'useRestriction')).Trim() -ceq 'true') { $node['useRestriction'] = $true }
	$expr = Get-Text (Get-Kid $el 'expression')
	if ($expr -cne '') { $node['expression'] = $expr }
	if ((Get-Text (Get-Kid $el 'availableAsField')).Trim() -ceq 'false') { $node['availableAsField'] = $false }
	if ((Get-Text (Get-Kid $el 'valueListAllowed')).Trim() -ceq 'true') { $node['valueListAllowed'] = $true }
	if ((Get-Text (Get-Kid $el 'denyIncompleteValues')).Trim() -ceq 'true') { $node['denyIncompleteValues'] = $true }
	$use = (Get-Text (Get-Kid $el 'use')).Trim()
	if ($use -cne '') { $node['use'] = $use }
	$avs = Get-Kids $el 'availableValue'
	if ($avs.Count -gt 0) {
		$avList = New-Object System.Collections.Generic.List[object]
		foreach ($av in $avs) {
			$avObj = [ordered]@{}
			$avObj['value'] = Get-Text (Get-Kid $av 'value')
			$pEl = Get-Kid $av 'presentation'
			if ($null -ne $pEl) {
				$pres = Get-MlText $pEl $node
				if ($pres -cne '') { $avObj['presentation'] = $pres }
			}
			[void]$avList.Add($avObj)
		}
		$node['availableValues'] = $avList
	}

	$handled = @('name', 'title', 'valueType', 'value', 'useRestriction', 'expression',
		'availableAsField', 'valueListAllowed', 'denyIncompleteValues', 'use', 'availableValue')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент параметра не поддержан: ' + $c.LocalName)
		}
	}
	return $node
}

function Invoke-AutoDatesCollapse($params) {
	$companionKeys = @('name', 'title', 'type', 'value', 'useRestriction',
		'availableAsField', 'expression')
	$byName = @{}
	foreach ($p in $params) {
		if (-not $byName.ContainsKey($p['name'])) { $byName[$p['name']] = $p }
	}
	$drop = New-Object System.Collections.Generic.List[object]
	foreach ($p in $params) {
		if ($p['type'] -cne 'StandardPeriod' -or $p.Contains('_todo')) { continue }
		if (-not ($byName.ContainsKey($script:NameBegin) -and $byName.ContainsKey($script:NameEnd))) { continue }
		$b = $byName[$script:NameBegin]
		$e = $byName[$script:NameEnd]
		if ([object]::ReferenceEquals($b, $p) -or [object]::ReferenceEquals($e, $p)) { continue }
		$expectedB = '&' + $p['name'] + $script:ExprBeginSuffix
		$expectedE = '&' + $p['name'] + $script:ExprEndSuffix
		$bClean = $true
		foreach ($k in $b.Keys) { if ($companionKeys -cnotcontains $k) { $bClean = $false } }
		foreach ($k in $e.Keys) { if ($companionKeys -cnotcontains $k) { $bClean = $false } }
		if ($bClean -and $b['expression'] -ceq $expectedB -and $e['expression'] -ceq $expectedE) {
			$p['autoDates'] = $true
			[void]$drop.Add($b)
			[void]$drop.Add($e)
			if ($p.Contains('use') -and $p['use'] -ceq 'Always') { $p.Remove('use') }
			if ($p.Contains('denyIncompleteValues') -and $p['denyIncompleteValues'] -eq $true) { $p.Remove('denyIncompleteValues') }
			break
		}
	}
	$out = New-Object System.Collections.Generic.List[object]
	foreach ($p in $params) {
		$isDropped = $false
		foreach ($d in $drop) { if ([object]::ReferenceEquals($d, $p)) { $isDropped = $true } }
		if (-not $isDropped) { [void]$out.Add($p) }
	}
	return ,$out
}

function ConvertTo-ParamShorthand($p) {
	if ($p.Contains('useRestriction') -and $p['useRestriction'] -eq $true -and
		$p.Contains('availableAsField') -and $p['availableAsField'] -eq $false) {
		$copy = [ordered]@{}
		foreach ($k in $p.Keys) {
			if ($k -cne 'useRestriction' -and $k -cne 'availableAsField') { $copy[$k] = $p[$k] }
		}
		$copy['hidden'] = $true
		$p = $copy
	}
	$allowed = @('name', 'title', 'type', 'value', 'autoDates', 'valueListAllowed', 'hidden')
	foreach ($k in $p.Keys) {
		if ($allowed -cnotcontains $k) { return $p }
	}
	$name = [string]$p['name']
	$typeStr = ''
	if ($p.Contains('type')) { $typeStr = [string]$p['type'] }
	$title = ''
	if ($p.Contains('title')) { $title = [string]$p['title'] }
	if (-not (Test-SimpleName $name)) { return $p }
	if ($typeStr -ceq '' -or -not (Test-SimpleName $typeStr)) { return $p }
	if ($title -cne '' -and [regex]::IsMatch($title, '[\]@#=:]')) { return $p }
	$vStr = $null
	if ($p.Contains('value')) {
		$v = $p['value']
		if ($v -is [bool]) {
			if ($v) { $vStr = 'true' } else { $vStr = 'false' }
		} else {
			$vStr = [string]$v
		}
		if ([regex]::IsMatch($vStr, '[@\[\]]') -or $vStr.Contains("`n") -or $vStr.Trim() -cne $vStr -or $vStr -ceq '') {
			return $p
		}
	}
	$s = $name
	if ($title -cne '') { $s += ' [' + $title + ']' }
	$s += ': ' + $typeStr
	if ($null -ne $vStr) { $s += ' = ' + $vStr }
	if ($p.Contains('autoDates') -and $p['autoDates'] -eq $true) { $s += ' @autoDates' }
	if ($p.Contains('valueListAllowed') -and $p['valueListAllowed'] -eq $true) { $s += ' @valueList' }
	if ($p.Contains('hidden') -and $p['hidden'] -eq $true) { $s += ' @hidden' }
	return $s
}

# === Selection / Filter / Order ===

function Build-Selection($selEl, $todoNode) {
	$items = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $selEl 'item')) {
		$xt = Get-XsiLocal $it
		if ($xt -ceq 'SelectedItemAuto') {
			if ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false') {
				Add-Todo $todoNode 'выборка: SelectedItemAuto с use=false не поддержан'
			}
			[void]$items.Add('Auto')
		} elseif ($xt -ceq 'SelectedItemField') {
			$fld = Get-Text (Get-Kid $it 'field')
			if ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false') {
				Add-Todo $todoNode ('выборка: use=false у поля "' + $fld + '" не поддержано')
			}
			$tEl = Get-Kid $it 'lwsTitle'
			if ($null -ne $tEl) {
				$obj = [ordered]@{}
				$obj['field'] = $fld
				$obj['title'] = Get-MlText $tEl $todoNode
				[void]$items.Add($obj)
			} else {
				[void]$items.Add($fld)
			}
		} elseif ($xt -ceq 'SelectedItemFolder') {
			$tEl = Get-Kid $it 'lwsTitle'
			$folder = [ordered]@{}
			if ($null -ne $tEl) { $folder['folder'] = Get-MlText $tEl $todoNode } else { $folder['folder'] = '' }
			$subItems = New-Object System.Collections.Generic.List[object]
			foreach ($sub in (Get-Kids $it 'item')) {
				$sxt = Get-XsiLocal $sub
				if ($sxt -ceq 'SelectedItemField') {
					[void]$subItems.Add((Get-Text (Get-Kid $sub 'field')))
				} else {
					Add-Todo $folder ('элемент папки выборки не поддержан: ' + $sxt)
				}
			}
			$folder['items'] = $subItems
			$placement = (Get-Text (Get-Kid $it 'placement')).Trim()
			if ($placement -cne '' -and $placement -cne 'Auto') {
				Add-Todo $folder ('размещение папки выборки не поддержано: ' + $placement)
			}
			[void]$items.Add($folder)
		} else {
			$stub = [ordered]@{}
			Add-Todo $stub ('элемент выборки не поддержан: ' + $xt)
			[void]$items.Add($stub)
		}
	}
	return ,$items
}

function Get-DetectedValueType($vStr) {
	if ($vStr -ceq 'true' -or $vStr -ceq 'false') { return 'xs:boolean' }
	if ([regex]::IsMatch($vStr, '^\d{4}-\d{2}-\d{2}T')) { return 'xs:dateTime' }
	if ([regex]::IsMatch($vStr, '^\d+(\.\d+)?$')) { return 'xs:decimal' }
	if ([regex]::IsMatch($vStr, '^(Перечисление|Справочник|ПланСчетов|Документ|ПланВидовХарактеристик|ПланВидовРасчета)\.')) { return 'dcscor:DesignTimeValue' }
	return 'xs:string'
}

function New-FilterObject($node, $field, $op, $value, $valueType, $useOff, $presentation, $viewMode, $settingId, $usp) {
	$obj = [ordered]@{}
	$obj['field'] = $field
	$obj['op'] = $op
	if ($null -ne $value) {
		$obj['value'] = $value
		if ($null -ne $valueType -and $valueType -cne '') { $obj['valueType'] = $valueType }
	}
	if ($useOff) { $obj['use'] = $false }
	if ($presentation -cne '') { $obj['presentation'] = $presentation }
	if ($viewMode -cne '') { $obj['viewMode'] = $viewMode }
	if ($settingId -cne '') { $obj['userSettingID'] = $settingId }
	if ($usp -cne '') { $obj['userSettingPresentation'] = $usp }
	if ($node.Contains('_todo')) { $obj['_todo'] = $node['_todo'] }
	return $obj
}

function Build-FilterItem($it, $todoNode) {
	$xt = Get-XsiLocal $it
	if ($xt -ceq 'FilterItemGroup') {
		$gt = (Get-Text (Get-Kid $it 'groupType')).Trim()
		$gmap = @{ 'AndGroup' = 'And'; 'OrGroup' = 'Or'; 'NotGroup' = 'Not' }
		$node = [ordered]@{}
		if ($gmap.ContainsKey($gt)) { $node['group'] = $gmap[$gt] } else { $node['group'] = 'And' }
		if ($gt -cne '' -and -not $gmap.ContainsKey($gt)) {
			Add-Todo $node ('тип группы отбора не распознан: ' + $gt)
		}
		if ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false') {
			Add-Todo $node 'группа отбора: use=false не поддержано нашим DSL'
		}
		$subItems = New-Object System.Collections.Generic.List[object]
		foreach ($sub in (Get-Kids $it 'item')) {
			[void]$subItems.Add((Build-FilterItem $sub $node))
		}
		$node['items'] = $subItems
		foreach ($extra in @('viewMode', 'userSettingID', 'userSettingPresentation')) {
			if ($null -ne (Get-Kid $it $extra)) {
				Add-Todo $node ('группа отбора: ' + $extra + ' не поддержан нашим DSL')
			}
		}
		return $node
	}
	if ($xt -cne 'FilterItemComparison') {
		$stub = [ordered]@{}
		Add-Todo $stub ('элемент отбора не поддержан: ' + $xt)
		return $stub
	}

	$node = [ordered]@{}
	$leftEl = Get-Kid $it 'left'
	$field = Get-Text $leftEl
	if ($null -ne $leftEl) {
		$lxt = Get-XsiLocal $leftEl
		if ($lxt -cne 'Field' -and $lxt -cne '') {
			Add-Todo $node ('левая часть отбора не поддержана: ' + $lxt)
		}
	}
	$comp = (Get-Text (Get-Kid $it 'comparisonType')).Trim()
	$op = $comp
	if ($script:ComparisonOps.ContainsKey($comp)) { $op = $script:ComparisonOps[$comp] }
	$useOff = ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false')

	$value = $null
	$valueType = $null
	$rEl = Get-Kid $it 'right'
	if ($null -ne $rEl -and -not (Get-XsiNil $rEl)) {
		$rxt = Get-XsiLocal $rEl
		if ($rxt -ceq 'boolean') {
			$value = ((Get-Text $rEl).Trim() -ceq 'true')
			$valueType = 'xs:boolean'
		} elseif ($rxt -ceq 'decimal' -or $rxt -ceq 'dateTime' -or $rxt -ceq 'string') {
			$value = Get-Text $rEl
			$valueType = 'xs:' + $rxt
		} elseif ($rxt -ceq 'DesignTimeValue') {
			$value = Get-Text $rEl
			$valueType = 'dcscor:DesignTimeValue'
		} elseif ($rxt -ceq '') {
			$value = Get-Text $rEl
			$valueType = 'xs:string'
		} else {
			$value = Get-Text $rEl
			$valueType = $rxt
			Add-Todo $node ('тип значения отбора не поддержан: ' + $rxt)
		}
	}

	$presentation = ''
	$pEl = Get-Kid $it 'presentation'
	if ($null -ne $pEl) { $presentation = Get-MlText $pEl $node }
	$viewMode = (Get-Text (Get-Kid $it 'viewMode')).Trim()
	$settingId = (Get-Text (Get-Kid $it 'userSettingID')).Trim()
	$usp = ''
	$uspEl = Get-Kid $it 'userSettingPresentation'
	if ($null -ne $uspEl) { $usp = Get-MlText $uspEl $node }

	$vStr = $null
	if ($null -ne $value) {
		if ($value -is [bool]) {
			if ($value) { $vStr = 'true' } else { $vStr = 'false' }
		} else {
			$vStr = [string]$value
		}
	}
	$valueOk = $true
	if ($null -ne $vStr) {
		$valueOk = ($vStr -cne '' -and -not $vStr.Contains("`n") -and -not $vStr.Contains('@') -and
			$vStr -cne '_' -and $vStr.Trim() -ceq $vStr -and (Get-DetectedValueType $vStr) -ceq $valueType)
	}
	$canShort = ((-not $node.Contains('_todo')) -and $presentation -ceq '' -and $usp -ceq '' -and
		$script:ComparisonOps.ContainsKey($comp) -and (Test-SimpleName $field) -and $valueOk -and
		($viewMode -ceq '' -or $viewMode -ceq 'QuickAccess' -or $viewMode -ceq 'Normal' -or $viewMode -ceq 'Inaccessible'))
	if ($canShort) {
		$s = $field + ' ' + $op
		if ($null -ne $vStr) {
			$s += ' ' + $vStr
		} elseif (@('=', '<>', '>', '>=', '<', '<=') -ccontains $op) {
			$s += ' _'
		}
		if ($useOff) { $s += ' @off' }
		if ($settingId -cne '') { $s += ' @user' }
		if ($viewMode -ceq 'QuickAccess') { $s += ' @quickAccess' }
		elseif ($viewMode -ceq 'Normal') { $s += ' @normal' }
		elseif ($viewMode -ceq 'Inaccessible') { $s += ' @inaccessible' }
		return $s
	}
	return New-FilterObject $node $field $op $value $valueType $useOff $presentation $viewMode $settingId $usp
}

function Build-Filter($fEl, $todoNode) {
	$items = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $fEl 'item')) {
		[void]$items.Add((Build-FilterItem $it $todoNode))
	}
	return ,$items
}

function Build-Order($ordEl, $todoNode) {
	$items = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $ordEl 'item')) {
		$xt = Get-XsiLocal $it
		if ($xt -ceq 'OrderItemAuto') {
			[void]$items.Add('Auto')
		} elseif ($xt -ceq 'OrderItemField') {
			$f = Get-Text (Get-Kid $it 'field')
			$d = (Get-Text (Get-Kid $it 'orderType')).Trim()
			if (-not (Test-SimpleName $f)) {
				$stub = [ordered]@{}
				Add-Todo $stub ('поле сортировки не выражается shorthand-строкой: "' + $f + '"')
				[void]$items.Add($stub)
			} elseif ($d -ceq 'Desc') {
				[void]$items.Add($f + ' desc')
			} else {
				[void]$items.Add($f)
			}
		} else {
			$stub = [ordered]@{}
			Add-Todo $stub ('элемент сортировки не поддержан: ' + $xt)
			[void]$items.Add($stub)
		}
	}
	return ,$items
}

# === ConditionalAppearance / OutputParameters / DataParameters ===

function Build-ConditionalAppearance($caEl, $todoNode) {
	$out = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $caEl 'item')) {
		$node = [ordered]@{}
		$selEl = Get-Kid $it 'selection'
		if ($null -ne $selEl) {
			$flds = New-Object System.Collections.Generic.List[object]
			foreach ($x in (Get-Kids $selEl 'item')) {
				$f = Get-Text (Get-Kid $x 'field')
				if ($f -cne '') { [void]$flds.Add($f) }
			}
			if ($flds.Count -gt 0) { $node['selection'] = $flds }
		}
		$fEl = Get-Kid $it 'filter'
		if ($null -ne $fEl) {
			$flt = Build-Filter $fEl $node
			if ($flt.Count -gt 0) { $node['filter'] = $flt }
		}
		$appEl = Get-Kid $it 'appearance'
		if ($null -ne $appEl) {
			$app = Get-AppearanceMap $appEl $node
			if ($app.Count -gt 0) { $node['appearance'] = $app }
		}
		$pEl = Get-Kid $it 'presentation'
		if ($null -ne $pEl) {
			$pres = Get-MlText $pEl $node
			if ($pres -cne '') { $node['presentation'] = $pres }
		}
		$vm = (Get-Text (Get-Kid $it 'viewMode')).Trim()
		if ($vm -cne '') { $node['viewMode'] = $vm }
		$uid = (Get-Text (Get-Kid $it 'userSettingID')).Trim()
		if ($uid -cne '') { $node['userSettingID'] = $uid }
		if ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false') {
			Add-Todo $node 'условное оформление: use=false не поддержано нашим DSL'
		}
		$scopeEl = Get-Kid $it 'scope'
		if ($null -ne $scopeEl) {
			$hasContent = ((Get-Text $scopeEl).Trim() -cne '')
			foreach ($sc in $scopeEl.ChildNodes) {
				if ($sc.NodeType -eq 'Element') { $hasContent = $true }
			}
			if ($hasContent) { Add-Todo $node 'область применения (scope) не поддержана нашим DSL' }
		}
		if ($null -ne (Get-Kid $it 'userSettingPresentation')) {
			Add-Todo $node 'условное оформление: userSettingPresentation не поддержан'
		}
		[void]$out.Add($node)
	}
	return ,$out
}

function Build-OutputParams($opEl, $todoNode) {
	$result = [ordered]@{}
	foreach ($it in (Get-Kids $opEl 'item')) {
		$p = (Get-Text (Get-Kid $it 'parameter')).Trim()
		if ($p -ceq '') { continue }
		$val = Get-SettingValue (Get-Kid $it 'value') $todoNode $p
		if ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false') {
			Add-Todo $todoNode ('параметр вывода "' + $p + '": use=false не поддержан, значение сохранено как активное')
		}
		$result[$p] = $val
	}
	return $result
}

function Build-DataParameters($dpEl, $todoNode) {
	$items = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $dpEl 'item')) {
		$node = [ordered]@{}
		$node['parameter'] = Get-Text (Get-Kid $it 'parameter')
		$useOff = ((Get-Text (Get-Kid $it 'use')).Trim() -ceq 'false')
		$variant = $null
		$vEl = Get-Kid $it 'value'
		if ($null -ne $vEl) {
			if (Get-XsiNil $vEl) {
				$node['nilValue'] = $true
			} else {
				$vxt = Get-XsiLocal $vEl
				if ($vxt -ceq 'StandardPeriod') {
					$variant = (Get-Text (Get-Kid $vEl 'variant')).Trim()
					$vv = [ordered]@{}
					$vv['variant'] = $variant
					$node['value'] = $vv
					$sd = (Get-Text (Get-Kid $vEl 'startDate')).Trim()
					$ed = (Get-Text (Get-Kid $vEl 'endDate')).Trim()
					if (($sd -cne '' -and $sd -cne $script:ZeroDate) -or ($ed -cne '' -and $ed -cne $script:ZeroDate)) {
						Add-Todo $node ('нестандартные даты StandardPeriod потеряны: ' + $sd + ' / ' + $ed)
					}
				} elseif ($vxt -ceq 'boolean') {
					$node['value'] = ((Get-Text $vEl).Trim() -ceq 'true')
				} else {
					$node['value'] = Get-Text $vEl
					if ($vxt -ceq 'decimal') { $node['valueType'] = 'decimal' }
				}
			}
		}
		if ($useOff) { $node['use'] = $false }
		$vm = (Get-Text (Get-Kid $it 'viewMode')).Trim()
		if ($vm -cne '') { $node['viewMode'] = $vm }
		$uid = (Get-Text (Get-Kid $it 'userSettingID')).Trim()
		if ($uid -cne '') { $node['userSettingID'] = $uid }
		$usp = ''
		$uspEl = Get-Kid $it 'userSettingPresentation'
		if ($null -ne $uspEl) { $usp = Get-MlText $uspEl $node }
		if ($usp -cne '') { $node['userSettingPresentation'] = $usp }

		$v = $null
		if ($node.Contains('value')) { $v = $node['value'] }
		$vStr = $null
		if ($v -is [System.Collections.IDictionary]) {
			$vStr = $variant
		} elseif ($v -is [bool]) {
			if ($v) { $vStr = 'true' } else { $vStr = 'false' }
		} elseif ($null -ne $v) {
			$vStr = [string]$v
			if ($script:PeriodVariants -ccontains $vStr) { $vStr = $null }
		}
		$valueOk = $true
		if ($null -ne $v) {
			$valueOk = ($null -ne $vStr -and $vStr -cne '' -and -not $vStr.Contains('@') -and
				-not $vStr.Contains("`n") -and $vStr.Trim() -ceq $vStr)
		}
		$canShort = ((-not $node.Contains('_todo')) -and $usp -ceq '' -and
			(-not $node.Contains('nilValue')) -and (-not $node.Contains('valueType')) -and
			($vm -ceq '' -or $vm -ceq 'QuickAccess' -or $vm -ceq 'Normal') -and
			(Test-SimpleName $node['parameter']) -and $valueOk)
		if ($canShort) {
			$s = [string]$node['parameter']
			if ($null -ne $vStr) { $s += ' = ' + $vStr }
			if ($useOff) { $s += ' @off' }
			if ($uid -cne '') { $s += ' @user' }
			if ($vm -ceq 'QuickAccess') { $s += ' @quickAccess' }
			elseif ($vm -ceq 'Normal') { $s += ' @normal' }
			[void]$items.Add($s)
		} else {
			[void]$items.Add($node)
		}
	}
	return ,$items
}

# === Structure ===

function Build-GroupItems($giEl, $todoNode) {
	$fields = New-Object System.Collections.Generic.List[object]
	foreach ($it in (Get-Kids $giEl 'item')) {
		$xt = Get-XsiLocal $it
		if ($xt -ceq 'GroupItemField') {
			$f = Get-Text (Get-Kid $it 'field')
			$gt = (Get-Text (Get-Kid $it 'groupType')).Trim()
			if ($gt -ceq '') { $gt = 'Items' }
			$pat = (Get-Text (Get-Kid $it 'periodAdditionType')).Trim()
			if ($pat -ceq '') { $pat = 'None' }
			$pab = (Get-Text (Get-Kid $it 'periodAdditionBegin')).Trim()
			$pae = (Get-Text (Get-Kid $it 'periodAdditionEnd')).Trim()
			if ($gt -ceq 'Items' -and $pat -ceq 'None') {
				[void]$fields.Add($f)
			} else {
				$obj = [ordered]@{}
				$obj['field'] = $f
				if ($gt -cne 'Items') { $obj['groupType'] = $gt }
				if ($pat -cne 'None') { $obj['periodAdditionType'] = $pat }
				[void]$fields.Add($obj)
			}
			if (($pab -cne '' -and $pab -cne $script:ZeroDate) -or ($pae -cne '' -and $pae -cne $script:ZeroDate)) {
				Add-Todo $todoNode ('границы добавления периода у "' + $f + '" потеряны')
			}
		} elseif ($xt -ceq 'GroupItemAuto') {
			$stub = [ordered]@{}
			Add-Todo $stub 'группировка Авто (GroupItemAuto) не поддержана нашим DSL'
			[void]$fields.Add($stub)
		} else {
			$stub = [ordered]@{}
			Add-Todo $stub ('элемент группировки не поддержан: ' + $xt)
			[void]$fields.Add($stub)
		}
	}
	return ,$fields
}

function Set-StructureExtras($el, $node, $handled) {
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -ne 'Element') { continue }
		$ln = $c.LocalName
		if ($handled -ccontains $ln) { continue }
		if ($ln -ceq 'userSettingID') {
			$script:DroppedSettingIds += 1
		} elseif ($ln -ceq 'viewMode') {
			$vm = (Get-Text $c).Trim()
			if ($vm -cne 'Normal') {
				Add-Todo $node ('элемент структуры: viewMode=' + $vm + ' не поддержан')
			}
		} elseif ($ln -ceq 'use') {
			if ((Get-Text $c).Trim() -ceq 'false') {
				Add-Todo $node 'элемент структуры: use=false не поддержан нашим DSL'
			}
		} elseif ($script:StructureExtraTodo -ccontains $ln) {
			Add-Todo $node ('элемент структуры: ' + $ln + ' не поддержан нашим DSL')
		} else {
			Add-Todo $node ('элемент структуры не поддержан: ' + $ln)
		}
	}
}

function Set-StructureContent($el, $node, $withChildren) {
	$nEl = Get-Kid $el 'name'
	if ($null -ne $nEl -and (Get-Text $nEl) -cne '') { $node['name'] = Get-Text $nEl }
	$giEl = Get-Kid $el 'groupItems'
	if ($null -ne $giEl) { $node['groupBy'] = Build-GroupItems $giEl $node }
	$ordEl = Get-Kid $el 'order'
	if ($null -ne $ordEl) {
		$o = Build-Order $ordEl $node
		if ($o.Count -gt 0 -and -not ($o.Count -eq 1 -and $o[0] -is [string] -and $o[0] -ceq 'Auto')) {
			$node['order'] = $o
		}
	}
	$selEl = Get-Kid $el 'selection'
	if ($null -ne $selEl) {
		$s = Build-Selection $selEl $node
		if ($s.Count -gt 0 -and -not ($s.Count -eq 1 -and $s[0] -is [string] -and $s[0] -ceq 'Auto')) {
			$node['selection'] = $s
		}
	}
	$fEl = Get-Kid $el 'filter'
	if ($null -ne $fEl) {
		$flt = Build-Filter $fEl $node
		if ($flt.Count -gt 0) { $node['filter'] = $flt }
	}
	$caEl = Get-Kid $el 'conditionalAppearance'
	if ($null -ne $caEl) {
		$ca = Build-ConditionalAppearance $caEl $node
		if ($ca.Count -gt 0) { $node['conditionalAppearance'] = $ca }
	}
	$opEl = Get-Kid $el 'outputParameters'
	if ($null -ne $opEl) {
		$op = Build-OutputParams $opEl $node
		if ($op.Count -gt 0) { $node['outputParameters'] = $op }
	}
	$handled = New-Object System.Collections.Generic.List[object]
	foreach ($h in @('name', 'groupItems', 'order', 'selection', 'filter',
			'conditionalAppearance', 'outputParameters')) { [void]$handled.Add($h) }
	if ($withChildren) {
		$children = New-Object System.Collections.Generic.List[object]
		foreach ($c in (Get-Kids $el 'item')) { [void]$children.Add((Build-StructureItem $c)) }
		if ($children.Count -gt 0) { $node['children'] = $children }
		[void]$handled.Add('item')
	}
	Set-StructureExtras $el $node $handled
}

function Build-StructureItem($el) {
	$xt = Get-XsiLocal $el
	if ($xt -ceq '' -or $xt -ceq 'StructureItemGroup') {
		$node = [ordered]@{}
		Set-StructureContent $el $node $true
		return $node
	}
	if ($xt -ceq 'StructureItemTable') {
		$node = [ordered]@{}
		$node['type'] = 'table'
		$nEl = Get-Kid $el 'name'
		if ($null -ne $nEl -and (Get-Text $nEl) -cne '') { $node['name'] = Get-Text $nEl }
		$rows = New-Object System.Collections.Generic.List[object]
		foreach ($r in (Get-Kids $el 'row')) {
			$axis = [ordered]@{}
			Set-StructureContent $r $axis $false
			[void]$rows.Add($axis)
		}
		$cols = New-Object System.Collections.Generic.List[object]
		foreach ($c in (Get-Kids $el 'column')) {
			$axis = [ordered]@{}
			Set-StructureContent $c $axis $false
			if ($axis.Contains('name')) {
				Add-Todo $axis 'имя колонки таблицы не поддержано компилятором'
			}
			[void]$cols.Add($axis)
		}
		if ($rows.Count -gt 0) { $node['rows'] = $rows }
		if ($cols.Count -gt 0) { $node['columns'] = $cols }
		$handled = New-Object System.Collections.Generic.List[object]
		foreach ($h in @('name', 'row', 'column')) { [void]$handled.Add($h) }
		foreach ($extra in @('selection', 'filter', 'conditionalAppearance', 'outputParameters')) {
			if ($null -ne (Get-Kid $el $extra)) {
				Add-Todo $node ('таблица структуры: ' + $extra + ' на уровне таблицы не поддержан')
				[void]$handled.Add($extra)
			}
		}
		Set-StructureExtras $el $node $handled
		return $node
	}
	if ($xt -ceq 'StructureItemChart') {
		$node = [ordered]@{}
		$node['type'] = 'chart'
		$nEl = Get-Kid $el 'name'
		if ($null -ne $nEl -and (Get-Text $nEl) -cne '') { $node['name'] = Get-Text $nEl }
		$points = Get-Kids $el 'point'
		if ($points.Count -gt 0) {
			$axis = [ordered]@{}
			Set-StructureContent $points[0] $axis $false
			$node['points'] = $axis
			if ($points.Count -gt 1) { Add-Todo $node 'несколько точек диаграммы: сохранена только первая' }
		}
		$series = Get-Kids $el 'series'
		if ($series.Count -gt 0) {
			$axis = [ordered]@{}
			Set-StructureContent $series[0] $axis $false
			$node['series'] = $axis
			if ($series.Count -gt 1) { Add-Todo $node 'несколько серий диаграммы: сохранена только первая' }
		}
		$selEl = Get-Kid $el 'selection'
		if ($null -ne $selEl) {
			$s = Build-Selection $selEl $node
			if ($s.Count -gt 0) { $node['selection'] = $s }
		}
		$opEl = Get-Kid $el 'outputParameters'
		if ($null -ne $opEl) {
			$op = Build-OutputParams $opEl $node
			if ($op.Count -gt 0) { $node['outputParameters'] = $op }
		}
		$handled = New-Object System.Collections.Generic.List[object]
		foreach ($h in @('name', 'point', 'series', 'selection', 'outputParameters')) { [void]$handled.Add($h) }
		Set-StructureExtras $el $node $handled
		return $node
	}
	$stub = [ordered]@{}
	Add-Todo $stub ('элемент структуры не поддержан: ' + $xt)
	return $stub
}

function Get-StructureShorthand($items) {
	$segments = New-Object System.Collections.Generic.List[object]
	$current = $items
	while ($true) {
		if ($current.Count -ne 1 -or -not ($current[0] -is [System.Collections.IDictionary])) { return $null }
		$node = $current[0]
		foreach ($k in $node.Keys) {
			if ($k -cne 'groupBy' -and $k -cne 'children') { return $null }
		}
		$gb = $null
		if ($node.Contains('groupBy')) { $gb = $node['groupBy'] }
		$children = $null
		if ($node.Contains('children')) { $children = $node['children'] }
		if ($null -eq $gb -or $gb.Count -eq 0) {
			if ($null -ne $children -and $children.Count -gt 0) { return $null }
			[void]$segments.Add('details')
			break
		}
		if ($gb.Count -ne 1 -or -not ($gb[0] -is [string]) -or -not (Test-SimpleName $gb[0])) { return $null }
		[void]$segments.Add($gb[0])
		if ($null -eq $children -or $children.Count -eq 0) { break }
		$current = $children
	}
	if ($segments.Count -eq 0) { return $null }
	return ($segments -join ' > ')
}

# === Settings variants ===

function Build-Settings($settingsEl) {
	$s = [ordered]@{}
	$selEl = Get-Kid $settingsEl 'selection'
	if ($null -ne $selEl) {
		$selList = Build-Selection $selEl $s
		if ($selList.Count -gt 0) { $s['selection'] = $selList }
	}
	$fEl = Get-Kid $settingsEl 'filter'
	if ($null -ne $fEl) {
		$flt = Build-Filter $fEl $s
		if ($flt.Count -gt 0) { $s['filter'] = $flt }
	}
	$ordEl = Get-Kid $settingsEl 'order'
	if ($null -ne $ordEl) {
		$o = Build-Order $ordEl $s
		if ($o.Count -gt 0) { $s['order'] = $o }
	}
	$caEl = Get-Kid $settingsEl 'conditionalAppearance'
	if ($null -ne $caEl) {
		$ca = Build-ConditionalAppearance $caEl $s
		if ($ca.Count -gt 0) { $s['conditionalAppearance'] = $ca }
	}
	$opEl = Get-Kid $settingsEl 'outputParameters'
	if ($null -ne $opEl) {
		$op = Build-OutputParams $opEl $s
		if ($op.Count -gt 0) { $s['outputParameters'] = $op }
	}
	$dpEl = Get-Kid $settingsEl 'dataParameters'
	if ($null -ne $dpEl) {
		$dp = Build-DataParameters $dpEl $s
		if ($dp.Count -gt 0) { $s['dataParameters'] = $dp }
	}
	$structItems = New-Object System.Collections.Generic.List[object]
	foreach ($c in (Get-Kids $settingsEl 'item')) { [void]$structItems.Add((Build-StructureItem $c)) }
	if ($structItems.Count -gt 0) {
		$short = Get-StructureShorthand $structItems
		if ($null -ne $short) { $s['structure'] = $short } else { $s['structure'] = $structItems }
	}
	$handled = @('selection', 'filter', 'order', 'conditionalAppearance',
		'outputParameters', 'dataParameters', 'item')
	foreach ($c in $settingsEl.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $s ('настройка варианта не поддержана: ' + $c.LocalName)
		}
	}
	return $s
}

function Build-Variant($vEl) {
	$node = [ordered]@{}
	$node['name'] = Get-Text (Get-Kid $vEl 'name')
	$pEl = Get-Kid $vEl 'presentation'
	$pres = ''
	if ($null -ne $pEl) { $pres = Get-MlText $pEl $node }
	if ($pres -cne '' -and $pres -cne $node['name']) { $node['presentation'] = $pres }
	$sEl = Get-Kid $vEl 'settings'
	if ($null -ne $sEl) { $node['settings'] = Build-Settings $sEl }
	$handled = @('name', 'presentation', 'settings')
	foreach ($c in $vEl.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент варианта настроек не поддержан: ' + $c.LocalName)
		}
	}
	return $node
}

function Test-DefaultVariant($v) {
	if ($v['name'] -cne $script:VariantMain -or $v.Contains('presentation') -or $v.Contains('_todo')) {
		return $false
	}
	if (-not $v.Contains('settings')) { return $true }
	$s = $v['settings']
	foreach ($k in $s.Keys) {
		if ($k -cne 'structure') { return $false }
	}
	if (-not $s.Contains('structure')) { return $true }
	$st = $s['structure']
	return ($st -is [string] -and $st -ceq 'details')
}

# === Templates ===

function Get-ParsedNumber($s) {
	$d = 0.0
	$ok = [double]::TryParse($s, [System.Globalization.NumberStyles]::Float,
		[System.Globalization.CultureInfo]::InvariantCulture, [ref]$d)
	if (-not $ok) { return 0 }
	if ($d -eq [math]::Floor($d)) { return [int64]$d }
	return $d
}

function Build-TemplateCell($cellEl, $tplNode) {
	$info = @{ width = 0; minHeight = 0; dd = ''; probe = $null; content = $null }
	$vMerge = $false
	$hMerge = $false
	$appEl = Get-Kid $cellEl 'appearance'
	if ($null -ne $appEl) {
		$probe = @{}
		foreach ($it in (Get-Kids $appEl 'item')) {
			$p = (Get-Text (Get-Kid $it 'parameter')).Trim()
			$vEl = Get-Kid $it 'value'
			$vTxt = ''
			if ($null -ne $vEl) { $vTxt = (Get-Text $vEl).Trim() }
			if ($p -ceq 'ОбъединятьПоВертикали' -and $vTxt -ceq 'true') { $vMerge = $true }
			elseif ($p -ceq 'ОбъединятьПоГоризонтали' -and $vTxt -ceq 'true') { $hMerge = $true }
			elseif ($p -ceq 'МинимальнаяШирина') { $info.width = Get-ParsedNumber $vTxt }
			elseif ($p -ceq 'МинимальнаяВысота') { $info.minHeight = Get-ParsedNumber $vTxt }
			elseif ($p -ceq 'Расшифровка') { $info.dd = $vTxt }
			elseif ($p -ceq 'ЦветФона') { $probe['bg'] = Resolve-ColorValue $vTxt $vEl }
			elseif ($p -ceq 'ГоризонтальноеПоложение') { $probe['hAlign'] = $vTxt }
			elseif ($p -ceq 'Размещение') { $probe['wrap'] = ($vTxt -ceq 'Wrap') }
			elseif ($p -ceq 'Шрифт') { $probe['font'] = $true }
		}
		if ($probe.Count -gt 0) { $info.probe = $probe }
	}
	$content = $null
	$itemEl = Get-Kid $cellEl 'item'
	if ($null -ne $itemEl) {
		$ixt = Get-XsiLocal $itemEl
		if ($ixt -ceq 'Field') {
			$vEl = Get-Kid $itemEl 'value'
			$vxt = Get-XsiLocal $vEl
			if ($vxt -ceq 'Parameter') {
				$content = '{' + (Get-Text $vEl).Trim() + '}'
			} elseif ($vxt -ceq 'LocalStringType') {
				$content = Get-MlText $vEl $tplNode
			} else {
				$content = Get-Text $vEl
			}
		} elseif ($ixt.Contains('Picture')) {
			Add-Todo $tplNode ('ячейка макета с картинкой (' + $ixt + ') не поддержана')
		} else {
			Add-Todo $tplNode ('элемент ячейки макета не поддержан: ' + $ixt)
		}
	}
	if ($null -eq $content) {
		if ($vMerge) { $content = '|' }
		elseif ($hMerge) { $content = '>' }
	} elseif ($content -ceq '|') {
		$content = '\|'
	} elseif ($content -ceq '>') {
		$content = '\>'
	}
	$info.content = $content
	return $info
}

function Get-TemplateStyle($probe) {
	$bg = $null
	if ($probe.ContainsKey('bg')) { $bg = $probe['bg'] }
	$center = ($probe.ContainsKey('hAlign') -and $probe['hAlign'] -ceq 'Center')
	$wrap = ($probe.ContainsKey('wrap') -and $probe['wrap'] -eq $true)
	if ($bg -ceq 'style:ReportHeaderBackColor' -and $center -and $wrap) { return 'header' }
	if ($bg -ceq 'style:ReportGroup1BackColor' -and -not $center -and -not $wrap) { return 'data' }
	if ($null -eq $bg -and $center -and $wrap) { return 'subheader' }
	if ($null -eq $bg -and -not $center -and -not $wrap) { return 'total' }
	return $null
}

function Build-Template($el) {
	$node = [ordered]@{}
	$node['name'] = Get-Text (Get-Kid $el 'name')
	if ($null -ne (Get-Kid $el 'templateCondition')) {
		Add-Todo $node 'условие выбора макета (templateCondition) не поддержано нашим DSL'
	}
	$inner = Get-Kid $el 'template'
	$rows = New-Object System.Collections.Generic.List[object]
	$widths = New-Object System.Collections.Generic.List[object]
	$minHeight = 0
	$firstProbe = $null
	$cellDd = [ordered]@{}
	if ($null -ne $inner) {
		foreach ($rowEl in (Get-Kids $inner 'item')) {
			$rxt = Get-XsiLocal $rowEl
			if ($rxt -cne 'TableRow') {
				Add-Todo $node ('элемент области макета не поддержан: ' + $rxt)
				continue
			}
			$row = New-Object System.Collections.Generic.List[object]
			$cI = 0
			foreach ($cellEl in (Get-Kids $rowEl 'tableCell')) {
				$info = Build-TemplateCell $cellEl $node
				[void]$row.Add($info.content)
				if ($rows.Count -eq 0) {
					[void]$widths.Add($info.width)
					if ($cI -eq 0) { $minHeight = $info.minHeight }
				}
				if ($null -eq $firstProbe -and $null -ne $info.probe) { $firstProbe = $info.probe }
				$content = $info.content
				if ($info.dd -cne '' -and $content -is [string] -and
					$content.StartsWith('{') -and $content.EndsWith('}')) {
					$cellDd[$content.Substring(1, $content.Length - 2)] = $info.dd
				}
				$cI += 1
			}
			[void]$rows.Add($row)
		}
	} else {
		Add-Todo $node 'макет без области AreaTemplate - строки не декомпилированы'
	}
	$style = $null
	if ($null -ne $firstProbe) {
		$style = Get-TemplateStyle $firstProbe
		if ($null -eq $style) {
			Add-Todo $node 'оформление ячеек не распознано - подбери style вручную (header/data/subheader/total или skd-styles.json)'
		}
	}
	if ($null -ne $style -and $style -cne 'data') { $node['style'] = $style }
	$hasWidth = $false
	foreach ($w in $widths) { if ($w -ne 0) { $hasWidth = $true } }
	if ($hasWidth) { $node['widths'] = $widths }
	if ($minHeight -ne 0) { $node['minHeight'] = $minHeight }
	$node['rows'] = $rows

	$params = New-Object System.Collections.Generic.List[object]
	$details = New-Object System.Collections.Generic.List[object]
	foreach ($pEl in (Get-Kids $el 'parameter')) {
		$pxt = Get-XsiLocal $pEl
		if ($pxt -ceq 'ExpressionAreaTemplateParameter') {
			$pObj = [ordered]@{}
			$pObj['name'] = Get-Text (Get-Kid $pEl 'name')
			$pObj['expression'] = Get-Text (Get-Kid $pEl 'expression')
			[void]$params.Add($pObj)
		} elseif ($pxt -ceq 'DetailsAreaTemplateParameter') {
			$fe = Get-Kid $pEl 'fieldExpression'
			$dObj = @{
				name = Get-Text (Get-Kid $pEl 'name')
				field = ''
				expr = ''
				action = (Get-Text (Get-Kid $pEl 'mainAction')).Trim()
			}
			if ($null -ne $fe) {
				$dObj.field = Get-Text (Get-Kid $fe 'field')
				$dObj.expr = Get-Text (Get-Kid $fe 'expression')
			}
			[void]$details.Add($dObj)
		} else {
			Add-Todo $node ('параметр макета не поддержан: ' + $pxt)
		}
	}
	$byName = @{}
	foreach ($p in $params) { $byName[$p['name']] = $p }
	foreach ($d in $details) {
		$target = $null
		$m = [regex]::Match($d.name, '^Расшифровка_(.+)$')
		if ($m.Success -and $d.field -ceq 'ИмяРесурса' -and $d.action -ceq 'DrillDown' -and
			$d.expr -ceq ('"' + $m.Groups[1].Value + '"')) {
			foreach ($pname in $cellDd.Keys) {
				if ($cellDd[$pname] -ceq $d.name -and $byName.ContainsKey($pname)) {
					$target = $byName[$pname]
					break
				}
			}
			if ($null -ne $target) {
				$target['drilldown'] = $m.Groups[1].Value
				continue
			}
		}
		Add-Todo $node ('параметр расшифровки макета не свернут: ' + $d.name)
	}
	if ($params.Count -gt 0) { $node['parameters'] = $params }

	$handled = @('name', 'template', 'parameter', 'templateCondition')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент макета не поддержан: ' + $c.LocalName)
		}
	}
	return $node
}

function Build-GroupTemplateNode($el, $ttypeOverride) {
	$node = [ordered]@{}
	$gn = Get-Kid $el 'groupName'
	$gf = Get-Kid $el 'groupField'
	if ($null -ne $gn -and (Get-Text $gn) -cne '') {
		$node['groupName'] = Get-Text $gn
	} elseif ($null -ne $gf) {
		$node['groupField'] = Get-Text $gf
	}
	$xmlTtype = (Get-Text (Get-Kid $el 'templateType')).Trim()
	if ($null -ne $ttypeOverride) {
		$node['templateType'] = $ttypeOverride
	} elseif ($xmlTtype -cne '') {
		$node['templateType'] = $xmlTtype
	} else {
		$node['templateType'] = 'Header'
	}
	$node['template'] = Get-Text (Get-Kid $el 'template')
	$handled = @('groupName', 'groupField', 'templateType', 'template')
	foreach ($c in $el.ChildNodes) {
		if ($c.NodeType -eq 'Element' -and $handled -cnotcontains $c.LocalName) {
			Add-Todo $node ('элемент привязки макета не поддержан: ' + $c.LocalName)
		}
	}
	return $node
}

# === JSON writer (PS 5.1 ConvertTo-Json mangles unicode and layout) ===

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

function ConvertTo-DraftJson($v, $indent) {
	if ($null -eq $v) { return 'null' }
	if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
	if ($v -is [int] -or $v -is [int64] -or $v -is [double] -or $v -is [decimal]) {
		return [System.Convert]::ToString($v, [System.Globalization.CultureInfo]::InvariantCulture)
	}
	if ($v -is [string]) { return ConvertTo-JsonStringLiteral $v }
	if ($v -is [System.Collections.IDictionary]) {
		if ($v.Count -eq 0) { return '{}' }
		$inner = $indent + '  '
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($k in $v.Keys) {
			[void]$parts.Add($inner + (ConvertTo-JsonStringLiteral ([string]$k)) + ': ' + (ConvertTo-DraftJson $v[$k] $inner))
		}
		return "{`n" + ($parts -join ",`n") + "`n" + $indent + '}'
	}
	if ($v -is [System.Collections.IEnumerable]) {
		$inner = $indent + '  '
		$parts = New-Object System.Collections.Generic.List[object]
		foreach ($it in $v) {
			[void]$parts.Add($inner + (ConvertTo-DraftJson $it $inner))
		}
		if ($parts.Count -eq 0) { return '[]' }
		return "[`n" + ($parts -join ",`n") + "`n" + $indent + ']'
	}
	return ConvertTo-JsonStringLiteral ([string]$v)
}

# === Main ===

if ([string]::IsNullOrEmpty($TemplatePath)) {
	[Console]::Error.WriteLine('Параметр -TemplatePath обязателен')
	exit 1
}
if (-not (Test-Path -LiteralPath $TemplatePath)) {
	[Console]::Error.WriteLine('Файл не найден: ' + $TemplatePath)
	exit 1
}
$inPath = (Resolve-Path -LiteralPath $TemplatePath).Path

$xmlDoc = New-Object System.Xml.XmlDocument
$xmlDoc.PreserveWhitespace = $false
try {
	$xmlDoc.Load($inPath)
} catch {
	[Console]::Error.WriteLine('Ошибка разбора XML: ' + $_.Exception.Message)
	exit 1
}

$root = $xmlDoc.DocumentElement
if ($null -eq $root -or $root.LocalName -cne 'DataCompositionSchema') {
	$found = '(пусто)'
	if ($null -ne $root) { $found = $root.LocalName }
	[Console]::Error.WriteLine('Корневой элемент не DataCompositionSchema: ' + $found)
	exit 1
}

$outPath = $OutputPath
if ([string]::IsNullOrEmpty($outPath)) {
	$dir = [System.IO.Path]::GetDirectoryName($inPath)
	$base = [System.IO.Path]::GetFileNameWithoutExtension($inPath)
	$outPath = [System.IO.Path]::Combine($dir, $base + '.skd.json')
}
if (-not [System.IO.Path]::IsPathRooted($outPath)) {
	$outPath = [System.IO.Path]::Combine((Get-Location).Path, $outPath)
}

$rootTodos = New-Object System.Collections.Generic.List[object]
function Add-RootTodo($msg) {
	[void]$rootTodos.Add($msg)
	[void]$script:Warnings.Add($msg)
}

$result = [ordered]@{}

$sources = New-Object System.Collections.Generic.List[object]
foreach ($ds in (Get-Kids $root 'dataSource')) {
	$srcObj = [ordered]@{}
	$srcObj['name'] = Get-Text (Get-Kid $ds 'name')
	$srcType = (Get-Text (Get-Kid $ds 'dataSourceType')).Trim()
	if ($srcType -ceq '') { $srcType = 'Local' }
	$srcObj['type'] = $srcType
	[void]$sources.Add($srcObj)
}
$defaultSource = $script:DefaultSourceName
if ($sources.Count -gt 0) { $defaultSource = $sources[0]['name'] }
$isDefaultSources = ($sources.Count -le 1 -and $defaultSource -ceq $script:DefaultSourceName -and
	($sources.Count -eq 0 -or $sources[0]['type'] -ceq 'Local'))
if (-not $isDefaultSources) { $result['dataSources'] = $sources }

$dataSets = New-Object System.Collections.Generic.List[object]
foreach ($ds in (Get-Kids $root 'dataSet')) {
	[void]$dataSets.Add((Build-DataSet $ds $defaultSource))
}
if ($dataSets.Count -eq 0) {
	Add-RootTodo 'в схеме нет ни одного dataSet - /skd-compile требует минимум один набор данных'
}
$result['dataSets'] = $dataSets

$links = New-Object System.Collections.Generic.List[object]
foreach ($l in (Get-Kids $root 'dataSetLink')) { [void]$links.Add((Build-Link $l)) }
if ($links.Count -gt 0) { $result['dataSetLinks'] = $links }

$calc = New-Object System.Collections.Generic.List[object]
foreach ($c in (Get-Kids $root 'calculatedField')) { [void]$calc.Add((Build-CalcField $c)) }
if ($calc.Count -gt 0) { $result['calculatedFields'] = $calc }

$totals = New-Object System.Collections.Generic.List[object]
foreach ($t in (Get-Kids $root 'totalField')) { [void]$totals.Add((Build-TotalField $t)) }
if ($totals.Count -gt 0) { $result['totalFields'] = $totals }

$rawParams = New-Object System.Collections.Generic.List[object]
foreach ($p in (Get-Kids $root 'parameter')) { [void]$rawParams.Add((Build-Parameter $p)) }
$rawParams = Invoke-AutoDatesCollapse $rawParams
$params = New-Object System.Collections.Generic.List[object]
foreach ($p in $rawParams) { [void]$params.Add((ConvertTo-ParamShorthand $p)) }
if ($params.Count -gt 0) { $result['parameters'] = $params }

$templates = New-Object System.Collections.Generic.List[object]
foreach ($t in (Get-Kids $root 'template')) { [void]$templates.Add((Build-Template $t)) }
if ($templates.Count -gt 0) { $result['templates'] = $templates }

foreach ($ft in (Get-Kids $root 'fieldTemplate')) {
	$fld = Get-Text (Get-Kid $ft 'field')
	Add-RootTodo ('привязка макета к полю (fieldTemplate "' + $fld + '") не поддержана нашим DSL')
}

$groupTemplates = New-Object System.Collections.Generic.List[object]
foreach ($gt in (Get-Kids $root 'groupHeaderTemplate')) {
	[void]$groupTemplates.Add((Build-GroupTemplateNode $gt 'GroupHeader'))
}
foreach ($gt in (Get-Kids $root 'groupTemplate')) {
	[void]$groupTemplates.Add((Build-GroupTemplateNode $gt $null))
}
if ($groupTemplates.Count -gt 0) { $result['groupTemplates'] = $groupTemplates }

$variants = New-Object System.Collections.Generic.List[object]
foreach ($v in (Get-Kids $root 'settingsVariant')) { [void]$variants.Add((Build-Variant $v)) }
if ($variants.Count -gt 0 -and -not ($variants.Count -eq 1 -and (Test-DefaultVariant $variants[0]))) {
	$result['settingsVariants'] = $variants
}

$knownRoot = @('dataSource', 'dataSet', 'dataSetLink', 'calculatedField', 'totalField',
	'parameter', 'template', 'fieldTemplate', 'groupHeaderTemplate',
	'groupTemplate', 'settingsVariant')
$seenUnknown = New-Object System.Collections.Generic.List[object]
foreach ($c in $root.ChildNodes) {
	if ($c.NodeType -ne 'Element') { continue }
	$ln = $c.LocalName
	if ($knownRoot -cnotcontains $ln -and $seenUnknown -cnotcontains $ln) {
		[void]$seenUnknown.Add($ln)
		Add-RootTodo ('элемент схемы не поддержан: ' + $ln)
	}
}

if ($script:DroppedSettingIds -gt 0) {
	Add-RootTodo ('userSettingID у ' + $script:DroppedSettingIds + ' элементов структуры отброшены (наш DSL их не выражает)')
}

if ($rootTodos.Count -gt 0) {
	$final = [ordered]@{}
	$final['_todo'] = $rootTodos
	foreach ($k in $result.Keys) { $final[$k] = $result[$k] }
	$result = $final
}

$outDir = [System.IO.Path]::GetDirectoryName($outPath)
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
	[void][System.IO.Directory]::CreateDirectory($outDir)
}
$json = (ConvertTo-DraftJson $result '') + "`n"
[System.IO.File]::WriteAllText($outPath, $json, (New-Object System.Text.UTF8Encoding($false)))

foreach ($w in $script:Warnings) {
	[Console]::Error.WriteLine('TODO: ' + $w)
}

Write-Output ('OK  ' + $outPath)
Write-Output ('    DataSets: ' + $dataSets.Count + '  Links: ' + $links.Count +
	'  Calculated: ' + $calc.Count + '  Totals: ' + $totals.Count +
	'  Params: ' + $params.Count + '  Templates: ' + $templates.Count +
	'  GroupTemplates: ' + $groupTemplates.Count + '  Variants: ' + $variants.Count +
	'  Todos: ' + $script:Warnings.Count)
exit 0
