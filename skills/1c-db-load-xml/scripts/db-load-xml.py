#!/usr/bin/env python3
# db-load-xml v1.3 - Load 1C configuration from XML files
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile


def resolve_v8path(v8path):
    """Resolve path to 1cv8.exe."""
    if not v8path:
        candidates = glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe")
        if candidates:
            candidates.sort()
            return candidates[-1]
        else:
            print("Error: 1cv8.exe not found. Specify -V8Path", file=sys.stderr)
            sys.exit(1)
    elif os.path.isdir(v8path):
        v8path = os.path.join(v8path, "1cv8.exe")

    if not os.path.isfile(v8path):
        print(f"Error: 1cv8.exe not found at {v8path}", file=sys.stderr)
        sys.exit(1)

    return v8path


# --- Вердикт платформы (общий блок, версия 1) ---
# Платформа сообщает результат тремя независимыми каналами, и ни один не самодостаточен:
# нулевой код возврата при проваленной операции - ее штатное поведение. Четвертый сигнал -
# постусловие: артефакт операции действительно появился и он от этого запуска.

# Фразы, которыми платформа сообщает об ОТСУТСТВИИ проблем. Сверяются раньше диагностики
# и целиком: строка "операция завершена с ошибками" не должна попасть под "операция завершена".
PLATFORM_CLEAN_PHRASES = (
    "ошибок не обнаружено",
    "ошибки не обнаружены",
    "предупреждений не обнаружено",
    "ошибок: 0",
    "предупреждений: 0",
    "errors were not found",
    "0 errors",
)

# Сообщения, при которых операция провалена, даже если код возврата нулевой.
PLATFORM_FATAL_PHRASES = (
    "неверное свойство объекта метаданных",
    "не входит в состав объекта метаданных",
    "неизвестное имя типа",
    "неизвестный объект метаданных",
    "ни один из документов не является регистратором для регистра",
    "неверное значение перечисления",
    "не может быть приведен к типу",
    "необходима версия платформы не меньше",
    "не найден метод",
    "не может быть применен",
)


def hide_platform_secret(text):
    """Замаскировать секреты в строке, уходящей в вывод."""
    if not text:
        return text
    # Ключи с секретом: пароль базы, код разблокировки, пароль хранилища конфигурации.
    # Длинные имена стоят первыми, иначе короткое подойдет как префикс длинного.
    keys = r'(?:^|(?<=\s))(/ConfigurationRepositoryP|/UC|/P)'
    masked = re.sub(keys + r'"[^"]*"', r'\g<1>"***"', text)
    masked = re.sub(keys + r'([^\s"]\S*)', r'\g<1>***', masked)
    # Утилита администрирования принимает секрет длинным ключом со знаком равенства:
    # --token=, --password=, --db-pwd=. Правило для ключей платформы их не покрывает.
    long_keys = r'(?:^|(?<=\s))(--(?:token|password|db-pwd|pwd)=)'
    masked = re.sub(long_keys + r'"[^"]*"', r'\g<1>"***"', masked)
    masked = re.sub(long_keys + r'([^\s"]\S*)', r'\g<1>***', masked)
    return masked


def platform_log_problems(log_text):
    """Строки лога, означающие провал операции при любом коде возврата."""
    problems = []
    if not log_text:
        return problems
    for line in log_text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        lower = trimmed.lower()
        if any(phrase in lower for phrase in PLATFORM_CLEAN_PHRASES):
            continue
        if any(phrase in lower for phrase in PLATFORM_FATAL_PHRASES):
            problems.append(trimmed)
    return problems


def platform_result_code(result_file):
    """Числовой результат платформы или None, если сигнал недоступен."""
    if not result_file or not os.path.isfile(result_file):
        return None
    try:
        with open(result_file, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def write_platform_verdict(exit_code, result_file, log_text, success_message,
                           failure_message, artifact_path=None, strict=False):
    """Свести четыре сигнала в один код возврата и напечатать вердикт."""
    final_code = exit_code
    result_code = platform_result_code(result_file)
    if result_code is not None and result_code != 0 and final_code == 0:
        print(f"[error] platform result code: {result_code}", file=sys.stderr)
        final_code = 1

    if final_code == 0:
        print(success_message)
    else:
        print(f"{failure_message} (code: {final_code})", file=sys.stderr)

    if log_text:
        print("--- Log ---")
        print(log_text)
        print("--- End ---")

    problems = platform_log_problems(log_text)
    if problems:
        print(f"[warning] platform reported success, but the log contains {len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        if strict and final_code == 0:
            final_code = 1

    if artifact_path and final_code == 0 and not os.path.exists(artifact_path):
        print(f"[error] platform reported success, but the expected result is missing: {artifact_path}",
              file=sys.stderr)
        final_code = 1

    return final_code
# --- Конец общего блока вердикта платформы ---

# --- Защита боевой базы (общий блок, версия 2) ---
# База, помеченная в .v8-project.json как боевая (role: prod), отказывает изменяющей
# операции, пока не передан --allow-prod. Отказ стоит одной команды, а неудачная загрузка в
# боевую базу необратима. Проверка идет до запуска платформы; когда файла настроек нет,
# записи базы нет или роль отличается от prod - поведение прежнее.
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


def info_base_server_key(value):
    """Ключ сравнения адреса сервера.

    Порт кластера по умолчанию 1541 отбрасывается: srv01 и srv01:1541 - одна база.
    Другой порт остается в ключе и отличает базу.
    """
    text = str(value or "").strip().lower()
    suffix = ":1541"
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    return text


def info_base_record_kind(db):
    """Вид записи реестра.

    Поле type учитывается, когда оно задано (server или file). Иначе серверная запись -
    это пара server и ref, файловая - путь.
    """
    declared = str(db.get("type") or "").strip().lower()
    if declared in ("server", "file"):
        return declared
    if str(db.get("server") or "").strip() and str(db.get("ref") or "").strip():
        return "server"
    if str(db.get("path") or "").strip():
        return "file"
    return ""


def info_base_path_key(value, base_dir):
    """Ключ сравнения путей баз.

    Приводит путь к виду, в котором два написания одной базы совпадают: окончательный
    каталог (os.path.realpath: junction и символическая ссылка), прямые слеши, нижний
    регистр, без завершающего разделителя. Относительный путь достраивается от base_dir.
    Подключенный диск и UNC-путь к тому же каталогу не сводятся.
    """
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if not os.path.isabs(text) and base_dir:
        text = os.path.join(base_dir, text)
    try:
        text = os.path.realpath(text)
    except (OSError, ValueError):
        text = os.path.abspath(text)
    text = text.replace("\\", "/").rstrip("/")
    if not text:
        text = "/"
    return text.lower()


def info_base_role(info_base_path, info_base_server, info_base_ref):
    """Роль целевой базы по настройкам проекта.

    Находит ближайший .v8-project.json и в нем запись того же вида, что и цель. Сервер и имя
    вместе - цель серверная, путь в этом запуске не сравнивается. Сервер сравнивается без
    порта 1541. Файловый путь - по окончательному каталогу. Поле type записи учитывается,
    когда оно задано. Сравнение без учета регистра. Читает только имя и роль, остальные
    поля файла не печатает.
    """
    # Импорт внутри функции: блок переносится в скилы с разным набором импортов, и обращение
    # к неимпортированному имени попадало бы в except ниже - отказ стал бы тихим.
    import json as _pg_json
    state = {"name": "", "role": "", "config_path": ""}
    start_dir = os.getcwd()
    config_path = find_v8_project_file(start_dir)
    if not config_path:
        return state
    state["config_path"] = config_path
    try:
        with open(config_path, "r", encoding="utf-8-sig") as handle:
            project = _pg_json.load(handle)
    except Exception as exc:
        # Файл есть, но не разбирается: роль неизвестна. Молчать нельзя - иначе защита не
        # работает, а причина не видна.
        print(f"[warning] project settings not parsed: {config_path} ({exc})", file=sys.stderr)
        state["config_path"] = ""
        return state
    databases = project.get("databases") if isinstance(project, dict) else None
    if not isinstance(databases, list):
        return state

    config_dir = os.path.dirname(config_path)
    server_key = info_base_server_key(info_base_server)
    ref = (info_base_ref or "").strip().lower()
    target = info_base_path_key(info_base_path, start_dir)
    # Заданы сервер и имя - цель серверная, даже если рядом передан путь. Как у платформы.
    server_target = bool(server_key and ref)

    for db in databases:
        if not isinstance(db, dict):
            continue
        kind = info_base_record_kind(db)
        if server_target:
            matched = (
                kind == "server"
                and info_base_server_key(db.get("server")) == server_key
                and str(db.get("ref") or "").strip().lower() == ref
            )
        elif target and kind == "file":
            matched = info_base_path_key(db.get("path"), config_dir) == target
        else:
            matched = False
        if not matched:
            continue
        state["name"] = str(db.get("name") or db.get("id") or "")
        state["role"] = str(db.get("role") or "").strip().lower()
        if state["role"] == "prod":
            return state
    return state


def assert_info_base_mutable(info_base_path, info_base_server, info_base_ref, allow_prod):
    """Отказ изменяющей операции на базе, помеченной боевой.

    Ничего не делает, когда передан allow_prod, когда записи базы нет и когда роль не prod.
    При отказе печатает причину в stderr и завершает процесс кодом 1.
    """
    if allow_prod:
        return
    state = info_base_role(info_base_path, info_base_server, info_base_ref)
    if state["role"] != "prod":
        return
    name = state["name"] or "<без имени>"
    print(f"База '{name}' помечена как боевая (role: prod) в {state['config_path']}.\n"
          "Изменяющая операция отменена. Запуск с --allow-prod - только по явной команде пользователя.",
          file=sys.stderr)
    sys.exit(1)
# --- Конец общего блока защиты боевой базы ---

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Load 1C configuration from XML files",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="", help="Path to 1cv8.exe or its bin directory")
    parser.add_argument("-InfoBasePath", default="", help="Path to file infobase")
    parser.add_argument("-InfoBaseServer", default="", help="1C server (for server infobase)")
    parser.add_argument("-InfoBaseRef", default="", help="Infobase name on server")
    parser.add_argument("-AllowProd", "--allow-prod", dest="AllowProd", action="store_true",
                        help="Allow a modifying operation against an infobase marked role: prod")
    parser.add_argument("-UserName", default="", help="1C user name")
    parser.add_argument("-Password", default="", help="1C user password")
    parser.add_argument("-ConfigDir", required=True, help="Directory with XML configuration sources")
    parser.add_argument(
        "-Mode",
        default="Full",
        choices=["Full", "Partial"],
        help="Load mode (default: Full)",
    )
    parser.add_argument("-Files", default="", help="Comma-separated relative file paths (for Partial mode)")
    parser.add_argument("-ListFile", default="", help="Path to file list (alternative to -Files, for Partial mode)")
    parser.add_argument("-Extension", default="", help="Extension name to load")
    parser.add_argument("-AllExtensions", action="store_true", help="Load all extensions")
    parser.add_argument(
        "-Format",
        default="Hierarchical",
        choices=["Hierarchical", "Plain"],
        help="File format (default: Hierarchical)",
    )
    parser.add_argument("-UpdateDB", action="store_true", help="Also update database configuration after load")
    parser.add_argument(
        "-StrictLog",
        action="store_true",
        help="Treat silent rejection warnings in the log as errors (elevate exit code to 1)",
    )
    args = parser.parse_args()

    # --- Боевая база ---
    assert_info_base_mutable(args.InfoBasePath, args.InfoBaseServer, args.InfoBaseRef, args.AllowProd)

    # --- Resolve V8Path ---
    v8path = resolve_v8path(args.V8Path)

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Validate config dir ---
    if not os.path.exists(args.ConfigDir):
        print(f"Error: config directory not found: {args.ConfigDir}", file=sys.stderr)
        sys.exit(1)

    # --- Validate Partial mode ---
    if args.Mode == "Partial" and not args.Files and not args.ListFile:
        print("Error: -Files or -ListFile required for Partial mode", file=sys.stderr)
        sys.exit(1)

    # --- Temp dir ---
    temp_dir = os.path.join(tempfile.gettempdir(), f"db_load_xml_{random.randint(0, 999999)}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # --- Build arguments ---
        arguments = ["DESIGNER"]

        if args.InfoBaseServer and args.InfoBaseRef:
            arguments += ["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"]
        else:
            arguments += ["/F", args.InfoBasePath]

        if args.UserName:
            arguments.append(f"/N{args.UserName}")
        if args.Password:
            arguments.append(f"/P{args.Password}")

        arguments += ["/LoadConfigFromFiles", args.ConfigDir]

        if args.Mode == "Full":
            print("Executing full configuration load...")
        else:
            print("Executing partial configuration load...")

            # Build list file
            generated_list_file = None
            if args.ListFile:
                # Use provided list file
                if not os.path.isfile(args.ListFile):
                    print(f"Error: list file not found: {args.ListFile}", file=sys.stderr)
                    sys.exit(1)
                generated_list_file = args.ListFile
            else:
                # Generate from -Files parameter
                file_list = [f.strip() for f in args.Files.split(",") if f.strip()]
                generated_list_file = os.path.join(temp_dir, "load_list.txt")
                with open(generated_list_file, "w", encoding="utf-8-sig") as f:
                    f.write("\n".join(file_list))

                print(f"Files to load: {len(file_list)}")
                for fl in file_list:
                    print(f"  {fl}")

            arguments += ["-listFile", generated_list_file]
            arguments.append("-partial")
            arguments.append("-updateConfigDumpInfo")

        arguments += ["-Format", args.Format]

        # --- Extensions ---
        if args.Extension:
            arguments += ["-Extension", args.Extension]
        elif args.AllExtensions:
            arguments.append("-AllExtensions")

        # --- UpdateDB ---
        if args.UpdateDB:
            arguments.append("/UpdateDBCfg")

        # --- Output ---
        # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
        # достаться от прошлого прогона.
        out_file = os.path.join(temp_dir, "load_log.txt")
        result_file = os.path.join(temp_dir, "load_result.txt")
        arguments.extend(["/Out", out_file])
        arguments.extend(["/DumpResult", result_file])
        arguments.append("/DisableStartupDialogs")

        # --- Execute ---
        print(f"Running: 1cv8.exe {hide_platform_secret(' '.join(arguments))}")
        result = subprocess.run([v8path] + arguments, capture_output=True, text=True)
        exit_code = result.returncode

        # --- Result ---
        log_content = None
        if os.path.isfile(out_file):
            try:
                with open(out_file, "r", encoding="utf-8-sig") as f:
                    log_content = f.read()
            except Exception:
                log_content = None

        exit_code = write_platform_verdict(
            exit_code,
            result_file,
            log_content,
            "Load completed successfully",
            "Error loading configuration",
            strict=args.StrictLog,
        )

        sys.exit(exit_code)

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
