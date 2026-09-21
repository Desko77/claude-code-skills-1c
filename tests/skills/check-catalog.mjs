#!/usr/bin/env node
// Каталог дефектов: карточки, реестр идентификаторов, фикстуры и совпадение сгенерированного.
//
// Каталог - данные: карточки skills/1c-code-review/references/catalog/<ID>.md с фиксированным
// набором разделов, реестр ledger.json и типизированные фикстуры tests/catalog/<ID>/. Проверяется:
//   1. у каждой карточки все разделы в требуемом порядке, законная форма непуста и с кодом;
//   2. идентификатор выдан реестром (issued), не выведен (retired) и уникален; состав карточок
//      и issued совпадает в обе стороны;
//   3. фикстура существует, ее тип совпадает с карточкой, файлы типа на месте, ожидаемые строки
//      в границах defect.bsl;
//   4. сгенерированные INDEX.md и секции правил совпадают с карточками (gen_catalog_index --check).
//
// Запуск:  node tests/skills/check-catalog.mjs
// Выход 1 при расхождении.
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..');
const CATALOG = join(ROOT, 'skills/1c-code-review/references/catalog');
const FIXTURES = join(ROOT, 'tests/catalog');
const GENERATOR = join(ROOT, 'tools/gen_catalog_index.py');

const SECTIONS = [
  'Идентификатор и группа',
  'Важность',
  'Триггер',
  'Почему дефект',
  'Законная форма',
  'Как чинить',
  'Детекторы',
  'Архетипы правки',
  'Фикстура',
  'Источник',
];
const SEVERITIES = new Set(['Critical', 'Major', 'Minor']);
const TYPE_FILES = {
  'bsl-pair': ['clean.bsl', 'defect.bsl'],
  diff: ['before.bsl', 'after.bsl'],
};

const problems = [];
let cardsChecked = 0;
let fixturesChecked = 0;

// Разбор карточки: заголовок первого уровня и разделы второго уровня по порядку.
function parseCard(file) {
  const text = readFileSync(file, 'utf8');
  const first = text.split('\n', 1)[0];
  const heading = first.match(/^# ([A-Z]+-\d{2})\. (.+)$/);
  if (!heading) {
    problems.push(`${file}: заголовок не вида '# <ИД>. <Заголовок>'`);
    return null;
  }
  const id = heading[1];
  if (id !== basenameNoExt(file)) {
    problems.push(`${file}: идентификатор ${id} не совпадает с именем файла`);
  }
  const chunks = text.split(/^## /m).slice(1);
  const names = [];
  const fields = {};
  for (const chunk of chunks) {
    const pos = chunk.indexOf('\n');
    const name = (pos < 0 ? chunk : chunk.slice(0, pos)).trim();
    names.push(name);
    fields[name] = (pos < 0 ? '' : chunk.slice(pos + 1)).trim();
  }
  const expected = SECTIONS.join(', ');
  if (names.join(',') !== SECTIONS.join(',')) {
    problems.push(`${id}: разделы [${names.join(', ')}] не совпадают с порядком [${expected}]`);
    return null;
  }
  for (const name of SECTIONS) {
    if (!fields[name]) {
      problems.push(`${id}: раздел "${name}" пуст`);
    }
  }
  if (!SEVERITIES.has(fields['Важность'])) {
    problems.push(`${id}: важность "${fields['Важность']}" вне шкалы Critical/Major/Minor`);
  }
  if (!fields['Законная форма'].includes('```')) {
    problems.push(`${id}: законная форма без блока кода`);
  }
  const fixtureType = (fields['Фикстура'].match(/^Тип: `([a-z-]+)`$/m) || [])[1];
  if (!fixtureType) {
    problems.push(`${id}: в разделе Фикстура нет строки "Тип: ..."`);
  }
  const fixturePath = (fields['Фикстура'].match(/^Путь: `([^`]+)`$/m) || [])[1];
  if (fixturePath !== `tests/catalog/${id}/`) {
    problems.push(`${id}: путь фикстуры "${fixturePath}" не указывает на tests/catalog/${id}/`);
  }
  return { id, fixtureType };
}

function basenameNoExt(file) {
  const base = file.split(/[\\/]/).pop();
  return base.replace(/\.[^.]+$/, '');
}

function checkFixture(card) {
  const dir = join(FIXTURES, card.id);
  if (!existsSync(dir)) {
    problems.push(`${card.id}: каталога фикстуры нет: ${dir}`);
    return;
  }
  const manifestFile = join(dir, 'manifest.json');
  if (!existsSync(manifestFile)) {
    problems.push(`${card.id}: нет manifest.json`);
    return;
  }
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestFile, 'utf8'));
  } catch (e) {
    problems.push(`${card.id}: manifest.json не разбирается: ${e.message}`);
    return;
  }
  if (manifest.id !== card.id) {
    problems.push(`${card.id}: id манифеста "${manifest.id}" не совпадает с карточкой`);
  }
  if (manifest.type !== card.fixtureType) {
    problems.push(`${card.id}: тип манифеста "${manifest.type}" не совпадает с типом карточки "${card.fixtureType}"`);
    return;
  }
  for (const name of TYPE_FILES[manifest.type] || []) {
    if (!existsSync(join(dir, name))) {
      problems.push(`${card.id}: у фикстуры типа ${manifest.type} нет файла ${name}`);
    }
  }
  if (manifest.type === 'bsl-pair' || manifest.type === 'diff') {
    // У пары - defect.bsl, у diff - after.bsl: строки expected считаются по файлу с дефектом.
    const defectFile = manifest.type === 'diff' ? 'after.bsl' : 'defect.bsl';
    const lines = readFileSync(join(dir, defectFile), 'utf8').split('\n');
    if (!Array.isArray(manifest.expected) || manifest.expected.length === 0) {
      problems.push(`${card.id}: у фикстуры ${manifest.type} пуст список expected`);
    } else {
      for (const n of manifest.expected) {
        if (!Number.isInteger(n) || n < 1 || n > lines.length) {
          problems.push(`${card.id}: expected ${n} вне границ ${defectFile} (${lines.length} строк)`);
        }
      }
    }
  }
  if (manifest.type === 'project-tree') {
    for (const rel of manifest.files || []) {
      if (!existsSync(join(dir, ...rel.split('/')))) {
        problems.push(`${card.id}: файла из манифеста нет: ${rel}`);
      }
    }
  }
  fixturesChecked++;
}

// 1-3. Карточки, реестр, фикстуры.
const files = readdirSync(CATALOG).filter((f) => f.endsWith('.md') && f !== 'INDEX.md').sort();
const cards = [];
for (const f of files) {
  const card = parseCard(join(CATALOG, f));
  if (card) cards.push(card);
}
cardsChecked = cards.length;

const seen = new Set();
for (const card of cards) {
  if (seen.has(card.id)) problems.push(`${card.id}: повтор идентификатора в каталоге`);
  seen.add(card.id);
}

const ledger = JSON.parse(readFileSync(join(CATALOG, 'ledger.json'), 'utf8'));
const issued = ledger.issued.map((e) => e.id);
const retired = new Set((ledger.retired || []).map((e) => e.id));
const issuedSeen = new Set();
for (const id of issued) {
  if (issuedSeen.has(id)) problems.push(`${id}: повтор в ledger.issued`);
  issuedSeen.add(id);
  if (retired.has(id)) problems.push(`${id}: числится и в issued, и в retired`);
}
for (const card of cards) {
  if (!issuedSeen.has(card.id)) problems.push(`${card.id}: карточка без записи в ledger.issued`);
  if (retired.has(card.id)) problems.push(`${card.id}: карточка выведена из каталога (retired)`);
}
for (const id of issuedSeen) {
  if (!seen.has(id)) problems.push(`${id}: выдан реестром, карточки нет`);
}

for (const card of cards) checkFixture(card);

// 4. Сгенерированное совпадает с карточками.
const gen = spawnSync('python', ['-X', 'utf8', GENERATOR, '--check'], {
  encoding: 'utf8', cwd: ROOT,
});
if (gen.status !== 0) {
  problems.push(`генератор --check не прошел (код ${gen.status}): ${(gen.stdout || gen.stderr || '').trim()}`);
}

console.log(`Карточек проверено: ${cardsChecked}, фикстур: ${fixturesChecked}.`);
if (problems.length) {
  console.error(`\nРАСХОЖДЕНИЯ (${problems.length}):`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('OK - карточки, реестр и фикстуры каталога согласованы, генерация совпадает.');
