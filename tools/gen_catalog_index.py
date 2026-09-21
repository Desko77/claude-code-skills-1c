#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор индекса и каталожных секций правил из карточек дефектов.

Читает карточки skills/1c-code-review/references/catalog/<ИДЕНТИФИКАТОР>.md, проверяет
обязательные поля и пишет:

- catalog/INDEX.md - таблица идентификатор, важность, группа, архетипы, детекторы, триггер;
- секции между маркерами catalog:begin / catalog:end в rules/anti_patterns.md (таблица
  триггеров с колонкой псевдонима) и rules/code-review-checklist.md (таблица по группам).

Вне маркеров файлы правил не меняются. Одинаковый вход дает одинаковый выход: сортировка
по идентификатору, генерация одной строкой на строку таблицы.

Режим --check ничего не пишет и выходит с кодом 1, если сгенерированное отличается от
файлов на диске.

Запуск:  python tools/gen_catalog_index.py [--check]
"""
import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "skills" / "1c-code-review" / "references" / "catalog"
INDEX = CATALOG / "INDEX.md"
RULE_TARGETS = {
    ROOT / "rules" / "anti_patterns.md": "anti",
    ROOT / "rules" / "code-review-checklist.md": "checklist",
}

BEGIN = "<!-- catalog:begin -->"
END = "<!-- catalog:end -->"

SECTIONS = [
    "Идентификатор и группа",
    "Важность",
    "Триггер",
    "Почему дефект",
    "Законная форма",
    "Как чинить",
    "Детекторы",
    "Архетипы правки",
    "Фикстура",
    "Источник",
]
SEVERITIES = {"Critical", "Major", "Minor"}
GROUPS = {
    "MODEL", "PERF", "QUERY", "TXN", "FORM",
    "CLIENT", "SEC", "EXT", "META", "PROC",
}
FIXTURE_TYPES = {"bsl-pair", "project-tree", "diff", "evidence"}
ARCHETYPES = {
    "транзакция", "блокировка", "права", "запрос", "модуль формы",
    "событие объекта", "новый общий модуль", "перехват в расширении",
    "изменение метаданных", "любой BSL",
}


class CardError(Exception):
    """Нарушение формата карточки или структуры каталога."""


def parse_card(path):
    """Разобрать карточку в словарь полей. Все разделы обязательны и строго по порядку."""
    text = path.read_text(encoding="utf-8")
    heading = re.match(r"^# ([A-Z]+-\d{2})\. (.+)$", text.split("\n", 1)[0])
    if not heading:
        raise CardError("%s: заголовок не вида '# <ИД>. <Заголовок>'" % path.name)
    card_id, title = heading.group(1), heading.group(2)
    if card_id != path.stem:
        raise CardError("%s: идентификатор %s не совпадает с именем файла" % (path.name, card_id))

    chunks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    order = []
    fields = {}
    for chunk in chunks:
        name, _, body = chunk.partition("\n")
        name = name.strip()
        order.append(name)
        fields[name] = body.strip()
    if order != SECTIONS:
        raise CardError(
            "%s: разделы %s не совпадают с требуемым порядком %s"
            % (path.name, order, SECTIONS))

    severity = fields["Важность"].strip()
    if severity not in SEVERITIES:
        raise CardError("%s: важность %s вне шкалы %s" % (path.name, severity, sorted(SEVERITIES)))

    group = card_id.split("-", 1)[0]
    if group not in GROUPS:
        raise CardError("%s: группа %s не входит в список групп" % (path.name, group))

    ident_lines = fields["Идентификатор и группа"].split("\n")
    if not any(line.strip() == "Идентификатор: `%s`" % card_id for line in ident_lines):
        raise CardError("%s: в разделе Идентификатор и группа нет строки Идентификатор" % path.name)
    alias = ""
    for line in ident_lines:
        if line.startswith("Псевдоним:"):
            alias = line.partition(":")[2].strip()

    legal = fields["Законная форма"]
    if not legal or "```" not in legal:
        raise CardError("%s: законная форма пуста или без блока кода" % path.name)

    archetypes = [a.strip() for a in fields["Архетипы правки"].split(",") if a.strip()]
    unknown = [a for a in archetypes if a not in ARCHETYPES]
    if unknown:
        raise CardError("%s: неизвестные архетипы %s" % (path.name, unknown))

    fixture_type = ""
    fixture_match = re.search(r"^Тип: `([a-z-]+)`", fields["Фикстура"], flags=re.MULTILINE)
    if fixture_match:
        fixture_type = fixture_match.group(1)
    if fixture_type not in FIXTURE_TYPES:
        raise CardError("%s: тип фикстуры %s вне списка %s"
                        % (path.name, fixture_type, sorted(FIXTURE_TYPES)))

    trigger = fields["Триггер"].split("\n")[0].strip()

    detectors = []
    for row in fields["Детекторы"].split("\n"):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) != 2 or not cells[0] or set(cells[0]) <= {"-", " "}:
            continue  # пустая строка, разделитель или строка с другим числом колонок
        if cells == ["Среда", "Детектор"]:
            continue  # заголовок таблицы
        detectors.append("%s: %s" % (cells[0], cells[1]))

    return {
        "id": card_id,
        "title": title,
        "group": group,
        "alias": alias,
        "severity": severity,
        "trigger": trigger,
        "archetypes": archetypes,
        "detectors": detectors,
        "fixture_type": fixture_type,
    }


def load_cards():
    cards = [parse_card(p) for p in sorted(CATALOG.glob("*.md")) if p.stem != "INDEX"]
    if not cards:
        raise CardError("в %s нет карточек" % CATALOG)
    seen = set()
    for card in cards:
        if card["id"] in seen:
            raise CardError("повтор идентификатора %s" % card["id"])
        seen.add(card["id"])
    return sorted(cards, key=lambda c: c["id"])


def render_index(cards):
    lines = [
        "# Индекс каталога дефектов",
        "",
        "Генерируется `tools/gen_catalog_index.py` по карточкам каталога; правится только",
        "через карточки. Колонка Триггер - формулировка одной строкой; полные триггер,",
        "законная форма и способ чинить - в карточке с идентичным именем.",
        "",
        "| Идентификатор | Важность | Группа | Архетипы | Детекторы | Триггер |",
        "|---------------|----------|--------|----------|-----------|---------|",
    ]
    for c in cards:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            c["id"], c["severity"], c["group"],
            ", ".join(c["archetypes"]), "; ".join(c["detectors"]), c["trigger"]))
    lines.append("")
    return "\n".join(lines)


def render_anti(cards):
    lines = [
        "## Каталог дефектов",
        "",
        "Секция генерируется `tools/gen_catalog_index.py` по карточкам каталога скила",
        "`1c-code-review`; между маркерами не правится. Колонка Псевдоним сохраняет прежнюю",
        "нумерацию пунктов этого файла: ссылки вида п.N читаются по ней. Подробности - в",
        "карточке каталога с тем же идентификатором.",
        "",
        "| Идентификатор | Псевдоним | Важность | Триггер |",
        "|---------------|-----------|----------|---------|",
    ]
    for c in cards:
        alias = c["alias"] if c["alias"] else ""
        lines.append("| %s | %s | %s | %s |" % (c["id"], alias, c["severity"], c["trigger"]))
    lines.append("")
    return "\n".join(lines)


def render_checklist(cards):
    lines = [
        "## Каталог дефектов",
        "",
        "Секция генерируется `tools/gen_catalog_index.py` по карточкам каталога скила",
        "`1c-code-review`; между маркерами не правится. Перевод важности карточек в действия",
        "ревью - `skills/1c-code-review/references/severity.md`.",
        "",
        "| Группа | Идентификатор | Важность | Триггер |",
        "|--------|---------------|----------|---------|",
    ]
    for c in cards:
        lines.append("| %s | %s | %s | %s |" % (c["group"], c["id"], c["severity"], c["trigger"]))
    lines.append("")
    return "\n".join(lines)


RENDERERS = {"anti": render_anti, "checklist": render_checklist}


def replace_section(text, rendered):
    """Заменить содержимое между маркерами, остальной текст не трогать."""
    begin = text.find(BEGIN)
    end = text.find(END)
    if begin == -1 or end == -1 or end < begin:
        raise CardError("маркеры catalog:begin/end не найдены или перепутаны местами")
    head = text[:begin + len(BEGIN)]
    tail = text[end:]
    return head + "\n\n" + rendered + "\n" + tail


def normalize(text):
    return text.replace("\r\n", "\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Генератор индекса каталога дефектов")
    parser.add_argument("--check", action="store_true",
                        help="без записи: выход 1, если файлы отличаются от генерации")
    args = parser.parse_args()

    try:
        cards = load_cards()
        outputs = [(INDEX, render_index(cards))]
        for path, kind in RULE_TARGETS.items():
            if not path.exists():
                raise CardError("нет файла правила: %s" % path)
            text = normalize(path.read_text(encoding="utf-8"))
            outputs.append((path, replace_section(text, RENDERERS[kind](cards))))
    except CardError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    stale = []
    for path, content in outputs:
        if args.check:
            disk = normalize(path.read_text(encoding="utf-8")) if path.exists() else ""
            if disk != content:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.write_text(content, encoding="utf-8", newline="\n")

    if args.check:
        if stale:
            print("ОТЛИЧАЕТСЯ ОТ ГЕНЕРАЦИИ:")
            for name in stale:
                print("  %s" % name)
            print("Выполни: python tools/gen_catalog_index.py")
            return 1
        print("OK - индекс и каталожные секции совпадают с карточками (%d шт.)." % len(cards))
        return 0
    print("Записано: %s и секции в %d правилах (%d карточек)."
          % (INDEX.relative_to(ROOT), len(RULE_TARGETS), len(cards)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
