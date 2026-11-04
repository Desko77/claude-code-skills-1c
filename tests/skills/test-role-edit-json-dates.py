"""Role editor preserves date-like metadata properties from JSON."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='role edit ') as temporary:
    root = Path(temporary)
    value = '2024-01-01T03:00:00+03:00'
    definition = root / 'role.json'
    definition.write_text(json.dumps({'name': 'Test'}), encoding='utf-8')
    operations = root / 'operations.json'
    operations.write_text(json.dumps([{'operation': 'modify-property', 'property': 'synonym', 'value': value}]), encoding='utf-8')
    compiler = ROOT / 'skills/1c-role-compile/scripts/role-compile.py'
    for ext, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        output = root / ext
        subprocess.run([sys.executable, str(compiler), '-JsonPath', str(definition), '-OutputDir', str(output)], check=True, capture_output=True)
        target = output / 'Roles/Test.xml'
        editor = ROOT / f'skills/1c-role-edit/scripts/role-edit.{ext}'
        result = subprocess.run(command + [str(editor), '-DefinitionFile', str(operations), '-RolePath', str(target), '-NoValidate'],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (ext, result.stdout, result.stderr)
        assert value.encode() in target.read_bytes(), ext
print('Both role editors preserve date-like synonyms.')
