#!/usr/bin/env python3
# switch-to-powershell v1.1 — Switch skill .md files back to PowerShell scripts
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Replaces python invocations with powershell.exe in all .md files under .claude/skills/."""
import os, re, glob, sys

def main():
    print("Совет: используйте 'python scripts/switch.py --runtime powershell' (новый интерфейс)\n")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_dir = os.path.join(repo_root, '.claude', 'skills')

    # Collect all .md files in skill directories (SKILL.md, json-dsl.md, etc.)
    md_files = sorted(glob.glob(os.path.join(skills_dir, '*', '*.md')))
    if not md_files:
        print(f"Error: no .md files found in {skills_dir}", file=sys.stderr)
        sys.exit(1)

    rx = re.compile(r'python\s+(\'?\.claude/skills/[^\s\']+?)\.py')
    switched = 0
    warnings = []

    for md_path in md_files:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        matches = rx.findall(content)
        if not matches:
            continue

        # Check that .ps1 files exist for all matches
        all_exist = True
        for m in matches:
            ps1_path = m.lstrip("'") + '.ps1'
            ps1_full = os.path.join(repo_root, ps1_path)
            if not os.path.isfile(ps1_full):
                skill_name = os.path.basename(os.path.dirname(md_path))
                md_name = os.path.basename(md_path)
                warnings.append(f"  SKIP: {ps1_path} not found (referenced in {skill_name}/{md_name})")
                all_exist = False

        if not all_exist:
            continue

        new_content = rx.sub(r'powershell.exe -NoProfile -File \1.ps1', content)
        if new_content != content:
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            skill_name = os.path.basename(os.path.dirname(md_path))
            md_name = os.path.basename(md_path)
            print(f"  [OK] {skill_name}/{md_name}")
            switched += 1

    print(f"\nSwitched {switched} file(s) to PowerShell.")
    if warnings:
        print("\nSkipped (missing .ps1 files):")
        for w in warnings:
            print(w)

if __name__ == '__main__':
    main()
