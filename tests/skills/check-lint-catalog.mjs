#!/usr/bin/env node
// Реестр lint-правил bsl-validate: каждое правило подтверждено своей парой фикстур каталога.
//
// Для каждого правила из skills/1c-bsl-validate/scripts/catalog-rules.json:
//   1. у карточки есть пара фикстур tests/catalog/<ИД>/{manifest.json,defect.bsl,clean.bsl}
//      с типом bsl-pair и непустым списком expected;
//   2. прогон режима -Catalog с -RuleId на defect.bsl дает находки ровно на строках expected
//      (ни одной лишней), на clean.bsl - ноль находок;
//   3. оба порта (Python и PowerShell) дают одинаковый вывод на одинаковых входах -
//      СЫРОЙ stdout, байт в байт, до любого разбора JSON: сравнение разобранного JSON
//      пропускало бы расхождения разделителей и порядка находок;
//   4. полный прогон каталога карточки без -RuleId (оба файла, все правила) тоже совпадает
//      у портов сыро - так сверяется единый порядок находок (файл, строка, идентификатор);
//   5. запрос в нижнем регистре с переносом между скобкой и ВЫБРАТЬ опознается обоими
//      портами одинаково - шаблоны запросов и вызовов регистронезависимы, а матч query-regex
//      идет по тексту литерала целиком.
//
// Правило без пары фикстур, расхождение строк, лишние находки или расхождение портов -
// гард красный. PowerShell-канал пропускается с сообщением там, где powershell.exe
// недоступен (не-Windows), - паритет в этих средах держат кейсы раннера.
//
// Запуск:  node tests/skills/check-lint-catalog.mjs
import { readFileSync, existsSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..');
const REGISTRY = join(ROOT, 'skills/1c-bsl-validate/scripts/catalog-rules.json');
const PY_SCRIPT = join(ROOT, 'skills/1c-bsl-validate/scripts/bsl-validate.py');
const PS_SCRIPT = join(ROOT, 'skills/1c-bsl-validate/scripts/bsl-validate.ps1');
const FIXTURES = join(ROOT, 'tests/catalog');

const problems = [];
let rulesChecked = 0;
let runs = 0;

// Прогон одного порта: ruleId null - полный прогон каталога без -RuleId.
function runPort(kind, modulePath, ruleId) {
  const args = ['-ModulePath', modulePath, '-Catalog'];
  if (ruleId) args.push('-RuleId', ruleId);
  args.push('-Json');
  const res = kind === 'py'
    ? spawnSync(process.env.PYTHON || 'python', ['-X', 'utf8', PY_SCRIPT, ...args],
        { encoding: 'utf8' })
    : spawnSync('powershell.exe',
        ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', PS_SCRIPT, ...args],
        { encoding: 'utf8' });
  runs++;
  if (res.error) {
    if (res.error.code === 'ENOENT') return { skipped: true };
    problems.push(`порт ${kind} (${ruleId || 'полный прогон'}): не запустился: ${res.error.message}`);
    return null;
  }
  if (res.stderr && res.stderr.trim()) {
    problems.push(`порт ${kind} (${ruleId || 'полный прогон'}): пишет в stderr: ${res.stderr.trim().slice(0, 200)}`);
  }
  return { raw: res.stdout };
}

// Парсинг после сырого захвата: payload для проверки expected.
function parsePayload(run, what) {
  try {
    return { payload: JSON.parse(run.raw) };
  } catch (e) {
    problems.push(`${what}: вывод не разбирается как JSON: ${e.message}`);
    return null;
  }
}

const findingsOf = (payload) => (payload.findings || []).map((f) => `${f.id}:${f.line}`).sort();

// Сырое сравнение двух прогонов портов; пропуск, если PowerShell недоступен.
function assertRawParity(pyRun, psRun, what) {
  if (!pyRun || !psRun || pyRun.skipped || psRun.skipped) return false;
  if (pyRun.raw !== psRun.raw) {
    problems.push(`${what}: порты расходятся в сыром stdout`);
    return false;
  }
  return true;
}

let registry;
try {
  registry = JSON.parse(readFileSync(REGISTRY, 'utf8'));
} catch (e) {
  console.error(`реестр lint-правил ${REGISTRY} не читается: ${e.message}`);
  process.exit(1);
}
if (!Array.isArray(registry) || registry.length === 0) {
  console.error('реестр lint-правил пуст или не массив');
  process.exit(1);
}

const seen = new Set();
for (const rule of registry) {
  const rid = rule.id;
  if (!rid) {
    problems.push('запись реестра без поля id');
    continue;
  }
  if (seen.has(rid)) {
    problems.push(`правило ${rid} перечислено дважды`);
    continue;
  }
  seen.add(rid);

  const dir = join(FIXTURES, rid);
  if (!existsSync(dir)) {
    problems.push(`правило ${rid}: нет каталога фикстур ${dir}`);
    continue;
  }
  const manifestFile = join(dir, 'manifest.json');
  if (!existsSync(manifestFile)) {
    problems.push(`правило ${rid}: нет manifest.json`);
    continue;
  }
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestFile, 'utf8'));
  } catch (e) {
    problems.push(`правило ${rid}: manifest.json не разбирается: ${e.message}`);
    continue;
  }
  if (manifest.type !== 'bsl-pair') {
    problems.push(`правило ${rid}: тип фикстуры ${manifest.type}, ожидается bsl-pair`);
    continue;
  }
  if (!Array.isArray(manifest.expected) || manifest.expected.length === 0) {
    problems.push(`правило ${rid}: пуст список expected`);
    continue;
  }
  if (!existsSync(join(dir, 'defect.bsl')) || !existsSync(join(dir, 'clean.bsl'))) {
    problems.push(`правило ${rid}: у пары фикстур нет defect.bsl или clean.bsl`);
    continue;
  }

  const expected = manifest.expected.map((n) => `${rid}:${n}`).sort();
  const defectPy = runPort('py', join(dir, 'defect.bsl'), rid);
  const cleanPy = runPort('py', join(dir, 'clean.bsl'), rid);
  const defectPs = runPort('ps', join(dir, 'defect.bsl'), rid);
  const cleanPs = runPort('ps', join(dir, 'clean.bsl'), rid);
  const psAvailable = !(defectPs && defectPs.skipped && cleanPs && cleanPs.skipped);

  const defectPyParsed = defectPy ? parsePayload(defectPy, `правило ${rid}: defect.bsl (python)`) : null;
  if (defectPyParsed && defectPyParsed.payload) {
    const got = findingsOf(defectPyParsed.payload);
    if (defectPyParsed.payload.status !== 'findings') {
      problems.push(`правило ${rid}: defect.bsl не дал находок (python)`);
    } else if (JSON.stringify(got) !== JSON.stringify(expected)) {
      problems.push(
        `правило ${rid}: defect.bsl (python) ожидаются [${expected.join(', ')}], получено [${got.join(', ')}]`);
    }
  }
  const cleanPyParsed = cleanPy ? parsePayload(cleanPy, `правило ${rid}: clean.bsl (python)`) : null;
  if (cleanPyParsed && cleanPyParsed.payload && cleanPyParsed.payload.findings.length > 0) {
    problems.push(
      `правило ${rid}: clean.bsl (python) дал находки: ${findingsOf(cleanPyParsed.payload).join(', ')}`);
  }
  if (!psAvailable) {
    console.log(`  правило ${rid}: powershell.exe недоступен, проверен только python-порт`);
  } else {
    const defectPsParsed = defectPs ? parsePayload(defectPs, `правило ${rid}: defect.bsl (powershell)`) : null;
    if (defectPsParsed && defectPsParsed.payload) {
      const got = findingsOf(defectPsParsed.payload);
      if (defectPsParsed.payload.status !== 'findings') {
        problems.push(`правило ${rid}: defect.bsl не дал находок (powershell)`);
      } else if (JSON.stringify(got) !== JSON.stringify(expected)) {
        problems.push(
          `правило ${rid}: defect.bsl (powershell) ожидаются [${expected.join(', ')}], получено [${got.join(', ')}]`);
      }
    }
    const cleanPsParsed = cleanPs ? parsePayload(cleanPs, `правило ${rid}: clean.bsl (powershell)`) : null;
    if (cleanPsParsed && cleanPsParsed.payload && cleanPsParsed.payload.findings.length > 0) {
      problems.push(
        `правило ${rid}: clean.bsl (powershell) дал находки: ${findingsOf(cleanPsParsed.payload).join(', ')}`);
    }
    assertRawParity(defectPy, defectPs, `правило ${rid}: defect.bsl`);
    assertRawParity(cleanPy, cleanPs, `правило ${rid}: clean.bsl`);
  }

  // Полный прогон каталога карточки: порядок находок всех правил един у портов.
  if (psAvailable) {
    const fullPy = runPort('py', dir, null);
    const fullPs = runPort('ps', dir, null);
    assertRawParity(fullPy, fullPs, `правило ${rid}: полный прогон каталога`);
  }
  rulesChecked++;
}

// Регистр и перенос строки: запрос в нижнем регистре, скобка подзапроса и ВЫБРАТЬ на
// разных строках. QUERY-14 обязан дать одинаковый ненулевой результат на обоих портах.
{
  const dir = mkdtempSync(join(tmpdir(), 'lint-catalog-lower-'));
  try {
    const module = join(dir, 'lower-query.bsl');
    writeFileSync(module,
      'Запрос = Новый Запрос;\n'
      + 'Запрос.Текст =\n'
      + '"выбрать\n'
      + '|    Заказы.Номер как Номер\n'
      + '|из\n'
      + '|    Документ.Заказ как Заказы\n'
      + '|где\n'
      + '|    Заказы.Ссылка в\n'
      + '|        (\n'
      + '|            выбрать Оплаты.Заказ\n'
      + '|        из\n'
      + '|            Документ.Оплата как Оплаты\n'
      + '|        где\n'
      + '|            Оплаты.Контрагент = Заказы.Контрагент)";\n'
      + 'Результат = Запрос.Выполнить();\n', 'utf8');
    const pyRun = runPort('py', module, null);
    const psRun = runPort('ps', module, null);
    const pyParsed = pyRun ? parsePayload(pyRun, 'нижний регистр (python)') : null;
    if (pyParsed && pyParsed.payload) {
      const got = findingsOf(pyParsed.payload);
      if (!got.includes('QUERY-14:9') || got.length === 0) {
        problems.push(`нижний регистр: QUERY-14 не найден в многострочном подзапросе: [${got.join(', ')}]`);
      }
    }
    if (pyRun && psRun && !pyRun.skipped && !psRun.skipped) {
      assertRawParity(pyRun, psRun, 'нижний регистр');
    } else {
      console.log('  нижний регистр: powershell.exe недоступен, проверен только python-порт');
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

console.log(`Правил проверено: ${rulesChecked}, запусков портов: ${runs}.`);
if (problems.length) {
  console.error(`\nРАСХОЖДЕНИЯ (${problems.length}):`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('OK - каждое правило реестра подтверждено парой фикстур, порты согласованы.');
