#!/usr/bin/env node
// Инвариант: линтер API-справочников читает все три раскладки выгрузки и проверяет
// утверждения в ОБЕ стороны - и положительные (вызов есть), и отрицательные (вызова нет).
//
// Снапшот-раннер этого не покрывает: он берет только скрипты из skills/ с портами
// .ps1/.py, а линтер лежит в tools/ и существует одним портом. Без этого гарда критерий
// "оба порта зеленые" выполнялся бы, не запустив ни одной проверки линтера.
//
// Раскладки: выгрузка Конфигуратора (<Модуль>/Ext/Module.bsl), EDT-проект
// (<Модуль>/Module.bsl) и распаковка v8unpack (CommonModule/<Модуль>/CommonModule.obj.bsl).
// Выгрузка синтетическая и создается здесь же: гард не зависит ни от какой библиотеки
// на диске и одинаково работает на любой машине.
//
// Выход 1 при нарушении. Запуск: node tests/skills/check-api-validator.mjs
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { removeTree } from './fs-safe.mjs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const IS_WIN = process.platform === 'win32';
const PY = process.env.PYTHON || (IS_WIN ? 'python' : 'python3');
const VALIDATOR = join(ROOT, 'tools', 'validate_api_reference.py');

// Синтетический общий модуль: два экспортных метода в программном интерфейсе.
const MODULE_BSL = [
  '#Область ПрограммныйИнтерфейс',
  '',
  '// Возвращает значение реквизита.',
  'Функция ЗначениеРеквизита(Ссылка, ИмяРеквизита) Экспорт',
  '\tВозврат Неопределено;',
  'КонецФункции',
  '',
  'Процедура СообщитьЧтоТо(Текст) Экспорт',
  'КонецПроцедуры',
  '',
  '#КонецОбласти',
  ''
].join('\n');

// Раскладка -> где лежит файл модуля относительно корня выгрузки.
const LAYOUTS = {
  configurator: ['CommonModules', 'ТестовыйМодуль', 'Ext', 'Module.bsl'],
  edt: ['CommonModules', 'ТестовыйМодуль', 'Module.bsl'],
  v8unpack: ['CommonModule', 'ТестовыйМодуль', 'CommonModule.obj.bsl'],
};

// Справочник с намеренными нарушениями и намеренно верными местами.
// Ожидание: три ошибки, и ни одной на верных строках.
const REFERENCE = [
  '# Проба линтера',
  '',
  'Верный вызов: `ТестовыйМодуль.ЗначениеРеквизита`.',
  '',
  'Выдуманный модуль: `НетТакогоМодуля.Метод`.',
  '',
  'Выдуманный метод: `ТестовыйМодуль.НетТакогоМетода`.',
  '',
  'Верное отрицание модуля: модуля `СовсемНетМодуля` не существует.',
  '',
  'Ложное отрицание модуля: модуля `ТестовыйМодуль` не существует.',
  '',
  'Верное отрицание метода: `ТестовыйМодуль.ВыдуманныйМетод` не существует.',
  '',
  'Ложное отрицание метода: `ТестовыйМодуль.СообщитьЧтоТо` не существует.',
  ''
].join('\n');

const EXPECTED = {
  MODULE_NOT_FOUND: 1,
  METHOD_NOT_FOUND: 1,
  FALSE_NEGATION_MODULE: 1,
  FALSE_NEGATION_METHOD: 1,
};

function buildSource(root, layout) {
  const parts = LAYOUTS[layout];
  const dir = join(root, ...parts.slice(0, -1));
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, parts[parts.length - 1]), MODULE_BSL, 'utf8');
}

function runValidator(refsDir, srcDir) {
  let stdout = '';
  try {
    stdout = execFileSync(PY, [VALIDATOR, '--refs', refsDir, '--src', srcDir, '--json'],
      { encoding: 'utf8', stdio: 'pipe' });
  } catch (err) {
    // Ненулевой код возврата ожидаем: в справочнике намеренные нарушения.
    stdout = err.stdout || '';
    if (!stdout) throw err;
  }
  return JSON.parse(stdout);
}

// Вторая версия библиотеки: метод СообщитьЧтоТо убран, добавлен НовыйМетод.
// На этой паре проверяются маркеры версии в тексте справочника.
const MODULE_BSL_NEW = [
  '#Область ПрограммныйИнтерфейс',
  '',
  'Функция ЗначениеРеквизита(Ссылка, ИмяРеквизита) Экспорт',
  '\tВозврат Неопределено;',
  'КонецФункции',
  '',
  'Функция НовыйМетод() Экспорт',
  '\tВозврат Истина;',
  'КонецФункции',
  '',
  '#КонецОбласти',
  ''
].join('\n');

const REFERENCE_VERSIONS = [
  '# Проба версий',
  '',
  'Есть в обеих: `ТестовыйМодуль.ЗначениеРеквизита`.',
  '',
  'Только в новой: `ТестовыйМодуль.НовыйМетод` [2.0].',
  '',
  'Верно помечен отсутствующим в новой: `ТестовыйМодуль.СообщитьЧтоТо` [нет в 2.0].',
  '',
  'ЛОЖНО помечен отсутствующим в старой: `ТестовыйМодуль.ЗначениеРеквизита` [нет в 1.0].',
  ''
].join('\n');

function checkVersions(tmp) {
  const refsDir = join(tmp, 'refs-versions');
  mkdirSync(refsDir, { recursive: true });
  writeFileSync(join(refsDir, 'versions.md'), REFERENCE_VERSIONS, 'utf8');

  for (const [ver, body] of [['1.0', MODULE_BSL], ['2.0', MODULE_BSL_NEW]]) {
    const dir = join(tmp, 'src-v' + ver, 'CommonModule', 'ТестовыйМодуль');
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'CommonModule.obj.bsl'), body, 'utf8');
  }

  let stdout = '';
  try {
    stdout = execFileSync(PY, [VALIDATOR, '--refs', refsDir,
      '--src', '1.0=' + join(tmp, 'src-v1.0'),
      '--src', '2.0=' + join(tmp, 'src-v2.0'), '--json'],
      { encoding: 'utf8', stdio: 'pipe' });
  } catch (err) {
    stdout = err.stdout || '';
    if (!stdout) { console.error(`[versions] линтер не отработал: ${err.message}`); return false; }
  }
  const report = JSON.parse(stdout);
  const codes = (report.findings || []).map(f => f.code).sort();
  // Ожидается ровно одна находка: ложная пометка отсутствия там, где метод есть.
  if (codes.length !== 1 || codes[0] !== 'FALSE_VERSION_NEGATION') {
    console.error(`[versions] ожидался ровно FALSE_VERSION_NEGATION, получено: ${codes.join(', ') || 'ничего'}`);
    return false;
  }
  console.log('[versions] ok: маркеры версии учтены, ложная пометка отсутствия поймана');
  return true;
}

let failures = 0;
const tmp = mkdtempSync(join(tmpdir(), 'api-validator-'));
try {
  const refsDir = join(tmp, 'refs');
  mkdirSync(refsDir, { recursive: true });
  writeFileSync(join(refsDir, 'probe.md'), REFERENCE, 'utf8');

  for (const layout of Object.keys(LAYOUTS)) {
    const srcDir = join(tmp, 'src-' + layout);
    buildSource(srcDir, layout);

    let report;
    try {
      report = runValidator(refsDir, srcDir);
    } catch (err) {
      console.error(`[${layout}] линтер не отработал: ${err.message}`);
      failures++;
      continue;
    }

    if (!report.modules_in_src) {
      console.error(`[${layout}] раскладка не распознана: модулей в выгрузке 0`);
      failures++;
      continue;
    }

    const counts = {};
    for (const f of report.findings || []) {
      counts[f.code] = (counts[f.code] || 0) + 1;
    }

    let ok = true;
    for (const [code, want] of Object.entries(EXPECTED)) {
      const got = counts[code] || 0;
      if (got !== want) {
        console.error(`[${layout}] ${code}: ожидалось ${want}, получено ${got}`);
        ok = false;
      }
    }
    // Верные строки не должны давать находок сверх ожидаемых.
    const extra = Object.keys(counts).filter(c => !(c in EXPECTED));
    if (extra.length) {
      console.error(`[${layout}] лишние коды находок: ${extra.join(', ')}`);
      ok = false;
    }
    if (!ok) failures++;
    else console.log(`[${layout}] ok: модулей ${report.modules_in_src}, находки как ожидалось`);
  }

  if (!checkVersions(tmp)) failures++;
} finally {
  removeTree(tmp);
}

if (failures) {
  console.error(`\nЛинтер API-справочников: нарушений ${failures}`);
  process.exit(1);
}
console.log('\nЛинтер API-справочников: три раскладки читаются, отрицания проверяются в обе стороны');
