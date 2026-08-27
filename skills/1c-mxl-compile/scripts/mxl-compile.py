#!/usr/bin/env python3
# mxl-compile v1.1 — Compile 1C spreadsheet from JSON
# Source: https://github.com/Desko77/claude-code-skills-1c
import argparse
import json
import math
import os
import hashlib
import re
import sys
import uuid

# ============================================================
# Support guard (Ext/ParentConfigurations.bin) — see docs/1c-support-state-spec.md
# Blocks edits of vendor objects "на замке" / read-only configs. Trigger = bin
# present; reaction from .v8-project.json editingAllowedCheck (deny|warn|off,
# default deny). Never throws (except sys.exit on deny) — errors degrade to allow.
# ============================================================

# Версия формата берется из Configuration.xml вверх по дереву от каталога вывода: от нее
# зависит состав шапки макета.
def template_format_version(start_path):
    d = start_path if os.path.isdir(start_path) else os.path.dirname(os.path.abspath(start_path))
    if not d:
        d = os.getcwd()
    for _ in range(20):
        cfg_path = os.path.join(d, "Configuration.xml")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8-sig") as f:
                    head = f.read()
            except OSError:
                head = ""
            m = re.search(r'<MetaDataObject[^>]+version="(\d+\.\d+)"', head)
            if m:
                return m.group(1)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return "2.17"


def _sg_parse(xml_path):
    """Разбор XML средствами стандартной библиотеки.

    Свой, а не разбор скила: одни порты работают через lxml, другие XML не разбирают вовсе,
    и обращение к чужому имени попадало в общий except ниже - гард молча разрешал правку.
    """
    from xml.etree import ElementTree as _sg_et
    return _sg_et.parse(xml_path).getroot()


def _sg_root_uuid(xml_path):
    if not os.path.isfile(xml_path):
        return None
    try:
        mx = _sg_parse(xml_path)
        for child in mx:
            if isinstance(child.tag, str) and child.get("uuid"):
                return child.get("uuid")
    except Exception:
        return None
    return None


def _sg_is_external_root(xml_path):
    if not os.path.isfile(xml_path):
        return False
    try:
        mx = _sg_parse(xml_path)
        for child in mx:
            if isinstance(child.tag, str):
                return child.tag.split("}")[-1] in ("ExternalDataProcessor", "ExternalReport")
    except Exception:
        return False
    return False

def _sg_find_v8project(start_dir):
    d = start_dir
    for _ in range(20):
        if not d:
            break
        pj = os.path.join(d, ".v8-project.json")
        if os.path.isfile(pj):
            return pj
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _sg_get_edit_mode(cfg_dir):
    try:
        pj = _sg_find_v8project(os.getcwd()) or _sg_find_v8project(cfg_dir)
        if not pj:
            return "deny"
        proj = json.loads(open(pj, encoding="utf-8-sig").read())
        cfg_full = os.path.normcase(os.path.abspath(cfg_dir)).rstrip("\\/")
        for db in proj.get("databases", []):
            src = db.get("configSrc")
            if src:
                src_full = os.path.normcase(os.path.abspath(src)).rstrip("\\/")
                if cfg_full == src_full or cfg_full.startswith(src_full + os.sep):
                    if db.get("editingAllowedCheck"):
                        return db["editingAllowedCheck"]
        if proj.get("editingAllowedCheck"):
            return proj["editingAllowedCheck"]
        return "deny"
    except Exception:
        return "deny"


def assert_edit_allowed(target_path, require):
    try:
        rp = os.path.abspath(target_path)
        # Autonomous external object (EPF/ERF): never part of a config on support (issue #39).
        if _sg_is_external_root(rp):
            return
        elem_uuid = _sg_root_uuid(rp)
        cfg_dir = None
        bin_path = None
        d = rp if os.path.isdir(rp) else os.path.dirname(rp)
        for _ in range(12):
            if not d:
                break
            if _sg_is_external_root(d + ".xml"):
                return
            if not elem_uuid:
                elem_uuid = _sg_root_uuid(d + ".xml")
            if not cfg_dir:
                cand = os.path.join(d, "Ext", "ParentConfigurations.bin")
                if os.path.exists(cand) or os.path.exists(os.path.join(d, "Configuration.xml")):
                    cfg_dir = d
                    bin_path = cand
            if elem_uuid and cfg_dir:
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        if not elem_uuid and cfg_dir:
            elem_uuid = _sg_root_uuid(os.path.join(cfg_dir, "Configuration.xml"))
        if not bin_path or not os.path.exists(bin_path):
            return
        data = open(bin_path, "rb").read()
        if len(data) <= 32:
            return
        if data[:3] == b"\xef\xbb\xbf":
            data = data[3:]
        text = data.decode("utf-8", "replace")
        h = re.match(r"\{6,(\d+),(\d+),", text)
        if not h:
            return
        g = int(h.group(1))
        k = int(h.group(2))
        if k == 0:
            return
        best = None
        if elem_uuid:
            for m in re.finditer(r"([0-2]),0," + re.escape(elem_uuid.lower()), text):
                f1 = int(m.group(1))
                if best is None or f1 < best:
                    best = f1
        blocked = False
        code = ""
        reason = ""
        if g == 1:
            blocked = True
            code = "capability-off"
            reason = "возможность изменения конфигурации выключена (вся конфигурация read-only)"
        elif require == "removed":
            if best is not None and best != 2:
                blocked = True
                code = "not-removed"
                reason = "объект не снят с поддержки — удаление сломает обновления"
        else:
            if best is not None and best == 0:
                blocked = True
                code = "locked"
                reason = "объект на замке — редактирование сломает обновления"
        if not blocked:
            return
        mode = _sg_get_edit_mode(cfg_dir)
        if mode == "off":
            return
        if mode == "warn":
            sys.stderr.write(f"[support-guard] ПРЕДУПРЕЖДЕНИЕ: {reason}. Цель: {rp}\n")
            return
        head = "[support-guard] Редактирование отклонено: это объект типовой конфигурации на поддержке поставщика, прямое редактирование молча сломает будущие обновления."
        cfe = "Рекомендуемый путь: внести доработку в расширение (навыки cfe-borrow / cfe-patch-method) — состояние поддержки менять не нужно, обновления вендора сохраняются."
        off_note = "Снять проверку для этой базы: editingAllowedCheck = warn|off в .v8-project.json."
        if code == "capability-off":
            state = f"Состояние: у всей конфигурации выключена возможность изменения (режим read-only «из коробки») — поэтому объект «{rp}» редактировать нельзя."
            fix = (
                "Либо снять защиту явно (навык support-edit, два шага):\n"
                f'  1. support-edit -Path "{cfg_dir}" -Capability on — включить возможность изменения (объекты пока остаются на замке);\n'
                f'  2. support-edit -Path "{rp}" -Set editable — открыть этот объект для редактирования.\n'
                "  Изменение применяется в базу полной загрузкой выгрузки и обходит механизм обновлений вендора."
            )
        elif code == "not-removed":
            state = f"Состояние: объект «{rp}» на поддержке (не снят с поддержки) — его удаление разорвёт обновления вендора."
            fix = (
                "Либо сначала снять объект с поддержки, затем удалять:\n"
                f'  support-edit -Path "{rp}" -Set off-support — объект уходит из-под обновлений, после этого удаление безопасно.'
            )
        else:
            state = f"Состояние: объект «{rp}» на замке (возможность изменения конфигурации включена, но сам объект не редактируется)."
            fix = (
                "Либо разрешить редактирование этого объекта (навык support-edit, выбрать одно):\n"
                f'  support-edit -Path "{rp}" -Set editable — редактировать и дальше получать обновления вендора (возможны конфликты слияния);\n'
                f'  support-edit -Path "{rp}" -Set off-support — снять с поддержки: обновления по объекту больше не приходят.'
            )
        sys.stderr.write(head + "\n" + state + "\n" + cfe + "\n" + fix + "\n" + off_note + "\n")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        return
# --- Конец общего блока гарда поддержки ---



class LenientDict(dict):
    """Словарь, нечувствительный к регистру ключей - как PSObject в PowerShell.

    Нужен для прощающего ввода: DSL принимает и `operation`, и `Operation`. Вложенные словари
    оборачиваются тоже, иначе леность теряется на первом же уровне вложенности.
    """

    def __init__(self, data=None):
        super().__init__()
        for k, v in (data or {}).items():
            self[k] = v

    @staticmethod
    def _wrap(v):
        if isinstance(v, dict):
            return LenientDict(v)
        if isinstance(v, list):
            return [LenientDict(x) if isinstance(x, dict) else x for x in v]
        return v

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))

    def _actual_key(self, key):
        if super().__contains__(key):
            return key
        if isinstance(key, str):
            low = key.lower()
            for k in super().keys():
                if isinstance(k, str) and k.lower() == low:
                    return k
        return None

    def __getitem__(self, key):
        k = self._actual_key(key)
        if k is None:
            raise KeyError(key)
        return super().__getitem__(k)

    def __contains__(self, key):
        return self._actual_key(key) is not None

    def get(self, key, default=None):
        k = self._actual_key(key)
        return super().__getitem__(k) if k is not None else default


def _ps_scalar(value):
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if value is None:
        return ''
    return str(value)


def ps_str(value):
    """Приведение к строке по правилам PowerShell.

    Замерено на pwsh 7: одиночный объект в "$x" дает @{k=v; k2=v2}, а массив склеивает через
    пробел результаты ToString() элементов - и у разобранного из JSON объекта ToString() пуст.
    В python str() дал бы repr списка, он и уезжал в XML.
    """
    if isinstance(value, (list, tuple)):
        return ' '.join('' if isinstance(x, dict) else _ps_scalar(x) for x in value)
    if isinstance(value, dict):
        return '@{' + '; '.join(k + '=' + _ps_scalar(v) for k, v in value.items()) + '}'
    return _ps_scalar(value)


def lenient(data):
    """JSON бывает объектом и массивом объектов - оборачиваем и то, и другое."""
    if isinstance(data, list):
        return [LenientDict(x) if isinstance(x, dict) else x for x in data]
    return LenientDict(data) if isinstance(data, dict) else data




def esc_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def write_utf8_bom(path, content, eol='\r\n'):
    # Исходники 1С хранятся в CRLF: этого ждет Конфигуратор, и это закреплено в .gitattributes.
    # Сборка идет через '\n'.join, поэтому концы строк разворачиваются здесь, на записи.
    # Нормализация идемпотентна - смешанный текст тоже приходит к одному виду.
    # Правка существующего файла передает сюда его собственный eol: форсировать CRLF там
    # нельзя, иначе навык переписывает весь чужой файл ради одной добавленной строки.
    content = content.replace('\r\n', '\n').replace('\n', eol)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)


def format_version_rank(version):
    """Версии сравниваются по составным частям: 2.9 старее, чем 2.21, хотя как число больше."""
    m = re.match(r"^(\d+)\.(\d+)$", str(version or ""))
    return int(m.group(1)) * 100 + int(m.group(2)) if m else 0


# Идентификатор набора колонок выводится из его имени: UUID версии 3 (MD5) без
# пространства имен - одно и то же имя всегда дает один и тот же идентификатор.
def name_uuid(name):
    return str(uuid.UUID(bytes=hashlib.md5(name.encode('utf-8')).digest(), version=3))


# Координаты области 1-based, а ноль дал бы -1 - сентинел отсутствующей оси.
def check_named_area_bounds(begin, end, axis, index, name):
    if begin < 1 or end < begin:
        print('namedAreas: %s%s%s must be a 1-based number or ascending range, got "%s-%s": namedAreas[%d] "%s"'
              % (chr(39), axis, chr(39), begin, end, index, name), file=sys.stderr)
        sys.exit(1)
    return (begin, end)


# Ось именованной области задается числом или диапазоном; список через запятую не
# описывает прямоугольник и потому отвергается.
def named_area_range(value, axis, index, name):
    text = str(value)
    if ',' in text:
        print('namedAreas: %s%s%s must be a single number or range, got list "%s": namedAreas[%d] "%s"'
              % (chr(39), axis, chr(39), text, index, name), file=sys.stderr)
        sys.exit(1)
    m = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$', text)
    if m:
        return check_named_area_bounds(int(m.group(1)), int(m.group(2)), axis, index, name)
    m = re.match(r'^\s*(\d+)\s*$', text)
    if m:
        return check_named_area_bounds(int(m.group(1)), int(m.group(1)), axis, index, name)
    print('namedAreas: %s%s%s must be a single number or range, got "%s": namedAreas[%d] "%s"'
          % (chr(39), axis, chr(39), text, index, name), file=sys.stderr)
    sys.exit(1)


# Строка задается массивом: элемент на колонку слева направо. Такая запись разворачивается в
# канонический вид до расчета форматов и вывода, поэтому дальше по коду вид строки один.
def shorthand_cell(value, col):
    # Фигурные скобки означают параметр, квадратные внутри строки - шаблонный текст.
    m = re.match(r'^\{(.+)\}$', value)
    if m:
        return {'col': col, 'param': m.group(1)}
    if re.search(r'\[.+\]', value):
        return {'col': col, 'template': value}
    return {'col': col, 'text': value}


def expand_area_rows(area_rows, area_name):
    expanded = []
    prev_occupied = {}
    row_no = 0
    for row in (area_rows or []):
        row_no += 1
        if not isinstance(row, list):
            table = LenientDict(row)
            if table.get('cells'):
                table['cells'] = [LenientDict(c) for c in table['cells']]
            occupied = {}
            for c in (table.get('cells') or []):
                # Колонка без явного номера раскладывается позже, в основном проходе: до
                # него занятые ей клетки неизвестны, поэтому в опору для '|' она не идет.
                if not c.get('col'):
                    continue
                span = int(c['span']) if c.get('span') else 1
                for k in range(span):
                    occupied[int(c['col']) + k] = c
            prev_occupied = occupied
            expanded.append(table)
            continue

        cells = []
        occupied = {}
        last_cell = None
        col_no = 0
        for item in row:
            col_no += 1
            if item is None:
                last_cell = None
                continue

            if item == '>':
                if last_cell is None:
                    print('Row shorthand: %s has no cell to the left: area "%s", row %d, cell %d'
                          % (chr(39) + '>' + chr(39), area_name, row_no, col_no), file=sys.stderr)
                    sys.exit(1)
                last_cell['span'] = (int(last_cell['span']) if last_cell.get('span') else 1) + 1
                occupied[col_no] = last_cell
                continue

            if item == '|':
                above = prev_occupied.get(col_no)
                if above is None:
                    print('Row shorthand: %s has no cell above: area "%s", row %d, cell %d'
                          % (chr(39) + '|' + chr(39), area_name, row_no, col_no), file=sys.stderr)
                    sys.exit(1)
                above['rowspan'] = (int(above['rowspan']) if above.get('rowspan') else 1) + 1
                occupied[col_no] = above
                last_cell = None
                continue

            if isinstance(item, str):
                cell = shorthand_cell(item, col_no)
            else:
                cell = LenientDict(item)
                if 'col' in cell:
                    print('Row shorthand: cell object must not carry %scol%s: area "%s", row %d, cell %d'
                          % (chr(39), chr(39), area_name, row_no, col_no), file=sys.stderr)
                    sys.exit(1)
                cell['col'] = col_no
            cells.append(cell)
            span = int(cell['span']) if cell.get('span') else 1
            for k in range(span):
                occupied[col_no + k] = cell
            last_cell = cell
        prev_occupied = occupied
        expanded.append({'cells': cells})
    return expanded


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description='Compile 1C spreadsheet from JSON', allow_abbrev=False)
    parser.add_argument('-JsonPath', type=str, required=True)
    parser.add_argument('-OutputPath', type=str, required=True)
    args = parser.parse_args()

    # --- 1. Load and validate JSON ---
    json_path = args.JsonPath
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8-sig') as f:
        defn = lenient(json.load(f))

    if not defn.get('columns'):
        print("Required field 'columns' is missing", file=sys.stderr)
        sys.exit(1)
    if not defn.get('areas') and not defn.get('rows'):
        print("Required field 'areas' is missing", file=sys.stderr)
        sys.exit(1)

    # Строки вне именованных областей обрабатываются как безымянная область: в файл она не
    # попадает, но строки выгружаются так же.
    sheet_areas = []
    if defn.get('areas'):
        sheet_areas.extend(defn['areas'])
    if defn.get('rows'):
        sheet_areas.append({'name': '', 'rows': defn['rows']})

    sheet_areas = [LenientDict({
        'name': a.get('name') or '',
        'columnSet': a.get('columnSet'),
        'rows': expand_area_rows(a.get('rows'), a.get('name') or ''),
    }) for a in sheet_areas]

    total_columns = int(defn['columns'])
    # Языки, на которые идет текст ячейки, заданный одной строкой.
    text_languages = [str(x) for x in (defn.get('textLanguages') or ['ru'])]

    # Текст ячейки задается строкой - тогда он идет на все языки вывода - или объектом
    # вида "язык: текст", тогда на каждый язык идет свой.
    def text_items(value):
        if isinstance(value, str):
            return [(lang, value) for lang in text_languages]
        return [(str(k), str(v)) for k, v in value.items()]
    default_width = int(defn['defaultWidth']) if defn.get('defaultWidth') else 10

    # --- 2. Build font palette ---
    font_map = {}   # name -> 0-based index
    font_entries = []  # list of dicts

    def add_font(name, font_def):
        face = font_def.get('face', 'Arial') if font_def else 'Arial'
        size_value = font_def.get('size', 10) if font_def else 10
        size = repr(float(size_value)) if isinstance(size_value, float) else str(int(size_value))
        if size.endswith('.0'):
            size = size[:-2]
        bold = 'true' if font_def and font_def.get('bold') is True else 'false'
        italic = 'true' if font_def and font_def.get('italic') is True else 'false'
        underline = 'true' if font_def and font_def.get('underline') is True else 'false'
        strikeout = 'true' if font_def and font_def.get('strikeout') is True else 'false'

        idx = len(font_entries)
        font_map[name] = idx
        font_entries.append({
            # Шрифт задается либо своими свойствами, либо ссылкой на элемент стиля или
            # системный шрифт - тогда своих свойств у него нет.
            'Ref': str(font_def.get('ref')) if font_def and font_def.get('ref') else '',
            'Kind': str(font_def.get('kind')) if font_def and font_def.get('kind') else 'Absolute',
            'Namespace': font_def.get('namespace') if font_def else None,
            'Face': face,
            'Size': size,
            'Bold': bold,
            'Italic': italic,
            'Underline': underline,
            'Strikeout': strikeout,
        })

    # Add user-defined fonts
    has_default = False
    if defn.get('fonts'):
        for fname, fdef in defn['fonts'].items():
            if fname == 'default':
                has_default = True
            add_font(fname, fdef)

    # Шрифт по умолчанию не объявляется: платформа пишет шрифт только там, где он задан.

    # --- 3. Determine line palette ---
    has_thin_borders = False
    has_thick_borders = False

    if defn.get('styles'):
        for sname, sval in defn['styles'].items():
            if sval.get('border') and sval['border'] != 'none':
                if sval.get('borderWidth') == 'thick':
                    has_thick_borders = True
                else:
                    has_thin_borders = True

    thin_line_index = -1
    thick_line_index = -1
    line_count = 0
    if has_thin_borders:
        thin_line_index = line_count
        line_count += 1
    if has_thick_borders:
        thick_line_index = line_count
        line_count += 1

    # --- 4. Parse column width specs ---
    def parse_column_spec(spec):
        cols = []
        for part in spec.split(','):
            part = part.strip()
            m = re.match(r'^(\d+)-(\d+)$', part)
            if m:
                from_col = int(m.group(1))
                to_col = int(m.group(2))
                for i in range(from_col, to_col + 1):
                    cols.append(i)
            else:
                cols.append(int(part))
        return cols

    # --- 4a. Auto-calculate defaultWidth from page format ---
    page_targets = {
        'A4-landscape': 780,
        'A4-portrait': 540,
    }

    page_name = None
    target_width = None
    if defn.get('page'):
        page_name = str(defn['page'])

        if re.match(r'^\d+$', page_name):
            target_width = int(page_name)
        elif page_name in page_targets:
            target_width = page_targets[page_name]
        else:
            print(f"WARNING: Unknown page format '{page_name}'. Known: {', '.join(page_targets.keys())}, or a number.", file=sys.stderr)

        if target_width:
            total_units = 0.0
            absolute_sum = 0
            specified_cols = {}

            if defn.get('columnWidths'):
                for prop_name, prop_value in defn['columnWidths'].items():
                    val = str(prop_value)
                    cols = parse_column_spec(prop_name)
                    for c in cols:
                        specified_cols[int(c)] = True
                        m = re.match(r'^([0-9.]+)x$', val)
                        if m:
                            total_units += float(m.group(1))
                        else:
                            absolute_sum += int(val)

            for c in range(1, total_columns + 1):
                if c not in specified_cols:
                    total_units += 1.0

            if total_units > 0:
                default_width = round((target_width - absolute_sum) / total_units)

    # Build column width map: 1-based col -> width
    col_width_map = {}
    if defn.get('columnWidths'):
        for prop_name, prop_value in defn['columnWidths'].items():
            val = str(prop_value)
            m = re.match(r'^([0-9.]+)x$', val)
            if m:
                width = round(float(m.group(1)) * default_width)
            else:
                width = int(val)
            columns = parse_column_spec(prop_name)
            for c in columns:
                col_width_map[c] = width

    # Набор колонок - своя раскладка ширин для части строк. Ширины разбираются тем же
    # правилом, что и основные, а идентификатор берется из описания или выводится из имени.
    column_sets = {}
    for set_name, set_def in (defn.get('columnSets') or {}).items():
        set_widths = {}
        for wp_name, wp_value in (set_def.get('columnWidths') or {}).items():
            val = str(wp_value)
            m = re.match(r'^([0-9.]+)x$', val)
            width = round(float(m.group(1)) * default_width) if m else int(val)
            for c in parse_column_spec(wp_name):
                set_widths[c] = width
        column_sets[set_name] = {
            'Id': str(set_def.get('id')) if set_def.get('id') else name_uuid(set_name),
            'Columns': int(set_def['columns']) if set_def.get('columns') else total_columns,
            'WidthMap': set_widths,
        }

    # Ссылка на набор допустима только именем: объект на месте имени - ошибка описания.
    def resolve_column_set_name(value, area_name):
        if value is None:
            return None
        if not isinstance(value, str):
            print('%scolumnSet%s must be a name declared in columnSets, got an object: area "%s"'
                  % (chr(39), chr(39), area_name), file=sys.stderr)
            sys.exit(1)
        if value not in column_sets:
            print('%scolumnSet%s is not declared in columnSets: "%s", area "%s"'
                  % (chr(39), chr(39), value, area_name), file=sys.stderr)
            sys.exit(1)
        return value

    # --- 5. Style resolver ---
    def resolve_style(style_name, fill_type):
        # В PowerShell параметр объявлен как [string]: встроенный объект стиля превращается
        # в текст @{...}, такого имени в наборе стилей нет, и стиль молча игнорируется.
        # Здесь то же самое - иначе объект уходит в поиск по словарю и разбор падает.
        style_name = ps_str(style_name) if style_name else style_name
        font_idx = font_map.get('default', -1)
        lb = -1; tb = -1; rb = -1; bb = -1
        ha = ''; va = ''; nf = ''
        text_color = ''
        wrap = False

        if style_name and defn.get('styles'):
            style = defn['styles'].get(style_name)
            if style:
                # Font
                if style.get('font') and style['font'] in font_map:
                    font_idx = font_map[style['font']]

                # Borders
                if style.get('border') and style['border'] != 'none':
                    line_idx = thick_line_index if style.get('borderWidth') == 'thick' else thin_line_index
                    for side in style['border'].split(','):
                        side = side.strip()
                        if side == 'all':
                            lb = line_idx; tb = line_idx; rb = line_idx; bb = line_idx
                        elif side == 'left':
                            lb = line_idx
                        elif side == 'top':
                            tb = line_idx
                        elif side == 'right':
                            rb = line_idx
                        elif side == 'bottom':
                            bb = line_idx

                # Alignment
                align_value = style.get('align') or style.get('horizontalAlignment')
                if align_value:
                    align_map = {'left': 'Left', 'center': 'Center', 'right': 'Right',
                                 'justify': 'Justify'}
                    ha = align_map.get(str(align_value).lower(), '')
                valign_value = style.get('valign') or style.get('verticalAlignment')
                if valign_value:
                    valign_map = {'top': 'Top', 'center': 'Center', 'bottom': 'Bottom'}
                    va = valign_map.get(str(valign_value).lower(), '')

                # Wrap
                if style.get('wrap') is True:
                    wrap = True

                # Number format
                if style.get('format'):
                    nf = style['format']

                # Цвет текста задается ссылкой на элемент стиля платформы.
                if style.get('textColor'):
                    text_color = str(style['textColor'])

        return {
            'FontIdx': font_idx,
            'LB': lb, 'TB': tb, 'RB': rb, 'BB': bb,
            'HA': ha, 'VA': va,
            'Wrap': wrap,
            'FillType': fill_type,
            'NumberFormat': nf,
            'TextColor': text_color,
        }

    # --- 6. Format palette builder ---
    format_registry = {}   # key -> props
    format_order = []       # ordered keys for index assignment

    def get_format_key(font_idx=-1, lb=-1, tb=-1, rb=-1, bb=-1, ha='', va='',
                       wrap=False, fill_type='', number_format='', width=-1, height=-1,
                       text_color='', hidden=False):
        return (f'f={font_idx}|lb={lb}|tb={tb}|rb={rb}|bb={bb}|ha={ha}|va={va}|wr={wrap}'
                f'|ft={fill_type}|nf={number_format}|w={width}|h={height}'
                f'|tc={text_color}|hd={hidden}')

    def register_format(key, props):
        if key not in format_registry:
            format_registry[key] = props
            format_order.append(key)
        # Return 1-based index
        return format_order.index(key) + 1

    # 6a. Default width format

    # 6b. Column width formats
    col_format_map = {}  # 1-based col -> format index
    for col in sorted(col_width_map):
        w = col_width_map[col]
        key = get_format_key(width=w)
        idx = register_format(key, {'Width': w})
        col_format_map[int(col)] = idx

    # 6b-1. Форматы ширин наборов колонок
    set_format_maps = {}
    for set_name, set_info in column_sets.items():
        set_map = {}
        for col in sorted(set_info['WidthMap']):
            w = set_info['WidthMap'][col]
            set_map[int(col)] = register_format(get_format_key(width=w), {'Width': w})
        set_format_maps[set_name] = set_map

    # 6c. Helper: determine fillType from cell content
    def get_fill_type(cell):
        if cell.get('param'):
            return 'Parameter'
        if cell.get('template'):
            return 'Template'
        return ''

    # Helper: register a cell format and return its index
    def register_cell_format(style_name, fill_type):
        resolved = resolve_style(style_name, fill_type)
        key = get_format_key(
            font_idx=resolved['FontIdx'],
            lb=resolved['LB'], tb=resolved['TB'], rb=resolved['RB'], bb=resolved['BB'],
            ha=resolved['HA'], va=resolved['VA'],
            wrap=resolved['Wrap'], fill_type=resolved['FillType'],
            number_format=resolved['NumberFormat'],
            text_color=resolved['TextColor'])
        props = {
            'FontIdx': resolved['FontIdx'],
            'LB': resolved['LB'], 'TB': resolved['TB'],
            'RB': resolved['RB'], 'BB': resolved['BB'],
            'HA': resolved['HA'], 'VA': resolved['VA'],
            'Wrap': resolved['Wrap'],
            'FillType': resolved['FillType'],
            'NumberFormat': resolved['NumberFormat'],
            'TextColor': resolved['TextColor'],
        }
        if key == get_format_key(font_idx=-1):
            return 0
        return register_format(key, props)

    # Формат строки собирается из высоты, скрытия и собственного стиля строки: платформа
    # держит их одним форматом.
    def get_row_format(row):
        row_height = int(row['height']) if row.get('height') else -1
        row_hidden = row.get('hidden') is True
        props = {'Hidden': row_hidden}
        if row_height >= 0:
            props['Height'] = row_height
        if not row.get('style'):
            return get_format_key(height=row_height, hidden=row_hidden), props
        r = resolve_style(row['style'], '')
        props.update({
            'FontIdx': r['FontIdx'],
            'LB': r['LB'], 'TB': r['TB'], 'RB': r['RB'], 'BB': r['BB'],
            'HA': r['HA'], 'VA': r['VA'],
            'Wrap': r['Wrap'],
            'NumberFormat': r['NumberFormat'],
            'TextColor': r['TextColor'],
        })
        key = get_format_key(
            font_idx=r['FontIdx'], lb=r['LB'], tb=r['TB'], rb=r['RB'], bb=r['BB'],
            ha=r['HA'], va=r['VA'], wrap=r['Wrap'], number_format=r['NumberFormat'],
            text_color=r['TextColor'], height=row_height, hidden=row_hidden)
        return key, props

    # Pre-register all formats from areas
    for area in sheet_areas:
        for row in area.get('rows', []):
            # Skip list-of-values shorthand rows (treated as empty rows like PS1)
            if isinstance(row, list):
                continue
            # Skip empty row placeholder
            if row.get('empty'):
                continue

            # Row height format
            if row.get('height') or row.get('hidden') is True or row.get('style'):
                h_key, h_props = get_row_format(row)
                register_format(h_key, h_props)

            # rowStyle gap-fill format
            if row.get('rowStyle'):
                register_cell_format(row['rowStyle'], '')

            # Explicit cell formats
            if row.get('cells'):
                for cell in row['cells']:
                    cell_style = cell.get('style') or row.get('rowStyle') or 'default'
                    ft = get_fill_type(cell)
                    register_cell_format(cell_style, ft)

    # --- 7. Generate XML ---
    lines = []

    # 7a. Header
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    # Палитра появляется в шапке макета с формата 2.21 (8.5) и встает после основного
    # пространства имен.
    mxl_pal = (' xmlns:pal="http://v8.1c.ru/8.1/data/ui/colors/palette"'
               if format_version_rank(template_format_version(args.OutputPath)) >= 221 else '')
    lines.append(f'<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet"{mxl_pal} xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')

    # 7b. Language settings
    # Ширина по умолчанию идет последним форматом палитры: платформа пишет ее
    # после всех прочих.
    default_format_key = get_format_key(width=default_width)
    default_format_index = register_format(default_format_key, {'Width': default_width})

    # Состав языков берется из описания: у макета их бывает несколько, и порядок значим.
    russian = '\u0420\u0443\u0441\u0441\u043a\u0438\u0439'
    language_list = []
    for lang in (defn.get('languages') or []):
        if isinstance(lang, str):
            language_list.append({'id': lang, 'code': lang, 'description': lang})
        else:
            lang_id = str(lang.get('id', ''))
            language_list.append({
                'id': lang_id,
                'code': str(lang.get('code') or lang_id),
                'description': str(lang.get('description') or lang_id),
            })
    if not language_list:
        language_list = [{'id': 'ru', 'code': russian, 'description': russian}]
    current_language = str(defn.get('currentLanguage') or language_list[0]['id'])
    default_language = str(defn.get('defaultLanguage') or language_list[0]['id'])

    lines.append('\t<languageSettings>')
    lines.append(f'\t\t<currentLanguage>{current_language}</currentLanguage>')
    lines.append(f'\t\t<defaultLanguage>{default_language}</defaultLanguage>')
    for lang in language_list:
        lines.append('\t\t<languageInfo>')
        lines.append(f'\t\t\t<id>{esc_xml(lang["id"])}</id>')
        lines.append(f'\t\t\t<code>{esc_xml(lang["code"])}</code>')
        lines.append(f'\t\t\t<description>{esc_xml(lang["description"])}</description>')
        lines.append('\t\t</languageInfo>')
    lines.append('\t</languageSettings>')

    # 7c. Columns
    lines.append('\t<columns>')
    lines.append(f'\t\t<size>{total_columns}</size>')

    # Emit columnsItem for columns with non-default widths
    for col in sorted(col_format_map.keys()):
        fmt_idx = col_format_map[col]
        col_idx = col - 1  # Convert to 0-based
        lines.append('\t\t<columnsItem>')
        lines.append(f'\t\t\t<index>{col_idx}</index>')
        lines.append('\t\t\t<column>')
        lines.append(f'\t\t\t\t<formatIndex>{fmt_idx}</formatIndex>')
        lines.append('\t\t\t</column>')
        lines.append('\t\t</columnsItem>')

    lines.append('\t</columns>')

    # Раскладки наборов идут отдельными блоками колонок, отличаясь идентификатором.
    for set_name, set_info in column_sets.items():
        lines.append('\t<columns>')
        lines.append(f'\t\t<id>{set_info["Id"]}</id>')
        lines.append(f'\t\t<size>{set_info["Columns"]}</size>')
        set_map = set_format_maps[set_name]
        for col in sorted(set_map):
            lines.append('\t\t<columnsItem>')
            lines.append(f'\t\t\t<index>{col - 1}</index>')
            lines.append('\t\t\t<column>')
            lines.append(f'\t\t\t\t<formatIndex>{set_map[col]}</formatIndex>')
            lines.append('\t\t\t</column>')
            lines.append('\t\t</columnsItem>')
        lines.append('\t</columns>')

    # 7d. Rows -- main generation loop
    global_row = 0
    merges = []
    named_items = []
    active_rowspans = []  # list of {ColStart, ColEnd, StartLocalRow, EndLocalRow}

    for area in sheet_areas:
        area_start_row = global_row
        area_name = area.get('name', '')
        area_column_set = resolve_column_set_name(area.get('columnSet'), area_name)
        active_rowspans = []
        local_row = 0

        for row in area.get('rows', []):
            # Набор колонок области действует на все ее строки; строка может задать свой.
            row_column_set = (resolve_column_set_name(row['columnSet'], area_name)
                              if row.get('columnSet') is not None else area_column_set)
            # Ширина строки берется из выбранного набора колонок: у набора она своя, и
            # проверять колонки строки по раскладке документа нельзя.
            row_columns = (column_sets[row_column_set]['Columns'] if row_column_set
                           else total_columns)

            # Empty row placeholder: emit N empty rows
            if row.get('empty'):
                count = int(row['empty'])
                for ei in range(count):
                    lines.append('\t<rowsItem>')
                    lines.append(f'\t\t<index>{global_row}</index>')
                    lines.append('\t\t<row>')
                    if row_column_set:
                        lines.append(f'\t\t\t<columnsID>{column_sets[row_column_set]["Id"]}</columnsID>')
                    lines.append('\t\t\t<empty>true</empty>')
                    lines.append('\t\t</row>')
                    lines.append('\t</rowsItem>')
                    global_row += 1
                    local_row += 1
                continue

            # Build set of columns occupied by rowspans from previous rows
            rowspan_occupied = {}
            for rs in active_rowspans:
                if local_row > rs['StartLocalRow'] and local_row <= rs['EndLocalRow']:
                    for c in range(rs['ColStart'], rs['ColEnd'] + 1):
                        rowspan_occupied[c] = True

            row_has_content = False
            row_cells = []

            # Determine row height format
            row_format_idx = 0
            if row.get('height') or row.get('hidden') is True or row.get('style'):
                h_key = get_row_format(row)[0]
                if h_key in format_registry:
                    row_format_idx = format_order.index(h_key) + 1

            if row.get('cells') and len(row['cells']) > 0:
                row_has_content = True

                # Явные номера колонок проверяются до раскладки: дальше по коду они уже
                # приводятся к числу, и отличить "0" от отсутствующего значения будет нельзя.
                with_col = 0
                for cell_no, cell in enumerate(row["cells"], 1):
                    raw = cell.get("col")
                    if raw is None or str(raw) == "":
                        continue
                    with_col += 1
                    try:
                        col_num = int(str(raw))
                    except ValueError:
                        col_num = 0
                    if col_num < 1 or col_num > row_columns:
                        print(f'Invalid \'col\' value "{raw}": area "{area_name}", row {local_row + 1}, cell {cell_no}', file=sys.stderr)
                        sys.exit(1)
                if 0 < with_col < len(row["cells"]):
                    print(f'Cell without \'col\' mixed with positioned cells: area "{area_name}", row {local_row + 1}', file=sys.stderr)
                    sys.exit(1)

                # Ячейка без col занимает ближайшую свободную колонку слева направо. Раньше
                # такой ячейке доставался номер 0 (пустое свойство приводилось к нулю), и в
                # файл уходил индекс -1 сразу для всех - колонки не различались.
                claimed = dict(rowspan_occupied)
                for cell in row['cells']:
                    if cell.get('col'):
                        cs = int(cell['col'])
                        sp = int(cell.get('span', 1))
                        for c in range(cs, cs + sp):
                            claimed[c] = True
                cursor = 1
                for cell in row['cells']:
                    if cell.get('col'):
                        continue
                    sp = int(cell.get('span', 1))
                    # Свободным должен быть ВЕСЬ диапазон объединения: иначе ячейка с span
                    # начиналась в свободной колонке и накрывала занятую соседнюю.
                    while any(claimed.get(c) for c in range(cursor, cursor + sp)):
                        cursor += 1
                    if cursor + sp - 1 > row_columns:
                        print(f'Row exceeds \'columns\' ({row_columns}): area "{area_name}", row {local_row + 1}', file=sys.stderr)
                        sys.exit(1)
                    cell['col'] = cursor
                    for c in range(cursor, cursor + sp):
                        claimed[c] = True
                    cursor += sp

                # Build set of occupied columns (1-based)
                occupied_cols = dict(rowspan_occupied)
                for cell in row['cells']:
                    col_start = int(cell['col'])
                    col_span = int(cell.get('span', 1))
                    for c in range(col_start, col_start + col_span):
                        occupied_cols[c] = True

                # Generate explicit cells
                for cell in row['cells']:
                    col_start = int(cell['col'])
                    col_span = int(cell.get('span', 1))
                    rowspan = int(cell.get('rowspan', 1))
                    cell_style = cell.get('style') or row.get('rowStyle') or 'default'
                    ft = get_fill_type(cell)
                    fmt_idx = register_cell_format(cell_style, ft)

                    cell_info = {
                        'Col': col_start - 1,  # 0-based
                        'FormatIdx': fmt_idx,
                        'Param': cell.get('param'),
                        'Detail': cell.get('detail'),
                        'Text': cell.get('text'),
                        'Template': cell.get('template'),
                    }
                    row_cells.append(cell_info)

                    # Track rowspan for subsequent rows
                    if rowspan > 1:
                        active_rowspans.append({
                            'ColStart': col_start,
                            'ColEnd': col_start + col_span - 1,
                            'StartLocalRow': local_row,
                            'EndLocalRow': local_row + rowspan - 1,
                        })

                    # Collect merge
                    if col_span > 1 or rowspan > 1:
                        merge = {'R': global_row, 'C': col_start - 1, 'W': col_span - 1}
                        if rowspan > 1:
                            merge['H'] = rowspan - 1
                        merges.append(merge)

                # Generate gap-fill cells for rowStyle
                if row.get('rowStyle'):
                    gap_fmt_idx = register_cell_format(row['rowStyle'], '')
                    for c in range(1, row_columns + 1):
                        if c not in occupied_cols:
                            row_cells.append({
                                'Col': c - 1,
                                'FormatIdx': gap_fmt_idx,
                                'Param': None,
                                'Detail': None,
                                'Text': None,
                                'Template': None,
                            })

                # Sort cells by column
                row_cells.sort(key=lambda x: x['Col'])

            elif row.get('rowStyle'):
                # Row with only rowStyle, no explicit cells
                row_has_content = True
                gap_fmt_idx = register_cell_format(row['rowStyle'], '')
                for c in range(1, row_columns + 1):
                    if c in rowspan_occupied:
                        continue
                    row_cells.append({
                        'Col': c - 1,
                        'FormatIdx': gap_fmt_idx,
                        'Param': None,
                        'Detail': None,
                        'Text': None,
                        'Template': None,
                    })

            # Emit rowsItem
            lines.append('\t<rowsItem>')
            lines.append(f'\t\t<index>{global_row}</index>')
            lines.append('\t\t<row>')

            if row_column_set:
                lines.append(f'\t\t\t<columnsID>{column_sets[row_column_set]["Id"]}</columnsID>')

            if row_format_idx > 0:
                lines.append(f'\t\t\t<formatIndex>{row_format_idx}</formatIndex>')

            if not row_has_content:
                lines.append('\t\t\t<empty>true</empty>')
            else:
                # Индекс колонки платформа пишет только при разрыве: ячейки, идущие подряд от
                # начала строки, нумеруются по порядку следования.
                expected_col = 0
                for cell_info in row_cells:
                    lines.append('\t\t\t<c>')
                    if int(cell_info['Col']) != expected_col:
                        lines.append(f'\t\t\t\t<i>{cell_info["Col"]}</i>')
                    expected_col = int(cell_info['Col']) + 1
                    lines.append('\t\t\t\t<c>')
                    lines.append(f'\t\t\t\t\t<f>{cell_info["FormatIdx"]}</f>')

                    if cell_info['Param']:
                        lines.append(f'\t\t\t\t\t<parameter>{cell_info["Param"]}</parameter>')
                        if cell_info['Detail']:
                            lines.append(f'\t\t\t\t\t<detailParameter>{cell_info["Detail"]}</detailParameter>')

                    if cell_info['Text']:
                        lines.append('\t\t\t\t\t<tl>')
                        for ti_lang, ti_content in text_items(cell_info['Text']):
                            lines.append('\t\t\t\t\t\t<v8:item>')
                            lines.append(f'\t\t\t\t\t\t\t<v8:lang>{ti_lang}</v8:lang>')
                            lines.append(f'\t\t\t\t\t\t\t<v8:content>{esc_xml(ti_content)}</v8:content>')
                            lines.append('\t\t\t\t\t\t</v8:item>')
                        lines.append('\t\t\t\t\t</tl>')

                    if cell_info['Template']:
                        lines.append('\t\t\t\t\t<tl>')
                        for ti_lang, ti_content in text_items(cell_info['Template']):
                            lines.append('\t\t\t\t\t\t<v8:item>')
                            lines.append(f'\t\t\t\t\t\t\t<v8:lang>{ti_lang}</v8:lang>')
                            lines.append(f'\t\t\t\t\t\t\t<v8:content>{esc_xml(ti_content)}</v8:content>')
                            lines.append('\t\t\t\t\t\t</v8:item>')
                        lines.append('\t\t\t\t\t</tl>')

                    lines.append('\t\t\t\t</c>')
                    lines.append('\t\t\t</c>')

            lines.append('\t\t</row>')
            lines.append('\t</rowsItem>')

            local_row += 1
            global_row += 1

        area_end_row = global_row - 1
        # Безымянная область - это строки самого документа: именованной области у них нет.
        if area_name:
            named_items.append({
                'Name': area_name,
                'Type': 'Rows',
                'BeginRow': area_start_row,
                'EndRow': area_end_row,
                'BeginColumn': -1,
                'EndColumn': -1,
            })

    # Именованная область задается и координатами: вид выводится из того, какие оси заданы.
    for na_index, na in enumerate(defn.get('namedAreas') or [], start=1):
        na_name = str(na.get('name') or '')
        has_rows = na.get('rows') is not None and str(na.get('rows')) != ''
        has_cols = na.get('cols') is not None and str(na.get('cols')) != ''
        if not has_rows and not has_cols:
            print('namedAreas: at least one of %srows%s/%scols%s is required: namedAreas[%d] "%s"'
                  % (chr(39), chr(39), chr(39), chr(39), na_index, na_name), file=sys.stderr)
            sys.exit(1)
        row_range = named_area_range(na['rows'], 'rows', na_index, na_name) if has_rows else None
        col_range = named_area_range(na['cols'], 'cols', na_index, na_name) if has_cols else None
        if row_range and col_range:
            na_type = 'Rectangle'
        elif row_range:
            na_type = 'Rows'
        else:
            na_type = 'Columns'
        named_items.append({
            'Name': na_name,
            'Type': na_type,
            'BeginRow': row_range[0] - 1 if row_range else -1,
            'EndRow': row_range[1] - 1 if row_range else -1,
            'BeginColumn': col_range[0] - 1 if col_range else -1,
            'EndColumn': col_range[1] - 1 if col_range else -1,
        })

    total_row_count = global_row

    # 7e. Scalar metadata
    lines.append(f'\t<templateMode>true</templateMode>')
    lines.append(f'\t<defaultFormatIndex>{default_format_index}</defaultFormatIndex>')
    lines.append(f'\t<height>{total_row_count}</height>')
    lines.append(f'\t<vgRows>{total_row_count}</vgRows>')

    # 7f. Merges
    for m in merges:
        lines.append('\t<merge>')
        lines.append(f'\t\t<r>{m["R"]}</r>')
        lines.append(f'\t\t<c>{m["C"]}</c>')
        if m.get('H'):
            lines.append(f'\t\t<h>{m["H"]}</h>')
        lines.append(f'\t\t<w>{m["W"]}</w>')
        lines.append('\t</merge>')

    # 7g. Named items
    for ni in named_items:
        lines.append('\t<namedItem xsi:type=\"NamedItemCells\">')
        lines.append(f'\t\t<name>{esc_xml(ni["Name"])}</name>')
        lines.append('\t\t<area>')
        lines.append(f'\t\t\t<type>{ni["Type"]}</type>')
        lines.append(f'\t\t\t<beginRow>{ni["BeginRow"]}</beginRow>')
        lines.append(f'\t\t\t<endRow>{ni["EndRow"]}</endRow>')
        lines.append(f'\t\t\t<beginColumn>{ni["BeginColumn"]}</beginColumn>')
        lines.append(f'\t\t\t<endColumn>{ni["EndColumn"]}</endColumn>')
        lines.append('\t\t</area>')
        lines.append('\t</namedItem>')

    # 7h. Line palette
    if has_thin_borders:
        lines.append('\t<line width="1" gap="false">')
        lines.append('\t\t<v8ui:style xsi:type="v8ui:SpreadsheetDocumentCellLineType">Solid</v8ui:style>')
        lines.append('\t</line>')
    if has_thick_borders:
        lines.append('\t<line width="2" gap="false">')
        lines.append('\t\t<v8ui:style xsi:type="v8ui:SpreadsheetDocumentCellLineType">Solid</v8ui:style>')
        lines.append('\t</line>')

    # 7i. Font palette
    for fe in font_entries:
        if fe.get('Ref'):
            # Объявление пространства имен идет первым атрибутом - так пишет платформа.
            ns_attr = ''
            for ns_prefix, ns_uri in (fe.get('Namespace') or {}).items():
                ns_attr += f' xmlns:{ns_prefix}="{esc_xml(str(ns_uri))}"'
            lines.append(f'\t<font{ns_attr} ref="{esc_xml(fe["Ref"])}" kind="{fe["Kind"]}"/>')
            continue
        lines.append(f'\t<font faceName="{fe["Face"]}" height="{fe["Size"]}" bold="{fe["Bold"]}" italic="{fe["Italic"]}" underline="{fe["Underline"]}" strikeout="{fe["Strikeout"]}" kind="Absolute" scale="100"/>')

    # 7j. Format palette
    for key in format_order:
        fmt = format_registry[key]
        lines.append('\t<format>')

        if fmt.get('Hidden') is True:
            lines.append('\t\t<hidden>true</hidden>')
        if fmt.get('FontIdx') is not None and fmt.get('FontIdx', -1) >= 0:
            lines.append(f'\t\t<font>{fmt["FontIdx"]}</font>')
        if fmt.get('TextColor'):
            lines.append(f'\t\t<textColor>{esc_xml(fmt["TextColor"])}</textColor>')
        # Рамка со всех сторон одной линией пишется одним тегом - так делает платформа.
        same_border = (fmt.get('LB') is not None and fmt.get('LB', -1) >= 0
                       and fmt.get('LB') == fmt.get('TB') == fmt.get('RB') == fmt.get('BB'))
        if same_border:
            lines.append(f'\t\t<border>{fmt["LB"]}</border>')
        if not same_border and fmt.get('LB') is not None and fmt.get('LB', -1) >= 0:
            lines.append(f'\t\t<leftBorder>{fmt["LB"]}</leftBorder>')
        if not same_border and fmt.get('TB') is not None and fmt.get('TB', -1) >= 0:
            lines.append(f'\t\t<topBorder>{fmt["TB"]}</topBorder>')
        if not same_border and fmt.get('RB') is not None and fmt.get('RB', -1) >= 0:
            lines.append(f'\t\t<rightBorder>{fmt["RB"]}</rightBorder>')
        if not same_border and fmt.get('BB') is not None and fmt.get('BB', -1) >= 0:
            lines.append(f'\t\t<bottomBorder>{fmt["BB"]}</bottomBorder>')
        if fmt.get('Width'):
            lines.append(f'\t\t<width>{fmt["Width"]}</width>')
        if fmt.get('Height'):
            lines.append(f'\t\t<height>{fmt["Height"]}</height>')
        if fmt.get('HA'):
            lines.append(f'\t\t<horizontalAlignment>{fmt["HA"]}</horizontalAlignment>')
        if fmt.get('VA'):
            lines.append(f'\t\t<verticalAlignment>{fmt["VA"]}</verticalAlignment>')
        if fmt.get('Wrap') is True:
            lines.append('\t\t<textPlacement>Wrap</textPlacement>')
        if fmt.get('FillType'):
            lines.append(f'\t\t<fillType>{fmt["FillType"]}</fillType>')
        if fmt.get('NumberFormat'):
            lines.append('\t\t<format>')
            lines.append('\t\t\t<v8:item>')
            lines.append('\t\t\t\t<v8:lang>ru</v8:lang>')
            lines.append(f'\t\t\t\t<v8:content>{esc_xml(fmt["NumberFormat"])}</v8:content>')
            lines.append('\t\t\t</v8:item>')
            lines.append('\t\t</format>')

        lines.append('\t</format>')

    # 7k. Close document
    lines.append('</document>')

    # --- 8. Write output ---
    out_path = args.OutputPath
    assert_edit_allowed(out_path, "editable")
    if not os.path.isabs(out_path):
        out_path = os.path.join(os.getcwd(), out_path)

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Платформа не оставляет перевод строки после закрывающего тега - лишний перевод
    # дает расхождение в первой же сверке с выгрузкой Конфигуратора.
    content = '\n'.join(lines)
    write_utf8_bom(out_path, content)

    # --- 9. Summary ---
    print(f"[OK] Compiled: {args.OutputPath}")
    if defn.get('page'):
        print(f"     Page: {page_name} -> target {target_width}, defaultWidth={default_width}")
    print(f"     Areas: {len(named_items)}, Rows: {total_row_count}, Columns: {total_columns}")
    print(f"     Fonts: {len(font_entries)}, Lines: {line_count}, Formats: {len(format_registry)}")
    print(f"     Merges: {len(merges)}")


if __name__ == '__main__':
    main()
