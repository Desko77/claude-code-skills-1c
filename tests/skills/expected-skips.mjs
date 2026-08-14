#!/usr/bin/env node
// Сколько кейсов ДОЛЖНО быть пропущено на этой ОС и этом порте.
//
// «skipped» в прогоне — норма, а не падение: часть кейсов гейтится по ОС, по порту или по
// наличию внешней выгрузки. Но само число ни о чём не говорит, пока не с чем сверить, а
// запоминать его нельзя — оно растёт с набором кейсов. Отсюда этот скрипт: он считает
// ожидаемое значение по тем же правилам, что и раннер, и его надо сверять с `Skipped: N`.
//
// Совпало — норма. Разошлось — разбираться: появился новый источник скипа либо кейс
// скипается не по той причине, что заявлена.
//
// Запуск: node tests/skills/expected-skips.mjs [--runtime python] [--list]
import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const CASES = join(HERE, 'cases');

const argv = process.argv.slice(2);
const runtime = argv.includes('--runtime') ? argv[argv.indexOf('--runtime') + 1] : 'powershell';
const listMode = argv.includes('--list');
const os = process.platform;

const reasons = { external: [], runtimeOnly: [], osOnly: [] };

for (const skill of readdirSync(CASES)) {
  const dir = join(CASES, skill);
  if (!statSync(dir).isDirectory()) continue;
  const skillCfgPath = join(dir, '_skill.json');
  const skillCfg = existsSync(skillCfgPath) ? JSON.parse(readFileSync(skillCfgPath, 'utf8')) : {};

  for (const file of readdirSync(dir)) {
    if (!file.endsWith('.json') || file === '_skill.json') continue;
    const id = `${skill}/${file.replace(/\.json$/, '')}`;
    const c = JSON.parse(readFileSync(join(dir, file), 'utf8'));

    // Порядок совпадает с раннером: сначала ОС, потом порт, потом фикстура.
    if (c.osOnly && ![].concat(c.osOnly).includes(os)) { reasons.osOnly.push(id); continue; }
    if (c.runtimeOnly && c.runtimeOnly !== runtime) { reasons.runtimeOnly.push(id); continue; }
    const setup = String(c.setup || skillCfg.setup || '');
    if (setup.startsWith('external:') && !existsSync(setup.slice('external:'.length))) {
      reasons.external.push(id);
    }
  }
}

const total = reasons.external.length + reasons.runtimeOnly.length + reasons.osOnly.length;

if (listMode) {
  for (const [key, ids] of Object.entries(reasons)) {
    if (!ids.length) continue;
    console.log(`\n${key} (${ids.length}):`);
    for (const id of ids) console.log(`  ${id}`);
  }
  console.log('');
}

console.log(
  `Ожидается пропущенных: ${total}  [${os}, runtime: ${runtime}]  ` +
    `= external ${reasons.external.length} + runtimeOnly ${reasons.runtimeOnly.length} + osOnly ${reasons.osOnly.length}`,
);
console.log('Сверить с "Skipped: N" из прогона runner.mjs с теми же --runtime.');
