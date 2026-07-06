#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ модуля 1С 7.7 (.1s, CP1251): инвентаризация + линтер особенностей синтаксиса.

Две подкоманды:

  inventory <file>   - что использует модуль:
      - СоздатьОбъект("Тип") - с какими объектами работает
      - упоминания типов метаданных (Справочник.X, Документ.Y, Регистр.Z, Перечисление, Журнал)
      - глобальные функции гл* (специфика конкретной базы)
      - объявленные процедуры/функции модуля

  lint <file>        - ищет частые ошибки 7.7, которые всплывают только при компиляции:
      - условие Если/ИначеЕсли/Пока без операции сравнения (голый вызов функции/число)
        -> в 7.7 это "Выражение должно иметь логический тип"

Линтер эвристический (не полноценный парсер), но ловит самый частый класс ошибок.

Примеры:
  python analyze_module.py inventory МодульФормы.1s
  python analyze_module.py lint МодульФормы.1s
"""
import argparse
import re
import sys
from pathlib import Path

ENC = "cp1251"


def lines_of(path):
    return Path(path).read_text(encoding=ENC, errors="replace").split("\n")


def is_comment(line):
    return line.lstrip().startswith("//")


def cmd_inventory(a):
    lines = lines_of(a.file)

    print("=== СоздатьОбъект(тип) ===")
    seen = set()
    rx = re.compile(r'СоздатьОбъект\("([^"]+)"')
    for i, l in enumerate(lines, 1):
        m = rx.search(l)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            print(f"  {i}: {m.group(1)}")

    print("\n=== Типы метаданных (Справочник./Документ./Регистр./Перечисление./Журнал.) ===")
    seen = set()
    rx = re.compile(r"\b(Справочник|Документ|Регистр|Перечисление|Журнал)\.([А-Яа-яA-Za-z][\w]*)")
    for l in lines:
        if is_comment(l):
            continue
        for m in rx.finditer(l):
            seen.add(f"{m.group(1)}.{m.group(2)}")
    for k in sorted(seen):
        print(f"  {k}")

    print("\n=== Глобальные функции гл* ===")
    seen = set()
    rx = re.compile(r"\b(гл[А-ЯA-Z][\w]*)\s*\(")
    for l in lines:
        if is_comment(l):
            continue
        for m in rx.finditer(l):
            seen.add(m.group(1))
    for k in sorted(seen):
        print(f"  {k}")

    print("\n=== Объявленные процедуры/функции ===")
    rx = re.compile(r"^\s*(Процедура|Функция)\s+([А-Яа-яA-Za-z_][\w]*)", re.IGNORECASE)
    for i, l in enumerate(lines, 1):
        m = rx.match(l)
        if m:
            print(f"  {i}: {m.group(1)} {m.group(2)}")


# Условие между ключевым словом и Тогда/Цикл
COND_RX = re.compile(r"\b(?:Если|ИначеЕсли)\b(.*?)\bТогда\b", re.IGNORECASE)
WHILE_RX = re.compile(r"\bПока\b(.*?)\bЦикл\b", re.IGNORECASE)
# наличие оператора сравнения в условии (=, <>, <, >, <=, >=)
HAS_CMP = re.compile(r"[=<>]")
# есть ли вообще вызов функции или идентификатор (чтобы не ругаться на пустое)
HAS_CALL = re.compile(r"[А-Яа-яA-Za-z_][\w.]*\s*\(|[А-Яа-яA-Za-z_]")


def check_condition(cond):
    """True - условие выглядит подозрительным (нет сравнения, но есть содержимое)."""
    c = cond.strip()
    if not c:
        return False
    # убрать строковые литералы, чтобы = внутри "" не считалось сравнением и наоборот
    c_nostr = re.sub(r'"[^"]*"', "", c)
    if HAS_CMP.search(c_nostr):
        return False  # есть сравнение - ок
    if HAS_CALL.search(c_nostr):
        return True  # есть содержимое, но нет сравнения - подозрительно
    return False


def cmd_lint(a):
    lines = lines_of(a.file)
    problems = 0
    for i, l in enumerate(lines, 1):
        if is_comment(l):
            continue
        for rx in (COND_RX, WHILE_RX):
            for m in rx.finditer(l):
                if check_condition(m.group(1)):
                    kw = "Пока/Цикл" if rx is WHILE_RX else "Если/ИначеЕсли"
                    print(f"  {i}: [{kw}] условие без сравнения -> '{m.group(1).strip()}'")
                    print(f"       строка: {l.strip()}")
                    problems += 1
    if problems:
        print(f"\n[{problems} подозрительных условий] "
              "В 7.7 условие должно содержать сравнение (= 1 / <> 0 и т.п.), "
              "иначе 'Выражение должно иметь логический тип'.", file=sys.stderr)
    else:
        print("[чисто] подозрительных условий не найдено.", file=sys.stderr)
    return problems


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inventory", help="инвентаризация модуля")
    pi.add_argument("file")
    pi.set_defaults(func=cmd_inventory)

    pl = sub.add_parser("lint", help="линтер особенностей синтаксиса 7.7")
    pl.add_argument("file")
    pl.set_defaults(func=cmd_lint)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
