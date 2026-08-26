#!/usr/bin/env python3
# cfe-patch-method v1.2 - Generate and resync method interceptors for 1C extension (CFE)
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

MARK_INS_START = "#Вставка"
MARK_INS_END = "#КонецВставки"
MARK_DEL_START = "#Удаление"
MARK_DEL_END = "#КонецУдаления"

PROC = "Процедура"
FUNC = "Функция"
END_PROC = "КонецПроцедуры"
END_FUNC = "КонецФункции"
REGION = "#Область"
END_REGION = "#КонецОбласти"
IF_START = "#Если"
THEN = "Тогда"
END_IF = "#КонецЕсли"

DECORATORS = {
    "Before": "&Перед",
    "After": "&После",
    "Instead": "&Вместо",
    "ModificationAndControl": "&ИзменениеИКонтроль",
}

TYPE_DIR_MAP = {
    "Catalog": "Catalogs", "Document": "Documents", "Enum": "Enums",
    "CommonModule": "CommonModules", "Report": "Reports", "DataProcessor": "DataProcessors",
    "ExchangePlan": "ExchangePlans", "ChartOfAccounts": "ChartsOfAccounts",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "BusinessProcess": "BusinessProcesses", "Task": "Tasks",
    "InformationRegister": "InformationRegisters", "AccumulationRegister": "AccumulationRegisters",
    "AccountingRegister": "AccountingRegisters", "CalculationRegister": "CalculationRegisters",
}
TYPE_DIR_MAP.update({v: v for v in list(TYPE_DIR_MAP.values())})
DIR_TYPE_MAP = {
    "CommonModules": "CommonModule", "Catalogs": "Catalog", "Documents": "Document",
    "Enums": "Enum", "Reports": "Report", "DataProcessors": "DataProcessor",
    "ExchangePlans": "ExchangePlan", "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "BusinessProcesses": "BusinessProcess", "Tasks": "Task",
    "InformationRegisters": "InformationRegister", "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister", "CalculationRegisters": "CalculationRegister",
}

MODULE_FILE_MAP = {
    "ObjectModule": "ObjectModule.bsl",
    "ManagerModule": "ManagerModule.bsl",
    "RecordSetModule": "RecordSetModule.bsl",
    "CommandModule": "CommandModule.bsl",
}


def read_bsl(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return fh.read()


def write_bsl(path, text):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(text)


def split_lines(text):
    return re.split(r"\r?\n", text) if text else []


def meaningful(lines, keep_comments=False):
    out = []
    for line in lines:
        t = line.strip()
        if not t:
            continue
        if not keep_comments and t.startswith("//"):
            continue
        out.append(t)
    return out


def find_method(text, name):
    """Сигнатура, тело, директива компиляции и охватывающее условие препроцессора."""
    lines = split_lines(text)
    head_pattern = re.compile(
        r"^[ 	]*(" + PROC + "|" + FUNC + r")\s+" + re.escape(name) + r"\s*\(",
        re.IGNORECASE,
    )
    start = -1
    decl_end = -1
    is_func = False
    params = ""
    for i, line in enumerate(lines):
        m = head_pattern.match(line)
        if not m:
            continue
        # Список параметров переносится на несколько строк - объявление читается
        # до закрывающей скобки, а не в пределах одной строки.
        decl = line
        j = i
        while ")" not in decl and j + 1 < len(lines):
            j += 1
            decl += " " + lines[j].strip()
        if ")" not in decl:
            continue
        start, decl_end = i, j
        is_func = m.group(1).lower().startswith(FUNC[0].lower())
        params = decl[decl.index("(") + 1:decl.index(")")].strip()
        break
    if start < 0:
        return None

    end_word = END_FUNC if is_func else END_PROC
    end = -1
    for i in range(decl_end + 1, len(lines)):
        if lines[i].strip().startswith(end_word):
            end = i
            break
    if end < 0:
        end = len(lines)

    body = lines[decl_end + 1:end]

    directive = ""
    for i in range(start - 1, -1, -1):
        t = lines[i].strip()
        if not t or t.startswith("//"):
            continue
        if t.startswith("&"):
            directive = t
        break

    preproc = ""
    cond_re = re.compile(r"^" + IF_START + r"\s+(.+?)\s+" + THEN + r"$")
    for i in range(start - 1, -1, -1):
        m = cond_re.match(lines[i].strip())
        if m:
            for j in range(end + 1, len(lines)):
                if lines[j].strip() == END_IF:
                    preproc = m.group(1)
                    break
            break

    return {
        "is_function": is_func,
        "params": params,
        "body": body,
        "directive": directive,
        "preproc": preproc,
        "start": start,
        "decl_end": decl_end,
        "end": end,
    }


def split_interceptor_body(lines):
    """Код оригинала, вставки разработчика и отключенные им фрагменты оригинала."""
    segments = []
    current = {"kind": "base", "lines": []}
    for line in lines:
        t = line.strip()
        if t in (MARK_INS_START, MARK_DEL_START):
            if current["lines"]:
                segments.append(current)
            current = {"kind": "insert" if t == MARK_INS_START else "delete", "lines": []}
            continue
        if t in (MARK_INS_END, MARK_DEL_END):
            segments.append(current)
            current = {"kind": "base", "lines": []}
            continue
        current["lines"].append(line)
    if current["lines"]:
        segments.append(current)
    return segments


def block_present(hay, needle):
    """Идут ли строки блока подряд; пустые строки и комментарии не учитываются."""
    n = meaningful(needle)
    if not n:
        return False
    h = [x for x in meaningful(hay, keep_comments=True) if not x.startswith("//")]
    if len(n) > len(h):
        return False
    for i in range(len(h) - len(n) + 1):
        if h[i:i + len(n)] == n:
            return True
    return False


def line_indexes(lines, value):
    return [i for i, l in enumerate(lines) if l.strip() == value]


def format_edit(edit):
    open_mark = MARK_INS_START if edit["kind"] == "insert" else MARK_DEL_START
    close_mark = MARK_INS_END if edit["kind"] == "insert" else MARK_DEL_END
    return [open_mark] + edit["lines"] + [close_mark]


def find_block_start(lines, block):
    """С какой строки начинается блок; пустые строки и комментарии не учитываются."""
    n = meaningful(block)
    if not n:
        return -1
    for i in range(len(lines)):
        if lines[i].strip() != n[0]:
            continue
        k = i
        ok = True
        for needle in n:
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k >= len(lines) or lines[k].strip() != needle:
                ok = False
                break
            k += 1
        if ok:
            return i
    return -1


def merge_edits(segments, orig_body):
    """Переносит правки разработчика в новую редакцию тела метода."""
    edits = []
    old_base = []
    for seg in segments:
        if seg["kind"] == "base":
            old_base.extend(seg["lines"])
            continue
        edit = {"kind": seg["kind"], "lines": seg["lines"], "before": "", "after": "",
                "index": len(old_base)}
        for i in range(len(old_base) - 1, -1, -1):
            if old_base[i].strip():
                edit["before"] = old_base[i].strip()
                break
        edits.append(edit)
        # Отключенный фрагмент был частью оригинала - он входит в прежнюю редакцию тела.
        if seg["kind"] == "delete":
            old_base.extend(seg["lines"])

    for edit in edits:
        idx = edit["index"] + (len(edit["lines"]) if edit["kind"] == "delete" else 0)
        for i in range(idx, len(old_base)):
            if old_base[i].strip():
                edit["after"] = old_base[i].strip()
                break

    unchanged = meaningful(old_base, keep_comments=True) == meaningful(orig_body, keep_comments=True)

    result = list(orig_body)
    kept = 0
    transferred = 0
    orphan = []
    conflicts = []

    for edit in edits:
        present = block_present(orig_body, edit["lines"])
        if edit["kind"] == "insert" and present:
            # Правка попала в основную конфигурацию: держать ее в расширении незачем.
            transferred += 1
            for c in [l for l in edit["lines"] if l.strip().startswith("//")]:
                if not block_present(orig_body, [c]):
                    orphan.append(c.strip())
            continue
        if edit["kind"] == "delete" and not present:
            transferred += 1
            continue
        if edit["kind"] == "delete" and present:
            # Вставка второй копии оставила бы отключенный код исполняться без маркеров.
            at = find_block_start(result, edit["lines"])
            if at >= 0:
                count = len(meaningful(edit["lines"]))
                result.insert(at + count, MARK_DEL_END)
                result.insert(at, MARK_DEL_START)
                kept += 1
                continue
            conflicts.append(edit)
            continue

        pos = -1
        if edit["after"]:
            hits = line_indexes(result, edit["after"])
            if len(hits) == 1:
                pos = hits[0]
        if pos < 0 and edit["before"]:
            hits = line_indexes(result, edit["before"])
            if len(hits) == 1:
                pos = hits[0] + 1
        if pos < 0:
            conflicts.append(edit)
            continue

        block = format_edit(edit)
        result[pos:pos] = block
        kept += 1

    if conflicts:
        result.append("\t// [РЕСИНК-КОНФЛИКТ] блоки ниже не легли автоматически - перенесите вручную.")
        for num, edit in enumerate(conflicts, start=1):
            word = "вставка" if edit["kind"] == "insert" else "удаление"
            result.append(
                "\t// [РЕСИНК-КОНФЛИКТ №%d] %s - исходный якорь изменен в новом оригинале." % (num, word))
            result.extend(format_edit(edit))

    return {
        "lines": result,
        "kept": kept,
        "transferred": transferred,
        "conflicts": len(conflicts),
        "orphan": orphan,
        "unchanged": unchanged,
    }


def resync_interceptor(ext_file, orig_file, method, proc_name, apply_changes):
    """Сверяет перехватчик ИзменениеИКонтроль с оригиналом и при разрешении переписывает его."""
    if not orig_file or not os.path.isfile(orig_file):
        return {"status": "no-original"}
    orig_info = find_method(read_bsl(orig_file), method)
    if orig_info is None:
        return {"status": "no-original"}

    ext_text = read_bsl(ext_file)
    ext_info = find_method(ext_text, proc_name)
    if ext_info is None:
        return {"status": "no-interceptor"}

    merged = merge_edits(split_interceptor_body(ext_info["body"]), orig_info["body"])
    same_signature = (ext_info["params"] == orig_info["params"]
                      and ext_info["is_function"] == orig_info["is_function"])
    if merged["unchanged"] and same_signature:
        return {"status": "actual", "kept": 0, "transferred": 0, "conflicts": 0, "orphan": []}

    if apply_changes:
        lines = split_lines(ext_text)
        # Объявление пересобирается по оригиналу: смена списка параметров или вида метода
        # разрывает связь перехватчика с перехватываемым методом.
        keyword = FUNC if orig_info["is_function"] else PROC
        indent = re.match(r"^[ 	]*", lines[ext_info["start"]]).group(0)
        head = lines[:ext_info["start"]] + [f"{indent}{keyword} {proc_name}({orig_info['params']})"]
        end_word = END_FUNC if orig_info["is_function"] else END_PROC
        tail = [f"{indent}{end_word}"] + lines[ext_info["end"] + 1:]
        write_bsl(ext_file, "\r\n".join(head + merged["lines"] + tail))

    if merged["conflicts"]:
        status = "partial"
    elif merged["kept"] == 0 and merged["transferred"] and same_signature:
        status = "transferred"
    else:
        status = "updated"
    return {
        "status": status,
        "kept": merged["kept"],
        "transferred": merged["transferred"],
        "conflicts": merged["conflicts"],
        "orphan": merged["orphan"],
    }


def controlled_methods(root):
    """Перехватчики ИзменениеИКонтроль во всех модулях расширения."""
    pattern = re.compile(
        re.escape(DECORATORS["ModificationAndControl"]) +
        r'\("([^"]+)"\)\s*\r?\n\s*(?:&[^\r\n]+\r?\n\s*)?(?:' + PROC + "|" + FUNC + r')\s+([^\s(]+)')
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".bsl"):
                continue
            path = os.path.join(dirpath, name)
            for m in pattern.finditer(read_bsl(path)):
                found.append({"file": path, "method": m.group(1), "proc": m.group(2)})
    return found


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Generate and resync method interceptors for 1C extension (CFE)",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True)
    parser.add_argument("-ModulePath", default="")
    parser.add_argument("-MethodName", default="")
    parser.add_argument("-InterceptorType", default="")
    parser.add_argument("-ConfigPath", default="")
    parser.add_argument("-Context", default="НаСервере")
    parser.add_argument("-IsFunction", action="store_true")
    parser.add_argument("-Check", action="store_true")
    parser.add_argument("-Actualize", action="store_true")
    args = parser.parse_args()
    context_given = "-Context" in sys.argv

    extension_path = args.ExtensionPath
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if os.path.isfile(extension_path):
        extension_path = os.path.dirname(extension_path)

    cfg_file = os.path.join(extension_path, "Configuration.xml")
    if not os.path.isfile(cfg_file):
        print(f"Configuration.xml not found in: {extension_path}", file=sys.stderr)
        sys.exit(1)

    config_root = ""
    if args.ConfigPath:
        config_root = args.ConfigPath
        if not os.path.isabs(config_root):
            config_root = os.path.join(os.getcwd(), config_root)

    ns = {"md": "http://v8.1c.ru/8.3/MDClasses"}
    root = ET.parse(cfg_file).getroot()
    name_prefix = "Расш_"
    props_node = root.find(".//md:Configuration/md:Properties", ns)
    if props_node is not None:
        prefix_node = props_node.find("md:NamePrefix", ns)
        if prefix_node is not None and prefix_node.text:
            name_prefix = prefix_node.text

    # --- Батч: -Check / -Actualize ---
    if args.Check or args.Actualize:
        if not config_root:
            print("Ошибка: для -Check и -Actualize нужен -ConfigPath", file=sys.stderr)
            sys.exit(1)
        items = controlled_methods(extension_path)
        total = len(items)
        drift = 0
        broken = 0
        fixed = 0
        details = []
        for item in items:
            rel = os.path.relpath(item["file"], extension_path)
            res = resync_interceptor(item["file"], os.path.join(config_root, rel),
                                     item["method"], item["proc"], args.Actualize)
            if res["status"] in ("actual", "no-interceptor"):
                continue
            if res["status"] == "no-original":
                # Метод или его модуль исчезли из основной конфигурации: перехватчик мертв,
                # и молчать об этом нельзя - ради такого случая проверка и нужна.
                broken += 1
                details.append(f"{item['method']} (оригинал не найден)")
                continue
            drift += 1
            if args.Actualize:
                fixed += 1
            details.append(f"{item['method']} ({res['status']})")

        if args.Actualize and broken == 0:
            print(f"[OK] Контролируемых методов: {total}, актуализировано: {fixed}")
            for d in details:
                print(f"     {d}")
            sys.exit(0)

        if drift == 0 and broken == 0:
            print(f"[OK] Контролируемые методы: {total}/{total} актуальны")
            sys.exit(0)
        if broken:
            print(f"Оригинал не найден: {broken} из {total}; дрейф: {drift}", file=sys.stderr)
        else:
            print(f"Дрейф оригинала: {drift} из {total}", file=sys.stderr)
        for d in details:
            print(f"     {d}", file=sys.stderr)
        sys.exit(1)

    # --- Одиночный режим ---
    for flag, value in (("ModulePath", args.ModulePath), ("MethodName", args.MethodName),
                        ("InterceptorType", args.InterceptorType)):
        if not value:
            print(f"Ошибка: параметр -{flag} обязателен (без -Check и -Actualize)", file=sys.stderr)
            sys.exit(1)
    if args.InterceptorType not in DECORATORS:
        print("Ошибка: -InterceptorType принимает %s, получено: %s"
              % (", ".join(DECORATORS), args.InterceptorType), file=sys.stderr)
        sys.exit(1)

    module_path = args.ModulePath
    method_name = args.MethodName
    interceptor_type = args.InterceptorType

    # ModulePath принимается и как имя объекта, и как путь к файлу модуля.
    is_form_module = False
    if "/" in module_path or "\\" in module_path or module_path.lower().endswith(".bsl"):
        norm = module_path.replace("\\", "/")
        segs = [s for s in norm.split("/") if s]
        if len(segs) < 2 or segs[0] not in DIR_TYPE_MAP:
            print(f"Unknown object type: {module_path}", file=sys.stderr)
            sys.exit(1)
        obj_type = DIR_TYPE_MAP[segs[0]]
        obj_name = segs[1]
        rel_path = norm
        is_form_module = "/Forms/" in norm
    else:
        parts = module_path.split(".")
        if len(parts) < 2:
            print(f"Invalid ModulePath format: {module_path}. Expected: Type.Name.Module or CommonModule.Name",
                  file=sys.stderr)
            sys.exit(1)
        obj_type, obj_name = parts[0], parts[1]
        if obj_type not in TYPE_DIR_MAP:
            print(f"Unknown object type: {obj_type}", file=sys.stderr)
            sys.exit(1)
        dir_name = TYPE_DIR_MAP[obj_type]
        if obj_type in ("CommonModule", "CommonModules"):
            rel_path = f"{dir_name}/{obj_name}/Ext/Module.bsl"
        elif len(parts) >= 4 and parts[2] == "Form":
            is_form_module = True
            rel_path = f"{dir_name}/{obj_name}/Forms/{parts[3]}/Ext/Form/Module.bsl"
        elif len(parts) >= 3:
            rel_path = f"{dir_name}/{obj_name}/Ext/" + MODULE_FILE_MAP.get(parts[2], parts[2] + ".bsl")
        else:
            print(f"Invalid ModulePath format: {module_path}. Expected: Type.Name.Module, "
                  f"Type.Name.Form.FormName, or CommonModule.Name", file=sys.stderr)
            sys.exit(1)

    bsl_file = os.path.join(extension_path, *rel_path.split("/"))
    orig_file = os.path.join(config_root, *rel_path.split("/")) if config_root else ""

    # --- Оригинал: сигнатура, тело, директива, препроцессор ---
    orig_params = ""
    orig_body = []
    orig_is_function = args.IsFunction
    orig_directive = ""
    orig_preproc = ""
    if orig_file:
        if not os.path.isfile(orig_file):
            print(f"Ошибка: модуль основной конфигурации не найден: {orig_file}", file=sys.stderr)
            sys.exit(1)
        info = find_method(read_bsl(orig_file), method_name)
        if info is None:
            print(f"Ошибка: метод {method_name} не найден в {orig_file}", file=sys.stderr)
            sys.exit(1)
        orig_is_function = info["is_function"]
        orig_params = info["params"]
        orig_body = info["body"]
        orig_directive = info["directive"]
        orig_preproc = info["preproc"]

    # Платформа не поддерживает Перед и После у функции: перехватчик обязан вернуть значение,
    # а эти виды его не возвращают. Для функции применимы Вместо и ИзменениеИКонтроль.
    if orig_is_function and interceptor_type in ("Before", "After"):
        print("Ошибка: функция перехватывается только видами Instead и ModificationAndControl, а не " + interceptor_type,
              file=sys.stderr)
        sys.exit(1)

    decorator = DECORATORS[interceptor_type]
    proc_name = f"{name_prefix}{method_name}"

    # --- Ресинк, если перехватчик уже стоит ---
    if os.path.isfile(bsl_file) and interceptor_type == "ModificationAndControl":
        if f'{decorator}("{method_name}")' in read_bsl(bsl_file):
            res = resync_interceptor(bsl_file, orig_file, method_name, proc_name, True)
            fqn = f"{obj_type}.{obj_name}.{method_name}"
            status = res["status"]
            if status == "actual":
                print(f"[АКТУАЛЕН] {fqn} - оригинал не менялся")
                sys.exit(0)
            if status == "transferred":
                print(f"[ПЕРЕНЕСЕНО В ОСНОВНУЮ] {fqn}")
                print(f"     перенесено в основную конфигурацию: {res['transferred']}")
                for c in res["orphan"]:
                    print(f"     [!] комментарий не перенесен: {c}")
                sys.exit(0)
            if status == "partial":
                print(f"[АКТУАЛИЗИРОВАН-ЧАСТИЧНО] {fqn}")
                print(f"     правок сохранено: {res['kept']}")
                print(f"     перенесено в основную конфигурацию: {res['transferred']}")
                print(f"     конфликтов: {res['conflicts']}")
                sys.exit(0)
            if status == "updated":
                print(f"[АКТУАЛИЗИРОВАН] {fqn}")
                print(f"     правок сохранено: {res['kept']}")
                print(f"     перенесено в основную конфигурацию: {res['transferred']}")
                for c in res["orphan"]:
                    print(f"     [!] комментарий не перенесен: {c}")
                sys.exit(0)
            print("Ошибка: оригинал метода %s не найден в основной конфигурации" % method_name,
                  file=sys.stderr)
            sys.exit(1)

    # --- Директива компиляции ---
    # У модуля формы она берется из оригинала: обработчик, объявленный на клиенте, на сервере
    # не свяжется. У прочих модулей директива не пишется вовсе.
    context = args.Context
    if is_form_module and not orig_directive and not context_given:
        # Обработчики формы по умолчанию клиентские: серверная директива оборвала бы вызов.
        context = "НаКлиенте"
    if is_form_module and orig_directive:
        context_annotation = orig_directive
    else:
        context_annotation = context if context.startswith("&") else "&" + context

    # --- Тело перехватчика ---
    keyword = FUNC if orig_is_function else PROC
    end_keyword = END_FUNC if orig_is_function else END_PROC

    body_lines = []
    if interceptor_type == "Before":
        body_lines.append("\t// TODO: код перед вызовом оригинального метода")
    elif interceptor_type == "After":
        body_lines.append("\t// TODO: код после вызова оригинального метода")
    elif interceptor_type == "Instead":
        # Оригинал вызывается явно: платформа передает его через ПродолжитьВызов.
        call_args = ""
        if orig_params:
            names = []
            for p in orig_params.split(","):
                name = p.split("=")[0].strip()
                name = re.sub(r"^Знач\s+", "", name)
                names.append(name)
            call_args = ", ".join(names)
        cont = "ПродолжитьВызов"  # ПродолжитьВызов
        if orig_is_function:
            body_lines.append(f"\tРезультат = {cont}({call_args});")
            body_lines.append("\t// TODO: доработать поведение")
            body_lines.append("\tВозврат Результат;")
        else:
            body_lines.append(f"\t{cont}({call_args});")
            body_lines.append("\t// TODO: доработать поведение")
    else:
        if orig_body:
            body_lines.extend(orig_body)
        else:
            body_lines.append("\t// Скопируйте тело оригинального метода и внесите правки,")
            body_lines.append(f"\t// используя маркеры {MARK_INS_START} / {MARK_DEL_START}")

    bsl_code = []
    if is_form_module:
        bsl_code.append(context_annotation)
    bsl_code.append(f'{decorator}("{method_name}")')
    bsl_code.append(f"{keyword} {proc_name}({orig_params})")
    bsl_code.extend(body_lines)
    bsl_code.append(end_keyword)

    # Область зависит от вида модуля - так же, как ее заводит Конфигуратор.
    if is_form_module:
        region_name = "ОбработчикиСобытийФормы"
    elif obj_type == "CommonModule":
        region_name = "ПрограммныйИнтерфейс"
    else:
        region_name = "ОбработчикиСобытий"

    # --- Предупреждение о незаимствованной форме ---
    if is_form_module:
        segs = rel_path.replace("\\", "/").split("/")
        if "Forms" in segs:
            idx = segs.index("Forms")
            if len(segs) > idx + 1:
                form_name = segs[idx + 1]
                forms_root = os.path.join(extension_path, TYPE_DIR_MAP[obj_type], obj_name, "Forms")
                form_meta = os.path.join(forms_root, form_name + ".xml")
                form_xml = os.path.join(forms_root, form_name, "Ext", "Form.xml")
                if not os.path.isfile(form_meta) or not os.path.isfile(form_xml):
                    print(f"[WARN] Form '{form_name}' metadata or Form.xml not found in extension.")
                    print("       Run /cfe-borrow first:")
                    print(f'       /cfe-borrow -ExtensionPath {extension_path} -ConfigPath <ConfigPath> '
                          f'-Object "{obj_type}.{obj_name}.Form.{form_name}"')
                    print("")

    # --- Размещение в модуле расширения ---
    os.makedirs(os.path.dirname(bsl_file), exist_ok=True)

    has_content = os.path.isfile(bsl_file) and read_bsl(bsl_file).strip() != ""
    if has_content:
        lines = split_lines(read_bsl(bsl_file))
        # Хвостовой перевод строки дает пустой элемент - он мешает искать конец региона.
        while lines and not lines[-1].strip():
            lines.pop()

        # Условие препроцессора вокруг оригинала должно охватывать и перехватчик. Если файл
        # такого условия не содержит, метод оборачивается отдельно.
        if orig_preproc and not any(l.strip() == f"{IF_START} {orig_preproc} {THEN}" for l in lines):
            bsl_code = [f"{IF_START} {orig_preproc} {THEN}", ""] + bsl_code + ["", END_IF]

        region_idx = -1
        for i, line in enumerate(lines):
            if line.strip() == f"{REGION} {region_name}":
                region_idx = i
                break

        if region_idx >= 0:
            end_idx = -1
            for i in range(region_idx + 1, len(lines)):
                if lines[i].strip() == END_REGION:
                    end_idx = i
                    break
            if end_idx < 0:
                end_idx = len(lines)
            while end_idx > region_idx + 1 and not lines[end_idx - 1].strip():
                end_idx -= 1
            lines[end_idx:end_idx] = [""] + bsl_code
            placement = "в существующий регион " + region_name
        else:
            block = ["", f"{REGION} {region_name}", ""] + bsl_code + ["", END_REGION]
            close_idx = -1
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == END_IF:
                    close_idx = i
                    break
            if close_idx >= 0:
                lines[close_idx:close_idx] = block
            else:
                lines.extend(block)
            placement = "в новый регион " + region_name
        write_bsl(bsl_file, "\r\n".join(lines) + "\r\n")
        print(f"[OK] Добавлен перехватчик {placement}")
    else:
        wrapped = []
        if orig_preproc:
            wrapped.append(f"{IF_START} {orig_preproc} {THEN}")
            wrapped.append("")
        wrapped.append(f"{REGION} {region_name}")
        wrapped.append("")
        wrapped.extend(bsl_code)
        wrapped.append("")
        wrapped.append(END_REGION)
        if orig_preproc:
            wrapped.append("")
            wrapped.append(END_IF)
        write_bsl(bsl_file, "\r\n".join(wrapped) + "\r\n")
        print("[OK] Создан файл модуля")

    print(f"     Файл:         {bsl_file}")
    print(f'     Декоратор:    {decorator}("{method_name}")')
    print(f"     Процедура:    {proc_name}()")
    if orig_preproc:
        print(f"     Препроцессор: {IF_START}:{orig_preproc}")
    print(f"     Контекст:   {context_annotation}")


if __name__ == "__main__":
    main()
