#!/usr/bin/env python3
# change-package v1.0 - Build a manual-change package for 1C modules edited outside the sources
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Строит пакет ручного внесения правок по двум версиям модулей 1С.

Вход - два файла .bsl или два каталога выгрузки. Выход - markdown: по каждому измененному
модулю блоки "Найти" и "Заменить целиком на" по методам, отдельно добавленные и удаленные
методы, изменения вне методов и список файлов, которые правятся в Конфигураторе руками.
Пакет нужен там, где исходники недоступны: объект на поддержке без права правки, объект
захвачен в хранилище другим пользователем, обычная форма."""

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
DECL_RE = re.compile(
    r"^[ \t]*(Процедура|Procedure|Функция|Function)[ \t]+(\w+)[ \t]*\(",
    re.IGNORECASE,
)
FUNC_WORDS = ("Функция", "Function")
END_PROC_WORDS = ("КонецПроцедуры", "EndProcedure")
END_FUNC_WORDS = ("КонецФункции", "EndFunction")

COUNTERS = ("changed", "added", "removed", "outside")


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


def parse_methods(lines):
    """Методы модуля в порядке следования: имя, границы и ключ сопоставления версий.

    Ключ - имя без учета регистра плюс номер повторения: одноименные методы в BSL
    невозможны, но битый модуль не должен из-за этого терять методы.
    """
    methods = []
    seen = {}
    index = 0
    while index < len(lines):
        match = DECL_RE.match(lines[index])
        if not match:
            index += 1
            continue
        name = match.group(2)
        start = index
        while start > 0 and is_attachment(lines[start - 1]):
            start -= 1
        end_words = END_FUNC_WORDS if word_matches(match.group(1), FUNC_WORDS) else END_PROC_WORDS
        end = index + 1
        while end < len(lines) and not opens_with_keyword(lines[end], end_words):
            end += 1
        if end >= len(lines):
            end = len(lines) - 1
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
    return methods


def method_text(method, lines):
    """Текст метода целиком: директивы и комментарий перед объявлением, тело, закрывающее слово."""
    return lines[method["start"]:method["end"] + 1]


def outside_text(lines, methods):
    """Строки модуля, не попавшие ни в один метод: переменные модуля и основной код."""
    covered = set()
    for method in methods:
        covered.update(range(method["start"], method["end"] + 1))
    return [line for number, line in enumerate(lines) if number not in covered]


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


def render_module_section(rel, before_lines, after_lines, before_methods, after_methods):
    """Пункты пакета по одному модулю: измененные методы, добавленные, удаленные, код вне методов."""
    items = []
    after_keys = {method["key"] for method in after_methods}
    before_by_key = {method["key"]: method for method in before_methods}

    for position, method in enumerate(after_methods):
        old = before_by_key.get(method["key"])
        if old is None:
            previous = after_methods[position - 1]["name"] if position else ""
            if previous:
                head = "### Добавить метод %s после метода %s" % (method["name"], previous)
            else:
                head = "### Добавить метод %s в начало модуля" % method["name"]
            items.extend(render_single(head, "Текст метода:", method_text(method, after_lines)))
        elif normalize_lines(method_text(old, before_lines)) != normalize_lines(method_text(method, after_lines)):
            items.extend(render_change("### Изменить метод %s" % method["name"],
                                       method_text(old, before_lines),
                                       method_text(method, after_lines)))

    for method in before_methods:
        if method["key"] not in after_keys:
            items.extend(render_single("### Удалить метод %s" % method["name"],
                                       "Удалить целиком:", method_text(method, before_lines)))

    old_outside = outside_text(before_lines, before_methods)
    new_outside = outside_text(after_lines, after_methods)
    if normalize_lines(old_outside) != normalize_lines(new_outside):
        items.extend(render_change("### Изменить код вне методов", old_outside, new_outside))

    if not items:
        return []
    head = "## " + rel
    title = describe_module_path(rel)
    if title:
        head += " - " + title
    return [head, ""] + items


def count_section(section):
    """Счетчики пунктов в готовом разделе модуля."""
    counts = {name: 0 for name in COUNTERS}
    heads = {
        "### Изменить метод": "changed",
        "### Добавить метод": "added",
        "### Удалить метод": "removed",
        "### Изменить код вне методов": "outside",
    }
    for line in section:
        for prefix, name in heads.items():
            if line.startswith(prefix):
                counts[name] += 1
                break
    return counts


def build_section(rel, before_lines, after_lines):
    """Раздел модуля и счетчики по нему: одним вызовом, чтобы порядок пунктов не разъезжался."""
    before_methods = parse_methods(before_lines)
    after_methods = parse_methods(after_lines)
    return render_module_section(rel, before_lines, after_lines, before_methods, after_methods)


def render_package(before_arg, after_arg, sections, manual, totals):
    """Пакет markdown целиком: шапка со счетчиками, разделы модулей, файлы для ручной правки."""
    out = ["# Пакет ручного внесения изменений", "",
           "До: " + before_arg,
           "После: " + after_arg, ""]
    if not sections and not manual:
        out.append("Различий между версиями нет.")
        return "\n".join(out) + "\n"
    out.append("Модулей с правками: %d, методов изменено: %d, добавлено: %d, удалено: %d, "
               "правок вне методов: %d"
               % (totals["modules"], totals["changed"], totals["added"],
                  totals["removed"], totals["outside"]))
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
                         "удалено: %d, правок вне методов: %d\n"
                         % (totals["modules"], totals["changed"], totals["added"],
                            totals["removed"], totals["outside"]))
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
