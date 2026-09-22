#!/usr/bin/env node
// Прогон тестов хуков набора: каждый *.test.mjs из этого каталога запускается отдельным
// процессом (падение одного файла не останавливает остальные). Сквозной тест вызывает
// Python-инструменты tools/ - требуется python в PATH и git.
// Запуск: node tests/hooks/run.mjs
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));

const files = readdirSync(HERE).filter((n) => n.endsWith('.test.mjs')).sort();
let failed = 0;
let totalTests = 0;
for (const file of files) {
  console.log(`\n${'='.repeat(70)}\n${file}\n${'='.repeat(70)}`);
  const r = spawnSync(process.execPath, [join(HERE, file)], { encoding: 'utf8' });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr);
  // Итог harness: "все N прошли" либо "M из N провалено".
  const summary = /(все (\d+) прошли|(\d+) из (\d+) провалено)/.exec(r.stdout || '');
  if (summary) totalTests += Number(summary[2] || summary[4]);
  if (r.status !== 0) failed++;
}

console.log(`\n${'='.repeat(70)}`);
console.log(failed === 0
  ? `OK - тесты хуков прошли: ${files.length} файлов, проверок ${totalTests}.`
  : `${failed} из ${files.length} тест-файлов упали.`);
process.exit(failed ? 1 : 0);
