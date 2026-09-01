#!/usr/bin/env node
// Инвариант: чистая логика поведенческого раннера работает без вызовов агента.
//
// Под проверкой четыре места, где ошибка не видна по зеленому прогону: ответ берется
// из трейса, а не из сырого потока; вызов на локальной переменной не считается модулем
// БСП; сбойный повтор не исчезает при сведении по большинству; неполная фаза не
// засчитывается ни с одной из двух сторон. Агент для этих проверок не нужен.
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
