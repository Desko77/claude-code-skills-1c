#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты канонического множества изменений: tools/changeset.py и hooks/_changeset.mjs.

Каждый сценарий строит временный git-репозиторий и запускает обе CLI с --json:
вывод обязан совпадать байт в байт, а статусы - с ожиданиями спецификации
skills/1c-code-review/references/changeset.md. Двойной запуск Python-CLI проверяет
детерминированность diffHash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PY_CLI = REPO_ROOT / "tools" / "changeset.py"
NODE_CLI = REPO_ROOT / "hooks" / "_changeset.mjs"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def u(text: str) -> bytes:
    """Байты UTF-8 из строкового литерала (в bytes-литерале кириллица недопустима)."""
    return text.encode("utf-8")


def run_cli(executable_args: list[str], repo: Path, base: str | None = None) -> subprocess.CompletedProcess:
    """Запустить CLI с --json; вывод байтовый, чтобы сверять байт в байт."""
    args = [*executable_args, "--repo", str(repo), "--json"]
    if base is not None:
        args += ["--base", base]
    return subprocess.run(args, capture_output=True)


def run_py(repo: Path, base: str | None = None) -> subprocess.CompletedProcess:
    return run_cli([sys.executable, "-X", "utf8", str(PY_CLI)], repo, base)


def run_node(repo: Path, base: str | None = None) -> subprocess.CompletedProcess:
    return run_cli(["node", str(NODE_CLI)], repo, base)


def git(repo: Path, *args: str) -> None:
    """Выполнить git в репозитории; отказ команды - ошибка теста с выводом git."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr.decode('utf-8', errors='replace')}"


def make_repo(tmp: Path) -> Path:
    """Создать временный git-репозиторий с настройками, не зависящими от машины."""
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "core.quotepath", "false")
    return repo


def write_file(repo: Path, rel: str, data: bytes) -> None:
    """Записать файл байтами как есть (концы строк значимы для sha256)."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def commit_all(repo: Path, message: str = "изменение") -> None:
    """Закоммитить все изменения репозитория (хуки и подпись выключены)."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, "--no-gpg-sign", "--no-verify")


def head_sha(repo: Path) -> str:
    """SHA-1 текущего коммита репозитория."""
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True)
    assert proc.returncode == 0
    return proc.stdout.decode("utf-8").strip()


class ChangesetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def assert_scenario(self, repo: Path, base: str | None = None, *,
                        expect: dict[str, dict] | None = None,
                        absent: list[str] | None = None,
                        sha_expect: dict[str, bytes] | None = None,
                        empty: bool = False) -> dict:
        """Сверить обе CLI на сценарии: код 0, выводы совпадают байт в байт, статусы верны.

        Возвращает разобранный JSON множества. Два запуска Python-CLI - проверка
        детерминированности: вывод стабилен между запусками.
        """
        py1 = run_py(repo, base)
        self.assertEqual(py1.returncode, 0, py1.stderr.decode("utf-8", errors="replace"))
        py2 = run_py(repo, base)
        node = run_node(repo, base)
        self.assertEqual(node.returncode, 0, node.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(py1.stdout, node.stdout, "вывод Python и Node расходится")
        self.assertEqual(py1.stdout, py2.stdout, "вывод Python недетерминирован")
        data = json.loads(py1.stdout.decode("utf-8"))
        self.assertEqual(data["base"], head_sha(repo) if base is None else base)
        entries = {entry["path"]: entry for entry in data["files"]}
        for path, spec in (expect or {}).items():
            self.assertIn(path, entries, f"путь отсутствует в множестве: {path}")
            self.assertEqual(entries[path]["status"], spec["status"],
                             f"статус {path}: {entries[path]}")
            if "renamedFrom" in spec:
                self.assertEqual(entries[path].get("renamedFrom"), spec["renamedFrom"])
            else:
                self.assertNotIn("renamedFrom", entries[path])
        for path in absent or []:
            self.assertNotIn(path, entries, f"путь не должен входить в множество: {path}")
        for path, content in (sha_expect or {}).items():
            self.assertEqual(entries[path]["sha256"], hashlib.sha256(content).hexdigest(),
                             f"sha256 {path} не равен хешу содержимого рабочего файла")
        if empty:
            self.assertEqual(data["files"], [])
            self.assertEqual(data["diffHash"], EMPTY_SHA256)
        return data

    def test_clean_repository(self):
        """Чистый репозиторий: пустое множество, diffHash - SHA-256 пустой строки."""
        repo = make_repo(self.tmp)
        write_file(repo, "a.txt", u("содержимое\n"))
        commit_all(repo)
        self.assert_scenario(repo, empty=True)

    def test_dirty_then_modified_again(self):
        """Файл изменен и затем изменен еще раз: одна запись modified с хешем последней версии."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        write_file(repo, "f.txt", u("версия три\n"))
        self.assert_scenario(repo, expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия три\n")})

    def test_staged_only(self):
        """Изменение только в индексе (staged): modified с хешем рабочего файла."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        git(repo, "add", "f.txt")
        self.assert_scenario(repo, expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия два\n")})

    def test_staged_plus_tree_edit(self):
        """Изменение в индексе плюс правка в рабочем дереве: modified с хешем рабочей версии."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        git(repo, "add", "f.txt")
        write_file(repo, "f.txt", u("версия три\n"))
        self.assert_scenario(repo, expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия три\n")})

    def test_staged_reverted_tree(self):
        """Правка в индексе, рабочее дерево возвращено к базовому содержимому: записи нет."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        git(repo, "add", "f.txt")
        write_file(repo, "f.txt", u("версия один\n"))
        self.assert_scenario(repo, empty=True)

    def test_untracked_added(self):
        """Новый неотслеживаемый файл: added с хешем содержимого."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "new.txt", u("новый файл\n"))
        self.assert_scenario(repo, expect={"new.txt": {"status": "added"}},
                             sha_expect={"new.txt": u("новый файл\n")})

    def test_deleted(self):
        """Удаленный файл: deleted, sha256 null."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("содержимое\n"))
        commit_all(repo)
        (repo / "f.txt").unlink()
        data = self.assert_scenario(repo, expect={"f.txt": {"status": "deleted"}})
        entry = {e["path"]: e for e in data["files"]}["f.txt"]
        self.assertIsNone(entry["sha256"])

    def test_renamed(self):
        """Переименование (git mv): renamed с renamedFrom, хеш содержимого рабочего файла."""
        repo = make_repo(self.tmp)
        write_file(repo, "a.txt", u("строка один\nстрока два\n"))
        commit_all(repo)
        git(repo, "mv", "a.txt", "b.txt")
        self.assert_scenario(repo,
                             expect={"b.txt": {"status": "renamed", "renamedFrom": "a.txt"}},
                             sha_expect={"b.txt": u("строка один\nстрока два\n")},
                             absent=["a.txt"])

    def test_renamed_edited(self):
        """Переименование с правкой содержимого: renamed, хеш новой версии."""
        repo = make_repo(self.tmp)
        write_file(repo, "a.txt", u("строка один\nстрока два\nстрока три\n"))
        commit_all(repo)
        git(repo, "mv", "a.txt", "b.txt")
        write_file(repo, "b.txt", u("строка один\nстрока два\nстрока три\nстрока четыре\n"))
        self.assert_scenario(repo,
                             expect={"b.txt": {"status": "renamed", "renamedFrom": "a.txt"}},
                             sha_expect={"b.txt": u("строка один\nстрока два\nстрока три\nстрока четыре\n")},
                             absent=["a.txt"])

    def test_ignored_excluded(self):
        """Игнорируемый файл в множество не входит; соседний обычный входит."""
        repo = make_repo(self.tmp)
        write_file(repo, ".gitignore", b"ignored.txt\n")
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "ignored.txt", u("мусор\n"))
        write_file(repo, "other.txt", u("обычный\n"))
        self.assert_scenario(repo, expect={"other.txt": {"status": "added"}},
                             absent=["ignored.txt"])

    def test_crlf_vs_lf(self):
        """CRLF и LF дают разные sha256: хеш считается от сырых байтов файла."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "crlf.txt", u("текст\r\nвторая строка\r\n"))
        write_file(repo, "lf.txt", u("текст\nвторая строка\n"))
        data = self.assert_scenario(
            repo,
            expect={"crlf.txt": {"status": "added"}, "lf.txt": {"status": "added"}},
            sha_expect={"crlf.txt": u("текст\r\nвторая строка\r\n"),
                        "lf.txt": u("текст\nвторая строка\n")})
        entries = {e["path"]: e for e in data["files"]}
        self.assertNotEqual(entries["crlf.txt"]["sha256"], entries["lf.txt"]["sha256"])

    def test_cyrillic_space_path(self):
        """Путь с кириллицей и пробелом: путь в множестве как есть (NFC), хеш содержимого."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        rel = "данные/файл с пробелом.txt"
        write_file(repo, rel, u("содержимое с кириллицей\n"))
        self.assert_scenario(repo, expect={rel: {"status": "added"}},
                             sha_expect={rel: u("содержимое с кириллицей\n")})

    def test_nested_directories(self):
        """Файл во вложенном каталоге: полный относительный путь от корня репозитория."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "deep/a/b/c/file.txt", u("глубоко\n"))
        self.assert_scenario(repo, expect={"deep/a/b/c/file.txt": {"status": "added"}},
                             sha_expect={"deep/a/b/c/file.txt": u("глубоко\n")})

    def test_add_then_delete_from_tree(self):
        """Файл добавлен в индекс и удален из рабочего дерева: записи нет (в base его нет)."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("недолгий\n"))
        git(repo, "add", "f.txt")
        (repo / "f.txt").unlink()
        self.assert_scenario(repo, empty=True)

    def test_rm_cached_conflict(self):
        """git rm --cached: файл есть в base и на диске, но не в индексе.

        Отличающийся от base файл - modified; возвращенный к базовому содержимому -
        записи нет (арбитраж blob-хешами, git diff такой путь видит удалением).
        """
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        git(repo, "rm", "-q", "--cached", "f.txt")
        self.assert_scenario(repo, expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия два\n")})
        write_file(repo, "f.txt", u("версия один\n"))
        self.assert_scenario(repo, empty=True)

    def test_explicit_base(self):
        """Явный base раньше HEAD: изменение между коммитами входит в множество."""
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo, "первый")
        first = head_sha(repo)
        write_file(repo, "f.txt", u("версия два\n"))
        commit_all(repo, "второй")
        self.assert_scenario(repo, base=first,
                             expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия два\n")})

    def test_not_a_repository(self):
        """Каталог без .git: обе CLI завершаются кодом 2 без traceback."""
        plain = self.tmp / "plain"
        plain.mkdir()
        (plain / "file.txt").write_text("не репозиторий", encoding="utf-8")
        for result in (run_py(plain), run_node(plain)):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn(b"Traceback", run_py(plain).stderr)


if __name__ == "__main__":
    unittest.main()
