#!/usr/bin/env node
// Прогон всех гардов-инвариантов одной командой. Гарды не входят в snapshot-прогон runner.mjs:
// они проверяют не вывод навыков, а инварианты исходников. Выход 1, если упал хотя бы один.
// Запуск: node tests/skills/check-all.mjs
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));

const GUARDS = [
  ['check-enum-drift.mjs', 'allowlist-и перечислений: meta-compile ↔ meta-validate ↔ meta-edit'],
  ['check-uuid-invariant.mjs', 'сохранение uuid объекта и сущностей при правке'],
  ['check-inline-drift.mjs', 'общие inline-реализации: копии совпадают с эталонами'],
  ['check-shared-blocks.mjs', 'переносимые блоки: совпадают с эталоном и вызываются'],
  ['check-type-maps.mjs', 'карты типов метаданных: согласованы со спецификацией'],
  ['check-format-versions.mjs', 'проверенный диапазон версий формата: согласован со спецификацией'],
  ['check-api-validator.mjs', 'линтер API-справочников: три раскладки выгрузки, отрицания в обе стороны'],
  ['check-eval-runner.mjs', 'поведенческий раннер: чистая логика разбора, сведения и сверки вызовов'],
];

let failed = 0;
for (const [script, title] of GUARDS) {
  console.log(`\n${'='.repeat(70)}\n${script} — ${title}\n${'='.repeat(70)}`);
  const r = spawnSync(process.execPath, [join(HERE, script)], { stdio: 'inherit' });
  if (r.status !== 0) failed++;
}

console.log(`\n${'='.repeat(70)}`);
console.log(failed === 0
  ? `OK — все гарды прошли (${GUARDS.length}).`
  : `${failed} из ${GUARDS.length} гардов упали.`);
process.exit(failed ? 1 : 0);
