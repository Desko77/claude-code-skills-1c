#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты сверки счетчиков README: check_readme_counters из tools/validate_ruleset.py.

Каждый сценарий строит временный каталог с README.md, каталогами skills/ и файлами
rules/*.md и сверяет список находок: при совпадении всех трех счетчиков с фактом
находок нет, при порче любого счетчика либо при пропавшем месте счетчика находка
блокирующая. Правила со второй формой (.mdc) засчитываются в счетчик правил.
Раскладка зеркала для Cursor (только .mdc, README свой без мест счетчиков) -
проверка пропускается, находок нет.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "tools" / "validate_ruleset.py"


def load_module():
    """Модуль tools/validate_ruleset.py, импортированный по пути: вызов функций без CLI."""
    spec = importlib.util.spec_from_file_location("validate_ruleset_py", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


README_TEMPLATE = """# Набор

## Состав набора

| Группа | Что делает | Скилов |
|--------|------------|--------|
| Первая | делает одно | {first} |
| Вторая | делает другое | {second} |

## Скилы ({heading})

Перечень скилов.

И **{rules} правил** - подключаются один раз.
"""


def build_repo(root, heading, first, second, rules, dirs=None):
    """Временный репозиторий: README из шаблона, каталоги skills/ и файлы rules/.

    Параметры: root - каталог назначения; heading - число в заголовке "## Скилы (N)";
    first и second - числа колонки "Скилов" таблицы групп; rules - число в "**N правил**"
    и одновременно число файлов rules/*.md; dirs - число каталогов skills/, по умолчанию
    first + second. Тест портит одно место, остальные счетчики остаются верными.
    Результат - корень.
    """
    if dirs is None:
        dirs = first + second
    (root / "skills").mkdir()
    for index in range(dirs):
        (root / "skills" / f"skill-{index}").mkdir()
    (root / "rules").mkdir()
    for index in range(rules):
        (root / "rules" / f"rule-{index}.md").write_text("# правило\n", encoding="utf-8")
    (root / "README.md").write_text(
        README_TEMPLATE.format(heading=heading, first=first, second=second, rules=rules),
        encoding="utf-8")
    return root


class ReadmeCountersTest(unittest.TestCase):
    """Сверка счетчиков README с составом временного репозитория."""

    def setUp(self):
        self.validator = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_check(self):
        """Список находок проверки счетчиков на временном репозитории."""
        problems = []
        self.validator.check_readme_counters(problems, self.root)
        return problems

    def blocking(self, problems):
        """Только блокирующие находки из списка."""
        return [problem for problem in problems if problem[0] == "ERROR"]

    def rewrite_readme(self, old, new):
        """Заменить фрагмент текста README: имитация переписанного места счетчика."""
        path = self.root / "README.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_counters_match_no_findings(self):
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        self.assertEqual(self.run_check(), [])

    def test_heading_mismatch_is_blocking(self):
        build_repo(self.root, heading=4, first=2, second=3, rules=4)
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('заголовок "## Скилы (4)"', errors[0][2])
        self.assertIn("каталогов skills/ - 5", errors[0][2])

    def test_table_sum_mismatch_is_blocking(self):
        build_repo(self.root, heading=5, first=2, second=2, rules=4, dirs=5)
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('сумма колонки "Скилов" - 4', errors[0][2])
        self.assertIn("каталогов skills/ - 5", errors[0][2])

    def test_rules_count_mismatch_is_blocking(self):
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        self.rewrite_readme("**4 правил**", "**3 правил**")
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('в тексте "**3 правил**"', errors[0][2])
        self.assertIn("файлов rules/*.md - 4", errors[0][2])

    def test_missing_heading_is_blocking(self):
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        self.rewrite_readme("## Скилы (5)", "## Скилы")
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('не найден заголовок "## Скилы (N)"', errors[0][2])

    def test_missing_rules_line_is_blocking(self):
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        self.rewrite_readme("**4 правил**", "правила набора")
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('не найдена строка "**N правил**"', errors[0][2])

    def test_missing_table_is_blocking(self):
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        self.rewrite_readme("| Группа | Что делает | Скилов |", "| Группа | Что делает |")
        errors = self.blocking(self.run_check())
        self.assertEqual(len(errors), 1)
        self.assertIn('не найдена таблица групп скилов', errors[0][2])

    def test_mdc_rules_counted(self):
        """Правила .mdc засчитываются в счетчик правил наряду с .md."""
        build_repo(self.root, heading=5, first=2, second=3, rules=4)
        (self.root / "rules" / "rule-extra.mdc").write_text("# правило\n", encoding="utf-8")
        self.rewrite_readme("**4 правил**", "**5 правил**")
        self.assertEqual(self.run_check(), [])

    def test_mirror_layout_skipped(self):
        """Зеркало для Cursor: правила .mdc, README без мест счетчиков - находок нет."""
        (self.root / "skills").mkdir()
        (self.root / "skills" / "skill-0").mkdir()
        (self.root / "rules").mkdir()
        for index in range(2):
            (self.root / "rules" / f"rule-{index}.mdc").write_text("# правило\n", encoding="utf-8")
        (self.root / "README.md").write_text(
            "# Зеркало\n\nСостав набора, счетчиков здесь нет.\n", encoding="utf-8")
        self.assertEqual(self.run_check(), [])


if __name__ == "__main__":
    unittest.main()
