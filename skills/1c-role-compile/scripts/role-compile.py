#!/usr/bin/env python3
# role-compile v1.4 — Compile 1C role from JSON
# Source: https://github.com/Desko77/claude-code-skills-1c
import argparse
import json
import os
import re
import sys
import uuid

# ============================================================
# Support guard (Ext/ParentConfigurations.bin) — see docs/1c-support-state-spec.md
# Blocks edits of vendor objects "на замке" / read-only configs. Trigger = bin
# present; reaction from .v8-project.json editingAllowedCheck (deny|warn|off,
# default deny). Never throws (except sys.exit on deny) — errors degrade to allow.
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
                reason = "объект не снят с поддержки — удаление сломает обновления"
        else:
            if best is not None and best == 0:
                blocked = True
                code = "locked"
                reason = "объект на замке — редактирование сломает обновления"
        if not blocked:
            return
        mode = _sg_get_edit_mode(cfg_dir)
        if mode == "off":
            return
        if mode == "warn":
            sys.stderr.write(f"[support-guard] ПРЕДУПРЕЖДЕНИЕ: {reason}. Цель: {rp}\n")
            return
        head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
        cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) — состояние поддержки менять не нужно, обновления вендора сохраняются."
        off_note = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
        if code == "capability-off":
            state = f"Состояние: у всей конфигурации выключена возможность изменения (режим read-only «из коробки») — поэтому объект «{rp}» редактировать нельзя."
            fix = (
                "Либо снять защиту явно (навык support-edit, два шага):\n"
                f'  1. support-edit -Path "{cfg_dir}" -Capability on — включить возможность изменения (объекты пока остаются на замке);\n'
                f'  2. support-edit -Path "{rp}" -Set editable — открыть этот объект для редактирования.\n'
                "  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
            )
        elif code == "not-removed":
            state = f"Состояние: объект «{rp}» на поддержке (не снят с поддержки) — его удаление разорвёт обновления вендора."
            fix = (
                "Либо сначала снять объект с поддержки, затем удалять:\n"
                f'  support-edit -Path "{rp}" -Set off-support — объект уходит из-под обновлений, после этого удаление безопасно.'
            )
        else:
            state = f"Состояние: объект «{rp}» на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
            fix = (
                "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):\n"
                f'  support-edit -Path "{rp}" -Set editable — редактировать и дальше получать обновления вендора (возможны конфликты слияния);\n'
                f'  support-edit -Path "{rp}" -Set off-support — снять с поддержки: обновления по объекту больше не приходят.'
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




def detect_format_version(d):
    while d:
        cfg_path = os.path.join(d, "Configuration.xml")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                head = f.read(2000)
            m = re.search(r'<MetaDataObject[^>]+version="(\d+\.\d+)"', head)
            if m:
                return m.group(1)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return "2.17"


def esc_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def emit_mltext(lines, indent, tag, text):
    if not text:
        lines.append(f"{indent}<{tag}/>")
        return
    lines.append(f"{indent}<{tag}>")
    lines.append(f"{indent}\t<v8:item>")
    lines.append(f"{indent}\t\t<v8:lang>ru</v8:lang>")
    lines.append(f"{indent}\t\t<v8:content>{esc_xml(text)}</v8:content>")
    lines.append(f"{indent}\t</v8:item>")
    lines.append(f"{indent}</{tag}>")


def new_uuid():
    return str(uuid.uuid4())


def write_utf8_bom(path, content):
    # Исходники 1С хранятся в CRLF: этого ждет Конфигуратор, и это закреплено в .gitattributes.
    # Сборка идет через '\n'.join, поэтому концы строк разворачиваются здесь, на записи.
    # Нормализация идемпотентна - смешанный текст тоже приходит к одному виду.
    content = content.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)


# --- Russian synonyms -> canonical English names ---

TYPE_ALIASES = {
    "Справочник": "Catalog",
    "Документ": "Document",
    "РегистрСведений": "InformationRegister",
    "РегистрНакопления": "AccumulationRegister",
    "РегистрБухгалтерии": "AccountingRegister",
    "РегистрРасчета": "CalculationRegister",
    "Константа": "Constant",
    "ПланСчетов": "ChartOfAccounts",
    "ПланВидовХарактеристик": "ChartOfCharacteristicTypes",
    "ПланВидовРасчета": "ChartOfCalculationTypes",
    "ПланОбмена": "ExchangePlan",
    "БизнесПроцесс": "BusinessProcess",
    "Задача": "Task",
    "Обработка": "DataProcessor",
    "Отчет": "Report",
    "ОбщаяФорма": "CommonForm",
    "ОбщаяКоманда": "CommonCommand",
    "Подсистема": "Subsystem",
    "КритерийОтбора": "FilterCriterion",
    "ЖурналДокументов": "DocumentJournal",
    "Последовательность": "Sequence",
    "ВебСервис": "WebService",
    "HTTPСервис": "HTTPService",
    "СервисИнтеграции": "IntegrationService",
    "ПараметрСеанса": "SessionParameter",
    "ОбщийРеквизит": "CommonAttribute",
    "Конфигурация": "Configuration",
    "Перечисление": "Enum",
    # Nested
    "Реквизит": "Attribute",
    "СтандартныйРеквизит": "StandardAttribute",
    "ТабличнаяЧасть": "TabularSection",
    "Измерение": "Dimension",
    "Ресурс": "Resource",
    "Команда": "Command",
    "РеквизитАдресации": "AddressingAttribute",
}

RIGHT_ALIASES = {
    "Чтение": "Read",
    "Добавление": "Insert",
    "Изменение": "Update",
    "Удаление": "Delete",
    "Просмотр": "View",
    "Редактирование": "Edit",
    "ВводПоСтроке": "InputByString",
    "Проведение": "Posting",
    "ОтменаПроведения": "UndoPosting",
    "ИнтерактивноеДобавление": "InteractiveInsert",
    "ИнтерактивнаяПометкаУдаления": "InteractiveSetDeletionMark",
    "ИнтерактивноеСнятиеПометкиУдаления": "InteractiveClearDeletionMark",
    "ИнтерактивноеУдаление": "InteractiveDelete",
    "ИнтерактивноеУдалениеПомеченных": "InteractiveDeleteMarked",
    "ИнтерактивноеПроведение": "InteractivePosting",
    "ИнтерактивноеПроведениеНеоперативное": "InteractivePostingRegular",
    "ИнтерактивнаяОтменаПроведения": "InteractiveUndoPosting",
    "ИнтерактивноеИзменениеПроведенных": "InteractiveChangeOfPosted",
    "Использование": "Use",
    "Получение": "Get",
    "Установка": "Set",
    "Старт": "Start",
    "ИнтерактивныйСтарт": "InteractiveStart",
    "ИнтерактивнаяАктивация": "InteractiveActivate",
    "Выполнение": "Execute",
    "ИнтерактивноеВыполнение": "InteractiveExecute",
    "УправлениеИтогами": "TotalsControl",
    "Администрирование": "Administration",
    "АдминистрированиеДанных": "DataAdministration",
    "ТонкийКлиент": "ThinClient",
    "ВебКлиент": "WebClient",
    "ТолстыйКлиент": "ThickClient",
    "ВнешнееСоединение": "ExternalConnection",
    "Вывод": "Output",
    "СохранениеДанныхПользователя": "SaveUserData",
    "МобильныйКлиент": "MobileClient",
}

# --- Known rights per object type ---

KNOWN_RIGHTS = {
    "Configuration": [
        "Administration", "DataAdministration", "UpdateDataBaseConfiguration",
        "ConfigurationExtensionsAdministration", "ActiveUsers", "EventLog", "ExclusiveMode",
        "ThinClient", "ThickClient", "WebClient", "MobileClient", "ExternalConnection",
        "Automation", "Output", "SaveUserData", "TechnicalSpecialistMode",
        "InteractiveOpenExtDataProcessors", "InteractiveOpenExtReports",
        "AnalyticsSystemClient", "CollaborationSystemInfoBaseRegistration",
        "MainWindowModeNormal", "MainWindowModeWorkplace",
        "MainWindowModeEmbeddedWorkplace", "MainWindowModeFullscreenWorkplace", "MainWindowModeKiosk",
    ],
    "Catalog": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "UpdateDataHistoryOfMissingData", "ReadDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "Document": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "Posting", "UndoPosting",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked",
        "InteractivePosting", "InteractivePostingRegular", "InteractiveUndoPosting",
        "InteractiveChangeOfPosted",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "UpdateDataHistoryOfMissingData", "ReadDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "InformationRegister": [
        "Read", "Update", "View", "Edit", "TotalsControl",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "UpdateDataHistoryOfMissingData", "ReadDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "AccumulationRegister": ["Read", "Update", "View", "Edit", "TotalsControl"],
    "AccountingRegister": ["Read", "Update", "View", "Edit", "TotalsControl"],
    "CalculationRegister": ["Read", "View"],
    "Constant": [
        "Read", "Update", "View", "Edit",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "ChartOfAccounts": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
        "ReadDataHistory", "ReadDataHistoryOfMissingData",
        "UpdateDataHistory", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
    ],
    "ChartOfCharacteristicTypes": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "ReadDataHistoryOfMissingData", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "ChartOfCalculationTypes": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
    ],
    "ExchangePlan": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "ReadDataHistoryOfMissingData", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "BusinessProcess": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "Start", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveActivate", "InteractiveStart",
    ],
    "Task": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "Execute", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveActivate", "InteractiveExecute",
    ],
    "DataProcessor": ["Use", "View"],
    "Report": ["Use", "View"],
    "CommonForm": ["View"],
    "CommonCommand": ["View"],
    "Subsystem": ["View"],
    "FilterCriterion": ["View"],
    "DocumentJournal": ["Read", "View"],
    "Sequence": ["Read", "Update"],
    "WebService": ["Use"],
    "HTTPService": ["Use"],
    "IntegrationService": ["Use"],
    "SessionParameter": ["Get", "Set"],
    "CommonAttribute": ["View", "Edit"],
}

NESTED_RIGHTS = ["View", "Edit"]
COMMAND_RIGHTS = ["View"]

# --- Presets ---

PRESETS = {
    "view": {
        "Catalog": ["Read", "View", "InputByString"],
        "ExchangePlan": ["Read", "View", "InputByString"],
        "Document": ["Read", "View", "InputByString"],
        "ChartOfAccounts": ["Read", "View", "InputByString"],
        "ChartOfCharacteristicTypes": ["Read", "View", "InputByString"],
        "ChartOfCalculationTypes": ["Read", "View", "InputByString"],
        "BusinessProcess": ["Read", "View", "InputByString"],
        "Task": ["Read", "View", "InputByString"],
        "InformationRegister": ["Read", "View"],
        "AccumulationRegister": ["Read", "View"],
        "AccountingRegister": ["Read", "View"],
        "CalculationRegister": ["Read", "View"],
        "Constant": ["Read", "View"],
        "DocumentJournal": ["Read", "View"],
        "Sequence": ["Read"],
        "CommonForm": ["View"],
        "CommonCommand": ["View"],
        "Subsystem": ["View"],
        "FilterCriterion": ["View"],
        "SessionParameter": ["Get"],
        "CommonAttribute": ["View"],
        "DataProcessor": ["Use", "View"],
        "Report": ["Use", "View"],
        "Configuration": ["ThinClient", "WebClient", "Output", "SaveUserData", "MainWindowModeNormal"],
    },
    "edit": {
        "Catalog": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"],
        "ExchangePlan": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"],
        "Document": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "Posting", "UndoPosting", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark", "InteractivePosting", "InteractivePostingRegular", "InteractiveUndoPosting", "InteractiveChangeOfPosted"],
        "ChartOfAccounts": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"],
        "ChartOfCharacteristicTypes": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"],
        "ChartOfCalculationTypes": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"],
        "BusinessProcess": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "Start", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark", "InteractiveActivate", "InteractiveStart"],
        "Task": ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString", "Execute", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark", "InteractiveActivate", "InteractiveExecute"],
        "InformationRegister": ["Read", "Update", "View", "Edit"],
        "AccumulationRegister": ["Read", "Update", "View", "Edit"],
        "AccountingRegister": ["Read", "Update", "View", "Edit"],
        "Constant": ["Read", "Update", "View", "Edit"],
        "DocumentJournal": ["Read", "View"],
        "Sequence": ["Read", "Update"],
        "SessionParameter": ["Get", "Set"],
        "CommonAttribute": ["View", "Edit"],
    },
}


def translate_object_name(name):
    parts = name.split('.')
    result = []
    for p in parts:
        # Написание с точками над е и без них равноправно: пользователь пишет как привык, а в
        # карте алиасов ключ один. Имя самого объекта не нормализуется - оно идет как есть.
        normalized = p.replace('ё', 'е').replace('Ё', 'Е')
        result.append(TYPE_ALIASES.get(normalized, p))
    return '.'.join(result)


def translate_right_name(name):
    return RIGHT_ALIASES.get(name, name)


def get_object_type(object_name):
    dot_idx = object_name.find('.')
    if dot_idx < 0:
        return object_name
    return object_name[:dot_idx]


def is_nested_object(object_name):
    return len(object_name.split('.')) >= 3


def resolve_preset(object_type, preset_name):
    preset = preset_name.lstrip('@')
    if preset not in PRESETS:
        print(f"WARNING: Unknown preset '@{preset}'. Known: @view, @edit", file=sys.stderr)
        return []
    type_map = PRESETS[preset]
    if object_type not in type_map:
        available = []
        for k in PRESETS:
            if object_type in PRESETS[k]:
                available.append(f'@{k}')
        avail_str = ', '.join(available) if available else 'none'
        print(f"WARNING: Preset '@{preset}' not defined for type '{object_type}'. Available: {avail_str}", file=sys.stderr)
        return []
    return list(type_map[object_type])


# Типы метаданных, у которых прав в роли нет вовсе (таблица типов, docs/1c-configuration-spec.md).
# Блок прав на такой тип платформа не примет, поэтому это отказ, а не предупреждение.
TYPES_WITHOUT_RIGHTS = [
    "CommandGroup", "CommonModule", "CommonPicture", "CommonTemplate", "DefinedType",
    "DocumentNumerator", "Enum", "EventSubscription", "FunctionalOption",
    "FunctionalOptionsParameter", "Language", "Role", "ScheduledJob", "SettingsStorage",
    "Style", "StyleItem", "WSReference", "XDTOPackage",
]

# Типы, права которых этим навыком не замерены: имя признается, набор прав не проверяется.
TYPES_RIGHTS_NOT_CHECKED = ["ExternalDataSource"]

# Виды вложенности по владельцу. Ключ - тип объекта или вид предыдущего уровня: у HTTP-сервиса
# внутри шаблона URL лежит метод, у таблицы внешнего источника - поле, у куба - измерение.
DEFAULT_NESTED_KINDS = ["Attribute", "TabularSection", "Command"]
NESTED_KINDS_BY_OWNER = {
    "WebService": ["Operation"],
    "HTTPService": ["URLTemplate"],
    "URLTemplate": ["Method"],
    "IntegrationService": ["IntegrationServiceChannel"],
    "Subsystem": ["Subsystem"],
    "CalculationRegister": ["Recalculation"],
    "ExternalDataSource": ["Table", "Cube", "Function"],
    "Table": ["Field"],
    "Cube": ["Dimension", "ResourceField"],
}

# Права вложенных объектов зависят от вида: у операции веб-сервиса и метода HTTP-сервиса это
# Use, у реквизита - View и Edit, у перерасчета - Read и Update.
NESTED_RIGHTS_BY_KIND = {
    "Attribute": ["View", "Edit"],
    "TabularSection": ["View", "Edit"],
    "Field": ["View", "Edit"],
    "Command": ["View"],
    "Subsystem": ["View"],
    "Operation": ["Use"],
    "Method": ["Use"],
    "URLTemplate": ["Use"],
    "IntegrationServiceChannel": ["Use"],
    "Recalculation": ["Read", "Update"],
}

# Виды, набор прав которых этим навыком не замерен: имя признается, права не проверяются.
NESTED_KINDS_RIGHTS_NOT_CHECKED = ["Table", "Cube", "Dimension", "ResourceField", "Function"]

# Ошибки ввода копятся до конца разбора: пользователь видит весь список сразу, а не по одной
# ошибке за прогон.
INPUT_ERRORS = []


def add_input_error(message):
    INPUT_ERRORS.append(message)


def find_similar_name(name, candidates):
    """Ближайшее по написанию имя - для подсказки при опечатке.

    Сравнение по общему префиксу и вхождению: этого хватает на реальные опечатки.
    """
    best = None
    best_score = 0
    for candidate in candidates:
        score = 0
        for a, b in zip(name, candidate):
            if a == b:
                score += 1
            else:
                break
        if name in candidate or candidate in name:
            score += 2
        if score > best_score:
            best_score = score
            best = candidate
    return best if best_score >= 3 else None


def test_object_type_known(object_name):
    object_type = get_object_type(object_name)
    if object_type in KNOWN_RIGHTS or object_type in TYPES_RIGHTS_NOT_CHECKED:
        return True
    if object_type in TYPES_WITHOUT_RIGHTS:
        add_input_error(f"{object_name}: тип '{object_type}' не имеет прав в роли")
        return False
    known = list(KNOWN_RIGHTS) + TYPES_WITHOUT_RIGHTS + TYPES_RIGHTS_NOT_CHECKED
    similar = find_similar_name(object_type, known)
    hint = f" Возможно: {similar}?" if similar else ""
    add_input_error(f"{object_name}: неизвестный тип объекта '{object_type}'.{hint}")
    return False


def find_kind_owner(kind):
    for owner, kinds in NESTED_KINDS_BY_OWNER.items():
        if kind in kinds:
            return owner
    return None


def test_nested_kind(object_name):
    parts = object_name.split(".")
    # Имя идет парами "вид.имя", поэтому виды стоят на четных позициях начиная с третьей.
    for i in range(2, len(parts), 2):
        kind = parts[i]
        owner = parts[0] if i == 2 else parts[i - 2]
        allowed = NESTED_KINDS_BY_OWNER.get(owner, DEFAULT_NESTED_KINDS)
        if kind in allowed:
            continue

        real_owner = find_kind_owner(kind)
        if real_owner:
            # Владелец вида сам бывает видом: поле лежит в таблице, а таблица - во внешнем
            # источнике данных. В сообщении называется корень цепочки, он же тип объекта.
            root_owner = real_owner
            for _ in range(10):
                upper = find_kind_owner(root_owner)
                if not upper:
                    break
                root_owner = upper
            chain = f" (внутри {real_owner})" if root_owner != real_owner else ""
            add_input_error(f"{object_name}: вид вложенности '{kind}' бывает только у "
                            f"{root_owner}{chain}, а здесь владелец '{owner}'")
        else:
            add_input_error(f"{object_name}: неизвестный вид вложенности '{kind}' у '{owner}'")
        return False
    return True


def validate_right_name(object_name, right_name):
    object_type = get_object_type(object_name)

    if is_nested_object(object_name):
        # Вид вложенности - предпоследний сегмент имени: пары идут как "вид.имя".
        kind = object_name.split(".")[-2]
        if kind in NESTED_KINDS_RIGHTS_NOT_CHECKED:
            return True
        allowed = NESTED_RIGHTS_BY_KIND.get(kind)
        if allowed is None:
            return True
        if right_name not in allowed:
            add_input_error(f"{object_name}: право '{right_name}' не существует у вида "
                            f"'{kind}' (допустимо: {', '.join(allowed)})")
            return False
        return True


    if object_type not in KNOWN_RIGHTS:
        # Тип уже разобран отдельной проверкой: здесь либо он без прав, либо права не замерены.
        return True

    valid_rights = KNOWN_RIGHTS[object_type]
    if right_name not in valid_rights:
        similar = find_similar_name(right_name, valid_rights)
        hint = f" Возможно: {similar}?" if similar else ""
        add_input_error(f"{object_name}: право '{right_name}' не существует у типа "
                        f"'{object_type}'.{hint}")
        return False

    return True


def parse_object_entry(entry):
    # --- String shorthand ---
    if isinstance(entry, str):
        colon_idx = entry.find(':')
        if colon_idx < 0:
            print(f"WARNING: Invalid string '{entry}' -- expected 'Object.Name: @preset' or 'Object.Name: Right1, Right2'", file=sys.stderr)
            return None
        obj_name = translate_object_name(entry[:colon_idx].strip())
        rights_str = entry[colon_idx + 1:].strip()
        object_type = get_object_type(obj_name)
        type_ok = test_object_type_known(obj_name)
        kind_ok = test_nested_kind(obj_name)
        if not type_ok or not kind_ok:
            return None

        if rights_str.startswith('@'):
            right_names = resolve_preset(object_type, rights_str)
        else:
            right_names = [translate_right_name(r.strip()) for r in rights_str.split(',') if r.strip()]
            for r in right_names:
                validate_right_name(obj_name, r)

        rights = []
        for r in right_names:
            rights.append({'Name': r, 'Value': 'true', 'Condition': None})
        return {'Name': obj_name, 'Rights': rights}

    # --- Object form ---
    obj_name = translate_object_name(str(entry.get('name', '')))
    if not obj_name:
        print("WARNING: Object entry missing 'name' field", file=sys.stderr)
        return None

    object_type = get_object_type(obj_name)
    type_ok = test_object_type_known(obj_name)
    kind_ok = test_nested_kind(obj_name)
    if not type_ok or not kind_ok:
        return None
    # Use a list of tuples to preserve insertion order
    rights_map = {}  # name -> {Value, Condition}
    rights_order = []  # preserve order

    # 1) Start with preset
    if entry.get('preset'):
        preset_rights = resolve_preset(object_type, str(entry['preset']))
        for r in preset_rights:
            if r not in rights_map:
                rights_order.append(r)
            rights_map[r] = {'Value': 'true', 'Condition': None}

    # 2) Apply explicit rights
    if entry.get('rights') is not None:
        if isinstance(entry['rights'], list):
            for r in entry['rights']:
                r_name = translate_right_name(str(r))
                validate_right_name(obj_name, r_name)
                if r_name not in rights_map:
                    rights_order.append(r_name)
                rights_map[r_name] = {'Value': 'true', 'Condition': None}
        elif isinstance(entry['rights'], dict):
            for p_name, p_value in entry['rights'].items():
                r_name = translate_right_name(p_name)
                validate_right_name(obj_name, r_name)
                bool_val = 'true' if p_value is True or str(p_value) == 'True' else 'false'
                if r_name not in rights_map:
                    rights_order.append(r_name)
                rights_map[r_name] = {'Value': bool_val, 'Condition': None}

    # 3) Apply RLS conditions
    if entry.get('rls'):
        for p_name, p_value in entry['rls'].items():
            rls_right = translate_right_name(p_name)
            if rls_right in rights_map:
                rights_map[rls_right]['Condition'] = str(p_value)
            else:
                print(f"WARNING: {obj_name}: RLS for '{rls_right}' but this right is not in the rights list", file=sys.stderr)

    # Convert to array
    rights = []
    for k in rights_order:
        rights.append({
            'Name': k,
            'Value': rights_map[k]['Value'],
            'Condition': rights_map[k]['Condition'],
        })

    return {'Name': obj_name, 'Rights': rights}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description='Compile 1C role from JSON', allow_abbrev=False)
    parser.add_argument('-JsonPath', type=str, required=True)
    parser.add_argument('-OutputDir', type=str, required=True)
    args = parser.parse_args()

    # --- 1. Load and validate JSON ---
    json_path = args.JsonPath
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8-sig') as f:
        defn = lenient(json.load(f))

    if not defn.get('name'):
        print("JSON must have 'name' field (role programmatic name)", file=sys.stderr)
        sys.exit(1)

    role_name = str(defn['name'])
    synonym = str(defn['synonym']) if defn.get('synonym') else role_name
    comment = str(defn['comment']) if defn.get('comment') else ''

    # Synonym: accept "rights" as alias for "objects"
    if not defn.get('objects') and defn.get('rights'):
        defn['objects'] = defn['rights']

    out_dir_resolved = args.OutputDir if os.path.isabs(args.OutputDir) else os.path.join(os.getcwd(), args.OutputDir)
    format_version = detect_format_version(out_dir_resolved)

    # --- 2. Parse all object entries ---
    parsed_objects = []
    if defn.get('objects'):
        for entry in defn['objects']:
            parsed = parse_object_entry(entry)
            if parsed:
                parsed_objects.append(parsed)

    # Отказ до первой записи: ни файла роли, ни записи в Configuration.xml. Иначе на диске
    # оставалась бы роль с неполным набором прав, и ошибка ввода превращалась бы в порчу
    # выгрузки.
    if INPUT_ERRORS:
        for message in INPUT_ERRORS:
            print(f"Ошибка: {message}", file=sys.stderr)
        print("Файлы не созданы: исправьте описание роли и повторите.", file=sys.stderr)
        sys.exit(1)

    # --- 3. Generate UUID ---
    uid = new_uuid()

    # --- 4. Emit metadata XML (Roles/Name.xml) ---
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"')
    lines.append('        xmlns:app="http://v8.1c.ru/8.2/managed-application/core"')
    lines.append('        xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config"')
    lines.append('        xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi"')
    lines.append('        xmlns:ent="http://v8.1c.ru/8.1/data/enterprise"')
    lines.append('        xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform"')
    lines.append('        xmlns:style="http://v8.1c.ru/8.1/data/ui/style"')
    lines.append('        xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system"')
    lines.append('        xmlns:v8="http://v8.1c.ru/8.1/data/core"')
    lines.append('        xmlns:v8ui="http://v8.1c.ru/8.1/data/ui"')
    lines.append('        xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web"')
    lines.append('        xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows"')
    lines.append('        xmlns:xen="http://v8.1c.ru/8.3/xcf/enums"')
    lines.append('        xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef"')
    lines.append('        xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"')
    lines.append('        xmlns:xs="http://www.w3.org/2001/XMLSchema"')
    lines.append('        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append(f'        version="{format_version}">')
    lines.append(f'    <Role uuid="{uid}">')
    lines.append('        <Properties>')
    lines.append(f'            <Name>{role_name}</Name>')
    lines.append('            <Synonym>')
    lines.append('                <v8:item>')
    lines.append('                    <v8:lang>ru</v8:lang>')
    lines.append(f'                    <v8:content>{esc_xml(synonym)}</v8:content>')
    lines.append('                </v8:item>')
    lines.append('            </Synonym>')
    if comment:
        lines.append(f'            <Comment>{esc_xml(comment)}</Comment>')
    else:
        lines.append('            <Comment/>')
    lines.append('        </Properties>')
    lines.append('    </Role>')
    lines.append('</MetaDataObject>')

    # Платформа не оставляет перевод строки после закрывающего тега.
    metadata_xml = '\n'.join(lines)

    # --- 5. Emit Rights XML (Roles/Name/Ext/Rights.xml) ---
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<Rights xmlns="http://v8.1c.ru/8.2/roles"')
    lines.append('        xmlns:xs="http://www.w3.org/2001/XMLSchema"')
    lines.append('        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append(f'        xsi:type="Rights" version="{format_version}">')

    # Global flags
    sfno = str(defn['setForNewObjects']).lower() if defn.get('setForNewObjects') is not None else 'false'
    sfab = str(defn['setForAttributesByDefault']).lower() if defn.get('setForAttributesByDefault') is not None else 'true'
    irco = str(defn['independentRightsOfChildObjects']).lower() if defn.get('independentRightsOfChildObjects') is not None else 'false'

    lines.append(f'    <setForNewObjects>{sfno}</setForNewObjects>')
    lines.append(f'    <setForAttributesByDefault>{sfab}</setForAttributesByDefault>')
    lines.append(f'    <independentRightsOfChildObjects>{irco}</independentRightsOfChildObjects>')

    # Object blocks
    total_rights = 0
    for obj in parsed_objects:
        lines.append('    <object>')
        lines.append(f'        <name>{obj["Name"]}</name>')
        for right in obj['Rights']:
            lines.append('        <right>')
            lines.append(f'            <name>{right["Name"]}</name>')
            lines.append(f'            <value>{right["Value"]}</value>')
            if right['Condition']:
                lines.append('            <restrictionByCondition>')
                lines.append(f'                <condition>{esc_xml(right["Condition"])}</condition>')
                lines.append('            </restrictionByCondition>')
            lines.append('        </right>')
            total_rights += 1
        lines.append('    </object>')

    # RLS restriction templates
    template_count = 0
    if defn.get('templates'):
        for tpl in defn['templates']:
            lines.append('    <restrictionTemplate>')
            lines.append(f'        <name>{esc_xml(str(tpl["name"]))}</name>')
            lines.append(f'        <condition>{esc_xml(str(tpl["condition"]))}</condition>')
            lines.append('    </restrictionTemplate>')
            template_count += 1

    lines.append('</Rights>')

    rights_xml = '\n'.join(lines) + '\n'

    # --- 6. Write output files ---
    out_dir = args.OutputDir
    assert_edit_allowed(out_dir, "editable")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(os.getcwd(), out_dir)

    # Determine Roles dir and config root
    # Back-compat: if OutputDir leaf is "Roles", use as-is; otherwise treat as config root
    leaf = os.path.basename(out_dir.rstrip(os.sep).rstrip('/'))
    if leaf == 'Roles':
        roles_dir = out_dir
        config_dir = os.path.dirname(out_dir)
    else:
        roles_dir = os.path.join(out_dir, 'Roles')
        config_dir = out_dir

    # Metadata: Roles/RoleName.xml
    metadata_path = os.path.join(roles_dir, f'{role_name}.xml')
    os.makedirs(roles_dir, exist_ok=True)

    # Rights: Roles/RoleName/Ext/Rights.xml
    role_sub_dir = os.path.join(roles_dir, role_name)
    ext_dir = os.path.join(role_sub_dir, 'Ext')
    rights_path = os.path.join(ext_dir, 'Rights.xml')
    os.makedirs(ext_dir, exist_ok=True)

    write_utf8_bom(metadata_path, metadata_xml)
    write_utf8_bom(rights_path, rights_xml)

    # --- 7. Register in Configuration.xml ---
    config_xml_path = os.path.join(config_dir, 'Configuration.xml')
    reg_result = None

    if os.path.exists(config_xml_path):
        with open(config_xml_path, 'r', encoding='utf-8-sig') as f:
            raw_text = f.read()

        # Check if already registered
        if f'<Role>{role_name}</Role>' in raw_text:
            reg_result = 'already'
        else:
            # Find last <Role>...</Role> and insert after it
            role_pattern = re.compile(r'(<Role>[^<]*</Role>)')
            matches = list(role_pattern.finditer(raw_text))
            new_role_tag = f'<Role>{role_name}</Role>'

            if matches:
                # Insert after last existing <Role>
                last_match = matches[-1]
                insert_pos = last_match.end()
                raw_text = raw_text[:insert_pos] + f'\n\t\t\t{new_role_tag}' + raw_text[insert_pos:]
            else:
                # No existing roles — insert before </ChildObjects>
                raw_text = raw_text.replace('</ChildObjects>', f'\t\t\t{new_role_tag}\n\t\t</ChildObjects>')

            write_utf8_bom(config_xml_path, raw_text)
            reg_result = 'added'
    else:
        reg_result = 'no-config'

    # --- 8. Summary ---
    print(f"[OK] Role '{role_name}' compiled")
    print(f"     UUID: {uid}")
    print(f"     Metadata: {metadata_path}")
    print(f"     Rights:   {rights_path}")
    print(f"     Objects: {len(parsed_objects)}, Rights: {total_rights}, Templates: {template_count}")
    if reg_result == 'added':
        print(f"     Configuration.xml: <Role>{role_name}</Role> added to ChildObjects")
    elif reg_result == 'already':
        print(f"     Configuration.xml: <Role>{role_name}</Role> already registered")
    elif reg_result == 'no-childobj':
        print(f"WARNING: Configuration.xml found but <ChildObjects> not found", file=sys.stderr)
    elif reg_result == 'no-config':
        print(f"WARNING: Configuration.xml not found at {config_xml_path} -- register manually", file=sys.stderr)


if __name__ == '__main__':
    main()
