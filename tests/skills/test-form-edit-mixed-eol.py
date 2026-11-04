"""A form edit must preserve line endings within untouched text values."""
import json
import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
compiler = ROOT / 'skills/1c-form-compile/scripts/form-compile.py'
source = (ROOT / 'skills/1c-form-edit/scripts/form-edit.py').read_text(encoding='utf-8')
function = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == 'restore_unchanged_text_eol')
namespace = {'re': re}
exec(compile(ast.Module(body=[function], type_ignores=[]), '<eol-test>', 'exec'), namespace)
restore = namespace['restore_unchanged_text_eol']
original = b'<r a="x>y"><a>same\nx</a><b>same\r\nx</b><c>unique\ntext</c><!--a\nb--><![CDATA[x\ny]]></r>'
serialized = b'<r a="x>y"><a>same\r\nx</a><b>same\r\nx</b><c>unique\r\ntext</c><!--a\r\nb--><![CDATA[x\r\ny]]></r>'
restored = restore(original, serialized)
assert b'<a>same\nx</a><b>same\r\nx</b>' in restored, 'each unchanged node retains its own EOL'
assert b'<c>unique\ntext</c>' in restored
assert b'<!--a\r\nb--><![CDATA[x\r\ny]]>' in restored, 'comments and CDATA are not altered by the helper'
assert restore(b'<!DOCTYPE r><r>unique\ntext</r>', serialized) == serialized
assert restore(b'<r><a>&#1055;\nX</a></r>', '<r><a>П\r\nX</a></r>'.encode()) == b'<r><a>&#1055;\nX</a></r>'
assert restore(b'<r><a>\n</a></r>', b'<r><a>\r\n</a></r>') == b'<r><a>\n</a></r>'
assert restore(b'<r><a>one\nline</a></r>', b'<r><a>changed\r\nline</a></r>') == b'<r><a>changed\r\nline</a></r>'
shifted = b'<r><a>inserted</a><a>one\r\nline</a></r>'
assert restore(b'<r><a>one\nline</a></r>', shifted) == shifted, 'shifted anonymous siblings must not be confused'
original_tails = b'<r><a>one\nline<x/>two\r\nlines</a></r>'
serialized_tails = b'<r><a>one\r\nline<x/>two\r\nlines</a></r>'
assert restore(original_tails, serialized_tails) == original_tails, 'text and tail retain separate EOL'
with tempfile.TemporaryDirectory(prefix='form eol ') as temporary:
    root = Path(temporary)
    form_def = root / 'form.json'
    form_def.write_text(json.dumps({'title': 'Первая\nВторая', 'elements': [
        {'label': 'Метка', 'title': 'Первая\nВторая'},
        {'label': 'Другая', 'title': 'Третья\nЧетвертая'}]}, ensure_ascii=False), encoding='utf-8')
    changes = root / 'changes.json'
    changes.write_text(json.dumps({'elements': [{'label': 'Новая', 'title': 'Новая'}]}, ensure_ascii=False), encoding='utf-8')
    for ext, command in [('ps1', ['pwsh', '-NoProfile', '-File']), ('py', [sys.executable])]:
        path = root / f'{ext}.xml'
        subprocess.run([sys.executable, str(compiler), '-JsonPath', str(form_def), '-OutputPath', str(path)],
                       check=True, capture_output=True)
        raw = path.read_bytes()
        crlf = 'Первая\r\nВторая'.encode()
        lf = 'Первая\nВторая'.encode()
        assert crlf in raw
        raw = raw.replace(crlf, lf, 1)
        if ext == 'py':
            raw = raw.replace(lf, b'&#1055;' + 'ервая\nВторая'.encode(), 1)
        path.write_bytes(raw)
        result = subprocess.run(command + [str(ROOT / f'skills/1c-form-edit/scripts/form-edit.{ext}'),
                                '-FormPath', str(path), '-JsonPath', str(changes)],
                                capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (ext, result.stdout, result.stderr)
        after = path.read_bytes()
        expected_lf = b'&#1055;' + 'ервая\nВторая'.encode() if ext == 'py' else lf
        assert expected_lf in after, f'{ext}: LF inside text was changed'
        assert crlf in after, f'{ext}: identical text with CRLF was changed'
        assert 'Третья\r\nЧетвертая'.encode() in after, f'{ext}: CRLF inside text was changed'
        assert b'\r\n' in after
print('Both editors preserve mixed text line endings.')
