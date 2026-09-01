#!/usr/bin/env node
// Инвариант: чистая логика поведенческого раннера работает без вызовов агента.
//
// На этом раннере ревью нашло четыре дефекта, и все четыре жили в чистой логике:
// ответ брался из сырого потока вместо трейса, вызов на локальной переменной считался
// модулем БСП, сбойный повтор исчезал при сведении по большинству, а проверка неполной
// фазы стояла только у одной из двух. Агент для их проверки не нужен, а без проверки
// они возвращаются.
//
// Выход 1 при нарушении. Запуск: node tests/skills/check-eval-runner.mjs
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

try {
  const out = execFileSync(PY, [join(ROOT, 'tools', 'run_skill_evals.py'), '--selftest'],
    { encoding: 'utf8', stdio: 'pipe' });
  process.stdout.write(out);
  console.log('Раннер прогонов: чистая логика проверена');
} catch (err) {
  process.stdout.write(err.stdout || '');
  process.stderr.write(err.stderr || '');
  console.error('Раннер прогонов: самопроверка не прошла');
  process.exit(1);
}
