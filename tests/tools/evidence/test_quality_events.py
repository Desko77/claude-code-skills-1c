#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты общего модуля событий следа: tools/quality_events.py.

Запись и чтение каталога событий во временном чистом git-репозитории. Отметка
времени всех событий принудительно одинакова (подмена now_iso): порядок имен
задает номер последовательности, а не producer и не случайный суффикс. Отбор
прогона select_run проверяется по порядку записи.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_env import isolate_state_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
SESSION = "sess-events"
FIXED_AT = "2026-09-22T12:00:00.123+03:00"


def load_module():
    """Модуль tools/quality_events.py по пути: вызов функций без CLI."""
    spec = importlib.util.spec_from_file_location("quality_events_test",
                                                  REPO_ROOT / "tools" / "quality_events.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    """Выполнить git в репозитории; отказ команды - ошибка теста с выводом git."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr.decode('utf-8', errors='replace')}"


def make_repo(tmp: Path) -> Path:
    """Чистый репозиторий с закоммиченным .gitignore на каталог следа."""
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


class QualityEventsOrderTests(unittest.TestCase):
    def setUp(self):
        isolate_state_dir(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self.tmp)
        self.mod = load_module()
        # Одна и та же отметка времени у всех событий теста.
        self.mod.now_iso = lambda: FIXED_AT
        self.diff_hash = "d" * 64

    def write(self, payload: dict) -> Path:
        """Записать событие с фиксированным now_iso (как пишут вызовы модуля)."""
        event = {"session": SESSION, "at": self.mod.now_iso(), "diffHash": self.diff_hash}
        event.update(payload)
        return self.mod.write_event(self.repo, SESSION, event)

    def test_same_timestamp_read_in_write_order(self):
        """Два события одной миллисекунды читаются в порядке записи."""
        first = self.write({"type": "scope", "producer": "profile", "required": []})
        second = self.write({"type": "applied", "producer": "hook", "check": "x"})
        events = self.mod.read_events(self.repo, SESSION)
        self.assertEqual([e.get("type") for e in events], ["scope", "applied"])
        self.assertEqual(events[0]["_file"], first.name)
        self.assertEqual(events[1]["_file"], second.name)
        self.assertLess(first.name, second.name)

    def test_same_timestamp_scope_then_applied_in_run(self):
        """applied в ту же миллисекунду, что scope, не выпадает из прогона."""
        self.write({"type": "scope", "producer": "profile", "required": ["code_review@edt"]})
        self.write({"type": "applied", "producer": "hook", "check": "code_review@edt",
                    "toolUseId": "t1", "outcome": {"status": "pass"}})
        events = self.mod.read_events(self.repo, SESSION)
        run = self.mod.select_run(events, self.diff_hash)
        self.assertIsNotNone(run)
        self.assertEqual(run["scope"]["type"], "scope")
        self.assertEqual([e.get("type") for e in run["events"]], ["applied"])

    def test_filename_sequence_and_locks(self):
        """Имя несет номер последовательности; lock-файлы занимают номера в каталоге сессии."""
        first = self.write({"type": "probe", "producer": "cli", "source": "ai-edt",
                            "status": "ok"})
        second = self.write({"type": "probe", "producer": "cli", "source": "script",
                             "status": "ok"})
        self.assertRegex(first.name, r"2026-09-22T120000-123-000000-cli-[0-9a-f]{6}\.json")
        self.assertRegex(second.name, r"2026-09-22T120000-123-000001-cli-[0-9a-f]{6}\.json")
        session_dir = first.parent.parent
        locks = sorted(p.name for p in session_dir.glob("*.lock"))
        self.assertEqual(locks, ["2026-09-22T120000-123-000000.lock",
                                 "2026-09-22T120000-123-000001.lock"])
        # Lock-файлы не читаются как события.
        self.assertEqual(len(self.mod.read_events(self.repo, SESSION)), 2)


if __name__ == "__main__":
    unittest.main()
