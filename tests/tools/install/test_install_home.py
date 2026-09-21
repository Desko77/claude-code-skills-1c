#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты установщика tools/install_home.py.

Установщик гоняется как отдельный процесс (subprocess с текущим интерпретатором)
с явным --home во временный каталог: реальный ~/.claude не затрагивается.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "tools" / "install_home.py"
AGENT_REPO = REPO_ROOT / "agents" / "1c-explore.md"


def run_installer(*args: str, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(INSTALLER), *args, "--home", str(home)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))


class InstallHomeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def install(self, *args: str) -> subprocess.CompletedProcess:
        return run_installer("install", *args, home=self.home)

    def check(self) -> subprocess.CompletedProcess:
        return run_installer("--check", home=self.home)

    def manifest_bytes(self) -> bytes:
        return (self.home / ".install-manifest.json").read_bytes()

    def test_clean_install(self):
        """Чистая установка: файл на месте, манифест содержит путь и sha256 репозитория."""
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.home / "agents" / "1c-explore.md"
        self.assertTrue(installed.exists())
        self.assertEqual(installed.read_bytes(), AGENT_REPO.read_bytes())
        manifest = json.loads(self.manifest_bytes())
        self.assertIn("agents/1c-explore.md", manifest["files"])

    def test_rerun_idempotent(self):
        """Повторная установка без изменений: выход 0, манифест побайтово тот же."""
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = self.manifest_bytes()
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.manifest_bytes(), before)

    def test_local_edit_conflict(self):
        """Локальная правка установленного файла: конфликт, файл не тронут, выход 1."""
        self.install()
        target = self.home / "agents" / "1c-explore.md"
        edited = target.read_text(encoding="utf-8") + "\n<!-- локальная правка -->\n"
        target.write_text(edited, encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_text(encoding="utf-8"), edited)
        self.assertIn("КОНФЛИКТ", result.stdout)

    def test_force_overwrites_with_backup(self):
        """--force: конфликтный файл переписан, правленая копия лежит в backup/install-*."""
        self.install()
        target = self.home / "agents" / "1c-explore.md"
        edited = target.read_text(encoding="utf-8") + "\n<!-- локальная правка -->\n"
        target.write_text(edited, encoding="utf-8")
        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), AGENT_REPO.read_bytes())
        backups = list((self.home / "backup").glob("install-*/agents/1c-explore.md"))
        self.assertEqual(len(backups), 1, f"ожидалась одна резервная копия: {backups}")
        self.assertEqual(backups[0].read_text(encoding="utf-8"), edited)

    def test_check_clean(self):
        """--check после установки без правок: выход 0."""
        self.install()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_detects_drift(self):
        """--check при расхождении: расхождение перечислено, выход 1."""
        self.install()
        target = self.home / "agents" / "1c-explore.md"
        target.write_text("измененное содержимое", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("РАСХОЖДЕНИЕ", result.stdout)

    def test_dry_run_writes_nothing(self):
        """--dry-run: план печатается, ни файла, ни манифеста не появляется."""
        result = self.install("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / "agents" / "1c-explore.md").exists())
        self.assertFalse((self.home / ".install-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
