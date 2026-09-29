#!/usr/bin/env python3
# role-edit v1.0 - точечная правка существующей роли 1С
import argparse
import html
import json
import os
import re
import subprocess
import sys

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

# --- Таблица прав и замыкание (общий блок, версия 2) ---
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
    # Замер 8.3.27: у регистра расчета есть Update и Edit, а TotalsControl - нет.
    "CalculationRegister": ["Read", "Update", "View", "Edit"],
    "Constant": [
        "Read", "Update", "View", "Edit",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "ChartOfAccounts": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
        "ReadDataHistory", "ReadDataHistoryOfMissingData",
        "UpdateDataHistory", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "ViewDataHistory", "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
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
        "InteractiveDelete", "InteractiveDeleteMarked",
        "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
        "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
        "ReadDataHistory", "ViewDataHistory", "UpdateDataHistory",
        "ReadDataHistoryOfMissingData", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
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
        "InteractiveDelete", "InteractiveDeleteMarked", "InteractiveActivate", "InteractiveStart",
        "ReadDataHistory", "ReadDataHistoryOfMissingData",
        "UpdateDataHistory", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "ViewDataHistory", "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "Task": [
        "Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
        "Execute", "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark",
        "InteractiveDelete", "InteractiveDeleteMarked", "InteractiveActivate", "InteractiveExecute",
        "ReadDataHistory", "ReadDataHistoryOfMissingData",
        "UpdateDataHistory", "UpdateDataHistoryOfMissingData",
        "UpdateDataHistorySettings", "UpdateDataHistoryVersionComment",
        "ViewDataHistory", "EditDataHistoryVersionComment", "SwitchToDataHistoryVersion",
    ],
    "DataProcessor": ["Use", "View"],
    "Report": ["Use", "View"],
    "CommonForm": ["View"],
    "CommonCommand": ["View"],
    "Subsystem": ["View"],
    "FilterCriterion": ["View"],
    "DocumentJournal": ["Read", "View"],
    "Sequence": ["Read", "Update"],
    # Замер 8.3.27: у самих веб- и HTTP-сервисов прав нет - платформа отбрасывает блок
    # при загрузке. Право Use живет на операции (WebService...Operation.*) и методе
    # (HTTPService...URLTemplate.*.Method.*).
    "WebService": [],
    "HTTPService": [],
    # Замер 8.3.27: у самого сервиса интеграции прав нет - платформа отбрасывает блок
    # при загрузке. Право Use живет на канале
    # (IntegrationService...IntegrationServiceChannel.*).
    "IntegrationService": [],
    "SessionParameter": ["Get", "Set"],
    "CommonAttribute": ["View", "Edit"],
}

NESTED_RIGHTS = ["View", "Edit"]
COMMAND_RIGHTS = ["View"]

# --- Замыкание прав по зависимостям ---
#
# Платформа при загрузке роли дописывает права, без которых заданные не действуют:
# после первой загрузки файл роли и база расходятся, если писать ровно заданный набор.
# Замер круговым прогоном на 8.3.27.2214: роль с единственным правом R загружается в
# пустую базу и выгружается обратно; в выгрузке - полный набор, который держит R.
# Замыкание одноименных прав объединяется (проверено сверкой с выгрузкой полного набора).

GLOBAL_RIGHT_IMPL = {
    "Insert": ["Read"],
    "Update": ["Read"],
    "Delete": ["Read"],
    "View": ["Read"],
    "Edit": ["Read", "Update", "View"],
    "InputByString": ["Read", "View"],
    "InteractiveInsert": ["Read", "Insert", "Update", "View", "Edit"],
    "InteractiveDelete": ["Read", "Update", "Delete", "View", "Edit"],
    "InteractiveDeleteMarked": ["Read", "Update", "Delete", "View", "Edit"],
    "InteractiveSetDeletionMark": ["Read", "Update", "View", "Edit"],
    "InteractiveClearDeletionMark": ["Read", "Update", "View", "Edit"],
    "InteractiveDeletePredefinedData":
        ["Read", "Update", "Delete", "View", "Edit", "InteractiveDelete"],
    "InteractiveSetDeletionMarkPredefinedData":
        ["Read", "Update", "View", "Edit", "InteractiveSetDeletionMark"],
    "InteractiveClearDeletionMarkPredefinedData":
        ["Read", "Update", "View", "Edit", "InteractiveClearDeletionMark"],
    "InteractiveDeleteMarkedPredefinedData":
        ["Read", "Update", "Delete", "View", "Edit", "InteractiveDeleteMarked"],
    "Posting": ["Read", "Update"],
    "UndoPosting": ["Read", "Update"],
    "InteractivePosting": ["Read", "Update", "Posting", "View", "Edit"],
    "InteractivePostingRegular": ["InteractivePosting"],
    "InteractiveUndoPosting": ["Read", "Update", "UndoPosting", "View", "Edit"],
    "InteractiveChangeOfPosted": ["Read", "Update", "View", "Edit"],
    "ReadDataHistory": ["Read"],
    "ReadDataHistoryOfMissingData": ["Read", "ReadDataHistory"],
    "UpdateDataHistory": ["Read", "ReadDataHistory"],
    "UpdateDataHistoryOfMissingData":
        ["Read", "ReadDataHistory", "ReadDataHistoryOfMissingData", "UpdateDataHistory"],
    "UpdateDataHistoryVersionComment": ["Read", "ReadDataHistory"],
    "ViewDataHistory": ["Read", "View", "ReadDataHistory"],
    "EditDataHistoryVersionComment": ["Read", "View", "ReadDataHistory", "UpdateDataHistoryVersionComment"],
    "SwitchToDataHistoryVersion": ["Read", "View"],
    "Start": ["Read", "Update"],
    "InteractiveStart": ["Read", "Update", "Start"],
    "InteractiveActivate": ["Read", "Update"],
    "Execute": ["Read", "Update"],
    "InteractiveExecute": ["Read", "Update", "Execute"],
    "Administration": ["DataAdministration"],
}

# Отклонения от глобальных правил, снятые тем же замером.
RIGHT_IMPL_BY_TYPE = {
    # У плана счетов блок истории данных не тянет за собой Read.
    "ChartOfAccounts": {
        "ReadDataHistory": [],
        "ReadDataHistoryOfMissingData": ["ReadDataHistory"],
        "UpdateDataHistory": ["ReadDataHistory"],
        "UpdateDataHistoryOfMissingData":
            ["ReadDataHistory", "ReadDataHistoryOfMissingData", "UpdateDataHistory"],
        "UpdateDataHistoryVersionComment": ["ReadDataHistory"],
        "ViewDataHistory": ["View", "ReadDataHistory"],
        "EditDataHistoryVersionComment": ["View", "ReadDataHistory", "UpdateDataHistoryVersionComment"],
        "SwitchToDataHistoryVersion": ["View"],
    },
    # У регистра сведений история отсутствующих данных не входит в замыкание.
    "InformationRegister": {
        "UpdateDataHistoryOfMissingData": ["Read", "ReadDataHistory", "UpdateDataHistory"],
    },
    # У обработки и отчета просмотр требует использования, а не чтения.
    "DataProcessor": {"View": ["Use"]},
    "Report": {"View": ["Use"]},
}


def impl_for(object_type, right):
    """Импликации права у конкретного типа: переопределение или глобальные,
    пересеченные с правами типа (импликация имеет смысл только для существующих прав)."""
    override = RIGHT_IMPL_BY_TYPE.get(object_type, {}).get(right)
    if override is not None:
        return list(override)
    type_rights = KNOWN_RIGHTS.get(object_type)
    implied = GLOBAL_RIGHT_IMPL.get(right, [])
    if type_rights is None:
        return list(implied)
    return [r for r in implied if r in type_rights]


def close_rights(object_type, right_names):
    """Транзитивное замыкание включенных прав по зависимостям.

    Возвращает замкнутый набор: платформа при загрузке дописывает те же права, поэтому
    файл, собранный этим замыканием, совпадает с выгрузкой после первой загрузки.
    """
    result = set(right_names)
    frontier = list(right_names)
    while frontier:
        r = frontier.pop()
        for imp in impl_for(object_type, r):
            if imp not in result:
                result.add(imp)
                frontier.append(imp)
    return result


# --- Канонический порядок прав ---
#
# Платформа выгружает права объекта в одном порядке по всем типам. Порядок снят с
# выгрузки полного набора и сверен: порядок каждого типа - подпоследовательность этого
# списка. Права вне списка (незамеренные вложенные виды) идут в конце в порядке ввода.
RIGHT_ORDER = [
    # Configuration
    "Administration", "DataAdministration", "UpdateDataBaseConfiguration",
    "ExclusiveMode", "ActiveUsers", "EventLog",
    "ThinClient", "WebClient", "MobileClient", "ThickClient", "ExternalConnection",
    "Automation", "TechnicalSpecialistMode", "CollaborationSystemInfoBaseRegistration",
    "MainWindowModeNormal", "MainWindowModeWorkplace", "MainWindowModeEmbeddedWorkplace",
    "MainWindowModeFullscreenWorkplace", "MainWindowModeKiosk", "AnalyticsSystemClient",
    "SaveUserData", "ConfigurationExtensionsAdministration",
    "InteractiveOpenExtDataProcessors", "InteractiveOpenExtReports", "Output",
    # объектные
    "Read", "Insert", "Update", "Delete", "Posting", "UndoPosting",
    "Use", "View", "Get", "Set",
    "InteractiveInsert", "Edit", "InteractiveDelete", "InteractiveSetDeletionMark",
    "InteractiveClearDeletionMark", "InteractiveDeleteMarked",
    "InteractivePosting", "InteractivePostingRegular", "InteractiveUndoPosting",
    "InteractiveChangeOfPosted", "InputByString",
    "InteractiveActivate", "Start", "InteractiveStart", "Execute", "InteractiveExecute",
    "InteractiveDeletePredefinedData", "InteractiveSetDeletionMarkPredefinedData",
    "InteractiveClearDeletionMarkPredefinedData", "InteractiveDeleteMarkedPredefinedData",
    "TotalsControl",
    "ReadDataHistory", "ReadDataHistoryOfMissingData", "UpdateDataHistory",
    "UpdateDataHistoryOfMissingData", "UpdateDataHistorySettings",
    "UpdateDataHistoryVersionComment", "ViewDataHistory", "EditDataHistoryVersionComment",
    "SwitchToDataHistoryVersion",
]
_RIGHT_ORDER_POS = {r: i for i, r in enumerate(RIGHT_ORDER)}


def right_sort_key(name):
    """Ключ сортировки права по каноническому порядку; незнакомое право - в конец."""
    return (_RIGHT_ORDER_POS.get(name, len(RIGHT_ORDER)),)


# Виды, у которых View и Edit подчиняются флажку setForAttributesByDefault.
# Замер 8.3.27.2214: выгрузка оставляет право, только если оно не совпадает с умолчанием.
# setForAttributesByDefault=true - умолчание true (явный true пропадает, false остается).
# setForAttributesByDefault=false - умолчание false (явный false пропадает, true остается).
# independentRightsOfChildObjects и наличие прав на сам объект выгрузку не меняют.
# Измерения и ресурсы регистров подчиняются тому же правилу; измерения куба внешнего источника не замерены.
NESTED_DEFAULT_KINDS = ("Attribute", "TabularSection", "StandardAttribute", "Dimension", "Resource")

# Условие ограничения доступа на вложенном праве, замер 8.3.27.2214: у стандартного реквизита
# выгрузка сохраняет условие и право с ним при любом значении; у реквизита, измерения и ресурса
# условие не сохраняется.
NESTED_CONDITION_KEPT_KINDS = ("StandardAttribute",)
NESTED_CONDITION_DROPPED_KINDS = ("Attribute", "Dimension", "Resource")


def nested_default_right_kept(object_name, right_name, value, set_for_attributes_by_default, condition=None):
    """Вложенное право остается в выгрузке, если несет сохраняемое условие или не дублирует умолчание."""
    parts = object_name.split(".")
    kind = parts[-2]
    if parts[0] == "ExternalDataSource" or kind not in NESTED_DEFAULT_KINDS or right_name not in ("View", "Edit"):
        return True
    if condition and kind in NESTED_CONDITION_KEPT_KINDS:
        return True
    default_value = "true" if set_for_attributes_by_default else "false"
    return str(value).lower() != default_value


def close_nested_view_edit(object_name, rights, set_for_attributes_by_default):
    """Согласует View и Edit вложенного права так, как их приводит загрузка платформы.

    Замер 8.3.27.2214: явный Edit=true при View=false дает View=true; View=false при Edit
    по умолчанию дает Edit=false. Возвращает новый список, исходный не меняется.
    """
    parts = object_name.split(".")
    rights = [dict(right) for right in rights]
    if parts[0] == "ExternalDataSource" or parts[-2] not in NESTED_DEFAULT_KINDS:
        return rights
    default_value = "true" if set_for_attributes_by_default else "false"
    view_right = next((r for r in rights if r['Name'] == 'View'), None)
    edit_right = next((r for r in rights if r['Name'] == 'Edit'), None)
    view = str(view_right['Value']).lower() if view_right else default_value
    edit = str(edit_right['Value']).lower() if edit_right else default_value
    if view != 'false' or edit != 'true':
        return rights
    if edit_right:
        if view_right:
            view_right['Value'] = 'true'
        else:
            rights.insert(rights.index(edit_right), {'Name': 'View', 'Value': 'true', 'Condition': None})
    else:
        rights.append({'Name': 'Edit', 'Value': 'false', 'Condition': None})
    return rights

# --- Конец общего блока таблицы прав и замыкания ---

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
DEFAULT_NESTED_KINDS = ["Attribute", "TabularSection", "StandardAttribute", "Command"]
REGISTER_NESTED_KINDS = ["Dimension", "Resource", "Attribute", "StandardAttribute", "Command"]
NESTED_KINDS_BY_OWNER = {
    "WebService": ["Operation"],
    "HTTPService": ["URLTemplate"],
    "URLTemplate": ["Method"],
    "IntegrationService": ["IntegrationServiceChannel"],
    "Subsystem": ["Subsystem"],
    "InformationRegister": REGISTER_NESTED_KINDS,
    "AccumulationRegister": REGISTER_NESTED_KINDS,
    "AccountingRegister": REGISTER_NESTED_KINDS,
    "CalculationRegister": REGISTER_NESTED_KINDS + ["Recalculation"],
    "ExternalDataSource": ["Table", "Cube", "Function"],
    "Table": ["Field"],
    "Cube": ["Dimension", "ResourceField"],
}

# Права вложенных объектов зависят от вида: у операции веб-сервиса и метода HTTP-сервиса это
# Use, у реквизита - View и Edit, у перерасчета - Read и Update.
NESTED_RIGHTS_BY_KIND = {
    "Attribute": ["View", "Edit"],
    "TabularSection": ["View", "Edit"],
    "StandardAttribute": ["View", "Edit"],
    "Resource": ["View", "Edit"],
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


def find_kind_owners(kind):
    return [owner for owner, kinds in NESTED_KINDS_BY_OWNER.items() if kind in kinds]


def test_nested_kind(object_name):
    parts = object_name.split(".")
    # Имя идет парами "вид.имя", поэтому виды стоят на четных позициях начиная с третьей.
    for i in range(2, len(parts), 2):
        kind = parts[i]
        owner = parts[0] if i == 2 else parts[i - 2]
        allowed = NESTED_KINDS_BY_OWNER.get(owner, DEFAULT_NESTED_KINDS)
        if kind in allowed:
            continue

        real_owners = [] if kind in DEFAULT_NESTED_KINDS else find_kind_owners(kind)
        if real_owners:
            # Владелец вида сам бывает видом: поле лежит в таблице, а таблица - во внешнем
            # источнике данных. В сообщении называется корень цепочки, он же тип объекта.
            places = []
            for real_owner in real_owners:
                root_owner = real_owner
                for _ in range(10):
                    upper = find_kind_owners(root_owner)
                    if not upper:
                        break
                    root_owner = upper[0]
                places.append(f"{root_owner} (внутри {real_owner})" if root_owner != real_owner else root_owner)
            add_input_error(f"{object_name}: вид вложенности '{kind}' бывает только у "
                            f"{', '.join(sorted(places))}, а здесь владелец '{owner}'")
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


def finish_rights(obj_name, rights_map, rights_order):
    """Замыкание включенных прав и канонический порядок выдачи.

    Замыкание применяется только к объектам верхнего уровня с замеренным набором прав:
    у вложенных видов платформа зависимостей не дописывает (замер 8.3.27).
    """
    object_type = get_object_type(obj_name)
    if not is_nested_object(obj_name) and object_type in KNOWN_RIGHTS:
        enabled = [r for r in rights_order if rights_map[r]['Value'] == 'true']
        closed = close_rights(object_type, enabled)
        for r in closed:
            if r not in rights_map:
                rights_order.append(r)
                rights_map[r] = {'Value': 'true', 'Condition': None}
        for r in rights_order:
            if rights_map[r]['Value'] == 'false' and r in closed:
                holders = sorted(p for p in closed
                                 if p != r and r in impl_for(object_type, p))
                print(f"WARNING: {obj_name}: право '{r}' выключено явно, но право "
                      f"{'/'.join(holders)} требует его включенным - платформа отбросит "
                      f"весь блок объекта при загрузке", file=sys.stderr)
    rights_order.sort(key=right_sort_key)
    return [{'Name': k, 'Value': rights_map[k]['Value'], 'Condition': rights_map[k]['Condition']}
            for k in rights_order]



# Экранирование текста для XML. Тело совпадает с role-compile: семейство общее.
def esc_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# Операции правки. Неизвестное имя - отказ.
KNOWN_OPS = {
    'add-rights', 'set-rights', 'remove-rights', 'deny-rights',
    'set-rls', 'remove-rls',
    'add-template', 'set-template', 'remove-template',
    'modify-property',
}

# Признаки роли, которые лежат в Rights.xml, а не в файле метаданных.
FLAG_PROPS = {
    'setForNewObjects',
    'setForAttributesByDefault',
    'independentRightsOfChildObjects',
}

PROP_MAP = {
    'synonym': 'synonym',
    'comment': 'comment',
    'setfornewobjects': 'setForNewObjects',
    'setforattributesbydefault': 'setForAttributesByDefault',
    'independentrightsofchildobjects': 'independentRightsOfChildObjects',
    'синоним': 'synonym',
    'комментарий': 'comment',
}


def stop_role_edit(message):
    """Отказ до записи: сообщение в stderr и код 1."""
    print(f'Ошибка: {message}', file=sys.stderr)
    sys.exit(1)


def flush_errors():
    """Печатает накопленные ошибки ввода и завершает процесс, если они есть."""
    if not INPUT_ERRORS:
        return
    for message in INPUT_ERRORS:
        print(f'Ошибка: {message}', file=sys.stderr)
    sys.exit(1)


def fold_op(item):
    """Ключи операции без учета регистра. Вложенный словарь прав не трогает."""
    if not isinstance(item, dict):
        return None
    out = {}
    for key, value in item.items():
        out[key.lower() if isinstance(key, str) else key] = value
    return out


def load_operations(path):
    """Читает JSON правки: массив, одна операция или объект с полем operations."""
    if not os.path.isfile(path):
        stop_role_edit(f'файл описания не найден: {path}')
    with open(path, 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        folded = fold_op(data)
        if 'operations' in folded:
            data = folded['operations']
        else:
            data = [folded]
    if not isinstance(data, list):
        add_input_error('описание правки: ожидался объект или массив операций')
        return []
    ops = []
    for item in data:
        folded = fold_op(item)
        if folded is None:
            add_input_error('операция: ожидался объект')
            continue
        ops.append(folded)
    return ops


def op_name(op):
    """Каноническое имя операции."""
    raw = op.get('operation') or op.get('op') or ''
    return str(raw).strip().lower()


def op_object_name(op):
    """Имя объекта метаданных в каноническом написании."""
    raw = op.get('object') or ''
    if not raw and op_name(op) not in ('add-template', 'set-template', 'remove-template', 'modify-property'):
        raw = op.get('name') or ''
    raw = str(raw).strip() if raw else ''
    return translate_object_name(raw) if raw else ''


def op_rights_spec(op):
    """Спецификация прав: поле rights, иначе value у операций над правами."""
    if 'rights' in op and op['rights'] is not None:
        return op['rights']
    if op_name(op) in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights'):
        if 'value' in op and op['value'] is not None:
            return op['value']
    return None


def op_right_name(op):
    """Имя одного права для операций RLS."""
    raw = op.get('right') or ''
    if not raw and isinstance(op.get('rights'), str):
        raw = op['rights']
    raw = str(raw).strip() if raw else ''
    return translate_right_name(raw) if raw else ''


def op_template_name(op):
    """Имя шаблона ограничения."""
    raw = op.get('template') or op.get('name') or ''
    return str(raw).strip()


def op_condition(op):
    """Текст условия RLS или шаблона. None - поле не задано."""
    if 'condition' in op and op['condition'] is not None:
        return str(op['condition'])
    if op_name(op) in ('set-rls', 'add-template', 'set-template') and 'value' in op and op['value'] is not None:
        return str(op['value'])
    return None


def op_property(op):
    """Имя свойства роли и новое значение. Неизвестное имя дает (None, value)."""
    prop = op.get('property') or ''
    value = op.get('value') if 'value' in op else None
    if not prop and isinstance(value, str) and '=' in value:
        prop, value = value.split('=', 1)
    if not prop:
        prop = op.get('name') or ''
    key = PROP_MAP.get(str(prop).strip().lower()) if prop else None
    return key, prop, value


def truthy(value):
    """Истина для значения права: bool, число и строки true/1/yes."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ('true', '1', 'yes')


def xml_bool(value):
    """true или false для признака роли. None - значение не разобрано."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    text = str(value).strip().lower()
    if text in ('true', '1'):
        return 'true'
    if text in ('false', '0'):
        return 'false'
    return None


def right_pairs(spec):
    """Пары (имя права, 'true'|'false') из строки, списка или словаря."""
    if isinstance(spec, str):
        parts = [part.strip() for part in spec.split(',') if part.strip()]
        return [(translate_right_name(part), 'true') for part in parts]
    if isinstance(spec, list):
        pairs = []
        for part in spec:
            text = str(part).strip()
            if text:
                pairs.append((translate_right_name(text), 'true'))
        return pairs
    if isinstance(spec, dict):
        pairs = []
        for key, value in spec.items():
            pairs.append((translate_right_name(str(key)), 'true' if truthy(value) else 'false'))
        return pairs
    add_input_error('права: ожидалась строка, список или словарь')
    return []


def validate_ops(ops):
    """Проверяет операции до чтения роли. Сообщения добавляются в INPUT_ERRORS."""
    if not ops:
        add_input_error('нет операций')
        return
    seen = set()
    for op in ops:
        name = op_name(op)
        if name not in KNOWN_OPS:
            add_input_error(f"неизвестная операция '{name}'")
            continue
        needs_object = name in (
            'add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls',
        )
        obj = op_object_name(op) if needs_object else ''
        if needs_object and not obj:
            add_input_error(f'{name}: не задан объект')
            continue
        check_type = name in ('add-rights', 'set-rights', 'deny-rights', 'set-rls')
        if check_type and obj not in seen:
            test_object_type_known(obj)
            test_nested_kind(obj)
            seen.add(obj)
        if name in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights'):
            spec = op_rights_spec(op)
            if spec is None or spec == '' or spec == [] or spec == {}:
                if name != 'set-rights' or spec is None:
                    add_input_error(f'{name}: не заданы права')
                elif spec is None:
                    add_input_error(f'{name}: не заданы права')
                continue
            if name == 'set-rights' and spec in ('', [], {}):
                continue
            pairs = right_pairs(spec)
            if name != 'remove-rights':
                for right_name, _value in pairs:
                    validate_right_name(obj, right_name)
            if name in ('add-rights', 'deny-rights', 'remove-rights') and not pairs:
                add_input_error(f'{name}: не заданы права')
        elif name == 'set-rls':
            right_name = op_right_name(op)
            if not right_name:
                add_input_error('set-rls: не задано право')
            else:
                validate_right_name(obj, right_name)
            rls_kind = obj.split('.')[-2] if is_nested_object(obj) else None
            if rls_kind in NESTED_CONDITION_DROPPED_KINDS:
                add_input_error(f"{obj}: платформа не хранит условие ограничения доступа у вида '{rls_kind}'")
            if op_condition(op) is None:
                add_input_error('set-rls: не задано условие')
        elif name == 'remove-rls':
            if not op_right_name(op):
                add_input_error('remove-rls: не задано право')
        elif name in ('add-template', 'set-template'):
            if not op_template_name(op):
                add_input_error(f'{name}: не задано имя шаблона')
            if op_condition(op) is None:
                add_input_error(f'{name}: не задано условие')
        elif name == 'remove-template':
            if not op_template_name(op):
                add_input_error('remove-template: не задано имя шаблона')
        elif name == 'modify-property':
            key, raw, value = op_property(op)
            if not key:
                add_input_error(f"неизвестное свойство '{raw}'")
            elif value is None:
                add_input_error(f'{key}: не задано значение')
            elif key in FLAG_PROPS and xml_bool(value) is None:
                add_input_error(f'{key}: ожидалось true или false')


def read_role_file(path):
    """Текст файла, признак BOM и признак CRLF. Переводы строк внутри - LF."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    body = raw[3:] if bom else raw
    text = body.decode('utf-8')
    crlf = '\r\n' in text
    return text.replace('\r\n', '\n'), bom, crlf


def write_text(path, text, bom, crlf):
    """Пишет текст в исходной кодировке файла: UTF-8, BOM и концы строк как были."""
    if crlf:
        text = text.replace('\n', '\r\n')
    data = text.encode('utf-8')
    if bom:
        data = b'\xef\xbb\xbf' + data
    with open(path, 'wb') as handle:
        handle.write(data)


def resolve_role_paths(path):
    """Пара путей: файл метаданных роли и Ext/Rights.xml."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        if os.path.basename(path).lower() == 'ext':
            return resolve_role_paths(os.path.join(path, 'Rights.xml'))
        name = os.path.basename(path)
        meta = os.path.join(os.path.dirname(path), name + '.xml')
        rights = os.path.join(path, 'Ext', 'Rights.xml')
        return meta, rights
    if os.path.basename(path).lower() == 'rights.xml':
        role_dir = os.path.dirname(os.path.dirname(path))
        name = os.path.basename(role_dir)
        meta = os.path.join(os.path.dirname(role_dir), name + '.xml')
        return meta, path
    name = os.path.splitext(os.path.basename(path))[0]
    meta = path if path.lower().endswith('.xml') else path + '.xml'
    rights = os.path.join(os.path.dirname(meta), name, 'Ext', 'Rights.xml')
    return meta, rights


def indent_unit(text):
    """Единица отступа файла: пробелы или таб перед первым вложенным тегом."""
    match = re.search(r'\n([ \t]+)<(?:object|setForNewObjects|restrictionTemplate)>', text)
    return match.group(1) if match else '\t'


def find_objects(text):
    """Блоки object: имя, права и границы в тексте с переводами LF."""
    found = []
    for match in re.finditer(r'[ \t]*<object>.*?</object>', text, re.DOTALL):
        block = match.group(0)
        name_match = re.search(r'<name>(.*?)</name>', block, re.DOTALL)
        rights = []
        for right_match in re.finditer(
            r'<right>\s*<name>(.*?)</name>\s*<value>(.*?)</value>(.*?)</right>',
            block,
            re.DOTALL,
        ):
            condition = None
            cond_match = re.search(r'<condition>(.*?)</condition>', right_match.group(3), re.DOTALL)
            if cond_match:
                condition = html.unescape(cond_match.group(1))
            rights.append({
                'Name': html.unescape(right_match.group(1).strip()),
                'Value': right_match.group(2).strip(),
                'Condition': condition,
            })
        found.append({
            'start': match.start(),
            'end': match.end(),
            'name': html.unescape(name_match.group(1).strip()) if name_match else '',
            'rights': rights,
        })
    return found


def render_object(name, rights, unit):
    """Блок object в оформлении выгрузки: таб или тот же отступ, что у файла."""
    lines = [f'{unit}<object>', f'{unit * 2}<name>{esc_xml(name)}</name>']
    for right in rights:
        lines.append(f'{unit * 2}<right>')
        lines.append(f'{unit * 3}<name>{esc_xml(right["Name"])}</name>')
        lines.append(f'{unit * 3}<value>{right["Value"]}</value>')
        if right.get('Condition'):
            lines.append(f'{unit * 3}<restrictionByCondition>')
            lines.append(f'{unit * 4}<condition>{esc_xml(right["Condition"])}</condition>')
            lines.append(f'{unit * 3}</restrictionByCondition>')
        lines.append(f'{unit * 2}</right>')
    lines.append(f'{unit}</object>')
    return '\n'.join(lines)


def close_object(obj_name, rights):
    """Замыкание включенных прав объекта и канонический порядок."""
    mapping = {}
    order = []
    for right in rights:
        if right['Name'] not in mapping:
            order.append(right['Name'])
        mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
    return finish_rights(obj_name, mapping, order)


def restore_conditions(current, new_rights):
    """Возвращает прежние условия RLS правам, которые после замыкания остались включенными.

    Замыкание дописывает недостающее право с пустым условием; если это право в роли уже было
    с условием, ограничение сохраняется, а не снимается молча.
    """
    old = {right['Name']: right.get('Condition') for right in current}
    for right in new_rights:
        if right['Value'] == 'true' and not right.get('Condition') and old.get(right['Name']):
            right['Condition'] = old[right['Name']]
    return new_rights


def splice_span(text, start, end, block):
    """Подменяет отрезок текста. block None удаляет отрезок вместе с переводом перед ним."""
    if block is None:
        if start > 0 and text[start - 1] == '\n':
            start -= 1
        return text[:start] + text[end:]
    return text[:start] + block + text[end:]


def insert_before_close(text, block, tag):
    """Вставляет блок перед первым тегом tag либо перед закрытием Rights."""
    match = re.search(r'\n[ \t]*<' + tag + r'>', text)
    if match is None and tag != '/Rights':
        match = re.search(r'\n[ \t]*</Rights>', text)
    if match is None:
        stop_role_edit('Rights.xml: нет закрывающего тега Rights')
    return text[:match.start()] + '\n' + block + text[match.start():]


def apply_rights_op(text, op):
    """Одна операция над правами или RLS. Чужие объекты не переписываются."""
    name = op_name(op)
    obj_name = op_object_name(op)
    unit = indent_unit(text)
    objects = find_objects(text)
    index = next((i for i, obj in enumerate(objects) if obj['name'] == obj_name), None)
    current = list(objects[index]['rights']) if index is not None else []

    if name == 'remove-rights':
        if index is None:
            return text
        drop = {pair[0] for pair in right_pairs(op_rights_spec(op))}
        kept = [right for right in current if right['Name'] not in drop]
        new_rights = restore_conditions(current, close_object(obj_name, kept))
        for removed in drop:
            if any(right['Name'] == removed and right['Value'] == 'true' for right in new_rights):
                print(
                    f"WARNING: {obj_name}: право '{removed}' снято, но замыкание снова включает его",
                    file=sys.stderr,
                )
        block = render_object(obj_name, new_rights, unit) if new_rights else None
        return splice_span(text, objects[index]['start'], objects[index]['end'], block)

    if name == 'remove-rls':
        if index is None:
            return text
        right_name = op_right_name(op)
        changed = False
        new_rights = []
        for right in current:
            item = dict(right)
            if item['Name'] == right_name and item.get('Condition'):
                item['Condition'] = None
                changed = True
            new_rights.append(item)
        if not changed:
            return text
        block = render_object(obj_name, new_rights, unit)
        return splice_span(text, objects[index]['start'], objects[index]['end'], block)

    if name == 'set-rights':
        pairs = right_pairs(op_rights_spec(op))
        old = {right['Name']: right for right in current}
        mapping = {}
        order = []
        for right_name, value in pairs:
            if right_name not in mapping:
                order.append(right_name)
                cond = old[right_name]['Condition'] if right_name in old else None
                mapping[right_name] = {'Value': value, 'Condition': cond}
        new_rights = restore_conditions(current, finish_rights(obj_name, mapping, order))
    elif name == 'set-rls':
        mapping = {}
        order = []
        for right in current:
            order.append(right['Name'])
            mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
        right_name = op_right_name(op)
        condition = op_condition(op)
        if right_name in mapping:
            mapping[right_name]['Value'] = 'true'
            mapping[right_name]['Condition'] = condition
        else:
            order.append(right_name)
            mapping[right_name] = {'Value': 'true', 'Condition': condition}
        new_rights = finish_rights(obj_name, mapping, order)
    else:
        pairs = right_pairs(op_rights_spec(op))
        if name == 'deny-rights':
            pairs = [(right_name, 'false') for right_name, _value in pairs]
        mapping = {}
        order = []
        for right in current:
            order.append(right['Name'])
            mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
        for right_name, value in pairs:
            if right_name in mapping:
                mapping[right_name]['Value'] = value
            else:
                order.append(right_name)
                mapping[right_name] = {'Value': value, 'Condition': None}
        new_rights = finish_rights(obj_name, mapping, order)

    block = render_object(obj_name, new_rights, unit) if new_rights else None
    if index is None:
        if block is None:
            return text
        if objects:
            end = objects[-1]['end']
            return text[:end] + '\n' + block + text[end:]
        return insert_before_close(text, block, 'restrictionTemplate')
    return splice_span(text, objects[index]['start'], objects[index]['end'], block)


def find_templates(text):
    """Шаблоны ограничения: имя, условие и границы блока."""
    found = []
    pattern = re.compile(
        r'[ \t]*<restrictionTemplate>\s*<name>(.*?)</name>\s*<condition>(.*?)</condition>\s*</restrictionTemplate>',
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        found.append({
            'start': match.start(),
            'end': match.end(),
            'name': html.unescape(match.group(1).strip()),
            'condition': html.unescape(match.group(2)),
        })
    return found


def render_template(name, condition, unit):
    """Блок restrictionTemplate в оформлении выгрузки."""
    return '\n'.join([
        f'{unit}<restrictionTemplate>',
        f'{unit * 2}<name>{esc_xml(name)}</name>',
        f'{unit * 2}<condition>{esc_xml(condition)}</condition>',
        f'{unit}</restrictionTemplate>',
    ])


def apply_template_op(text, op):
    """Добавление, замена или снятие шаблона. Совпадающий add ничего не меняет."""
    name = op_name(op)
    template = op_template_name(op)
    unit = indent_unit(text)
    found = find_templates(text)
    index = next((i for i, item in enumerate(found) if item['name'] == template), None)
    if name == 'remove-template':
        if index is None:
            return text
        return splice_span(text, found[index]['start'], found[index]['end'], None)
    condition = op_condition(op)
    if index is not None and found[index]['condition'] == condition:
        return text
    if name == 'add-template' and index is not None:
        add_input_error(f"шаблон '{template}' уже есть, для замены используйте set-template")
        return text
    block = render_template(template, condition, unit)
    if index is None:
        return insert_before_close(text, block, '/Rights')
    return splice_span(text, found[index]['start'], found[index]['end'], block)


def replace_synonym(text, value):
    """Меняет русский синоним, не трогая uuid и остальные языки."""
    pattern = re.compile(
        r'(<Synonym\b[^>]*>.*?<v8:lang>\s*ru\s*</v8:lang>\s*<v8:content>)(.*?)(</v8:content>)',
        re.DOTALL,
    )
    if not pattern.search(text):
        return None
    return pattern.sub(lambda match: match.group(1) + esc_xml(str(value)) + match.group(3), text, count=1)


def replace_comment(text, value):
    """Меняет комментарий роли. Пустая строка записывается пустым тегом."""
    escaped = esc_xml(str(value))
    if re.search(r'<Comment\s*/>', text):
        if escaped == '':
            return text
        return re.sub(r'<Comment\s*/>', f'<Comment>{escaped}</Comment>', text, count=1)
    if re.search(r'<Comment\b[^>]*>.*?</Comment>', text, re.DOTALL):
        if escaped == '':
            return re.sub(r'<Comment\b[^>]*>.*?</Comment>', '<Comment/>', text, count=1, flags=re.DOTALL)
        return re.sub(
            r'(<Comment\b[^>]*>)(.*?)(</Comment>)',
            lambda match: match.group(1) + escaped + match.group(3),
            text,
            count=1,
            flags=re.DOTALL,
        )
    return None


def replace_flag(text, tag, value):
    """Меняет текст признака роли в Rights.xml."""
    pattern = re.compile(rf'(<{tag}>)(\s*)(true|false)(\s*)(</{tag}>)')
    if not pattern.search(text):
        return None
    return pattern.sub(rf'\g<1>\g<2>{value}\g<4>\g<5>', text, count=1)


def apply_property_op(rights, meta, op):
    """Меняет синоним, комментарий или признак. Возвращает пару текстов."""
    key, _raw, value = op_property(op)
    if key in ('synonym', 'comment'):
        if key == 'synonym':
            updated = replace_synonym(meta, value)
        else:
            updated = replace_comment(meta, '' if value is None else value)
        if updated is None:
            add_input_error(f'{key}: в файле роли нет этого свойства')
            return rights, meta
        return rights, updated
    updated = replace_flag(rights, key, xml_bool(value))
    if updated is None:
        add_input_error(f'{key}: в Rights.xml нет этого признака')
        return rights, meta
    return updated, meta


def field_parent_name(object_name):
    """Имя объекта-владельца, если блок прав относится к реквизиту или табличной части."""
    parts = object_name.split('.')
    if len(parts) < 4:
        return ''
    for index in range(2, len(parts), 2):
        if parts[index] in ('Attribute', 'TabularSection', 'StandardAttribute'):
            return parts[0] + '.' + parts[1]
    return ''


def normalize_nested_defaults(text):
    """Приводит вложенные права к тому, что оставляет выгрузка платформы."""
    match = re.search(r'<setForAttributesByDefault>(.*?)</setForAttributesByDefault>', text)
    sfab = True if match is None else match.group(1).strip().lower() == 'true'
    unit = indent_unit(text)
    objects = find_objects(text)
    for obj in reversed(objects):
        if not is_nested_object(obj['name']):
            continue
        kept = [
            right for right in close_nested_view_edit(obj['name'], obj['rights'], sfab)
            if nested_default_right_kept(obj['name'], right['Name'], right['Value'], sfab, right.get('Condition'))
        ]
        if kept == obj['rights']:
            continue
        block = render_object(obj['name'], kept, unit) if kept else None
        text = splice_span(text, obj['start'], obj['end'], block)
    return text


def warn_fields_without_object(text):
    """Предупреждает, если при обычных флажках остались права на поля без прав на объект."""
    sfab_match = re.search(r'<setForAttributesByDefault>(.*?)</setForAttributesByDefault>', text)
    irco_match = re.search(
        r'<independentRightsOfChildObjects>(.*?)</independentRightsOfChildObjects>', text)
    sfab = True if sfab_match is None else sfab_match.group(1).strip().lower() == 'true'
    irco = False if irco_match is None else irco_match.group(1).strip().lower() == 'true'
    if not sfab or irco:
        return
    objects = find_objects(text)
    parents = {obj['name'] for obj in objects if not is_nested_object(obj['name'])}
    seen = set()
    for obj in objects:
        parent = field_parent_name(obj['name'])
        if not parent or parent in parents or parent in seen:
            continue
        seen.add(parent)
        print(
            f"WARNING: {parent}: права на поля без прав на объект при "
            "setForAttributesByDefault=true и independentRightsOfChildObjects=false (#std532)",
            file=sys.stderr,
        )


def apply_ops(rights, meta, ops):
    """Применяет операции по порядку. При ошибке тексты не считаются годными к записи."""
    for op in ops:
        name = op_name(op)
        if name in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls'):
            rights = apply_rights_op(rights, op)
        elif name in ('add-template', 'set-template', 'remove-template'):
            rights = apply_template_op(rights, op)
        elif name == 'modify-property':
            rights, meta = apply_property_op(rights, meta, op)
        if INPUT_ERRORS:
            break
    return rights, meta


def role_validate_script():
    """Путь к role-validate.py соседнего навыка."""
    base = os.path.dirname(os.path.abspath(__file__))
    for folder in ('1c-role-validate', 'role-validate'):
        candidate = os.path.normpath(os.path.join(base, '..', '..', folder, 'scripts', 'role-validate.py'))
        if os.path.isfile(candidate):
            return candidate
    return ''


def role_label(meta_text, meta_path):
    """Имя роли из метаданных, иначе из имени файла."""
    match = re.search(r'<Name>(.*?)</Name>', meta_text)
    if match:
        return match.group(1).strip()
    return os.path.splitext(os.path.basename(meta_path))[0]


def main():
    """Читает правку, проверяет ее и записывает измененные файлы роли."""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Точечная правка существующей роли 1С', allow_abbrev=False)
    parser.add_argument('-RolePath', required=True)
    parser.add_argument('-DefinitionFile', default=None)
    parser.add_argument('-Operation', default=None)
    parser.add_argument('-Object', default=None)
    parser.add_argument('-Rights', default=None)
    parser.add_argument('-Right', default=None)
    parser.add_argument('-Template', default=None)
    parser.add_argument('-Condition', default=None)
    parser.add_argument('-Property', default=None)
    parser.add_argument('-Value', default=None)
    parser.add_argument('-NoValidate', action='store_true')
    args = parser.parse_args()

    if args.DefinitionFile and args.Operation:
        stop_role_edit('-DefinitionFile и -Operation вместе не задают')
    if not args.DefinitionFile and not args.Operation:
        stop_role_edit('укажите -DefinitionFile или -Operation')

    if args.DefinitionFile:
        ops = load_operations(args.DefinitionFile)
    else:
        ops = [fold_op({
            'operation': args.Operation,
            'object': args.Object,
            'rights': args.Rights,
            'right': args.Right,
            'template': args.Template,
            'condition': args.Condition,
            'property': args.Property,
            'value': args.Value,
        })]
    validate_ops(ops)
    flush_errors()

    meta_path, rights_path = resolve_role_paths(args.RolePath)
    if not os.path.isfile(meta_path):
        stop_role_edit(f'файл роли не найден: {meta_path}')
    if not os.path.isfile(rights_path):
        stop_role_edit(f'файл прав не найден: {rights_path}')
    assert_edit_allowed(meta_path, 'editable')

    rights, rights_bom, rights_crlf = read_role_file(rights_path)
    meta, meta_bom, meta_crlf = read_role_file(meta_path)
    new_rights, new_meta = apply_ops(rights, meta, ops)
    if not INPUT_ERRORS:
        new_rights = normalize_nested_defaults(new_rights)
        warn_fields_without_object(new_rights)
    flush_errors()

    if new_rights != rights:
        write_text(rights_path, new_rights, rights_bom, rights_crlf)
    if new_meta != meta:
        write_text(meta_path, new_meta, meta_bom, meta_crlf)

    label = role_label(new_meta, meta_path)
    print(f'role-edit: {label}, операций {len(ops)}')

    if not args.NoValidate:
        script = role_validate_script()
        if script:
            print('--- role-validate ---')
            subprocess.run([sys.executable, script, '-RightsPath', rights_path])


main()
