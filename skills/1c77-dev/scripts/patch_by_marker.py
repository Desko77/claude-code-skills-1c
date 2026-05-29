#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Идемпотентная вставка блока кода по маркеру-якорю в файл 1С 7.7 (.1s, CP1251).

Зачем: повторяемые правки (вставить одинаковый блок колонок/присваиваний в обработку выгрузки,
добавить элемент в форму и т.п.) удобнее делать привязкой к стабильному фрагменту-якорю, а не к
номерам строк. Идемпотентность: если блок уже стоит рядом с маркером - повторно не вставляется,
скрипт можно прогонять много раз.

Маркер должен встречаться ровно один раз (или используй --all для всех вхождений).
Запись в CP1251 с сохранением переводов строк.

Примеры:
  # вставить блок после строки-якоря
  python patch_by_marker.py Модуль.1s --marker 'тз.НоваяКолонка("Комментарий","Строка",300);' \\
      --after --block-file new_columns.txt

  # вставить текст напрямую перед якорем, проверить идемпотентность
  python patch_by_marker.py Форма.frm --marker 'Элементы:' --after --block '    BUTTON: { ... }'
"""
import argparse
import sys
from pathlib import Path

ENC = "cp1251"


def read_raw(path):
    with open(path, encoding=ENC, newline="") as f:
        return f.read()


def write_raw(path, text):
    with open(path, "w", encoding=ENC, newline="") as f:
        f.write(text)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--marker", required=True, help="текст-якорь, к которому привязываемся")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--after", action="store_true", help="вставить блок ПОСЛЕ маркера (по умолчанию)")
    g.add_argument("--before", action="store_true", help="вставить блок ПЕРЕД маркером")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--block", help="текст блока для вставки")
    src.add_argument("--block-file", help="файл с текстом блока (читается как CP1251)")
    p.add_argument("--all", action="store_true", help="вставлять у всех вхождений маркера (иначе требуется уникальный)")
    p.add_argument("--dry-run", action="store_true", help="только показать, не писать")
    a = p.parse_args()

    text = read_raw(a.file)
    block = a.block if a.block is not None else Path(a.block_file).read_text(encoding=ENC)

    cnt = text.count(a.marker)
    if cnt == 0:
        sys.exit("Маркер не найден - проверь точное написание (CP1251, пробелы, кавычки).")
    if cnt > 1 and not a.all:
        sys.exit(f"Маркер встречается {cnt} раз. Уточни маркер или используй --all.")

    before = a.before
    # идемпотентность: блок уже стоит со стороны вставки от маркера?
    if before:
        if (block + a.marker) in text:
            print("[идемпотентно] блок уже перед маркером, пропуск.", file=sys.stderr)
            return
        new = text.replace(a.marker, block + a.marker, (0 if a.all else 1) or 1) if a.all \
            else text.replace(a.marker, block + a.marker, 1)
    else:
        if (a.marker + block) in text:
            print("[идемпотентно] блок уже после маркера, пропуск.", file=sys.stderr)
            return
        new = text.replace(a.marker, a.marker + block) if a.all \
            else text.replace(a.marker, a.marker + block, 1)

    inserted = (len(new) - len(text))
    print(f"[вставлено {1 if not a.all else cnt} раз, +{inserted} символов]", file=sys.stderr)
    if a.dry_run:
        print("[dry-run, файл не изменён]", file=sys.stderr)
        return
    write_raw(a.file, new)
    print("[записано]", file=sys.stderr)


if __name__ == "__main__":
    main()
