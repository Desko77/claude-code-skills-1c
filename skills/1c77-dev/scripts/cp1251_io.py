#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чтение / поиск / замена в файлах 1С 7.7 (.1s, .frm, .mdp) в кодировке CP1251.

Зачем: обычный Grep ищет по UTF-8 байтам и кириллицу в CP1251-файлах НЕ находит,
а Read показывает кракозябры. Этот скрипт - корректный доступ к таким файлам.

Подкоманды:
  read    <file> [--start N] [--count M]                  печать строк с номерами
  grep    <file> <pattern> [-i] [-C N]                    поиск регуляркой (номера строк)
  replace <file> <old> <new> [--regex] [--count K] [--dry-run]   замена

Запись всегда в CP1251 с newline='' - оригинальные переводы строк (обычно CRLF)
не искажаются, иначе файл может стать нечитаемым для 7.7.

Примеры:
  python cp1251_io.py grep Модуль.1s "ПустаяСтрока" -C 1
  python cp1251_io.py read Модуль.1s --start 1500 --count 40
  python cp1251_io.py replace Модуль.1s "ПустаяСтрока(Х) Тогда" "ПустаяСтрока(Х) = 1 Тогда"
"""
import argparse
import re
import sys
from pathlib import Path

ENC = "cp1251"


def read_text(path):
    return Path(path).read_text(encoding=ENC, errors="replace")


def read_raw(path):
    # newline='' - сохранить исходные переводы строк для последующей записи
    with open(path, encoding=ENC, newline="") as f:
        return f.read()


def write_raw(path, text):
    with open(path, "w", encoding=ENC, newline="") as f:
        f.write(text)


def cmd_read(a):
    lines = read_text(a.file).split("\n")
    start = max(1, a.start)
    end = len(lines) if a.count is None else min(len(lines), start - 1 + a.count)
    for i in range(start, end + 1):
        print(f"{i}\t{lines[i - 1]}")


def cmd_grep(a):
    flags = re.IGNORECASE if a.ignore_case else 0
    rx = re.compile(a.pattern, flags)
    lines = read_text(a.file).split("\n")
    hits = [i for i, l in enumerate(lines, 1) if rx.search(l)]
    for i in hits:
        lo = max(1, i - a.context)
        hi = min(len(lines), i + a.context)
        for j in range(lo, hi + 1):
            mark = ":" if j == i else "-"
            print(f"{j}{mark}\t{lines[j - 1]}")
        if a.context:
            print("--")
    print(f"[{len(hits)} совпадений]", file=sys.stderr)


def cmd_replace(a):
    text = read_raw(a.file)
    if a.regex:
        new, n = re.subn(a.old, a.new, text, count=(a.count or 0))
    else:
        total = text.count(a.old)
        n = total if a.count is None else min(a.count, total)
        new = text.replace(a.old, a.new, a.count if a.count is not None else -1)
    print(f"[замен: {n}]", file=sys.stderr)
    if a.dry_run:
        print("[dry-run, файл не изменён]", file=sys.stderr)
        return
    if n:
        write_raw(a.file, new)
        print("[записано]", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("read", help="печать строк файла")
    pr.add_argument("file")
    pr.add_argument("--start", type=int, default=1)
    pr.add_argument("--count", type=int, default=None)
    pr.set_defaults(func=cmd_read)

    pg = sub.add_parser("grep", help="поиск регуляркой")
    pg.add_argument("file")
    pg.add_argument("pattern")
    pg.add_argument("-i", "--ignore-case", action="store_true")
    pg.add_argument("-C", "--context", type=int, default=0)
    pg.set_defaults(func=cmd_grep)

    prp = sub.add_parser("replace", help="замена подстроки/регулярки")
    prp.add_argument("file")
    prp.add_argument("old")
    prp.add_argument("new")
    prp.add_argument("--regex", action="store_true", help="трактовать old как regex, new как шаблон замены")
    prp.add_argument("--count", type=int, default=None, help="максимум замен (по умолчанию все)")
    prp.add_argument("--dry-run", action="store_true", help="только посчитать, не писать")
    prp.set_defaults(func=cmd_replace)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
