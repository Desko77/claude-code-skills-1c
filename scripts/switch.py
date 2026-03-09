#!/usr/bin/env python3
# switch.py v1.1 — Переключение навыков 1С между AI-платформами и рантаймами
# Source: https://github.com/Desko77/claude-code-skills-1c
"""
Копирует навыки из .claude/skills/ на другие AI-платформы (Cursor, Codex, Copilot,
Kiro, Gemini CLI, OpenCode, Windsurf, Kilo Code, Cline, Roo Code, Augment и др.)
с перезаписью путей, и/или переключает рантайм (PowerShell ↔ Python).

Использование:
  python scripts/switch.py                           # интерактивный режим
  python scripts/switch.py cursor                    # скопировать на Cursor
  python scripts/switch.py cursor --runtime python   # скопировать + Python
  python scripts/switch.py --undo cursor             # удалить копию
  python scripts/switch.py --runtime python          # сменить runtime in-place
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


def check_runtime_files(skills_dir, target_runtime, root):
    """Check that target runtime script files exist. Returns list of warnings."""
    warnings = []
    for skill_name in scan_skills(skills_dir):
        for md_path in collect_md_files(os.path.join(skills_dir, skill_name)):
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if target_runtime == 'python':
                matches = RX_PS.findall(content)
                for m in matches:
                    py_path = m.lstrip("'") + '.py'
                    if not os.path.isfile(os.path.join(root, py_path)):
                        warnings.append(f"  {py_path} не найден")
            elif target_runtime == 'powershell':
                matches = RX_PY.findall(content)
                for m in matches:
                    ps1_path = m.lstrip("'") + '.ps1'
                    if not os.path.isfile(os.path.join(root, ps1_path)):
                        warnings.append(f"  {ps1_path} не найден")
    return warnings


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

    installed = 0
    warnings = []

    print(f"\nКопирование {len(skills)} навыков в {target_prefix}/ ...")

    for skill_name in skills:
        src_skill = os.path.join(src_dir, skill_name)
        dst_skill = os.path.join(target_dir, skill_name)

        # Copy entire skill directory
        shutil.copytree(src_skill, dst_skill)

        # Rewrite paths in all .md files
        for md_path in collect_md_files(dst_skill):
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = rewrite_paths(content, SOURCE_PREFIX, target_prefix)

            # Apply runtime switch if requested
            if runtime == 'python':
                new_content, _ = switch_runtime_content(new_content, 'python')

                # Check .py files exist in source repo
                for m in RX_PS.findall(content):
                    clean = m.lstrip("'").replace(SOURCE_PREFIX, target_prefix)
                    original_py = m.lstrip("'") + '.py'
                    if not os.path.isfile(os.path.join(repo_root(), original_py)):
                        warnings.append(f"  {original_py} не найден ({skill_name})")

            if new_content != content:
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

        print(f"  [OK] {skill_name}")
        installed += 1

    print(f"\nГотово! {installed} навыков установлено в {target_prefix}/")
    if warnings:
        print("\nПредупреждения (отсутствующие .py файлы):")
        for w in warnings:
            print(w)
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
    warnings = []

    print(f"\nПереключение на {runtime} в {PLATFORMS[platform_name]}/ ...")

    for skill_name in skills:
        skill_path = os.path.join(skills_dir, skill_name)
        for md_path in collect_md_files(skill_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content, changed = switch_runtime_content(content, runtime)

            # Check target files exist
            if runtime == 'python':
                for m in RX_PS.findall(content):
                    py_path = m.lstrip("'") + '.py'
                    full = os.path.join(repo_root(), py_path)
                    if not os.path.isfile(full):
                        md_name = os.path.basename(md_path)
                        warnings.append(f"  {py_path} не найден ({skill_name}/{md_name})")
            elif runtime == 'powershell':
                for m in RX_PY.findall(content):
                    ps1_path = m.lstrip("'") + '.ps1'
                    full = os.path.join(repo_root(), ps1_path)
                    if not os.path.isfile(full):
                        md_name = os.path.basename(md_path)
                        warnings.append(f"  {ps1_path} не найден ({skill_name}/{md_name})")

            if changed:
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                md_name = os.path.basename(md_path)
                print(f"  [OK] {skill_name}/{md_name}")
                switched += 1

    print(f"\nПереключено {switched} файлов на {runtime}.")
    if warnings:
        print(f"\nПредупреждения (отсутствующие файлы):")
        for w in warnings:
            print(w)
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

    # Check if already installed — offer update or remove
    project_dir = os.getcwd()
    target_prefix = PLATFORMS[platform]
    target_dir = os.path.join(project_dir, target_prefix.replace('/', os.sep))

    if platform != 'claude-code' and os.path.isdir(target_dir):
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

    if platform == 'claude-code':
        return cmd_switch_runtime(runtime, project_dir)
    else:
        return cmd_install(platform, runtime, project_dir)


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
        if args.platform == 'claude-code':
            parser.error("--undo не применим к claude-code (это исходная платформа)")
        return cmd_undo(args.platform, args.project_dir)

    # --runtime without platform = in-place switch
    if args.runtime and not args.platform:
        return cmd_switch_runtime(args.runtime, args.project_dir)

    # platform specified
    if args.platform:
        if args.platform == 'claude-code':
            if args.runtime:
                return cmd_switch_runtime(args.runtime, args.project_dir)
            else:
                parser.error("для claude-code укажите --runtime python или --runtime powershell")
        runtime = args.runtime or 'powershell'
        return cmd_install(args.platform, runtime, args.project_dir)

    # No args at all — shouldn't reach here due to len(sys.argv)==1 check
    return interactive_mode()


if __name__ == '__main__':
    sys.exit(main() or 0)
