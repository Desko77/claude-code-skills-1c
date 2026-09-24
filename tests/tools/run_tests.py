#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Раннер unit-тестов инструментов из tools/: unittest discover по tests/tools.

В отличие от снапшот-прогонов tests/skills (Node, навыки целиком), здесь живут
тесты отдельных Python-инструментов - пока установщика tools/install_home.py.

  python tests/tools/run_tests.py     # все тесты
  python tests/tools/run_tests.py -v  # подробный вывод

Код выхода: 0 все тесты прошли, 1 есть провалы.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

TESTS_DIR = Path(__file__).resolve().parent


def main() -> int:
    suite = unittest.TestLoader().discover(start_dir=str(TESTS_DIR), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
