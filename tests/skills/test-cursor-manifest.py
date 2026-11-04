"""Проверяет состав конвертации и исключение служебного кеша Python."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('convert', ROOT / 'tools/convert_from_claude.py')
convert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert)


class ConversionTest(unittest.TestCase):
    def test_manifest_is_stable_with_local_binary_and_different_filename_case(self):
        spec = importlib.util.spec_from_file_location('manifest', ROOT / 'tools/check_cursor_manifest.py')
        manifest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manifest)
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for name in ('rules', 'docs', 'tools', 'skills/demo/scripts'):
                (root / name).mkdir(parents=True)
            (root / 'skills/demo/SKILL.md').write_text(
                '---\nname: demo\ndescription: demo\n---\n\nText\n', encoding='utf-8')
            entry = root / 'skills/demo/scripts/entry.py'
            entry.write_text('pass\n', encoding='utf-8')
            shutil.copy2(ROOT / 'tools/convert_from_claude.py', root / 'tools')
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', 'add', '-f', '--', '.'], cwd=root, check=True)
            manifest.ROOT = root
            expected = manifest.generated_manifest()
            entry.rename(entry.with_name('temporary.py'))
            entry.with_name('temporary.py').rename(entry.with_name('ENTRY.py'))
            (root / 'skills/demo/scripts/local.epf').write_bytes(b'local build')
            self.assertEqual(expected, manifest.generated_manifest())

    def test_skill_files_follow_source_but_python_cache_is_not_shipped(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            skill = root / 'src' / 'demo'
            scripts = skill / 'scripts'
            scripts.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: demo\ndescription: demo\n---\n\nText\n', encoding='utf-8')
            (scripts / 'one.py').write_text('pass\n', encoding='utf-8')
            (scripts / 'cached.pyc').write_bytes(b'cache')
            (scripts / '__pycache__').mkdir()
            (scripts / '__pycache__' / 'one.pyc').write_bytes(b'cache')
            target = root / 'dst'
            convert.convert_skill(skill, target, False)
            output = target / 'demo' / 'scripts'
            self.assertEqual({p.name for p in output.iterdir()}, {'one.py'})
            (scripts / 'one.py').unlink()
            (scripts / 'two.py').write_text('pass\n', encoding='utf-8')
            convert.convert_skill(skill, target, False)
            self.assertEqual({p.name for p in output.iterdir()}, {'two.py'})


if __name__ == '__main__':
    unittest.main()
