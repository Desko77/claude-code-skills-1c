#!/usr/bin/env node
// Инвариант: сканер текстов дает на корпусе РОВНО ожидаемый набор категорий,
// и корпус покрывает ВЕСЬ реестр публичных категорий.
//
// Формула "чистый корпус без находок" неприменима: у документа с учебными примерами
// находки законны. Поэтому сверяется набор категорий по каждому файлу, а не ноль.
//
// Проверка полноты обязательна отдельно: без нее новая категория, не сработавшая ни на
// одном файле корпуса, осталась бы невидимой, и обещание "появилась категория - гард
// падает" не выполнялось бы.
//
// Расхождение копии с оригиналом ПРЕДУПРЕЖДАЕТ, но не роняет: падение здесь означало бы,
// что любая правка документации ломает сборку, то есть ровно то, от чего уходили
// копированием файлов в фикстуры.
//
// Выход 1 при нарушении. Запуск: node tests/skills/check-text-corpus.mjs
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const SCANNER = join(ROOT, 'skills', 'humanize-ai-text', 'scripts', 'humanize_scan.py');
const CORPUS = join(ROOT, 'tests', 'skills', 'cases', 'humanize-scan', 'corpus');
const REGISTRY = join(ROOT, 'skills', 'humanize-ai-text', 'scripts', 'categories.json');

const manifest = JSON.parse(readFileSync(join(CORPUS, 'manifest.json'), 'utf8'));
const registry = JSON.parse(readFileSync(REGISTRY, 'utf8'));
const known = new Set(registry.categories.map(c => c.id));

let failures = 0;
const covered = new Set();

for (const entry of manifest.files) {
  const path = join(CORPUS, entry.file);
  if (!existsSync(path)) {
    console.error(`  НЕТ ФАЙЛА: ${entry.file}`);
    failures++;
    continue;
  }

  let report;
  try {
    const args = [SCANNER, path, '--json'];
    if (entry.genre) args.push('--genre', entry.genre);
    let stdout;
    try {
      stdout = execFileSync(PY, args, { encoding: 'utf8', stdio: 'pipe' });
    } catch (err) {
      // Код возврата 1 при находках штатный: грязный корпус их и должен давать.
      // Сравниватель обязан разбирать валидный JSON при коде 1, иначе грязный
      // корпус принимался бы за сбой запуска и гард не работал бы вовсе.
      stdout = err.stdout || '';
      if (!stdout) throw err;
    }
    report = JSON.parse(stdout)[0];
  } catch (err) {
    console.error(`  ${entry.file}: сканер не отработал: ${err.message}`);
    failures++;
    continue;
  }

  if (entry.genre && report.genre !== entry.genre) {
    console.error(`  ${entry.file}: жанр ${report.genre}, ожидался ${entry.genre}`);
    failures++;
  }

  const got = [...new Set(report.findings.map(f => f.category))].sort();
  const want = [...entry.expect].sort();
  for (const c of got) covered.add(c);

  const extra = got.filter(c => !want.includes(c));
  const missing = want.filter(c => !got.includes(c));
  if (extra.length || missing.length) {
    console.error(`  ${entry.file}: лишние [${extra.join(', ')}], недостающие [${missing.join(', ')}]`);
    failures++;
  }

  // Неизвестная реестру категория означает, что сканер начал выдавать то,
  // чего в источнике истины нет.
  const unknown = got.filter(c => !known.has(c));
  if (unknown.length) {
    console.error(`  ${entry.file}: категории вне реестра: ${unknown.join(', ')}`);
    failures++;
  }
}

// Полнота покрытия: объединение ожидаемых категорий корпуса должно совпасть с реестром.
const wantedByCorpus = new Set(manifest.files.flatMap(e => e.expect));
const uncovered = [...known].filter(c => !wantedByCorpus.has(c));
if (uncovered.length) {
  console.error(`\n  Реестр покрыт не весь, нет образца на: ${uncovered.join(', ')}`);
  failures++;
}

// Дрейф копий: предупреждение, не падение.
let drifted = 0;
for (const entry of manifest.files) {
  if (!entry.source) continue;
  const orig = join(ROOT, entry.source);
  const copy = join(CORPUS, entry.file);
  if (!existsSync(orig)) {
    console.log(`  ПРЕДУПРЕЖДЕНИЕ: оригинала нет, ${entry.source}`);
    drifted++;
    continue;
  }
  if (readFileSync(orig, 'utf8') !== readFileSync(copy, 'utf8')) {
    console.log(`  ПРЕДУПРЕЖДЕНИЕ: копия разошлась с оригиналом, ${entry.source}`);
    drifted++;
  }
}

if (failures) {
  console.error(`\nКорпус сканера текстов: нарушений ${failures}`);
  process.exit(1);
}
console.log(`Корпус сканера текстов: ${manifest.files.length} файлов, реестр покрыт весь `
  + `(${known.size} категорий)${drifted ? `, разошлось копий ${drifted}` : ''}`);
