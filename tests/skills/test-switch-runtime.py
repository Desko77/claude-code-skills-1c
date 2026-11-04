"""Both runtime switchers must recognize current and legacy PowerShell commands."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('switch', ROOT / 'scripts/switch.py')
switch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switch)

for executable in ('pwsh', 'pwsh.exe', 'powershell.exe'):
    command = f'{executable} -NoProfile -File skills/demo/scripts/demo.ps1'
    python_command, changed = switch.switch_runtime_content(command, 'python')
    assert changed and python_command == 'python skills/demo/scripts/demo.py', executable
    powershell_command, changed = switch.switch_runtime_content(python_command, 'powershell')
    assert changed and powershell_command == 'pwsh -NoProfile -File skills/demo/scripts/demo.ps1'

with tempfile.TemporaryDirectory(prefix='switch-runtime-') as temporary:
    root = Path(temporary)
    (root / 'scripts').mkdir()
    skill = root / '.claude/skills/demo'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('pwsh -NoProfile -File .claude/skills/demo/run.ps1\n', encoding='utf-8')
    shutil.copy2(ROOT / 'scripts/switch-to-python.py', root / 'scripts')
    subprocess.run([sys.executable, str(root / 'scripts/switch-to-python.py')], check=True, capture_output=True)
    assert (skill / 'SKILL.md').read_text(encoding='utf-8') == 'python .claude/skills/demo/run.py\n'
print('Runtime switchers support pwsh and legacy PowerShell.')
