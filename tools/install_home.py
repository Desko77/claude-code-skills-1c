#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Установщик домашнего контура набора: компоненты репозитория -> ~/.claude.

Компонент - каталог репозитория и его адресат в домашнем каталоге (таблица
COMPONENTS ниже; расширяется добавлением строки). Каждая установленная копия
регистрируется в манифесте <home>/.install-manifest.json с sha256.

Правило слияния при установке (файл в доме):

  отсутствует или совпадает с манифестом   - переписать версией репозитория;
  отличается и от манифеста, и от репозитория - конфликт: не трогать,
  перечислить, код выхода 1 (без --force);
  совпадает с репозиторием (вне манифеста)  - переписать и записать в манифест.

  --force  конфликтный файл резервируется в <home>/backup/install-<время>/
           и переписывается, код выхода 0;
  --dry-run показать план, ничего не менять.

Режим --check файлы не пишет: 0 - все файлы выбранных компонентов в доме
совпадают с репозиторием, 1 - есть расхождения (перечислены).

Использование:
  python tools/install_home.py install
  python tools/install_home.py install --components agents
  python tools/install_home.py install --home <каталог> --force
  python tools/install_home.py --check
  python tools/install_home.py install --dry-run

Коды выхода: 0 успех или совпадение, 1 конфликт или расхождение, 2 ошибка.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = ".install-manifest.json"

# Таблица компонентов: имя -> исходный каталог репозитория и адресат в <home>.
# Необязательный ключ include - список относительных путей или glob-шаблонов
# внутри source; без него ставятся все файлы каталога source.
# Порядок = порядок установки. Новые компоненты добавляются строкой сюда,
# остальная логика установщика не меняется.
COMPONENTS: dict[str, dict[str, object]] = {
    "agents": {"source": "agents", "target": "agents"},
    "hooks": {"source": "hooks", "target": "hooks/1c-skills"},
    "tools": {"source": "tools", "target": "tools/1c-skills",
              "include": ["install_home.py", "changeset.py", "change_profile.py",
                          "evidence.py", "quality_events.py"]},
    "commands": {"source": "commands", "target": "commands",
                 "include": ["quality.md"]},
}


TEXT_SUFFIXES = {".md", ".json", ".txt", ".py", ".mjs", ".js", ".yml", ".yaml", ".ps1", ".bsl"}


def sha256_file(path: Path) -> str:
    """Хеш содержимого файла.

    Текстовые файлы (по расширению из TEXT_SUFFIXES) хешируются с концами строк,
    приведенными к LF: редактор, сменивший LF на CRLF, не должен давать расхождение
    или конфликт. Бинарные файлы хешируются как есть.
    """
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_manifest(home: Path) -> dict:
    """Прочитать манифест установки из home; отсутствующий манифест - пустой.

    Нечитаемый или испорченный манифест (не JSON, корень не объект, секция files
    не словарь) завершает работу кодом 2 с диагностикой в stderr.
    """
    manifest_path = home / MANIFEST_NAME
    if not manifest_path.exists():
        return {"files": {}}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"манифест не читается ({manifest_path}): {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        print(f"манифест испорчен: секция files не словарь ({manifest_path})", file=sys.stderr)
        sys.exit(2)
    return data


def save_manifest(home: Path, manifest: dict) -> None:
    """Записать манифест установки в home детерминированно (сортировка ключей, LF)."""
    manifest_path = home / MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Детерминированная запись: сортировка ключей и стабильные отступы дают
    # побайтово одинаковый манифест при повторной установке без изменений.
    text = json.dumps({"files": dict(sorted(manifest["files"].items()))},
                      ensure_ascii=False, indent=2) + "\n"
    manifest_path.write_text(text, encoding="utf-8", newline="\n")


def collect_files(component: str) -> list[tuple[Path, Path, str]]:
    """Файлы компонента: (исходник репозитория, адресат в home, ключ манифеста).

    Если в описании компонента есть ключ include, берутся только файлы, чей
    относительный путь внутри source совпадает с одним из его элементов
    (точный путь или glob-шаблон). Пустой результат после фильтра - код 2.
    """
    spec = COMPONENTS[component]
    source_dir = REPO_ROOT / spec["source"]
    if not source_dir.is_dir():
        print(f"исходников компонента нет: {source_dir}", file=sys.stderr)
        sys.exit(2)
    include = spec.get("include")
    result = []
    for file in sorted(source_dir.rglob("*")):
        if file.is_file():
            rel = file.relative_to(source_dir).as_posix()
            if include and not any(fnmatch.fnmatchcase(rel, pattern) for pattern in include):
                continue
            key = f"{spec['target']}/{rel}"
            result.append((file, Path(spec["target"]) / rel, key))
    if not result:
        print(f"компонент {component} пуст: файлов в {source_dir} нет"
              + (" после фильтра include" if include else ""), file=sys.stderr)
        sys.exit(2)
    return result


def parse_components(arg: str | None) -> list[str]:
    """Разобрать список компонентов из довода; пусто - все компоненты; неизвестное имя - код 2."""
    names = [name.strip() for name in (arg or "").split(",") if name.strip()] if arg else list(COMPONENTS)
    unknown = [name for name in names if name not in COMPONENTS]
    if unknown:
        print(f"неизвестные компоненты: {', '.join(unknown)}; доступны: {', '.join(COMPONENTS)}",
              file=sys.stderr)
        sys.exit(2)
    return names


def cmd_install(home: Path, components: list[str], force: bool, dry_run: bool) -> int:
    """Установить компоненты в home с учетом манифеста.

    Файл, совпадающий с манифестом или отсутствующий, переписывается; измененный и не
    по манифесту, и не как в репозитории - конфликт (не тронут, код 1), при force -
    резервная копия и перепись. При dry_run ничего не пишется, включая каталоги резерва.
    """
    manifest = load_manifest(home)
    conflicts: list[str] = []
    # Одна метка времени на прогон: несколько конфликтных файлов уходят в один каталог резерва.
    backup_stamp = time.strftime("%Y%m%d-%H%M%S")
    for component in components:
        for src, dst, key in collect_files(component):
            repo_sha = sha256_file(src)
            dst_path = home / dst
            if dst_path.exists():
                home_sha = sha256_file(dst_path)
                known = manifest["files"].get(key)
                if home_sha != known and home_sha != repo_sha:
                    if not force:
                        print(f"КОНФЛИКТ  {dst}: изменен снаружи (не по манифесту и не как в репозитории), не тронут")
                        conflicts.append(key)
                        continue
                    backup = home / "backup" / f"install-{backup_stamp}" / dst
                    if not dry_run:
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(dst_path, backup)
                    print(f"РЕЗЕРВ    {dst} -> {backup}")
            action = "обновлен" if dst_path.exists() else "установлен"
            if not dry_run:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_path)
            manifest["files"][key] = repo_sha
            print(f"{action:9} {dst}")
    if not dry_run:
        save_manifest(home, manifest)
    if conflicts:
        print(f"конфликтов: {len(conflicts)}; файлы не тронуты, манифест их не содержит")
        return 1
    print("готово" + (" (сухой прогон, изменения не записаны)" if dry_run else ""))
    return 0


def cmd_check(home: Path, components: list[str]) -> int:
    """Сверить файлы компонентов в home с репозиторием без записи; расхождения - код 1."""
    drifted = 0
    for component in components:
        for src, dst, _key in collect_files(component):
            dst_path = home / dst
            if not dst_path.exists():
                print(f"РАСХОЖДЕНИЕ  {dst}: файл отсутствует")
                drifted += 1
            elif sha256_file(dst_path) != sha256_file(src):
                print(f"РАСХОЖДЕНИЕ  {dst}: отличается от репозитория")
                drifted += 1
            else:
                print(f"OK           {dst}")
    if drifted:
        print(f"расхождений: {drifted}")
        return 1
    print("все файлы компонентов совпадают с репозиторием")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI: install (по умолчанию) либо --check.

    Коды выхода: 0 - выполнено, 1 - конфликты или расхождения, 2 - ошибка
    (неверный довод, испорченный манифест, отказ файловой системы).
    """
    parser = argparse.ArgumentParser(
        description="Установка компонентов набора в домашний каталог ~/.claude с манифестом и резервными копиями.")
    parser.add_argument("command", nargs="?", default="install", choices=["install"],
                        help="команда (сейчас одна: install)")
    parser.add_argument("--components", metavar="СПИСОК",
                        help="компоненты через запятую (по умолчанию все: %s)" % ", ".join(COMPONENTS))
    parser.add_argument("--home", type=Path, default=Path.home() / ".claude",
                        metavar="КАТАЛОГ", help="домашний каталог (по умолчанию ~/.claude)")
    parser.add_argument("--force", action="store_true",
                        help="конфликтные файлы резервируются и переписываются")
    parser.add_argument("--dry-run", action="store_true", help="показать план без записи")
    parser.add_argument("--check", action="store_true",
                        help="только проверка совпадения с репозиторием (файлы не пишет)")
    args = parser.parse_args(argv)

    components = parse_components(args.components)
    try:
        if args.check:
            return cmd_check(args.home, components)
        return cmd_install(args.home, components, args.force, args.dry_run)
    except OSError as exc:
        # Отказ файловой системы (нет прав, диск, занятый файл) - ошибка установки,
        # а не конфликт: код 2, чтобы вызывающий отличал ее от кода 1.
        print(f"ошибка файловой системы: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
