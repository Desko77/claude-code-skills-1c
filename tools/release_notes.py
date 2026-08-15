# -*- coding: utf-8 -*-
"""Собрать описание релиза из CHANGELOG, развернув жесткие переносы строк.

В .md-файлах GitHub схлопывает одиночный перенос в пробел, поэтому ручная разбивка абзаца по
~100 символов там не видна. В ОПИСАНИИ РЕЛИЗА тот же markdown рендерится с жесткими переносами:
каждая строка становится отдельной, и абзац выглядит рваным. Поэтому текст релиза собирается
из того же CHANGELOG, но абзацы склеиваются в одну строку.

Не склеиваются: блоки кода, таблицы, заголовки, цитаты, разделители. Пункт списка остается
отдельной строкой, но его продолжение подклеивается к нему.
"""
import re
import sys
from pathlib import Path

BLOCK_START = re.compile(r"^(#{1,6} |> |\||---$|\*\*\*$|___$)")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")


def unwrap(text: str) -> str:
    out = []
    buf = []            # накопленный абзац или пункт списка
    in_code = False

    def flush():
        if buf:
            out.append(" ".join(s.strip() for s in buf))
            buf.clear()

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        if not stripped:                      # пустая строка - конец абзаца
            flush()
            out.append("")
            continue

        if BLOCK_START.match(stripped):       # заголовок, таблица, цитата, разделитель
            flush()
            out.append(line)
            continue

        if LIST_ITEM.match(line):             # новый пункт списка
            flush()
            buf.append(line)
            continue

        buf.append(line)                      # продолжение абзаца или пункта

    flush()
    # схлопнуть тройные пустые строки, если появились
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


if len(sys.argv) < 3:
    print("Использование: python tools/release_notes.py CHANGELOG.md заметки.md [версия]\n"
          "Затем: gh release create vX.Y.Z --notes-file заметки.md", file=sys.stderr)
    raise SystemExit(2)

version = sys.argv[3] if len(sys.argv) > 3 else "1.0.0"
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
t = src.read_text(encoding="utf-8")
marker = f"## {version}"
if marker not in t:
    print(f"В {src.name} нет раздела {marker}", file=sys.stderr)
    raise SystemExit(1)
body = t[t.index(marker):].split("\n", 1)[1]
# Раздел заканчивается на заголовке следующей версии. Без этой отсечки в заметки попадают
# все предыдущие релизы; на 1.0.0 это не проявлялось - тот раздел лежал последним в файле.
next_release = body.find("\n## ")
if next_release != -1:
    body = body[:next_release]
res = unwrap(body)
dst.write_text(res, encoding="utf-8")
print(f"{src.name}: было строк {len(body.splitlines())}, стало {len(res.splitlines())} -> {dst}")
