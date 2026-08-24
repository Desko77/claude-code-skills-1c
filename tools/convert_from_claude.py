#!/usr/bin/env python3
"""
Convert claude-code-skills-1c → cursor-1c-skills.

Converts rules (.md → .mdc with MDC frontmatter) and skills
(strip allowed-tools/argument-hint, replace Claude Code tool references).
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# ─── Rules configuration ────────────────────────────────────────────────────

RULES_CONFIG = {
    "designer-batch-verdict": {
        "description": "Вердикт пакетного запуска платформы: четыре сигнала вместо кода возврата",
        "globs": ["**/scripts/*.ps1", "**/scripts/*.py", "**/*.cmd", "**/*.bat"],
    },
    "1c-transactions-and-locks": {
        "description": "Транзакции и управляемые блокировки: шаблон, порядок захвата",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "edt-source-format": {
        "description": "Формат исходников 1С и один владелец развертывания на прогон",
        "globs": ["**/*.mdo", "**/*.form", "**/Configuration.xml"],
    },
    "1c-cyrillic-windows": {
        "description": "Кириллица в путях и аргументах на Windows: симптомы, кодировки, отказы",
        "globs": ["**/*.ps1", "**/*.py", "**/*.cmd", "**/*.bat", "**/*.mjs"],
    },
    "1c-ordinary-forms": {
        "description": "Обычные формы: отличия от управляемых, порядок операций с видимостью",
        "globs": ["**/Forms/**/*.bsl", "**/Ext/Form.xml"],
    },
    "1c-coding-standards": {
        "description": "Стандарты кода BSL: именование, запросы, коллекции",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "anti_patterns": {
        "description": "Критические антипаттерны 1С: запрос в цикле, реквизиты через точку",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "async-methods-1c": {
        "description": "Асинхронные методы 1С: Асинх/Ждать/Обещание (8.3.18+)",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "1c-extension-patterns": {
        "description": "Паттерны расширений CFE: перехватчики, маркеры",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "1c-mdo-integrity": {
        "description": "Целостность MDO-файлов: UUID, ссылки",
        "globs": ["**/*.mdo"],
    },
    "code-exploration-guide": {
        "description": "Методология исследования кодовой базы 1С",
        "globs": [],
    },
    "code-review-checklist": {
        "description": "Чеклист ревью BSL-кода",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "form_module_rules": {
        "description": "Клиент-серверное разделение в модулях форм",
        "globs": ["**/*.bsl"],
    },
    "forms_events": {
        "description": "Привязка обработчиков событий в Form.xml",
        "globs": ["**/Form.xml", "**/*.bsl"],
    },
    "query-optimization-tips": {
        "description": "Оптимизация запросов 1С: ВЫРАЗИТЬ, ВТ, индексы",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "refactoring": {
        "description": "Правила рефакторинга кода 1С",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "routine_assignment_ext_processor": {
        "description": "Фоновые задания из внешней обработки через БСП",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "testing-patterns": {
        "description": "Паттерны тестирования 1С: YaXUnit, Vanessa",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "v8unpack-source-structure": {
        "description": "Структура исходников v8unpack",
        "globs": [],
    },
    "model-selection": {
        "description": "Стратегия выбора моделей: Opus/Sonnet/Haiku по типу задачи",
        "globs": [],
    },
    "mcp-tool-priority": {
        "description": "Маршрутизатор MCP-серверов: какой сервер брать под задачу, обязательные проверки",
        "globs": [],
    },
    "git-safety-rules": {
        "description": "Безопасная работа с git: деструктивные команды, секреты, политика EOL для 1С",
        "globs": [],
    },
    "text-formatting": {
        "description": "Запрещенные символы в генерируемом тексте: длинное тире, буква ё, кавычки-елочки",
        "globs": [],
    },
    "file-edit-efficiency": {
        "description": "Выбор инструмента чтения и правки файлов по стоимости токенов",
        "globs": [],
    },
    "skill-design": {
        "description": "Проектирование навыков: способы вызова, лестница информации, критерии завершения",
        "globs": [],
    },
    "agent-working-memory": {
        "description": "Рабочая память агента: файлы плана, передача сессии, журнал инцидентов",
        "globs": [],
    },
    "sdd-workflow": {
        "description": "Specification-Driven Development: 9-фазный workflow разработки",
        "globs": [],
    },
    "1c-form-reserved-names": {
        "description": "Зарезервированные имена свойств в модулях форм 1С",
        "globs": ["**/*.bsl"],
    },
    "forms_generation": {
        "description": "Генерация и модификация форм 1С через 1c-forms-mcp",
        "globs": ["**/Forms/**/*.xml", "**/Forms/**"],
    },
    "edt-form-xml-requirements": {
        "description": "Требования EDT к XML-формам (Form.form): extInfo, дефолты полей",
        "globs": ["**/Form.form", "**/Forms/**"],
    },
    "external-data-source-mdo": {
        "description": "Внешние источники данных (ВИД) в формате EDT",
        "globs": ["**/*.mdo", "**/ExternalDataSources/**"],
    },
    "bsp-profile-rights-api": {
        "description": "Программная работа с профилями групп доступа БСП: ссылки на ИдентификаторыОбъектовМетаданных",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "1c-report-direct-query": {
        "description": "Прямой запрос в отчётах 1С (СКД) без схемы компоновки",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "1c-role-rights": {
        "description": "Права ролей 1С: права на объекты, RLS, наследование",
        "globs": ["**/Rights.xml", "**/Roles/**", "**/*.mdo"],
    },
    "edt-zip-export-pitfalls": {
        "description": "Ограничения инкрементального экспорта конфигурации из EDT в ИБ",
        "globs": ["**/*.mdo"],
    },
    "agent-verification-patterns": {
        "description": "Паттерны проверки результата работы агента (reconciliation loop)",
        "globs": [],
    },
    "bsl-ssl": {
        "description": "Переиспользование БСП, разметка правок типовых модулей, устаревшие объекты",
        "globs": ["**/*.bsl", "**/*.os"],
    },
    "edt-bsl-write-safety": {
        "description": "Безопасная запись BSL-модулей через EDT MCP (режимы write_module_source)",
        "globs": ["**/*.bsl"],
    },
    "integrations": {
        "description": "Python-first подход к HTTP-интеграциям 1С (прототип Python, перенос на BSL)",
        "globs": [],
    },
    "1c-skd-two-pass-preprocessing": {
        "description": "Двухпроходный СКД: предобработка детальных записей до свертки",
        "globs": ["**/Reports/**/*.bsl", "**/*.dcs"],
    },
}

EXCLUDE_SKILLS = {"skill-creator"}

# Body text replacements for SKILL.md (order matters — longer patterns first)
SKILL_TEXT_REPLACEMENTS = [
    # 1c-db-list:123
    ("через AskUserQuestion", "интерактивно"),
    # 1c-mxl-compile:38
    ("(read via Read tool before writing JSON)", "(прочитай перед написанием JSON)"),
    # 1c-mxl-decompile:38
    ("(read via Read tool)", ""),
    # 1c-mxl-compile:29
    ("(Write tool) ", ""),
    # 1c-role-info:34, 1c-role-validate:34
    ("via Read tool", ""),
    (" via Read tool", ""),
    # Generic fallback
    ("Read tool", ""),
    ("Write tool", ""),
]


# ─── Frontmatter parsing ────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict | None, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict_or_None, body_without_frontmatter).
    """
    if not content.startswith("---"):
        return None, content

    end = content.find("\n---", 3)
    if end == -1:
        return None, content

    fm_text = content[4:end].strip()
    body = content[end + 4:].lstrip("\n")

    fm = {}
    current_key = None
    current_list = None

    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # List item
        if stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
                fm[current_key] = current_list
            current_list.append(stripped[2:].strip().strip('"').strip("'"))
            continue

        # Key-value
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            current_key = key
            current_list = None
            if value:
                fm[key] = value
            # If no value, might be followed by list items

    return fm, body


def build_mdc_frontmatter(description: str, globs: list[str]) -> str:
    """Build MDC frontmatter string."""
    lines = ["---"]
    lines.append(f'description: "{description}"')
    if globs:
        globs_str = ", ".join(f'"{g}"' for g in globs)
        lines.append(f"globs: [{globs_str}]")
    lines.append("alwaysApply: false")
    lines.append("---")
    return "\n".join(lines)


def build_skill_frontmatter(fm: dict) -> str:
    """Build cleaned SKILL.md frontmatter (only name and description)."""
    lines = ["---"]
    if "name" in fm:
        name = fm["name"]
        if " " in name or ":" in name:
            lines.append(f'name: "{name}"')
        else:
            lines.append(f"name: {name}")
    if "description" in fm:
        desc = fm["description"]
        if not desc.startswith('"'):
            desc = f'"{desc}"'
        lines.append(f"description: {desc}")
    lines.append("---")
    return "\n".join(lines)


# ─── Conversion logic ───────────────────────────────────────────────────────

def convert_rule(source_path: Path, target_path: Path, dry_run: bool) -> str:
    """Convert a rule .md → .mdc with MDC frontmatter."""
    stem = source_path.stem
    config = RULES_CONFIG.get(stem)
    if not config:
        return f"  SKIP (no config): {source_path.name}"

    content = source_path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(content)

    mdc_fm = build_mdc_frontmatter(config["description"], config["globs"])
    result = mdc_fm + "\n\n" + body

    target_file = target_path / f"{stem}.mdc"
    if not dry_run:
        target_file.write_text(result, encoding="utf-8")
    return f"  {'[DRY] ' if dry_run else ''}rule: {source_path.name} → {target_file.name}"


def apply_text_replacements(text: str) -> str:
    """Apply Claude Code tool reference replacements to skill body text."""
    for old, new in SKILL_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    # Clean up double spaces left by removals
    text = re.sub(r"  +", " ", text)
    # Clean up empty parentheses
    text = text.replace(" ()", "")
    text = text.replace("()", "")
    return text


def convert_skill(source_dir: Path, target_dir: Path, dry_run: bool) -> str:
    """Convert a skill directory."""
    skill_name = source_dir.name
    if skill_name in EXCLUDE_SKILLS:
        return f"  SKIP (excluded): {skill_name}"

    skill_md = source_dir / "SKILL.md"
    if not skill_md.exists():
        return f"  SKIP (no SKILL.md): {skill_name}"

    target_skill_dir = target_dir / skill_name
    if not dry_run:
        target_skill_dir.mkdir(parents=True, exist_ok=True)

    # Convert SKILL.md
    content = skill_md.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    if fm:
        new_fm = build_skill_frontmatter(fm)
    else:
        new_fm = "---\n---"

    body = apply_text_replacements(body)
    result = new_fm + "\n\n" + body

    if not dry_run:
        (target_skill_dir / "SKILL.md").write_text(result, encoding="utf-8")

    # Copy scripts/, references/, reference/, docs/, examples/, presets/ directories
    copied_dirs = []
    for subdir_name in ("scripts", "references", "reference", "docs", "examples", "presets", "bin"):
        subdir = source_dir / subdir_name
        if subdir.is_dir():
            target_subdir = target_skill_dir / subdir_name
            if not dry_run:
                if target_subdir.exists():
                    shutil.rmtree(target_subdir)
                shutil.copytree(subdir, target_subdir)
            copied_dirs.append(subdir_name)

    # Copy extra .md files at skill root (not SKILL.md)
    for f in sorted(source_dir.iterdir()):
        if f.is_file() and f.suffix == ".md" and f.name != "SKILL.md":
            if not dry_run:
                shutil.copy2(f, target_skill_dir / f.name)

    extra = f" + {', '.join(copied_dirs)}" if copied_dirs else ""
    return f"  {'[DRY] ' if dry_run else ''}skill: {skill_name}{extra}"


def convert_commands(source_dir: Path, target_dir: Path, dry_run: bool) -> list[str]:
    """Copy commands directory as-is."""
    results = []
    if not source_dir.is_dir():
        return ["  SKIP: no commands/ directory"]

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(source_dir.iterdir()):
        if item.is_file():
            if not dry_run:
                shutil.copy2(item, target_dir / item.name)
            results.append(f"  {'[DRY] ' if dry_run else ''}command: {item.name}")

    return results


def convert_docs(source_dir: Path, target_dir: Path, dry_run: bool) -> list[str]:
    """Copy docs directory as-is.

    Спецификации переносятся, потому что навыки на них ССЫЛАЮТСЯ: комментарии скриптов и SKILL.md
    отправляют читателя в docs/1c-configuration-spec.md за лестницей версий формата и наборами
    GeneratedType. Без переноса эти ссылки в cursor-репозитории вели в пустоту.
    """
    results = []
    if not source_dir.is_dir():
        return ["  SKIP: no docs/ directory"]

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(source_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source_dir)
        if not dry_run:
            (target_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_dir / rel)
        results.append(f"  {'[DRY] ' if dry_run else ''}doc: {rel.as_posix()}")

    return results


def convert_tests(source_dir: Path, target_dir: Path, dry_run: bool) -> list[str]:
    """Перенести регресс-тесты скилов.

    Скрипты в зеркале те же самые, и ломаются они так же. Без тестов дефект здесь виден только
    после того, как его поймали в исходном наборе, а часть скилов зеркала берут отсюда напрямую.
    Раннер разрешает скилы относительно корня репозитория и раскладку не меняет, поэтому набор
    переносится как есть.

    Артефакты прогона - кэш и последний отчет - остаются локальными и не переносятся.
    """
    results = []
    if not source_dir.is_dir():
        return ["  SKIP: no tests/ directory"]

    skip_parts = {".cache", "__pycache__", "node_modules"}
    skip_names = {".last-report.json"}

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for item in sorted(source_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source_dir)
        if skip_parts & set(rel.parts) or rel.name in skip_names:
            continue
        if not dry_run:
            (target_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_dir / rel)
        count += 1
    results.append(f"  {'[DRY] ' if dry_run else ''}перенесено файлов: {count}")
    return results


def convert_workflows(source_dir: Path, target_dir: Path, dry_run: bool) -> list[str]:
    """Перенести описание сборки: без него тесты в зеркале лежат, но не запускаются."""
    results = []
    if not source_dir.is_dir():
        return ["  SKIP: no .github/workflows/"]

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(source_dir.glob("*.yml")):
        if not dry_run:
            # Ветка по умолчанию в зеркале - master, а не main. Без замены сборка
            # зарегистрирована, но не запускается ни на одном коммите: условие не совпадает.
            text = item.read_text(encoding="utf-8").replace("branches: [main]", "branches: [master]")
            (target_dir / item.name).write_text(text, encoding="utf-8", newline="")
        results.append(f"  {'[DRY] ' if dry_run else ''}workflow: {item.name} (ветка master)")
    return results


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description="Convert claude-code-skills-1c → cursor-1c-skills"
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to claude-code-skills-1c repository",
    )
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Path to cursor-1c-skills output directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files",
    )
    args = parser.parse_args()

    source: Path = args.source.resolve()
    target: Path = args.target.resolve()
    dry_run: bool = args.dry_run

    if not source.is_dir():
        print(f"ERROR: Source directory not found: {source}", file=sys.stderr)
        sys.exit(1)

    if not (source / "rules").is_dir() or not (source / "skills").is_dir():
        print(f"ERROR: Source doesn't look like claude-code-skills-1c (missing rules/ or skills/)", file=sys.stderr)
        sys.exit(1)

    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    # Convert rules
    print("=== Rules (.md → .mdc) ===")
    rules_target = target / "rules"
    if not dry_run:
        rules_target.mkdir(parents=True, exist_ok=True)

    rules_count = 0
    for md_file in sorted((source / "rules").glob("*.md")):
        msg = convert_rule(md_file, rules_target, dry_run)
        print(msg)
        if "SKIP" not in msg:
            rules_count += 1

    # Convert skills
    print("\n=== Skills ===")
    skills_target = target / "skills"
    if not dry_run:
        skills_target.mkdir(parents=True, exist_ok=True)

    skills_count = 0
    for skill_dir in sorted((source / "skills").iterdir()):
        if skill_dir.is_dir():
            msg = convert_skill(skill_dir, skills_target, dry_run)
            print(msg)
            if "SKIP" not in msg:
                skills_count += 1

    # Copy commands
    print("\n=== Commands ===")
    commands_source = source / "commands"
    commands_target = target / "commands"
    cmd_count = 0
    for msg in convert_commands(commands_source, commands_target, dry_run):
        print(msg)
        if "SKIP" not in msg:
            cmd_count += 1

    # Copy docs
    print("\n=== Docs ===")
    doc_count = 0
    for msg in convert_docs(source / "docs", target / "docs", dry_run):
        if "SKIP" in msg:
            print(msg)
        else:
            doc_count += 1
    print(f"  {'[DRY] ' if dry_run else ''}перенесено файлов: {doc_count}")

    # Copy tests
    print("\n=== Tests ===")
    for msg in convert_tests(source / "tests", target / "tests", dry_run):
        print(msg)

    # Copy CI workflows
    print("\n=== CI ===")
    for msg in convert_workflows(source / ".github" / "workflows",
                                 target / ".github" / "workflows", dry_run):
        print(msg)

    # Summary
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Done: {rules_count} rules, {skills_count} skills, {cmd_count} commands, "
          f"{doc_count} docs")


if __name__ == "__main__":
    main()
