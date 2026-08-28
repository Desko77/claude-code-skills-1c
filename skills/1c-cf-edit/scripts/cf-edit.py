#!/usr/bin/env python3
# cf-edit v1.1 - Edit 1C configuration root (Configuration.xml)
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import io
import json
import os
import re
import subprocess
import uuid
import sys
from html import escape as html_escape
from lxml import etree

# ============================================================
# Support guard (Ext/ParentConfigurations.bin) - see docs/1c-support-state-spec.md
# Blocks edits of vendor objects "на замке" / read-only configs. Trigger = bin
# present; reaction from .v8-project.json editingAllowedCheck (deny|warn|off,
# default deny). Never throws (except sys.exit on deny) - errors degrade to allow.
# ============================================================

def _sg_parse(xml_path):
    """Разбор XML средствами стандартной библиотеки.

    Свой, а не разбор скила: одни порты работают через lxml, другие XML не разбирают вовсе,
    и обращение к чужому имени попадало в общий except ниже - гард молча разрешал правку.
    """
    from xml.etree import ElementTree as _sg_et
    return _sg_et.parse(xml_path).getroot()


def _sg_root_uuid(xml_path):
    if not os.path.isfile(xml_path):
        return None
    try:
        mx = _sg_parse(xml_path)
        for child in mx:
            if isinstance(child.tag, str) and child.get("uuid"):
                return child.get("uuid")
    except Exception:
        return None
    return None


def _sg_is_external_root(xml_path):
    if not os.path.isfile(xml_path):
        return False
    try:
        mx = _sg_parse(xml_path)
        for child in mx:
            if isinstance(child.tag, str):
                return child.tag.split("}")[-1] in ("ExternalDataProcessor", "ExternalReport")
    except Exception:
        return False
    return False

def _sg_find_v8project(start_dir):
    d = start_dir
    for _ in range(20):
        if not d:
            break
        pj = os.path.join(d, ".v8-project.json")
        if os.path.isfile(pj):
            return pj
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _sg_get_edit_mode(cfg_dir):
    try:
        pj = _sg_find_v8project(os.getcwd()) or _sg_find_v8project(cfg_dir)
        if not pj:
            return "deny"
        proj = json.loads(open(pj, encoding="utf-8-sig").read())
        cfg_full = os.path.normcase(os.path.abspath(cfg_dir)).rstrip("\\/")
        for db in proj.get("databases", []):
            src = db.get("configSrc")
            if src:
                src_full = os.path.normcase(os.path.abspath(src)).rstrip("\\/")
                if cfg_full == src_full or cfg_full.startswith(src_full + os.sep):
                    if db.get("editingAllowedCheck"):
                        return db["editingAllowedCheck"]
        if proj.get("editingAllowedCheck"):
            return proj["editingAllowedCheck"]
        return "deny"
    except Exception:
        return "deny"


def assert_edit_allowed(target_path, require):
    try:
        rp = os.path.abspath(target_path)
        # Autonomous external object (EPF/ERF): never part of a config on support (issue #39).
        if _sg_is_external_root(rp):
            return
        elem_uuid = _sg_root_uuid(rp)
        cfg_dir = None
        bin_path = None
        d = rp if os.path.isdir(rp) else os.path.dirname(rp)
        for _ in range(12):
            if not d:
                break
            if _sg_is_external_root(d + ".xml"):
                return
            if not elem_uuid:
                elem_uuid = _sg_root_uuid(d + ".xml")
            if not cfg_dir:
                cand = os.path.join(d, "Ext", "ParentConfigurations.bin")
                if os.path.exists(cand) or os.path.exists(os.path.join(d, "Configuration.xml")):
                    cfg_dir = d
                    bin_path = cand
            if elem_uuid and cfg_dir:
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        if not elem_uuid and cfg_dir:
            elem_uuid = _sg_root_uuid(os.path.join(cfg_dir, "Configuration.xml"))
        if not bin_path or not os.path.exists(bin_path):
            return
        data = open(bin_path, "rb").read()
        if len(data) <= 32:
            return
        if data[:3] == b"\xef\xbb\xbf":
            data = data[3:]
        text = data.decode("utf-8", "replace")
        h = re.match(r"\{6,(\d+),(\d+),", text)
        if not h:
            return
        g = int(h.group(1))
        k = int(h.group(2))
        if k == 0:
            return
        best = None
        if elem_uuid:
            for m in re.finditer(r"([0-2]),0," + re.escape(elem_uuid.lower()), text):
                f1 = int(m.group(1))
                if best is None or f1 < best:
                    best = f1
        blocked = False
        code = ""
        reason = ""
        if g == 1:
            blocked = True
            code = "capability-off"
            reason = "возможность изменения конфигурации выключена (вся конфигурация read-only)"
        elif require == "removed":
            if best is not None and best != 2:
                blocked = True
                code = "not-removed"
                reason = "объект не снят с поддержки - удаление сломает обновления"
        else:
            if best is not None and best == 0:
                blocked = True
                code = "locked"
                reason = "объект на замке - редактирование сломает обновления"
        if not blocked:
            return
        mode = _sg_get_edit_mode(cfg_dir)
        if mode == "off":
            return
        if mode == "warn":
            sys.stderr.write(f"[support-guard] ПРЕДУПРЕЖДЕНИЕ: {reason}. Цель: {rp}\n")
            return
        head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
        cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) - состояние поддержки менять не нужно, обновления вендора сохраняются."
        off_note = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
        if code == "capability-off":
            state = f"Состояние: у всей конфигурации выключена возможность изменения (режим read-only 'из коробки') - поэтому объект '{rp}' редактировать нельзя."
            fix = (
                "Либо снять защиту явно (навык support-edit, два шага):\n"
                f'  1. support-edit -Path "{cfg_dir}" -Capability on - включить возможность изменения (объекты пока остаются на замке);\n'
                f'  2. support-edit -Path "{rp}" -Set editable - открыть этот объект для редактирования.\n'
                "  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
            )
        elif code == "not-removed":
            state = f"Состояние: объект '{rp}' на поддержке (не снят с поддержки) - его удаление разорвет обновления вендора."
            fix = (
                "Либо сначала снять объект с поддержки, затем удалять:\n"
                f'  support-edit -Path "{rp}" -Set off-support - объект уходит из-под обновлений, после этого удаление безопасно.'
            )
        else:
            state = f"Состояние: объект '{rp}' на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
            fix = (
                "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):\n"
                f'  support-edit -Path "{rp}" -Set editable - редактировать и дальше получать обновления вендора (возможны конфликты слияния);\n'
                f'  support-edit -Path "{rp}" -Set off-support - снять с поддержки: обновления по объекту больше не приходят.'
            )
        sys.stderr.write(head + "\n" + state + "\n" + cfe + "\n" + fix + "\n" + off_note + "\n")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        return
# --- Конец общего блока гарда поддержки ---



class LenientDict(dict):
    """Словарь, нечувствительный к регистру ключей - как PSObject в PowerShell.

    Нужен для прощающего ввода: DSL принимает и `operation`, и `Operation`. Вложенные словари
    оборачиваются тоже, иначе леность теряется на первом же уровне вложенности.
    """

    def __init__(self, data=None):
        super().__init__()
        for k, v in (data or {}).items():
            self[k] = v

    @staticmethod
    def _wrap(v):
        if isinstance(v, dict):
            return LenientDict(v)
        if isinstance(v, list):
            return [LenientDict(x) if isinstance(x, dict) else x for x in v]
        return v

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))

    def _actual_key(self, key):
        if super().__contains__(key):
            return key
        if isinstance(key, str):
            low = key.lower()
            for k in super().keys():
                if isinstance(k, str) and k.lower() == low:
                    return k
        return None

    def __getitem__(self, key):
        k = self._actual_key(key)
        if k is None:
            raise KeyError(key)
        return super().__getitem__(k)

    def __contains__(self, key):
        return self._actual_key(key) is not None

    def get(self, key, default=None):
        k = self._actual_key(key)
        return super().__getitem__(k) if k is not None else default


def lenient(data):
    """JSON бывает объектом и массивом объектов - оборачиваем и то, и другое."""
    if isinstance(data, list):
        return [LenientDict(x) if isinstance(x, dict) else x for x in data]
    return LenientDict(data) if isinstance(data, dict) else data



MD_NS = "http://v8.1c.ru/8.3/MDClasses"
XR_NS = "http://v8.1c.ru/8.3/xcf/readable"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
V8_NS = "http://v8.1c.ru/8.1/data/core"
XS_NS = "http://www.w3.org/2001/XMLSchema"

# Canonical type order for ChildObjects (45 types)
TYPE_ORDER = [
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
    "BusinessProcess", "Task", "IntegrationService", "Bot",
]

# Type → on-disk directory name (plural)
TYPE_TO_DIR = {
    "Language": "Languages", "Subsystem": "Subsystems", "StyleItem": "StyleItems", "Style": "Styles",
    "CommonPicture": "CommonPictures", "SessionParameter": "SessionParameters", "Role": "Roles", "CommonTemplate": "CommonTemplates",
    "FilterCriterion": "FilterCriteria", "CommonModule": "CommonModules", "CommonAttribute": "CommonAttributes", "ExchangePlan": "ExchangePlans",
    "XDTOPackage": "XDTOPackages", "WebService": "WebServices", "HTTPService": "HTTPServices", "WSReference": "WSReferences",
    "EventSubscription": "EventSubscriptions", "ScheduledJob": "ScheduledJobs", "SettingsStorage": "SettingsStorages", "FunctionalOption": "FunctionalOptions",
    "FunctionalOptionsParameter": "FunctionalOptionsParameters", "DefinedType": "DefinedTypes", "CommonCommand": "CommonCommands", "CommandGroup": "CommandGroups",
    "Constant": "Constants", "CommonForm": "CommonForms", "Catalog": "Catalogs", "Document": "Documents",
    "DocumentNumerator": "DocumentNumerators", "Sequence": "Sequences", "DocumentJournal": "DocumentJournals", "Enum": "Enums",
    "Report": "Reports", "DataProcessor": "DataProcessors", "InformationRegister": "InformationRegisters", "AccumulationRegister": "AccumulationRegisters",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes", "ChartOfAccounts": "ChartsOfAccounts", "AccountingRegister": "AccountingRegisters",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes", "CalculationRegister": "CalculationRegisters",
    "BusinessProcess": "BusinessProcesses", "Task": "Tasks", "IntegrationService": "IntegrationServices",
    "Bot": "Bots",
}

ML_PROPS = ["Synonym", "BriefInformation", "DetailedInformation", "Copyright", "VendorInformationAddress", "ConfigurationInformationAddress"]
SCALAR_PROPS = ["Name", "Version", "Vendor", "Comment", "NamePrefix", "UpdateCatalogAddress"]
REF_PROPS = ["DefaultLanguage"]


def localname(el):
    return etree.QName(el.tag).localname


def info(msg):
    print(f"[INFO] {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def get_child_indent(container):
    if container.text and "\n" in container.text:
        after_nl = container.text.rsplit("\n", 1)[-1]
        if after_nl and not after_nl.strip():
            return after_nl
    for child in container:
        if child.tail and "\n" in child.tail:
            after_nl = child.tail.rsplit("\n", 1)[-1]
            if after_nl and not after_nl.strip():
                return after_nl
    depth = 0
    current = container
    while current is not None:
        depth += 1
        current = current.getparent()
    return "\t" * depth


def insert_before_closing(container, new_el, child_indent):
    children = list(container)
    if len(children) == 0:
        parent_indent = child_indent[:-1] if len(child_indent) > 0 else ""
        container.text = "\n" + child_indent
        new_el.tail = "\n" + parent_indent
        container.append(new_el)
    else:
        last = children[-1]
        new_el.tail = last.tail
        last.tail = "\n" + child_indent
        container.append(new_el)


def insert_before_ref(container, new_el, ref_el, child_indent):
    """Insert new_el before ref_el inside container."""
    idx = list(container).index(ref_el)
    prev = ref_el.getprevious()
    if prev is not None:
        new_el.tail = prev.tail
        prev.tail = "\n" + child_indent
    else:
        new_el.tail = container.text
        container.text = "\n" + child_indent
    container.insert(idx, new_el)


def remove_with_indent(el):
    parent = el.getparent()
    prev = el.getprevious()
    if prev is not None:
        if el.tail:
            prev.tail = el.tail
    else:
        if el.tail:
            parent.text = el.tail
    parent.remove(el)


def expand_self_closing(container, parent_indent):
    if len(container) == 0 and not (container.text and container.text.strip()):
        container.text = "\n" + parent_indent


def import_fragment(xml_string):
    wrapper = (
        f'<_W xmlns="{MD_NS}" xmlns:xsi="{XSI_NS}" xmlns:v8="{V8_NS}" '
        f'xmlns:xr="{XR_NS}" xmlns:xs="{XS_NS}">{xml_string}</_W>'
    )
    frag = etree.fromstring(wrapper.encode("utf-8"))
    return list(frag)


def parse_batch_value(val):
    items = []
    for part in val.split(";;"):
        trimmed = part.strip()
        if trimmed:
            items.append(trimmed)
    return items


def save_xml_bom(tree, path):
    xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    # Пустой элемент: ElementTree отдает `<a />`, Конфигуратор пишет `<a/>`. Внутри
    # CDATA/комментария или значения атрибута ` />` может быть содержимым, поэтому ветками
    # альтернации и возвращаются как есть.
    xml_bytes = re.sub(rb'(?s)<!\[CDATA\[.*?\]\]>|<!--.*?-->|(?<=\S) />',
                    lambda m: b'/>' if m.group(0) == b' />' else m.group(0), xml_bytes)
    xml_bytes = xml_bytes.replace(b"<?xml version='1.0' encoding='UTF-8'?>", b'<?xml version="1.0" encoding="UTF-8"?>')
    # Концы строк: XML-разбор нормализует CRLF в LF при чтении, поэтому разворачиваем обратно -
    # исходники 1С хранятся в CRLF. Хвостового перевода платформа не пишет, замерено на выгрузках.
    # Концы строк берутся из ФАЙЛА, который правим: объекты конфигурации хранятся в CRLF,
    # схемы компоновки в LF. Форсировать один вид нельзя - навык испортит чужой формат.
    # После разбора в байтах всегда LF: XML-разбор нормализует концы строк при чтении.
    _orig = open(path, 'rb').read() if os.path.exists(path) else b''
    if b'\r\n' in _orig:
        xml_bytes = xml_bytes.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    # Хвостовой перевод исходного файла тоже сохраняется: универсального правила нет,
    # часть навыков его пишет, часть нет - правка не должна это менять.
    if _orig.endswith(b'\n') and not xml_bytes.endswith(b'\n'):
        xml_bytes += b'\r\n' if b'\r\n' in _orig else b'\n'
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(xml_bytes)


# Панели интерфейса клиентского приложения. Имени панели в файле нет: платформа опознает
# панель по ПОЗИЦИИ в списке panelDef. Порядок замерен на выгрузках - он одинаков в
# конфигурациях с разными uuid панелей.
PANEL_SLOTS = ("sections", "favorites", "history", "open", "functions")

# Зоны раскладки идут в файле в этом порядке; пустая зона не записывается.
PANEL_ZONES = ("top", "left", "right", "bottom")

# Русские имена типов в ссылке на форму. Значения - канонические имена ChildObjects.
RU_TYPE_MAP = {
    "Справочник": "Catalog", "Документ": "Document", "Перечисление": "Enum",
    "Отчет": "Report", "Обработка": "DataProcessor", "Константа": "Constant",
    "РегистрСведений": "InformationRegister", "РегистрНакопления": "AccumulationRegister",
    "РегистрБухгалтерии": "AccountingRegister", "РегистрРасчета": "CalculationRegister",
    "ПланСчетов": "ChartOfAccounts", "ПланВидовХарактеристик": "ChartOfCharacteristicTypes",
    "ПланВидовРасчета": "ChartOfCalculationTypes", "ПланОбмена": "ExchangePlan",
    "БизнесПроцесс": "BusinessProcess", "Задача": "Task", "ЖурналДокументов": "DocumentJournal",
    "ОбщаяФорма": "CommonForm", "Подсистема": "Subsystem",
}


def normalize_form_ref(ref):
    """Ссылка на форму приводится к виду Тип.Имя.Form.ИмяФормы.

    Принимается и краткая запись без сегмента Form, и русское имя типа: платформа пишет
    только канонический вид, а в задании удобнее любой.
    """
    parts = [p for p in str(ref).split(".") if p != ""]
    if not parts:
        return str(ref)
    parts[0] = RU_TYPE_MAP.get(parts[0], parts[0])
    if len(parts) == 3:
        parts.insert(2, "Form")
    elif len(parts) >= 4 and parts[2] in ("Форма", "form"):
        parts[2] = "Form"
    return ".".join(parts)


def detect_file_eol(path):
    """Конец строки существующего файла; у нового - канонический CRLF."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return '\r\n'
    return '\r\n' if b'\r\n' in data or b'\n' not in data else '\n'


def parse_object_value(op_name, value):
    """Значение операции - объект. Из -Value оно приходит строкой, разбираем JSON."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            print(f"{op_name}: -Value is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        if isinstance(parsed, dict):
            return parsed
    print(f"{op_name} value must be an object", file=sys.stderr)
    sys.exit(1)


def read_panel_defs(interface_path):
    """Идентификаторы panelDef в порядке файла - это и есть порядок PANEL_SLOTS."""
    ids = []
    for line in io.open(interface_path, encoding="utf-8-sig").read().split("\n"):
        m = re.search(r'<panelDef id="([^"]+)"', line)
        if m:
            ids.append(m.group(1))
    return ids


OPERATIONS = (
    "modify-property", "add-childObject", "remove-childObject",
    "add-defaultRole", "remove-defaultRole", "set-defaultRoles",
    "set-home-page", "set-panels",
)


def _canon_op(name):
    """Имя операции приводится к каноническому виду - switch в PowerShell сравнивает
    без учета регистра, а python по умолчанию с учетом."""
    low = str(name).lower()
    for o in OPERATIONS:
        if o.lower() == low:
            return o
    return name


def sibling_skill_script(name, script_name):
    """Скрипт соседнего навыка. Каталог навыка назван с префиксом 1c-, без него пути нет."""
    base = os.path.dirname(os.path.abspath(__file__))
    for folder in ('1c-' + name, name):
        candidate = os.path.normpath(os.path.join(base, '..', '..', folder, 'scripts', script_name))
        if os.path.isfile(candidate):
            return candidate
    return ''


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Edit 1C configuration root (Configuration.xml)", allow_abbrev=False)
    parser.add_argument("-ConfigPath", required=True)
    parser.add_argument("-DefinitionFile", default=None)
    parser.add_argument("-Operation", default=None, choices=["modify-property", "add-childObject", "remove-childObject", "add-defaultRole",
                                 "remove-defaultRole", "set-defaultRoles", "set-home-page", "set-panels"])
    parser.add_argument("-Value", default=None)
    parser.add_argument("-NoValidate", action="store_true")
    args = parser.parse_args()

    if args.DefinitionFile and args.Operation:
        print("Cannot use both -DefinitionFile and -Operation", file=sys.stderr)
        sys.exit(1)
    if not args.DefinitionFile and not args.Operation:
        print("Either -DefinitionFile or -Operation is required", file=sys.stderr)
        sys.exit(1)

    config_path = args.ConfigPath
    assert_edit_allowed(config_path, "editable")
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if os.path.isdir(config_path):
        candidate = os.path.join(config_path, "Configuration.xml")
        if os.path.isfile(candidate):
            config_path = candidate
        else:
            print("No Configuration.xml in directory", file=sys.stderr)
            sys.exit(1)
    if not os.path.isfile(config_path):
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    resolved_path = os.path.abspath(config_path)
    config_dir = os.path.dirname(resolved_path)

    xml_parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(resolved_path, xml_parser)
    xml_root = tree.getroot()

    add_count = 0
    remove_count = 0
    modify_count = 0
    # Пакет применяется целиком: побочные файлы пишутся после того, как прошли все
    # операции. Иначе отказ на второй операции оставлял первый файл уже записанным.
    pending_writes = []

    cfg_el = None
    for child in xml_root:
        if isinstance(child.tag, str) and localname(child) == "Configuration":
            cfg_el = child
            break
    if cfg_el is None:
        print("No <Configuration> element found", file=sys.stderr)
        sys.exit(1)

    props_el = None
    child_objs_el = None
    for child in cfg_el:
        if not isinstance(child.tag, str):
            continue
        if localname(child) == "Properties":
            props_el = child
        if localname(child) == "ChildObjects":
            child_objs_el = child

    obj_name = ""
    if props_el is not None:
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "Name":
                obj_name = (child.text or "").strip()
                break
    info(f"Configuration: {obj_name}")

    # --- Operations ---
    def do_modify_property(batch_val):
        nonlocal modify_count
        items = parse_batch_value(batch_val)
        for item in items:
            eq_idx = item.find("=")
            if eq_idx < 1:
                print(f"Invalid property format '{item}', expected 'Key=Value'", file=sys.stderr)
                sys.exit(1)
            prop_name = item[:eq_idx].strip()
            prop_value = item[eq_idx + 1:].strip()

            prop_el = None
            for child in props_el:
                if isinstance(child.tag, str) and localname(child) == prop_name:
                    prop_el = child
                    break
            if prop_el is None:
                print(f"Property '{prop_name}' not found in Properties", file=sys.stderr)
                sys.exit(1)

            if prop_name in ML_PROPS:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                if not prop_value:
                    prop_el.text = None
                else:
                    indent = get_child_indent(props_el)
                    item_el = etree.SubElement(prop_el, f"{{{V8_NS}}}item")
                    lang_el = etree.SubElement(item_el, f"{{{V8_NS}}}lang")
                    lang_el.text = "ru"
                    content_el = etree.SubElement(item_el, f"{{{V8_NS}}}content")
                    content_el.text = prop_value
                    prop_el.text = "\n" + indent + "\t"
                    item_el.text = "\n" + indent + "\t\t"
                    lang_el.tail = "\n" + indent + "\t\t"
                    content_el.tail = "\n" + indent + "\t"
                    item_el.tail = "\n" + indent
            elif prop_name in SCALAR_PROPS or prop_name in REF_PROPS:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                if not prop_value:
                    prop_el.text = None
                else:
                    prop_el.text = prop_value
            else:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                prop_el.text = prop_value

            modify_count += 1
            info(f'Set {prop_name} = "{prop_value}"')

    def do_add_child_object(batch_val):
        nonlocal add_count
        if child_objs_el is None:
            print("No <ChildObjects> element found", file=sys.stderr)
            sys.exit(1)

        items = parse_batch_value(batch_val)
        cfg_indent = get_child_indent(cfg_el)
        if len(child_objs_el) == 0 and not (child_objs_el.text and child_objs_el.text.strip()):
            expand_self_closing(child_objs_el, cfg_indent)
        child_indent = get_child_indent(child_objs_el)

        for item in items:
            dot_idx = item.find(".")
            if dot_idx < 1:
                print(f"Invalid format '{item}', expected 'Type.Name'", file=sys.stderr)
                sys.exit(1)
            type_name = item[:dot_idx]
            obj_name_val = item[dot_idx + 1:]

            if type_name not in TYPE_ORDER:
                print(f"Unknown type '{type_name}'", file=sys.stderr)
                sys.exit(1)
            type_idx = TYPE_ORDER.index(type_name)

            # Check that the referenced object actually exists on disk.
            # cf-edit add-childObject is a low-level operation for rare scenarios
            # (e.g. restoring a rolled-back Configuration.xml when object files are intact).
            # For creating NEW objects, meta-compile/role-compile/subsystem-compile already
            # auto-register in Configuration.xml - calling cf-edit add-childObject there is
            # unnecessary and error-prone.
            type_dir = TYPE_TO_DIR.get(type_name)
            obj_file = os.path.join(config_dir, type_dir, f"{obj_name_val}.xml")
            if not os.path.exists(obj_file):
                hint_skill = {"Subsystem": "subsystem-compile", "Role": "role-compile"}.get(type_name, "meta-compile")
                print(
                    f"Object file not found: {type_dir}/{obj_name_val}.xml\n"
                    f"cf-edit add-childObject only references objects that already exist on disk.\n"
                    f"To create a new {type_name}, use {hint_skill} (auto-registers in Configuration.xml):\n"
                    f'  /{hint_skill} with {{"type":"{type_name}","name":"{obj_name_val}"}}',
                    file=sys.stderr
                )
                sys.exit(1)

            # Dedup
            exists = False
            for child in child_objs_el:
                if isinstance(child.tag, str) and localname(child) == type_name and (child.text or "") == obj_name_val:
                    exists = True
                    break
            if exists:
                warn(f"Already exists: {type_name}.{obj_name_val}")
                continue

            # Find insertion point
            insert_before = None
            for child in child_objs_el:
                if not isinstance(child.tag, str):
                    continue
                child_type_name = localname(child)
                if child_type_name not in TYPE_ORDER:
                    continue
                child_type_idx = TYPE_ORDER.index(child_type_name)

                if child_type_name == type_name:
                    if (child.text or "") > obj_name_val and insert_before is None:
                        insert_before = child
                elif child_type_idx > type_idx and insert_before is None:
                    insert_before = child

            new_el = etree.Element(f"{{{MD_NS}}}{type_name}")
            new_el.text = obj_name_val

            if insert_before is not None:
                insert_before_ref(child_objs_el, new_el, insert_before, child_indent)
            else:
                insert_before_closing(child_objs_el, new_el, child_indent)

            add_count += 1
            info(f"Added: {type_name}.{obj_name_val}")

    def do_remove_child_object(batch_val):
        nonlocal remove_count
        if child_objs_el is None:
            print("No <ChildObjects> element found", file=sys.stderr)
            sys.exit(1)

        items = parse_batch_value(batch_val)
        for item in items:
            dot_idx = item.find(".")
            if dot_idx < 1:
                print(f"Invalid format '{item}', expected 'Type.Name'", file=sys.stderr)
                sys.exit(1)
            type_name = item[:dot_idx]
            obj_name_val = item[dot_idx + 1:]

            found = False
            for child in list(child_objs_el):
                if isinstance(child.tag, str) and localname(child) == type_name and (child.text or "") == obj_name_val:
                    remove_with_indent(child)
                    remove_count += 1
                    info(f"Removed: {type_name}.{obj_name_val}")
                    found = True
                    break
            if not found:
                warn(f"Not found: {type_name}.{obj_name_val}")

    def do_add_default_role(batch_val):
        nonlocal add_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found in Properties", file=sys.stderr)
            sys.exit(1)

        props_indent = get_child_indent(props_el)
        if len(roles_el) == 0 and not (roles_el.text and roles_el.text.strip()):
            expand_self_closing(roles_el, props_indent)
        role_indent = get_child_indent(roles_el)

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            exists = False
            for child in roles_el:
                if isinstance(child.tag, str) and (child.text or "").strip() == role_name:
                    exists = True
                    break
            if exists:
                warn(f"DefaultRole already exists: {role_name}")
                continue

            frag_xml = f'<xr:Item xsi:type="xr:MDObjectRef">{role_name}</xr:Item>'
            nodes = import_fragment(frag_xml)
            if nodes:
                insert_before_closing(roles_el, nodes[0], role_indent)
                add_count += 1
                info(f"Added DefaultRole: {role_name}")

    def do_remove_default_role(batch_val):
        nonlocal remove_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found", file=sys.stderr)
            sys.exit(1)

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            found = False
            for child in list(roles_el):
                if isinstance(child.tag, str) and (child.text or "").strip() == role_name:
                    remove_with_indent(child)
                    remove_count += 1
                    info(f"Removed DefaultRole: {role_name}")
                    found = True
                    break
            if not found:
                warn(f"DefaultRole not found: {role_name}")

    def do_set_home_page(batch_val):
        nonlocal modify_count
        batch_val = parse_object_value("set-home-page", batch_val)

        version = xml_root.get("version") or "2.17"
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<HomePageWorkArea xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" '
                 'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
                 'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
                 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                 f'version="{version}">']
        template = batch_val.get("template") or "TwoColumnsVariableWidth"
        lines.append(f"\t<WorkingAreaTemplate>{html_escape(template)}</WorkingAreaTemplate>")

        item_count = 0
        for key, tag in (("left", "LeftColumn"), ("right", "RightColumn")):
            column = batch_val.get(key) or []
            if not column:
                continue
            lines.append(f"\t<{tag}>")
            for entry in column:
                item = entry if isinstance(entry, dict) else {"form": entry}
                form = normalize_form_ref(item.get("form", ""))
                # Высота 10 и общая видимость - то, что платформа подставляет сама.
                height = item.get("height", 10)
                visible = item.get("visibility", True)
                lines.append("\t\t<Item>")
                lines.append(f"\t\t\t<Form>{html_escape(form)}</Form>")
                lines.append(f"\t\t\t<Height>{int(height)}</Height>")
                lines.append("\t\t\t<Visibility>")
                lines.append(f"\t\t\t\t<xr:Common>{'true' if visible else 'false'}</xr:Common>")
                for role, allowed in (item.get("roles") or {}).items():
                    role_name = role if str(role).startswith("Role.") else f"Role.{role}"
                    flag = 'true' if allowed else 'false'
                    lines.append(f'\t\t\t\t<xr:Value name="{html_escape(role_name)}">{flag}</xr:Value>')
                lines.append("\t\t\t</Visibility>")
                lines.append("\t\t</Item>")
                item_count += 1
            lines.append(f"\t</{tag}>")
        lines.append("</HomePageWorkArea>")

        ext_dir = os.path.join(os.path.dirname(resolved_path), "Ext")
        target = os.path.join(ext_dir, "HomePageWorkArea.xml")
        pending_writes.append((target, "\n".join(lines), detect_file_eol(target)))
        modify_count += 1
        info(f"Home page work area: {template}, {item_count} form(s)")

    def do_set_panels(batch_val):
        nonlocal modify_count
        batch_val = parse_object_value("set-panels", batch_val)

        interface_path = os.path.join(os.path.dirname(resolved_path), "Ext",
                                      "ClientApplicationInterface.xml")
        if not os.path.isfile(interface_path):
            print(f"Ext/ClientApplicationInterface.xml not found next to {resolved_path}",
                  file=sys.stderr)
            sys.exit(1)
        panel_defs = read_panel_defs(interface_path)
        if len(panel_defs) != len(PANEL_SLOTS):
            print(f"Ext/ClientApplicationInterface.xml: expected {len(PANEL_SLOTS)} panelDef, "
                  f"found {len(panel_defs)}", file=sys.stderr)
            sys.exit(1)
        slot_uuid = dict(zip(PANEL_SLOTS, panel_defs))

        def panel_lines(name, indent):
            if name not in slot_uuid:
                print(f"Unknown panel '{name}'. Known: {', '.join(PANEL_SLOTS)}", file=sys.stderr)
                sys.exit(1)
            pad = "\t" * indent
            return [f'{pad}<panel id="{uuid.uuid4()}">',
                    f"{pad}\t<uuid>{slot_uuid[name]}</uuid>",
                    f"{pad}</panel>"]

        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<ClientApplicationInterface xmlns="http://v8.1c.ru/8.2/managed-application/core" '
                 'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
                 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                 'xsi:type="InterfaceLayouter">']
        placed = 0
        for zone in PANEL_ZONES:
            entries = batch_val.get(zone) or []
            if not entries:
                continue
            lines.append(f"\t<{zone}>")
            for entry in entries:
                # Группа - стек панелей в одной зоне: внешний group с id, внутри по одному
                # безымянному group на каждую панель.
                if isinstance(entry, dict) and entry.get("group"):
                    lines.append(f'\t\t<group id="{uuid.uuid4()}">')
                    for member in entry["group"]:
                        lines.append("\t\t\t<group>")
                        lines.extend(panel_lines(member, 4))
                        lines.append("\t\t\t</group>")
                        placed += 1
                    lines.append("\t\t</group>")
                else:
                    lines.extend(panel_lines(entry, 2))
                    placed += 1
            lines.append(f"\t</{zone}>")
        for panel_id in panel_defs:
            lines.append(f'\t<panelDef id="{panel_id}"/>')
        lines.append("</ClientApplicationInterface>")

        pending_writes.append((interface_path, "\n".join(lines), detect_file_eol(interface_path)))
        modify_count += 1
        info(f"Client application interface: {placed} panel(s) placed")

    def do_set_default_roles(batch_val):
        nonlocal modify_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found", file=sys.stderr)
            sys.exit(1)

        # Clear all existing children
        for ch in list(roles_el):
            roles_el.remove(ch)
        roles_el.text = None

        if not items:
            modify_count += 1
            info("Cleared DefaultRoles")
            return

        props_indent = get_child_indent(props_el)
        role_indent = props_indent + "\t"

        roles_el.text = "\n" + props_indent

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            frag_xml = f'<xr:Item xsi:type="xr:MDObjectRef">{role_name}</xr:Item>'
            nodes = import_fragment(frag_xml)
            if nodes:
                insert_before_closing(roles_el, nodes[0], role_indent)

        modify_count += 1
        info(f"Set DefaultRoles: {len(items)} roles")

    # --- Execute operations ---
    operations = []
    if args.DefinitionFile:
        def_file = args.DefinitionFile
        if not os.path.isabs(def_file):
            def_file = os.path.join(os.getcwd(), def_file)
        with open(def_file, "r", encoding="utf-8-sig") as fh:
            ops = lenient(json.loads(fh.read()))
        if isinstance(ops, list):
            operations = ops
        else:
            operations = [ops]
    else:
        operations = [{"operation": args.Operation, "value": args.Value or ""}]

    for op in operations:
        op_name = op.get("operation", args.Operation or "")
        # Регистр имени операции не значим: switch в PowerShell сравнивает без его учета.
        op_name = _canon_op(op_name)
        op_value = op.get("value", args.Value or "")

        if op_name == "modify-property":
            do_modify_property(op_value)
        elif op_name == "add-childObject":
            do_add_child_object(op_value)
        elif op_name == "remove-childObject":
            do_remove_child_object(op_value)
        elif op_name == "add-defaultRole":
            do_add_default_role(op_value)
        elif op_name == "remove-defaultRole":
            do_remove_default_role(op_value)
        elif op_name == "set-defaultRoles":
            do_set_default_roles(op_value)
        elif op_name == "set-home-page":
            do_set_home_page(op_value)
        elif op_name == "set-panels":
            do_set_panels(op_value)
        else:
            print(f"Unknown operation: {op_name}", file=sys.stderr)
            sys.exit(1)

    # --- Save ---
    save_xml_bom(tree, resolved_path)
    for target, text, eol in pending_writes:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with io.open(target, "w", encoding="utf-8-sig", newline=eol) as fh:
            fh.write(text)
    info(f"Saved: {resolved_path}")

    # --- Auto-validate ---
    if not args.NoValidate:
        validate_script = sibling_skill_script('cf-validate', 'cf-validate.py')
        if validate_script:
            print()
            print("--- Running cf-validate ---")
            subprocess.run([sys.executable, validate_script, "-ConfigPath", resolved_path])

    # --- Summary ---
    print()
    print("=== cf-edit summary ===")
    print(f"  Configuration: {obj_name}")
    print(f"  Added:         {add_count}")
    print(f"  Removed:       {remove_count}")
    print(f"  Modified:      {modify_count}")
    sys.exit(0)


if __name__ == "__main__":
    main()
