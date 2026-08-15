# cf-init v1.2 — Create empty 1C configuration scaffold
# Source: https://github.com/Desko77/claude-code-skills-1c
param(
	[Parameter(Mandatory)]
	[string]$Name,
	[string]$Synonym = $Name,
	[string]$OutputDir = "src",
	[string]$Version,
	[string]$Vendor,
	[string]$CompatibilityMode = "Version8_3_24",
	[ValidateSet("2.17", "2.18", "2.20", "2.21")]
	[string]$FormatVersion = "2.17"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- XML text escaping: only the three characters that break parsing ---
# Quotes and apostrophes stay as typed: they are legal inside element content,
# and 1C writes them unescaped in its own dumps.
function ConvertTo-XmlText([string]$Text) {
	if ([string]::IsNullOrEmpty($Text)) { return "" }
	return $Text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;")
}

# --- <Tag>value</Tag> or <Tag/> when the value is empty ---
function Format-PropertyLine([string]$Tag, [string]$Value) {
	if ([string]::IsNullOrEmpty($Value)) { return "`t`t`t<$Tag/>" }
	return "`t`t`t<$Tag>$(ConvertTo-XmlText $Value)</$Tag>"
}

# --- Format capabilities ---
$formatNumber = [double]::Parse($FormatVersion, [System.Globalization.CultureInfo]::InvariantCulture)
# TextToSpeech mobile functionality appeared in 8.3.25 (format 2.18).
# On 2.17 the tag makes the platform reject the dump with an XDTO error.
$useTextToSpeech = $formatNumber -ge 2.18
# Format 2.21 (8.5) brings the palette namespace and the reworked main window properties.
$useVersion85Interface = $formatNumber -ge 2.21

if ($CompatibilityMode -eq "DontUse") {
	[Console]::Error.WriteLine("Warning: CompatibilityMode 'DontUse' is not recommended - the configuration loses platform features of 8.3 and cannot be opened by older releases either. Use Version8_3_XX unless the legacy mode is a deliberate choice.")
}

# --- Resolve output dir ---
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
	$OutputDir = Join-Path (Get-Location).Path $OutputDir
}

# --- Check existing ---
$cfgFile = Join-Path $OutputDir "Configuration.xml"
if (Test-Path $cfgFile) {
	Write-Error "Configuration.xml already exists: $cfgFile"
	exit 1
}

# --- Generate UUIDs ---
$uuidCfg  = [guid]::NewGuid().ToString()
$uuidLang = [guid]::NewGuid().ToString()
# Seven interface objects: they are listed in InternalInfo of Configuration.xml
# and referenced back from Ext/ClientApplicationInterface.xml.
$panelIds = @(1..7 | ForEach-Object { [guid]::NewGuid().ToString() })

# --- Root element with namespaces ---
$namespaces = [System.Collections.Generic.List[string]]::new()
$namespaces.Add('xmlns="http://v8.1c.ru/8.3/MDClasses"')
$namespaces.Add('xmlns:app="http://v8.1c.ru/8.2/managed-application/core"')
$namespaces.Add('xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config"')
$namespaces.Add('xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi"')
$namespaces.Add('xmlns:ent="http://v8.1c.ru/8.1/data/enterprise"')
$namespaces.Add('xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"')
if ($useVersion85Interface) {
	$namespaces.Add('xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"')
}
$namespaces.Add('xmlns:style="http://v8.1c.ru/8.1/data/ui/style"')
$namespaces.Add('xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system"')
$namespaces.Add('xmlns:v8="http://v8.1c.ru/8.1/data/core"')
$namespaces.Add('xmlns:v8ui="http://v8.1c.ru/8.1/data/ui"')
$namespaces.Add('xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web"')
$namespaces.Add('xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows"')
$namespaces.Add('xmlns:xen="http://v8.1c.ru/8.3/xcf/enums"')
$namespaces.Add('xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef"')
$namespaces.Add('xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"')
$namespaces.Add('xmlns:xs="http://www.w3.org/2001/XMLSchema"')
$namespaces.Add('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
$rootOpen = "<MetaDataObject $($namespaces -join ' ') version=`"$FormatVersion`">"

# --- Mobile application functionalities ---
$mobileFuncs = @(
	@("Biometrics","true"), @("Location","false"), @("BackgroundLocation","false"),
	@("BluetoothPrinters","false"), @("WiFiPrinters","false"), @("Contacts","false"),
	@("Calendars","false"), @("PushNotifications","false"), @("LocalNotifications","false"),
	@("InAppPurchases","false"), @("PersonalComputerFileExchange","false"), @("Ads","false"),
	@("NumberDialing","false"), @("CallProcessing","false"), @("CallLog","false"),
	@("AutoSendSMS","false"), @("ReceiveSMS","false"), @("SMSLog","false"),
	@("Camera","false"), @("Microphone","false"), @("MusicLibrary","false"),
	@("PictureAndVideoLibraries","false"), @("AudioPlaybackAndVibration","false"),
	@("BackgroundAudioPlaybackAndVibration","false"), @("InstallPackages","false"),
	@("OSBackup","true"), @("ApplicationUsageStatistics","false"),
	@("BarcodeScanning","false"), @("BackgroundAudioRecording","false"),
	@("AllFilesAccess","false"), @("Videoconferences","false"), @("NFC","false"),
	@("DocumentScanning","false"), @("SpeechToText","false"), @("Geofences","false"),
	@("IncomingShareRequests","false"), @("AllIncomingShareRequestsTypesProcessing","false")
)
if ($useTextToSpeech) {
	$mobileFuncs += ,@("TextToSpeech","false")
}

# --- Class identifiers of the seven contained interface objects ---
$containedClassIds = @(
	"9cd510cd-abfc-11d4-9434-004095e12fc7",
	"9fcd25a0-4822-11d4-9414-008048da11f9",
	"e3687481-0a87-462c-a166-9f34594f9bba",
	"9de14907-ec23-4a07-96f0-85521cb6b53b",
	"51f2d5d8-ea4d-4064-8892-82951750031e",
	"e68182ea-4237-4383-967f-90c1e3370bc7",
	"fb282519-d103-4dd3-bc12-cb271d631dfc"
)

# --- Configuration.xml ---
$cfg = [System.Collections.Generic.List[string]]::new()
$cfg.Add('<?xml version="1.0" encoding="UTF-8"?>')
$cfg.Add($rootOpen)
$cfg.Add("`t<Configuration uuid=`"$uuidCfg`">")
$cfg.Add("`t`t<InternalInfo>")
for ($i = 0; $i -lt $containedClassIds.Count; $i++) {
	$cfg.Add("`t`t`t<xr:ContainedObject>")
	$cfg.Add("`t`t`t`t<xr:ClassId>$($containedClassIds[$i])</xr:ClassId>")
	$cfg.Add("`t`t`t`t<xr:ObjectId>$($panelIds[$i])</xr:ObjectId>")
	$cfg.Add("`t`t`t</xr:ContainedObject>")
}
$cfg.Add("`t`t</InternalInfo>")
$cfg.Add("`t`t<Properties>")
$cfg.Add((Format-PropertyLine "Name" $Name))
if ([string]::IsNullOrEmpty($Synonym)) {
	$cfg.Add("`t`t`t<Synonym/>")
} else {
	$cfg.Add("`t`t`t<Synonym>")
	$cfg.Add("`t`t`t`t<v8:item>")
	$cfg.Add("`t`t`t`t`t<v8:lang>ru</v8:lang>")
	$cfg.Add("`t`t`t`t`t<v8:content>$(ConvertTo-XmlText $Synonym)</v8:content>")
	$cfg.Add("`t`t`t`t</v8:item>")
	$cfg.Add("`t`t`t</Synonym>")
}
$cfg.Add("`t`t`t<Comment/>")
$cfg.Add("`t`t`t<NamePrefix/>")
$cfg.Add("`t`t`t<ConfigurationExtensionCompatibilityMode>$CompatibilityMode</ConfigurationExtensionCompatibilityMode>")
$cfg.Add("`t`t`t<DefaultRunMode>ManagedApplication</DefaultRunMode>")
$cfg.Add("`t`t`t<UsePurposes>")
$cfg.Add("`t`t`t`t<v8:Value xsi:type=`"app:ApplicationUsePurpose`">PlatformApplication</v8:Value>")
$cfg.Add("`t`t`t</UsePurposes>")
$cfg.Add("`t`t`t<ScriptVariant>Russian</ScriptVariant>")
$cfg.Add("`t`t`t<DefaultRoles/>")
$cfg.Add((Format-PropertyLine "Vendor" $Vendor))
$cfg.Add((Format-PropertyLine "Version" $Version))
$cfg.Add("`t`t`t<UpdateCatalogAddress/>")
$cfg.Add("`t`t`t<IncludeHelpInContents>false</IncludeHelpInContents>")
$cfg.Add("`t`t`t<UseManagedFormInOrdinaryApplication>false</UseManagedFormInOrdinaryApplication>")
$cfg.Add("`t`t`t<UseOrdinaryFormInManagedApplication>false</UseOrdinaryFormInManagedApplication>")
$cfg.Add("`t`t`t<AdditionalFullTextSearchDictionaries/>")
$cfg.Add("`t`t`t<CommonSettingsStorage/>")
$cfg.Add("`t`t`t<ReportsUserSettingsStorage/>")
$cfg.Add("`t`t`t<ReportsVariantsStorage/>")
$cfg.Add("`t`t`t<FormDataSettingsStorage/>")
$cfg.Add("`t`t`t<DynamicListsUserSettingsStorage/>")
$cfg.Add("`t`t`t<URLExternalDataStorage/>")
$cfg.Add("`t`t`t<Content/>")
$cfg.Add("`t`t`t<DefaultReportForm/>")
$cfg.Add("`t`t`t<DefaultReportVariantForm/>")
$cfg.Add("`t`t`t<DefaultReportSettingsForm/>")
$cfg.Add("`t`t`t<DefaultReportAppearanceTemplate/>")
$cfg.Add("`t`t`t<DefaultDynamicListSettingsForm/>")
$cfg.Add("`t`t`t<DefaultSearchForm/>")
$cfg.Add("`t`t`t<DefaultDataHistoryChangeHistoryForm/>")
$cfg.Add("`t`t`t<DefaultDataHistoryVersionDataForm/>")
$cfg.Add("`t`t`t<DefaultDataHistoryVersionDifferencesForm/>")
$cfg.Add("`t`t`t<DefaultCollaborationSystemUsersChoiceForm/>")
if ($useVersion85Interface) {
	$cfg.Add("`t`t`t<AuxiliaryReportForm/>")
	$cfg.Add("`t`t`t<AuxiliaryReportVariantForm/>")
	$cfg.Add("`t`t`t<AuxiliaryReportSettingsForm/>")
	$cfg.Add("`t`t`t<AuxiliaryDynamicListSettingsForm/>")
	$cfg.Add("`t`t`t<AuxiliaryDataHistoryChangeHistoryForm/>")
	$cfg.Add("`t`t`t<AuxiliaryDataHistoryVersionDataForm/>")
	$cfg.Add("`t`t`t<AuxiliaryDataHistoryVersionDifferencesForm/>")
	$cfg.Add("`t`t`t<AuxiliaryCollaborationSystemUsersChoiceForm/>")
}
$cfg.Add("`t`t`t<RequiredMobileApplicationPermissions/>")
$cfg.Add("`t`t`t<UsedMobileApplicationFunctionalities>")
foreach ($mf in $mobileFuncs) {
	$cfg.Add("`t`t`t`t<app:functionality>")
	$cfg.Add("`t`t`t`t`t<app:functionality>$($mf[0])</app:functionality>")
	$cfg.Add("`t`t`t`t`t<app:use>$($mf[1])</app:use>")
	$cfg.Add("`t`t`t`t</app:functionality>")
}
$cfg.Add("`t`t`t</UsedMobileApplicationFunctionalities>")
$cfg.Add("`t`t`t<StandaloneConfigurationRestrictionRoles/>")
$cfg.Add("`t`t`t<MobileApplicationURLs/>")
$cfg.Add("`t`t`t<AllowedIncomingShareRequestTypes/>")
if ($useVersion85Interface) {
	$cfg.Add("`t`t`t<MainClientApplicationWindowInterfaceVariant>NavigationLeft</MainClientApplicationWindowInterfaceVariant>")
	$cfg.Add("`t`t`t<ClientApplicationTheme>Auto</ClientApplicationTheme>")
}
$cfg.Add("`t`t`t<MainClientApplicationWindowMode>Normal</MainClientApplicationWindowMode>")
if ($useVersion85Interface) {
	$cfg.Add("`t`t`t<ClientApplicationWindowsOpenVariant>OpenDataInDialogs</ClientApplicationWindowsOpenVariant>")
}
$cfg.Add("`t`t`t<DefaultInterface/>")
if ($useVersion85Interface) {
	$cfg.Add("`t`t`t<Caption/>")
	$cfg.Add("`t`t`t<ShortCaption/>")
}
$cfg.Add("`t`t`t<DefaultStyle/>")
$cfg.Add("`t`t`t<DefaultLanguage>Language.Русский</DefaultLanguage>")
$cfg.Add("`t`t`t<BriefInformation/>")
$cfg.Add("`t`t`t<DetailedInformation/>")
$cfg.Add("`t`t`t<Copyright/>")
$cfg.Add("`t`t`t<VendorInformationAddress/>")
$cfg.Add("`t`t`t<ConfigurationInformationAddress/>")
$cfg.Add("`t`t`t<DataLockControlMode>Managed</DataLockControlMode>")
$cfg.Add("`t`t`t<ObjectAutonumerationMode>NotAutoFree</ObjectAutonumerationMode>")
$cfg.Add("`t`t`t<ModalityUseMode>DontUse</ModalityUseMode>")
$cfg.Add("`t`t`t<SynchronousPlatformExtensionAndAddInCallUseMode>DontUse</SynchronousPlatformExtensionAndAddInCallUseMode>")
$cfg.Add("`t`t`t<InterfaceCompatibilityMode>TaxiEnableVersion8_2</InterfaceCompatibilityMode>")
if ($useVersion85Interface) {
	$cfg.Add("`t`t`t<Version85InterfaceMigrationMode>DontUse</Version85InterfaceMigrationMode>")
}
$cfg.Add("`t`t`t<DatabaseTablespacesUseMode>DontUse</DatabaseTablespacesUseMode>")
$cfg.Add("`t`t`t<CompatibilityMode>$CompatibilityMode</CompatibilityMode>")
$cfg.Add("`t`t`t<DefaultConstantsForm/>")
$cfg.Add("`t`t</Properties>")
$cfg.Add("`t`t<ChildObjects>")
$cfg.Add("`t`t`t<Language>Русский</Language>")
$cfg.Add("`t`t</ChildObjects>")
$cfg.Add("`t</Configuration>")
$cfg.Add("</MetaDataObject>")
$cfgXml = $cfg -join "`r`n"

# --- Languages/Русский.xml ---
$lang = [System.Collections.Generic.List[string]]::new()
$lang.Add('<?xml version="1.0" encoding="UTF-8"?>')
$lang.Add($rootOpen)
$lang.Add("`t<Language uuid=`"$uuidLang`">")
$lang.Add("`t`t<Properties>")
$lang.Add("`t`t`t<Name>Русский</Name>")
$lang.Add("`t`t`t<Synonym>")
$lang.Add("`t`t`t`t<v8:item>")
$lang.Add("`t`t`t`t`t<v8:lang>ru</v8:lang>")
$lang.Add("`t`t`t`t`t<v8:content>Русский</v8:content>")
$lang.Add("`t`t`t`t</v8:item>")
$lang.Add("`t`t`t</Synonym>")
$lang.Add("`t`t`t<Comment/>")
$lang.Add("`t`t`t<LanguageCode>ru</LanguageCode>")
$lang.Add("`t`t</Properties>")
$lang.Add("`t</Language>")
$lang.Add("</MetaDataObject>")
$langXml = $lang -join "`r`n"

# --- Ext/ClientApplicationInterface.xml ---
# Command interface layout: the top and left panels reference their definitions
# by uuid, the remaining panelDef entries stay empty until the interface is edited.
$iface = [System.Collections.Generic.List[string]]::new()
$iface.Add('<?xml version="1.0" encoding="UTF-8"?>')
$iface.Add('<ClientApplicationInterface xmlns="http://v8.1c.ru/8.2/managed-application/core" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="InterfaceLayouter">')
$iface.Add("`t<top>")
$iface.Add("`t`t<panel id=`"$($panelIds[0])`">")
$iface.Add("`t`t`t<uuid>$($panelIds[1])</uuid>")
$iface.Add("`t`t</panel>")
$iface.Add("`t</top>")
$iface.Add("`t<left>")
$iface.Add("`t`t<panel id=`"$($panelIds[2])`">")
$iface.Add("`t`t`t<uuid>$($panelIds[3])</uuid>")
$iface.Add("`t`t</panel>")
$iface.Add("`t</left>")
$iface.Add("`t<panelDef id=`"$($panelIds[3])`"/>")
$iface.Add("`t<panelDef id=`"$($panelIds[4])`"/>")
$iface.Add("`t<panelDef id=`"$($panelIds[5])`"/>")
$iface.Add("`t<panelDef id=`"$($panelIds[1])`"/>")
$iface.Add("`t<panelDef id=`"$($panelIds[6])`"/>")
$iface.Add("</ClientApplicationInterface>")
$ifaceXml = $iface -join "`r`n"

# --- Create directories ---
$langDir  = Join-Path $OutputDir "Languages"
$extDir   = Join-Path $OutputDir "Ext"
foreach ($dir in @($OutputDir, $langDir, $extDir)) {
	if (-not (Test-Path $dir)) {
		New-Item -ItemType Directory -Path $dir -Force | Out-Null
	}
}

# --- Write files with UTF-8 BOM ---
$enc = New-Object System.Text.UTF8Encoding($true)
$langFile  = Join-Path $langDir "Русский.xml"
$ifaceFile = Join-Path $extDir "ClientApplicationInterface.xml"

[System.IO.File]::WriteAllText($cfgFile, $cfgXml, $enc)
[System.IO.File]::WriteAllText($langFile, $langXml, $enc)
[System.IO.File]::WriteAllText($ifaceFile, $ifaceXml, $enc)

# --- Output ---
Write-Host "[OK] Создана конфигурация: $Name"
Write-Host "     Каталог:            $OutputDir"
Write-Host "     Версия формата:     $FormatVersion"
Write-Host "     Configuration.xml:  $cfgFile"
Write-Host "     Languages:          $langFile"
Write-Host "     Интерфейс:          $ifaceFile"
