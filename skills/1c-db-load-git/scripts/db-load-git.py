#!/usr/bin/env python3
# db-load-git v1.3 - Load Git changes into 1C database
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
def get_object_xml_from_subfile(relative_path):
    """Map sub-file path (BSL, HTML, etc.) to object XML path."""
    parts = re.split(r"[\\/]", relative_path)
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}.xml"
    return None


def run_git(config_dir, git_args):
    """Run a git command in config_dir and return output lines on success."""
    result = subprocess.run(
        ["git"] + git_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=config_dir,
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]
    return []


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Load Git changes into 1C database",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="", help="Path to 1cv8.exe or its bin directory")
    parser.add_argument("-InfoBasePath", default="", help="Path to file infobase")
    parser.add_argument("-InfoBaseServer", default="", help="1C server (for server infobase)")
    parser.add_argument("-InfoBaseRef", default="", help="Infobase name on server")
    parser.add_argument("-UserName", default="", help="1C user name")
    parser.add_argument("-Password", default="", help="1C user password")
    parser.add_argument("-ConfigDir", required=True, help="Directory with XML configuration (git repo)")
    parser.add_argument(
        "-Source",
        default="All",
        choices=["All", "Staged", "Unstaged", "Commit"],
        help="Change source (default: All)",
    )
    parser.add_argument("-CommitRange", default="", help="Commit range (for Source=Commit), e.g. HEAD~3..HEAD")
    parser.add_argument("-Extension", default="", help="Extension name to load")
    parser.add_argument("-AllExtensions", action="store_true", help="Load all extensions")
    parser.add_argument(
        "-Format",
        default="Hierarchical",
        choices=["Hierarchical", "Plain"],
        help="File format (default: Hierarchical)",
    )
    parser.add_argument("-DryRun", action="store_true", help="Only show what would be loaded (no actual load)")
    parser.add_argument("-UpdateDB", action="store_true", help="Also update database configuration after load")
    parser.add_argument("-StrictLog", action="store_true")
    args = parser.parse_args()

    # --- Resolve V8Path (skip if DryRun) ---
    v8path = None
    if not args.DryRun:
        v8path = resolve_v8path(args.V8Path)

    # --- Validate connection (skip if DryRun) ---
    if not args.DryRun:
        if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
            print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
            sys.exit(1)

    # --- Validate config dir ---
    if not os.path.exists(args.ConfigDir):
        print(f"Error: config directory not found: {args.ConfigDir}", file=sys.stderr)
        sys.exit(1)

    # --- Validate Commit mode ---
    if args.Source == "Commit" and not args.CommitRange:
        print("Error: -CommitRange required for Source=Commit", file=sys.stderr)
        sys.exit(1)

    # --- Check git ---
    try:
        subprocess.run(["git", "--version"], capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: git not found in PATH", file=sys.stderr)
        sys.exit(1)

    # --- Get changed files from Git ---
    changed_files = []

    if args.Source == "Staged":
        print("Getting staged changes...")
        changed_files += run_git(args.ConfigDir, ["diff", "--cached", "--name-only", "--relative"])
    elif args.Source == "Unstaged":
        print("Getting unstaged changes...")
        changed_files += run_git(args.ConfigDir, ["diff", "--name-only", "--relative"])
        changed_files += run_git(args.ConfigDir, ["ls-files", "--others", "--exclude-standard"])
    elif args.Source == "Commit":
        print(f"Getting changes from {args.CommitRange}...")
        changed_files += run_git(args.ConfigDir, ["diff", "--name-only", "--relative", args.CommitRange])
    elif args.Source == "All":
        print("Getting all uncommitted changes...")
        changed_files += run_git(args.ConfigDir, ["diff", "--cached", "--name-only", "--relative"])
        changed_files += run_git(args.ConfigDir, ["diff", "--name-only", "--relative"])
        changed_files += run_git(args.ConfigDir, ["ls-files", "--others", "--exclude-standard"])

    # Deduplicate and filter blanks
    changed_files = list(dict.fromkeys(f for f in changed_files if f.strip()))

    if len(changed_files) == 0:
        print("No changes found")
        sys.exit(0)

    print(f"Git changes detected: {len(changed_files)} files")

    # --- Filter and map to config files ---
    config_files = []

    for file in changed_files:
        file = file.strip().replace("\\", "/")
        if not file:
            continue

        # Skip service files
        if file == "ConfigDumpInfo.xml":
            continue

        full_path = os.path.join(args.ConfigDir, file)

        if file.endswith(".xml"):
            # XML file - add directly if exists
            if os.path.exists(full_path):
                if file not in config_files:
                    config_files.append(file)
        else:
            # Non-XML (BSL, HTML, etc.) - map to parent object XML + include all Ext/ files
            object_xml = get_object_xml_from_subfile(file)
            if object_xml:
                full_xml_path = os.path.join(args.ConfigDir, object_xml)
                if os.path.exists(full_xml_path):
                    if object_xml not in config_files:
                        config_files.append(object_xml)
                    if os.path.exists(full_path) and file not in config_files:
                        config_files.append(file)

                    # Add all files from Ext/ directory of the object
                    parts = re.split(r"[\\/]", file)
                    if len(parts) >= 2:
                        ext_dir = os.path.join(args.ConfigDir, parts[0], parts[1], "Ext")
                        if os.path.isdir(ext_dir):
                            for root, dirs, files in os.walk(ext_dir):
                                for fname in files:
                                    abs_path = os.path.join(root, fname)
                                    rel_path = os.path.relpath(abs_path, args.ConfigDir).replace("\\", "/")
                                    if rel_path not in config_files:
                                        config_files.append(rel_path)

    if len(config_files) == 0:
        print("No configuration files found in changes")
        sys.exit(0)

    print(f"Files for loading: {len(config_files)}")
    for f in config_files:
        print(f"  {f}")

    # --- DryRun: stop here ---
    if args.DryRun:
        print("")
        print("DryRun mode - no changes applied")
        sys.exit(0)

    # --- Temp dir ---
    temp_dir = os.path.join(tempfile.gettempdir(), f"db_load_git_{random.randint(0, 999999)}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # --- Write list file (UTF-8 with BOM) ---
        list_file = os.path.join(temp_dir, "load_list.txt")
        with open(list_file, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(config_files))

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
        arguments += ["-listFile", list_file]
        arguments += ["-Format", args.Format]
        arguments.append("-partial")
        arguments.append("-updateConfigDumpInfo")

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
        print("")
        print("Executing partial configuration load...")
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
