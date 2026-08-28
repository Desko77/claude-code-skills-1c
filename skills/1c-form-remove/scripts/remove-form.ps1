# form-remove v1.1 - Remove form from 1C object
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[Alias("ProcessorName")]
	[string]$ObjectName,

	[Parameter(Mandatory)]
	[string]$FormName,

	[string]$SrcDir = "src"
)

$ErrorActionPreference = "Stop"

# --- Проверки ---

$rootXmlPath = Join-Path $SrcDir "$ObjectName.xml"
if (-not (Test-Path $rootXmlPath)) {
	Write-Error "Корневой файл обработки не найден: $rootXmlPath"
	exit 1
}

$processorDir = Join-Path $SrcDir $ObjectName
$formsDir = Join-Path $processorDir "Forms"
$formMetaPath = Join-Path $formsDir "$FormName.xml"
$formDir = Join-Path $formsDir $FormName

if (-not (Test-Path $formMetaPath)) {
	Write-Error "Метаданные формы не найдены: $formMetaPath"
	exit 1
}

# --- Удаление файлов ---

if (Test-Path $formDir) {
	Remove-Item -Path $formDir -Recurse -Force
	Write-Host "[OK] Удален каталог: $formDir"
}

Remove-Item -Path $formMetaPath -Force
Write-Host "[OK] Удален файл: $formMetaPath"

# --- Модификация корневого XML ---

$rootXmlFull = Resolve-Path $rootXmlPath
$xmlDoc = New-Object System.Xml.XmlDocument
$xmlDoc.PreserveWhitespace = $true
$xmlDoc.Load($rootXmlFull.Path)

$nsMgr = New-Object System.Xml.XmlNamespaceManager($xmlDoc.NameTable)
$nsMgr.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")

# Удалить <Form>FormName</Form> из ChildObjects
$formNodes = $xmlDoc.SelectNodes("//md:ChildObjects/md:Form", $nsMgr)
foreach ($node in $formNodes) {
	if ($node.InnerText -eq $FormName) {
		$parent = $node.ParentNode
		# Удалить предшествующий whitespace
		$prev = $node.PreviousSibling
		if ($prev -and $prev.NodeType -eq [System.Xml.XmlNodeType]::Whitespace) {
			$parent.RemoveChild($prev) | Out-Null
		}
		$parent.RemoveChild($node) | Out-Null
		# Опустевший контейнер платформа пишет одиночным тегом, а не парой. Внутри
		# остается перевод строки с отступом - его тоже убираем, иначе выйдет пара
		# с пробелом.
		$onlyBlank = $true
		foreach ($rest in @($parent.ChildNodes)) {
			if ($rest.NodeType -ne [System.Xml.XmlNodeType]::Whitespace -and
				$rest.NodeType -ne [System.Xml.XmlNodeType]::SignificantWhitespace) { $onlyBlank = $false }
		}
		if ($onlyBlank) {
			foreach ($rest in @($parent.ChildNodes)) { $parent.RemoveChild($rest) | Out-Null }
			$parent.IsEmpty = $true
		}
		break
	}
}

# Ссылку на удаленную форму несет любое свойство Default*Form и Auxiliary*Form -
# одного DefaultForm мало: у справочника форма объекта лежит в DefaultObjectForm.
foreach ($prop in $xmlDoc.SelectNodes("//*")) {
	if ($prop.NodeType -ne 'Element') { continue }
	if (-not ($prop.LocalName.StartsWith('Default') -or $prop.LocalName.StartsWith('Auxiliary'))) { continue }
	if (-not $prop.LocalName.EndsWith('Form')) { continue }
	if ($prop.InnerText -match "Form\.$FormName$") {
		$prop.InnerText = ""
		$prop.IsEmpty = $true
	}
}

# Сохранить с BOM
$encBom = New-Object System.Text.UTF8Encoding($true)
$settings = New-Object System.Xml.XmlWriterSettings
$settings.Encoding = $encBom
$settings.Indent = $false

$stream = New-Object System.IO.FileStream($rootXmlFull.Path, [System.IO.FileMode]::Create)
$writer = [System.Xml.XmlWriter]::Create($stream, $settings)
$xmlDoc.Save($writer)
$writer.Close()
$stream.Close()
# Пустой элемент: XmlWriter отдает `<a />`, Конфигуратор пишет `<a/>`. Внутри
# CDATA/комментария или значения атрибута ` />` может быть содержимым,
# поэтому они идут первыми ветками альтернации и возвращаются как есть.
$tightPath = $rootXmlFull.Path
$tightText = [System.IO.File]::ReadAllText($tightPath, [System.Text.Encoding]::UTF8)
# Платформа пишет UTF-8 заглавными, а XmlDocument.Save - строчными: без этого
# навык менял шапку чужого файла и давал лишнее расхождение со сверкой.
$tightText = $tightText.Replace('encoding="utf-8"', 'encoding="UTF-8"')
$tightText = [regex]::Replace($tightText, '(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|<([A-Za-z0-9_:.\-]+)((?:\s+[A-Za-z0-9_:.\-]+="[^"]*")*)\s+/>', { param($m) if ($m.Groups[1].Success) { '<' + $m.Groups[1].Value + $m.Groups[2].Value + '/>' } else { $m.Value } })
[System.IO.File]::WriteAllText($tightPath, $tightText, (New-Object System.Text.UTF8Encoding($true)))

Write-Host "[OK] Форма $FormName удалена из $rootXmlPath"
