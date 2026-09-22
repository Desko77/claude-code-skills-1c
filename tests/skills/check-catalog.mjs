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
//   4. сгенерированные INDEX.md, references/detectors.md и секции правил совпадают с карточками
//      (gen_catalog_index --check);
//   5. матрица детекторов: детекторы из словаря спецификации, уровни совпадают со словарем,
//      правило lint названо идентификатором карточки, при "чтение" в EDT есть обоснование;
//   6. пороги покрытия: 100% Critical с детерминированным детектором в EDT либо с обоснованием
//      чтения, не менее 50% всех карточек с детерминированным детектором хотя бы в одной среде
//      (сравнение по счетчикам, округление - только печать). Детектор bsl_validate:<ИД>
//      детерминирован только при <ИД> в реестре реализованных правил lint
//      skills/1c-bsl-validate/scripts/catalog-rules.json; пока реестр пуст, недобор порога
//      печатается предупреждением и не проваливает проверку (переходное правило спецификации);
//   7. гейтовый конфиг assets/bsl-ls-gate.json: состав диагностик совпадает с code_review-ссылками
//      карточек в обе стороны, важность диагностики равна важности карточки без конфликтов.
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

// Словарь детекторов спецификации (docs/1c-defect-catalog-spec.md, раздел Детекторы).
const DETECTOR_DICT = {
  EDT: {
    'code_review:*': 'static',
    get_project_errors: 'semantic',
    validate_query: 'semantic',
    validate_for_export: 'semantic',
    security_audit: 'semantic',
    detect_query_anti_patterns: 'static',
    ask_1c_ai: 'llm',
    'чтение': 'read',
  },
  'Конфигуратор': {
    syntaxcheck: 'static',
    'bsl_validate:*': 'static',
    query_validate: 'static',
    meta_validate: 'static',
    role_validate: 'static',
    form_validate: 'static',
    'чтение': 'read',
  },
};
const DETERMINISTIC = new Set(['semantic', 'static']);
const GATE_CONFIG = join(ROOT, 'skills/1c-code-review/assets/bsl-ls-gate.json');
const LINT_REGISTRY = join(ROOT, 'skills/1c-bsl-validate/scripts/catalog-rules.json');
const SEVERITY_MAP = { Critical: 'CRITICAL', Major: 'MAJOR', Minor: 'MINOR' };

const problems = [];
let cardsChecked = 0;
let fixturesChecked = 0;

// Разбор карточки: заголовок первого уровня и разделы второго уровня по порядку.
function parseCard(file) {
  // Концы строк приводятся к LF: рабочая копия по .gitattributes может быть CRLF,
  // а разбор заголовков и разделов идет построчно.
  const text = readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
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

  // Матрица детекторов: таблица "Среда | Детектор | Уровень" + обоснование чтения.
  const detectors = [];
  for (const line of fields['Детекторы'].split('\n')) {
    const stripped = line.trim();
    if (!stripped.startsWith('|')) continue;
    const cells = stripped.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    if (cells.length !== 3 || !cells[0] || /^[-\s]*$/.test(cells[0])) continue;
    if (cells.join(',') === 'Среда,Детектор,Уровень') continue;
    detectors.push({ env: cells[0], detector: cells[1], level: cells[2] });
  }
  if (detectors.length === 0) {
    problems.push(`${id}: таблица детекторов пуста`);
  }
  const justification =
    (fields['Детекторы'].match(/^Обоснование чтения:\s*(.+)$/m) || [])[1] || '';
  for (const { env, detector, level } of detectors) {
    const dict = DETECTOR_DICT[env];
    if (!dict) {
      problems.push(`${id}: среда "${env}" вне словаря (EDT, Конфигуратор)`);
      continue;
    }
    let expected = dict[detector];
    if (expected === undefined) {
      const family = detector.split(':')[0];
      expected = detector.includes(':') ? dict[`${family}:*`] : undefined;
    }
    if (expected === undefined) {
      problems.push(`${id}: детектор "${detector}" в среде ${env} вне словаря`);
    } else if (level !== expected) {
      problems.push(`${id}: уровень "${level}" у детектора ${detector} не совпадает со словарем (${expected})`);
    }
    if (detector.startsWith('bsl_validate:') && detector !== `bsl_validate:${id}`) {
      problems.push(`${id}: правило lint "${detector}" не названо идентификатором карточки`);
    }
  }
  const envs = new Set(detectors.map((d) => d.env));
  if (!envs.has('EDT') || !envs.has('Конфигуратор')) {
    problems.push(`${id}: в матрице нет обеих сред`);
  }
  const hasEdtRead = detectors.some((d) => d.env === 'EDT' && d.detector === 'чтение');
  if (hasEdtRead && !justification) {
    problems.push(`${id}: чтение в среде EDT без строки "Обоснование чтения:"`);
  }
  return { id, fixtureType, severity: fields['Важность'], detectors, justification };
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
    const lines = readFileSync(join(dir, defectFile), 'utf8').replace(/\r\n/g, '\n').split('\n');
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
  if (manifest.type === 'evidence') {
    // Спецификация задает следу единственное имя evidence.json; иное имя файла или состав
    // files - расхождение. Файл существует, разбирается как JSON и несет kind; полная
    // проверка формата следа - валидатор спринта 5, здесь только структура.
    const files = manifest.files || [];
    if (files.length !== 1 || files[0] !== 'evidence.json') {
      problems.push(`${card.id}: у фикстуры evidence files должен быть ["evidence.json"], задано ${JSON.stringify(files)}`);
    }
    if (!existsSync(join(dir, 'evidence.json'))) {
      problems.push(`${card.id}: файла следа нет: evidence.json`);
    } else {
      try {
        const trace = JSON.parse(readFileSync(join(dir, 'evidence.json'), 'utf8'));
        if (typeof trace.kind !== 'string' || !trace.kind) {
          problems.push(`${card.id}: файл следа evidence.json без поля kind`);
        }
      } catch (e) {
        problems.push(`${card.id}: файл следа evidence.json не разбирается как JSON: ${e.message}`);
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

// 6. Пороги покрытия детерминированными детекторами.
// Детектор bsl_validate:<ИД> детерминирован только при <ИД> в реестре реализованных
// правил lint (skills/1c-bsl-validate/scripts/catalog-rules.json); каждая запись реестра
// обязана называть карточку с этим детектором.
const lintCards = cards.filter((c) =>
  c.detectors.some((d) => d.detector.startsWith('bsl_validate:')));
const lintCardIds = new Set(lintCards.map((c) => c.id));
let lintRegistry = null;
try {
  const parsed = JSON.parse(readFileSync(LINT_REGISTRY, 'utf8'));
  if (!Array.isArray(parsed) || parsed.length === 0 || parsed.some((r) => typeof r !== 'object' || !r.id || !r.kind)) {
    problems.push('реестр lint-правил: ожидался массив объектов с полями id и kind');
  } else {
    lintRegistry = new Set(parsed.map((r) => r.id));
    if (lintRegistry.size !== parsed.length) {
      problems.push('реестр lint-правил: повтор идентификатора');
    }
    for (const rule of parsed) {
      if (!['regex', 'query-regex', 'structure'].includes(rule.kind)) {
        problems.push(`реестр lint-правил: ${rule.id} с kind ${rule.kind} вне словаря`);
      }
      if (rule.kind === 'structure' && !rule.check) {
        problems.push(`реестр lint-правил: ${rule.id} без check`);
      }
      if (rule.kind !== 'structure' && !rule.pattern) {
        problems.push(`реестр lint-правил: ${rule.id} без pattern`);
      }
      if (!lintCardIds.has(rule.id)) {
        problems.push(`реестр lint-правил: ${rule.id} без карточки с детектором bsl_validate`);
      }
    }
  }
} catch (e) {
  problems.push(`реестр lint-правил ${LINT_REGISTRY} не читается как JSON: ${e.message}`);
}
const isDeterministic = (d) => {
  if (!DETERMINISTIC.has(d.level)) return false;
  if (!d.detector.startsWith('bsl_validate:')) return true;
  return lintRegistry !== null && lintRegistry.has(d.detector.slice('bsl_validate:'.length));
};
const deterministicIn = (card, env = null) =>
  card.detectors.some((d) => isDeterministic(d) && (!env || d.env === env));
const critical = cards.filter((c) => c.severity === 'Critical');
const criticalUncovered = critical.filter(
  (c) => !deterministicIn(c, 'EDT') && !c.justification);
if (criticalUncovered.length) {
  problems.push(
    `порог Critical: без детерминированного детектора в EDT и без обоснования чтения: ${criticalUncovered.map((c) => c.id).join(', ')}`);
}
const coveredTotal = cards.filter((c) => deterministicIn(c));
const coveragePercent = Math.round((100 * coveredTotal.length) / cards.length);
if (coveredTotal.length * 2 < cards.length) {
  const implemented =
    lintRegistry === null ? 0 : [...lintRegistry].filter((id) => lintCardIds.has(id)).length;
  if (implemented > 0) {
    const unread = cards.filter((c) => !deterministicIn(c)).map((c) => c.id);
    problems.push(
      `порог покрытия: детерминированный детектор хотя бы в одной среде у ${coveredTotal.length} из ${cards.length} (${coveragePercent}%), ниже 50%. Без детектора: ${unread.join(', ')}`);
  } else {
    // Переходное правило спецификации (раздел Детекторы): пока реестр lint-правил пуст,
    // недобор порога не проваливает гард - печатается предупреждение.
    console.log(
      `порог покрытия не достигнут: lint-правила не реализованы (реестр: ${implemented} из ${lintCards.length});` +
        ` детерминированный детектор хотя бы в одной среде у ${coveredTotal.length} из ${cards.length} (${coveragePercent}%)`);
  }
}

// 7. Гейтовый конфиг: состав диагностик и важности совпадают с карточками в обе стороны.
let gate = null;
try {
  gate = JSON.parse(readFileSync(GATE_CONFIG, 'utf8'));
} catch (e) {
  problems.push(`гейтовый конфиг ${GATE_CONFIG} не читается как JSON: ${e.message}`);
}
if (gate) {
  const parameters = (gate.diagnostics && gate.diagnostics.parameters) || {};
  const metadata = (gate.diagnostics && gate.diagnostics.metadata) || {};
  // код диагностики -> важность карточки; конфликт важностей у одной диагностики - ошибка
  const cardCodes = new Map();
  for (const card of cards) {
    for (const d of card.detectors) {
      if (!d.detector.startsWith('code_review:')) continue;
      const code = d.detector.slice('code_review:'.length);
      const prev = cardCodes.get(code);
      if (prev && prev !== card.severity) {
        problems.push(`${card.id}: диагностика ${code} у карточек с разной важностью (${prev} и ${card.severity})`);
      }
      cardCodes.set(code, card.severity);
    }
  }
  const inCards = new Set(cardCodes.keys());
  const inConfig = new Set(Object.keys(parameters));
  for (const code of inCards) {
    if (!inConfig.has(code)) problems.push(`гейтовый конфиг: диагностика ${code} есть в карточках, нет в конфиге`);
  }
  for (const code of inConfig) {
    if (!inCards.has(code)) problems.push(`гейтовый конфиг: диагностика ${code} есть в конфиге, нет в карточках`);
    if (parameters[code] !== true) problems.push(`гейтовый конфиг: диагностика ${code} не включена (parameters)`);
  }
  for (const [code, severity] of cardCodes) {
    const expected = SEVERITY_MAP[severity];
    const actual = metadata[code] && metadata[code].severity;
    if (actual !== expected) {
      problems.push(`гейтовый конфиг: важность ${code} в конфиге "${actual}", по карточке ожидается "${expected}"`);
    }
  }
  for (const code of Object.keys(metadata)) {
    if (!inCards.has(code)) problems.push(`гейтовый конфиг: metadata для ${code}, диагностики нет в карточках`);
  }
}

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
