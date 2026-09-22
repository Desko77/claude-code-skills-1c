#!/usr/bin/env node
// Реестр lint-правил bsl-validate: каждое правило подтверждено своей парой фикстур каталога.
//
// Для каждого правила из skills/1c-bsl-validate/scripts/catalog-rules.json:
//   1. у карточки есть пара фикстур tests/catalog/<ИД>/{manifest.json,defect.bsl,clean.bsl}
//      с типом bsl-pair и непустым списком expected;
//   2. прогон режима -Catalog с -RuleId на defect.bsl дает находки ровно на строках expected
//      (ни одной лишней), на clean.bsl - ноль находок;
//   3. оба порта (Python и PowerShell) дают одинаковый JSON на одинаковых входах.
//
// Правило без пары фикстур, расхождение строк, лишние находки или расхождение портов -
// гард красный. PowerShell-канал пропускается с сообщением там, где powershell.exe
// недоступен (не-Windows), - паритет в этих средах держат кейсы раннера.
//
// Запуск:  node tests/skills/check-lint-catalog.mjs
import { readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..');
const REGISTRY = join(ROOT, 'skills/1c-bsl-validate/scripts/catalog-rules.json');
const PY_SCRIPT = join(ROOT, 'skills/1c-bsl-validate/scripts/bsl-validate.py');
const PS_SCRIPT = join(ROOT, 'skills/1c-bsl-validate/scripts/bsl-validate.ps1');
const FIXTURES = join(ROOT, 'tests/catalog');

const problems = [];
let rulesChecked = 0;
let runs = 0;

function runPort(kind, modulePath, ruleId) {
  const args = ['-ModulePath', modulePath, '-Catalog', '-RuleId', ruleId, '-Json'];
  const res = kind === 'py'
    ? spawnSync(process.env.PYTHON || 'python', ['-X', 'utf8', PY_SCRIPT, ...args],
        { encoding: 'utf8' })
    : spawnSync('powershell.exe',
        ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', PS_SCRIPT, ...args],
        { encoding: 'utf8' });
  runs++;
  if (res.error) {
    if (res.error.code === 'ENOENT') return { skipped: true };
    problems.push(`правило ${ruleId}: порт ${kind} не запустился: ${res.error.message}`);
    return null;
  }
  if (res.stderr && res.stderr.trim()) {
    problems.push(`правило ${ruleId}: порт ${kind} пишет в stderr: ${res.stderr.trim().slice(0, 200)}`);
  }
  try {
    return { payload: JSON.parse(res.stdout) };
  } catch (e) {
    problems.push(`правило ${ruleId}: порт ${kind} вывод не разбирается как JSON: ${e.message}`);
    return null;
  }
}

const findingsOf = (payload) => (payload.findings || []).map((f) => `${f.id}:${f.line}`).sort();

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

  if (defectPy && defectPy.payload) {
    const got = findingsOf(defectPy.payload);
    if (defectPy.payload.status !== 'findings') {
      problems.push(`правило ${rid}: defect.bsl не дал находок (python)`);
    } else if (JSON.stringify(got) !== JSON.stringify(expected)) {
      problems.push(
        `правило ${rid}: defect.bsl (python) ожидаются [${expected.join(', ')}], получено [${got.join(', ')}]`);
    }
  }
  if (cleanPy && cleanPy.payload && cleanPy.payload.findings.length > 0) {
    problems.push(
      `правило ${rid}: clean.bsl (python) дал находки: ${findingsOf(cleanPy.payload).join(', ')}`);
  }
  if (defectPs && defectPs.skipped && cleanPs && cleanPs.skipped) {
    console.log(`  правило ${rid}: powershell.exe недоступен, проверен только python-порт`);
  } else if (defectPs && defectPs.payload && cleanPs && cleanPs.payload) {
    const got = findingsOf(defectPs.payload);
    if (defectPs.payload.status !== 'findings') {
      problems.push(`правило ${rid}: defect.bsl не дал находок (powershell)`);
    } else if (JSON.stringify(got) !== JSON.stringify(expected)) {
      problems.push(
        `правило ${rid}: defect.bsl (powershell) ожидаются [${expected.join(', ')}], получено [${got.join(', ')}]`);
    }
    if (cleanPs.payload.findings.length > 0) {
      problems.push(
        `правило ${rid}: clean.bsl (powershell) дал находки: ${findingsOf(cleanPs.payload).join(', ')}`);
    }
    if (defectPy && defectPy.payload && cleanPy && cleanPy.payload) {
      if (JSON.stringify(defectPy.payload) !== JSON.stringify(defectPs.payload)) {
        problems.push(`правило ${rid}: порты расходятся на defect.bsl`);
      }
      if (JSON.stringify(cleanPy.payload) !== JSON.stringify(cleanPs.payload)) {
        problems.push(`правило ${rid}: порты расходятся на clean.bsl`);
      }
    }
  }
  rulesChecked++;
}

console.log(`Правил проверено: ${rulesChecked}, запусков портов: ${runs}.`);
if (problems.length) {
  console.error(`\nРАСХОЖДЕНИЯ (${problems.length}):`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('OK - каждое правило реестра подтверждено парой фикстур, порты согласованы.');
