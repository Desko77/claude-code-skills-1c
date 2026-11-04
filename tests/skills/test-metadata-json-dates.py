"""Date-like metadata synonyms remain literal strings in both ports."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ('meta-compile', '-JsonPath', {'type': 'Catalog', 'name': 'Тест'}),
    ('subsystem-compile', '-DefinitionFile', {'name': 'Тест'}),
    ('role-compile', '-JsonPath', {'name': 'Тест'}),
]
with tempfile.TemporaryDirectory(prefix='metadata json ') as temporary:
    root = Path(temporary)
    for skill, flag, definition in CASES:
        title = '2024-01-01T03:00:00+03:00'
        definition['synonym'] = title
        input_file = root / f'{skill}.json'
        input_file.write_text(json.dumps(definition, ensure_ascii=False), encoding='utf-8')
        for extension, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
            output = root / f'{skill}-{extension}'
            script = ROOT / f'skills/1c-{skill}/scripts/{skill}.{extension}'
            result = subprocess.run(command + [str(script), flag, str(input_file), '-OutputDir', str(output)],
                                    capture_output=True, text=True, encoding='utf-8')
            assert result.returncode == 0, (skill, extension, result.stdout, result.stderr)
            assert any(title.encode('utf-8') in path.read_bytes() for path in output.rglob('*.xml')), (skill, extension)
print('Both metadata compiler ports preserve date-like synonyms.')
