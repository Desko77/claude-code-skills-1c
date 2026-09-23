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

    def test_force_dry_run_writes_no_backup(self):
        """--force --dry-run при конфликте: каталог резерва не создается, файл не тронут."""
        self.install()
        installed = self.home / "agents" / "1c-explore.md"
        installed.write_text("local edit", encoding="utf-8")
        result = self.install("--force", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / "backup").exists())
        self.assertEqual(installed.read_text(encoding="utf-8"), "local edit")

    def test_eol_only_change_is_not_drift(self):
        """Смена концов строк LF -> CRLF в установленном файле не считается расхождением."""
        self.install()
        installed = self.home / "agents" / "1c-explore.md"
        data = installed.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        installed.write_bytes(data)
        self.assertEqual(self.check().returncode, 0)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_manifest_non_object_root_exits_2(self):
        """Манифест с корнем не-объектом (JSON-массив) - код 2 и диагностика, не traceback."""
        (self.home / ".install-manifest.json").write_text("[]", encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 2)
        self.assertIn("манифест испорчен", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_filesystem_error_exits_2(self):
        """Адресат недоступен для записи (на месте каталога agents лежит файл) - код 2."""
        (self.home / "agents").write_text("not a directory", encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("ошибка файловой системы", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_dry_run_writes_nothing(self):
        """--dry-run: план печатается, ни файла, ни манифеста не появляется."""
        result = self.install("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / "agents" / "1c-explore.md").exists())
        self.assertFalse((self.home / ".install-manifest.json").exists())

    def test_hooks_component_installs(self):
        """Компонент hooks: hooks.json, support-guard.mjs и common/*.mjs лежат в hooks/1c-skills."""
        result = self.install("--components", "hooks")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        base = self.home / "hooks" / "1c-skills"
        self.assertTrue((base / "hooks.json").exists())
        self.assertTrue((base / "support-guard.mjs").exists())
        self.assertTrue((base / "skill-suggester.mjs").exists())
        common_files = sorted((REPO_ROOT / "hooks" / "common").glob("*.mjs"))
        self.assertTrue(common_files)
        for src in common_files:
            self.assertEqual((base / "common" / src.name).read_bytes(), src.read_bytes())

    def test_tools_component_installs_only_listed(self):
        """Компонент tools с include: ставятся только инструменты контура качества и установщик."""
        expected = ["change_profile.py", "changeset.py", "evidence.py", "install_home.py",
                    "quality_events.py"]
        result = self.install("--components", "tools")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        base = self.home / "tools" / "1c-skills"
        installed = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
        self.assertEqual(installed, expected)
        self.assertEqual((base / "install_home.py").read_bytes(), INSTALLER.read_bytes())
        manifest = json.loads(self.manifest_bytes())
        self.assertEqual(sorted(manifest["files"]), ["tools/1c-skills/" + name for name in expected])

    def test_three_components_together(self):
        """--components agents,hooks,tools: файлы всех трех компонентов на месте."""
        result = self.install("--components", "agents,hooks,tools")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / "agents" / "1c-explore.md").exists())
        self.assertTrue((self.home / "hooks" / "1c-skills" / "hooks.json").exists())
        self.assertTrue((self.home / "tools" / "1c-skills" / "install_home.py").exists())

    def test_commands_quality_keeps_personal_and_check_sees_drift(self):
        """commands/quality.md ставится, личный close-task.md не тронут, --check видит правку."""
        personal = self.home / "commands" / "close-task.md"
        personal.parent.mkdir(parents=True)
        personal.write_text("личная команда\n", encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        quality = self.home / "commands" / "quality.md"
        self.assertEqual(quality.read_bytes(), (REPO_ROOT / "commands" / "quality.md").read_bytes())
        self.assertEqual(personal.read_text(encoding="utf-8"), "личная команда\n")
        self.assertFalse((self.home / "commands" / "move-project.md").exists())
        self.assertNotIn("close-task.md", result.stdout)
        quality.write_text("правка\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("РАСХОЖДЕНИЕ", result.stdout)
        self.assertIn("quality.md", result.stdout)
        self.assertEqual(personal.read_text(encoding="utf-8"), "личная команда\n")

    def test_check_all_components_clean(self):
        """--check по трем компонентам после их установки: выход 0."""
        result = self.install("--components", "agents,hooks,tools")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_installer("--check", "--components", "agents,hooks,tools", home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
