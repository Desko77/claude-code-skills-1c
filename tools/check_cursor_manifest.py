#!/usr/bin/env python3
"""Проверка состава файлов, которые конвертер переносит в Cursor."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tools/cursor-manifest.json'


def generated_manifest():
    groups = defaultdict(list)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8')
    source_names = {name.casefold(): name for name in tracked.split(chr(0)) if name}
    with tempfile.TemporaryDirectory(prefix='cursor-manifest-') as tmp:
        target = Path(tmp)
        subprocess.run([sys.executable, str(ROOT / 'tools/convert_from_claude.py'),
                        '--source', str(ROOT), '--target', str(target)],
                       check=True, stdout=subprocess.DEVNULL)
        for path in target.rglob('*'):
            if path.is_file():
                rel = path.relative_to(target).as_posix()
                source_rel = rel[:-1] if rel.startswith('rules/') and rel.endswith('.mdc') else rel
                canonical = source_names.get(source_rel.casefold())
                if canonical is None:
                    if (ROOT / source_rel).exists():
                        continue  # Local artifacts are outside the tracked source manifest.
                    canonical = source_rel
                rel = canonical + 'c' if rel.startswith('rules/') and rel.endswith('.mdc') else canonical
                groups[rel.split('/')[0]].append(rel)
    return {group: {'count': len(names), 'sha256': hashlib.sha256(
        ('\n'.join(sorted(names)) + '\n').encode('utf-8')).hexdigest()}
        for group, names in sorted(groups.items())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true')
    args = parser.parse_args()
    actual = generated_manifest()
    if args.update:
        MANIFEST.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Обновлен состав Cursor: {sum(v["count"] for v in actual.values())} файлов.')
        return 0
    expected = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if actual != expected:
        for group in sorted(set(actual) | set(expected)):
            if actual.get(group) != expected.get(group):
                print(f'Изменился состав {group}: было {expected.get(group)}, стало {actual.get(group)}')
        print('Проверьте изменения и обновите: python tools/check_cursor_manifest.py --update')
        return 1
    print(f'Состав Cursor совпадает: {sum(v["count"] for v in actual.values())} файлов.')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
