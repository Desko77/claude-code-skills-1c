#!/usr/bin/env node
// Гард хуков следа проверок: тесты tests/hooks проходят под раннером tests/hooks/run.mjs
// (писатель applied/failed, контекст сессии, снятие release, сквозная совместимость
// с tools/evidence.py). Выход как у раннера: 0 все тесты прошли, 1 провал или ошибка
// запуска.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

const r = spawnSync(process.execPath, [join(ROOT, 'tests', 'hooks', 'run.mjs')], { stdio: 'inherit' });
if (r.error) {
  console.error(`Не удалось запустить node: ${r.error.message}`);
  process.exit(1);
}
process.exit(r.status ?? 1);
