"""Date-like text in spreadsheet cells must stay literal."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='mxl json ') as temporary:
    root = Path(temporary)
    title = '2024-01-01T03:00:00+03:00'
    definition = {'columns': 1, 'areas': [{'name': 'Test', 'rows': [
        {'cells': [{'col': 1, 'text': title}]}]}]}
    source = root / 'definition.json'
    source.write_text(json.dumps(definition, ensure_ascii=False), encoding='utf-8')
    for extension, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        output = root / f'{extension}.xml'
        script = ROOT / f'skills/1c-mxl-compile/scripts/mxl-compile.{extension}'
        result = subprocess.run(command + [str(script), '-JsonPath', str(source), '-OutputPath', str(output)],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (extension, result.stdout, result.stderr)
        assert title.encode('utf-8') in output.read_bytes(), extension
print('Both spreadsheet compilers preserve date-like cell text.')
