"""Date-like titles must remain strings in both form-edit ports."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / 'skills/1c-form-compile/scripts/form-compile.py'
EDITORS = [
    ['pwsh', '-NoProfile', '-File', str(ROOT / 'skills/1c-form-edit/scripts/form-edit.ps1')],
    [sys.executable, str(ROOT / 'skills/1c-form-edit/scripts/form-edit.py')],
]

with tempfile.TemporaryDirectory(prefix='form edit проверка ') as directory:
    work = Path(directory)
    definition = work / 'form.json'
    definition.write_text(json.dumps({'title': 'Тест', 'attributes': [], 'elements': []}, ensure_ascii=False), encoding='utf-8')
    changes = work / 'changes.json'
    titles = ['2024-01-01T00:00:00', '2024-01-01T03:00:00+03:00']
    changes.write_text(json.dumps({'elements': [
        {'label': f'Метка{i}', 'title': title} for i, title in enumerate(titles)
    ]}, ensure_ascii=False), encoding='utf-8')
    for i, editor in enumerate(EDITORS):
        form = work / f'Form{i}.xml'
        subprocess.run([sys.executable, str(COMPILER), '-JsonPath', str(definition), '-OutputPath', str(form)], check=True, capture_output=True)
        result = subprocess.run(editor + ['-FormPath', str(form), '-JsonPath', str(changes)], capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise AssertionError(f'{editor[0]} exited {result.returncode}: {result.stdout}\n{result.stderr}')
        contents = form.read_text(encoding='utf-8-sig')
        for title in titles:
            assert title in contents, f'{editor[0]} changed or dropped {title}'
print('Both form-edit ports preserve ISO-like titles and timezone offsets.')
