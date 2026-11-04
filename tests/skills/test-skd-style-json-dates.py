"""User style presets preserve date-like font names in both ports."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
case = json.loads((ROOT / 'tests/skills/cases/skd-compile/horizontal-merge.json').read_text(encoding='utf-8'))['input']
case['templates'][0]['style'] = 'myDateFont'
name = '2024-01-01T03:00:00+03:00'
with tempfile.TemporaryDirectory(prefix='skd style ') as temporary:
    root = Path(temporary)
    (root / 'skd-styles.json').write_text(json.dumps({'myDateFont': {'font': name}}), encoding='utf-8')
    definition = root / 'definition.json'
    definition.write_text(json.dumps(case, ensure_ascii=False), encoding='utf-8')
    for ext, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        output = root / f'{ext}.xml'
        script = ROOT / f'skills/1c-skd-compile/scripts/skd-compile.{ext}'
        result = subprocess.run(command + [str(script), '-DefinitionFile', str(definition), '-OutputPath', str(output)],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (ext, result.stdout, result.stderr)
        assert name.encode() in output.read_bytes(), ext
    for ext, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        result_file = root / f'{ext}.json'
        script = ROOT / f'skills/1c-skd-decompile/scripts/skd-decompile.{ext}'
        result = subprocess.run(command + [str(script), '-TemplatePath', str(root / 'py.xml'), '-OutputPath', str(result_file)],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (ext, result.stdout, result.stderr)
        assert 'myDateFont' in result_file.read_text(encoding='utf-8-sig'), ext
print('Both SKD ports preserve and recognize user style strings.')
