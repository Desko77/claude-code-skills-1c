#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Линтер API-справочников скилов против реальной выгрузки конфигурации 1С.

Ищет в reference-файлах (markdown) токены вида `Модуль.Метод`, упомянутые
в бэктиках: inline-спаны (`КадровыйУчет.КадровыеДанныеСотрудников`) и вызовы
внутри fenced-блоков кода (КадровыйУчет.КадровыеДанныеСотрудников(...)).
Каждый токен сверяется с выгрузкой конфигурации:

  - общий модуль найден в выгрузке;
  - метод объявлен в модуле;
  - метод экспортный;
  - если рядом с токеном заявлена стабильность ("стабильный" / "служебный"),
    регион метода (#Область) соответствует заявлению.

Вердикты:
  ERROR  - модуль не найден / метод не найден / метод не экспортный /
           заявлен стабильным, а лежит вне отслеживаемых областей
  WARN   - заявлен стабильным, а лежит в служебном или устаревшем регионе
  INFO   - заявлен служебным, а лежит в ПрограммныйИнтерфейс

Проверяются только общие модули. Обращения к менеджерам объектов
(Документы.X, РегистрыСведений.X, ...), типам метаданных (Документ.X,
Справочник.X, ...), именам файлов (*.md, *.py) и методам платформенных
объектов на переменных (ЗапросВТ.Выполнить()) отфильтровываются.
Токен сразу после маркера "НЕТ" (конвенция справочника для намеренно
несуществующих методов: "НЕТ метода `X.Y()` - использовать `X.Z()`")
не проверяется как вызов, но проверяется КАК ОТРИЦАНИЕ: если заявленный
несуществующим модуль или метод на самом деле есть в выгрузке, это ошибка
FALSE_NEGATION_MODULE или FALSE_NEGATION_METHOD. Ложное отрицание вреднее
пропуска - оно уводит от работающего метода. Отрицание имени модуля целиком
("модуля `X` не существует") разбирается отдельной формой: точечной цепочки
там нет. Замена на той же строке проверяется как обычный вызов.

Использование:
  python tools/validate_api_reference.py --refs <файл-или-папка-md> --src <выгрузка> [--json]
  python tools/validate_api_reference.py --refs <файл-или-папка-md> --list [--json]

  --src   корень выгрузки конфигурации; поддержаны три раскладки - выгрузка
          Конфигуратора (CommonModules/<Модуль>/Ext/Module.bsl), EDT-проект
          (CommonModules/<Модуль>/Module.bsl) и распаковка v8unpack
          (CommonModule/<Модуль>/CommonModule.obj.bsl).
          Ключ можно повторять с префиксом версии, тогда действуют маркеры версии
          в тексте справочника:
            --src 3.1.11=<путь> --src 3.2.1=<путь>
          Вызов без маркера обязан найтись во ВСЕХ переданных выгрузках. Маркер
          `Модуль.Метод` [3.2.1] сверяет только с этой версией, а [нет в 3.1.11]
          требует отсутствия в названной версии и наличия в остальных.
  --list  без выгрузки: только извлечь и показать токены с фильтрами
          (визуальная проверка экстрактора)
  --json  машиночитаемый отчет вместо текстового

Пример (справочник ЗУП):
  python tools/validate_api_reference.py --refs "skills/zup-hr-api-reference/references" --src "C:/dumps/zup31"

Коды выхода: 0 - чисто; 1 - есть находки (ERROR/WARN); 2 - ошибка параметров.
"""
# Адаптация валидатора из brake71/1c-ssl-skills (MIT, (c) Чекменев Дмитрий Алексеевич)

import argparse
import json
import re
import sys
from pathlib import Path

# Принудительный UTF-8 для консоли Windows (по умолчанию cp866/cp1251, кириллица ломается)
for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if _reconf is not None:
        try:
            _reconf(encoding="utf-8")
        except (TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Регионы BSL-модулей (стабильность экспортного метода определяется регионом)
# ---------------------------------------------------------------------------

STABLE_REGION = "ПрограммныйИнтерфейс"
SERVICE_REGIONS = ("СлужебныйПрограммныйИнтерфейс", "СлужебныеПроцедурыИФункции")
DEPRECATED_REGION = "УстаревшиеПроцедурыИФункции"
OVERRIDE_REGIONS = ("ПереопределениеВызовов", "ПереопределениеТекстаЗапросаНабораДанных")

# Только значимые регионы отслеживаются по имени; прочие области - простая
# группировка, их методы наследуют регион родителя (см. парсер, проход 1).
_TRACKED_REGIONS = {STABLE_REGION, DEPRECATED_REGION, *SERVICE_REGIONS, *OVERRIDE_REGIONS}
TRACKED_REGIONS_LOWER = {name.lower(): name for name in _TRACKED_REGIONS}


# ---------------------------------------------------------------------------
# Фильтры ложных срабатываний
# ---------------------------------------------------------------------------

# Типы метаданных 1С: токены вида Документ.X / Справочник.X / InformationRegister.X
# описывают объекты метаданных, а не экспорт общего модуля. Список унаследован
# от оригинального валидатора (RU + EN формы).
METADATA_TYPE_PREFIXES = frozenset(name.lower() for name in (
    # английские формы (выгрузка конфигурации / английский API метаданных)
    "InformationRegister", "Constant", "ScheduledJob", "Catalog",
    "CatalogRef", "Document", "DocumentRef", "ChartOfCharacteristicTypes",
    "ChartOfCharacteristicTypesRef", "InformationRegisterRecord",
    "CatalogObject", "DocumentObject", "Enum", "EnumRef",
    "CatalogManager", "DocumentManager", "InformationRegisterManager",
    "ConstantManager", "ConstantValueManager", "Task", "TaskRef",
    "Sequence", "SequenceRecord", "ExchangePlan", "ExchangePlanRef",
    "CalculationRegister", "CalculationRegisterRecord",
    "AccumulationRegister", "AccumulationRegisterRecord",
    "AccountingRegister", "AccountingRegisterRecord",
    "ChartOfCalculationTypes", "ChartOfCalculationTypesRef",
    "BusinessProcess", "BusinessProcessRef", "BusinessProcessObject",
    "BusinessProcessRoute", "BusinessProcessRoutePoint",
    "CatalogSelection", "DocumentSelection", "InformationRegisterSelection",
    "CommonForm", "CommonTemplate", "CommonModule", "CommonPicture",
    "CommonAttribute", "FilterTemplate", "DataProcessor", "Report",
    "SettingsStorage", "Cube", "CubeDimensionTable", "Table",
    "Characteristic", "ExternalDataProcessor", "ExternalReport",
    "HTTPService", "WebService", "Bot",
    # русские формы (русский API платформы 1С:Предприятие)
    "РегистрСведений", "РегистрНакопления", "РегистрБухгалтерии",
    "РегистрРасчета", "Константа", "РегламентноеЗадание",
    "Справочник", "СправочникСсылка", "СправочникОбъект",
    "СправочникМенеджер", "СправочникНаборЗаписей", "СправочникВыборка",
    "Документ", "ДокументСсылка", "ДокументОбъект", "ДокументМенеджер",
    "ДокументВыборка", "ДокументНаборЗаписей",
    "ПланВидовХарактеристик", "ПланВидовХарактеристикСсылка",
    "ПланВидовРасчета", "ПланВидовРасчетаСсылка",
    "ПланСчетов", "ПланСчетовСсылка",
    "ПланОбмена", "ПланОбменаСсылка",
    "Перечисление", "ПеречислениеСсылка",
    "Последовательность", "ПоследовательностьНаборЗаписей",
    "Перерасчет", "БизнесПроцесс", "БизнесПроцессСсылка",
    "БизнесПроцессОбъект", "Задача", "ЗадачаСсылка", "ЗадачаОбъект",
    "ОбщаяФорма", "ОбщийМакет", "ОбщийМодуль", "ОбщаяКартинка",
    "ОбщийРеквизит", "ОбработкаВыбор", "Отчет", "Обработка",
    "ХранилищеНастроек", "Куб", "ТаблицаИзмерений", "Таблица",
    "Характеристика", "ВнешняяОбработка", "ВнешнийОтчет",
    "HTTPСервис", "WebСервис", "Бот",
    "ФункциональнаяОпция", "ПараметрСеанса", "КритерийОтбора",
    "ПодпискаНаСобытие", "РегламентноеЗаданиеМенеджер",
    "РегистрСведенийМенеджер", "РегистрСведенийВыборка",
    "РегистрСведенийНаборЗаписей", "РегистрСведенийЗапись",
    "РегистрНакопленияМенеджер", "РегистрНакопленияВыборка",
    "РегистрНакопленияНаборЗаписей", "РегистрНакопленияЗапись",
    "ОпределяемыйТип", "Метаданные",
))

# Менеджеры объектов из глобального контекста (множественные формы):
# Документы.ПереносДанных.СоздатьДокумент(), РегистрыСведений.X.Метод() и т.п.
# Это не общие модули - валидатор их пропускает.
MANAGER_PREFIXES = frozenset(name.lower() for name in (
    # русские формы
    "Документы", "Справочники", "РегистрыСведений", "РегистрыНакопления",
    "РегистрыРасчета", "РегистрыБухгалтерии", "Перечисления",
    "ПланыВидовРасчета", "ПланыВидовХарактеристик", "ПланыСчетов",
    "ПланыОбмена", "Обработки", "Отчеты", "Константы", "БизнесПроцессы",
    "Задачи", "ВнешниеОбработки", "ВнешниеОтчеты", "Последовательности",
    "ХранилищаНастроек", "ПараметрыСеанса", "HTTPСервисы", "WebСервисы",
    # Менеджеры платформы без объекта метаданных: обращение к ним выглядит как
    # вызов общего модуля, но общим модулем не является. Поймано на справочнике
    # регламентных заданий: антипаттерн "не звать РегламентныеЗадания.НайтиРегламентныеЗадания
    # платформы напрямую" валидатор принимал за ссылку на несуществующий модуль БСП.
    "РегламентныеЗадания", "ФоновыеЗадания", "ПланыОбменаМенеджер",
    "ScheduledJobs", "BackgroundJobs",
    # английские формы
    "Documents", "Catalogs", "InformationRegisters", "AccumulationRegisters",
    "CalculationRegisters", "AccountingRegisters", "Enums",
    "ChartsOfCalculationTypes", "ChartsOfCharacteristicTypes",
    "ChartsOfAccounts", "ExchangePlans", "DataProcessors", "Reports",
    "Constants", "BusinessProcesses", "Tasks", "ExternalDataProcessors",
    "ExternalReports", "Sequences", "SettingsStorages", "SessionParameters",
    "HTTPServices", "WebServices",
))

# Расширения файлов: токен вида prefixes.md / bsp_api.py - ссылка на файл,
# а не метод (страховка; такие токены обычно отсекает и требование заглавной
# буквы у метода).
FILE_EXTENSIONS = frozenset((
    "md", "bsl", "xml", "json", "py", "txt", "html", "htm", "yml", "yaml",
    "jpeg", "jpg", "png", "gif", "svg", "csv", "tsv", "log", "epf", "erf",
    "mdo", "form", "cf", "cfe", "dt", "mxl", "ps1", "cmd", "bat",
))

# Методы платформенных объектов: в примерах кода вызовы на переменных
# (ЗапросВТ.Выполнить(), ДокПеренос.Записать()) синтаксически неотличимы от
# вызова общего модуля. Токен с таким именем метода пропускается - иначе
# ложное "модуль не найден" на каждой переменной.
PLATFORM_OBJECT_METHODS = frozenset(name.lower() for name in (
    "Выполнить", "ВыполнитьПакет", "Записать", "Прочитать", "Загрузить",
    "Выгрузить", "ВыгрузитьКолонку", "Добавить", "Вставить", "Удалить",
    "Очистить", "Свернуть", "Скопировать", "Найти", "НайтиСтроки",
    "НайтиПоЗначению", "УстановитьПараметр", "Провести", "ОтменитьПроведение",
    "ПолучитьОбъект", "Разблокировать", "Заблокировать",
    "Следующий", "Выбрать", "Количество", "Получить",
    "Execute", "ExecuteBatch", "Write", "Read", "Load", "Unload",
    "UnloadColumn", "Add", "Insert", "Delete", "Clear", "GroupBy", "Copy",
    "Find", "FindRows", "FindByValue", "SetParameter", "Post", "UndoPosting",
    "GetObject", "Unlock", "Lock",
    "Next", "Select", "Count", "Get",
))

# Категории отфильтрованных токенов (для --list и статистики)
CAT_METADATA = "тип метаданных"
CAT_MANAGER = "менеджер объектов"
CAT_CHAIN = "цепочка 3+ сегментов"
CAT_FILE = "имя файла"
CAT_PLATFORM = "метод платформенного объекта"
CAT_NEGATED = "заявлен несуществующим (НЕТ ...)"

# Маркер намеренно несуществующего метода: слово "НЕТ" (заглавными) перед
# токеном без других бэктиков между маркером и токеном. Конвенция разделов
# "частые ошибки": "- НЕТ метода `X.Y()` - использовать `X.Z()`".
RE_NEGATION_BEFORE = re.compile(r"(?<!\w)НЕТ(?!\w)[^`]*$")

# Негация ПОСЛЕ токена в той же строке: "Метода `X.Y` в БСП нет",
# "`X.Y` не существует". Срабатывает, если маркер стоит правее токена.
RE_NEGATION_AFTER = re.compile(r"в БСП нет|не существует|does not exist",
                               re.IGNORECASE)

# Таблица несуществующих методов: заголовок с "НЕ СУЩЕСТВУЕТ" -> в строках
# таблицы токены ПЕРВОЙ ячейки заявлены несуществующими, остальные валидируются.
RE_NEG_TABLE_HEADER = re.compile(r"НЕ\s+СУЩЕСТВУ", re.IGNORECASE)

# Отрицание имени МОДУЛЯ целиком, без метода: "модуля `РегламентныеЗадания` не
# существует", "модуль `X` НЕ существует как общий модуль". Точечные цепочки
# ловятся общим разбором, а одиночное имя в бэктиках им не покрывается: без
# этой формы самая частая и полезная запись отрицательного знания не проверялась.
RE_NEG_MODULE = re.compile(
    r"модул[ьяе]\w*\s+`([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*)`"
    r"[^`\n]{0,80}?(?:не\s+существует|НЕ\s+СУЩЕСТВУ|в\s+БСП\s+нет)",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Извлечение токенов из markdown
# ---------------------------------------------------------------------------

# Сегмент идентификатора: с заглавной буквы (кириллица/латиница), далее буквы,
# цифры, подчеркивание. Требование заглавной буквы отсекает имена файлов
# (bsp_api.py) и большинство не-BSL конструкций.
_SEG = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*"

# Inline-спан целиком: `Модуль.Метод`, `Модуль.Метод()` или `Модуль.Метод(...)`.
# Якорный матч всего спана отсекает выражения (`Поле = Объект.Поле`) и
# фрагменты с многоточием (`...ФизическихЛиц()`).
RE_SPAN = re.compile(r"`([^`\n]+)`")
# Хвост "Экспорт" после сигнатуры разрешен: справочник прикладных сценариев пишет
# вызов ПОЛНОЙ сигнатурой, `Модуль.Метод(Знач А = Неопределено) Экспорт`, и без
# этого хвоста такие строки не разбирались вовсе. Поймано на живом справочнике:
# валидатор отчитывался нулем ошибок, не проверив ни одной сигнатуры, а имя хука
# в тексте было выдумано по памяти.
RE_SPAN_TOKEN = re.compile(
    r"^(" + _SEG + r"(?:\." + _SEG + r")+)[ \t]*(\(.*\))?"
    r"(?:[ \t]+(?:Экспорт|Export))?$", re.IGNORECASE)

# Вызов в fenced-блоке кода: полная точечная цепочка непосредственно перед
# открывающей скобкой. Lookbehind запрещает старт в середине идентификатора
# или после точки (иначе из Документы.X.СоздатьДокумент( вырезался бы хвост).
RE_CODE_CALL = re.compile(
    r"(?<![\w.])(" + _SEG + r"(?:\." + _SEG + r")+)[ \t]*\(")

# Ограждение fenced-блока: ``` или ~~~ в начале строки
RE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

# Маркер версии после упоминания вызова: `Модуль.Метод` [3.2.1] - вызов есть только
# в этой версии; [нет в 3.1.11] - вызова в этой версии нет. Отсутствие маркера
# утверждает, что вызов есть во ВСЕХ проверяемых версиях.
RE_VERSION_MARK = re.compile(
    r"\[\s*(нет\s+в\s+)?(\d+\.\d+(?:\.\d+)*)\s*\]", re.IGNORECASE)


def version_mark(line_text, after_pos):
    """Достать маркер версии, стоящий в строке ПРАВЕЕ упоминания вызова.

    Возвращает пару (версия, отрицание) либо None. Маркер ищется только правее
    токена: слева от него в строке может стоять чужой маркер соседнего вызова.
    """
    m = RE_VERSION_MARK.search(line_text, after_pos)
    return (m.group(2), bool(m.group(1))) if m else None

# Маркеры заявленной стабильности в строке с токеном. Приоритет у "служебный":
# строка "служебный, не стабильный" трактуется как заявка на служебный.
_UNSTABLE_SUBSTRINGS = ("служебн", "нестабильн")
_STABLE_SUBSTRING = "стабильн"


def declared_stability(line_text, in_code):
    """Заявленная стабильность из текста строки с токеном.

    True = заявлен стабильным, False = заявлен служебным/нестабильным,
    None = стабильность не заявлена (проверяется только существование).

    Имена методов сами содержат слова-маркеры (СлужебнаяФункция), поэтому
    сканируется только описательный текст: в прозе - строка без бэктик-спанов,
    в коде - только комментарий после //.
    """
    if in_code:
        comment_pos = line_text.find("//")
        scan = line_text[comment_pos + 2:] if comment_pos >= 0 else ""
    else:
        scan = re.sub(r"`[^`\n]*`", " ", line_text)
    low = scan.lower()
    if any(sub in low for sub in _UNSTABLE_SUBSTRINGS):
        return False
    if _STABLE_SUBSTRING in low:
        return True
    return None


def classify_chain(segments):
    """Категория фильтрации для точечной цепочки или None, если токен принят.

    Порядок проверок: сначала известные префиксы (метаданные, менеджеры) -
    они закрывают и цепочки из 3+ сегментов; затем длина цепочки; затем
    фильтры по имени метода.
    """
    module_low = segments[0].lower()
    if module_low in METADATA_TYPE_PREFIXES:
        return CAT_METADATA
    if module_low in MANAGER_PREFIXES:
        return CAT_MANAGER
    if len(segments) != 2:
        return CAT_CHAIN
    method_low = segments[1].lower()
    if method_low in FILE_EXTENSIONS:
        return CAT_FILE
    if method_low in PLATFORM_OBJECT_METHODS:
        return CAT_PLATFORM
    return None


def extract_file_tokens(md_path):
    """Извлечь токены Модуль.Метод из markdown-файла.

    Возвращает (accepted, skipped):
      accepted - список словарей {file, line, module, method, token, declared}
      skipped  - список словарей {file, line, token, category}

    Правила: вне fenced-блоков разбираются только inline-спаны с якорным
    полным совпадением; внутри fenced-блоков - только цепочки с открывающей
    скобкой (вызовы).
    """
    accepted = []
    skipped = []
    text = md_path.read_text(encoding="utf-8-sig", errors="replace")
    in_fence = False
    neg_table = False  # внутри таблицы "НЕ СУЩЕСТВУЕТ | Использовать"
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if RE_FENCE.match(raw):
            in_fence = not in_fence
            continue
        stripped = raw.lstrip()
        if not in_fence:
            if "|" in raw and RE_NEG_TABLE_HEADER.search(raw):
                neg_table = True
            elif neg_table and not stripped.startswith("|"):
                neg_table = False
        # граница первой ячейки для строк neg-таблицы
        cell1_end = -1
        if neg_table and stripped.startswith("|"):
            first_pipe = raw.find("|")
            cell1_end = raw.find("|", first_pipe + 1)
        chains = []  # пары (цепочка, позиция начала в строке)
        if in_fence:
            for m in RE_CODE_CALL.finditer(raw):
                chains.append((m.group(1), m.start(1)))
        else:
            for m in RE_SPAN.finditer(raw):
                tm = RE_SPAN_TOKEN.match(m.group(1).strip())
                if tm:
                    chains.append((tm.group(1), m.start()))
        # Отрицание имени модуля целиком разбирается до цепочек: у него своя
        # форма, в общий разбор Модуль.Метод оно не попадает.
        for nm in RE_NEG_MODULE.finditer(raw):
            skipped.append({
                "file": str(md_path), "line": lineno,
                "token": nm.group(1), "category": CAT_NEGATED,
                "module": nm.group(1), "method": None,
            })

        for chain, start_pos in chains:
            segments = chain.split(".")
            category = classify_chain(segments)
            if category is None and RE_NEGATION_BEFORE.search(raw[:start_pos]):
                category = CAT_NEGATED
            if category is None and cell1_end >= 0 and start_pos < cell1_end:
                category = CAT_NEGATED
            if category is None:
                neg_after = RE_NEGATION_AFTER.search(raw)
                if neg_after and neg_after.start() > start_pos:
                    category = CAT_NEGATED
            if category is not None:
                entry = {
                    "file": str(md_path), "line": lineno,
                    "token": chain, "category": category,
                }
                # Отрицательное утверждение - тоже утверждение, и оно бывает ложным.
                # Раньше такой токен просто выпадал из проверки, поэтому запись
                # "метода X нет" не падала, когда X существует. Разбор сохраняется,
                # чтобы валидация могла его подтвердить.
                if category == CAT_NEGATED and len(segments) == 2:
                    entry["module"] = segments[0]
                    entry["method"] = segments[1]
                skipped.append(entry)
                continue
            accepted.append({
                "file": str(md_path), "line": lineno,
                "module": segments[0], "method": segments[1],
                "token": segments[0] + "." + segments[1],
                "declared": declared_stability(raw, in_fence),
                "version": version_mark(raw, start_pos + len(chain)),
            })
    return accepted, skipped


def collect_reference_files(refs_path):
    """Список markdown-файлов по пути --refs (файл или папка, рекурсивно)."""
    p = Path(refs_path)
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(p.rglob("*.md"))
    return []


# ---------------------------------------------------------------------------
# Парсер BSL-модуля: два прохода (регионы, затем объявления методов)
# ---------------------------------------------------------------------------

RE_METHOD_DECL = re.compile(
    r"^\s*(?:Асинх\s+|Async\s+)?(Функция|Процедура|Function|Procedure)\s+(\w+)\s*\(",
    re.IGNORECASE)
RE_EXPORT_WORD = re.compile(r"\b(?:Экспорт|Export)\b", re.IGNORECASE)
RE_EXPORT_LEAD = re.compile(r"^(?:Экспорт|Export)\b", re.IGNORECASE)

# Окно поиска конца многострочной сигнатуры (строк от объявления)
_SIGNATURE_WINDOW = 40


def _region_open_name(stripped_line):
    """Имя региона, если строка открывает #Область / #Region, иначе None."""
    low = stripped_line.lower()
    for keyword in ("#область", "#region"):
        if low.startswith(keyword):
            return stripped_line[len(keyword):].strip()
    return None


def _region_close(stripped_line):
    """True, если строка закрывает регион (#КонецОбласти / #EndRegion)."""
    low = stripped_line.lower()
    return low.startswith("#конецобласти") or low.startswith("#endregion")


def parse_bsl_methods(bsl_path):
    """Разобрать Module.bsl: все методы модуля с регионом и признаком экспорта.

    Возвращает словарь: имя_метода_в_нижнем_регистре -> {name, region, is_export}.

    Проход 1: регион каждой строки через стек #Область; вложенные области
    с неотслеживаемыми именами наследуют регион родителя.
    Проход 2: объявления Функция/Процедура; экспортность определяется по
    слову Экспорт на строке закрытия скобки сигнатуры (баланс скобок) либо
    на следующей непустой строке (стиль "Экспорт с новой строки").

    Чтение в utf-8-sig: выгрузки 1С пишут Module.bsl в UTF-8 c BOM.
    """
    text = bsl_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    n = len(lines)

    # Проход 1: регион на строку
    region_per_line = [None] * n
    stack = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        opened = _region_open_name(stripped)
        if opened is not None:
            tracked = TRACKED_REGIONS_LOWER.get(opened.lower())
            # Неотслеживаемая область наследует регион родителя (или None)
            stack.append(tracked if tracked is not None else (stack[-1] if stack else None))
        elif _region_close(stripped):
            if stack:
                stack.pop()
        else:
            region_per_line[i] = stack[-1] if stack else None

    # Проход 2: объявления методов
    methods = {}
    i = 0
    while i < n:
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("&"):
            i += 1
            continue
        decl = RE_METHOD_DECL.match(lines[i])
        if decl is None:
            i += 1
            continue
        method_name = decl.group(2)
        region = region_per_line[i]

        # Найти строку закрытия скобки сигнатуры по балансу скобок
        depth = lines[i].count("(") - lines[i].count(")")
        closing_idx = i
        if depth > 0:
            for j in range(i + 1, min(i + _SIGNATURE_WINDOW, n)):
                depth += lines[j].count("(") - lines[j].count(")")
                closing_idx = j
                if depth <= 0:
                    break

        is_export = bool(RE_EXPORT_WORD.search(lines[closing_idx]))
        if not is_export:
            # Стиль "Экспорт на отдельной строке после закрывающей скобки"
            for j in range(closing_idx + 1, min(closing_idx + 3, n)):
                peek = lines[j].strip()
                if not peek or peek.startswith("//"):
                    continue
                is_export = bool(RE_EXPORT_LEAD.match(peek))
                break

        key = method_name.lower()
        prev = methods.get(key)
        if prev is None:
            methods[key] = {"name": method_name, "region": region, "is_export": is_export}
        else:
            # Дубль объявления (условная компиляция #Если): экспортная версия
            # и стабильный регион имеют приоритет
            if is_export and not prev["is_export"]:
                methods[key] = {"name": method_name, "region": region, "is_export": True}
            elif is_export == prev["is_export"] and region == STABLE_REGION:
                prev["region"] = region
        i = closing_idx + 1
    return methods


# ---------------------------------------------------------------------------
# Индекс общих модулей выгрузки
# ---------------------------------------------------------------------------

# Каталог с общими модулями и имена файлов модуля - по раскладкам.
# Конфигуратор и EDT кладут модули в CommonModules/, распаковка v8unpack - в
# CommonModule/ (единственное число) и называет файл CommonModule.obj.bsl.
LAYOUTS = (
    ("CommonModules", ("Ext/Module.bsl", "Module.bsl")),
    ("CommonModule", ("CommonModule.obj.bsl",)),
)


def resolve_src_root(src_arg):
    """Корень с каталогом общих модулей: сам путь либо подпапка src/ (EDT-проект).

    Возвращает пару (корень, имя каталога модулей) либо None. Имя каталога
    возвращается вместе с корнем, потому что дальше оно нужно построению
    индекса, а определять раскладку дважды - расходиться в трактовке.
    """
    p = Path(src_arg)
    for dir_name, _files in LAYOUTS:
        if (p / dir_name).is_dir():
            return p, dir_name
        if (p / "src" / dir_name).is_dir():
            return p / "src", dir_name
    return None


def build_module_index(src_root, dir_name="CommonModules"):
    """Индекс общих модулей: имя_в_нижнем_регистре -> (имя, путь к файлу модуля).

    Поддержаны три раскладки: выгрузка Конфигуратора (<Модуль>/Ext/Module.bsl),
    EDT-проект (<Модуль>/Module.bsl) и распаковка v8unpack
    (CommonModule/<Модуль>/CommonModule.obj.bsl).
    """
    index = {}
    candidates = dict(LAYOUTS).get(dir_name, ("Ext/Module.bsl", "Module.bsl"))
    cm_dir = Path(src_root) / dir_name
    for entry in sorted(cm_dir.iterdir()):
        if not entry.is_dir():
            continue
        for rel in candidates:
            candidate = entry.joinpath(*rel.split("/"))
            if candidate.is_file():
                index[entry.name.lower()] = (entry.name, candidate)
                break
    return index


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

def _merge_declared(values):
    """Свести заявления стабильности от нескольких упоминаний токена.

    Если все ненулевые заявления совпадают - вернуть его; при противоречии
    или отсутствии - None (проверка региона пропускается).
    """
    distinct = {v for v in values if v is not None}
    return distinct.pop() if len(distinct) == 1 else None


def validate_negations(skipped, module_index, parse_cache):
    """Проверить, что заявленные несуществующими модули и методы правда отсутствуют.

    Отрицательное знание - половина ценности справочника: запись "модуля X нет,
    механизм лежит в Y" удерживает от выдуманного вызова. Но ложное отрицание
    вреднее пропуска: оно уводит от РАБОТАЮЩЕГО метода. Поэтому проверяется в
    обе стороны.

    Разбираются две формы: отрицание пары Модуль.Метод и отрицание имени модуля
    целиком. Токены прочих категорий (менеджеры, типы метаданных, имена файлов)
    пропускаются: они и не заявляют отсутствия.
    """
    findings = []
    seen = set()
    for occ in skipped:
        if occ.get("category") != CAT_NEGATED or "module" not in occ:
            continue
        module, method = occ["module"], occ.get("method")
        key = (occ["file"], module.lower(), (method or "").lower())
        if key in seen:
            continue
        seen.add(key)

        entry = module_index.get(module.lower())
        if entry is None:
            continue  # модуля правда нет, утверждение верно
        real_module, bsl_path = entry

        if method is None:
            findings.append({
                "file": occ["file"], "lines": [occ["line"]], "token": module,
                "severity": "ERROR", "code": "FALSE_NEGATION_MODULE",
                "message": "заявлен несуществующим, но общий модуль '%s' есть в выгрузке"
                           % real_module,
            })
            continue

        if real_module not in parse_cache:
            parse_cache[real_module] = parse_bsl_methods(bsl_path)
        if method.lower() in parse_cache[real_module]:
            findings.append({
                "file": occ["file"], "lines": [occ["line"]],
                "token": module + "." + method,
                "severity": "ERROR", "code": "FALSE_NEGATION_METHOD",
                "message": "заявлен несуществующим, но метод объявлен в модуле (%s)"
                           % bsl_path,
            })
    return findings


def load_api_index(path):
    """Загрузить справочник API БСП: (Модуль.Метод в нижнем регистре) -> запись.

    Нужен для проверок, которые по исходникам не делаются: устаревание вызова -
    наше курируемое знание, в тексте модуля его нет. Возвращает пустой словарь,
    если файла нет: справочник не обязателен, без него проверка просто не идет.
    """
    index = {}
    p = Path(path)
    if not p.is_file():
        return index
    with p.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            module, name = record.get("m"), record.get("n")
            if module and name and module != "?":
                index["%s.%s" % (module.lower(), name.lower())] = record
    return index


def validate_against_index(accepted, api_index):
    """Прогнать вызовы справочника через индекс API и вернуть находки.

    Проверяется то, чего не видно в исходниках модуля: помечен ли вызов
    устаревшим. Инвариант "ни один вызов не попадает в справочник без проверки"
    без этого прохода оставался бы пожеланием - проверка шла бы поштучно и
    вручную, а значит непредсказуемо.
    """
    findings = []
    seen = set()
    for occ in accepted:
        key = (occ["file"], occ["token"].lower())
        if key in seen:
            continue
        seen.add(key)
        record = api_index.get(occ["token"].lower())
        if record is None:
            continue  # отсутствие в индексе ловит сверка с исходниками
        dep = record.get("dep")
        if dep:
            findings.append({
                "file": occ["file"], "lines": [occ["line"]], "token": occ["token"],
                "severity": "WARN", "code": "DEPRECATED_CALL",
                "message": "устаревший вызов, вместо него %s" % dep,
            })
    return findings


def validate_versioned(accepted, skipped, sources):
    """Сверить вызовы с выгрузками по маркерам версии.

    Правила, заданные форматом маркера:
      - вызов БЕЗ маркера утверждает, что есть во всех версиях, и потому
        проверяется по КАЖДОЙ выгрузке;
      - вызов с маркером `[3.2.1]` проверяется только по выгрузке этой версии;
        если такой выгрузки не передали, проверка по нему пропускается;
      - вызов с маркером `[нет в 3.1.11]` проверяется НАОБОРОТ: он обязан
        отсутствовать в названной версии и присутствовать в остальных.

    Одна выгрузка без префикса версии сохраняет прежнее поведение: маркеры при
    ней не действуют, потому что сверять их не с чем.
    """
    versions = [v for v in sources if v is not None]
    findings = []

    def check_in(version, occs):
        src = sources.get(version) or sources.get(None)
        if src is None:
            return []
        return validate_tokens(occs, src["index"], src["cache"])

    # Без маркера: сверяем по всем выгрузкам, дубли находок схлопываем.
    plain = [o for o in accepted if not o.get("version")]
    seen = set()
    for version in (versions or [None]):
        for f in check_in(version, plain):
            key = (f["file"], f["token"], f["code"])
            if key in seen:
                continue
            seen.add(key)
            if versions:
                f["message"] += " (версия %s)" % version
            findings.append(f)

    for occ in accepted:
        mark = occ.get("version")
        if not mark:
            continue
        version, negated = mark
        if version not in sources:
            continue  # выгрузки этой версии не передали, сверять не с чем
        if not negated:
            findings += check_in(version, [occ])
            continue
        # "нет в <версия>": наличие вызова там - ошибка, отсутствие в остальных тоже.
        src = sources[version]
        entry = src["index"].get(occ["module"].lower())
        if entry is not None:
            real_module, bsl_path = entry
            if real_module not in src["cache"]:
                src["cache"][real_module] = parse_bsl_methods(bsl_path)
            if occ["method"].lower() in src["cache"][real_module]:
                findings.append({
                    "file": occ["file"], "lines": [occ["line"]], "token": occ["token"],
                    "severity": "ERROR", "code": "FALSE_VERSION_NEGATION",
                    "message": "помечен как отсутствующий в %s, но там объявлен" % version,
                })
        for other in versions:
            if other != version:
                findings += check_in(other, [occ])

    findings += validate_negations(
        skipped, next(iter(sources.values()))["index"],
        next(iter(sources.values()))["cache"])
    return findings


def validate_tokens(accepted, module_index, parse_cache=None):
    """Сверить принятые токены с индексом модулей выгрузки.

    Возвращает список находок: {file, lines, token, severity, code, message}.
    Токены группируются по (файл, модуль, метод); модуль парсится один раз.
    Кэш разбора модулей принимается снаружи, чтобы проверка отрицаний не
    разбирала те же файлы повторно.
    """
    findings = []
    if parse_cache is None:
        parse_cache = {}

    groups = {}
    for occ in accepted:
        key = (occ["file"], occ["module"].lower(), occ["method"].lower())
        groups.setdefault(key, []).append(occ)

    for (file_path, module_low, _method_low), occs in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[1][0]["line"])):
        first = occs[0]
        token = first["token"]
        lines = sorted({o["line"] for o in occs})
        declared = _merge_declared(o["declared"] for o in occs)

        def add(severity, code, message):
            findings.append({
                "file": file_path, "lines": lines, "token": token,
                "severity": severity, "code": code, "message": message,
            })

        entry = module_index.get(module_low)
        if entry is None:
            add("ERROR", "MODULE_NOT_FOUND",
                "общий модуль '%s' не найден в выгрузке" % first["module"])
            continue
        real_module, bsl_path = entry
        if real_module not in parse_cache:
            parse_cache[real_module] = parse_bsl_methods(bsl_path)
        methods = parse_cache[real_module]

        info = methods.get(first["method"].lower())
        if info is None:
            add("ERROR", "METHOD_NOT_FOUND",
                "метод '%s' не найден в модуле (%s)" % (token, bsl_path))
            continue
        if not info["is_export"]:
            add("ERROR", "METHOD_NOT_EXPORT",
                "метод '%s' найден, но не экспортный" % token)
            continue

        # Существование подтверждено; регион сверяется только при заявленной
        # стабильности (основная защита от галлюцинаций уже отработала)
        if declared is None:
            continue
        region = info["region"]
        actually_stable = (region == STABLE_REGION)
        if declared and not actually_stable:
            severity = "ERROR" if region is None else "WARN"
            region_label = region or "вне отслеживаемых областей"
            add(severity, "STABILITY_MISMATCH",
                "заявлен стабильным, но лежит в регионе '%s'" % region_label)
        elif not declared and actually_stable:
            add("INFO", "OVERLY_CONSERVATIVE",
                "заявлен служебным, но лежит в '%s'" % STABLE_REGION)
    return findings


# ---------------------------------------------------------------------------
# Отчеты
# ---------------------------------------------------------------------------

def _fmt_lines(lines):
    return ", ".join(str(x) for x in lines)


def render_list_report(per_file):
    """Текстовый отчет режима --list: принятые токены и фильтрация по файлам."""
    out = []
    total_accepted = 0
    total_unique = 0
    total_skipped = 0
    for file_path, (accepted, skipped) in per_file.items():
        out.append("=== %s ===" % file_path)
        by_token = {}
        for occ in accepted:
            by_token.setdefault(occ["token"], []).append(occ["line"])
        total_accepted += len(accepted)
        total_unique += len(by_token)
        out.append("Принятые токены: %d уникальных (%d упоминаний)"
                   % (len(by_token), len(accepted)))
        for token in sorted(by_token):
            out.append("  %-75s строки: %s" % (token, _fmt_lines(sorted(by_token[token]))))
        if skipped:
            total_skipped += len(skipped)
            out.append("Отфильтровано: %d" % len(skipped))
            by_cat = {}
            for item in skipped:
                by_cat.setdefault(item["category"], []).append(item)
            for cat in sorted(by_cat):
                out.append("  [%s]" % cat)
                for item in by_cat[cat]:
                    out.append("    %-73s строка %d" % (item["token"], item["line"]))
        out.append("")
    out.append("--- Итог ---")
    out.append("Файлов: %d; принято: %d уникальных (%d упоминаний); отфильтровано: %d"
               % (len(per_file), total_unique, total_accepted, total_skipped))
    return "\n".join(out)


def render_validation_report(per_file, findings, module_count):
    """Текстовый отчет валидации: находки в формате файл:строка + сводка."""
    out = []
    findings_by_file = {}
    for f in findings:
        findings_by_file.setdefault(f["file"], []).append(f)

    checked_unique = 0
    checked_total = 0
    for file_path, (accepted, _skipped) in per_file.items():
        unique = {(o["module"].lower(), o["method"].lower()) for o in accepted}
        checked_unique += len(unique)
        checked_total += len(accepted)
        file_findings = findings_by_file.get(file_path, [])
        out.append("=== %s === (токенов: %d уникальных / %d упоминаний)"
                   % (file_path, len(unique), len(accepted)))
        if not file_findings:
            out.append("  OK")
        else:
            for f in sorted(file_findings, key=lambda x: x["lines"][0]):
                out.append("  %s:%d: [%s] %s - %s"
                           % (f["file"], f["lines"][0], f["severity"],
                              f["token"], f["message"]))
                if len(f["lines"]) > 1:
                    out.append("      также упоминается: строки %s"
                               % _fmt_lines(f["lines"][1:]))
        out.append("")

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    warns = sum(1 for f in findings if f["severity"] == "WARN")
    infos = sum(1 for f in findings if f["severity"] == "INFO")
    out.append("--- Итог ---")
    out.append("Общих модулей в выгрузке: %d" % module_count)
    out.append("Токенов проверено: %d уникальных (%d упоминаний)"
               % (checked_unique, checked_total))
    out.append("  ERROR: %d" % errors)
    out.append("  WARN:  %d" % warns)
    out.append("  INFO:  %d" % infos)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description="Линтер API-справочников против выгрузки конфигурации 1С "
                    "(проверка токенов Модуль.Метод)")
    parser.add_argument("--refs", required=True,
                        help="reference-файл .md или папка с ними (рекурсивно)")
    parser.add_argument("--src", default=None, action="append",
                        help="корень выгрузки конфигурации; можно повторять с префиксом "
                             "версии: --src 3.1.11=<путь> --src 3.2.1=<путь>")
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="только извлечь и показать токены (без сверки с выгрузкой)")
    parser.add_argument("--index", default=None,
                        help="справочник API БСП (bsp-api.jsonl) для проверки на "
                             "устаревание вызовов; по умолчанию берется из набора")
    parser.add_argument("--json", action="store_true",
                        help="отчет в формате JSON")
    args = parser.parse_args()

    md_files = collect_reference_files(args.refs)
    if not md_files:
        print("Ошибка: --refs не найден или не содержит .md: %s" % args.refs,
              file=sys.stderr)
        sys.exit(2)

    per_file = {}
    for md in md_files:
        accepted, skipped = extract_file_tokens(md)
        if accepted or skipped:
            per_file[str(md)] = (accepted, skipped)

    if args.list_only:
        if args.json:
            payload = {
                "mode": "list",
                "files": {
                    fp: {"accepted": acc, "skipped": skp}
                    for fp, (acc, skp) in per_file.items()
                },
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_list_report(per_file))
        sys.exit(0)

    if not args.src:
        print("Ошибка: нужен --src <выгрузка> (или --list для извлечения без сверки)",
              file=sys.stderr)
        sys.exit(2)
    # Выгрузок может быть несколько, каждая со своей версией библиотеки.
    # Без префикса версия считается "любой" - это прежнее поведение с одним --src.
    sources = {}
    for raw_src in args.src:
        version, _, path = raw_src.partition("=")
        if not path:
            version, path = None, raw_src
        resolved = resolve_src_root(path)
        if resolved is None:
            print("Ошибка: в --src нет папки с общими модулями "
                  "(CommonModules/ либо CommonModule/): %s" % path, file=sys.stderr)
            sys.exit(2)
        root, layout_dir = resolved
        sources[version] = {
            "root": root,
            "index": build_module_index(root, layout_dir),
            "cache": {},
        }

    all_accepted = [occ for acc, _ in per_file.values() for occ in acc]
    all_skipped = [occ for _, skp in per_file.values() for occ in skp]

    findings = validate_versioned(all_accepted, all_skipped, sources)

    # Проход по справочнику API: ловит то, чего в исходниках модуля не видно.
    default_index = (Path(__file__).resolve().parent.parent / "skills" / "1c-bsp-api"
                     / "references" / "bsp-api.jsonl")
    api_index = load_api_index(args.index or default_index)
    if api_index:
        findings += validate_against_index(all_accepted, api_index)
    # Для отчета берем первую выгрузку: счет модулей и корень нужны как ориентир,
    # а находки уже собраны по всем версиям.
    first = next(iter(sources.values()))
    src_root, module_index = first["root"], first["index"]

    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    warns = sum(1 for f in findings if f["severity"] == "WARN")

    if args.json:
        payload = {
            "mode": "validate",
            "src": str(src_root),
            "modules_in_src": len(module_index),
            "checked_occurrences": len(all_accepted),
            "checked_unique": len({(o["file"], o["module"].lower(), o["method"].lower())
                                   for o in all_accepted}),
            "findings": findings,
            "summary": {
                "error": errors,
                "warn": warns,
                "info": sum(1 for f in findings if f["severity"] == "INFO"),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_validation_report(per_file, findings, len(module_index)))

    sys.exit(1 if (errors or warns) else 0)


if __name__ == "__main__":
    main()
