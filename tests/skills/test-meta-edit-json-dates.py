"""Date-like synonyms passed to meta-edit remain literal strings."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='meta edit ') as temporary:
    root = Path(temporary)
    title = '2024-01-01T03:00:00+03:00'
    definition = root / 'definition.json'
    definition.write_text(json.dumps({'type': 'Catalog', 'name': 'Тест'}, ensure_ascii=False), encoding='utf-8')
    changes = root / 'changes.json'
    changes.write_text(json.dumps({'modify': {'properties': {'Synonym': title}}}, ensure_ascii=False), encoding='utf-8')
    compiler = ROOT / 'skills/1c-meta-compile/scripts/meta-compile.py'
    for extension, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        output = root / extension
        subprocess.run([sys.executable, str(compiler), '-JsonPath', str(definition), '-OutputDir', str(output)],
                       check=True, capture_output=True)
        script = ROOT / f'skills/1c-meta-edit/scripts/meta-edit.{extension}'
        result = subprocess.run(command + [str(script), '-DefinitionFile', str(changes),
                                '-ObjectPath', str(output / 'Catalogs/Тест'), '-NoValidate'],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (extension, result.stdout, result.stderr)
        assert title.encode('utf-8') in (output / 'Catalogs/Тест.xml').read_bytes(), extension
print('Both metadata editors preserve date-like synonyms.')
