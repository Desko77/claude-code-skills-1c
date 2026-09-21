#!/usr/bin/env node
// Гард инструментов tools/: unit-тесты tests/tools проходят под раннером tests/tools/run_tests.py
// (пока покрыт установщик install_home.py: слияние, конфликты, резервные копии, --check).
// Выход как у раннера: 0 все тесты прошли, 1 провал или ошибка запуска.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

const r = spawnSync(PY, ['-X', 'utf8', join(ROOT, 'tests', 'tools', 'run_tests.py')], { stdio: 'inherit' });
if (r.error) {
  console.error(`Не удалось запустить ${PY}: ${r.error.message}`);
  process.exit(1);
}
process.exit(r.status ?? 1);
