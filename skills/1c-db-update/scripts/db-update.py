#!/usr/bin/env python3
# db-update v1.0 — Update 1C database configuration
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Update 1C database configuration",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UserName", default="")
    parser.add_argument("-Password", default="")
    parser.add_argument("-Extension", default="")
    parser.add_argument("-AllExtensions", action="store_true")
    parser.add_argument("-Dynamic", default="", choices=["", "+", "-"])
    parser.add_argument("-Server", action="store_true")
    parser.add_argument("-WarningsAsErrors", action="store_true")
    parser.add_argument("-StrictLog", action="store_true")
    parser.add_argument("-CheckApplicability", action="store_true")
    args = parser.parse_args()

    v8path = resolve_v8path(args.V8Path)

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Temp dir ---
    temp_dir = os.path.join(tempfile.gettempdir(), f"db_update_{random.randint(0, 999999)}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # --- Проверка применимости расширения ---
        # Перехватчик расширения, который ссылается на метод, переименованный поставщиком,
        # не виден ни синтаксическому контролю, ни проверке XML: исходники корректны. Отказ
        # обнаруживается только этой проверкой и только против конкретной базы.
        if args.CheckApplicability and not (args.Extension or args.AllExtensions):
            print("Error: -CheckApplicability requires -Extension or -AllExtensions", file=sys.stderr)
            sys.exit(1)

        if args.CheckApplicability:
            check_args = ["DESIGNER"]
            if args.InfoBaseServer and args.InfoBaseRef:
                check_args.extend(["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"])
            else:
                check_args.extend(["/F", args.InfoBasePath])
            if args.UserName:
                check_args.append(f"/N{args.UserName}")
            if args.Password:
                check_args.append(f"/P{args.Password}")
            check_args.append("/CheckCanApplyConfigurationExtensions")
            if args.Extension:
                check_args.extend(["-Extension", args.Extension])
            check_out = os.path.join(temp_dir, "check_apply_log.txt")
            check_result_file = os.path.join(temp_dir, "check_apply_result.txt")
            check_args.extend(["/Out", check_out])
            check_args.extend(["/DumpResult", check_result_file])
            check_args.append("/DisableStartupDialogs")

            print(f"Running: 1cv8.exe {hide_platform_secret(' '.join(check_args))}")
            check_run = subprocess.run([v8path] + check_args, capture_output=True, text=True)
            check_log = None
            if os.path.isfile(check_out):
                try:
                    with open(check_out, "r", encoding="utf-8-sig") as f:
                        check_log = f.read()
                except Exception:
                    check_log = None
            # Строгий режим здесь включен всегда, а не по ключу вызова: смысл проверки в том,
            # чтобы остановить обновление. Отказ платформа сообщает строкой журнала при нулевом
            # коде возврата, и без строгости проверка нашла бы несовместимость и пропустила
            # обновление дальше.
            check_code = write_platform_verdict(
                check_run.returncode,
                check_result_file,
                check_log,
                "Extension applicability check passed",
                "Extension applicability check failed",
                strict=True,
            )
            if check_code != 0:
                print("Database configuration was NOT updated: the extension cannot be applied "
                      "to this infobase", file=sys.stderr)
                sys.exit(check_code)

        # --- Build arguments ---
        arguments = ["DESIGNER"]

        if args.InfoBaseServer and args.InfoBaseRef:
            arguments.extend(["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"])
        else:
            arguments.extend(["/F", args.InfoBasePath])

        if args.UserName:
            arguments.append(f"/N{args.UserName}")
        if args.Password:
            arguments.append(f"/P{args.Password}")

        arguments.append("/UpdateDBCfg")

        # --- Options ---
        if args.Dynamic:
            arguments.append(f"-Dynamic{args.Dynamic}")
        if args.Server:
            arguments.append("-Server")
        if args.WarningsAsErrors:
            arguments.append("-WarningsAsErrors")

        # --- Extensions ---
        if args.Extension:
            arguments.extend(["-Extension", args.Extension])
        elif args.AllExtensions:
            arguments.append("-AllExtensions")

        # --- Output ---
        # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
        # достаться от прошлого прогона.
        out_file = os.path.join(temp_dir, "update_log.txt")
        result_file = os.path.join(temp_dir, "update_result.txt")
        arguments.extend(["/Out", out_file])
        arguments.extend(["/DumpResult", result_file])
        arguments.append("/DisableStartupDialogs")

        # --- Execute ---
        print(f"Running: 1cv8.exe {hide_platform_secret(' '.join(arguments))}")
        result = subprocess.run(
            [v8path] + arguments,
            capture_output=True,
            text=True,
        )
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
            "Database configuration updated successfully",
            "Error updating database configuration",
            strict=args.StrictLog,
        )

        sys.exit(exit_code)

    finally:
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
