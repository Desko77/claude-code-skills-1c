#!/usr/bin/env python3
# cf-info v1.0 — Compact summary of 1C configuration root
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import os
import sys
from collections import OrderedDict
from lxml import etree

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# --- Argument parsing ---
parser = argparse.ArgumentParser(description="Analyze 1C configuration structure", allow_abbrev=False)
parser.add_argument("-ConfigPath", required=True, help="Path to Configuration.xml or directory")
parser.add_argument("-Mode", choices=["overview", "brief", "full"], default="overview", help="Output mode")
parser.add_argument("-Limit", type=int, default=150, help="Max lines to show")
parser.add_argument("-Offset", type=int, default=0, help="Lines to skip")
parser.add_argument("-OutFile", default="", help="Write output to file")
args = parser.parse_args()

# --- Output helper (collect all, paginate at the end) ---
lines_buf = []

def out(text=""):
    lines_buf.append(text)

# --- Resolve path ---
config_path = args.ConfigPath
if not os.path.isabs(config_path):
    config_path = os.path.join(os.getcwd(), config_path)

# Directory -> find Configuration.xml
if os.path.isdir(config_path):
    candidate = os.path.join(config_path, "Configuration.xml")
    if os.path.isfile(candidate):
        config_path = candidate
    else:
        print(f"[ERROR] No Configuration.xml found in directory: {config_path}", file=sys.stderr)
        sys.exit(1)

if not os.path.isfile(config_path):
    print(f"[ERROR] File not found: {config_path}", file=sys.stderr)
    sys.exit(1)

# --- Load XML ---
tree = etree.parse(config_path, etree.XMLParser(remove_blank_text=False))
xml_root = tree.getroot()
NS = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xs": "http://www.w3.org/2001/XMLSchema",
    "app": "http://v8.1c.ru/8.2/managed-application/core",
}

md_root = xml_root  # root is MetaDataObject itself
if etree.QName(md_root.tag).localname != "MetaDataObject":
    print("[ERROR] Not a valid 1C metadata XML file (no MetaDataObject root)", file=sys.stderr)
    sys.exit(1)

cfg_node = md_root.find("md:Configuration", NS)
if cfg_node is None:
    print("[ERROR] No <Configuration> element found", file=sys.stderr)
    sys.exit(1)

version = md_root.get("version", "")
props_node = cfg_node.find("md:Properties", NS)
child_obj_node = cfg_node.find("md:ChildObjects", NS)

# --- Helpers ---
def get_ml_text(node):
    if node is None:
        return ""
    item = node.find("v8:item/v8:content", NS)
    if item is not None and item.text:
        return item.text
    return ""

def get_prop_text(prop_name):
    n = props_node.find(f"md:{prop_name}", NS)
    if n is not None and n.text:
        return n.text
    return ""

def get_prop_ml(prop_name):
    n = props_node.find(f"md:{prop_name}", NS)
    return get_ml_text(n)

# --- Type name maps (canonical order, 44 types) ---
type_order = [
    "Language", "Subsystem", "StyleItem", "Style",
    "CommonPicture", "SessionParameter", "Role", "CommonTemplate",
    "FilterCriterion", "CommonModule", "CommonAttribute", "ExchangePlan",
    "XDTOPackage", "WebService", "HTTPService", "WSReference",
    "EventSubscription", "ScheduledJob", "SettingsStorage", "FunctionalOption",
    "FunctionalOptionsParameter", "DefinedType", "CommonCommand", "CommandGroup",
    "Constant", "CommonForm", "Catalog", "Document",
    "DocumentNumerator", "Sequence", "DocumentJournal", "Enum",
    "Report", "DataProcessor", "InformationRegister", "AccumulationRegister",
    "ChartOfCharacteristicTypes", "ChartOfAccounts", "AccountingRegister",
    "ChartOfCalculationTypes", "CalculationRegister",
    "BusinessProcess", "Task", "IntegrationService",
]

type_ru_names = {
    "Language": "Языки", "Subsystem": "Подсистемы", "StyleItem": "Элементы стиля", "Style": "Стили",
    "CommonPicture": "Общие картинки", "SessionParameter": "Параметры сеанса", "Role": "Роли",
    "CommonTemplate": "Общие макеты", "FilterCriterion": "Критерии отбора", "CommonModule": "Общие модули",
    "CommonAttribute": "Общие реквизиты", "ExchangePlan": "Планы обмена", "XDTOPackage": "XDTO-пакеты",
    "WebService": "Веб-сервисы", "HTTPService": "HTTP-сервисы", "WSReference": "WS-ссылки",
    "EventSubscription": "Подписки на события", "ScheduledJob": "Регламентные задания",
    "SettingsStorage": "Хранилища настроек", "FunctionalOption": "Функциональные опции",
    "FunctionalOptionsParameter": "Параметры ФО", "DefinedType": "Определяемые типы",
    "CommonCommand": "Общие команды", "CommandGroup": "Группы команд", "Constant": "Константы",
    "CommonForm": "Общие формы", "Catalog": "Справочники", "Document": "Документы",
    "DocumentNumerator": "Нумераторы", "Sequence": "Последовательности", "DocumentJournal": "Журналы документов",
    "Enum": "Перечисления", "Report": "Отчёты", "DataProcessor": "Обработки",
    "InformationRegister": "Регистры сведений", "AccumulationRegister": "Регистры накопления",
    "ChartOfCharacteristicTypes": "ПВХ", "ChartOfAccounts": "Планы счетов",
    "AccountingRegister": "Регистры бухгалтерии", "ChartOfCalculationTypes": "ПВР",
    "CalculationRegister": "Регистры расчёта", "BusinessProcess": "Бизнес-процессы",
    "Task": "Задачи", "IntegrationService": "Сервисы интеграции",
}

# --- Count objects in ChildObjects ---
object_counts = OrderedDict()
total_objects = 0

if child_obj_node is not None:
    for child in child_obj_node:
        if not isinstance(child.tag, str):
            continue  # skip comments/PIs
        type_name = etree.QName(child.tag).localname
        if type_name not in object_counts:
            object_counts[type_name] = 0
        object_counts[type_name] += 1
        total_objects += 1

# --- Read key properties ---
cfg_name = get_prop_text("Name")
cfg_synonym = get_prop_ml("Synonym")
cfg_version = get_prop_text("Version")
cfg_vendor = get_prop_text("Vendor")
cfg_compat = get_prop_text("CompatibilityMode")
cfg_ext_compat = get_prop_text("ConfigurationExtensionCompatibilityMode")
cfg_default_run = get_prop_text("DefaultRunMode")
cfg_script = get_prop_text("ScriptVariant")
cfg_default_lang = get_prop_text("DefaultLanguage")
cfg_data_lock = get_prop_text("DataLockControlMode")
dash = "\u2014"
cfg_modality = get_prop_text("ModalityUseMode")
cfg_intf_compat = get_prop_text("InterfaceCompatibilityMode")
cfg_auto_num = get_prop_text("ObjectAutonumerationMode")
cfg_sync_calls = get_prop_text("SynchronousPlatformExtensionAndAddInCallUseMode")
cfg_db_spaces = get_prop_text("DatabaseTablespacesUseMode")
cfg_window_mode = get_prop_text("MainClientApplicationWindowMode")

# --- BRIEF mode ---
if args.Mode == "brief":
    syn_part = f' {dash} "{cfg_synonym}"' if cfg_synonym else ""
    ver_part = f" v{cfg_version}" if cfg_version else ""
    compat_part = f" | {cfg_compat}" if cfg_compat else ""
    out(f"Конфигурация: {cfg_name}{syn_part}{ver_part} | {total_objects} объектов{compat_part}")

# --- OVERVIEW mode ---
if args.Mode == "overview":
    syn_part = f' {dash} "{cfg_synonym}"' if cfg_synonym else ""
    ver_part = f" v{cfg_version}" if cfg_version else ""
    out(f"=== Конфигурация: {cfg_name}{syn_part}{ver_part} ===")
    out()

    # Key properties
    out(f"Формат:         {version}")
    if cfg_vendor:
        out(f"Поставщик:      {cfg_vendor}")
    if cfg_version:
        out(f"Версия:         {cfg_version}")
    out(f"Совместимость:  {cfg_compat}")
    out(f"Режим запуска:  {cfg_default_run}")
    out(f"Язык скриптов:  {cfg_script}")
    out(f"Язык:           {cfg_default_lang}")
    out(f"Блокировки:     {cfg_data_lock}")
    out(f"Модальность:    {cfg_modality}")
    out(f"Интерфейс:      {cfg_intf_compat}")
    out()

    # Object counts table
    out(f"--- Состав ({total_objects} объектов) ---")
    out()
    max_type_len = 0
    for type_name in type_order:
        if type_name in object_counts:
            ru_name = type_ru_names.get(type_name, type_name)
            if len(ru_name) > max_type_len:
                max_type_len = len(ru_name)
    if max_type_len < 10:
        max_type_len = 10

    for type_name in type_order:
        if type_name in object_counts:
            count = object_counts[type_name]
            ru_name = type_ru_names.get(type_name, type_name)
            padded = ru_name.ljust(max_type_len)
            out(f"  {padded}  {count}")

# --- FULL mode ---
if args.Mode == "full":
    syn_part = f' {dash} "{cfg_synonym}"' if cfg_synonym else ""
    ver_part = f" v{cfg_version}" if cfg_version else ""
    out(f"=== Конфигурация: {cfg_name}{syn_part}{ver_part} ===")
    out()

    # --- Section: Identification ---
    out("--- Идентификация ---")
    out(f"UUID:           {cfg_node.get('uuid', '')}")
    out(f"Имя:            {cfg_name}")
    if cfg_synonym:
        out(f"Синоним:        {cfg_synonym}")
    cfg_comment = get_prop_text("Comment")
    if cfg_comment:
        out(f"Комментарий:    {cfg_comment}")
    cfg_prefix = get_prop_text("NamePrefix")
    if cfg_prefix:
        out(f"Префикс:        {cfg_prefix}")
    if cfg_vendor:
        out(f"Поставщик:      {cfg_vendor}")
    if cfg_version:
        out(f"Версия:         {cfg_version}")
    cfg_update_addr = get_prop_text("UpdateCatalogAddress")
    if cfg_update_addr:
        out(f"Каталог обн.:   {cfg_update_addr}")
    out()

    # --- Section: Modes ---
    out("--- Режимы работы ---")
    out(f"Формат:              {version}")
    out(f"Совместимость:       {cfg_compat}")
    out(f"Совм. расширений:    {cfg_ext_compat}")
    out(f"Режим запуска:       {cfg_default_run}")
    out(f"Язык скриптов:       {cfg_script}")
    out(f"Блокировки:          {cfg_data_lock}")
    out(f"Автонумерация:       {cfg_auto_num}")
    out(f"Модальность:         {cfg_modality}")
    out(f"Синхр. вызовы:       {cfg_sync_calls}")
    out(f"Интерфейс:           {cfg_intf_compat}")
    out(f"Табл. пространства:  {cfg_db_spaces}")
    out(f"Режим окна:          {cfg_window_mode}")
    out()

    # --- Section: Language, roles, purposes ---
    out("--- Назначение ---")
    out(f"Язык по умолч.:  {cfg_default_lang}")

    # UsePurposes
    purpose_node = props_node.find("md:UsePurposes", NS)
    if purpose_node is not None:
        purposes = []
        for val in purpose_node.findall("v8:Value", NS):
            if val.text:
                purposes.append(val.text)
        if purposes:
            out(f"Назначения:      {', '.join(purposes)}")

    # DefaultRoles
    roles_node = props_node.find("md:DefaultRoles", NS)
    if roles_node is not None:
        roles = []
        for item in roles_node.findall("xr:Item", NS):
            if item.text:
                roles.append(item.text)
        if roles:
            out(f"Роли по умолч.:  {len(roles)}")
            for r in roles:
                out(f"  - {r}")

    # Booleans
    use_mf = get_prop_text("UseManagedFormInOrdinaryApplication")
    use_of = get_prop_text("UseOrdinaryFormInManagedApplication")
    out(f"Управл.формы в обычн.: {use_mf}")
    out(f"Обычн.формы в управл.: {use_of}")
    out()

    # --- Section: Storages & default forms ---
    out("--- Хранилища и формы по умолчанию ---")
    storage_props = [
        "CommonSettingsStorage", "ReportsUserSettingsStorage", "ReportsVariantsStorage",
        "FormDataSettingsStorage", "DynamicListsUserSettingsStorage", "URLExternalDataStorage",
    ]
    for sp in storage_props:
        val = get_prop_text(sp)
        if val:
            out(f"  {sp}: {val}")
    form_props = [
        "DefaultReportForm", "DefaultReportVariantForm", "DefaultReportSettingsForm",
        "DefaultReportAppearanceTemplate", "DefaultDynamicListSettingsForm", "DefaultSearchForm",
        "DefaultDataHistoryChangeHistoryForm", "DefaultDataHistoryVersionDataForm",
        "DefaultDataHistoryVersionDifferencesForm", "DefaultCollaborationSystemUsersChoiceForm",
        "DefaultConstantsForm", "DefaultInterface", "DefaultStyle",
    ]
    for fp in form_props:
        val = get_prop_text(fp)
        if val:
            out(f"  {fp}: {val}")
    out()

    # --- Section: Info ---
    cfg_brief = get_prop_ml("BriefInformation")
    cfg_detail = get_prop_ml("DetailedInformation")
    cfg_copyright = get_prop_ml("Copyright")
    cfg_vendor_addr = get_prop_ml("VendorInformationAddress")
    cfg_info_addr = get_prop_ml("ConfigurationInformationAddress")
    if cfg_brief or cfg_detail or cfg_copyright or cfg_vendor_addr or cfg_info_addr:
        out("--- Информация ---")
        if cfg_brief:
            out(f"Краткая:         {cfg_brief}")
        if cfg_detail:
            out(f"Подробная:       {cfg_detail}")
        if cfg_copyright:
            out(f"Copyright:       {cfg_copyright}")
        if cfg_vendor_addr:
            out(f"Сайт поставщика: {cfg_vendor_addr}")
        if cfg_info_addr:
            out(f"Адрес информ.:   {cfg_info_addr}")
        out()

    # --- Section: Mobile functionalities ---
    mobile_func = props_node.find("md:UsedMobileApplicationFunctionalities", NS)
    if mobile_func is not None:
        enabled_funcs = []
        disabled_funcs = []
        for func in mobile_func.findall("app:functionality", NS):
            f_name = func.find("app:functionality", NS)
            f_use = func.find("app:use", NS)
            if f_name is not None and f_use is not None:
                if f_use.text == "true":
                    enabled_funcs.append(f_name.text or "")
                else:
                    disabled_funcs.append(f_name.text or "")
        total_func = len(enabled_funcs) + len(disabled_funcs)
        out(f"--- Мобильные функциональности ({total_func}, включено: {len(enabled_funcs)}) ---")
        for f in enabled_funcs:
            out(f"  [+] {f}")
        for f in disabled_funcs:
            out(f"  [-] {f}")
        out()

    # --- Section: InternalInfo ---
    internal_info = cfg_node.find("md:InternalInfo", NS)
    if internal_info is not None:
        contained = internal_info.findall("xr:ContainedObject", NS)
        out(f"--- InternalInfo ({len(contained)} ContainedObject) ---")
        for co in contained:
            class_id_node = co.find("xr:ClassId", NS)
            object_id_node = co.find("xr:ObjectId", NS)
            class_id = class_id_node.text if class_id_node is not None else ""
            object_id = object_id_node.text if object_id_node is not None else ""
            out(f"  {class_id} -> {object_id}")
        out()

    # --- Section: ChildObjects (full list) ---
    out(f"--- Состав ({total_objects} объектов) ---")
    out()

    for type_name in type_order:
        if type_name not in object_counts:
            continue
        count = object_counts[type_name]
        ru_name = type_ru_names.get(type_name, type_name)
        out(f"  {ru_name} ({type_name}): {count}")

        # Collect names for this type
        if child_obj_node is not None:
            for child in child_obj_node:
                if not isinstance(child.tag, str):
                    continue
                if etree.QName(child.tag).localname == type_name:
                    out(f"    {child.text or ''}")

# --- Pagination and output ---
total = len(lines_buf)
if args.Offset > 0 or args.Limit < total:
    start = min(args.Offset, total)
    end = min(start + args.Limit, total)
    page = lines_buf[start:end]
    result = "\n".join(page)
    if end < total:
        result += f"\n\n... ({end} of {total} lines, use -Offset {end} to continue)"
else:
    result = "\n".join(lines_buf)

print(result)

if args.OutFile:
    out_file = args.OutFile
    if not os.path.isabs(out_file):
        out_file = os.path.join(os.getcwd(), out_file)
    with open(out_file, "w", encoding="utf-8-sig") as f:
        f.write(result)
    print(f"\nWritten to: {out_file}")
