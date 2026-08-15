# help-add v1.3 — Add built-in help to 1C object
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$ObjectName,

	[string]$Lang = "ru",

	[string]$SrcDir = "src"
)

$ErrorActionPreference = "Stop"

# --- Detect format version ---

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

$formatVersion = Detect-FormatVersion (Resolve-Path $SrcDir).Path

# --- Проверки ---

$objectDir = Join-Path $SrcDir $ObjectName
$extDir = Join-Path $objectDir "Ext"

if (-not (Test-Path $extDir)) {
	Write-Error "Каталог объекта не найден: $extDir. Проверьте путь ObjectName (например Catalogs/МойСправочник)."
	exit 1
}

$helpXmlPath = Join-Path $extDir "Help.xml"
if (Test-Path $helpXmlPath) {
	Write-Error "Справка уже существует: $helpXmlPath"
	exit 1
}

# --- Кодировка ---

$encBom = New-Object System.Text.UTF8Encoding($true)

# --- 1. Help.xml ---

$helpXml = @"
<?xml version="1.0" encoding="UTF-8"?>
<Help xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="$formatVersion">
	<Page>$Lang</Page>
</Help>
"@

[System.IO.File]::WriteAllText($helpXmlPath, $helpXml, $encBom)

# --- 2. Help/<lang>.html ---

$helpDir = Join-Path $extDir "Help"
New-Item -ItemType Directory -Path $helpDir -Force | Out-Null

$helpHtmlPath = Join-Path $helpDir "$Lang.html"

$helpHtml = @"
<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <link rel="stylesheet" type="text/css" href="v8help://service_book/service_style"/>
</head>
<body>
    <h1>$ObjectName</h1>
    <p>Описание.</p>
</body>
</html>
"@

[System.IO.File]::WriteAllText($helpHtmlPath, $helpHtml, $encBom)

# --- 3. Проверка IncludeHelpInContents в метаданных форм ---

$formsDir = Join-Path $objectDir "Forms"
if (Test-Path $formsDir) {
	$formMetaFiles = Get-ChildItem -Path $formsDir -Filter "*.xml" -File
	foreach ($formMeta in $formMetaFiles) {
		$xmlDoc = New-Object System.Xml.XmlDocument
		$xmlDoc.PreserveWhitespace = $true
		$xmlDoc.Load($formMeta.FullName)

		$nsMgr = New-Object System.Xml.XmlNamespaceManager($xmlDoc.NameTable)
		$nsMgr.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")

		$includeHelp = $xmlDoc.SelectSingleNode("//md:IncludeHelpInContents", $nsMgr)
		if (-not $includeHelp) {
			# Добавить после <FormType>
			$formType = $xmlDoc.SelectSingleNode("//md:FormType", $nsMgr)
			if ($formType) {
				$newElem = $xmlDoc.CreateElement("IncludeHelpInContents", "http://v8.1c.ru/8.3/MDClasses")
				$newElem.InnerText = "false"
				$parent = $formType.ParentNode
				$nextSibling = $formType.NextSibling
				# Вставить перенос + табуляцию + элемент
				$ws = $xmlDoc.CreateWhitespace("`n`t`t`t")
				if ($nextSibling) {
					$parent.InsertBefore($ws, $nextSibling) | Out-Null
					$parent.InsertBefore($newElem, $ws) | Out-Null
				} else {
					$parent.AppendChild($ws) | Out-Null
					$parent.AppendChild($newElem) | Out-Null
				}

				$settings = New-Object System.Xml.XmlWriterSettings
				$settings.Encoding = $encBom
				$settings.Indent = $false
				$stream = New-Object System.IO.FileStream($formMeta.FullName, [System.IO.FileMode]::Create)
				$writer = [System.Xml.XmlWriter]::Create($stream, $settings)
				$xmlDoc.Save($writer)
				$writer.Close()
				$stream.Close()
				# Пустой элемент: XmlWriter отдает `<a />`, Конфигуратор пишет `<a/>`. Внутри
				# CDATA/комментария или значения атрибута ` />` может быть содержимым,
				# поэтому они идут первыми ветками альтернации и возвращаются как есть.
				$tightPath = $formMeta.FullName
				$tightText = [System.IO.File]::ReadAllText($tightPath, [System.Text.Encoding]::UTF8)
				$tightText = [regex]::Replace($tightText, '(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|<([A-Za-z0-9_:.\-]+)((?:\s+[A-Za-z0-9_:.\-]+="[^"]*")*)\s+/>', { param($m) if ($m.Groups[1].Success) { '<' + $m.Groups[1].Value + $m.Groups[2].Value + '/>' } else { $m.Value } })
				[System.IO.File]::WriteAllText($tightPath, $tightText, (New-Object System.Text.UTF8Encoding($true)))

				Write-Host "     IncludeHelpInContents добавлен: $($formMeta.Name)"
			}
		}
	}
}

Write-Host "[OK] Создана справка: $ObjectName"
Write-Host "     Метаданные: $helpXmlPath"
Write-Host "     Страница:   $helpHtmlPath"
