#!/usr/bin/env python3
# db-run v1.0 - Launch 1C:Enterprise
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import glob
import os
import subprocess
import sys


def resolve_v8path(v8path):
    """Resolve path to 1cv8.exe."""
    if not v8path:
        found = sorted(glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe"))
        if found:
            return found[-1]
        else:
            print("Error: 1cv8.exe not found. Specify -V8Path", file=sys.stderr)
            sys.exit(1)
    elif os.path.isdir(v8path):
        v8path = os.path.join(v8path, "1cv8.exe")

    if not os.path.isfile(v8path):
        print(f"Error: 1cv8.exe not found at {v8path}", file=sys.stderr)
        sys.exit(1)
    return v8path


# --- Дополнительные аргументы платформы (общий блок, версия 1) ---
# Список разделяется запятой, а не пробелом: аргумент платформы несет пробел внутри значения
# (/C "имя значение", путь с пробелом), и разбор по пробелу разорвал бы такой аргумент.
def split_platform_arguments(raw):
    if not raw or not raw.strip():
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def find_v8_project_file(start_dir):
    """Файл настроек проекта вверх по дереву от целевого каталога.

    Существование каталога не требуется: подъем идет по строке пути, а целевого каталога
    на момент создания базы еще нет.
    """
    d = os.path.abspath(start_dir)
    for _ in range(20):
        candidate = os.path.join(d, ".v8-project.json")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def project_platform_arguments(start_dir, key):
    # Импорт внутри функции: блок переносится в скилы с разным набором импортов, и
    # обращение к неимпортированному имени попадало бы в except ниже - отказ стал бы тихим.
    import json as _pa_json
    try:
        path = find_v8_project_file(start_dir)
        if not path:
            return []
        with open(path, "r", encoding="utf-8-sig") as f:
            settings = _pa_json.load(f)
        value = settings.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return split_platform_arguments(value)
        return [str(v) for v in value if str(v)]
    except Exception:
        # Непрочитанные настройки не повод отменять запуск: дополнительные аргументы
        # необязательны, а сам файл проверяет и сообщает о поломке отдельный линтер.
        return []


def resolve_platform_arguments(explicit, start_dir, key):
    """Аргументы вызова заменяют значение из настроек проекта целиком, а не дополняют его:
    при сложении снять заданный в проекте аргумент было бы нечем.

    None означает, что параметр не задавали, - тогда действуют настройки проекта. Пустая
    строка означает заданное пустое значение и снимает аргументы проекта на этот запуск.
    """
    if explicit is not None:
        return split_platform_arguments(explicit)
    return project_platform_arguments(start_dir, key)


def merge_dash_values(argv, keys):
    """Склеить "-Ключ значение" в "-Ключ=значение" для перечисленных ключей.

    Разбор командной строки принимает значение, начинающееся с дефиса, за новый ключ: строка
    "--verbose,--token=x" без склейки обрывает разбор подсказкой по использованию.
    """
    out = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in keys and i + 1 < len(argv):
            out.append(token + "=" + argv[i + 1])
            i += 2
            continue
        out.append(token)
        i += 1
    return out
# --- Конец общего блока дополнительных аргументов ---


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Launch 1C:Enterprise",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UserName", default="")
    parser.add_argument("-Password", default="")
    parser.add_argument("-Execute", default="")
    parser.add_argument("-CParam", default="")
    parser.add_argument("-URL", default="")
    parser.add_argument("-AdditionalV8Arguments", default=None)
    parser.add_argument("-StartupCheckSeconds", type=int, default=3)
    args = parser.parse_args(merge_dash_values(sys.argv[1:], ("-AdditionalV8Arguments",)))

    v8path = resolve_v8path(args.V8Path)

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Build arguments ---
    arguments = ["ENTERPRISE"]

    if args.InfoBaseServer and args.InfoBaseRef:
        arguments.extend(["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"])
    else:
        arguments.extend(["/F", args.InfoBasePath])

    if args.UserName:
        arguments.append(f"/N{args.UserName}")
    if args.Password:
        arguments.append(f"/P{args.Password}")

    # --- Optional params ---
    execute = args.Execute
    if execute:
        ext = os.path.splitext(execute)[1].lower()
        if ext == ".erf":
            print("[WARN] /Execute does not support ERF files (external reports).")
            print(f"       Open the report via File -> Open: {execute}")
            print("       Launching database without /Execute.")
            execute = ""

    if execute:
        arguments.extend(["/Execute", execute])
    if args.CParam:
        arguments.extend(["/C", args.CParam])
    if args.URL:
        arguments.extend(["/URL", args.URL])

    arguments.append("/DisableStartupDialogs")
    settings_dir = args.InfoBasePath or os.getcwd()
    arguments.extend(resolve_platform_arguments(
        args.AdditionalV8Arguments, settings_dir, "v8args"))

    # --- Execute (background, no wait) ---
    print(f"Running: 1cv8.exe {' '.join(arguments)}")
    process = subprocess.Popen([v8path] + arguments)

    # Контрольное окно: платформа с отвергнутыми параметрами завершается почти сразу, и
    # сообщение о запуске было бы ложным. Живой процесс за это время не завершается.
    try:
        code = process.wait(timeout=args.StartupCheckSeconds)
    except subprocess.TimeoutExpired:
        code = None
    if code is not None and code != 0:
        print(f"Error: платформа завершилась сразу после запуска, код возврата {code}")
        sys.exit(1)

    print("1C:Enterprise launched")


if __name__ == "__main__":
    main()
