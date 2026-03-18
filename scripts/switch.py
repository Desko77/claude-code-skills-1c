#!/usr/bin/env python3
# switch.py v1.2 — Переключение навыков 1С между AI-платформами и рантаймами
# Source: https://github.com/Desko77/claude-code-skills-1c
"""
Копирует навыки из .claude/skills/ на другие AI-платформы (Cursor, Codex, Copilot,
Kiro, Gemini CLI, OpenCode, Windsurf, Kilo Code, Cline, Roo Code, Augment и др.)
с перезаписью путей, и/или переключает рантайм (PowerShell ↔ Python).

Использование:
  python scripts/switch.py                                       # интерактивный режим
  python scripts/switch.py cursor                                # скопировать на Cursor
  python scripts/switch.py cursor --runtime python               # скопировать + Python
  python scripts/switch.py claude-code --project-dir /my/proj    # установить в проект
  python scripts/switch.py --undo cursor                         # удалить копию
  python scripts/switch.py --runtime python                      # сменить runtime in-place
"""
import argparse
import glob
import os
import re
import shutil
import sys

# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------
PLATFORMS = {
    'claude-code': '.claude/skills',
    'agents':      '.agents/skills',
    'augment':     '.augment/skills',
    'cline':       '.cline/skills',
    'codex':       '.codex/skills',
    'cursor':      '.cursor/skills',
    'copilot':     '.github/skills',
    'gemini':      '.gemini/skills',
    'kilo':        '.kilocode/skills',
    'kiro':        '.kiro/skills',
    'opencode':    '.opencode/skills',
    'roo':         '.roo/skills',
    'windsurf':    '.windsurf/skills',
}

SOURCE_PREFIX = '.claude/skills'

# Рекомендуемые записи для .gitignore целевого проекта
GITIGNORE_RECOMMENDATIONS = [
    '.v8-project.json',
    'build/',
    'base/',
    '*.epf',
    '*.erf',
    '*.log',
]

# ---------------------------------------------------------------------------
# Runtime regex patterns (from switch-to-python.py / switch-to-powershell.py)
# ---------------------------------------------------------------------------
RX_PS = re.compile(r'powershell\.exe\s+(?:-NoProfile\s+)?-File\s+(.+?)\.ps1')
RX_PY = re.compile(r"python\s+('?[\w./_-]+?)\.py")


def repo_root():
    """Return the repository root (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_skills_dir():
    return os.path.join(repo_root(), '.claude', 'skills')


def scan_skills(skills_dir):
    """Return sorted list of skill directory names that contain SKILL.md."""
    result = []
    for entry in sorted(os.listdir(skills_dir)):
        skill_path = os.path.join(skills_dir, entry)
        if os.path.isdir(skill_path) and os.path.isfile(os.path.join(skill_path, 'SKILL.md')):
            result.append(entry)
    return result


def collect_md_files(skill_dir):
    """Return list of .md files in a skill directory."""
    return sorted(glob.glob(os.path.join(skill_dir, '*.md')))


def classify_skill_runtime(skill_dir):
    """Classify skill runtime based on invocations in .md files.

    Returns 'ps', 'py', 'both', or 'none'.
    """
    has_ps = has_py = False
    for md_path in collect_md_files(skill_dir):
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if RX_PS.search(content):
            has_ps = True
        if RX_PY.search(content):
            has_py = True
    if has_ps and has_py:
        return 'both'
    return 'ps' if has_ps else ('py' if has_py else 'none')


def check_missing_files(skill_dir, target_runtime, root):
    """Check if target runtime script files exist for a skill.

    Returns list of missing file paths (relative to root).
    """
    missing = []
    for md_path in collect_md_files(skill_dir):
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if target_runtime == 'python':
            for m in RX_PS.findall(content):
                py_path = m.lstrip("'") + '.py'
                if not os.path.isfile(os.path.join(root, py_path)):
                    missing.append(py_path)
        elif target_runtime == 'powershell':
            for m in RX_PY.findall(content):
                ps1_path = m.lstrip("'") + '.ps1'
                if not os.path.isfile(os.path.join(root, ps1_path)):
                    missing.append(ps1_path)
    return missing


def is_different_dir(dir1, dir2):
    """Check if two directories are different (resolved)."""
    return os.path.normcase(os.path.realpath(dir1)) != \
           os.path.normcase(os.path.realpath(dir2))


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------
def rewrite_paths(content, source_prefix, target_prefix):
    """Replace .claude/skills/ path prefix with target platform prefix."""
    return content.replace(source_prefix + '/', target_prefix + '/')


def switch_runtime_content(content, target_runtime):
    """Switch runtime invocations in .md content. Returns (new_content, switched)."""
    if target_runtime == 'python':
        new = RX_PS.sub(r'python \1.py', content)
    elif target_runtime == 'powershell':
        new = RX_PY.sub(r'powershell.exe -NoProfile -File \1.ps1', content)
    else:
        return content, False
    return new, new != content


def print_gitignore_recommendations(project_dir):
    """Print .gitignore recommendations for the target project."""
    gitignore_path = os.path.join(project_dir, '.gitignore')
    existing = set()
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                existing.add(line.strip())

    missing = [r for r in GITIGNORE_RECOMMENDATIONS if r not in existing]
    if missing:
        print(f"\nРекомендуется добавить в .gitignore проекта:")
        for r in missing:
            print(f"  {r}")


def collect_runtime_messages(skill_name, skill_dir, target_runtime, root):
    """Check runtime compatibility for a skill.

    Returns (info_list, warning_list).
    """
    info = []
    warnings = []
    src_rt = classify_skill_runtime(skill_dir)

    if target_runtime == 'python' and src_rt in ('ps', 'none'):
        missing = check_missing_files(skill_dir, 'python', root)
        if missing:
            info.append(f"  {skill_name} — только PowerShell "
                        f"(Python-версия не предусмотрена)")
    elif target_runtime == 'powershell' and src_rt in ('py', 'none'):
        missing = check_missing_files(skill_dir, 'powershell', root)
        if missing:
            info.append(f"  {skill_name} — только Python "
                        f"(PowerShell-версия не предусмотрена)")
    else:
        missing = check_missing_files(skill_dir, target_runtime, root)
        for m in missing:
            warnings.append(f"  {m} не найден ({skill_name})")

    return info, warnings


def print_runtime_messages(info, warnings):
    """Print collected info and warning messages."""
    if info:
        print(f"\nИнформация:")
        for i in info:
            print(i)
    if warnings:
        print(f"\nПредупреждения (отсутствующие файлы):")
        for w in warnings:
            print(w)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_install(platform, runtime, project_dir):
    """Copy skills to target platform directory with path rewriting."""
    src_dir = source_skills_dir()
    target_prefix = PLATFORMS[platform]
    target_dir = os.path.join(project_dir, target_prefix.replace('/', os.sep))

    skills = scan_skills(src_dir)
    if not skills:
        print(f"Ошибка: навыки не найдены в {src_dir}", file=sys.stderr)
        return 1

    if os.path.isdir(target_dir):
        existing = scan_skills(target_dir)
        if existing:
            print(f"В {target_prefix}/ уже есть {len(existing)} навыков. Обновляю...")
            shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)

    # Copy root-level files from source skills dir (.gitignore, etc.)
    for name in os.listdir(src_dir):
        src_path = os.path.join(src_dir, name)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, os.path.join(target_dir, name))

    installed = 0
    all_info = []
    all_warnings = []

    print(f"\nКопирование {len(skills)} навыков в {target_prefix}/ ...")

    for skill_name in skills:
        src_skill = os.path.join(src_dir, skill_name)
        dst_skill = os.path.join(target_dir, skill_name)

        # Skip runtime conversion for single-runtime skills where
        # target files don't exist (e.g. img-grid has only .py)
        src_rt = classify_skill_runtime(src_skill)
        missing = check_missing_files(src_skill, runtime, repo_root())
        skip_runtime = bool(missing) and (
            (runtime == 'python' and src_rt in ('ps', 'none'))
            or (runtime == 'powershell' and src_rt in ('py', 'none'))
        )

        # Copy entire skill directory
        shutil.copytree(src_skill, dst_skill)

        # Rewrite paths in all .md files
        for md_path in collect_md_files(dst_skill):
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = rewrite_paths(content, SOURCE_PREFIX, target_prefix)

            # Apply runtime switch (skip for single-runtime skills
            # where target runtime is not available)
            if not skip_runtime:
                if runtime == 'python':
                    new_content, _ = switch_runtime_content(new_content, 'python')
                elif runtime == 'powershell':
                    new_content, _ = switch_runtime_content(new_content, 'powershell')

            if new_content != content:
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

        # Check runtime compatibility (against source)
        info, warnings = collect_runtime_messages(
            skill_name, src_skill, runtime, repo_root())
        all_info.extend(info)
        all_warnings.extend(warnings)

        print(f"  [OK] {skill_name}")
        installed += 1

    print(f"\nГотово! {installed} навыков установлено в {target_prefix}/")

    print_runtime_messages(all_info, all_warnings)
    print_gitignore_recommendations(project_dir)

    if platform != 'claude-code':
        print(f"\nДля удаления: python scripts/switch.py --undo {platform}")
    return 0


def cmd_undo(platform, project_dir):
    """Remove installed skills for a platform."""
    target_prefix = PLATFORMS[platform]
    target_dir = os.path.join(project_dir, target_prefix.replace('/', os.sep))

    if not os.path.isdir(target_dir):
        print(f"Директория {target_prefix}/ не найдена — нечего удалять.")
        return 0

    skills = scan_skills(target_dir)
    shutil.rmtree(target_dir)

    # Clean up empty parent directories
    parent = os.path.dirname(target_dir)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)

    print(f"Удалено: {target_prefix}/ ({len(skills)} навыков)")
    return 0


def cmd_switch_runtime(runtime, project_dir):
    """Switch runtime in-place for skills in the current project."""
    # Find skills directory: try all known platform dirs
    skills_dir = None
    platform_name = None
    for name, prefix in PLATFORMS.items():
        candidate = os.path.join(project_dir, prefix.replace('/', os.sep))
        if os.path.isdir(candidate) and scan_skills(candidate):
            skills_dir = candidate
            platform_name = name
            break

    if not skills_dir:
        print("Ошибка: не найдена директория навыков в текущем каталоге.", file=sys.stderr)
        return 1

    skills = scan_skills(skills_dir)
    switched = 0
    all_info = []
    all_warnings = []

    print(f"\nПереключение на {runtime} в {PLATFORMS[platform_name]}/ ...")

    for skill_name in skills:
        skill_path = os.path.join(skills_dir, skill_name)

        # Skip runtime conversion for single-runtime skills where
        # target files don't exist (e.g. img-grid has only .py)
        cur_rt = classify_skill_runtime(skill_path)
        missing = check_missing_files(skill_path, runtime, repo_root())
        skip_runtime = bool(missing) and (
            (runtime == 'python' and cur_rt in ('ps', 'none'))
            or (runtime == 'powershell' and cur_rt in ('py', 'none'))
        )

        info, warnings = collect_runtime_messages(
            skill_name, skill_path, runtime, repo_root())
        all_info.extend(info)
        all_warnings.extend(warnings)

        if skip_runtime:
            continue

        for md_path in collect_md_files(skill_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content, changed = switch_runtime_content(content, runtime)

            if changed:
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                md_name = os.path.basename(md_path)
                print(f"  [OK] {skill_name}/{md_name}")
                switched += 1

    print(f"\nПереключено {switched} файлов на {runtime}.")
    print_runtime_messages(all_info, all_warnings)
    return 0


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------
def ask_choice(prompt, options, default=1):
    """Ask user to choose from numbered options. Returns 1-based index."""
    print(f"\n{prompt}")
    for i, (label, hint) in enumerate(options, 1):
        marker = "*" if i == default else " "
        print(f"  {marker}{i:>2}. {label:<16} ({hint})")
    while True:
        try:
            raw = input(f"\nВыбор [{default}]: ").strip()
            if not raw:
                return default
            val = int(raw)
            if 1 <= val <= len(options):
                return val
            print(f"  Введите число от 1 до {len(options)}")
        except ValueError:
            print(f"  Введите число от 1 до {len(options)}")
        except (EOFError, KeyboardInterrupt):
            print("\nОтмена.")
            sys.exit(0)


def ask_path(prompt, default=''):
    """Ask user for a directory path."""
    hint = f" [{default}]" if default else ""
    try:
        raw = input(f"\n{prompt}{hint}: ").strip()
        return raw if raw else default
    except (EOFError, KeyboardInterrupt):
        print("\nОтмена.")
        sys.exit(0)


def interactive_mode():
    """Run interactive setup wizard."""
    print("Навыки 1С — настройка платформы")
    print("=" * 31)

    platform_options = [
        ("Claude Code",    ".claude/skills/"),
        ("Augment",        ".augment/skills/"),
        ("Cline",          ".cline/skills/"),
        ("Cursor",         ".cursor/skills/"),
        ("GitHub Copilot", ".github/skills/"),
        ("Kilo Code",      ".kilocode/skills/"),
        ("Kiro",           ".kiro/skills/"),
        ("OpenAI Codex",   ".codex/skills/"),
        ("Gemini CLI",     ".gemini/skills/"),
        ("OpenCode",       ".opencode/skills/"),
        ("Roo Code",       ".roo/skills/"),
        ("Windsurf",       ".windsurf/skills/"),
        ("Agent Skills",   ".agents/skills/"),
    ]
    platform_keys = [
        'claude-code', 'augment', 'cline', 'cursor', 'copilot', 'kilo',
        'kiro', 'codex', 'gemini', 'opencode', 'roo', 'windsurf', 'agents',
    ]

    choice = ask_choice("Для какой платформы настроить навыки?", platform_options)
    platform = platform_keys[choice - 1]

    project_dir = os.getcwd()
    install_mode = True

    # For claude-code in repo root, offer runtime switch as alternative
    if platform == 'claude-code' and not is_different_dir(project_dir, repo_root()):
        mode_options = [
            ("Переключить runtime", "сменить PowerShell \u2194 Python в текущем проекте"),
            ("Установить в проект", "скопировать навыки в другой проект"),
        ]
        mode = ask_choice("Что сделать?", mode_options)
        install_mode = (mode == 2)

    # Ask for project directory when installing
    if install_mode:
        default_dir = project_dir
        project_dir = ask_path("Путь к целевому проекту", default_dir)
        if not project_dir or not os.path.isdir(project_dir):
            print(f"Ошибка: директория '{project_dir}' не найдена.",
                  file=sys.stderr)
            return 1

    # Check if already installed — offer update or remove
    target_prefix = PLATFORMS[platform]
    target_dir = os.path.join(project_dir, target_prefix.replace('/', os.sep))

    if install_mode and os.path.isdir(target_dir):
        existing = scan_skills(target_dir)
        if existing:
            action_options = [
                ("Обновить", f"перезаписать {len(existing)} навыков"),
                ("Удалить",  f"удалить {target_prefix}/"),
                ("Отмена",   "ничего не делать"),
            ]
            action = ask_choice(
                f"В {target_prefix}/ уже есть {len(existing)} навыков.",
                action_options
            )
            if action == 2:
                return cmd_undo(platform, project_dir)
            if action == 3:
                print("Отмена.")
                return 0

    runtime_options = [
        ("PowerShell", "рекомендуется для Windows"),
        ("Python",     "рекомендуется для Linux/Mac"),
    ]
    rt_choice = ask_choice("Какой рантайм скриптов?", runtime_options)
    runtime = 'powershell' if rt_choice == 1 else 'python'

    if install_mode:
        return cmd_install(platform, runtime, project_dir)
    else:
        return cmd_switch_runtime(runtime, project_dir)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) == 1:
        return interactive_mode()

    parser = argparse.ArgumentParser(
        description='Переключение навыков 1С между AI-платформами и рантаймами',
        epilog='Примеры:\n'
               '  python scripts/switch.py cursor\n'
               '  python scripts/switch.py cursor --runtime python\n'
               '  python scripts/switch.py claude-code --project-dir /my/proj\n'
               '  python scripts/switch.py --undo cursor\n'
               '  python scripts/switch.py --runtime python\n',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('platform', nargs='?', choices=list(PLATFORMS.keys()),
                        help='целевая платформа')
    parser.add_argument('--runtime', choices=['python', 'powershell'],
                        help='рантайм скриптов (python или powershell)')
    parser.add_argument('--undo', action='store_true',
                        help='удалить навыки для указанной платформы')
    parser.add_argument('--project-dir', default=os.getcwd(),
                        help='путь к целевому проекту (по умолчанию: текущий каталог)')

    args = parser.parse_args()

    # --undo requires platform
    if args.undo:
        if not args.platform:
            parser.error("--undo требует указания платформы")
        if args.platform == 'claude-code' \
                and not is_different_dir(args.project_dir, repo_root()):
            parser.error(
                "--undo не применим к claude-code в исходном репозитории")
        return cmd_undo(args.platform, args.project_dir)

    # --runtime without platform = in-place switch
    if args.runtime and not args.platform:
        return cmd_switch_runtime(args.runtime, args.project_dir)

    # platform specified
    if args.platform:
        if args.platform == 'claude-code':
            # claude-code + different project-dir → install
            if is_different_dir(args.project_dir, repo_root()):
                runtime = args.runtime or 'powershell'
                return cmd_install(args.platform, runtime, args.project_dir)
            # claude-code in repo root → runtime switch only
            if args.runtime:
                return cmd_switch_runtime(args.runtime, args.project_dir)
            else:
                parser.error(
                    "для claude-code без --project-dir укажите "
                    "--runtime python или --runtime powershell")
        runtime = args.runtime or 'powershell'
        return cmd_install(args.platform, runtime, args.project_dir)

    # No args at all — shouldn't reach here due to len(sys.argv)==1 check
    return interactive_mode()


if __name__ == '__main__':
    sys.exit(main() or 0)
