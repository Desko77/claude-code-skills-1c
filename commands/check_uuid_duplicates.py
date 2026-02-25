#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Проверка и исправление уникальности UUID в MDO-файлах конфигурации 1С.

Сканирует .mdo файлы, извлекает UUID из атрибутов uuid, typeId, valueTypeId
и находит дубликаты — межфайловые (коллизии между объектами) и опционально
внутрифайловые.

Использование:
    python check_uuid_duplicates.py [опции] <path1> [path2] ...

Опции:
    --fix            Исправить найденные дубликаты (заменить на новые UUID).
                     Первое вхождение сохраняется, остальные заменяются.
    --include-intra  Показывать/исправлять также внутрифайловые дубликаты
                     (по умолчанию скрыты — в 1С uuid объекта часто
                     совпадает с typeId в producedTypes того же файла)

Принимает файлы и папки. Папки сканируются рекурсивно (*.mdo).
Код выхода: 0 — дубликатов нет (или все исправлены), 1 — есть дубликаты.
"""

import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path


UUID_PATTERN = re.compile(
    r'\b(uuid|typeId|valueTypeId)="([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"'
)

FLAGS = {"--fix", "--include-intra"}


def collect_mdo_files(paths):
    """Собрать список .mdo файлов из указанных путей."""
    mdo_files = []
    for p in paths:
        path = Path(p)
        if path.is_file() and path.suffix.lower() == ".mdo":
            mdo_files.append(path)
        elif path.is_dir():
            mdo_files.extend(path.rglob("*.mdo"))
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: пропущен '{p}' — не файл и не папка", file=sys.stderr)
    return sorted(set(mdo_files))


def scan_file(filepath):
    """Извлечь UUID из файла с номерами строк."""
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                for match in UUID_PATTERN.finditer(line):
                    attr_name = match.group(1)
                    uuid_value = match.group(2).lower()
                    entries.append((uuid_value, attr_name, line_num))
    except (OSError, UnicodeDecodeError) as e:
        print(f"ПРЕДУПРЕЖДЕНИЕ: ошибка чтения '{filepath}': {e}", file=sys.stderr)
    return entries


def find_duplicates(paths, include_intra=False):
    """Найти дубликаты UUID среди .mdo файлов."""
    uuid_registry = defaultdict(list)
    mdo_files = collect_mdo_files(paths)

    if not mdo_files:
        print("Не найдено .mdo файлов по указанным путям.", file=sys.stderr)
        return {}, 0

    for filepath in mdo_files:
        entries = scan_file(filepath)
        for uuid_value, attr_name, line_num in entries:
            uuid_registry[uuid_value].append({
                "file": str(filepath),
                "line": line_num,
                "attr": attr_name,
            })

    duplicates = {}

    for uuid_value, occurrences in uuid_registry.items():
        if len(occurrences) < 2:
            continue

        files = set(o["file"] for o in occurrences)
        is_cross_file = len(files) > 1

        if not is_cross_file and not include_intra:
            continue

        dup_type = "МЕЖФАЙЛОВЫЙ" if is_cross_file else "ВНУТРИФАЙЛОВЫЙ"
        duplicates[uuid_value] = {
            "type": dup_type,
            "occurrences": occurrences,
        }

    return duplicates, len(mdo_files)


def fix_duplicates(duplicates, base_dir=None):
    """Исправить дубликаты: первое вхождение оставить, остальные заменить.

    Возвращает количество исправленных UUID.
    """
    # Собираем замены по файлам: {filepath: [(line_num, old_uuid, new_uuid), ...]}
    replacements_by_file = defaultdict(list)

    for old_uuid, info in duplicates.items():
        occurrences = info["occurrences"]
        # Первое вхождение оставляем, остальные заменяем
        for occ in occurrences[1:]:
            new_uuid = str(uuid.uuid4())
            replacements_by_file[occ["file"]].append(
                (occ["line"], old_uuid, new_uuid, occ["attr"])
            )

    fixed_count = 0

    for filepath, replacements in sorted(replacements_by_file.items()):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError) as e:
            print(f"  ОШИБКА чтения '{filepath}': {e}", file=sys.stderr)
            continue

        # Индексируем замены по номеру строки
        repl_by_line = defaultdict(list)
        for line_num, old_uuid, new_uuid, attr in replacements:
            repl_by_line[line_num].append((old_uuid, new_uuid, attr))

        changed = False
        for line_num, repls in repl_by_line.items():
            idx = line_num - 1
            if idx >= len(lines):
                continue
            for old_uuid, new_uuid, attr in repls:
                old_frag = f'{attr}="{old_uuid}"'
                new_frag = f'{attr}="{new_uuid}"'
                if old_frag.lower() in lines[idx].lower():
                    # Замена с учётом регистра в файле
                    pattern = re.compile(
                        re.escape(f'{attr}="') + re.escape(old_uuid) + re.escape('"'),
                        re.IGNORECASE,
                    )
                    new_line = pattern.sub(f'{attr}="{new_uuid}"', lines[idx], count=1)
                    if new_line != lines[idx]:
                        lines[idx] = new_line
                        changed = True
                        fixed_count += 1
                        rel = format_path(filepath, base_dir)
                        print(f"  {rel}:{line_num}  [{attr}]  {old_uuid} -> {new_uuid}")

        if changed:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            except OSError as e:
                print(f"  ОШИБКА записи '{filepath}': {e}", file=sys.stderr)

    return fixed_count


def format_path(filepath, base_dir=None):
    """Сократить путь относительно базовой директории."""
    if base_dir:
        try:
            return str(Path(filepath).relative_to(base_dir))
        except ValueError:
            pass
    return filepath


def print_report(duplicates, file_count, base_dir=None):
    """Вывести отчёт о дубликатах."""
    if not duplicates:
        print(f"OK — дубликатов не найдено (проверено файлов: {file_count})")
        return

    cross_file = {k: v for k, v in duplicates.items() if v["type"] == "МЕЖФАЙЛОВЫЙ"}
    intra_file = {k: v for k, v in duplicates.items() if v["type"] == "ВНУТРИФАЙЛОВЫЙ"}

    total = len(duplicates)
    parts = []
    if cross_file:
        parts.append(f"межфайловых: {len(cross_file)}")
    if intra_file:
        parts.append(f"внутрифайловых: {len(intra_file)}")
    detail = ", ".join(parts)

    print(f"НАЙДЕНО ДУБЛИКАТОВ: {total} ({detail})")
    print(f"Проверено файлов: {file_count}")
    print("=" * 80)

    if cross_file:
        print("\n--- МЕЖФАЙЛОВЫЕ ДУБЛИКАТЫ (коллизии между объектами) ---\n")
        for uuid_value, info in sorted(cross_file.items()):
            print(f"  UUID: {uuid_value}")
            for occ in info["occurrences"]:
                path = format_path(occ["file"], base_dir)
                print(f"    {path}:{occ['line']}  [{occ['attr']}]")
            print()

    if intra_file:
        print("\n--- ВНУТРИФАЙЛОВЫЕ ДУБЛИКАТЫ ---\n")
        for uuid_value, info in sorted(intra_file.items()):
            print(f"  UUID: {uuid_value}")
            for occ in info["occurrences"]:
                path = format_path(occ["file"], base_dir)
                print(f"    {path}:{occ['line']}  [{occ['attr']}]")
            print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    do_fix = "--fix" in sys.argv
    include_intra = "--include-intra" in sys.argv
    paths = [a for a in sys.argv[1:] if a not in FLAGS]

    if not paths:
        print(__doc__)
        sys.exit(2)

    base_dir = None
    if len(paths) == 1 and Path(paths[0]).is_dir():
        base_dir = Path(paths[0]).resolve()

    duplicates, file_count = find_duplicates(paths, include_intra)

    if do_fix and duplicates:
        print_report(duplicates, file_count, base_dir)
        print("\n" + "=" * 80)
        print("ИСПРАВЛЕНИЕ ДУБЛИКАТОВ (первое вхождение сохраняется):\n")
        fixed = fix_duplicates(duplicates, base_dir)
        print(f"\nИсправлено UUID: {fixed}")

        # Повторная проверка
        print("\n--- Повторная проверка ---\n")
        duplicates2, file_count2 = find_duplicates(paths, include_intra)
        if not duplicates2:
            print(f"OK — дубликатов не найдено (проверено файлов: {file_count2})")
            sys.exit(0)
        else:
            print(f"ВНИМАНИЕ: осталось дубликатов: {len(duplicates2)}")
            print_report(duplicates2, file_count2, base_dir)
            sys.exit(1)
    else:
        print_report(duplicates, file_count, base_dir)
        sys.exit(1 if duplicates else 0)


if __name__ == "__main__":
    main()
