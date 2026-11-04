"""Event bindings are checked against local complete form modules."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
compiler = ROOT / 'skills/1c-form-compile/scripts/form-compile.py'
validators = [
    ['pwsh', '-NoProfile', '-File', str(ROOT / 'skills/1c-form-validate/scripts/form-validate.ps1')],
    [sys.executable, str(ROOT / 'skills/1c-form-validate/scripts/form-validate.py')],
]

with tempfile.TemporaryDirectory(prefix='events ') as tmp:
    root = Path(tmp)
    form = root / 'Form.xml'
    definition = root / 'form.json'
    definition.write_text(json.dumps({'events': {'OnOpen': 'ПриОткрытии'}}, ensure_ascii=False), encoding='utf-8')
    subprocess.run([sys.executable, str(compiler), '-JsonPath', str(definition), '-OutputPath', str(form)], check=True, capture_output=True)
    module = root / 'Form' / 'Module.bsl'
    module.parent.mkdir(exist_ok=True)
    for validator in validators:
        for code, expected in [
            ('Процедура пРИоТКРЫТИИ(Отказ)\nКонецПроцедуры', 0),
            ('Procedure ПриОткрытии(Cancel)\nEndProcedure', 0),
            ('// Процедура ПриОткрытии(Отказ)\n', 0),
            ('Процедура Другая()\nКонецПроцедуры', 0),
        ]:
            module.write_text(code, encoding='utf-8-sig')
            result = subprocess.run(validator + ['-FormPath', str(form)], capture_output=True, text=True, encoding='utf-8')
            assert result.returncode == expected, (validator[0], code, result.stdout, result.stderr)
            if code.startswith('//') or 'Другая' in code:
                assert "[WARN]" in result.stdout and 'ПриОткрытии' in result.stdout
        module.unlink()
        result = subprocess.run(validator + ['-FormPath', str(form)], capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (validator[0], result.stdout, result.stderr)
        assert 'Module.bsl' in result.stdout, result.stdout
        original = form.read_text(encoding='utf-8-sig')
        form.write_text(original.replace('</Form>', '<BaseForm version="2.20"/></Form>'), encoding='utf-8-sig')
        module.write_text('// inherited handler', encoding='utf-8-sig')
        result = subprocess.run(validator + ['-FormPath', str(form)], capture_output=True, text=True, encoding='utf-8')
        assert 'BaseForm may provide inherited handlers' in result.stdout, result.stdout
        assert "not declared in local Module.bsl" not in result.stdout, result.stdout
        form.write_text(original, encoding='utf-8-sig')
        module.unlink()
print('Form event bindings checked for both validators.')
