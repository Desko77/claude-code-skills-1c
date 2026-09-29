#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты валидатора следа: tools/evidence.py.

Фикстуры - каталоги событий сессии во временном чистом git-репозитории
(diffHash прогона стабилен). Каждая ветка вердикта check --strict - отдельный
тест: clean, with_gaps (подтвержденное снятие проверки и снятие gate без scope),
blocked (нет scope, устаревший хеш, обязательная без события, critical - в том
числе с заявкой на пропуск и с поздним applied без critical, без toolUseId,
поврежденный файл, пропуск без класса, пропуск с битой ссылкой, нет probe);
чужое и просроченное снятие игнорируются и вердикт не блокируют. Заявки на
пропуск (skipped, probe down, not_verified) проверку не закрывают, а снятие
засчитывается только с командой в журнале сессии: без журнала, при чужой
проверке в команде и при команде внутри результата инструмента проверка остается
незакрытой. Подкоманды add и render проверяются на запись и формат отчета.
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


def load_quality_events():
    """Модуль tools/quality_events.py: каталог событий вне репозитория."""
    spec = importlib.util.spec_from_file_location("quality_events_evidence_test",
                                                  REPO_ROOT / "tools" / "quality_events.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_clean_repo(tmp: Path) -> Path:
    """Чистый репозиторий с базовым коммитом.

    diffHash прогона - хеш пустого множества: все события с этим хешем образуют прогон.
    След пишется вне дерева.
    """
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "base.txt").write_text("база\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "база", "--no-gpg-sign", "--no-verify")
    return repo


class Trace:
    """Каталог событий сессии во временном репозитории: запись и чтение фикстур."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.directory = load_quality_events().events_dir(repo, SESSION)
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


def check(repo: Path, base: str = "HEAD", transcript=None) -> subprocess.CompletedProcess:
    """Запустить check --strict; transcript - журнал сессии для подтверждений снятия."""
    args = ["check", "--strict", "--base", base]
    if transcript is not None:
        args.extend(["--transcript", str(transcript)])
    return run_cli(repo, *args)


def journal(path: Path, entries: list) -> Path:
    """Журнал сессии: записи пользователя в формате JSONL.

    Запись - либо текст сообщения, либо пара (текст, пометка служебного), либо
    готовый словарь записи (результат инструмента, запись хука).
    """
    lines = []
    for entry in entries:
        if isinstance(entry, dict):
            record = entry
        else:
            text, meta = entry if isinstance(entry, tuple) else (entry, False)
            record = {"type": "user", "isMeta": meta,
                      "message": {"role": "user", "content": text}}
        lines.append(json.dumps(record, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


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

    def test_blocked_skip_request_not_applicable(self):
        """Заявка на пропуск not_applicable проверку не закрывает: код 3 и строка команды."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(
            ["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100200-000-cli-s1.json",
                       {"type": "skipped", "check": "ask_1c_ai@edt",
                        "class": "not_applicable", "reason": "правка только документации"})
        self.trace.put("2026-09-22T100300-000-cli-p1.json", probe("ai-edt"))
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("проверка не закрыта, есть только заявка на пропуск "
                      "(not_applicable): ask_1c_ai@edt", out)
        self.assertIn("заявка на пропуск: ask_1c_ai@edt [not_applicable] "
                      "правка только документации", out)
        self.assertIn("подтверждение человеком: /quality release check ask_1c_ai@edt "
                      "правка только документации", out)

    def test_blocked_skip_request_tool_unavailable(self):
        """Заявка tool_unavailable называет отказ инструмента из ссылки: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        ref = self.trace.put("2026-09-22T100100-000-hook-f1.json",
                             {"type": "failed", "check": "code_review@edt",
                              "detector": "code_review", "toolUseId": "t1",
                              "error": "timeout"})
        self.trace.put("2026-09-22T100200-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "tool_unavailable", "ref": ref})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("заявка на пропуск: code_review@edt [tool_unavailable] timeout", out)

    def test_blocked_probe_down_request(self):
        """probe down по источнику обязательной проверки: заявка на пропуск, код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(
            ["code_review@edt", "ask_1c_ai@edt"]))
        self.trace.put("2026-09-22T100100-000-cli-p1.json",
                       {"type": "probe", "source": "ai-edt", "status": "down",
                        "detail": "EDT не отвечает"})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("заявка на пропуск: code_review@edt [probe down] EDT не отвечает", out)
        self.assertIn("подтверждение человеком: /quality release check code_review@edt "
                      "EDT не отвечает", out)
        self.assertNotIn("ask_1c_ai@edt [probe down]", out)

    def test_with_gaps_release_confirmed(self):
        """Снятие с командой в журнале сессии закрывает проверку: код 1, пробел release."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl", [
            "/quality release check code_review@edt ложное срабатывание"])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8", errors="replace"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("с пробелами", out)
        self.assertIn("пробел: code_review@edt", out)

    def test_blocked_release_without_confirmation(self):
        """Снятие без команды в журнале сессии проверку не закрывает: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl", ["прогони проверки еще раз"])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("снятие проверки code_review@edt: не найдено подтверждение "
                      "пользователя в журнале сессии", proc.stdout.decode("utf-8"))

    def test_unconfirmed_release_does_not_block_closed_run(self):
        """Лишнее неподтвержденное снятие при закрытых проверках прогон не блокирует: код 0."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt", "t1"))
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        self.trace.put("2026-09-22T100300-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "ask_1c_ai@edt",
                        "reason": "не нужна", "source": "user_prompt", "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl", ["продолжай"])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", errors="replace"))

    def test_blocked_release_without_journal(self):
        """Снятие при недоступном журнале сессии не засчитывается: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("не найдено подтверждение пользователя",
                      proc.stdout.decode("utf-8"))

    def test_blocked_release_for_other_check(self):
        """Команда в журнале называет другую проверку: снятие не засчитано, код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl", [
            "/quality release check ask_1c_ai@edt правка документации"])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("не найдено подтверждение пользователя",
                      proc.stdout.decode("utf-8"))

    def test_blocked_release_in_tool_result(self):
        """Команда внутри результата инструмента подтверждением не считается: код 3."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "снятие", "source": "user_prompt", "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl", [
            {"type": "user", "toolUseResult": {"ok": True},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "content": "/quality release check code_review@edt"}]}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
                 {"type": "text", "text": "Stop hook feedback:\nподтверждение человеком: "
                  "/quality release check code_review@edt снятие"}]}},
        ])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8", errors="replace"))
        self.assertIn("не найдено подтверждение пользователя",
                      proc.stdout.decode("utf-8"))

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
        """critical плюс подтвержденное release: снятие перекрывает и critical, и skipped."""
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
        log = journal(self.tmp / "journal.jsonl", [
            "/quality release check code_review@edt ложное срабатывание"])
        proc = check(self.repo, transcript=log)
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

    def test_foreign_release_ignored(self):
        """release с чужим diffHash игнорируется: код 0, на вердикт не влияет."""
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
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
        self.assertNotIn("чужим diffHash", proc.stdout.decode("utf-8"))

    def test_foreign_release_closes_nothing(self):
        """Чужое снятие не закрывает обязательную проверку: блокировка из-за нее."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "снятие", "source": "user_prompt", "diffHash": "1" * 64,
                        "expiresAt": FUTURE})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3)
        out = proc.stdout.decode("utf-8")
        self.assertIn("обязательная проверка без события: code_review@edt", out)
        self.assertNotIn("чужим diffHash", out)

    def test_expired_release_ignored(self):
        """Просроченное release с текущим хешем игнорируется: код 0."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json", scope([]))
        self.trace.put("2026-09-22T100100-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "снятие", "source": "user_prompt", "expiresAt": PAST})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8"))
        self.assertNotIn("просроченное", proc.stdout.decode("utf-8"))

    def test_gate_release_without_scope(self):
        """Подтвержденное снятие gate без scope: код 1, вердикт с пробелами."""
        self.trace.put("2026-09-22T100100-000-hook-r1.json",
                       {"type": "release", "scope": "gate", "reason": "проверки после мержа",
                        "source": "user_prompt", "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl",
                      ["/quality release gate проверки после мержа"])
        proc = check(self.repo, transcript=log)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode("utf-8"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("с пробелами", out)
        self.assertNotIn("нет scope", out)
        self.assertIn("пробел: gate", out)

    def test_blocked_gate_release_without_journal(self):
        """Снятие gate без журнала сессии не засчитывается: код 3, прогона нет."""
        self.trace.put("2026-09-22T100100-000-hook-r1.json",
                       {"type": "release", "scope": "gate", "reason": "проверки после мержа",
                        "source": "user_prompt", "expiresAt": FUTURE})
        proc = check(self.repo)
        self.assertEqual(proc.returncode, 3, proc.stdout.decode("utf-8"))
        out = proc.stdout.decode("utf-8")
        self.assertIn("снятие gate: не найдено подтверждение пользователя", out)
        self.assertIn("нет scope", out)

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

    def render(self, transcript=None) -> str:
        """Запустить render и вернуть текст отчета."""
        args = ["render"]
        if transcript is not None:
            args.extend(["--transcript", str(transcript)])
        proc = run_cli(self.repo, *args)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
        return proc.stdout.decode("utf-8")

    def test_render_clean_four_tables(self):
        """render: вердикт clean и все четыре таблицы, проверка в "Проверено"."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json", applied("code_review@edt"))
        self.trace.put("2026-09-22T100200-000-cli-p1.json", probe("ai-edt"))
        self.trace.put("2026-09-22T100300-000-cli-n1.json",
                       {"type": "not_verified", "dimension": "производительность",
                        "reason": "нагрузочный прогон не выполнялся"})
        text = self.render()
        self.assertIn("Вердикт: clean", text)
        for header in ("## Проверено", "## С пробелами", "## Заявки на пропуск",
                       "## Не проверено"):
            self.assertIn(header, text)
        self.assertIn("code_review@edt", text)
        self.assertIn("probe ok", text)
        requests_table = text.split("## Заявки на пропуск")[1].split("## Не проверено")[0]
        self.assertIn("производительность: нагрузочный прогон не выполнялся",
                      requests_table)

    def test_render_skip_request_not_gap(self):
        """render: заявка на пропуск идет в свою таблицу и в "Не проверено", вердикт blocked."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-cli-s1.json",
                       {"type": "skipped", "check": "code_review@edt",
                        "class": "not_applicable", "reason": "правка документации"})
        text = self.render()
        self.assertIn("Вердикт: blocked", text)
        requests_table = text.split("## Заявки на пропуск")[1].split("## Не проверено")[0]
        self.assertIn("| code_review@edt | not_applicable | правка документации | "
                      "/quality release check code_review@edt правка документации |",
                      requests_table)
        self.assertIn("| code_review@edt | заявка на пропуск (not_applicable): "
                      "правка документации |", text)

    def test_render_release_gap(self):
        """render: подтвержденное снятие показывается в "С пробелами", вердикт with_gaps."""
        self.trace.put("2026-09-22T100000-000-profile-scope.json",
                       scope(["code_review@edt"]))
        self.trace.put("2026-09-22T100100-000-hook-a1.json",
                       applied("code_review@edt", "t1", "findings", critical=1))
        self.trace.put("2026-09-22T100200-000-hook-r1.json",
                       {"type": "release", "scope": "check", "check": "code_review@edt",
                        "reason": "ложное срабатывание", "source": "user_prompt",
                        "expiresAt": FUTURE})
        log = journal(self.tmp / "journal.jsonl",
                      ["/quality release check code_review@edt ложное срабатывание"])
        text = self.render(transcript=log)
        self.assertIn("Вердикт: with_gaps", text)
        self.assertIn("| code_review@edt | release: снятие человеком |", text)

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
