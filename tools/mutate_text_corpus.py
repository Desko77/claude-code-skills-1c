#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверяет, что гард корпуса сканера текстов действительно ловит поломку.

Зеленый гард, который ничего не проверяет, хуже отсутствующего: по нему делают
вывод о работоспособности. Поэтому гард проверяется мутациями - временными
поломками, каждая из которых ОБЯЗАНА его уронить.

Мутации две на каждую категорию реестра:

  - убрать категорию из реестра: должен упасть гард полноты покрытия;
  - подменить ожидаемый набор в манифесте: должен упасть сравниватель.

Операция названа явно, потому что "снять правило и посмотреть" допускает разные
прочтения. Сам детектор правкой исходника не отключается: точное сравнение
фактического набора с ожидаемым при полном покрытии реестра ловит исчезновение
категории математически.

Прогон восстанавливает файлы даже при падении: мутация, оставшаяся на диске,
испортила бы следующий прогон.

Использование:
  python tools/mutate_text_corpus.py            прогнать все мутации
  python tools/mutate_text_corpus.py --verbose  показать вывод гарда

Коды возврата: 0 гард поймал все мутации, 1 хотя бы одна прошла незамеченной,
2 ошибка запуска.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "tests" / "skills" / "check-text-corpus.mjs"
REGISTRY = REPO_ROOT / "skills" / "humanize-ai-text" / "scripts" / "categories.json"
MANIFEST = (REPO_ROOT / "tests" / "skills" / "cases" / "humanize-scan"
            / "corpus" / "manifest.json")


def guard_fails(verbose: bool) -> bool:
    """Прогнать гард и сказать, упал ли он."""
    result = subprocess.run(["node", str(GUARD)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if verbose:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result.returncode != 0


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    """Точка входа: прогнать мутации по каждой категории реестра."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verbose", action="store_true", help="показать вывод гарда")
    args = parser.parse_args()

    for path in (GUARD, REGISTRY, MANIFEST):
        if not path.is_file():
            print("нет файла: %s" % path, file=sys.stderr)
            return 2

    registry_backup = read(REGISTRY)
    manifest_backup = read(MANIFEST)
    registry = json.loads(registry_backup)
    categories = [c["id"] for c in registry["categories"]]

    if guard_fails(args.verbose):
        print("гард падает ДО мутаций - сначала привести корпус в порядок", file=sys.stderr)
        return 2

    survived: list[str] = []
    try:
        for category in categories:
            # Мутация 1: категории нет в реестре - должна упасть проверка полноты.
            trimmed = dict(registry)
            trimmed["categories"] = [c for c in registry["categories"] if c["id"] != category]
            write(REGISTRY, json.dumps(trimmed, ensure_ascii=False, indent=2) + "\n")
            caught_registry = guard_fails(args.verbose)
            write(REGISTRY, registry_backup)

            # Мутация 2: в манифесте ожидается не та категория - должен упасть
            # сравниватель наборов.
            manifest = json.loads(manifest_backup)
            touched = False
            for entry in manifest["files"]:
                if category in entry["expect"]:
                    entry["expect"] = [c for c in entry["expect"] if c != category]
                    touched = True
                    break
            if touched:
                write(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                caught_manifest = guard_fails(args.verbose)
                write(MANIFEST, manifest_backup)
            else:
                caught_manifest = False

            status = []
            if not caught_registry:
                status.append("реестр")
            if not caught_manifest:
                status.append("манифест")
            if status:
                survived.append("%s (%s)" % (category, ", ".join(status)))
                print("  ПРОШЛА НЕЗАМЕЧЕННОЙ: %s - %s" % (category, ", ".join(status)))
            else:
                print("  поймана: %s" % category)
    finally:
        # Восстановление обязательно даже при падении: мутация на диске испортила
        # бы следующий прогон и выглядела бы как настоящая поломка.
        write(REGISTRY, registry_backup)
        write(MANIFEST, manifest_backup)

    print()
    if survived:
        print("мутаций прошло незамеченными: %d из %d" % (len(survived), len(categories)),
              file=sys.stderr)
        return 1
    print("гард ловит все %d мутаций реестра категорий" % len(categories))
    return 0


if __name__ == "__main__":
    sys.exit(main())
