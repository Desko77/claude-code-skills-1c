#!/usr/bin/env node
// Переносимые блоки: код, живущий копией в нескольких скилах и обязанный совпадать.
//
// Зачем отдельно от check-inline-drift. Тот держит РАЗБРОС общих функций от роста и допускает
// расхождения - это верно для функций, которые размножились исторически. Но у блока, который
// переносят СОЗНАТЕЛЬНО (вердикт платформы, гард поддержки), требование другое: он обязан быть
// одинаковым везде и обязан вызываться. Храповик такого не ловит по устройству: он сравнивает
// число вариантов тела, поэтому скил может получить блок и не вызвать его - число вариантов не
// изменится, проверка останется зеленой.
//
// Что проверяется по каждому блоку и порту:
//   1. У каждого потребителя из списка блок присутствует (найден маркер начала и конца).
//   2. Содержимое блока совпадает с эталоном побайтно после снятия отступов и пустых строк.
//   3. Точка вызова есть ВНЕ самого блока - иначе блок мертвый.
//   4. Список потребителей совпадает с фактом: скил с блоком, но без записи в манифесте - ошибка
//      (забыли внести), запись без блока - тоже (перенос не доехал).
//
// Манифест: tests/skills/shared-blocks.json
// Запуск:  node tests/skills/check-shared-blocks.mjs [--list]
// Выход 1 при расхождении.
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { basename, dirname, join, resolve } from 'node:path';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)));
const SKILLS = resolve(ROOT, '../..', 'skills');
const MANIFEST = join(ROOT, 'shared-blocks.json');

const listMode = process.argv.includes('--list');

// Сравнивается смысл, а не оформление: отступы и пустые строки снимаются. Комментарии, наоборот,
// остаются - в переносимом блоке они часть содержимого и расходиться не должны.
function normalize(text) {
  return text
    .split('\n')
    .map((l) => l.replace(/\t/g, '    ').trimEnd())
    .filter((l) => l.trim() !== '')
    .join('\n')
    .trim();
}

function skillScript(skill, ext) {
  const dir = join(SKILLS, skill, 'scripts');
  if (!existsSync(dir) || !statSync(dir).isDirectory()) return null;
  const files = readdirSync(dir).filter((f) => f.endsWith(ext));
  return files.length ? files.map((f) => join(dir, f)) : null;
}

// ВСЕ файлы скила, где лежит блок. У скила бывает несколько скриптов одного порта
// (epf-build плюс stub-db-create), и проверяется каждая копия: остановка на первой оставляла
// вторую непроверенной, и правка эталона до нее молча не доезжала.
function findBlocks(skill, ext, marker, endMarker) {
  const files = skillScript(skill, ext);
  if (!files) return [];
  const found = [];
  for (const file of files) {
    const text = readFileSync(file, 'utf8').replace(/^﻿/, '');
    const from = text.indexOf(marker);
    if (from < 0) continue;
    const to = text.indexOf(endMarker, from + marker.length);
    if (to < 0) {
      found.push({ file, text, body: null, broken: 'не найден конец блока' });
      continue;
    }
    found.push({ file, text, body: normalize(text.slice(from, to)) });
  }
  return found;
}

// Скилы, где маркер есть фактически - для сверки со списком потребителей.
function skillsWithMarker(ext, marker) {
  const found = new Set();
  for (const skill of readdirSync(SKILLS)) {
    const files = skillScript(skill, ext);
    if (!files) continue;
    for (const file of files) {
      if (readFileSync(file, 'utf8').includes(marker)) { found.add(skill); break; }
    }
  }
  return found;
}

if (!existsSync(MANIFEST)) {
  console.error(`ERROR: нет манифеста ${MANIFEST}`);
  process.exit(1);
}
const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8')).blocks;

const problems = [];
let checked = 0;

for (const [blockName, ports] of Object.entries(manifest)) {
  for (const [ext, spec] of Object.entries(ports)) {
    if (ext.startsWith('_') || ext === 'описание') continue;
    const suffix = ext === 'ps1' ? '.ps1' : '.py';
    const { маркер: marker, конец: endMarker, вызов: call, эталон: reference } = spec;
    const consumers = spec['потребители'];

    const referenceBlock = findBlocks(reference, suffix, marker, endMarker)[0];
    if (!referenceBlock || !referenceBlock.body) {
      problems.push(`${blockName}/${ext}: у эталона ${reference} блок не найден`);
      continue;
    }

    for (const skill of consumers) {
      const copies = findBlocks(skill, suffix, marker, endMarker);
      if (copies.length === 0) {
        checked++;
        problems.push(`${blockName}/${ext}: ${skill} - блока нет, а он в списке потребителей`);
        continue;
      }
      for (const found of copies) {
      checked++;
      const where = copies.length > 1 ? `${skill} (${basename(found.file)})` : skill;
      if (found.broken) {
        problems.push(`${blockName}/${ext}: ${where} - ${found.broken}`);
        continue;
      }
      if (found.body !== referenceBlock.body) {
        problems.push(`${blockName}/${ext}: ${where} - блок разошелся с эталоном ${reference}`);
      }
      // Вызов ищется вне самого блока: внутри блока имя встречается в объявлении.
      // По границе имени, а не подстрокой: Write-PlatformVerdictDisabled содержит
      // Write-PlatformVerdict целиком, и поиск подстрокой считал бы отключенный вызов рабочим.
      // Дефис в имени команд PowerShell в  не входит, поэтому границы заданы явно.
      const outside = found.text.replace(found.text.slice(
        found.text.indexOf(marker),
        found.text.indexOf(endMarker, found.text.indexOf(marker)),
      ), '');
      // Дефис в имени команд PowerShell не входит в \b, поэтому границы заданы явно.
      const escaped = call.replace(/[^A-Za-z0-9_-]/g, (c) => '\\' + c);
      const callRe = new RegExp('(?<![A-Za-z0-9_-])' + escaped + '(?![A-Za-z0-9_-])');
      if (!callRe.test(outside)) {
        problems.push(`${blockName}/${ext}: ${where} - блок есть, но ${call} не вызывается`);
      }
      }
    }

    const actual = skillsWithMarker(suffix, marker);
    for (const skill of actual) {
      if (!consumers.includes(skill)) {
        problems.push(`${blockName}/${ext}: ${skill} несет блок, но его нет в списке потребителей`);
      }
    }

    if (listMode) {
      console.log(`${blockName}/${ext}: потребителей ${consumers.length}, эталон ${reference}`);
    }
  }
}

console.log(`Переносимых блоков проверено: ${checked} копий.`);

if (problems.length) {
  console.error(`\nРАСХОЖДЕНИЯ (${problems.length}):`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('OK - переносимые блоки совпадают с эталоном и вызываются.');
