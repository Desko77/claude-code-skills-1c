"""Config-index queries must preserve string values, arrays and nulls."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
expected = {'synonym': '2024-01-01T03:00:00+03:00',
            'attributes': {'Field': {'synonym': '2024-01-01T00:00:00'}},
            'values': [None, '2024-01-01T00:00:00Z', 'plain'],
            'one': ['2024-02-01T00:00:00'], 'empty': [], 'nullable': None}
with tempfile.TemporaryDirectory(prefix='index json ') as tmp:
    path = Path(tmp) / 'index.json'
    path.write_text(json.dumps({'objects': {'Catalog.Test': expected}}), encoding='utf-8')
    for ext, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        script = ROOT / f'skills/1c-config-index/scripts/config-index.{ext}'
        result = subprocess.run(command + [str(script), '-IndexPath', str(path), '-Object', 'Catalog.Test'],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (ext, result.stderr)
        assert json.loads(result.stdout) == expected, (ext, result.stdout)
print('Both config-index ports preserve date-like strings and arrays.')
