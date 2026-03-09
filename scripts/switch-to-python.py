#!/usr/bin/env python3
# switch-to-python v1.1 — Switch skill .md files to use Python scripts
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Replaces powershell.exe invocations with python in all .md files under .claude/skills/."""
import os, re, glob, sys

def main():
    print("Совет: используйте 'python scripts/switch.py --runtime python' (новый интерфейс)\n")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_dir = os.path.join(repo_root, '.claude', 'skills')

    # Collect all .md files in skill directories (SKILL.md, json-dsl.md, etc.)
    md_files = sorted(glob.glob(os.path.join(skills_dir, '*', '*.md')))
    if not md_files:
        print(f"Error: no .md files found in {skills_dir}", file=sys.stderr)
        sys.exit(1)

    rx = re.compile(r'powershell\.exe\s+(?:-NoProfile\s+)?-File\s+(.+?)\.ps1')
    switched = 0
    warnings = []

    for md_path in md_files:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        matches = rx.findall(content)
        if not matches:
            continue

        # Check that .py files exist
        for m in matches:
            clean_path = m.lstrip("'")
            py_path = clean_path + '.py'
            py_full = os.path.join(repo_root, py_path)
            if not os.path.isfile(py_full):
                skill_name = os.path.basename(os.path.dirname(md_path))
                md_name = os.path.basename(md_path)
                warnings.append(f"  WARN: {py_path} not found (referenced in {skill_name}/{md_name})")

        new_content = rx.sub(r'python \1.py', content)
        if new_content != content:
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            skill_name = os.path.basename(os.path.dirname(md_path))
            md_name = os.path.basename(md_path)
            print(f"  [OK] {skill_name}/{md_name}")
            switched += 1

    print(f"\nSwitched {switched} file(s) to Python.")
    if warnings:
        print("\nWarnings (missing .py files):")
        for w in warnings:
            print(w)

if __name__ == '__main__':
    main()
