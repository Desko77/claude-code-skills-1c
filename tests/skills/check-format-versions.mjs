#!/usr/bin/env node
// Анти-дрейф проверенного диапазона версий формата выгрузки.
//
// Навыки автономны, и допустимый диапазон версий раньше был независимым литеральным списком в
// каждом валидаторе. Сверять его было не с чем — поэтому волна 2.21 прошла по четырём валидаторам
// и молча обошла пятый: form-validate остался на 2.17-2.20 и ругался на форму, которую сам же
// создавал через epf-init 2.21 → form-add (issue #63).
//
// Эталон границ — таблица «Лестница версий» из docs/1c-configuration-spec.md (§7.1). Берём
// документацию, а не отдельный JSON: тогда спека и код не расходятся молча.
//
// Держит три инварианта:
//   1. Границы диапазона одинаковы во всех навыках-потребителях и на обоих портах.
//   2. Дефолт -FormatVersion у *-init лежит внутри диапазона.
//   3. Верхняя граница = последняя ступень лестницы: добавили ступень в спеку и забыли поднять код
//      (или наоборот) - падаем здесь, а не на чужой выгрузке. Замеренность верхней ступени при этом
//      не требуется: версию мы поддерживаем по описанию возможностей раньше, чем достаем выгрузку
//      с нее (так вошли 2.18 и 2.21). Незамеренный верх - предупреждение, а не отказ.
//
// Запуск: node tests/skills/check-format-versions.mjs [--list]
// Выход 1 при ERROR.
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SKILLS = join(ROOT, 'skills');

// Кейсы и гарды адресуют навыки короткими именами, у нас они с префиксом 1c-.
// Часть навыков переименована при переносе - для них отдельные соответствия.
const SKILL_ALIASES = {
  'epf-init': '1c-epf-scaffold',
  'help-add': '1c-help-manage',
  'support-edit': '1c-support-state',
};
function skillDir(name) {
  for (const candidate of [SKILL_ALIASES[name], '1c-' + name, name]) {
    if (candidate && existsSync(join(SKILLS, candidate))) return join(SKILLS, candidate);
  }
  return join(SKILLS, '1c-' + name);
}
const SPEC = join(ROOT, 'docs', '1c-configuration-spec.md');

// Навыки, объявляющие проверенный диапазон. file — базовое имя скрипта в scripts/.
const RANGE_CONSUMERS = [
  { skill: 'cf-validate', file: 'cf-validate' },
  { skill: 'cfe-validate', file: 'cfe-validate' },
  { skill: 'epf-validate', file: 'epf-validate' },
  { skill: 'form-validate', file: 'form-validate' },
  { skill: 'meta-validate', file: 'meta-validate' },
  { skill: 'cf-init', file: 'cf-init', hasDefault: true },
  { skill: 'epf-init', file: 'init', hasDefault: true },
  { skill: 'erf-init', file: 'init', hasDefault: true },
];

// Навыки без параметра -FormatVersion: версия зашита прямо в шаблон заголовка. Диапазон они не
// объявляют, но и выпускать файл вне диапазона не должны - поэтому проверяется зашитое значение.
// Заодно ловится случай, когда шаблонов в скрипте несколько и они разъехались между собой.
const FIXED_VERSION_EMITTERS = [];

const errors = [];
const listMode = process.argv.includes('--list');

function read(path) {
  return existsSync(path) ? readFileSync(path, 'utf8') : null;
}

function rank(ver) {
  const m = /^(\d+)\.(\d+)$/.exec(ver || '');
  return m ? Number(m[1]) * 100 + Number(m[2]) : 0;
}

// ─── Эталон: лестница из спецификации ───────────────────────────────────────
// Строки вида: | 8.3.24 | `2.17` | да |
// Платформа может быть неизвестна - тогда в столбце стоит `?`. Версию мы поддерживаем, а привязки
// к релизу нет; выдумывать ее в спеке нельзя, поэтому ступень остается с явным пробелом в данных.
function parseLadder(text) {
  const rows = [];
  const section = text.split(/^### 7\.1\./m)[1];
  if (!section) return rows;
  const body = section.split(/^###? /m)[0];
  for (const line of body.split('\n')) {
    const m = /^\|\s*([\d.]+|\?)\s*\|\s*`?(\d+\.\d+)`?\s*\|\s*([^|]+?)\s*\|/.exec(line);
    if (m) rows.push({ platform: m[1], version: m[2], measured: m[3].trim() });
  }
  return rows;
}

const specText = read(SPEC);
if (!specText) {
  console.error(`ERROR: спецификация не найдена: ${SPEC}`);
  process.exit(1);
}

const ladder = parseLadder(specText);
if (ladder.length === 0) {
  errors.push(`Таблица лестницы версий не разобрана из ${SPEC} (§7.1) — изменился формат таблицы?`);
}

// Ступени, помеченные как незамеренные, эталоном верхней границы быть не могут.
const measured = ladder.filter((r) => r.measured.toLowerCase() !== 'нет');
const lastMeasured = measured.length ? measured[measured.length - 1] : null;

// Лестница обязана идти по возрастанию: немонотонность = ошибка в самой таблице.
for (let i = 1; i < ladder.length; i++) {
  if (rank(ladder[i].version) <= rank(ladder[i - 1].version)) {
    errors.push(
      `Лестница в спеке немонотонна: ${ladder[i - 1].platform} → ${ladder[i - 1].version}, ` +
        `затем ${ladder[i].platform} → ${ladder[i].version}`,
    );
  }
}

// ─── Границы в скриптах ─────────────────────────────────────────────────────
const found = [];
for (const c of RANGE_CONSUMERS) {
  for (const [port, ext] of [['ps1', '.ps1'], ['py', '.py']]) {
    const path = join(skillDir(c.skill), 'scripts', c.file + ext);
    const text = read(path);
    if (text === null) {
      errors.push(`${c.skill} (${port}): файл не найден: ${path}`);
      continue;
    }
    const minRe = port === 'ps1' ? /\$formatVerifiedMin\s*=\s*"([\d.]+)"/ : /FORMAT_VERIFIED_MIN\s*=\s*"([\d.]+)"/;
    const maxRe = port === 'ps1' ? /\$formatVerifiedMax\s*=\s*"([\d.]+)"/ : /FORMAT_VERIFIED_MAX\s*=\s*"([\d.]+)"/;
    const min = minRe.exec(text);
    const max = maxRe.exec(text);
    if (!min || !max) {
      errors.push(
        `${c.skill} (${port}): не найдены границы проверенного диапазона ` +
          `(${port === 'ps1' ? '$formatVerifiedMin/$formatVerifiedMax' : 'FORMAT_VERIFIED_MIN/MAX'})`,
      );
      continue;
    }
    const entry = { skill: c.skill, port, min: min[1], max: max[1], def: null };

    if (c.hasDefault) {
      const defRe = port === 'ps1'
        ? /\[string\]\$FormatVersion\s*=\s*"([\d.]+)"/
        : /'-FormatVersion',\s*dest='FormatVersion',\s*default='([\d.]+)'/;
      const def = defRe.exec(text);
      if (!def) {
        errors.push(`${c.skill} (${port}): не найден дефолт -FormatVersion`);
      } else {
        entry.def = def[1];
      }
    }

    // Запрет вернулся: ValidateSet/choices снова закрывают вход вместо предупреждения (issue #63).
    if (c.hasDefault) {
      const banned = port === 'ps1'
        ? /\[ValidateSet\([^)]*\)\]\s*\r?\n\s*\[string\]\$FormatVersion/
        : /'-FormatVersion'[^)]*choices\s*=/s;
      if (banned.test(text)) {
        errors.push(
          `${c.skill} (${port}): -FormatVersion снова ограничен списком. Версии вне проверенного ` +
            `диапазона реальны — их место в предупреждении, а не в запрете на входе (issue #63)`,
        );
      }
    }

    found.push(entry);
  }
}

// ─── Инвариант 1: границы совпадают у всех ──────────────────────────────────
const mins = new Set(found.map((f) => f.min));
const maxs = new Set(found.map((f) => f.max));
if (mins.size > 1) {
  errors.push(
    `Нижняя граница разъехалась: ` +
      found.map((f) => `${f.skill}/${f.port}=${f.min}`).join(', '),
  );
}
if (maxs.size > 1) {
  errors.push(
    `Верхняя граница разъехалась: ` +
      found.map((f) => `${f.skill}/${f.port}=${f.max}`).join(', '),
  );
}

const codeMin = found.length ? found[0].min : null;
const codeMax = found.length ? found[0].max : null;

if (codeMin && codeMax && rank(codeMin) > rank(codeMax)) {
  errors.push(`Диапазон вывернут: min=${codeMin} > max=${codeMax}`);
}

// ─── Инвариант 2: дефолты внутри диапазона ──────────────────────────────────
for (const f of found) {
  if (!f.def) continue;
  if (rank(f.def) < rank(codeMin) || rank(f.def) > rank(codeMax)) {
    errors.push(
      `${f.skill} (${f.port}): дефолт -FormatVersion=${f.def} вне проверенного диапазона ${codeMin}-${codeMax}`,
    );
  }
}

// ─── Инвариант 2б: зашитые в шаблон версии внутри диапазона ─────────────────
const fixed = [];
for (const c of FIXED_VERSION_EMITTERS) {
  for (const [port, ext] of [['ps1', '.ps1'], ['py', '.py']]) {
    const path = join(skillDir(c.skill), 'scripts', c.file + ext);
    const text = read(path);
    if (text === null) {
      errors.push(`${c.skill} (${port}): файл не найден: ${path}`);
      continue;
    }
    // Корневой элемент выгрузки, а не объявление XML: у второго version="1.0".
    const versions = [...text.matchAll(/xmlns[^>]*\sversion="(\d+\.\d+)"/g)].map((m) => m[1]);
    if (versions.length === 0) {
      errors.push(`${c.skill} (${port}): в шаблонах не найден version корневого элемента`);
      continue;
    }
    const distinct = [...new Set(versions)];
    if (distinct.length > 1) {
      errors.push(
        `${c.skill} (${port}): шаблоны выпускают разные версии формата (${distinct.join(', ')}) - ` +
          `объект и его части окажутся в разных версиях`,
      );
    }
    for (const v of distinct) {
      if (rank(v) < rank(codeMin) || rank(v) > rank(codeMax)) {
        errors.push(
          `${c.skill} (${port}): шаблон выпускает version="${v}" вне проверенного диапазона ${codeMin}-${codeMax}`,
        );
      }
    }
    fixed.push({ skill: c.skill, port, versions: distinct });
  }
}

// ─── Инвариант 3: границы сходятся с лестницей ──────────────────────────────
const lastStep = ladder.length ? ladder[ladder.length - 1] : null;
if (codeMax && lastStep && codeMax !== lastStep.version) {
  errors.push(
    `Верхняя граница в коде (${codeMax}) не совпадает с последней ступенью лестницы ` +
      `(${lastStep.version}, платформа ${lastStep.platform}). Либо в спеку добавили ступень ` +
      `и забыли поднять диапазон в навыках, либо наоборот.`,
  );
}
// Верх диапазона держится на описании возможностей, а не на живой выгрузке. Это рабочее состояние,
// но знать о нем надо: цена ошибки в незамеренной версии выше.
if (codeMax && lastStep && lastStep.measured.toLowerCase() === 'нет') {
  console.log(
    `WARN: верхняя ступень ${lastStep.version} не замерена на выгрузке платформы. ` +
      `Поддержка держится на описании возможностей.`,
  );
}
if (codeMin && ladder.length && !ladder.some((r) => r.version === codeMin)) {
  errors.push(`Нижняя граница в коде (${codeMin}) отсутствует в лестнице спецификации`);
}

// ─── Вывод ──────────────────────────────────────────────────────────────────
if (listMode) {
  console.log('Лестница версий (docs/1c-configuration-spec.md §7.1):');
  for (const r of ladder) {
    console.log(`  ${r.platform.padEnd(8)} → ${r.version}   замерено: ${r.measured}`);
  }
  console.log('\nПроверенный диапазон в навыках:');
  for (const f of found) {
    console.log(`  ${f.skill.padEnd(14)} ${f.port.padEnd(4)} ${f.min}-${f.max}${f.def ? `  default=${f.def}` : ''}`);
  }
  console.log('\nЗашитые в шаблон версии:');
  for (const f of fixed) {
    console.log(`  ${f.skill.padEnd(14)} ${f.port.padEnd(4)} ${f.versions.join(', ')}`);
  }
  console.log('');
}

if (errors.length) {
  for (const e of errors) console.error(`ERROR: ${e}`);
  console.error(`\n${errors.length} ошибок.`);
  process.exit(1);
}

console.log(
  `OK — проверенный диапазон ${codeMin}-${codeMax} согласован: ` +
    `${found.length} файлов, лестница ${ladder.length} ступеней (последняя замеренная — ${lastMeasured?.version}).`,
);
