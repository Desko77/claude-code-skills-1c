"""Validate explicit addition sources without rejecting inherited forms."""
import subprocess
import sys
import tempfile
import copy
from pathlib import Path
from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/skills/cases/form-compile/snapshots/addition-three-kinds/Catalogs/Позиции/Forms/ФормаСписка/Ext/Form.xml'
NS = {'f': 'http://v8.1c.ru/8.3/xcf/logform'}
VALIDATORS = [
    ['pwsh', '-NoProfile', '-File', str(ROOT / 'skills/1c-form-validate/scripts/form-validate.ps1')],
    [sys.executable, str(ROOT / 'skills/1c-form-validate/scripts/form-validate.py')],
]
with tempfile.TemporaryDirectory(prefix='addition source ') as temporary:
    path = Path(temporary) / 'Form.xml'
    tree = etree.parse(str(FIXTURE))
    item = tree.xpath('(//f:AdditionSource/f:Item)[1]', namespaces=NS)[0]
    def run():
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        for validator in VALIDATORS:
            result = subprocess.run(validator + ['-FormPath', str(path)], capture_output=True, text=True, encoding='utf-8')
            assert result.returncode == 0, (validator[0], result.stdout, result.stderr)
            yield result.stdout
    for output in run():
        assert "AdditionSource item 'Отсутствует'" not in output
    item.text = 'Отсутствует'
    for output in run():
        assert "AdditionSource item 'Отсутствует'" in output and '[WARN]' in output, output
    item.text = ''
    for output in run():
        assert 'AdditionSource item is empty' in output and '[WARN]' in output, output
    item.text = 'Отсутствует'
    parent = item.getparent()
    parent.remove(item)
    for output in run():
        assert 'AdditionSource item is empty' in output and '[WARN]' in output, output
    parent.insert(0, item)
    attributes = tree.xpath('//f:Attributes', namespaces=NS)[0]
    attribute = copy.deepcopy(attributes[0])
    attribute.set('name', 'ТолькоРеквизит')
    attribute.set('id', '999')
    attributes.append(attribute)
    item.text = 'ТолькоРеквизит'
    for output in run():
        assert "AdditionSource item 'ТолькоРеквизит'" in output, output
    item.text = 'Отсутствует'
    root = tree.getroot()
    etree.SubElement(root, f'{{{NS["f"]}}}BaseForm', version='2.20')
    for output in run():
        assert "AdditionSource item 'Отсутствует'" not in output, output
        assert 'AdditionSource' in output and 'BaseForm' in output, output
print('Addition sources checked for both validators.')
