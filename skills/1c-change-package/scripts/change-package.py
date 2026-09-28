#!/usr/bin/env python3
# change-package v1.0 - Build a manual-change package for 1C modules edited outside the sources
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Строит пакет ручного внесения правок по двум версиям модулей 1С.

Вход - два файла .bsl или два каталога выгрузки. Выход - markdown: по каждому измененному
модулю блоки "Найти" и "Заменить целиком на" по методам, отдельно добавленные и удаленные
методы, участки вне методов и список файлов, которые правятся в Конфигураторе руками.
Пакет нужен там, где исходники недоступны: объект на поддержке без права правки, объект
захвачен в хранилище другим пользователем, обычная форма.

Блок "Найти" обязан встречаться в старой версии ровно один раз и быть непрерывным куском
модуля. Там, где такой фрагмент построить нельзя - разъехались участки вне методов,
метод разобран неоднозначно, добавлять метод не к чему - пакет предлагает замену модуля
целиком: один пункт с полным текстом обеих версий."""

import argparse
import os
import re
import sys

# --- Справочники имен ---

# Каталог выгрузки -> русское имя типа объекта. Незнакомый каталог описания не дает.
TYPE_TITLES = {
    "AccountingRegisters": "Регистр бухгалтерии",
    "AccumulationRegisters": "Регистр накопления",
    "Bots": "Бот",
    "BusinessProcesses": "Бизнес-процесс",
    "CalculationRegisters": "Регистр расчета",
    "Catalogs": "Справочник",
    "ChartsOfAccounts": "План счетов",
    "ChartsOfCalculationTypes": "План видов расчета",
    "ChartsOfCharacteristicTypes": "План видов характеристик",
    "CommonAttributes": "Общий реквизит",
    "CommonCommands": "Общая команда",
    "CommonForms": "Общая форма",
    "CommonModules": "Общий модуль",
    "CommonPictures": "Общая картинка",
    "CommonTemplates": "Общий макет",
    "Constants": "Константа",
    "DataProcessors": "Обработка",
    "DefinedTypes": "Определяемый тип",
    "DocumentJournals": "Журнал документов",
    "DocumentNumerators": "Нумератор документов",
    "Documents": "Документ",
    "Enums": "Перечисление",
    "EventSubscriptions": "Подписка на событие",
    "ExchangePlans": "План обмена",
    "FilterCriteria": "Критерий отбора",
    "FunctionalOptions": "Функциональная опция",
    "HTTPServices": "HTTP-сервис",
    "InformationRegisters": "Регистр сведений",
    "IntegrationServices": "Сервис интеграции",
    "Languages": "Язык",
    "Reports": "Отчет",
    "Roles": "Роль",
    "ScheduledJobs": "Регламентное задание",
    "Sequences": "Последовательность",
    "SessionParameters": "Параметр сеанса",
    "SettingsStorages": "Хранилище настроек",
    "StyleItems": "Элемент стиля",
    "Subsystems": "Подсистема",
    "Tasks": "Задача",
    "WebServices": "Web-сервис",
    "WSReferences": "WS-ссылка",
    "XDTOPackages": "Пакет XDTO",
}

# Имя файла модуля -> вид модуля. Пустая строка там, где вид уже назван типом объекта
# (общий модуль, модуль формы): иначе вышло бы "Общий модуль Товары, модуль".
MODULE_TITLES = {
    "CommandModule.bsl": "модуль команды",
    "ManagerModule.bsl": "модуль менеджера",
    "Module.bsl": "",
    "ObjectModule.bsl": "модуль объекта",
    "RecordSetModule.bsl": "модуль набора записей",
    "ValueManagerModule.bsl": "модуль менеджера значения",
}

# Корневые модули конфигурации лежат в Ext/ рядом с Configuration.xml.
ROOT_MODULE_TITLES = {
    "ExternalConnectionModule.bsl": "Модуль внешнего соединения",
    "ManagedApplicationModule.bsl": "Модуль управляемого приложения",
    "OrdinaryApplicationModule.bsl": "Модуль обычного приложения",
    "SessionModule.bsl": "Модуль сеанса",
}

# Ключевые слова читаются в обоих написаниях: модуль может быть русским или английским.
# Асинхронный метод объявляется словом Асинх (Async) перед ключевым словом метода.
DECL_RE = re.compile(
    r"^[ \t]*(?:(?:Асинх|Async)[ \t]+)?(Процедура|Procedure|Функция|Function)[ \t]+(\w+)[ \t]*\(",
    re.IGNORECASE,
)
FUNC_WORDS = ("Функция", "Function")
END_PROC_WORDS = ("КонецПроцедуры", "EndProcedure")
END_FUNC_WORDS = ("КонецФункции", "EndFunction")

# Директивы препроцессора: ветка #Если охватывает метод и дает ему второе закрывающее слово.
IF_WORDS = ("#Если", "#If")
ENDIF_WORDS = ("#КонецЕсли", "#EndIf")

# Привязка участка вне методов: до первого метода, после последнего, после названного.
START_ANCHOR = "start"
END_ANCHOR = "end"

COUNTERS = ("changed", "added", "removed", "outside", "replaced")


# --- Чтение файлов ---

def read_module(path):
    """Текст модуля в unicode: UTF-8, а при отказе разбора - CP1251."""
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251")


def split_module_lines(text):
    """Строки текста независимо от вида перевода строки."""
    return re.split(r"\r\n|\r|\n", text)


def normalize_lines(lines):
    """Слепок текста для сравнения: хвостовые пробелы и пустые строки не учитываются."""
    return [line.rstrip() for line in lines if line.strip()]


def files_differ(first, second):
    """Два файла различаются по содержимому."""
    with open(first, "rb") as handle:
        left = handle.read()
    with open(second, "rb") as handle:
        right = handle.read()
    return left != right


# --- Разбор методов ---

def word_matches(word, words):
    """Слово совпадает с одним из написаний без учета регистра."""
    folded = word.lower()
    return any(folded == other.lower() for other in words)


def opens_with_keyword(line, words):
    """Строка начинается с ключевого слова, а следом пробел, табуляция или комментарий."""
    text = line.strip().lower()
    for word in words:
        head = word.lower()
        if text == head:
            return True
        if text.startswith(head) and text[len(head):len(head) + 1] in (" ", "\t", "/"):
            return True
    return False


def is_attachment(line):
    """Строка примыкает к объявлению метода: директива компиляции или комментарий."""
    text = line.strip()
    return text.startswith("&") or text.startswith("//")


def method_start(lines, decl):
    """Начало метода: примыкающие комментарии, директивы и ветка препроцессора над объявлением.

    Пустая строка между двумя примыкающими строками границу не рвет: иначе комментарий
    отрывался бы от метода из-за одной пустой строки и показывался отдельным пунктом.
    Возврат - граница и число охвативших объявление веток #Если: от него зависит поиск
    конца метода.
    """
    start = decl
    branches = 0
    while start > 0:
        previous = lines[start - 1]
        if is_attachment(previous):
            start -= 1
            continue
        if opens_with_keyword(previous, IF_WORDS):
            branches += 1
            start -= 1
            continue
        if not previous.strip():
            above = start - 1
            while above >= 0 and not lines[above].strip():
                above -= 1
            if above >= 0 and opens_with_keyword(lines[above], IF_WORDS):
                branches += 1
                start = above
                continue
            if above >= 0 and is_attachment(lines[above]):
                start = above
                continue
        break
    return start, branches


def method_end(lines, decl, branches, end_words, other_words):
    """Конец метода: закрывающее слово с учетом веток препроцессора.

    Ветки #Если/#Иначе дают методу два закрывающих слова, поэтому метод кончается строкой
    #КонецЕсли, закрывшей последнюю ветку. Возврат - граница и признак однозначного
    разбора: незакрытая ветка, лишний #КонецЕсли или чужое закрывающее слово означают,
    что границы метода определить нельзя, и модуль придется заменять целиком.
    """
    depth = branches
    inner = -1
    index = decl + 1
    while index < len(lines):
        line = lines[index]
        if opens_with_keyword(line, IF_WORDS):
            depth += 1
        elif opens_with_keyword(line, ENDIF_WORDS):
            depth -= 1
            if depth < 0:
                return len(lines) - 1, False
            if depth == 0:
                if inner < 0:
                    return len(lines) - 1, False
                return index, True
        elif opens_with_keyword(line, end_words):
            if depth == 0:
                return index, True
            inner = index
        elif opens_with_keyword(line, other_words):
            return len(lines) - 1, False
        index += 1
    return len(lines) - 1, False


def parse_methods(lines):
    """Методы модуля в порядке следования: имя, границы и ключ сопоставления версий.

    Ключ - имя без учета регистра плюс номер повторения: одноименные методы в BSL
    невозможны, но битый модуль не должен из-за этого терять методы. Второй элемент
    возврата - признак разобранного модуля.
    """
    methods = []
    seen = {}
    index = 0
    parsed = True
    while index < len(lines):
        match = DECL_RE.match(lines[index])
        if not match:
            index += 1
            continue
        keyword = match.group(1)
        name = match.group(2)
        start, branches = method_start(lines, index)
        end_words = END_FUNC_WORDS if word_matches(keyword, FUNC_WORDS) else END_PROC_WORDS
        other_words = END_PROC_WORDS if word_matches(keyword, FUNC_WORDS) else END_FUNC_WORDS
        end, resolved = method_end(lines, index, branches, end_words, other_words)
        if not resolved:
            parsed = False
        folded = name.lower()
        repeat = seen.get(folded, 0)
        seen[folded] = repeat + 1
        methods.append({
            "key": (folded, repeat),
            "name": name,
            "start": start,
            "decl": index,
            "end": end,
        })
        index = end + 1
    return methods, parsed


def method_text(method, lines):
    """Текст метода целиком: директивы и комментарий перед объявлением, тело, закрывающее слово."""
    return lines[method["start"]:method["end"] + 1]


def has_repeats(methods):
    """В модуле есть методы с повторяющимся именем: разбор по именам ненадежен."""
    return len({method["key"][0] for method in methods}) != len(methods)


def trim_blank(lines):
    """Строки без пустых строк в конце: ровно то, что попадает в блок пакета."""
    body = list(lines)
    while body and not body[-1].strip():
        body.pop()
    return body


def count_block(lines, block):
    """Сколько раз блок встречается в модуле: блок "Найти" обязан быть единственным."""
    body = trim_blank(block)
    if not body:
        return 0
    total = 0
    for start in range(len(lines) - len(body) + 1):
        if lines[start:start + len(body)] == body:
            total += 1
    return total


def run_anchor(start, methods):
    """Привязка участка вне методов: начало модуля, конец модуля или метод перед ним."""
    previous = [method for method in methods if method["end"] < start]
    following = [method for method in methods if method["start"] > start]
    if not previous:
        return START_ANCHOR, "в начале модуля"
    if not following:
        return END_ANCHOR, "в конце модуля"
    method = previous[-1]
    return "after:" + method["key"][0] + "|" + str(method["key"][1]), "после метода " + method["name"]


def outside_runs(lines, methods):
    """Смежные участки модуля вне методов, каждый со своей привязкой.

    Участок - непрерывный кусок модуля: ровно то, что человек найдет в Конфигураторе одним
    поиском. Пустые участки в список не попадают: перестановка пустых строк правкой не
    считается, а привязка такого участка меняется от добавления любого метода.
    """
    covered = set()
    for method in methods:
        covered.update(range(method["start"], method["end"] + 1))
    runs = []
    index = 0
    while index < len(lines):
        if index in covered:
            index += 1
            continue
        first = index
        while index < len(lines) and index not in covered:
            index += 1
        block = lines[first:index]
        if not normalize_lines(block):
            continue
        key, label = run_anchor(first, methods)
        runs.append({"key": key, "label": label, "lines": block})
    return runs


# --- Описание модуля человеческим языком ---

def join_title(parts):
    """Части описания через запятую, пустые части отбрасываются."""
    return ", ".join(part for part in parts if part)


def object_title(dir_name, name):
    """Название объекта по каталогу выгрузки: "Справочник Товары"."""
    title = TYPE_TITLES.get(dir_name, "")
    if not title:
        return ""
    return title + " " + name


def describe_module_path(rel):
    """Описание модуля по пути в выгрузке: "Справочник Товары, модуль объекта"."""
    parts = rel.replace("\\", "/").split("/")
    file_name = parts[-1]
    kind = MODULE_TITLES.get(file_name, "")

    if len(parts) == 2 and parts[0] == "Ext":
        return ROOT_MODULE_TITLES.get(file_name, "")

    if "Forms" in parts:
        index = parts.index("Forms")
        form_name = parts[index + 1] if index + 1 < len(parts) else ""
        title = object_title(parts[0], parts[1]) if index >= 2 else ""
        return join_title([title, ("форма " + form_name) if form_name else "", kind])

    if len(parts) >= 2:
        return join_title([object_title(parts[0], parts[1]), kind])
    return kind


# --- Сбор файлов ---

def collect_files(root):
    """Относительные пути всех файлов каталога по возрастанию, разделитель - косая черта."""
    result = []
    for current, dirs, files in os.walk(root):
        dirs.sort()
        for name in files:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            result.append(rel)
    return sorted(result)


# --- Отрисовка пакета ---

def fence(lines):
    """Текст в ограде bsl с закрывающей пустой строкой пункта."""
    body = list(lines)
    while body and not body[-1].strip():
        body.pop()
    return ["```bsl"] + body + ["```", ""]


def render_change(head, before_lines, after_lines):
    """Пункт пакета с парой блоков: что найти и на что заменить целиком."""
    return ([head, "", "Найти:", ""] + fence(before_lines)
            + ["Заменить целиком на:", ""] + fence(after_lines))


def render_single(head, caption, lines):
    """Пункт пакета с одним блоком: добавление или удаление метода."""
    return [head, "", caption, ""] + fence(lines)


def added_head(after_methods, position, before_keys):
    """Заголовок пункта добавления метода: привязка к методу, который есть в старой версии.

    Заголовок "в начало модуля" поставил бы метод выше переменных модуля и вне веток
    препроцессора, поэтому место задает соседний метод старой версии. Возврат None -
    привязать не к чему, модуль придется заменять целиком.
    """
    name = after_methods[position]["name"]
    for method in after_methods[position + 1:]:
        if method["key"] in before_keys:
            return "### Добавить метод %s перед методом %s" % (name, method["name"])
    for method in reversed(after_methods[:position]):
        if method["key"] in before_keys:
            return "### Добавить метод %s после метода %s" % (name, method["name"])
    return None


def outside_items(before_lines, after_lines, before_methods, after_methods):
    """Пункты по участкам вне методов; None - если участки версий друг другу не отвечают."""
    old_by_key = {run["key"]: run for run in outside_runs(before_lines, before_methods)}
    new_runs = outside_runs(after_lines, after_methods)
    if set(old_by_key) != {run["key"] for run in new_runs}:
        return None
    items = []
    for run in new_runs:
        old = old_by_key[run["key"]]
        if normalize_lines(old["lines"]) == normalize_lines(run["lines"]):
            continue
        if count_block(before_lines, old["lines"]) != 1:
            return None
        items.extend(render_change("### Изменить код вне методов " + run["label"],
                                   old["lines"], run["lines"]))
    return items


def reorder_note():
    """Сообщение о перестановке методов: блоков замены у перестановки нет."""
    return ["### Порядок методов изменен", "",
            "Методы расположены в другом порядке, чем в старой версии: перенести целиком, "
            "без правки текста."]


def methods_reordered(before_methods, after_methods):
    """Порядок общих методов в новой версии отличается от старой."""
    after_keys = {method["key"] for method in after_methods}
    before_keys = {method["key"] for method in before_methods}
    old_order = [method["key"] for method in before_methods if method["key"] in after_keys]
    new_order = [method["key"] for method in after_methods if method["key"] in before_keys]
    return old_order != new_order


def section_items(before_lines, after_lines, before_methods, after_methods):
    """Пункты по одному модулю: измененные методы, добавленные, удаленные, участки вне методов.

    None - однозначных фрагментов "Найти" не построить, нужна замена модуля целиком.
    """
    items = []
    before_keys = {method["key"] for method in before_methods}
    after_keys = {method["key"] for method in after_methods}
    before_by_key = {method["key"]: method for method in before_methods}

    for position, method in enumerate(after_methods):
        old = before_by_key.get(method["key"])
        if old is None:
            head = added_head(after_methods, position, before_keys)
            if head is None:
                return None
            items.extend(render_single(head, "Текст метода:", method_text(method, after_lines)))
            continue
        old_text = method_text(old, before_lines)
        new_text = method_text(method, after_lines)
        if normalize_lines(old_text) == normalize_lines(new_text):
            continue
        if count_block(before_lines, old_text) != 1:
            return None
        items.extend(render_change("### Изменить метод %s" % method["name"], old_text, new_text))

    for method in before_methods:
        if method["key"] in after_keys:
            continue
        text = method_text(method, before_lines)
        if count_block(before_lines, text) != 1:
            return None
        items.extend(render_single("### Удалить метод %s" % method["name"],
                                   "Удалить целиком:", text))

    outside = outside_items(before_lines, after_lines, before_methods, after_methods)
    if outside is None:
        return None
    items.extend(outside)

    if methods_reordered(before_methods, after_methods):
        items.extend(reorder_note())
    return items


def whole_module_items(before_lines, after_lines):
    """Пункт замены модуля целиком: один блок вместо разрозненных фрагментов."""
    return render_change("### Заменить модуль целиком", before_lines, after_lines)


def count_section(section):
    """Счетчики пунктов в готовом разделе модуля."""
    counts = {name: 0 for name in COUNTERS}
    heads = {
        "### Изменить метод": "changed",
        "### Добавить метод": "added",
        "### Удалить метод": "removed",
        "### Изменить код вне методов": "outside",
        "### Заменить модуль целиком": "replaced",
    }
    for line in section:
        for prefix, name in heads.items():
            if line.startswith(prefix):
                counts[name] += 1
                break
    return counts


def build_section(rel, before_lines, after_lines):
    """Раздел модуля и счетчики по нему: одним вызовом, чтобы порядок пунктов не разъезжался."""
    before_methods, before_parsed = parse_methods(before_lines)
    after_methods, after_parsed = parse_methods(after_lines)
    items = None
    if (before_parsed and after_parsed
            and not has_repeats(before_methods) and not has_repeats(after_methods)):
        items = section_items(before_lines, after_lines, before_methods, after_methods)
    if items is None:
        items = whole_module_items(before_lines, after_lines)
    if not items:
        return []
    head = "## " + rel
    title = describe_module_path(rel)
    if title:
        head += " - " + title
    return [head, ""] + items


def replaced_part(totals):
    """Хвост строки счетчиков: модулей, заменяемых целиком. Ноль в отчет не попадает."""
    if not totals["replaced"]:
        return ""
    return ", замен целиком: %d" % totals["replaced"]


def render_package(before_arg, after_arg, sections, manual, totals):
    """Пакет markdown целиком: шапка со счетчиками, разделы модулей, файлы для ручной правки."""
    out = ["# Пакет ручного внесения изменений", "",
           "До: " + before_arg,
           "После: " + after_arg, ""]
    if not sections and not manual:
        out.append("Различий между версиями нет.")
        return "\n".join(out) + "\n"
    out.append("Модулей с правками: %d, методов изменено: %d, добавлено: %d, удалено: %d, "
               "правок вне методов: %d%s"
               % (totals["modules"], totals["changed"], totals["added"],
                  totals["removed"], totals["outside"], replaced_part(totals)))
    if manual:
        out.append("Файлов для правки вручную: %d" % len(manual))
    out.append("")
    for section in sections:
        out.extend(section)
    if manual:
        out.extend(["## Файлы для правки вручную", ""])
        for mark, path in manual:
            out.append("- Изменить вручную в Конфигураторе: " + path + mark)
        out.append("")
    return "\n".join(out) + "\n"


# --- Сравнение версий ---

def empty_totals():
    """Нулевые счетчики пакета."""
    totals = {"modules": 0}
    totals.update({name: 0 for name in COUNTERS})
    return totals


def add_counts(totals, counts):
    """Прибавить счетчики одного модуля к счетчикам пакета."""
    for name in COUNTERS:
        totals[name] += counts[name]


def compare_directories(before_root, after_root):
    """Разбор двух каталогов выгрузки: разделы пакета и список файлов для ручной правки."""
    before_set = set(collect_files(before_root))
    after_set = set(collect_files(after_root))

    sections = []
    manual = []
    totals = empty_totals()

    for rel in sorted(before_set & after_set):
        first = os.path.join(before_root, rel)
        second = os.path.join(after_root, rel)
        if not files_differ(first, second):
            continue
        if not rel.lower().endswith(".bsl"):
            manual.append(("", rel))
            continue
        section = build_section(rel, split_module_lines(read_module(first)),
                                split_module_lines(read_module(second)))
        if not section:
            continue
        sections.append(section)
        totals["modules"] += 1
        add_counts(totals, count_section(section))

    marks = {(True, True): " (новый модуль)", (True, False): " (новый файл)",
             (False, True): " (удаленный модуль)", (False, False): " (удаленный файл)"}
    for rel in sorted(after_set - before_set):
        manual.append((marks[(True, rel.lower().endswith(".bsl"))], rel))
    for rel in sorted(before_set - after_set):
        manual.append((marks[(False, rel.lower().endswith(".bsl"))], rel))

    return sections, manual, totals


def compare_files(before_arg, before_path, after_path):
    """Разбор двух одиночных файлов: модуль разбирается по методам, прочий файл идет в ручную правку.

    Заголовок раздела - путь в том виде, как его задал пользователь: относительного пути
    внутри выгрузки у одиночного файла нет.
    """
    if not files_differ(before_path, after_path):
        return [], [], empty_totals()
    if not before_path.lower().endswith(".bsl") or not after_path.lower().endswith(".bsl"):
        return [], [("", before_arg)], empty_totals()
    section = build_section(before_arg, split_module_lines(read_module(before_path)),
                            split_module_lines(read_module(after_path)))
    if not section:
        return [], [], empty_totals()
    totals = empty_totals()
    totals["modules"] = 1
    add_counts(totals, count_section(section))
    return [section], [], totals


# --- Точка входа ---

def write_out(path, text):
    """Запись пакета: UTF-8 без BOM и перевод строки LF - одинаково с портом PowerShell."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def print_summary(totals, manual):
    """Строки отчета в stdout после записи файла."""
    if totals["modules"] or manual:
        sys.stdout.write("[OK]    Модулей с правками: %d, методов изменено: %d, добавлено: %d, "
                         "удалено: %d, правок вне методов: %d%s\n"
                         % (totals["modules"], totals["changed"], totals["added"],
                            totals["removed"], totals["outside"], replaced_part(totals)))
    if manual:
        sys.stdout.write("[WARN]  Файлов для правки вручную: %d\n" % len(manual))


def main():
    # newline="" обязателен: иначе текстовый stdout на Windows переводит LF в CRLF и
    # расходится с портом PowerShell, который печатает LF.
    sys.stdout.reconfigure(encoding="utf-8", newline="")
    sys.stderr.reconfigure(encoding="utf-8", newline="")
    parser = argparse.ArgumentParser(
        description="Build a manual-change package from two versions of 1C modules",
        allow_abbrev=False,
    )
    parser.add_argument("-Before", dest="Before", default="")
    parser.add_argument("-After", dest="After", default="")
    parser.add_argument("-OutFile", dest="OutFile", default="")
    args = parser.parse_args()

    if not args.Before or not args.After:
        sys.stderr.write("[ERROR] Укажите -Before и -After\n")
        return 2
    before = os.path.abspath(args.Before)
    after = os.path.abspath(args.After)
    for path in (before, after):
        if not os.path.exists(path):
            sys.stderr.write("[ERROR] Путь не найден: " + path + "\n")
            return 1
    if os.path.isdir(before) != os.path.isdir(after):
        sys.stderr.write("[ERROR] До и после должны быть либо двумя файлами, либо двумя каталогами\n")
        return 1

    if os.path.isdir(before):
        sections, manual, totals = compare_directories(before, after)
    else:
        sections, manual, totals = compare_files(args.Before, before, after)

    text = render_package(args.Before, args.After, sections, manual, totals)

    if not args.OutFile:
        sys.stdout.write(text)
        return 0
    out_file = os.path.abspath(args.OutFile)
    try:
        write_out(out_file, text)
    except OSError as error:
        sys.stderr.write("[ERROR] Пакет не записан: %s\n" % error)
        return 1
    sys.stdout.write("[OK]    Пакет записан: " + out_file + "\n")
    print_summary(totals, manual)
    return 0


if __name__ == "__main__":
    sys.exit(main())
