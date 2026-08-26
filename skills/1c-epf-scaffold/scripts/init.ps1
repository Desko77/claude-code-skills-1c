# epf-init v1.0 — Init 1C external data processor scaffold
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$Name,

	[string]$Synonym = $Name,

	[string]$SrcDir = "src"
,

	[string]$FormatVersion = "2.17"
)

$ErrorActionPreference = "Stop"

# --- Версия формата выгрузки ---
# Проверенный диапазон замерен на платформе; вне его навык предупреждает, но работу не
# останавливает: формат мог уйти вперед, а опечатка в значении - другое дело.
$formatVerifiedMin = "2.17"
$formatVerifiedMax = "2.21"

if ($FormatVersion -notmatch "^\d+\.\d+$") {
	[Console]::Error.WriteLine("Malformed -FormatVersion '$FormatVersion': expected a number like 2.21")
	exit 1
}
# Версии формата сравниваются по составным частям, а не как десятичная дробь:
# 2.9 старее, чем 2.21, хотя как число больше.
function Get-FormatVersionRank {
	param([string]$Version)
	if ($Version -match '^(\d+)\.(\d+)$') { return [int]$Matches[1] * 100 + [int]$Matches[2] }
	return 0
}

$formatRank = Get-FormatVersionRank $FormatVersion
if ($formatRank -lt (Get-FormatVersionRank $formatVerifiedMin) -or $formatRank -gt (Get-FormatVersionRank $formatVerifiedMax)) {
	[Console]::Error.WriteLine("[WARN] Format version '$FormatVersion' is outside the tested range $formatVerifiedMin-$formatVerifiedMax")
}

# Палитра появляется в шапке с формата 2.21 (8.5) и встает между lf и style.
$paletteNs = ""
if ($formatRank -ge 221) {
	$paletteNs = ' xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"'
}


$uuid1 = [guid]::NewGuid().ToString()
$uuid2 = [guid]::NewGuid().ToString()
$uuid3 = [guid]::NewGuid().ToString()
$uuid4 = [guid]::NewGuid().ToString()

$xml = @"
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"$paletteNs xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="$FormatVersion">
	<ExternalDataProcessor uuid="$uuid1">
		<InternalInfo>
			<xr:ContainedObject>
				<xr:ClassId>c3831ec8-d8d5-4f93-8a22-f9bfae07327f</xr:ClassId>
				<xr:ObjectId>$uuid2</xr:ObjectId>
			</xr:ContainedObject>
			<xr:GeneratedType name="ExternalDataProcessorObject.$Name" category="Object">
				<xr:TypeId>$uuid3</xr:TypeId>
				<xr:ValueId>$uuid4</xr:ValueId>
			</xr:GeneratedType>
		</InternalInfo>
		<Properties>
			<Name>$Name</Name>
			<Synonym>
				<v8:item>
					<v8:lang>ru</v8:lang>
					<v8:content>$Synonym</v8:content>
				</v8:item>
			</Synonym>
			<Comment/>
			<DefaultForm/>
			<AuxiliaryForm/>
		</Properties>
		<ChildObjects/>
	</ExternalDataProcessor>
</MetaDataObject>
"@

$rootFile = Join-Path $SrcDir "$Name.xml"
$processorDir = Join-Path $SrcDir $Name

if (Test-Path $rootFile) {
	Write-Error "Файл уже существует: $rootFile"
	exit 1
}

if (-not (Test-Path $SrcDir)) {
	New-Item -ItemType Directory -Path $SrcDir -Force | Out-Null
}
$extDir = Join-Path $processorDir "Ext"
New-Item -ItemType Directory -Path $extDir -Force | Out-Null

$enc = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Resolve-Path $SrcDir | Join-Path -ChildPath "$Name.xml"), $xml, $enc)

# --- Модуль объекта ---

$moduleBsl = @"
#Область ОписаниеПеременных

#КонецОбласти

#Область ПрограммныйИнтерфейс

#КонецОбласти

#Область СлужебныеПроцедурыИФункции

#КонецОбласти
"@

$modulePath = Join-Path $extDir "ObjectModule.bsl"
[System.IO.File]::WriteAllText($modulePath, $moduleBsl, $enc)

Write-Host "[OK] Создана обработка: $rootFile"
Write-Host "     Каталог: $processorDir"
Write-Host "     Модуль:  $modulePath"
