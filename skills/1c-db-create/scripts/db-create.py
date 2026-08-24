#!/usr/bin/env python3
# db-create v1.0 — Create 1C information base
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
    parser.add_argument("-StrictLog", action="store_true")
    args = parser.parse_args()

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
        # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
        # достаться от прошлого прогона.
        out_file = os.path.join(temp_dir, "create_log.txt")
        result_file = os.path.join(temp_dir, "create_result.txt")
        arguments.extend(["/Out", out_file])
        arguments.extend(["/DumpResult", result_file])
        arguments.append("/DisableStartupDialogs")

        # --- Execute ---
        print(f"Running: 1cv8.exe {hide_platform_secret(' '.join(arguments))}")
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
                ready = a.startswith('File="') or a.startswith('Srvr="')
                parts.append(a if ready else subprocess.list2cmdline([a]))
            command = ' '.join(parts)
        else:
            command = [v8path] + arguments
        # Вывод платформы не перехватывается: PowerShell запускает процесс с общей консолью,
        # и его сообщения попадают в вывод навыка. Перехват их прятал, а нужен только код
        # возврата - подробности навык и так печатает из файла журнала ниже.
        result = subprocess.run(command)
        exit_code = result.returncode

        # --- Result ---
        log_content = None
        if os.path.isfile(out_file):
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
