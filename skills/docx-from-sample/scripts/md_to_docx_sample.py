# -*- coding: utf-8 -*-
"""Markdown -> DOCX в оформлении образца.

    python md_to_docx_sample.py doc.md --profile profile.json --out doc.docx --title "Название"

Разметка markdown:
    | ... |                  таблица (первая строка - шапка)
    <!-- landscape -->       дальше альбомная секция
    <!-- portrait -->        дальше книжная секция
    **Текст**                титульная строка (до первого заголовка документа)
    - Пункт                  маркированный список

Уровень заголовка определяется профилем (headings_map): точным совпадением текста,
регулярным выражением или по следующему абзацу. Все, что не опознано, - обычный текст.
Профиль правится под жанр документа, скрипт универсален.
"""
import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docx_builder import SampleDoc

SEP = re.compile(r"^\|[\s\-:|]*-[\s\-:|]*\|$")
ORIENT = re.compile(r"^<!--\s*(landscape|portrait)\s*-->$")
BOLD_LINE = re.compile(r"^\*\*(.+)\*\*$")


def parse_md(text):
    """Разбор на блоки: ("table", rows) | ("orient", value) | ("text", line)."""
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not SEP.match(lines[i].strip()):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", rows))
            continue
        m = ORIENT.match(ln.strip())
        if m:
            blocks.append(("orient", m.group(1)))
            i += 1
            continue
        if ln.strip():
            blocks.append(("text", ln.strip()))
        i += 1
    return blocks


class Converter:
    def __init__(self, profile, title, sample=None):
        self.d = SampleDoc(profile, sample=sample)
        self.p = self.d.p
        self.hm = self.p.get("headings_map", {})
        self.title = title
        tmpl = self.p.get("footer", {}).get("template", "{title}")
        self.d.footer_for_all(tmpl.format(title=title) if title else None)
        self.in_title_zone = True
        self.prev_h1 = None

    # --- распознавание роли строки

    def role(self, text, next_text):
        if text in self.hm.get("h1_unnumbered", []):
            return "h1_unnumbered"
        if text in self.hm.get("h1", []):
            return "h1"
        if text in self.hm.get("h2", []):
            return "h2"
        if text in self.hm.get("h3", []):
            return "h3"
        if text in self.hm.get("callout", []):
            return "callout"
        for rx, role in (self.hm.get("regex") or {}).items():
            if re.match(rx, text):
                return role
        after = self.hm.get("h2_after_h1", [])
        if self.prev_h1 in after:
            return "h2_once"
        for prefix in self.hm.get("h3_if_next_starts_with", []):
            if next_text.startswith(prefix):
                return "h3"
        if text.startswith("- "):
            return "bullet"
        return "body"

    def table_kind(self, header):
        """Как оформить таблицу: ключ профиля table_rules по шапке."""
        rules = self.p.get("table_rules", {})
        key = " | ".join(header)
        for name, cfg in rules.items():
            if name == "default":
                continue
            match = cfg.get("match_header")
            if match and (key == match or header[0] == match):
                return cfg
        return rules.get("default", {})

    def emit_table(self, rows):
        if not rows:
            return
        header, body = rows[0], rows[1:]
        if self.in_title_zone:
            if len(header) >= 3 and not any("".join(r).strip() for r in rows):
                self.d.rule_table(cols=len(header))
            else:
                self.d.plain_table(rows, bold_first_row=True)
            return
        cfg = self.table_kind(header)
        merge = []
        clean = []
        markers = self.p.get("tables", {}).get("full_width_rows", [])
        for r in body:
            if r and len(set(r)) == 1 and r[0] in markers:
                merge.append((len(clean), r[0]))
                clean.append([""] * len(header))
            else:
                clean.append(r)
        self.d.table(
            header, clean,
            style=cfg.get("style", "default"),
            head_fill=cfg.get("head_fill"),
            body_style_key=cfg.get("body_style_key", "table_body"),
            borders=cfg.get("border_sz"),
            repeat=cfg.get("repeat_header"),
            head_size=cfg.get("head_size"),
            widths=cfg.get("widths"),
            merge_rows=merge,
        )

    def run(self, blocks, out, author):
        def next_text(pos):
            for k in range(pos + 1, len(blocks)):
                if blocks[k][0] == "text":
                    return blocks[k][1]
            return ""

        for pos, (kind, val) in enumerate(blocks):
            if kind == "orient":
                self.d.section(val)
                continue
            if kind == "table":
                self.emit_table(val)
                continue

            text = val
            bold = BOLD_LINE.match(text)
            if bold and self.in_title_zone:
                self.d.para(bold.group(1), align="center",
                            size=self.p.get("title_page", {}).get("big_pt", 22), bold=True)
                continue

            head = text[2:].strip() if text.startswith("- ") else None
            if head and head in self.hm.get("h1_unnumbered", []):
                if self.in_title_zone:
                    self.in_title_zone = False
                    self.d.section("portrait")
                self.d.heading(head, 1, numbered=False)
                if head in self.hm.get("toc_after", []):
                    self.d.toc()
                continue

            if self.in_title_zone:
                cfg = self.p.get("title_page", {})
                size = cfg.get("big_pt", 22) if len(text) < cfg.get("big_max_len", 90) \
                    else cfg.get("small_pt", 16)
                self.d.para(text, align="center", size=size)
                continue

            role = self.role(text, next_text(pos))
            if role == "h1_unnumbered":
                self.d.heading(text, 1, numbered=False)
                if text in self.hm.get("toc_after", []):
                    self.d.toc()
            elif role == "h1":
                self.d.heading(text, 1)
                self.prev_h1 = text
            elif role == "h2":
                self.d.heading(text, 2)
            elif role == "h2_once":
                self.d.heading(text, 2)
                self.prev_h1 = None
            elif role == "h3":
                self.d.heading(text, 3)
            elif role == "card":
                self.d.heading(text, 2, keep_next=True)
            elif role == "callout":
                self.d.callout(text)
            elif role == "bullet":
                self.d.bullet(text[2:].strip())
            else:
                self.d.body(text)

        self.d.save(out, author=author, title=self.title)
        return self.d


def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out")
    ap.add_argument("--title", default="")
    ap.add_argument("--sample", help="образец, если надо переопределить путь из профиля")
    ap.add_argument("--author")
    a = ap.parse_args()

    out = a.out or (a.md[:-3] + ".docx")
    with io.open(a.md, encoding="utf-8") as f:
        blocks = parse_md(f.read())
    conv = Converter(a.profile, a.title, sample=a.sample)
    d = conv.run(blocks, out, a.author)
    print("Готово: %s" % out)
    print("  таблиц: %d, секций: %d" % (len(d.doc.tables), len(d.doc.sections)))
    for w in d.warnings:
        print("  ВНИМАНИЕ: %s" % w)
    print("  Дальше: verify_result.py (сверка, обновление оглавления, картинки страниц).")


if __name__ == "__main__":
    sys.exit(main())
