#!/usr/bin/env python3
# db-cfe-admin v1.0 - Manage configuration extensions in a 1C infobase via ibcmd
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile


# --- Вывод платформы (общий блок, версия 1) ---
# Платформа пишет диагностику в кодировке консоли (866 на русской Windows), утилита
# администрирования и часть сборок - в UTF-8. Байты читаются один раз и декодируются по
# факту: перепутанная кодировка превращает сообщение об ошибке в нечитаемое.
def read_platform_text(path):
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    if not data:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    try:
        # Строгое декодирование бросает исключение на байтах, недопустимых в UTF-8, - это и
        # есть признак однобайтовой кодировки. Нестрогое подставило бы символ замены молча.
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp866", "replace")


def show_platform_output(paths):
    """Вывод показывается и при успешном завершении: платформа сообщает предупреждения, не
    меняя код возврата, и потерянное предупреждение обходится дороже лишних строк в протоколе.
    """
    chunks = []
    for path in paths:
        text = read_platform_text(path).strip()
        if text:
            chunks.append(text)
    if not chunks:
        return
    print("--- Вывод платформы ---")
    for chunk in chunks:
        print(chunk)
# --- Конец общего блока вывода платформы ---

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

YES_NO = ("yes", "no")
SCOPES = ("infobase", "data-separation")
DBMS_KINDS = ("MSSQLServer", "PostgreSQL", "IBMDB2", "OracleDatabase")
PROPERTY_FLAGS = (
    ("Active", "--active"),
    ("SafeMode", "--safe-mode"),
    ("UnsafeActionProtection", "--unsafe-action-protection"),
    ("UsedInDistributedInfobase", "--used-in-distributed-infobase"),
)


def fail(message):
    """Сообщение об ошибке параметров и завершение кодом 1.

    Параметры: message - текст без префикса Error.
    Возвращает: управление не возвращается.
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def resolve_ibcmd_path(v8path):
    """Путь к ibcmd.

    Пустой аргумент - поиск ibcmd.exe в каталогах bin установленных платформ.
    Каталог - ibcmd.exe внутри него. Файл 1cv8.exe - ibcmd.exe в том же каталоге.
    Иной существующий файл используется как есть.

    Параметры: v8path - значение -V8Path.
    Возвращает: путь к исполняемому файлу; при отсутствии завершает процесс кодом 1.
    """
    if not v8path:
        found = sorted(glob.glob(r"C:\Program Files\1cv8\*\bin\ibcmd.exe"))
        if not found:
            fail("ibcmd.exe not found. Specify -V8Path")
        return found[-1]
    if os.path.isdir(v8path):
        candidate = os.path.join(v8path, "ibcmd.exe")
    else:
        base = os.path.basename(v8path).lower()
        if base in ("1cv8.exe", "1cv8"):
            candidate = os.path.join(os.path.dirname(os.path.abspath(v8path)), "ibcmd.exe")
        else:
            candidate = v8path
    if not os.path.isfile(candidate):
        fail(f"ibcmd.exe not found at {candidate}")
    return candidate


def ibcmd_yes_no(label, value):
    """Флаг свойства в виде yes или no.

    Пустая строка означает, что свойство не задавали.

    Параметры: label - имя параметра скрипта; value - сырое значение.
    Возвращает: yes, no или пустую строку. Недопустимое значение завершает процесс кодом 1.
    """
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).strip().lower()
    if text not in YES_NO:
        fail(f"{label} accepts yes or no, got: {value}")
    return text


def ibcmd_scope(value):
    """Область действия расширения: infobase или data-separation.

    Параметры: value - сырое значение -Scope.
    Возвращает: каноническое значение или пустую строку. Иное завершает процесс кодом 1.
    """
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).strip().lower()
    if text not in SCOPES:
        fail(f"-Scope accepts infobase or data-separation, got: {value}")
    return text


def ibcmd_dbms(value):
    """Тип СУБД в написании справки ibcmd.

    Параметры: value - сырое значение -Dbms.
    Возвращает: MSSQLServer, PostgreSQL, IBMDB2, OracleDatabase или пустую строку.
    """
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).strip()
    for kind in DBMS_KINDS:
        if text.lower() == kind.lower():
            return kind
    fail(f"-Dbms accepts {', '.join(DBMS_KINDS)}, got: {value}")
    return ""


def build_ibcmd_arguments(operation, name, all_extensions, properties, scope,
                          info_base_path, info_base_server, info_base_ref, dbms,
                          data_path, user_name, password):
    """Аргументы ibcmd без пути к exe.

    Порядок фиксирован: оба порта печатают одну и ту же строку.
    Заданные сервер и имя - цель серверная, путь в команду не попадает.

    Параметры: операция, имя расширения, признак удаления всех, словарь свойств
    yes/no и имя профиля, область действия, подключение, каталог данных, пользователь.
    Возвращает: список аргументов.
    """
    if operation == "check":
        command = ["infobase", "config", "check", "--extension=" + name]
    elif operation == "list":
        command = ["infobase", "config", "extension", "list"]
    elif operation == "set-properties":
        command = ["infobase", "config", "extension", "update", "--name=" + name]
        for key in (
            "--active",
            "--safe-mode",
            "--security-profile-name",
            "--unsafe-action-protection",
            "--used-in-distributed-infobase",
        ):
            if properties.get(key):
                command.append(key + "=" + properties[key])
        if scope:
            command.append("--scope=" + scope)
    elif operation == "delete":
        command = ["infobase", "config", "extension", "delete"]
        if all_extensions:
            command.append("--all")
        else:
            command.append("--name=" + name)
    else:
        fail(f"unknown operation: {operation}")

    server_target = bool((info_base_server or "").strip() and (info_base_ref or "").strip())
    if server_target:
        command.append("--db-server=" + info_base_server)
        command.append("--db-name=" + info_base_ref)
        if dbms:
            command.append("--dbms=" + dbms)
    else:
        command.append("--db-path=" + info_base_path)
    if data_path:
        command.append("--data=" + data_path)
    if user_name:
        command.append("--user=" + user_name)
    if password:
        command.append("--password=" + password)
    return command


def format_ibcmd_command(arguments):
    """Строка команды ibcmd для печати.

    Значение с пробелом берется в кавычки. Пароль заменяется на ***.

    Параметры: arguments - список аргументов без exe.
    Возвращает: строку, начинающуюся с ibcmd.
    """
    shown = []
    for arg in arguments:
        if arg.startswith("--password=") or arg.startswith("--db-pwd="):
            shown.append(arg.split("=", 1)[0] + "=***")
            continue
        if re.search(r"\s", arg) and "=" in arg:
            key, value = arg.split("=", 1)
            shown.append(f'{key}="{value}"')
            continue
        shown.append(arg)
    return "ibcmd " + " ".join(shown)


def execute_ibcmd(exe, arguments):
    """Запуск ibcmd и показ его вывода.

    Параметры: exe - путь к ibcmd; arguments - аргументы без exe.
    Возвращает: пару (код возврата, был ли непустой вывод). Код 1, если кода процесса нет.
    """
    temp_dir = tempfile.mkdtemp(prefix="db_cfe_admin_")
    stdout_file = os.path.join(temp_dir, "stdout.txt")
    stderr_file = os.path.join(temp_dir, "stderr.txt")
    try:
        with open(stdout_file, "wb") as out_handle, open(stderr_file, "wb") as err_handle:
            result = subprocess.run([exe] + arguments, stdout=out_handle, stderr=err_handle)
        texts = [read_platform_text(path).strip() for path in (stdout_file, stderr_file)]
        show_platform_output([stdout_file, stderr_file])
        code = 1 if result.returncode is None else result.returncode
        return code, any(texts)
    finally:
        try:
            for name in (stdout_file, stderr_file):
                if os.path.isfile(name):
                    os.remove(name)
            os.rmdir(temp_dir)
        except OSError:
            pass


def main():
    """Разбор параметров, защита боевой базы, печать команды или запуск ibcmd."""
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Manage 1C configuration extensions in an infobase via ibcmd",
        allow_abbrev=False,
    )

    def parser_exit(status=0, message=None):
        if message:
            sys.stderr.write(message)
        raise SystemExit(0 if status == 0 else 1)

    parser.exit = parser_exit
    parser.add_argument("Operation", choices=("list", "check", "set-properties", "delete"))
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UserName", default="")
    parser.add_argument("-Password", default="")
    parser.add_argument("-DataPath", default="")
    parser.add_argument("-Dbms", default="")
    parser.add_argument("-AllowProd", "--allow-prod", dest="AllowProd", action="store_true")
    parser.add_argument("-WhatIf", "--dry-run", dest="WhatIf", action="store_true")
    parser.add_argument("-Name", default="")
    parser.add_argument("-All", action="store_true")
    parser.add_argument("-Active", default="")
    parser.add_argument("-SafeMode", default="")
    parser.add_argument("-SecurityProfileName", default="")
    parser.add_argument("-UnsafeActionProtection", default="")
    parser.add_argument("-UsedInDistributedInfobase", default="")
    parser.add_argument("-Scope", default="")
    args = parser.parse_args()

    server_target = bool(args.InfoBaseServer.strip() and args.InfoBaseRef.strip())
    if not server_target and not args.InfoBasePath.strip():
        fail("specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef")
    dbms = ibcmd_dbms(args.Dbms)
    if dbms and not server_target:
        fail("-Dbms requires -InfoBaseServer and -InfoBaseRef")

    name = args.Name.strip()
    if args.All and args.Operation != "delete":
        fail("-All is valid only for delete")
    if args.Operation == "list" and (name or args.All):
        fail("list does not take -Name or -All")
    if args.Operation == "check" and not name:
        fail("check requires -Name")
    if args.Operation == "set-properties" and not name:
        fail("set-properties requires -Name")
    if args.Operation == "delete" and args.All and name:
        fail("delete accepts either -Name or -All")
    if args.Operation == "delete" and not args.All and not name:
        fail("delete requires -Name or -All")

    properties = {}
    for field, flag in PROPERTY_FLAGS:
        value = ibcmd_yes_no("-" + field, getattr(args, field))
        if value:
            properties[flag] = value
    profile = args.SecurityProfileName.strip()
    if profile:
        properties["--security-profile-name"] = profile
    scope = ibcmd_scope(args.Scope)
    if args.Operation == "set-properties" and not properties and not scope:
        fail("set-properties requires at least one property")
    if args.Operation != "set-properties" and (properties or scope):
        fail("property parameters are valid only for set-properties")

    if args.Operation in ("set-properties", "delete"):
        assert_info_base_mutable(
            args.InfoBasePath, args.InfoBaseServer, args.InfoBaseRef, args.AllowProd)

    arguments = build_ibcmd_arguments(
        args.Operation, name, args.All, properties, scope,
        args.InfoBasePath, args.InfoBaseServer, args.InfoBaseRef, dbms,
        args.DataPath, args.UserName, args.Password,
    )
    command = format_ibcmd_command(arguments)
    if args.WhatIf:
        print(command)
        sys.exit(0)

    exe = resolve_ibcmd_path(args.V8Path)
    print(f"Running: {command}")
    code, had_output = execute_ibcmd(exe, arguments)
    if code != 0:
        print(f"Error: ibcmd finished with code {code}", file=sys.stderr)
        sys.exit(1)

    if args.Operation == "list":
        if not had_output:
            print("Расширений нет")
        print("Список расширений получен")
    elif args.Operation == "check":
        print(f"Проверка расширения завершена: {name}")
    elif args.Operation == "set-properties":
        print(f"Свойства расширения обновлены: {name}")
    else:
        target = "все" if args.All else name
        print(f"Расширение удалено: {target}")
    sys.exit(0)


if __name__ == "__main__":
    main()
