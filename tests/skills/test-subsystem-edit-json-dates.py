"""Nested operation JSON preserves date-like strings in subsystem properties."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='subsystem edit ') as temporary:
    root = Path(temporary)
    title = '2024-01-01T03:00:00+03:00'
    definition = root / 'definition.json'
    definition.write_text(json.dumps({'name': 'Test'}), encoding='utf-8')
    changes = root / 'changes.json'
    value = json.dumps({'name': 'Synonym', 'value': title})
    changes.write_text(json.dumps([{'operation': 'set-property', 'value': value}]), encoding='utf-8')
    compiler = ROOT / 'skills/1c-subsystem-compile/scripts/subsystem-compile.py'
    for extension, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        output = root / extension
        subprocess.run([sys.executable, str(compiler), '-DefinitionFile', str(definition), '-OutputDir', str(output)],
                       check=True, capture_output=True)
        target = output / 'Subsystems/Test.xml'
        script = ROOT / f'skills/1c-subsystem-edit/scripts/subsystem-edit.{extension}'
        result = subprocess.run(command + [str(script), '-DefinitionFile', str(changes),
                                '-SubsystemPath', str(target), '-NoValidate'],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (extension, result.stdout, result.stderr)
        assert title.encode('utf-8') in target.read_bytes(), extension
print('Both subsystem editors preserve date-like synonyms.')
