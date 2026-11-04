"""Проверяет состав конвертации и исключение служебного кеша Python."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('convert', ROOT / 'tools/convert_from_claude.py')
convert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert)


class ConversionTest(unittest.TestCase):
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
