# -*- coding: utf-8 -*-
"""Одноразовая сборка role-edit: маркеры общего блока и копия из role-compile."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY_SRC = ROOT / "skills" / "1c-role-compile" / "scripts" / "role-compile.py"
PS_SRC = ROOT / "skills" / "1c-role-compile" / "scripts" / "role-compile.ps1"
PY_LOGIC = ROOT / "_role_edit_py_logic.py"
PS_LOGIC = ROOT / "_role_edit_ps1_logic.ps1"
PY_OUT = ROOT / "skills" / "1c-role-edit" / "scripts" / "role-edit.py"
PS_OUT = ROOT / "skills" / "1c-role-edit" / "scripts" / "role-edit.ps1"

START = "# --- Таблица прав и замыкание (общий блок, версия 1) ---"
END = "# --- Конец общего блока таблицы прав и замыкания ---"


def read(path):
    return path.read_text(encoding="utf-8", newline="") if False else Path.read_text(path, encoding="utf-8")


def read_keep(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_keep(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def line_start(text, index):
    prev = text.rfind("\n", 0, index)
    return 0 if prev < 0 else prev + 1


def extract_until(text, start_needle, end_needle):
    start = text.find(start_needle)
    if start < 0:
        raise SystemExit(f"не найден якорь: {start_needle}")
    start = line_start(text, start)
    end = text.find(end_needle, start + len(start_needle))
    if end < 0:
        raise SystemExit(f"не найден конец: {end_needle}")
    end = line_start(text, end)
    return text[start:end]


def insert_block(text, start_needle, end_needle):
    if START in text and END in text:
        return text
    start = text.find(start_needle)
    if start < 0:
        raise SystemExit(f"не найден старт блока: {start_needle}")
    start = line_start(text, start)
    end = text.find(end_needle, start + len(start_needle))
    if end < 0:
        raise SystemExit(f"не найден конец блока: {end_needle}")
    end = line_start(text, end)
    block = text[start:end]
    if not block.endswith("\n"):
        block += "\n"
    replacement = START + "\n" + block + END + "\n"
    return text[:start] + replacement + text[end:]


def slice_marked(text):
    start = text.find(START)
    end = text.find(END, start)
    if start < 0 or end < 0:
        raise SystemExit("маркеры блока не найдены")
    end_line = text.find("\n", end)
    if end_line < 0:
        chunk = text[start:]
    else:
        chunk = text[start:end_line + 1]
    return chunk


def py_guard(text):
    marker = "# Support guard (Ext/ParentConfigurations.bin)"
    idx = text.find(marker)
    banner = text.rfind("# ===", 0, idx)
    banner = line_start(text, banner)
    end_marker = "# --- Конец общего блока гарда поддержки ---"
    end = text.find(end_marker, idx)
    end = text.find("\n", end)
    return text[banner:end + 1]


def ps_guard(text):
    return extract_until(text, "# --- Support guard (Ext/ParentConfigurations.bin) ---", "param(") if False else None


def ps_guard_real(text):
    start = text.find("# --- Support guard (Ext/ParentConfigurations.bin) ---")
    end_marker = "# --- Конец общего блока гарда поддержки ---"
    end = text.find(end_marker, start)
    end = text.find("\n", end)
    return text[start:end + 1]


def main():
    py = read_keep(PY_SRC)
    ps = read_keep(PS_SRC)
    py = insert_block(
        py,
        "# --- Russian synonyms -> canonical English names ---",
        "# --- Presets ---",
    )
    ps = insert_block(
        ps,
        "# --- 3. Russian synonyms",
        "# Nested objects:",
    )
    write_keep(PY_SRC, py)
    write_keep(PS_SRC, ps)

    py_helpers = extract_until(py, "def translate_object_name(", "def resolve_preset(")
    py_helpers += "\n" + extract_until(
        py,
        "# Типы метаданных, у которых прав в роли нет вовсе",
        "def parse_object_entry(",
    )
    ps_helpers = extract_until(ps, "# Nested objects:", "function Parse-ObjectEntry")

    header = """#!/usr/bin/env python3
# role-edit v1.0 - точечная правка существующей роли 1С
import argparse
import html
import json
import os
import re
import subprocess
import sys

"""
    py_text = (
        header
        + py_guard(py)
        + "\n"
        + slice_marked(py)
        + "\n"
        + py_helpers
        + "\n"
        + PY_LOGIC.read_text(encoding="utf-8")
        + "\n\nmain()\n"
    )
    ps_header = """# role-edit v1.0 - точечная правка существующей роли 1С
param(
    [Parameter(Mandatory)]
    [string]$RolePath,
    [string]$DefinitionFile,
    [string]$Operation,
    [string]$Object,
    [string]$Rights,
    [string]$Right,
    [string]$Template,
    [string]$Condition,
    [string]$Property,
    [string]$Value,
    [switch]$NoValidate
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

"""
    ps_text = (
        ps_header
        + ps_guard_real(ps)
        + "\n"
        + slice_marked(ps)
        + "\n"
        + ps_helpers
        + "\n"
        + PS_LOGIC.read_text(encoding="utf-8")
        + "\n"
    )
    write_keep(PY_OUT, py_text)
    write_keep(PS_OUT, ps_text)
    print(f"py {len(py_text)} bytes, ps {len(ps_text)} bytes")
    print("py block has close_rights", "def close_rights(" in slice_marked(py))
    print("ps block has Close-Rights", "function Close-Rights" in slice_marked(ps))
    print("py helpers finish", "def finish_rights(" in py_helpers)
    print("ps helpers Finish", "function Finish-Rights" in ps_helpers)


if __name__ == "__main__":
    main()
