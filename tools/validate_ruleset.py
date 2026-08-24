#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Линтер набора: frontmatter, перекрестные ссылки и бюджет постоянного контекста.

Три проверки, каждая ловит свой класс молчаливых поломок.

1. Frontmatter. У скила обязателен блок с полями name и description, и name обязан
   совпадать с именем каталога: расхождение означает, что скил не вызовется по имени.
   У правила блок необязателен, но если он есть, в нем допустимы только известные ключи -
   опечатка в ключе не дает ошибки нигде, правило просто перестает подключаться как задумано.

2. Перекрестные ссылки. Правила и скилы ссылаются друг на друга именами файлов в бэктиках.
   Ссылка на несуществующий файл ничего не ломает при прогоне тестов и живет годами.

3. Бюджет постоянного контекста. Правило БЕЗ ключа paths загружается всегда, правило С ним -
   только при работе с совпавшими файлами. Описания скилов лежат в контексте каждый ход
   независимо ни от чего. Обе величины растут незаметно, поэтому меряются и держатся под
   порогом-храповиком: вырос - либо ужимай, либо подними порог осознанно.

Запуск:  python tools/validate_ruleset.py [--budget]
Выход 1 при находках уровня ERROR.
"""
import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"
SKILLS_DIR = ROOT / "skills"

# Ключи, допустимые во frontmatter правила. Все прочее - опечатка либо забытый эксперимент.
# Ключи frontmatter правила. Набор существует в двух формах: здесь правило - это .md с
# ключом paths, в зеркале для Cursor - .mdc с ключами globs и alwaysApply. Линтер запускается
# сборкой в обоих репозиториях, поэтому знает обе формы.
RULE_KEYS = {"paths", "globs", "alwaysApply", "name", "description"}
PATH_KEYS = ("paths", "paths[]", "globs", "globs[]")


def rule_files():
    """Правила обеих форм: .md здесь, .mdc в зеркале."""
    return sorted(list(RULES_DIR.glob("*.md")) + list(RULES_DIR.glob("*.mdc")))

# Имена, которые выглядят ссылкой на файл, но ею не являются: шаблоны имен результата,
# заполнители в примерах команд. Проверять их бессмысленно.
LINK_EXCLUSIONS = {
    "input.md",
    "output.md",
    "methods.md",
    "benchmark.md",
    # Файлы проекта пользователя, а не набора: набор о них рассказывает, но их не содержит.
    "CLAUDE.md",
    "AGENTS.md",
    # Имена из примеров работы скилов.
    "postanovka.md",
    "postanovka-enhanced.md",
    # Файл конфигурации 1С 7.7, а не markdown: расширение совпало случайно.
    "1cv7.md",
}
LINK_EXCLUSION_PATTERNS = (
    re.compile(r"^-"),                 # суффиксные шаблоны вида "-human.md"
    re.compile(r"^<"),                 # заполнители вида "<имя>.md"
    re.compile(r"[{}*]"),              # шаблоны с подстановкой
)

# Порог-храповик. Поднимается осознанно и вместе с объяснением, а не по факту роста.
BUDGET_RULES_BYTES = 135_000
BUDGET_SKILL_DESCRIPTIONS_BYTES = 90_000


def read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def parse_frontmatter(text):
    """Вернуть (словарь полей, тело). Полей нет - пустой словарь."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    body = text[end + 4:]
    fields = {}
    current = None
    folded = None   # имя поля, значение которого собирается из последующих строк
    lines = block.split("\n")
    for line in lines:
        stripped = line.strip()
        # Свернутый скаляр: "description: >" и текст на следующих строках с отступом.
        # Без сборки такого значения поле выглядит непустым (в нем один символ), и
        # проверка описания проходит, а бюджет считает один байт вместо реального текста.
        if folded is not None:
            if not stripped:
                continue
            if line.startswith((" ", "\t")):
                fields[folded] = (fields[folded] + " " + stripped).strip()
                continue
            folded = None
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            current = match.group(1)
            value = match.group(2).strip()
            if re.fullmatch(r"[>|][-+]?\d*", value):
                fields[current] = ""
                folded = current
            else:
                fields[current] = value
        elif stripped.startswith("-") and current:
            fields.setdefault(current + "[]", []).append(stripped[1:].strip())
    return fields, body


def collect_known_files():
    """Имена файлов, на которые ссылаться законно.

    В зеркале для Cursor правила лежат с расширением .mdc, а ссылки в скилах остаются на .md:
    имя правила одно и то же, различается только формат подключения к среде. Поэтому правило
    засчитывается по обоим расширениям.
    """
    known = {}
    for path in list(RULES_DIR.glob("*.md")) + list(RULES_DIR.glob("*.mdc")):
        known.setdefault(path.name, []).append(path)
        if path.suffix == ".mdc":
            known.setdefault(path.stem + ".md", []).append(path)
    for path in SKILLS_DIR.rglob("*.md"):
        known.setdefault(path.name, []).append(path)
    for path in (ROOT / "docs").glob("*.md"):
        known.setdefault(path.name, []).append(path)
    return known


def check_frontmatter(problems):
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            problems.append(("ERROR", str(skill_dir), "нет файла SKILL.md"))
            continue
        fields, _ = parse_frontmatter(read(skill_md))
        if not fields:
            problems.append(("ERROR", str(skill_md), "нет frontmatter"))
            continue
        name = fields.get("name", "").strip("\"'")
        if not name:
            problems.append(("ERROR", str(skill_md), "во frontmatter нет поля name"))
        elif name != skill_dir.name:
            problems.append(("ERROR", str(skill_md),
                             f"name={name} не совпадает с именем каталога {skill_dir.name}"))
        if not fields.get("description"):
            problems.append(("ERROR", str(skill_md), "во frontmatter нет поля description"))

    for rule in rule_files():
        fields, _ = parse_frontmatter(read(rule))
        unknown = {k for k in fields if not k.endswith("[]")} - RULE_KEYS
        if unknown:
            problems.append(("ERROR", str(rule),
                             f"неизвестные ключи frontmatter: {', '.join(sorted(unknown))}"))


def check_links(problems):
    known = collect_known_files()
    targets = list(RULES_DIR.glob("*.md")) + list(SKILLS_DIR.rglob("*.md"))
    for path in sorted(targets):
        text = read(path)
        for name in set(re.findall(r"`([A-Za-z0-9_.\-<>{}*]+\.md)`", text)):
            if name in LINK_EXCLUSIONS:
                continue
            if any(pattern.search(name) for pattern in LINK_EXCLUSION_PATTERNS):
                continue
            if name == path.name:
                continue
            if (path.parent / name).exists():
                continue
            if name in known:
                continue
            problems.append(("ERROR", str(path), f"ссылка на несуществующий файл: {name}"))


def measure_budget():
    """Постоянно загружаемое: правила без paths плюс описания всех скилов."""
    always = []
    conditional = []
    for rule in rule_files():
        text = read(rule)
        fields, _ = parse_frontmatter(text)
        size = len(text.encode("utf-8"))
        if any(key in fields for key in PATH_KEYS):
            conditional.append((rule.name, size))
        else:
            always.append((rule.name, size))

    descriptions = 0
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        fields, _ = parse_frontmatter(read(skill_md))
        descriptions += len(fields.get("description", "").encode("utf-8"))
    return always, conditional, descriptions


def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Линтер набора правил и скилов")
    parser.add_argument("--budget", action="store_true",
                        help="показать раскладку бюджета контекста по файлам")
    args = parser.parse_args()

    problems = []
    check_frontmatter(problems)
    check_links(problems)

    always, conditional, descriptions = measure_budget()
    always_bytes = sum(size for _, size in always)

    print(f"Скилов: {len(list(SKILLS_DIR.glob('*/SKILL.md')))}, правил: {len(always) + len(conditional)}")
    print(f"Постоянно загружаемые правила (без paths): {len(always)}, {always_bytes:,} байт".replace(",", " "))
    print(f"Правила по совпадению путей: {len(conditional)}")
    print(f"Описания скилов: {descriptions:,} байт".replace(",", " "))

    if args.budget:
        print("\nПостоянно загружаемые правила, по убыванию:")
        for name, size in sorted(always, key=lambda x: -x[1]):
            print(f"  {size:>7} {name}")

    if always_bytes > BUDGET_RULES_BYTES:
        problems.append(("ERROR", "rules/",
                         f"постоянный контекст правил {always_bytes} байт превысил порог "
                         f"{BUDGET_RULES_BYTES}: выноси детали в правило с paths, "
                         f"а не поднимай порог по факту роста"))
    if descriptions > BUDGET_SKILL_DESCRIPTIONS_BYTES:
        problems.append(("ERROR", "skills/",
                         f"описания скилов {descriptions} байт превысили порог "
                         f"{BUDGET_SKILL_DESCRIPTIONS_BYTES}"))

    errors = [p for p in problems if p[0] == "ERROR"]
    if problems:
        print()
        for level, where, message in problems:
            print(f"{level}: {where} - {message}")
    print()
    print(f"Находок: {len(problems)}, из них блокирующих: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
