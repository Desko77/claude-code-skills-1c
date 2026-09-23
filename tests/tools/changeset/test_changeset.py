#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты канонического множества изменений: tools/changeset.py и hooks/_changeset.mjs.

Каждый сценарий строит временный git-репозиторий и запускает обе CLI с --json:
вывод обязан совпадать байт в байт, а статусы - с ожиданиями спецификации
skills/1c-code-review/references/changeset.md. Двойной запуск Python-CLI проверяет
детерминированность diffHash.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
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


def py_module():
    """Модуль tools/changeset.py, импортированный по пути: прямой вызов функций без CLI."""
    spec = importlib.util.spec_from_file_location("changeset_py", PY_CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NODE_PAYLOAD_SCRIPT = (
    "const {pathToFileURL} = require('node:url');"
    "import(pathToFileURL(process.env.CHANGESET_MJS).href).then((m) => {"
    "const files = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));"
    "process.stdout.write(m.buildDiffPayload(files).toString('base64'));"
    "}, (e) => {console.error(e); process.exit(1);});"
)


def node_payload(files: list[dict]) -> bytes:
    """Байты buildDiffPayload Node-реализации на синтетических записях (base64 в stdout).

    Путь к модулю передается переменной окружения, а не аргументом: аргумент при
    node -e становится argv[1], и CLI-защитник _changeset.mjs запустил бы CLI.
    """
    env = {**os.environ, "CHANGESET_MJS": str(NODE_CLI)}
    proc = subprocess.run(["node", "-e", NODE_PAYLOAD_SCRIPT],
                          input=json.dumps(files).encode("utf-8"), capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return base64.b64decode(proc.stdout)


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


def run_hook(repo: Path, hook: str, payload: dict) -> subprocess.CompletedProcess:
    """Запустить хук с JSON на stdin в каталоге репозитория."""
    return subprocess.run(
        ["node", str(REPO_ROOT / "hooks" / hook)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=str(repo),
    )


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

    def test_diff_hash_framing_synthetic(self):
        """Кадрирование diffHash однозначно: проверка на синтетических записях без ФС.

        Наборы воспроизводят коллизию простого табуляционного формата: конкатенация
        строк двух записей совпадает со строкой одной записи, чей путь содержит
        табуляцию и перевод строки. Префикс длины пути разделяет записи, payload
        двух наборов различается; обе реализации дают одинаковые байты.
        """
        two_files = [
            {"path": "a", "sha256": "h1", "status": "modified"},
            {"path": "b", "sha256": "h2", "status": "added"},
        ]
        one_file = [{"path": "a\tmodified\th1\nb", "sha256": "h2", "status": "added"}]
        old_format = "".join(
            f"{r['path']}\t{r['status']}\t{r['sha256']}\n" for r in two_files)
        self.assertEqual(
            old_format, "a\tmodified\th1\nb\tadded\th2\n",
            "сценарий потерял коллизию табуляционного формата")
        self.assertEqual(old_format,
                         "".join(f"{r['path']}\t{r['status']}\t{r['sha256']}\n"
                                 for r in one_file))
        py = py_module()
        expected_two = b"1:a\0modified\0h1\0" + b"1:b\0added\0h2\0"
        self.assertEqual(py.build_payload(two_files), expected_two)
        self.assertEqual(node_payload(two_files), expected_two)
        expected_one = b"15:a\tmodified\th1\nb\0added\0h2\0"
        self.assertEqual(py.build_payload(one_file), expected_one)
        self.assertEqual(node_payload(one_file), expected_one)
        self.assertNotEqual(py.build_payload(two_files), py.build_payload(one_file))

    @unittest.skipIf(sys.platform == "win32",
                     "имя с табуляцией и переводом строки недопустимо на Windows")
    def test_tab_newline_filename(self):
        """Имя файла с табуляцией и переводом строки: путь читается из -z-вывода целиком."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        rel = "группа\tфайл\nвторой.txt"
        write_file(repo, rel, u("содержимое\n"))
        data = self.assert_scenario(repo, expect={rel: {"status": "added"}},
                                    sha_expect={rel: u("содержимое\n")})
        write_file(repo, rel, u("другое содержимое\n"))
        data_changed = self.assert_scenario(repo, expect={rel: {"status": "added"}})
        self.assertNotEqual(data["diffHash"], data_changed["diffHash"])

    def test_rm_cached_ignored(self):
        """git rm --cached и путь в .gitignore: ls-files --others путь скрывает.

        Арбитраж выполняется по записи deleted с файлом на диске: файл равен base -
        записи нет; изменен - modified; удален с диска - deleted с null.
        """
        repo = make_repo(self.tmp)
        write_file(repo, "f.txt", u("версия один\n"))
        commit_all(repo)
        write_file(repo, ".gitignore", b"f.txt\n")
        git(repo, "rm", "-q", "--cached", "f.txt")
        proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-status", "HEAD"],
                              capture_output=True)
        self.assertIn(b"D\tf.txt", proc.stdout, "diff не видит путь как удаленный")
        proc = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
            capture_output=True)
        self.assertNotIn(b"f.txt", proc.stdout, "untracked-список должен скрывать путь")
        self.assert_scenario(repo, absent=["f.txt"])
        write_file(repo, "f.txt", u("версия два\n"))
        self.assert_scenario(repo, expect={"f.txt": {"status": "modified"}},
                             sha_expect={"f.txt": u("версия два\n")})
        (repo / "f.txt").unlink()
        self.assert_scenario(repo, expect={"f.txt": {"status": "deleted"}})

    def test_gitlink_excluded(self):
        """Гитлинк (подмодуль, режим 160000) исключается при любом статусе diff.

        Измененный gitlink diff дает как M, путь при этом каталог; gitlink в base,
        удаленный из индекса, - как D. Новый gitlink (в base отсутствует) узнается
        по индексу ls-files -s.
        """
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo, "первый")
        sha_one = head_sha(repo)
        write_file(repo, "more.txt", u("еще\n"))
        commit_all(repo, "второй")
        sha_two = head_sha(repo)
        write_file(repo, "sub/inner.txt", u("внутри\n"))
        git(repo, "update-index", "--add", "--cacheinfo", "160000", sha_one, "sub")
        commit_all(repo, "gitlink")
        git(repo, "update-index", "--cacheinfo", "160000", sha_two, "sub")
        proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-status", "-z", "HEAD"],
                              capture_output=True)
        self.assertIn(b"M\0sub\0", proc.stdout, "gitlink не изменен - сценарий пуст")
        self.assert_scenario(repo, absent=["sub"])
        git(repo, "update-index", "--add", "--cacheinfo", "160000", sha_one, "newsub")
        self.assert_scenario(repo, absent=["sub", "newsub"])
        git(repo, "update-index", "--force-remove", "sub")
        proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-status", "-z", "HEAD"],
                              capture_output=True)
        self.assertIn(b"D\0sub\0", proc.stdout, "gitlink не удален - сценарий пуст")
        self.assert_scenario(repo, absent=["sub", "newsub"])

    def test_leading_dash_path(self):
        """Путь с ведущим дефисом: путь-операнд git отделен --, обе CLI завершаются кодом 0.

        Арбитраж blob-хешами (git rm --cached) вызывает hash-object с путем-операндом
        -foo: без -- имя читается как ключ и CLI падает с кодом 2.
        """
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        write_file(repo, "-foo", u("первая\n"))
        self.assert_scenario(repo, expect={"-foo": {"status": "added"}},
                             sha_expect={"-foo": u("первая\n")})
        git(repo, "add", "--", "-foo")
        commit_all(repo)
        write_file(repo, "-foo", u("вторая\n"))
        git(repo, "rm", "-q", "--cached", "--", "-foo")
        self.assert_scenario(repo, expect={"-foo": {"status": "modified"}},
                             sha_expect={"-foo": u("вторая\n")})

    def test_trace_inside_repo_excluded_from_untracked(self):
        """Каталог следа внутри корня не входит в untracked: diffHash стабилен и совпадает.

        Хук пишет событие в QUALITY_STATE_DIR = <корень>/.qstate. Второе событие
        не меняет diffHash. Обычный untracked-файл вне каталога входит в множество.
        На win32 то же при другом регистре пути. Запись git diff внутри каталога
        остается.
        """
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", u("база\n"))
        commit_all(repo)
        state = str(repo / ".qstate")
        saved = os.environ.get("QUALITY_STATE_DIR")
        os.environ["QUALITY_STATE_DIR"] = state

        def restore() -> None:
            if saved is None:
                os.environ.pop("QUALITY_STATE_DIR", None)
            else:
                os.environ["QUALITY_STATE_DIR"] = saved

        self.addCleanup(restore)
        session = "qstate-session"
        baseline = run_hook(repo, "quality-baseline.mjs", {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": str(repo),
            "session_id": session,
        })
        self.assertEqual(baseline.returncode, 0, baseline.stderr.decode("utf-8", errors="replace"))
        self.assertGreaterEqual(len(list((repo / ".qstate").rglob("*.json"))), 1)

        def load_pair() -> dict:
            py = run_py(repo)
            node = run_node(repo)
            self.assertEqual(py.returncode, 0, py.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(node.returncode, 0, node.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(py.stdout, node.stdout, "вывод Python и Node расходится")
            return json.loads(py.stdout.decode("utf-8"))

        def assert_no_trace(data: dict) -> None:
            for entry in data["files"]:
                path = entry["path"].replace("\\", "/")
                folded = path.lower() if sys.platform == "win32" else path
                self.assertFalse(folded == ".qstate" or folded.startswith(".qstate/"), path)

        first = load_pair()
        assert_no_trace(first)
        applied = run_hook(repo, "evidence-writer.mjs", {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__1c-edt__validate_for_export",
            "tool_input": {},
            "tool_response": "Ошибок нет",
            "tool_use_id": "toolu_qstate",
            "cwd": str(repo),
            "session_id": session,
        })
        self.assertEqual(applied.returncode, 0, applied.stderr.decode("utf-8", errors="replace"))
        self.assertGreaterEqual(len(list((repo / ".qstate").rglob("*.json"))), 2)
        second = load_pair()
        assert_no_trace(second)
        self.assertEqual(second["diffHash"], first["diffHash"])
        if sys.platform == "win32":
            os.environ["QUALITY_STATE_DIR"] = "".join(
                ch.upper() if ch.islower() else ch.lower() if ch.isupper() else ch
                for ch in state)
            cased_hook = run_hook(repo, "evidence-writer.mjs", {
                "hook_event_name": "PostToolUse",
                "tool_name": "mcp__1c-edt__validate_for_export",
                "tool_input": {},
                "tool_response": "Ошибок нет",
                "tool_use_id": "toolu_qstate_case",
                "cwd": str(repo),
                "session_id": session,
            })
            self.assertEqual(cased_hook.returncode, 0,
                             cased_hook.stderr.decode("utf-8", errors="replace"))
            cased = load_pair()
            assert_no_trace(cased)
            self.assertEqual(cased["diffHash"], first["diffHash"])
        write_file(repo, "outside.txt", u("вне\n"))
        control = load_pair()
        assert_no_trace(control)
        self.assertIn("outside.txt", {entry["path"] for entry in control["files"]})
        write_file(repo, ".qstate/pinned.txt", b"v1\n")
        git(repo, "add", "--", ".qstate/pinned.txt")
        git(repo, "commit", "-q", "-m", "pin", "--no-gpg-sign", "--no-verify")
        write_file(repo, ".qstate/pinned.txt", b"v2\n")
        pinned = load_pair()
        by_path = {entry["path"]: entry["status"] for entry in pinned["files"]}
        self.assertEqual(by_path.get(".qstate/pinned.txt"), "modified")
        for path in by_path:
            if path == ".qstate/pinned.txt":
                continue
            folded = path.lower() if sys.platform == "win32" else path
            self.assertFalse(folded == ".qstate" or folded.startswith(".qstate/"), path)

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
