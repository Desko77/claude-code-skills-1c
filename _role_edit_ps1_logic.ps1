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
    $pairs = New-Object System.Collections.Generic.List[object]
    if ($null -eq $Spec) { return ,$pairs }
    if ($Spec -is [string]) {
        foreach ($part in ($Spec -split ',')) {
            $name = $part.Trim()
            if ($name) { $pairs.Add(@{ Name = (Translate-RightName $name); Value = 'true' }) }
        }
        return ,$pairs
    }
    if ($Spec -is [System.Array]) {
        foreach ($part in $Spec) {
            $name = "$part".Trim()
            if ($name) { $pairs.Add(@{ Name = (Translate-RightName $name); Value = 'true' }) }
        }
        return ,$pairs
    }
    foreach ($prop in $Spec.PSObject.Properties) {
        $flag = 'false'
        if (ConvertTo-RightOn $prop.Value) { $flag = 'true' }
        $pairs.Add(@{ Name = (Translate-RightName $prop.Name); Value = $flag })
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
    $ops = New-Object System.Collections.Generic.List[object]
    foreach ($item in $items) {
        if ($null -eq $item) { Add-InputError 'операция: ожидался объект'; continue }
        $ops.Add($item)
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
    $found = New-Object System.Collections.Generic.List[object]
    foreach ($match in [regex]::Matches($Text, '(?s)[ \t]*<object>.*?</object>')) {
        $block = $match.Value
        $nameMatch = [regex]::Match($block, '(?s)<name>(.*?)</name>')
        $rights = New-Object System.Collections.Generic.List[object]
        foreach ($rightMatch in [regex]::Matches($block, '(?s)<right>\s*<name>(.*?)</name>\s*<value>(.*?)</value>(.*?)</right>')) {
            $condition = $null
            $condMatch = [regex]::Match($rightMatch.Groups[3].Value, '(?s)<condition>(.*?)</condition>')
            if ($condMatch.Success) {
                $condition = [System.Net.WebUtility]::HtmlDecode($condMatch.Groups[1].Value)
            }
            $rights.Add(@{
                Name = [System.Net.WebUtility]::HtmlDecode($rightMatch.Groups[1].Value.Trim())
                Value = $rightMatch.Groups[2].Value.Trim()
                Condition = $condition
            })
        }
        $objName = ''
        if ($nameMatch.Success) { $objName = [System.Net.WebUtility]::HtmlDecode($nameMatch.Groups[1].Value.Trim()) }
        $found.Add(@{
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
        $kept = New-Object System.Collections.Generic.List[object]
        foreach ($right in $current) {
            if (-not $drop.ContainsKey($right.Name)) { $kept.Add($right) }
        }
        $newRights = @(Complete-RoleRights $objName $kept)
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
        $newRights = New-Object System.Collections.Generic.List[object]
        foreach ($right in $current) {
            $item = @{ Name = $right.Name; Value = $right.Value; Condition = $right.Condition }
            if ($item.Name -eq $rightName -and $item.Condition) {
                $item.Condition = $null
                $changed = $true
            }
            $newRights.Add($item)
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
        $newRights = @(Finish-Rights -ObjectName $objName -RightsMap $map)
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
    $found = New-Object System.Collections.Generic.List[object]
    $pattern = '(?s)[ \t]*<restrictionTemplate>\s*<name>(.*?)</name>\s*<condition>(.*?)</condition>\s*</restrictionTemplate>'
    foreach ($match in [regex]::Matches($Text, $pattern)) {
        $found.Add(@{
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
    $ops = New-Object System.Collections.Generic.List[object]
    $ops.Add((New-InlineOperation))
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
Exit-InputErrors

if ($edited.Rights -ne $rightsFile.Text) {
    Write-RoleText $paths.Rights $edited.Rights $rightsFile.Bom $rightsFile.Crlf
}
if ($edited.Meta -ne $metaFile.Text) {
    Write-RoleText $paths.Meta $edited.Meta $metaFile.Bom $metaFile.Crlf
}

$label = Get-RoleLabel $edited.Meta $paths.Meta
Write-Host "role-edit: $label, операций $($ops.Count)"

if (-not $NoValidate) {
    $validateScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '1c-role-validate\scripts\role-validate.ps1'
    if (Test-Path -LiteralPath $validateScript) {
        Write-Host '--- role-validate ---'
        & powershell.exe -NoProfile -File $validateScript -RightsPath $paths.Rights
    }
}
