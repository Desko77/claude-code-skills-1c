"""Check storage and binary type serialization in both metadata tools and ports."""
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
ATTRS = [
    {'name': 'StorageEn', 'type': 'ValueStorage'},
    {'name': 'StorageRu', 'type': 'ХранилищеЗначения'},
    {'name': 'StorageXml', 'type': 'v8:ValueStorage'},
    {'name': 'BinaryXml', 'type': 'xs:base64Binary'},
    {'name': 'Ordinary', 'type': 'String(12)'},
    {'name': 'Composite', 'type': 'ValueStorage + Boolean'},
]
EXPECTED = {'StorageEn': ['v8:ValueStorage'], 'StorageRu': ['v8:ValueStorage'],
            'StorageXml': ['v8:ValueStorage'], 'BinaryXml': ['xs:base64Binary'],
            'Ordinary': ['xs:string'], 'Composite': ['v8:ValueStorage', 'xs:boolean']}


def invoke(port, skill, args):
    script = ROOT / 'skills' / f'1c-meta-{skill}' / 'scripts' / f'meta-{skill}.{port}'
    command = ['pwsh', '-NoProfile', '-File', str(script)] if port == 'ps1' else [sys.executable, str(script)]
    return subprocess.run(command + list(map(str, args)), capture_output=True, text=True, encoding='utf-8', errors='replace')


def read_types(path):
    root = ET.parse(path).getroot()
    result = {}
    for attribute in root.findall('.//md:Attribute', NS):
        name = attribute.findtext('md:Properties/md:Name', namespaces=NS)
        if name in EXPECTED:
            result[name] = [node.text for node in attribute.findall('md:Properties/md:Type/v8:Type', NS)]
    return result


class StorageTypes(unittest.TestCase):
    def test_decompile_compile_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            definition = base / 'definition.json'
            definition.write_text(json.dumps({'type': 'Catalog', 'name': 'StorageCase', 'attributes': ATTRS}, ensure_ascii=False), encoding='utf-8')
            result = invoke('py', 'compile', ['-JsonPath', definition, '-OutputDir', base / 'initial'])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            original = base / 'initial/Catalogs/StorageCase.xml'
            for decompiler in ('py', 'ps1'):
                draft = base / f'{decompiler}.json'
                result = invoke(decompiler, 'decompile', ['-ObjectPath', original, '-OutputPath', draft])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for compiler in ('py', 'ps1'):
                    target = base / f'{decompiler}-{compiler}'
                    result = invoke(compiler, 'compile', ['-JsonPath', draft, '-OutputDir', target])
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(read_types(target / 'Catalogs/StorageCase.xml'), EXPECTED)

    def test_compile_and_edit(self):
        for port in ('py', 'ps1'):
            for skill in ('compile', 'edit'):
                with self.subTest(port=port, skill=skill), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp) / 'src'
                    shutil.copytree(FIXTURE, base)
                    input_path = Path(tmp) / 'definition.json'
                    if skill == 'compile':
                        input_path.write_text(json.dumps({'type': 'Catalog', 'name': 'StorageCase', 'attributes': ATTRS}, ensure_ascii=False), encoding='utf-8')
                        args = ['-JsonPath', input_path, '-OutputDir', base]
                        output = base / 'Catalogs/StorageCase.xml'
                    else:
                        input_path.write_text(json.dumps({'add': {'attributes': ATTRS}}, ensure_ascii=False), encoding='utf-8')
                        output = base / 'Catalogs/Контрагенты.xml'
                        args = ['-DefinitionFile', input_path, '-ObjectPath', output, '-NoValidate']
                    result = invoke(port, skill, args)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(read_types(output), EXPECTED)


if __name__ == '__main__':
    unittest.main()
