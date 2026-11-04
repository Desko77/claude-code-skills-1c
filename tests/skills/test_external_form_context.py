"""Regression coverage for external form owner types in both script ports."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(port, skill, script, *args):
    path = ROOT / 'skills' / skill / 'scripts' / (script + ('.ps1' if port == 'pwsh' else '.py'))
    command = ['pwsh', '-NoProfile', '-File', str(path)] if port == 'pwsh' else [sys.executable, str(path)]
    return subprocess.run(command + list(map(str, args)), text=True, encoding='utf-8', errors='replace', capture_output=True)


class ExternalFormContext(unittest.TestCase):
    def test_owner_type(self):
        for port in ('pwsh', 'python'):
            for kind, invalid, valid in (
                ('ExternalDataProcessor', 'DataProcessorObject', 'ExternalDataProcessorObject'),
                ('ExternalReport', 'ReportObject', 'ExternalReportObject'),
            ):
                with self.subTest(port=port, kind=kind), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / 'Owner.xml').write_text(f'<MetaDataObject version="2.17"><{kind} uuid="x"/></MetaDataObject>', encoding='utf-8')
                    output = root / 'Owner' / 'Forms' / 'Form' / 'Ext' / 'Form.xml'
                    definition = root / 'form.json'
                    definition.write_text(json.dumps({'attributes': [{'name': 'Object', 'type': f'{invalid}.Owner', 'main': True}]}), encoding='utf-8')
                    bad = run(port, '1c-form-compile', 'form-compile', '-JsonPath', definition, '-OutputPath', output)
                    self.assertNotEqual(bad.returncode, 0, bad.stdout + bad.stderr)
                    self.assertFalse(output.exists())
                    definition.write_text(json.dumps({'attributes': [{'name': 'Object', 'type': f'{valid}.Owner', 'main': True}]}), encoding='utf-8')
                    good = run(port, '1c-form-compile', 'form-compile', '-JsonPath', definition, '-OutputPath', output)
                    self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
                    ok = run(port, '1c-form-validate', 'form-validate', '-FormPath', output)
                    self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
                    output.write_text(output.read_text(encoding='utf-8-sig').replace(f'cfg:{valid}.Owner', f'cfg:{invalid}.Owner'), encoding='utf-8-sig')
                    wrong = run(port, '1c-form-validate', 'form-validate', '-FormPath', output)
                    self.assertNotEqual(wrong.returncode, 0, wrong.stdout + wrong.stderr)

    def test_configuration_and_secondary_attributes_remain_valid(self):
        for port in ('pwsh', 'python'):
            for external in (False, True):
                with self.subTest(port=port, external=external), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    output = root / 'Owner' / 'Forms' / 'Form' / 'Ext' / 'Form.xml'
                    (root / ('Owner.xml' if external else 'Configuration.xml')).write_text(
                        '<MetaDataObject version="2.17"><ExternalDataProcessor uuid="x"/></MetaDataObject>' if external
                        else '<MetaDataObject version="2.17"><Configuration uuid="x"/></MetaDataObject>', encoding='utf-8')
                    definition = root / 'form.json'
                    attrs = [{'name': 'Object', 'type': 'DataProcessorObject.Other', 'main': not external}]
                    definition.write_text(json.dumps({'attributes': attrs}), encoding='utf-8')
                    compiled = run(port, '1c-form-compile', 'form-compile', '-JsonPath', definition, '-OutputPath', output)
                    self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                    checked = run(port, '1c-form-validate', 'form-validate', '-FormPath', output)
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == '__main__':
    unittest.main()
