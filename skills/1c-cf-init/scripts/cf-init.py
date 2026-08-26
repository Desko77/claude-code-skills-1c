#!/usr/bin/env python3
# cf-init v1.2 — Create empty 1C configuration scaffold
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Generates minimal XML source files for a 1C configuration."""
import sys, os, re, argparse, uuid

# Проверенный диапазон версий формата. Эталон - лестница версий в docs/1c-configuration-spec.md
# (§7.1); согласованность границ стережет tests/skills/check-format-versions.mjs. Сравнение
# числовое, поэтому промежуточная версия ведет себя предсказуемо.
FORMAT_VERIFIED_MIN = "2.17"
FORMAT_VERIFIED_MAX = "2.21"


def format_version_rank(version):
    """Версии сравниваются по составным частям: 2.9 старее, чем 2.21, хотя как число больше."""
    m = re.match(r"^(\d+)\.(\d+)$", str(version or ""))
    return int(m.group(1)) * 100 + int(m.group(2)) if m else 0


def _format_version_rank(version):
    m = re.match(r'^(\d+)\.(\d+)$', version or '')
    return int(m.group(1)) * 100 + int(m.group(2)) if m else 0


def format_version_known(version):
    rank = _format_version_rank(version)
    if rank == 0:
        return False
    return _format_version_rank(FORMAT_VERIFIED_MIN) <= rank <= _format_version_rank(FORMAT_VERIFIED_MAX)




# Class identifiers of the seven contained interface objects.
CLASS_IDS = (
    "9cd510cd-abfc-11d4-9434-004095e12fc7",
    "9fcd25a0-4822-11d4-9414-008048da11f9",
    "e3687481-0a87-462c-a166-9f34594f9bba",
    "9de14907-ec23-4a07-96f0-85521cb6b53b",
    "51f2d5d8-ea4d-4064-8892-82951750031e",
    "e68182ea-4237-4383-967f-90c1e3370bc7",
    "fb282519-d103-4dd3-bc12-cb271d631dfc",
)

MOBILE_FUNCS = [
    ("Biometrics","true"), ("Location","false"), ("BackgroundLocation","false"),
    ("BluetoothPrinters","false"), ("WiFiPrinters","false"), ("Contacts","false"),
    ("Calendars","false"), ("PushNotifications","false"), ("LocalNotifications","false"),
    ("InAppPurchases","false"), ("PersonalComputerFileExchange","false"), ("Ads","false"),
    ("NumberDialing","false"), ("CallProcessing","false"), ("CallLog","false"),
    ("AutoSendSMS","false"), ("ReceiveSMS","false"), ("SMSLog","false"),
    ("Camera","false"), ("Microphone","false"), ("MusicLibrary","false"),
    ("PictureAndVideoLibraries","false"), ("AudioPlaybackAndVibration","false"),
    ("BackgroundAudioPlaybackAndVibration","false"), ("InstallPackages","false"),
    ("OSBackup","true"), ("ApplicationUsageStatistics","false"),
    ("BarcodeScanning","false"), ("BackgroundAudioRecording","false"),
    ("AllFilesAccess","false"), ("Videoconferences","false"), ("NFC","false"),
    ("DocumentScanning","false"), ("SpeechToText","false"), ("Geofences","false"),
    ("IncomingShareRequests","false"), ("AllIncomingShareRequestsTypesProcessing","false"),
]


def esc_xml(s):
    """Escape only the three characters that break XML parsing.

    Quotes and apostrophes stay as typed: they are legal inside element content,
    and 1C writes them unescaped in its own dumps.
    """
    if not s:
        return ""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def property_line(tag, value):
    """<Tag>value</Tag> or <Tag/> when the value is empty."""
    if not value:
        return f"\t\t\t<{tag}/>"
    return f"\t\t\t<{tag}>{esc_xml(value)}</{tag}>"


def new_uuid():
    return str(uuid.uuid4())


def write_utf8_bom(path, lines):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write("\r\n".join(lines))


def build_root_open(format_version, with_palette):
    ns = [
        'xmlns="http://v8.1c.ru/8.3/MDClasses"',
        'xmlns:app="http://v8.1c.ru/8.2/managed-application/core"',
        'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config"',
        'xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi"',
        'xmlns:ent="http://v8.1c.ru/8.1/data/enterprise"',
        'xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"',
    ]
    if with_palette:
        ns.append('xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"')
    ns += [
        'xmlns:style="http://v8.1c.ru/8.1/data/ui/style"',
        'xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system"',
        'xmlns:v8="http://v8.1c.ru/8.1/data/core"',
        'xmlns:v8ui="http://v8.1c.ru/8.1/data/ui"',
        'xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web"',
        'xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows"',
        'xmlns:xen="http://v8.1c.ru/8.3/xcf/enums"',
        'xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef"',
        'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"',
        'xmlns:xs="http://www.w3.org/2001/XMLSchema"',
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
    ]
    return f'<MetaDataObject {" ".join(ns)} version="{format_version}">'


def build_configuration(name, synonym, vendor, version, compat, root_open,
                        uuid_cfg, contained_ids, mobile_funcs, v85):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', root_open,
           f'\t<Configuration uuid="{uuid_cfg}">', "\t\t<InternalInfo>"]
    for class_id, object_id in zip(CLASS_IDS, contained_ids):
        out += ["\t\t\t<xr:ContainedObject>",
                f"\t\t\t\t<xr:ClassId>{class_id}</xr:ClassId>",
                f"\t\t\t\t<xr:ObjectId>{object_id}</xr:ObjectId>",
                "\t\t\t</xr:ContainedObject>"]
    out += ["\t\t</InternalInfo>", "\t\t<Properties>", property_line("Name", name)]
    if not synonym:
        out.append("\t\t\t<Synonym/>")
    else:
        out += ["\t\t\t<Synonym>", "\t\t\t\t<v8:item>", "\t\t\t\t\t<v8:lang>ru</v8:lang>",
                f"\t\t\t\t\t<v8:content>{esc_xml(synonym)}</v8:content>",
                "\t\t\t\t</v8:item>", "\t\t\t</Synonym>"]
    out += [
        "\t\t\t<Comment/>",
        "\t\t\t<NamePrefix/>",
        f"\t\t\t<ConfigurationExtensionCompatibilityMode>{compat}</ConfigurationExtensionCompatibilityMode>",
        "\t\t\t<DefaultRunMode>ManagedApplication</DefaultRunMode>",
        "\t\t\t<UsePurposes>",
        '\t\t\t\t<v8:Value xsi:type="app:ApplicationUsePurpose">PlatformApplication</v8:Value>',
        "\t\t\t</UsePurposes>",
        "\t\t\t<ScriptVariant>Russian</ScriptVariant>",
        "\t\t\t<DefaultRoles/>",
        property_line("Vendor", vendor),
        property_line("Version", version),
        "\t\t\t<UpdateCatalogAddress/>",
        "\t\t\t<IncludeHelpInContents>false</IncludeHelpInContents>",
        "\t\t\t<UseManagedFormInOrdinaryApplication>false</UseManagedFormInOrdinaryApplication>",
        "\t\t\t<UseOrdinaryFormInManagedApplication>false</UseOrdinaryFormInManagedApplication>",
        "\t\t\t<AdditionalFullTextSearchDictionaries/>",
        "\t\t\t<CommonSettingsStorage/>",
        "\t\t\t<ReportsUserSettingsStorage/>",
        "\t\t\t<ReportsVariantsStorage/>",
        "\t\t\t<FormDataSettingsStorage/>",
        "\t\t\t<DynamicListsUserSettingsStorage/>",
        "\t\t\t<URLExternalDataStorage/>",
        "\t\t\t<Content/>",
        "\t\t\t<DefaultReportForm/>",
        "\t\t\t<DefaultReportVariantForm/>",
        "\t\t\t<DefaultReportSettingsForm/>",
        "\t\t\t<DefaultReportAppearanceTemplate/>",
        "\t\t\t<DefaultDynamicListSettingsForm/>",
        "\t\t\t<DefaultSearchForm/>",
        "\t\t\t<DefaultDataHistoryChangeHistoryForm/>",
        "\t\t\t<DefaultDataHistoryVersionDataForm/>",
        "\t\t\t<DefaultDataHistoryVersionDifferencesForm/>",
        "\t\t\t<DefaultCollaborationSystemUsersChoiceForm/>",
    ]
    if v85:
        out += [
            "\t\t\t<AuxiliaryReportForm/>",
            "\t\t\t<AuxiliaryReportVariantForm/>",
            "\t\t\t<AuxiliaryReportSettingsForm/>",
            "\t\t\t<AuxiliaryDynamicListSettingsForm/>",
            "\t\t\t<AuxiliaryDataHistoryChangeHistoryForm/>",
            "\t\t\t<AuxiliaryDataHistoryVersionDataForm/>",
            "\t\t\t<AuxiliaryDataHistoryVersionDifferencesForm/>",
            "\t\t\t<AuxiliaryCollaborationSystemUsersChoiceForm/>",
        ]
    out += ["\t\t\t<RequiredMobileApplicationPermissions/>",
            "\t\t\t<UsedMobileApplicationFunctionalities>"]
    for func_name, func_use in mobile_funcs:
        out += ["\t\t\t\t<app:functionality>",
                f"\t\t\t\t\t<app:functionality>{func_name}</app:functionality>",
                f"\t\t\t\t\t<app:use>{func_use}</app:use>",
                "\t\t\t\t</app:functionality>"]
    out += ["\t\t\t</UsedMobileApplicationFunctionalities>",
            "\t\t\t<StandaloneConfigurationRestrictionRoles/>",
            "\t\t\t<MobileApplicationURLs/>",
            "\t\t\t<AllowedIncomingShareRequestTypes/>"]
    if v85:
        out += ["\t\t\t<MainClientApplicationWindowInterfaceVariant>NavigationLeft</MainClientApplicationWindowInterfaceVariant>",
                "\t\t\t<ClientApplicationTheme>Auto</ClientApplicationTheme>"]
    out.append("\t\t\t<MainClientApplicationWindowMode>Normal</MainClientApplicationWindowMode>")
    if v85:
        out.append("\t\t\t<ClientApplicationWindowsOpenVariant>OpenDataInDialogs</ClientApplicationWindowsOpenVariant>")
    out.append("\t\t\t<DefaultInterface/>")
    if v85:
        out += ["\t\t\t<Caption/>", "\t\t\t<ShortCaption/>"]
    out += [
        "\t\t\t<DefaultStyle/>",
        "\t\t\t<DefaultLanguage>Language.Русский</DefaultLanguage>",
        "\t\t\t<BriefInformation/>",
        "\t\t\t<DetailedInformation/>",
        "\t\t\t<Copyright/>",
        "\t\t\t<VendorInformationAddress/>",
        "\t\t\t<ConfigurationInformationAddress/>",
        "\t\t\t<DataLockControlMode>Managed</DataLockControlMode>",
        "\t\t\t<ObjectAutonumerationMode>NotAutoFree</ObjectAutonumerationMode>",
        "\t\t\t<ModalityUseMode>DontUse</ModalityUseMode>",
        "\t\t\t<SynchronousPlatformExtensionAndAddInCallUseMode>DontUse</SynchronousPlatformExtensionAndAddInCallUseMode>",
        "\t\t\t<InterfaceCompatibilityMode>TaxiEnableVersion8_2</InterfaceCompatibilityMode>",
    ]
    if v85:
        out.append("\t\t\t<Version85InterfaceMigrationMode>DontUse</Version85InterfaceMigrationMode>")
    out += [
        "\t\t\t<DatabaseTablespacesUseMode>DontUse</DatabaseTablespacesUseMode>",
        f"\t\t\t<CompatibilityMode>{compat}</CompatibilityMode>",
        "\t\t\t<DefaultConstantsForm/>",
        "\t\t</Properties>",
        "\t\t<ChildObjects>",
        "\t\t\t<Language>Русский</Language>",
        "\t\t</ChildObjects>",
        "\t</Configuration>",
        "</MetaDataObject>",
    ]
    return out


def build_language(root_open, uuid_lang):
    return ['<?xml version="1.0" encoding="UTF-8"?>', root_open,
            f'\t<Language uuid="{uuid_lang}">',
            "\t\t<Properties>",
            "\t\t\t<Name>Русский</Name>",
            "\t\t\t<Synonym>",
            "\t\t\t\t<v8:item>",
            "\t\t\t\t\t<v8:lang>ru</v8:lang>",
            "\t\t\t\t\t<v8:content>Русский</v8:content>",
            "\t\t\t\t</v8:item>",
            "\t\t\t</Synonym>",
            "\t\t\t<Comment/>",
            "\t\t\t<LanguageCode>ru</LanguageCode>",
            "\t\t</Properties>",
            "\t</Language>",
            "</MetaDataObject>"]


def build_interface(panel_ids):
    """Command interface layout: the top and left panels reference their
    definitions by uuid, the remaining panelDef entries stay empty until the
    interface is edited."""
    return ['<?xml version="1.0" encoding="UTF-8"?>',
            '<ClientApplicationInterface xmlns="http://v8.1c.ru/8.2/managed-application/core" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="InterfaceLayouter">',
            "\t<top>",
            f'\t\t<panel id="{panel_ids[0]}">',
            f"\t\t\t<uuid>{panel_ids[1]}</uuid>",
            "\t\t</panel>",
            "\t</top>",
            "\t<left>",
            f'\t\t<panel id="{panel_ids[2]}">',
            f"\t\t\t<uuid>{panel_ids[3]}</uuid>",
            "\t\t</panel>",
            "\t</left>",
            f'\t<panelDef id="{panel_ids[3]}"/>',
            f'\t<panelDef id="{panel_ids[4]}"/>',
            f'\t<panelDef id="{panel_ids[5]}"/>',
            f'\t<panelDef id="{panel_ids[1]}"/>',
            f'\t<panelDef id="{panel_ids[6]}"/>',
            "</ClientApplicationInterface>"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description='Create empty 1C configuration scaffold', allow_abbrev=False)
    parser.add_argument('-Name', dest='Name', required=True)
    parser.add_argument('-Synonym', dest='Synonym', default=None)
    parser.add_argument('-OutputDir', dest='OutputDir', default='src')
    parser.add_argument('-Version', dest='Version', default='')
    parser.add_argument('-Vendor', dest='Vendor', default='')
    parser.add_argument('-CompatibilityMode', dest='CompatibilityMode', default='Version8_3_24')
    parser.add_argument('-FormatVersion', dest='FormatVersion', default='2.17')
    args = parser.parse_args()

    name = args.Name
    synonym = args.Synonym if args.Synonym is not None else name
    output_dir = args.OutputDir
    compat = args.CompatibilityMode
    format_version = args.FormatVersion

    # --- Format capabilities ---
    # Версия формата не ограничивается закрытым списком: лестница версий продолжается, и
    # неизвестная версия должна давать предупреждение, а не отказ. Признаки считаются
    # числовым сравнением, поэтому промежуточная версия ведет себя предсказуемо.
    if not re.fullmatch(r'\d+\.\d+', format_version):
        print(f"FormatVersion must look like 2.17, got: {format_version}", file=sys.stderr)
        sys.exit(1)
    if not format_version_known(format_version):
        print(f"Warning: format version '{format_version}' is outside the verified ladder "
              f"({FORMAT_VERIFIED_MIN}-{FORMAT_VERIFIED_MAX}). The header is written as asked and feature flags "
              f"follow the numeric comparison, but the result is not covered by tests.",
              file=sys.stderr)
    format_number = float(format_version)
    # TextToSpeech mobile functionality appeared in 8.3.25 (format 2.18).
    # On 2.17 the tag makes the platform reject the dump with an XDTO error.
    use_text_to_speech = format_number >= 2.18
    # Format 2.21 (8.5) brings the palette namespace and the reworked main window properties.
    v85 = format_version_rank(args.FormatVersion) >= 221

    if compat == "DontUse":
        print("Warning: CompatibilityMode 'DontUse' is not recommended - the configuration "
              "loses platform features of 8.3 and cannot be opened by older releases either. "
              "Use Version8_3_XX unless the legacy mode is a deliberate choice.", file=sys.stderr)

    # --- Resolve output dir ---
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.getcwd(), output_dir)

    # --- Check existing ---
    cfg_file = os.path.join(output_dir, "Configuration.xml")
    if os.path.exists(cfg_file):
        print(f"Configuration.xml already exists: {cfg_file}", file=sys.stderr)
        sys.exit(1)

    # --- Generate UUIDs ---
    uuid_cfg = new_uuid()
    uuid_lang = new_uuid()
    # Семь служебных объектов конфигурации перечислены в InternalInfo, и отдельно семь
    # идентификаторов раскладки командного интерфейса. Наборы РАЗНЫЕ: в выгрузке платформы
    # они не пересекаются, интерфейс связывает panel с panelDef, а не с InternalInfo.
    contained_ids = [new_uuid() for _ in range(7)]
    panel_ids = [new_uuid() for _ in range(7)]

    mobile_funcs = list(MOBILE_FUNCS)
    if use_text_to_speech:
        mobile_funcs.append(("TextToSpeech", "false"))

    root_open = build_root_open(format_version, v85)

    # --- Create directories ---
    lang_dir = os.path.join(output_dir, "Languages")
    ext_dir = os.path.join(output_dir, "Ext")
    for path in (output_dir, lang_dir, ext_dir):
        os.makedirs(path, exist_ok=True)

    lang_file = os.path.join(lang_dir, "Русский.xml")
    iface_file = os.path.join(ext_dir, "ClientApplicationInterface.xml")

    write_utf8_bom(cfg_file, build_configuration(
        name, synonym, args.Vendor, args.Version, compat, root_open,
        uuid_cfg, contained_ids, mobile_funcs, v85))
    write_utf8_bom(lang_file, build_language(root_open, uuid_lang))
    write_utf8_bom(iface_file, build_interface(panel_ids))

    # --- Output ---
    print(f"[OK] Создана конфигурация: {name}")
    print(f"     Каталог:            {output_dir}")
    print(f"     Версия формата:     {format_version}")
    print(f"     Configuration.xml:  {cfg_file}")
    print(f"     Languages:          {lang_file}")
    print(f"     Интерфейс:          {iface_file}")


if __name__ == '__main__':
    main()
