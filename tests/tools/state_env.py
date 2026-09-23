# -*- coding: utf-8 -*-
"""Временный каталог следа для тестов инструментов.

QUALITY_STATE_DIR подменяется на время теста: запись и чтение следа не касаются
домашнего каталога. Дочерние процессы наследуют os.environ.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def isolate_state_dir(test: unittest.TestCase) -> Path:
    """Назначить тесту свой QUALITY_STATE_DIR и убрать его по завершении."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    patcher = mock.patch.dict(os.environ, {"QUALITY_STATE_DIR": tmp.name})
    patcher.start()
    test.addCleanup(patcher.stop)
    return Path(tmp.name)
