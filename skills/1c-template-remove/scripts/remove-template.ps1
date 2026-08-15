# template-remove v1.1 — Remove template from 1C object
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[Alias("ProcessorName")]
	[string]$ObjectName,

	[Parameter(Mandatory)]
	[string]$TemplateName,

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
$templatesDir = Join-Path $processorDir "Templates"
$templateMetaPath = Join-Path $templatesDir "$TemplateName.xml"
$templateDir = Join-Path $templatesDir $TemplateName

if (-not (Test-Path $templateMetaPath)) {
	Write-Error "Метаданные макета не найдены: $templateMetaPath"
	exit 1
}

# --- Удаление файлов ---

if (Test-Path $templateDir) {
	Remove-Item -Path $templateDir -Recurse -Force
	Write-Host "[OK] Удалён каталог: $templateDir"
}

Remove-Item -Path $templateMetaPath -Force
Write-Host "[OK] Удалён файл: $templateMetaPath"

# --- Модификация корневого XML ---

$rootXmlFull = Resolve-Path $rootXmlPath
$xmlDoc = New-Object System.Xml.XmlDocument
$xmlDoc.PreserveWhitespace = $true
$xmlDoc.Load($rootXmlFull.Path)

$nsMgr = New-Object System.Xml.XmlNamespaceManager($xmlDoc.NameTable)
$nsMgr.AddNamespace("md", "http://v8.1c.ru/8.3/MDClasses")

# Удалить <Template>TemplateName</Template> из ChildObjects
$templateNodes = $xmlDoc.SelectNodes("//md:ChildObjects/md:Template", $nsMgr)
foreach ($node in $templateNodes) {
	if ($node.InnerText -eq $TemplateName) {
		$parent = $node.ParentNode
		# Удалить предшествующий whitespace
		$prev = $node.PreviousSibling
		if ($prev -and $prev.NodeType -eq [System.Xml.XmlNodeType]::Whitespace) {
			$parent.RemoveChild($prev) | Out-Null
		}
		$parent.RemoveChild($node) | Out-Null
		break
	}
}

# Очистить MainDataCompositionSchema если указывала на этот макет
$mainDCS = $xmlDoc.SelectSingleNode("//md:MainDataCompositionSchema", $nsMgr)
if ($mainDCS -and $mainDCS.InnerText -match "Template\.$([regex]::Escape($TemplateName))$") {
	$mainDCS.InnerText = ""
	Write-Host "[OK] Очищён MainDataCompositionSchema"
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
$tightText = [regex]::Replace($tightText, '(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|<([A-Za-z0-9_:.\-]+)((?:\s+[A-Za-z0-9_:.\-]+="[^"]*")*)\s+/>', { param($m) if ($m.Groups[1].Success) { '<' + $m.Groups[1].Value + $m.Groups[2].Value + '/>' } else { $m.Value } })
[System.IO.File]::WriteAllText($tightPath, $tightText, (New-Object System.Text.UTF8Encoding($true)))

Write-Host "[OK] Макет $TemplateName удалён из $rootXmlPath"
