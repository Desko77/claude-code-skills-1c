#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Каноническое множество изменений git-репозитория относительно базового коммита.

Вычисляет записи изменений (путь, статус, sha256 рабочего файла), хеш множества
diffHash и полный SHA-1 базового коммита. Спецификация -
skills/1c-code-review/references/changeset.md; hooks/_changeset.mjs дает тот же
результат байт в байт (сверяется тестами tests/tools/changeset/).

Использование:
  python tools/changeset.py [--repo <каталог>] [--base <коммит>] [--json]

Без --json печатается таблица для человека.

Коды выхода: 0 расчет выполнен (в том числе пустое множество), 2 каталог не найден,
не git-репозиторий, git недоступен, base не разрешается в коммит.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            # newline="\n" обязательно: без него на Windows перевод строки в пайпе
            # становится \r\n и вывод расходится с hooks/_changeset.mjs байт в байт.
            _reconf(encoding="utf-8", newline="\n")
        except (ValueError, OSError):
            pass


class ChangesetError(Exception):
    """Отказ расчета: git недоступен, каталог не репозиторий, base не разрешается, путь не UTF-8."""


def _run_git(args: list[str], cwd: Path) -> bytes:
    """Выполнить git с аргументами и вернуть stdout; любой отказ - ChangesetError.

    Диагностика git (stderr) попадает в сообщение исключения, вызывающий код
    переводит исключение в код выхода 2 без traceback.
    """
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)
    except OSError as exc:
        raise ChangesetError(f"git недоступен: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ChangesetError(
            f"git {' '.join(args)} завершился с кодом {proc.returncode}: {detail}")
    return proc.stdout


def _decode(data: bytes, what: str) -> str:
    """Декодировать вывод git как UTF-8; невалидные байты - ChangesetError."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChangesetError(f"{what}: путь не является валидным UTF-8") from exc


def _parse_diff(raw: bytes) -> dict[str, dict]:
    """Разобрать git diff --name-status -z в словарь NFC-путь -> запись.

    Запись: status, renamedFrom (None или прежний путь), fsPath (исходный путь из
    вывода git - по нему читается файл). Формат -z: поля записи разделены NUL -
    статус, путь; у R/C после статуса идут ДВА пути: прежний, затем новый
    (не как в git status -z, где первым идет новый).
    """
    tokens = raw.split(b"\0")
    entries: dict[str, dict] = {}
    i = 0
    while i < len(tokens) and tokens[i]:
        code = _decode(tokens[i], "git diff").strip()
        renamed_from = None
        if code.startswith(("R", "C")):
            renamed_from = unicodedata.normalize("NFC", _decode(tokens[i + 1], "git diff"))
            fs_path = _decode(tokens[i + 2], "git diff")
            i += 3
        else:
            fs_path = _decode(tokens[i + 1], "git diff")
            i += 2
        if code.startswith("R"):
            status = "renamed"
        elif code.startswith(("A", "C")):
            status = "added"
        elif code.startswith("D"):
            status = "deleted"
        else:
            status = "modified"
        entries[unicodedata.normalize("NFC", fs_path)] = {
            "status": status,
            "renamedFrom": renamed_from,
            "fsPath": fs_path,
        }
    return entries


def _differs_from_base(top: Path, base: str, fs_path: str) -> bool:
    """Отличается ли рабочий файл от base; решает git с учетом конверсий репозитория.

    Для конфликта "файл есть в base и на диске, но не в индексе" (git rm --cached):
    git diff такой путь всегда видит удалением (untracked для него невидим), поэтому
    отличие решается сравнением blob-хешей - git hash-object --path применяет к
    рабочим байтам фильтры и конверсию пути (как при add), git ls-tree base дает
    хеш блоба в базовом коммите. Путь-операнд отделен --: имя с ведущим дефисом
    иначе читается как ключ, значение --path передается присоединенным (--path=).
    """
    ls_line = _decode(_run_git(["ls-tree", base, "--", fs_path], top), "git ls-tree").strip()
    fields = ls_line.split()
    if len(fields) < 3:
        return True  # пути нет в base; для конфликта с D недостижимо, защита парсера
    base_blob = fields[2].split("\t")[0]
    work_blob = _decode(_run_git(["hash-object", f"--path={fs_path}", "--", fs_path], top),
                        "git hash-object").strip()
    return work_blob != base_blob


def _gitlink_paths(top: Path, base: str) -> set[str]:
    """Пути-гитлинки (подмодули): режим 160000 в индексе или в базовом коммите.

    Gitlink - запись о коммите другого репозитория, в рабочем дереве это каталог;
    спецификация исключает такой путь из множества целиком при любом статусе diff.
    Источники - git ls-files -s -z (индекс: новый gitlink в base отсутствует) и
    git ls-tree -r -z <base> (коммит: gitlink мог быть удален из индекса).
    """
    paths: set[str] = set()
    outputs = (_run_git(["ls-files", "-s", "-z"], top),
               _run_git(["ls-tree", "-r", "-z", base], top))
    for raw in outputs:
        for record in raw.split(b"\0"):
            if not record:
                continue
            # Формат -z у обеих команд: метаданные, TAB, путь, NUL. Первый TAB
            # отделяет метаданные от пути, TAB внутри самого пути не мешает.
            meta, _, path_bytes = record.partition(b"\t")
            if meta.split(b" ", 1)[0] == b"160000":
                paths.add(unicodedata.normalize("NFC", _decode(path_bytes, "git ls-tree")))
    return paths


def build_payload(files: list[dict]) -> bytes:
    """Собрать байты для diffHash из записей, уже отсортированных по байтам пути.

    Запись кадрируется однозначно: длина пути в байтах UTF-8 (десятичная), ":",
    байты пути, NUL, статус, NUL, sha256 либо литерал null, NUL. Префикс длины
    разделяет записи - имя с табуляцией или переводом строки не может сложиться
    в ту же последовательность байтов, что имена других файлов.
    """
    chunks: list[bytes] = []
    for record in files:
        path_bytes = record["path"].encode("utf-8")
        sha = record["sha256"] if record["sha256"] is not None else "null"
        chunks.append(f"{len(path_bytes)}:".encode("ascii") + path_bytes
                      + b"\0" + record["status"].encode("ascii")
                      + b"\0" + sha.encode("ascii") + b"\0")
    return b"".join(chunks)


def compute_changeset(repo_dir: Path | str, base: str = "HEAD") -> dict:
    """Вычислить каноническое множество изменений репозитория относительно base.

    Возвращает {"base": SHA-1, "diffHash": hex, "files": [записи]} по спецификации
    skills/1c-code-review/references/changeset.md. Базовые команды: rev-parse,
    diff --name-status, ls-files --others; untracked-пути сливаются с записями diff
    по правилам спецификации.
    """
    repo_dir = Path(repo_dir)
    if not repo_dir.is_dir():
        raise ChangesetError(f"каталог не найден: {repo_dir}")
    top = Path(_decode(_run_git(["rev-parse", "--show-toplevel"], repo_dir),
                       "git rev-parse").strip())
    base_sha = _decode(_run_git(["rev-parse", "--verify", f"{base}^{{commit}}"], top),
                       "git rev-parse").strip()
    diff_raw = _run_git(["diff", "--name-status", "-z", "-M",
                         "--no-color", "--no-ext-diff", "--no-textconv", base], top)
    untracked_raw = _run_git(["ls-files", "--others", "--exclude-standard", "-z"], top)

    entries = _parse_diff(diff_raw)
    for token in untracked_raw.split(b"\0"):
        if not token:
            continue
        fs_path = _decode(token, "git ls-files")
        path = unicodedata.normalize("NFC", fs_path)
        if path not in entries:
            entries[path] = {"status": "added", "renamedFrom": None, "fsPath": fs_path}
        # Путь, совпавший с записью diff (git rm --cached без игнора), отдельной
        # записью не становится: статус из diff - deleted, арбитраж - в финальном
        # проходе по факту файла на диске.

    gitlinks = _gitlink_paths(top, base)
    files: list[dict] = []
    for path, entry in entries.items():
        if path in gitlinks:
            continue  # подмодуль: gitlink, в рабочем дереве каталог, а не файл
        on_disk = (top / entry["fsPath"]).is_file()
        if entry["status"] == "deleted" and on_disk:
            # Файл есть в base и на диске, но не в индексе (git rm --cached), причем
            # путь игнорируемый - ls-files --others его не показывает. Отличие от
            # base решает сравнение blob-хешей: равен - записи нет, отличается -
            # modified.
            if not _differs_from_base(top, base, entry["fsPath"]):
                continue
            entry = {"status": "modified", "renamedFrom": None, "fsPath": entry["fsPath"]}
        if not on_disk:
            if entry["status"] in ("added", "renamed"):
                continue  # файла нет ни в base, ни в рабочем дереве
            files.append({"path": path, "sha256": None, "status": "deleted"})
            continue
        record = {
            "path": path,
            "sha256": hashlib.sha256((top / entry["fsPath"]).read_bytes()).hexdigest(),
            "status": entry["status"],
        }
        if entry["renamedFrom"] is not None:
            record["renamedFrom"] = entry["renamedFrom"]
        files.append(record)

    files.sort(key=lambda r: r["path"].encode("utf-8"))
    return {
        "base": base_sha,
        "diffHash": hashlib.sha256(build_payload(files)).hexdigest(),
        "files": files,
    }


def render_table(result: dict) -> str:
    """Таблица множества для человека: шапка с base и diffHash, строка на файл."""
    lines = [f"base: {result['base']}",
             f"diffHash: {result['diffHash']}",
             f"файлов: {len(result['files'])}"]
    for record in result["files"]:
        sha = record["sha256"] if record["sha256"] is not None else "-"
        tail = f" <- {record['renamedFrom']}" if "renamedFrom" in record else ""
        lines.append(f"{record['status']:<8} {sha}  {record['path']}{tail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI: JSON (--json) либо таблица; 0 расчет выполнен, 2 отказ."""
    parser = argparse.ArgumentParser(
        description="Каноническое множество изменений git-репозитория относительно базового коммита.")
    parser.add_argument("--repo", type=Path, default=Path("."), metavar="КАТАЛОГ",
                        help="каталог репозитория (по умолчанию текущий)")
    parser.add_argument("--base", default="HEAD", metavar="КОММИТ",
                        help="базовый коммит (по умолчанию HEAD)")
    parser.add_argument("--json", action="store_true",
                        help="вывод JSON вместо таблицы")
    args = parser.parse_args(argv)
    try:
        result = compute_changeset(args.repo, args.base)
    except ChangesetError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
