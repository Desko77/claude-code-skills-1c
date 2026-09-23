#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты валидатора следа: tools/evidence.py.

Фикстуры - каталоги событий .claude/.state/quality/<сессия>/events/ во временном
чистом git-репозитории (diffHash прогона стабилен). Каждая ветка вердикта check
--strict - отдельный тест: clean, with_gaps (пропуск и снятие), blocked (нет scope,
устаревший хеш, обязательная без события, critical - в том числе с пропуском и с
поздним applied без critical, без toolUseId, чужое и просроченное снятие,
поврежденный файл, пропуск без класса, пропуск с битой ссылкой, нет probe).
Подкоманды add и render проверяются на запись и формат отчета.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_env import isolate_state_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI = REPO_ROOT / "tools" / "evidence.py"
SESSION = "sess-test"
FUTURE = "2099-01-01T00:00:00+03:00"
PAST = "2020-01-01T00:00:00+03:00"


def load_changeset():
    """Модуль tools/changeset.py по пути: текущий diffHash чистого репозитория."""
    spec = importlib.util.spec_from_file_location("changeset_evidence_test",
                                                  REPO_ROOT / "tools" / "changeset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    """Выполнить git в репозитории; отказ команды - ошибка теста с выводом git."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr.decode('utf-8', errors='replace')}"


def make_clean_repo(tmp: Path) -> Path:
    """Чистый репозиторий с закоммиченным .gitignore на каталог следа.

    diffHash прогона - хеш пустого множества: все события с этим хешем образуют прогон.
    """
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitignore").write_text(".claude/.state/\n", encoding="utf-8")
    (repo / "base.txt").write_text("база\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "база", "--no-gpg-sign", "--no-verify")
    return repo


class Trace:
    """Каталог событий сессии во временном репозитории: запись и чтение фикстур."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.directory = repo / ".claude" / ".state" / "quality" / SESSION / "events"
        self.diff_hash = load_changeset().compute_changeset(repo, "HEAD")["diffHash"]
        self.counter = 0

    def put(self, name: str, payload: dict) -> str:
        """Записать файл события с общими полями; возвращает имя файла."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.counter += 1
        event = {"session": SESSION, "producer": "hook",
                 "at": f"2026-09-22T10:{self.counter // 60:02d}:{self.counter % 60:02d}.000+03:00",
                 "diffHash": self.diff_hash}
        event.update(payload)
        path = self.directory / name
        path.write_text(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
        return name

    def put_raw(self, name: str, text: str) -> None:
        """Записать произвольный текст как файл события (поврежденная фикстура)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_text(text, encoding="utf-8", newline="\n")


def scope(required: list[str]) -> dict:
    """Событие scope с обязательным составом."""
    return {"type": "scope", "volume": {"class": "C1", "bslLines": 5, "bslFiles": 1},
            "archetypes": ["любой BSL"], "env": ["edt"], "driver": "объем: 5 строк BSL",
            "required": required, "analyzerConfig": "project-config", "vendorCopy": None}


def applied(check: str, tool_use_id: str = "tool-1", status: str = "pass",
            critical: int = 0, major: int = 0, minor: int = 0) -> dict:
    """Событие applied: выполненная проверка с итогом."""
    return {"type": "applied", "check": check, "detector": check, "env": "edt",
            "level": "semantic", "target": "src/module.bsl", "toolUseId": tool_use_id,
            "inputHash": "in", "responseHash": "out",
            "outcome": {"status": status, "critical": critical, "major": major,
                        "minor": minor}}


def probe(source: str, status: str = "ok") -> dict:
    """Событие probe: доступность источника."""
    return {"type": "probe", "source": source, "status": status, "detail": ""}


def run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Запустить evidence.py с --repo и --session."""
    return subprocess.run([sys.executable, "-X", "utf8", str(CLI), *args,
                           "--repo", str(repo), "--session", SESSION],
                          capture_output=True)


def check(repo: Path, base: str = "HEAD") -> subprocess.CompletedProcess:
    """Запустить check --strict; base нужен для фикстуры устаревшего хеша."""
    return run_cli(repo, "check", "--strict", "--base", base)


class EvidenceCheckTests(unittest.TestCase):
    def setUp(self):
        isolate_state_dir(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_clean_repo(self.tmp)
        self.trace = Trace(self.repo)

    def test_clean(self):
        """Все проверки applied без critical, probe ok по источникам: код 0."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(
            ["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100200-000-hook-a2.json",
                       applied("ask_1c_ai@edt", "t2", "findings", major=2))
        self.trace.put("2026-09-22T100300-000-cli-p1.json", probe("ai-edt"))
        self.trace.put("2026-09-22T100400-000-cli-p2.json", probe("naparnik"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("чисто", proc.stdout.decode("utf-8"))

    def test_clean_empty_required(self):
        """scope без обязательных проверок (C0): вердикт чисто без событий."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope([]))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", errors="replace"))

    def test_last_scope_wins(self):
        """Два scope с одним хешем: прогон строится по последнему."""
        self.trace.put("2026-09-22T100000-000-profile-s1.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-profile-s2.json",
                       scope(["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100200-000-hook-a1.json", applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100300-000-hook-a2.json", applied("ask_1c_ai@edt", "t2"))
        self.trace.put("2026-09-22T100400-000-cli-p1.json", probe("ai-edt"))
        self.trace.put("2026-09-22T100500-000-cli-p2.json", probe("naparnik"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", errors="replace"))

    def test_with_gaps_skipped(self):
        """Пропуск not_applicable закрывает проверку с пробелом: код 1."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(
            ["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100200-000-cli-s1.json",
                       {"type": "skipped", "check": "ask_1c_ai@edt",
                        "class": "not_applicable", "reason": "правка только документации"})
        self.trace.put("2026-09-22T100300-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8", errors="replace"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("с пробелами", out)
        self.assertIn("пробел: ask_1c_ai@edt", out)

    def test_with_gaps_skipped_tool_unavailable(self):
        """Пропуск tool_unavailable со ссылкой на failed: код 1, не блокировка."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        ref = self.trace.put("2026-09-22T100100-000-hook-f1.json",
                             {"type": "failed", "check": "code_review@edt",
                              "detector": "code_review", "toolUseId": "t1",
                              "error": "timeout"})
        self.trace.put("2026-09-22T100200-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "tool_unavailable", "ref": ref})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8", errors="replace"))

    def test_with_gaps_release(self):
        """Действующее снятие закрывает applied с critical: код 1, не блокировка."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8", errors="replace"))

    def test_blocked_no_scope(self):
        """События есть, scope нет: код 3."""
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("нет scope", proc.stdout.decode("utf-8"))

    def test_blocked_stale_hash(self):
        """scope с чужим (устаревшим) diffHash: код 3, прогон устарел."""
        self.directory_put_stale()
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("нет scope", proc.stdout.decode("utf-8"))

    def directory_put_stale(self) -> None:
        """scope с заведомо несовпадающим diffHash."""
        self.trace.directory.mkdir(parents=True, exist_ok=True)
        event = {"type": "scope", "session": SESSION, "producer": "profile",
                 "at": "2026-09-22T10:0000.000+03:00", "diffHash": "0" * 64,
                 "required": ["code_review@edt"], "analyzerConfig": "project-config"}
        (self.trace.directory / "2026-09-22T100000-000-profile-scope.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")

    def test_blocked_required_without_event(self):
        """Обязательная проверка без события: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(
            ["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("обязательная проверка без события: ask_1c_ai@edt",
                      proc.stdout.decode("utf-8"))

    def test_blocked_critical(self):
        """applied с critical без снятия: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=2, major=1))
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("critical", proc.stdout.decode("utf-8"))

    def test_blocked_critical_with_valid_skip(self):
        """critical плюс валидный skipped той же проверки: пропуск не перекрывает, код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        ref = self.trace.put("2026-09-22T100100-000-hook-f1.json",
                             {"type": "failed", "check": "code_review@edt",
                              "detector": "code_review", "toolUseId": "t1",
                              "error": "timeout"})
        self.trace.put("2026-09-22T100200-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100300-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "tool_unavailable", "ref": ref})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("applied с critical без снятия: code_review@edt",
                      proc.stdout.decode("utf-8"))

    def test_blocked_critical_with_later_pass(self):
        """critical плюс позднее applied без critical той же проверки: код 3, не clean."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-a2.json",
                       applied("code_review@edt", "t2", "pass"))
        self.trace.put("2026-09-22T100300-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("applied с critical без снятия: code_review@edt",
                      proc.stdout.decode("utf-8"))

    def test_with_gaps_critical_release_beats_skip(self):
        """critical плюс действующее release: снятие перекрывает и critical, и skipped."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "not_applicable", "reason": "правка документации"})
        self.trace.put("2026-09-22T100300-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("с пробелами", proc.stdout.decode("utf-8"))
        self.assertIn("пробел: code_review@edt", proc.stdout.decode("utf-8"))

    def test_blocked_no_tool_use_id(self):
        """applied без toolUseId: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       {**applied("code_review@edt"), "toolUseId": None})
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("toolUseId", proc.stdout.decode("utf-8"))

    def test_blocked_foreign_release(self):
        """release с чужим diffHash: код 3 независимо от остального прогона."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope([]))
        self.trace.directory.mkdir(parents=True, exist_ok=True)
        event = {"type": "release", "session": SESSION, "producer": "hook",
                 "at": "2026-09-22T10:0100.000+03:00", "diffHash": "1" * 64,
                 "scope": "check", "check": "code_review@edt", "reason": "снятие",
                 "source": "user_prompt", "expiresAt": FUTURE}
        (self.trace.directory / "2026-09-22T100100-000-hook-r1.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("чужим diffHash", proc.stdout.decode("utf-8"))

    def test_blocked_expired_release(self):
        """Просроченное release с текущим хешем: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope([]))
        self.trace.put("2026-09-22T100100-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "снятие", "source": "user_prompt", "expiresAt": PAST})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("просроченное", proc.stdout.decode("utf-8"))

    def test_blocked_corrupt_file(self):
        """Поврежденный файл события: код 3, не исключение."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope([]))
        self.trace.put_raw("2026-09-22T100100-000-hook-x1.json", "{не json")
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("поврежденный", proc.stdout.decode("utf-8"))

    def test_blocked_skip_without_class(self):
        """Пропуск без класса: код 3 (не закрывает проверку пробелом)."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt"})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("без класса", proc.stdout.decode("utf-8"))

    def test_blocked_skip_bad_ref(self):
        """Пропуск tool_unavailable с битой ссылкой: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "tool_unavailable", "ref": "no-such-file.json"})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("без ссылки", proc.stdout.decode("utf-8"))

    def test_blocked_missing_probe(self):
        """Нет probe ok по источнику закрывающего applied: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt", "t1"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("probe ok", proc.stdout.decode("utf-8"))

    def test_blocked_error_call(self):
        """Несуществующая сессия в не-репозитории: код 2."""
        proc = subprocess.run([sys.executable, "-X", "utf8", str(CLI), "check",
                               "--strict", "--repo", str(self.tmp / "empty"),
                               "--session", SESSION], capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ошибка:", proc.stderr.decode("utf-8", errors="replace"))


class EvidenceAddTests(unittest.TestCase):
    def setUp(self):
        isolate_state_dir(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_clean_repo(self.tmp)
        self.trace = Trace(self.repo)

    def test_add_applied_refused(self):
        """add --type applied: код 2, сообщение про хук."""
        proc = run_cli(self.repo, "add", "--type", "applied", "--check", "code_review@edt")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("пишет только хук", proc.stderr.decode("utf-8"))

    def test_add_release_refused(self):
        """add --type release: код 2, сообщение про хук."""
        proc = run_cli(self.repo, "add", "--type", "release")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("пишет только хук", proc.stderr.decode("utf-8"))

    def test_add_skipped_not_applicable(self):
        """add skipped not_applicable: файл события с полем класса и текущим diffHash."""
        proc = run_cli(self.repo, "add", "--type", "skipped",
                       "--check", "ask_1c_ai@edt", "--class", "not_applicable",
                       "--reason", "нет вызовов BSL")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        name = proc.stdout.decode("utf-8").strip()
        event = json.loads((self.trace.directory / name).read_text(encoding="utf-8"))
        self.assertEqual(event["type"], "skipped")
        self.assertEqual(event["class"], "not_applicable")
        self.assertEqual(event["diffHash"], self.trace.diff_hash)
        self.assertEqual(event["producer"], "cli")
        self.assertIn("-cli-", name)

    def test_add_skipped_tool_unavailable_requires_ref(self):
        """add skipped tool_unavailable без ref: код 2."""
        proc = run_cli(self.repo, "add", "--type", "skipped",
                       "--check", "ask_1c_ai@edt", "--class", "tool_unavailable")
        self.assertEqual(proc.returncode, 2)

    def test_add_skipped_unknown_class(self):
        """add skipped с классом вне списка: код 2 (argparse отвергает выбор)."""
        proc = run_cli(self.repo, "add", "--type", "skipped",
                       "--check", "ask_1c_ai@edt", "--class", "lazy")
        self.assertEqual(proc.returncode, 2)

    def test_add_probe_and_not_verified(self):
        """add probe ok и not_verified: события записаны с нужными полями."""
        ok = run_cli(self.repo, "add", "--type", "probe", "--source", "ai-edt",
                     "--status", "ok", "--detail", "жив")
        self.assertEqual(ok.returncode, 0, ok.stderr.decode("utf-8", errors="replace"))
        nv = run_cli(self.repo, "add", "--type", "not_verified",
                     "--dimension", "производительность",
                     "--reason", "нагрузочный прогон не выполнялся")
        self.assertEqual(nv.returncode, 0, nv.stderr.decode("utf-8", errors="replace"))
        files = sorted(self.trace.directory.glob("*.json"))
        self.assertEqual(len(files), 2)
        probe_event = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(probe_event["type"], "probe")

    def test_add_probe_bad_source(self):
        """add probe с неизвестным источником: код 2."""
        proc = run_cli(self.repo, "add", "--type", "probe",
                       "--source", "someone", "--status", "ok")
        self.assertEqual(proc.returncode, 2)

    def test_add_bad_session(self):
        """Сессия с разделителем пути: код 2 (защита каталога)."""
        proc = subprocess.run([sys.executable, "-X", "utf8", str(CLI), "add",
                               "--type", "probe", "--source", "ai-edt", "--status", "ok",
                               "--repo", str(self.repo), "--session", "../escape"],
                              capture_output=True)
        self.assertEqual(proc.returncode, 2)


class EvidenceRenderTests(unittest.TestCase):
    def setUp(self):
        isolate_state_dir(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_clean_repo(self.tmp)
        self.trace = Trace(self.repo)

    def render(self) -> str:
        """Запустить render и вернуть текст отчета."""
        proc = run_cli(self.repo, "render")
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
        return proc.stdout.decode("utf-8")

    def test_render_clean_three_tables(self):
        """render: вердикт clean и все три таблицы, проверка в "Проверено"."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt"))
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        self.trace.put("2026-09-22T100300-000-cli-n1.json",
                       {"type": "not_verified", "dimension": "производительность",
                        "reason": "нагрузочный прогон не выполнялся"})
        text = self.render()
        self.assertIn("Вердикт: clean", text)
        for header in ("## Проверено", "## С пробелами", "## Не проверено"):
            self.assertIn(header, text)
        self.assertIn("code_review@edt", text)
        self.assertIn("probe ok", text)
        self.assertIn("производительность", text)

    def test_render_gap_with_class(self):
        """render: пропуск показывается в "С пробелами" с классом и причиной."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "not_applicable", "reason": "правка документации"})
        text = self.render()
        self.assertIn("Вердикт: with_gaps", text)
        self.assertIn("skipped", text)
        self.assertIn("not_applicable: правка документации", text)

    def test_render_blocked_reasons(self):
        """render: блокирующие причины перечислены, "Не проверено" называет проверку."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt", "ask_1c_ai@edt"]))
        text = self.render()
        self.assertIn("Вердикт: blocked", text)
        self.assertIn("## Блокирующие причины", text)
        self.assertIn("code_review@edt", text.split("## Не проверено")[1])


if __name__ == "__main__":
    unittest.main()
