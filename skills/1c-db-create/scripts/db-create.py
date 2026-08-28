#!/usr/bin/env python3
# db-create v1.0 - Create 1C information base
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
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Create 1C information base",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UseTemplate", default="")
    parser.add_argument("-AddToList", action="store_true")
    parser.add_argument("-ListName", default="")
    # Значение по умолчанию None, а не пустая строка: пустую строку задают, чтобы снять
    # аргументы из настроек проекта, и от отсутствия параметра ее надо отличать.
    parser.add_argument("-AdditionalV8Arguments", default=None)
    parser.add_argument("-AdditionalIbcmdArguments", default=None)
    parser.add_argument("-StrictLog", action="store_true")
    args = parser.parse_args(merge_dash_values(
        sys.argv[1:], ("-AdditionalV8Arguments", "-AdditionalIbcmdArguments")))

    v8path = resolve_v8path(args.V8Path)

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Validate template ---
    if args.UseTemplate and not os.path.exists(args.UseTemplate):
        print(f"Error: template file not found: {args.UseTemplate}", file=sys.stderr)
        sys.exit(1)

    # --- Temp dir ---
    temp_dir = os.path.join(tempfile.gettempdir(), f"db_create_{random.randint(0, 999999)}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # --- Build arguments ---
        # Каталог поиска настроек проекта: от места будущей базы вверх по дереву.
        settings_dir = args.InfoBasePath or os.getcwd()

        # Утилита администрирования принимает собственный набор ключей и не понимает ни /Out,
        # ни /DumpResult, ни /DisableStartupDialogs - у нее отдельная ветка построения команды.
        is_ibcmd = os.path.splitext(os.path.basename(v8path))[0].lower() == "ibcmd"

        # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
        # достаться от прошлого прогона. Объявлены до ветвления: ветка утилиты
        # администрирования их не создает.
        out_file = os.path.join(temp_dir, "create_log.txt")
        result_file = os.path.join(temp_dir, "create_result.txt")

        if is_ibcmd:
            if args.InfoBaseServer and args.InfoBaseRef:
                print("Error: создание серверной базы через ibcmd этим скриптом не поддерживается", file=sys.stderr)
                sys.exit(1)
            # Ключи платформы утилита администрирования не понимает. Молча их отбросить
            # нельзя: вызывающий считает, что аргумент действует, и получит поведение,
            # которого не просил.
            # Шаблон и регистрацию в списке баз утилита администрирования делает другими
            # командами. Молчаливое игнорирование дало бы пустую незарегистрированную базу и
            # отчет об успехе.
            if args.UseTemplate:
                print("Error: -UseTemplate не поддерживается движком ibcmd", file=sys.stderr)
                sys.exit(1)
            if args.AddToList:
                print("Error: -AddToList не поддерживается движком ibcmd", file=sys.stderr)
                sys.exit(1)
            if split_platform_arguments(args.AdditionalV8Arguments):
                print("Error: -AdditionalV8Arguments относится к 1cv8.exe, а выбран движок ibcmd. "
                      "Используйте -AdditionalIbcmdArguments", file=sys.stderr)
                sys.exit(1)
            extra = resolve_platform_arguments(args.AdditionalIbcmdArguments, settings_dir, "ibcmdargs")
            # Позиционный токен встает в строку как часть команды: "infobase create config" -
            # это уже другая команда, а не создание базы с дополнительным ключом.
            positional = [a for a in extra if not a.startswith("-")]
            if positional:
                print("Error: позиционный токен в -AdditionalIbcmdArguments меняет команду ibcmd: "
                      + ", ".join(positional), file=sys.stderr)
                sys.exit(1)
            arguments = ["infobase", "create", f'--db-path="{args.InfoBasePath}"'] + extra
        else:
            arguments = ["CREATEINFOBASE"]

            if args.InfoBaseServer and args.InfoBaseRef:
                arguments.append(f'Srvr="{args.InfoBaseServer}";Ref="{args.InfoBaseRef}"')
            else:
                arguments.append(f'File="{args.InfoBasePath}"')

            # --- Template ---
            if args.UseTemplate:
                arguments.extend(["/UseTemplate", args.UseTemplate])

            # --- Add to list ---
            if args.AddToList:
                if args.ListName:
                    arguments.extend(["/AddToList", args.ListName])
                else:
                    arguments.append("/AddToList")

            # --- Output ---
            arguments.extend(["/Out", out_file])
            arguments.extend(["/DumpResult", result_file])
            arguments.append("/DisableStartupDialogs")
            arguments.extend(resolve_platform_arguments(
                args.AdditionalV8Arguments, settings_dir, "v8args"))

        # --- Execute ---
        print(f"Running: {os.path.basename(v8path)} {hide_platform_secret(' '.join(arguments))}")
        # Токены платформы уже содержат кавычки: File="путь с пробелом". Список в subprocess
        # на Windows пересобирает такой токен целиком - обрамляет его своими кавычками и
        # экранирует внутренние, и до платформы доезжает искаженный аргумент. PowerShell
        # передает строку как есть, поэтому строка собирается здесь тем же образом.
        if os.name == 'nt':
            # Токен подключения уже несет свои кавычки (File="путь") - платформа разбирает
            # его сама, и перекавычивание его ломает. Остальные значения кавычим по правилам
            # Windows, иначе путь шаблона или журнала с пробелом разъедется на два аргумента.
            parts = [subprocess.list2cmdline([v8path])]
            for a in arguments:
                ready = a.startswith('File="') or a.startswith('Srvr="') or a.startswith('--db-path="')
                parts.append(a if ready else subprocess.list2cmdline([a]))
            command = ' '.join(parts)
        else:
            command = [v8path] + arguments
        # Потоки процесса уходят в файлы: унаследованная консоль отдала бы вывод платформы
        # в кодировке 866 как есть, и кириллица в сообщении об ошибке стала бы нечитаемой.
        stdout_file = os.path.join(temp_dir, "platform_stdout.txt")
        stderr_file = os.path.join(temp_dir, "platform_stderr.txt")
        with open(stdout_file, "wb") as so, open(stderr_file, "wb") as se:
            result = subprocess.run(command, stdout=so, stderr=se)
        exit_code = result.returncode
        show_platform_output([stdout_file, stderr_file])

        # --- Result ---
        # У утилиты администрирования нет ни файла результата, ни лога платформы: вердикт
        # опирается на код возврата и постусловие.
        if is_ibcmd:
            result_file = None
        log_content = None
        if not is_ibcmd and os.path.isfile(out_file):
            try:
                with open(out_file, "r", encoding="utf-8-sig") as f:
                    log_content = f.read()
            except Exception:
                log_content = None

        # Постусловие есть только у файловой базы: серверная база файлом на диске не представлена.
        artifact_path = None
        if args.InfoBaseServer and args.InfoBaseRef:
            success_message = f"Information base created successfully: {args.InfoBaseServer}/{args.InfoBaseRef}"
        else:
            success_message = f"Information base created successfully: {args.InfoBasePath}"
            artifact_path = os.path.join(args.InfoBasePath, "1Cv8.1CD")

        exit_code = write_platform_verdict(
            exit_code,
            result_file,
            log_content,
            success_message,
            "Error creating information base",
            artifact_path=artifact_path,
            strict=args.StrictLog,
        )

        sys.exit(exit_code)

    finally:
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
