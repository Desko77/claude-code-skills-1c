"""Ensure explicit and default type lengths agree between Python and PowerShell 7."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/skills/cases/meta-edit/snapshots/add-attribute'
NS = {'md': 'http://v8.1c.ru/8.3/MDClasses', 'v8': 'http://v8.1c.ru/8.1/data/core'}


def compile_definition(port, base, definition):
    path = base.parent / 'definition.json'
    path.write_text(json.dumps(definition, ensure_ascii=False), encoding='utf-8')
    script = ROOT / 'skills/1c-meta-compile/scripts' / f'meta-compile.{port}'
    command = ['pwsh', '-NoProfile', '-File', str(script)] if port == 'ps1' else [sys.executable, str(script)]
    result = subprocess.run(command + ['-JsonPath', str(path), '-OutputDir', str(base)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return base / ('Constants' if definition['type'] == 'Constant' else 'Catalogs') / (definition['name'] + '.xml')


def qualifiers(element):
    return (element.findtext('v8:StringQualifiers/v8:Length', namespaces=NS),
            element.findtext('v8:NumberQualifiers/v8:Digits', namespaces=NS),
            element.findtext('v8:NumberQualifiers/v8:FractionDigits', namespaces=NS))


class MetadataLengths(unittest.TestCase):
    def test_constant_lengths(self):
        cases = [
            ({'valueType': 'string'}, ('10', None, None)),
            ({'valueType': 'String'}, ('10', None, None)),
            ({'valueType': 'Number'}, (None, '10', '0')),
            ({'valueType': 'String', 'length': 25}, ('25', None, None)),
            ({'valueType': 'string', 'length': 25}, ('25', None, None)),
            ({'valueType': 'Number', 'length': 13, 'precision': 2}, (None, '13', '2')),
        ]
        for port in ('py', 'ps1'):
            for index, (settings, expected) in enumerate(cases):
                with self.subTest(port=port, settings=settings), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp) / 'src'
                    shutil.copytree(FIXTURE, base)
                    path = compile_definition(port, base, {'type': 'Constant', 'name': f'Constant{index}', **settings})
                    node = ET.parse(path).getroot().find('.//md:Constant/md:Properties/md:Type', NS)
                    self.assertIsNotNone(node)
                    self.assertEqual(qualifiers(node), expected)

    def test_attribute_lengths(self):
        attributes = [{'name': 'Text', 'type': 'String'}, {'name': 'Num', 'type': 'Number'},
                      {'name': 'Explicit', 'type': 'String', 'length': 25}]
        expected = {'Text': ('10', None, None), 'Num': (None, '10', '0'), 'Explicit': ('25', None, None)}
        for port in ('py', 'ps1'):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp) / 'src'
                shutil.copytree(FIXTURE, base)
                path = compile_definition(port, base, {'type': 'Catalog', 'name': 'LengthCase', 'attributes': attributes})
                root = ET.parse(path).getroot()
                actual = {}
                for attr in root.findall('.//md:Attribute/md:Properties', NS):
                    actual[attr.findtext('md:Name', namespaces=NS)] = qualifiers(attr.find('md:Type', NS))
                self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
