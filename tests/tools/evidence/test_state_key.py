#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Векторы ключа репозитория: tools/quality_events.py против эталона Node."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VECTORS = REPO_ROOT / "tests" / "hooks" / "fixtures" / "state-key-vectors.json"


def load_module():
    """Модуль tools/quality_events.py по пути."""
    spec = importlib.util.spec_from_file_location("quality_events_vectors",
                                                  REPO_ROOT / "tools" / "quality_events.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StateKeyVectorTests(unittest.TestCase):
    def test_vectors(self):
        """Каждый вектор: normalize_top и repo_key совпадают с эталоном."""
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        self.assertEqual(len(vectors), 10)
        mod = load_module()
        for vector in vectors:
            normalized = mod.normalize_top(vector["input"], vector["platform"])
            self.assertEqual(normalized, vector["normalized"], vector["input"])
            self.assertEqual(mod.repo_key(normalized), vector["key"], vector["input"])


if __name__ == "__main__":
    unittest.main()
