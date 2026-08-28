#!/usr/bin/env python3
# mxl-decompile v1.0 - Decompile 1C spreadsheet to JSON
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from lxml import etree

# --- Namespace map ---

NSMAP = {
    "d": "http://v8.1c.ru/8.2/data/spreadsheet",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "v8ui": "http://v8.1c.ru/8.1/data/ui",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def find(node, xpath):
    return node.find(xpath, NSMAP)


def findall(node, xpath):
    return node.findall(xpath, NSMAP)


# --- Черновой JSON (общий блок, версия 2) ---
# Ширина строки, после которой контейнер разворачивается по элементу на строку.
DRAFT_JSON_WIDTH = 400


def to_inline_json(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        if not value:
            return '{}'
        parts = [json.dumps(str(k), ensure_ascii=False) + ': ' + to_inline_json(v)
                 for k, v in value.items()]
        return '{ ' + ', '.join(parts) + ' }'
    if isinstance(value, (list, tuple)):
        if not value:
            return '[]'
        return '[' + ', '.join(to_inline_json(v) for v in value) + ']'
    return json.dumps(str(value), ensure_ascii=False)


def to_draft_json(value, indent=''):
    """Описание пишется в том виде, в каком его удобно править руками: контейнер идет
    одной строкой, пока в нее помещается, и разворачивается, когда перестает."""
    rendered = to_inline_json(value)
    if (len(indent) + len(rendered) <= DRAFT_JSON_WIDTH
            or not isinstance(value, (dict, list, tuple)) or not value):
        return rendered
    inner = indent + '  '
    if isinstance(value, dict):
        parts = [inner + json.dumps(str(k), ensure_ascii=False) + ': ' + to_draft_json(v, inner)
                 for k, v in value.items()]
        return '{\n' + ',\n'.join(parts) + '\n' + indent + '}'
    parts = [inner + to_draft_json(v, inner) for v in value]
    return '[\n' + ',\n'.join(parts) + '\n' + indent + ']'
# --- Конец общего блока чернового JSON ---


# Строка, у которой все ячейки простые, записывается массивом значений по колонкам - так
# описание читается и правится быстрее, чем набором объектов.
def row_to_shorthand(row):
    if set(row.keys()) != {"cells"} or not row["cells"]:
        return None
    slots = {}
    max_col = 0
    for c in row["cells"]:
        if not set(c.keys()) <= {"col", "span", "text", "param", "template"}:
            return None
        content = [k for k in ("text", "param", "template") if k in c]
        if len(content) != 1:
            return None
        kind = content[0]
        value = c[kind]
        if not isinstance(value, str):
            return None
        if kind == "param":
            if "{" in value or "}" in value:
                return None
            token = "{" + value + "}"
        elif kind == "template":
            if not re.search(r"\[.+\]", value):
                return None
            token = value
        else:
            if (value in (">", "|") or re.match(r"^\{.+\}$", value)
                    or re.search(r"\[.+\]", value)):
                return None
            token = value
        col = int(c.get("col") or 0)
        span = int(c.get("span") or 1)
        if col < 1 or span < 1 or col in slots:
            return None
        slots[col] = token
        for k in range(1, span):
            if col + k in slots:
                return None
            slots[col + k] = ">"
        if col + span - 1 > max_col:
            max_col = col + span - 1
    return [slots.get(i) for i in range(1, max_col + 1)]


def rows_to_shorthand(compressed_rows):
    """Область с вертикальными объединениями не сокращается: они выражаются знаком | и
    связывают соседние строки, а посвязной разбор здесь не окупается."""
    for r in compressed_rows:
        for c in (r.get("cells") or []):
            if c.get("rowspan"):
                return compressed_rows
    out = []
    for r in compressed_rows:
        short = row_to_shorthand(r)
        out.append(r if short is None else short)
    return out


# Имя набора колонок выводится из его порядка: в файле у набора есть идентификатор, но нет
# имени, а описанию имя нужно.
SET_NAME_PREFIX = 'nabor'


def font_size_value(raw):
    value = float(raw or 0)
    return int(value) if value == int(value) else value


# Префиксы, объявленные на корне: у элемента шрифта они не свои и в описание не идут.
INHERITED_PREFIXES = ('style', 'v8', 'v8ui', 'xs', 'xsi', 'pal')


def text_of(node):
    if node is not None and node.text:
        return node.text
    return None


def int_of(node, default=0):
    if node is not None and node.text:
        return int(node.text)
    return default


# --- Main ---

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Decompile 1C spreadsheet to JSON", allow_abbrev=False)
    parser.add_argument("-TemplatePath", required=True, help="Path to Template.xml")
    parser.add_argument("-OutputPath", default=None, help="Output JSON path (stdout if omitted)")
    args = parser.parse_args()

    template_path = args.TemplatePath
    output_path = args.OutputPath

    # --- 1. Load and parse XML ---

    if not os.path.isfile(template_path):
        print(f"File not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    parser_xml = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(template_path, parser_xml)
    root = tree.getroot()

    # --- 2. Extract font palette ---

    raw_fonts = []
    for f_node in findall(root, "d:font"):
        font_ns = OrderedDict()
        for ns_prefix, ns_uri in (f_node.nsmap or {}).items():
            if ns_prefix and ns_prefix not in INHERITED_PREFIXES:
                font_ns[ns_prefix] = ns_uri
        raw_fonts.append({
            # Шрифт задается либо своими свойствами, либо ссылкой на элемент стиля или
            # системный шрифт - тогда у него есть ref, kind и объявление префикса.
            "Ref": f_node.get("ref", ""),
            "Kind": f_node.get("kind", ""),
            "Namespace": font_ns,
            "Face": f_node.get("faceName", ""),
            # Размер шрифта бывает дробным: целое сохраняется целым, чтобы описание
            # не менялось на ровном месте.
            "Size": font_size_value(f_node.get("height", "0")),
            "Bold": f_node.get("bold") == "true",
            "Italic": f_node.get("italic") == "true",
            "Underline": f_node.get("underline") == "true",
            "Strikeout": f_node.get("strikeout") == "true",
        })

    # --- 3. Extract line palette ---

    raw_lines = []
    for l_node in findall(root, "d:line"):
        raw_lines.append({"Width": int(l_node.get("width", "0"))})

    # --- 4. Extract format palette ---

    raw_formats = []
    for fmt_node in findall(root, "d:format"):
        fmt = {
            "FontIdx": -1,
            "LB": -1, "TB": -1, "RB": -1, "BB": -1,
            "Width": 0, "Height": 0,
            "HA": "", "VA": "",
            "Wrap": False, "FillType": "", "DataFormat": "",
            "TextColor": "", "Hidden": False,
        }

        n = find(fmt_node, "d:font")
        if n is not None and n.text:
            fmt["FontIdx"] = int(n.text)
        # Рамка со всех сторон одной линией записана одним тегом.
        n = find(fmt_node, "d:border")
        if n is not None and n.text:
            all_sides = int(n.text)
            fmt["LB"] = all_sides
            fmt["TB"] = all_sides
            fmt["RB"] = all_sides
            fmt["BB"] = all_sides
        n = find(fmt_node, "d:leftBorder")
        if n is not None and n.text:
            fmt["LB"] = int(n.text)
        n = find(fmt_node, "d:topBorder")
        if n is not None and n.text:
            fmt["TB"] = int(n.text)
        n = find(fmt_node, "d:rightBorder")
        if n is not None and n.text:
            fmt["RB"] = int(n.text)
        n = find(fmt_node, "d:bottomBorder")
        if n is not None and n.text:
            fmt["BB"] = int(n.text)

        n = find(fmt_node, "d:textColor")
        if n is not None and n.text:
            fmt["TextColor"] = n.text
        n = find(fmt_node, "d:hidden")
        if n is not None and n.text == "true":
            fmt["Hidden"] = True
        n = find(fmt_node, "d:width")
        if n is not None and n.text:
            fmt["Width"] = int(n.text)
        n = find(fmt_node, "d:height")
        if n is not None and n.text:
            fmt["Height"] = int(n.text)

        n = find(fmt_node, "d:horizontalAlignment")
        if n is not None and n.text:
            fmt["HA"] = n.text
        n = find(fmt_node, "d:verticalAlignment")
        if n is not None and n.text:
            fmt["VA"] = n.text

        n = find(fmt_node, "d:textPlacement")
        if n is not None and n.text == "Wrap":
            fmt["Wrap"] = True

        n = find(fmt_node, "d:fillType")
        if n is not None and n.text:
            fmt["FillType"] = n.text

        n = find(fmt_node, "d:format/v8:item/v8:content")
        if n is not None and n.text:
            fmt["DataFormat"] = n.text

        raw_formats.append(fmt)

    def get_format(idx):
        if idx <= 0 or idx > len(raw_formats):
            return None
        return raw_formats[idx - 1]

    # --- 5. Extract columns and default width ---

    col_nodes = findall(root, "d:columns")
    col_node = col_nodes[0]
    total_columns = int_of(find(col_node, "d:size"))

    col_format_indices = {}
    for ci in findall(col_node, "d:columnsItem"):
        col_idx = int_of(find(ci, "d:index"))
        fmt_idx = int_of(find(ci, "d:column/d:formatIndex"))
        col_format_indices[col_idx] = fmt_idx

    default_fmt_idx = 0
    n = find(root, "d:defaultFormatIndex")
    if n is not None and n.text:
        default_fmt_idx = int(n.text)

    default_width = 10
    if default_fmt_idx > 0:
        def_fmt = get_format(default_fmt_idx)
        if def_fmt and def_fmt["Width"] > 0:
            default_width = def_fmt["Width"]

    # Build column width map (1-based col -> width), only non-default
    col_width_map = OrderedDict()
    for col0 in sorted(col_format_indices.keys()):
        fmt = get_format(col_format_indices[col0])
        if fmt and fmt["Width"] > 0 and fmt["Width"] != default_width:
            col1 = str(col0 + 1)
            col_width_map[col1] = fmt["Width"]

    # Блок колонок с идентификатором - это набор: своя раскладка ширин для части строк.
    column_sets_out = OrderedDict()
    set_name_by_id = {}
    for set_index, cn in enumerate(col_nodes[1:], start=1):
        id_node = find(cn, "d:id")
        if id_node is None or not id_node.text:
            continue
        set_id = id_node.text.strip()
        set_name = "%s%d" % (SET_NAME_PREFIX, set_index)
        entry = OrderedDict([("id", set_id), ("columns", int_of(find(cn, "d:size")))])
        set_widths = OrderedDict()
        for ci in findall(cn, "d:columnsItem"):
            c0 = int_of(find(ci, "d:index"))
            fmt = get_format(int_of(find(ci, "d:column/d:formatIndex")))
            if fmt and fmt["Width"] > 0:
                set_widths[str(c0 + 1)] = fmt["Width"]
        if set_widths:
            entry["columnWidths"] = set_widths
        column_sets_out[set_name] = entry
        set_name_by_id[set_id] = set_name

    # --- 6. Extract merges ---

    merge_map = {}
    for m_node in findall(root, "d:merge"):
        r = int_of(find(m_node, "d:r"))
        c = int_of(find(m_node, "d:c"))
        w = int_of(find(m_node, "d:w"))
        h_node = find(m_node, "d:h")
        h = int_of(h_node) if h_node is not None else 0
        merge_map[f"{r},{c}"] = {"W": w, "H": h}

    # --- 7. Extract named items ---

    named_areas = []
    coord_areas = []
    for ni_node in findall(root, "d:namedItem"):
        xsi_type = ni_node.get(f"{{{XSI_NS}}}type", "")
        if xsi_type != "NamedItemCells":
            continue

        area_node = find(ni_node, "d:area")
        area_type_node = find(area_node, "d:type")
        area_type = text_of(area_type_node) or ""
        ni_name = text_of(find(ni_node, "d:name")) or ""
        begin_row = int_of(find(area_node, "d:beginRow"))
        end_row = int_of(find(area_node, "d:endRow"))
        begin_col = int_of(find(area_node, "d:beginColumn"))
        end_col = int_of(find(area_node, "d:endColumn"))

        # Область строк без колоночных границ описывает содержимое; все прочие виды - это
        # координатные области, они сохраняются отдельным разделом описания.
        if area_type == "Rows" and begin_col < 0 and end_col < 0:
            named_areas.append({
                "Name": ni_name,
                "BeginRow": begin_row,
                "EndRow": end_row,
            })
            continue

        coord_area = OrderedDict([("name", ni_name)])
        if begin_row >= 0:
            coord_area["rows"] = (str(begin_row + 1) if begin_row == end_row
                                  else f"{begin_row + 1}-{end_row + 1}")
        if begin_col >= 0:
            coord_area["cols"] = (str(begin_col + 1) if begin_col == end_col
                                  else f"{begin_col + 1}-{end_col + 1}")
        coord_areas.append(coord_area)

    # --- 8. Extract rows ---

    row_data = {}
    # Языки, встреченные в тексте ячеек, в порядке первого появления.
    text_languages_seen = []
    for ri_node in findall(root, "d:rowsItem"):
        row_idx = int_of(find(ri_node, "d:index"))
        row_node = find(ri_node, "d:row")

        index_to = row_idx
        it_node = find(ri_node, "d:indexTo")
        if it_node is not None and it_node.text:
            index_to = int(it_node.text)

        row_fmt_idx = 0
        fmt_node = find(row_node, "d:formatIndex")
        if fmt_node is not None and fmt_node.text:
            row_fmt_idx = int(fmt_node.text)

        row_set_name = None
        cid_node = find(row_node, "d:columnsID")
        if cid_node is not None and cid_node.text:
            row_set_name = set_name_by_id.get(cid_node.text.strip())

        is_empty = False
        empty_node = find(row_node, "d:empty")
        if empty_node is not None and empty_node.text == "true":
            is_empty = True

        cells = []
        if not is_empty:
            col = -1
            for c_group in findall(row_node, "d:c"):
                i_node = find(c_group, "d:i")
                if i_node is not None and i_node.text:
                    col = int(i_node.text)
                else:
                    col += 1

                c_content = find(c_group, "d:c")
                if c_content is None:
                    continue

                cell_fmt_idx = 0
                f_node = find(c_content, "d:f")
                if f_node is not None and f_node.text:
                    cell_fmt_idx = int(f_node.text)

                param = None
                p_node = find(c_content, "d:parameter")
                if p_node is not None and p_node.text:
                    param = p_node.text

                detail = None
                d_node = find(c_content, "d:detailParameter")
                if d_node is not None and d_node.text:
                    detail = d_node.text

                # Текст хранится по языкам: одноязычный вариант вернется строкой, разноязычный -
                # объектом, поэтому берутся все элементы, а не первый.
                text = None
                text_by_lang = OrderedDict()
                for t_item in findall(c_content, "d:tl/v8:item"):
                    content_node = find(t_item, "v8:content")
                    if content_node is None or not content_node.text:
                        continue
                    lang_node = find(t_item, "v8:lang")
                    lang = lang_node.text if lang_node is not None and lang_node.text else "ru"
                    text_by_lang[lang] = content_node.text
                    if text is None:
                        text = content_node.text
                    if lang not in text_languages_seen:
                        text_languages_seen.append(lang)

                cells.append({
                    "Col": col,
                    "FormatIdx": cell_fmt_idx,
                    "Param": param,
                    "Detail": detail,
                    "Text": text,
                    "TextByLang": text_by_lang,
                })

        for r in range(row_idx, index_to + 1):
            row_data[r] = {
                "FormatIdx": row_fmt_idx,
                "ColumnSet": row_set_name,
                "Cells": cells,
                "Empty": is_empty,
            }

    # --- 9. Build style key (ignoring fillType) ---

    def get_border_desc(fmt):
        if not fmt:
            return {"Border": "none", "Thick": False}

        lb = fmt["LB"] >= 0
        tb = fmt["TB"] >= 0
        rb = fmt["RB"] >= 0
        bb = fmt["BB"] >= 0

        if not lb and not tb and not rb and not bb:
            return {"Border": "none", "Thick": False}

        thick = False
        for b_idx in [fmt["LB"], fmt["TB"], fmt["RB"], fmt["BB"]]:
            if b_idx >= 0 and b_idx < len(raw_lines) and raw_lines[b_idx]["Width"] >= 2:
                thick = True
                break

        if lb and tb and rb and bb:
            return {"Border": "all", "Thick": thick}

        sides = []
        if tb:
            sides.append("top")
        if bb:
            sides.append("bottom")
        if lb:
            sides.append("left")
        if rb:
            sides.append("right")

        return {"Border": ",".join(sides), "Thick": thick}

    def get_style_key(fmt):
        if not fmt:
            return "empty"
        # Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры: подмена
        # навязывала бы его ячейкам, у которых шрифта не было.
        fi = fmt["FontIdx"] if fmt["FontIdx"] >= 0 else -1
        bd = get_border_desc(fmt)
        return (f"f={fi}|b={bd['Border']}|bw={bd['Thick']}|ha={fmt['HA']}|va={fmt['VA']}"
                f"|wr={fmt['Wrap']}|df={fmt['DataFormat']}|tc={fmt['TextColor']}")

    # --- 10. Name fonts ---

    font_names = {}
    font_defs = OrderedDict()

    # Имя default означает шрифт, который сборка подставит стилю без явного шрифта. Если в
    # макете есть оформленный формат БЕЗ шрифта, такого умолчания у документа нет: первый
    # шрифт палитры именуется как остальные, иначе сборка навяжет его тем ячейкам, у которых
    # шрифта не было.
    has_fontless_format = any(
        fmt["FontIdx"] < 0 and (fmt["LB"] >= 0 or fmt["TB"] >= 0 or fmt["RB"] >= 0
                                or fmt["BB"] >= 0 or fmt["HA"] or fmt["VA"] or fmt["Wrap"]
                                or fmt["FillType"] or fmt["DataFormat"] or fmt["TextColor"]
                                or fmt["Hidden"])
        for fmt in raw_formats)

    # Шрифт-ссылка именуется по самой ссылке: свойств, из которых собирается имя, у него нет.
    def ref_font_name(f):
        value = str(f["Ref"])
        return value.split(":", 1)[1] if ":" in value else value

    def get_font_key(f):
        ns = ";".join(f"{k}={v}" for k, v in sorted((f["Namespace"] or {}).items()))
        return (f"{f['Ref']}|{f['Kind']}|{ns}|{f['Face']}|{f['Size']}"
                f"|{f['Bold']}|{f['Italic']}|{f['Underline']}|{f['Strikeout']}")

    font_key_map = {}

    for i in range(0, len(raw_fonts)):
        f = raw_fonts[i]
        df = raw_fonts[0]

        # Dedup: if identical font already named, reuse
        f_key = get_font_key(f)
        if f_key in font_key_map:
            font_names[i] = font_key_map[f_key]
            continue

        name = None

        if f["Ref"]:
            name = ref_font_name(f)

        if not name and f["Face"] == df["Face"] and f["Size"] == df["Size"]:
            if f["Bold"] and not df["Bold"] and not f["Italic"] and not f["Underline"] and not f["Strikeout"]:
                name = "bold"
            elif f["Italic"] and not df["Italic"] and not f["Bold"]:
                name = "italic"
            elif f["Underline"] and not df["Underline"] and not f["Bold"] and not f["Italic"]:
                name = "underline"
        elif f["Face"] == df["Face"] and f["Size"] > df["Size"] and f["Bold"]:
            name = "header"
        elif f["Face"] == df["Face"] and f["Size"] < df["Size"]:
            name = "small"

        if not name and i == 0 and not has_fontless_format:
            name = "default"

        if not name:
            parts = []
            if f["Face"] and f["Face"] != df["Face"]:
                parts.append(f["Face"].lower())
            parts.append(str(f["Size"]))
            if f["Bold"]:
                parts.append("bold")
            if f["Italic"]:
                parts.append("italic")
            if f["Underline"]:
                parts.append("underline")
            if f["Strikeout"]:
                parts.append("strikeout")
            name = "-".join(parts)

        base_name = name
        suffix = 2
        while name in font_defs:
            name = f"{base_name}{suffix}"
            suffix += 1

        font_names[i] = name
        font_defs[name] = f
        font_key_map[f_key] = name

    # --- 11. Collect and name styles ---

    style_keys = OrderedDict()
    format_to_style_key = {}

    # Собственный формат строки тоже дает стиль: высота и скрытие в стиль не входят, а шрифт
    # и оформление - входят.
    def row_format_styled(fmt):
        if not fmt:
            return False
        return bool(fmt["FontIdx"] >= 0 or fmt["LB"] >= 0 or fmt["TB"] >= 0 or fmt["RB"] >= 0
                    or fmt["BB"] >= 0 or fmt["HA"] or fmt["VA"] or fmt["Wrap"]
                    or fmt["DataFormat"] or fmt["TextColor"])

    for rd in row_data.values():
        row_fmt_own = get_format(rd["FormatIdx"])
        if row_format_styled(row_fmt_own):
            row_key = get_style_key(row_fmt_own)
            if row_key not in style_keys:
                style_keys[row_key] = row_fmt_own
            format_to_style_key[rd["FormatIdx"]] = row_key
        for cell in rd["Cells"]:
            fmt = get_format(cell["FormatIdx"])
            if not fmt:
                continue
            key = get_style_key(fmt)
            if key not in style_keys:
                style_keys[key] = fmt
            format_to_style_key[cell["FormatIdx"]] = key

    def name_style(fmt):
        if not fmt:
            return "default"
        parts = []

        # Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры.
        fi = fmt["FontIdx"] if fmt["FontIdx"] >= 0 else -1
        if fi in font_names and font_names[fi] != "default":
            parts.append(font_names[fi])

        bd = get_border_desc(fmt)
        if bd["Border"] != "none":
            if bd["Border"] == "all":
                parts.append("bordered")
            else:
                parts.append(f"border-{bd['Border']}")

        if fmt["HA"] == "Center":
            parts.append("center")
        elif fmt["HA"] == "Right":
            parts.append("right")
        if fmt["VA"] == "Center":
            parts.append("vcenter")
        elif fmt["VA"] == "Top":
            parts.append("vtop")
        if fmt["Wrap"]:
            parts.append("wrap")
        if fmt["TextColor"] and not parts:
            parts.append("colored")
        if fmt["DataFormat"]:
            parts.append("fmt")

        if len(parts) == 0:
            return "default"
        return "-".join(parts)

    style_names = OrderedDict()
    style_defs = OrderedDict()

    for key in style_keys:
        fmt = style_keys[key]
        name = name_style(fmt)

        base_name = name
        suffix = 2
        while name in style_defs:
            name = f"{base_name}{suffix}"
            suffix += 1

        style_names[key] = name

        s_def = OrderedDict()
        # Формат без шрифта - это отсутствие шрифта, а не первый шрифт палитры.
        fi = fmt["FontIdx"] if fmt["FontIdx"] >= 0 else -1
        if fi in font_names and font_names[fi] != "default":
            s_def["font"] = font_names[fi]
        if fmt["HA"]:
            a_map = {"Left": "left", "Center": "center", "Right": "right",
                     "Justify": "justify"}
            a = a_map.get(fmt["HA"])
            if a:
                s_def["align"] = a
        if fmt["VA"]:
            va_map = {"Top": "top", "Center": "center", "Bottom": "bottom"}
            a = va_map.get(fmt["VA"])
            if a:
                s_def["valign"] = a
        if fmt["TextColor"]:
            s_def["textColor"] = fmt["TextColor"]
        bd = get_border_desc(fmt)
        if bd["Border"] != "none":
            s_def["border"] = bd["Border"]
            if bd["Thick"]:
                s_def["borderWidth"] = "thick"
        if fmt["Wrap"]:
            s_def["wrap"] = True
        if fmt["DataFormat"]:
            s_def["format"] = fmt["DataFormat"]

        style_defs[name] = s_def

    def get_style_name(fmt_idx):
        key = format_to_style_key.get(fmt_idx)
        if key and key in style_names:
            return style_names[key]
        return "default"

    # Одноязычный текст возвращается строкой, разноязычный - объектом "язык: текст".
    # Одинаковый текст на всех встреченных языках - это тоже строка: ее развернет обратно
    # textLanguages при сборке.
    def text_value(cell):
        by_lang = cell.get("TextByLang") or {}
        if not by_lang:
            return cell["Text"]
        # Строкой текст записывается только тогда, когда он одинаков и покрывает ВЕСЬ состав
        # языков вывода: иначе обратная сборка добавит ячейке язык, которого в ней не было.
        if (len(set(by_lang.values())) == 1
                and set(by_lang) == set(text_languages_seen)):
            return cell["Text"]
        return OrderedDict(by_lang)

    # --- 12. Build areas ---

    dsl_areas = []
    sheet_rows = None

    # Строки, не попавшие ни в одну именованную область, тоже принадлежат документу.
    # Они разбиваются на отрезки между областями, чтобы порядок строк сохранился.
    last_row = max((int(k) for k in row_data), default=-1)
    sheet_areas = []
    cursor = 0
    for area in sorted(named_areas, key=lambda a: (a["BeginRow"], a["EndRow"])):
        if area["BeginRow"] > cursor:
            sheet_areas.append({"Name": "", "BeginRow": cursor, "EndRow": area["BeginRow"] - 1})
        sheet_areas.append(area)
        cursor = max(cursor, area["EndRow"] + 1)
    if cursor <= last_row:
        sheet_areas.append({"Name": "", "BeginRow": cursor, "EndRow": last_row})

    for area in sheet_areas:
        area_rows = []

        for global_row in range(area["BeginRow"], area["EndRow"] + 1):
            rd = row_data.get(global_row)

            # Свой формат есть и у строки без ячеек: высота, скрытие и стиль строки от
            # отсутствия содержимого не пропадают.
            def row_own_properties(rd_local):
                out = OrderedDict()
                if rd_local.get("ColumnSet"):
                    out["columnSet"] = rd_local["ColumnSet"]
                if rd_local["FormatIdx"] > 0:
                    row_fmt_local = get_format(rd_local["FormatIdx"])
                    if row_fmt_local and row_fmt_local["Height"] > 0:
                        out["height"] = row_fmt_local["Height"]
                    if row_fmt_local and row_fmt_local["Hidden"]:
                        out["hidden"] = True
                    if row_format_styled(row_fmt_local):
                        key_local = format_to_style_key.get(rd_local["FormatIdx"])
                        if key_local and key_local in style_names:
                            out["style"] = style_names[key_local]
                return out

            if not rd or rd["Empty"]:
                area_rows.append(row_own_properties(rd) if rd else OrderedDict())
                continue

            dsl_row = row_own_properties(rd)

            # Separate content cells from gap-fill cells
            content_cells = []
            gap_cells = []

            for cell in rd["Cells"]:
                has_content = cell["Param"] or cell["Text"]
                has_merge = f"{global_row},{cell['Col']}" in merge_map

                if has_content or has_merge:
                    content_cells.append(cell)
                else:
                    gap_cells.append(cell)

            # Detect rowStyle
            row_style_name = None
            row_style_key = None

            if len(gap_cells) > 0:
                gap_keys = {}
                for gc in gap_cells:
                    fmt = get_format(gc["FormatIdx"])
                    gap_keys[get_style_key(fmt)] = True

                if len(gap_keys) == 1:
                    row_style_key = list(gap_keys.keys())[0]
                    if row_style_key in style_names:
                        row_style_name = style_names[row_style_key]

            if row_style_name and row_style_name != "default":
                dsl_row["rowStyle"] = row_style_name

            # Build cell list
            dsl_cells = []

            for cell in sorted(content_cells, key=lambda c: c["Col"]):
                dsl_cell = OrderedDict()
                dsl_cell["col"] = cell["Col"] + 1

                # Span/rowspan from merge
                mk = f"{global_row},{cell['Col']}"
                if mk in merge_map:
                    m = merge_map[mk]
                    if m["W"] > 0:
                        dsl_cell["span"] = m["W"] + 1
                    if m["H"] > 0:
                        dsl_cell["rowspan"] = m["H"] + 1

                # Style
                cell_fmt = get_format(cell["FormatIdx"])
                cell_style_key = get_style_key(cell_fmt)

                if row_style_key and cell_style_key == row_style_key:
                    pass  # Inherits rowStyle
                else:
                    # Нулевой формат означает, что оформление у ячейки не задано: стиль ей не
                    # нужен, иначе обратная сборка завела бы формат, которого в исходнике нет.
                    if int(cell["FormatIdx"]) > 0:
                        sn = get_style_name(cell["FormatIdx"])
                        if sn != "default" or not row_style_name:
                            dsl_cell["style"] = sn

                # Content
                fill_type = cell_fmt["FillType"] if cell_fmt else ""

                if cell["Param"]:
                    dsl_cell["param"] = cell["Param"]
                    if cell["Detail"]:
                        dsl_cell["detail"] = cell["Detail"]
                elif fill_type == "Template" and cell["Text"]:
                    dsl_cell["template"] = text_value(cell)
                elif cell["Text"]:
                    dsl_cell["text"] = text_value(cell)

                dsl_cells.append(dsl_cell)

            if len(dsl_cells) > 0:
                dsl_row["cells"] = dsl_cells
            area_rows.append(dsl_row)

        # Compress consecutive empty rows ({}) into { empty = N }
        compressed_rows = []
        empty_run = 0
        for r in area_rows:
            if len(r) == 0:
                empty_run += 1
            else:
                if empty_run > 0:
                    if empty_run == 1:
                        compressed_rows.append(OrderedDict())
                    else:
                        compressed_rows.append(OrderedDict([("empty", empty_run)]))
                    empty_run = 0
                compressed_rows.append(r)
        if empty_run > 0:
            if empty_run == 1:
                compressed_rows.append(OrderedDict())
            else:
                compressed_rows.append(OrderedDict([("empty", empty_run)]))

        # Без единой именованной области строки документа выносятся на верхний уровень;
        # иначе безымянный отрезок остается областью без имени и держит свое место.
        compressed_rows = rows_to_shorthand(compressed_rows)
        if not named_areas:
            sheet_rows = compressed_rows
        elif area["Name"]:
            dsl_areas.append(OrderedDict([
                ("name", area["Name"]),
                ("rows", compressed_rows),
            ]))
        else:
            dsl_areas.append(OrderedDict([("rows", compressed_rows)]))

    # --- 13. Compress columnWidths ---

    compressed_widths = OrderedDict()
    if len(col_width_map) > 0:
        # Group columns by width
        width_to_cols = {}
        for col_str, width in col_width_map.items():
            width_to_cols.setdefault(width, []).append(col_str)

        for width, cols in width_to_cols.items():
            cols_sorted = sorted(cols, key=lambda x: int(x))

            ranges = []
            range_start = cols_sorted[0]
            range_prev = cols_sorted[0]

            for i in range(1, len(cols_sorted)):
                if int(cols_sorted[i]) == int(range_prev) + 1:
                    range_prev = cols_sorted[i]
                else:
                    if range_start == range_prev:
                        ranges.append(range_start)
                    else:
                        ranges.append(f"{range_start}-{range_prev}")
                    range_start = cols_sorted[i]
                    range_prev = cols_sorted[i]

            if range_start == range_prev:
                ranges.append(range_start)
            else:
                ranges.append(f"{range_start}-{range_prev}")

            for rng in ranges:
                compressed_widths[rng] = width

    # --- 14. Build fonts output ---

    fonts_out = OrderedDict()
    for name, f in font_defs.items():
        f_out = OrderedDict()
        if f["Ref"]:
            if f["Namespace"]:
                f_out["namespace"] = OrderedDict(f["Namespace"])
            f_out["ref"] = f["Ref"]
            f_out["kind"] = f["Kind"]
            fonts_out[name] = f_out
            continue
        f_out["face"] = f["Face"]
        f_out["size"] = f["Size"]
        if f["Bold"]:
            f_out["bold"] = True
        if f["Italic"]:
            f_out["italic"] = True
        if f["Underline"]:
            f_out["underline"] = True
        if f["Strikeout"]:
            f_out["strikeout"] = True
        fonts_out[name] = f_out

    # --- 15. Assemble result ---

    # Состав языков сохраняется: у макета их бывает несколько, и обратная сборка обязана
    # воспроизвести тот же список.
    languages_out = []
    current_language = ""
    default_language = ""
    lang_settings = find(root, "d:languageSettings")
    if lang_settings is not None:
        current_language = text_of(find(lang_settings, "d:currentLanguage")) or ""
        default_language = text_of(find(lang_settings, "d:defaultLanguage")) or ""
        for li in findall(lang_settings, "d:languageInfo"):
            languages_out.append(OrderedDict([
                ("id", text_of(find(li, "d:id")) or ""),
                ("code", text_of(find(li, "d:code")) or ""),
                ("description", text_of(find(li, "d:description")) or ""),
            ]))

    result = OrderedDict()
    result["columns"] = total_columns
    result["defaultWidth"] = default_width
    if len(compressed_widths) > 0:
        result["columnWidths"] = compressed_widths
    # Умолчание навыка - один русский язык; всякий иной состав записывается.
    if text_languages_seen and text_languages_seen != ["ru"]:
        result["textLanguages"] = text_languages_seen
    # В описание не выносится ровно то, что навык подставит сам: один русский язык. Любой
    # другой одиночный язык записывается, иначе обратная сборка сделает макет русским.
    russian_default = (len(languages_out) == 1
                       and languages_out[0]["id"] == "ru"
                       and languages_out[0]["code"] == "Русский"
                       and languages_out[0]["description"] == "Русский"
                       and current_language in ("", "ru")
                       and default_language in ("", "ru"))
    if languages_out and not russian_default:
        result["languages"] = languages_out
        if current_language:
            result["currentLanguage"] = current_language
        if default_language:
            result["defaultLanguage"] = default_language

    # Remove empty "default" style
    if "default" in style_defs and len(style_defs["default"]) == 0:
        del style_defs["default"]

    # Remove unused styles
    used_styles = set()
    style_scan_rows = []
    for a in dsl_areas:
        style_scan_rows.extend(a["rows"])
    if sheet_rows:
        style_scan_rows.extend(sheet_rows)
    for r in style_scan_rows:
        # Строка, записанная массивом, стилей не несет.
        if not isinstance(r, dict):
            continue
        if "rowStyle" in r:
            used_styles.add(r["rowStyle"])
        if "style" in r:
            used_styles.add(r["style"])
        if "cells" in r:
            for c in r["cells"]:
                if "style" in c:
                    used_styles.add(c["style"])
    to_remove = [s for s in style_defs if s not in used_styles]
    for s in to_remove:
        del style_defs[s]

    result["fonts"] = fonts_out
    result["styles"] = style_defs
    if dsl_areas:
        result["areas"] = dsl_areas
    if sheet_rows is not None:
        result["rows"] = sheet_rows
    if coord_areas:
        result["namedAreas"] = coord_areas
    if column_sets_out:
        result["columnSets"] = column_sets_out

    # --- 16. Convert to JSON ---

    # Описание пишется в том виде, в каком его удобно править руками: компактно там, где
    # это не мешает читать.
    json_str = to_draft_json(result)

    # --- 17. Output ---

    if output_path:
        abs_path = os.path.join(os.getcwd(), output_path) if not os.path.isabs(output_path) else output_path
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(json_str)
        print(f"[OK] Decompiled: {output_path}")
    else:
        print(json_str)

    print(f"     Areas: {len(named_areas)}, Rows: {len(row_data)}, Columns: {total_columns}", file=sys.stderr)
    print(f"     Fonts: {len(font_defs)}, Styles: {len(style_defs)}, Merges: {len(merge_map)}", file=sys.stderr)


if __name__ == "__main__":
    main()
