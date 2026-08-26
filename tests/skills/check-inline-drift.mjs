#!/usr/bin/env node
// Храповик общих реализаций. Навыки автономны и не подключают общих библиотек, поэтому
// вспомогательные функции размножены копиями. Копии расходятся молча: правку вносят в один навык,
// а в пятнадцати остальных остается прежнее поведение - и никто этого не видит.
//
// Гард не требует, чтобы все копии совпадали: часть расхождений законна (у навыка своя специфика),
// а часть - долг, который разгребается постепенно. Он требует другого: чтобы РАЗБРОС НЕ РОС.
// Для каждой семьи (одноименная функция в двух и более навыках) в базовой линии записано, сколько
// различающихся вариантов тела допустимо сегодня. Стало больше - падаем. Стало меньше - тоже
// падаем, но с подсказкой обновить линию: храповик проворачивается только в сторону порядка.
//
// Базовая линия: tests/skills/inline-baseline.json
// Запуск:  node tests/skills/check-inline-drift.mjs [--list] [--update]
// Выход 1 при расхождении с линией.
import { readFileSync, writeFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SKILLS = join(ROOT, 'skills');
const BASELINE = join(dirname(fileURLToPath(import.meta.url)), 'inline-baseline.json');

const listMode = process.argv.includes('--list');
const updateMode = process.argv.includes('--update');

// Имена, которые совпадают у всех по природе жанра, а не потому что это общая реализация:
// точка входа, конструктор, локальные однобуквенные помощники. Сверять их бессмысленно -
// они и должны быть разными в каждом навыке.
const NOT_FAMILIES = new Set(['main', '__init__', '__repr__', '__str__', 'X', 'out', 'local', 'find', 'info']);

// ─── Разбор исходников ──────────────────────────────────────────────────────
// Сравнивается смысл, а не оформление: комментарии и пустые строки отбрасываются, табы
// приводятся к пробелам. Иначе разъедется каждая вторая копия из-за отступов.
function normalize(body) {
  return body
    .split('\n')
    .map((l) => l.replace(/\t/g, '    ').trimEnd())
    .filter((l) => l.trim() !== '' && !/^\s*#/.test(l))
    .join('\n')
    .trim();
}

// PowerShell: function Имя { ... } и function Имя(параметры) { ... }.
// Список параметров необязателен, и без его учета разбор пропускал 370 функций из 823 -
// почти половину набора. Вложенных круглых скобок в списках параметров набора нет,
// поэтому простого [^)]* достаточно; появятся - понадобится счет баланса скобок.
// Конец тела - закрывающая скобка на отступе объявления. Конец тела - закрывающая скобка на отступе объявления.
// Отступ ловится как пробелы и табы, а НЕ как \s: иначе в него попадут переводы строк и
// закрывающая скобка не найдется никогда (на этом гард молча не видел ни одной функции).
function psFunctions(text) {
  const out = new Map();
  const re = /^([ \t]*)function\s+([A-Za-z0-9_-]+)\s*(?:\([^)]*\))?\s*\{/gm;
  let m;
  while ((m = re.exec(text))) {
    const from = m.index + m[0].length;
    const to = text.indexOf(`\n${m[1]}}`, from);
    if (to < 0) continue;
    out.set(m[2], normalize(text.slice(from, to)));
  }
  return out;
}

// Python: def имя(...): до строки с отступом не больше, чем у самого def.
function pyFunctions(text) {
  const out = new Map();
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const m = /^([ \t]*)def\s+([A-Za-z0-9_]+)\s*\(/.exec(lines[i]);
    if (!m) continue;
    const indent = m[1].length;
    let j = i + 1;
    for (; j < lines.length; j++) {
      if (lines[j].trim() === '') continue;
      if (lines[j].length - lines[j].trimStart().length <= indent) break;
    }
    out.set(m[2], normalize(lines.slice(i + 1, j).join('\n')));
  }
  return out;
}

function collect() {
  const families = new Map();   // "port:name" -> Map<skill, нормализованное тело>
  for (const skill of readdirSync(SKILLS)) {
    const dir = join(SKILLS, skill, 'scripts');
    if (!existsSync(dir) || !statSync(dir).isDirectory()) continue;
    for (const file of readdirSync(dir)) {
      const port = file.endsWith('.ps1') ? 'ps1' : file.endsWith('.py') ? 'py' : null;
      if (!port) continue;
      const text = readFileSync(join(dir, file), 'utf8').replace(/^﻿/, '');
      for (const [name, body] of port === 'ps1' ? psFunctions(text) : pyFunctions(text)) {
        if (NOT_FAMILIES.has(name)) continue;
        const key = `${port}:${name}`;
        if (!families.has(key)) families.set(key, new Map());
        families.get(key).set(skill, body);
      }
    }
  }
  // Семья - это функция, живущая в двух и более навыках. В одном навыке сверять не с чем.
  for (const [key, copies] of families) if (copies.size < 2) families.delete(key);
  return families;
}

// ─── Замер ──────────────────────────────────────────────────────────────────
const families = collect();
const current = {};
for (const [key, copies] of families) {
  current[key] = { skills: copies.size, variants: new Set(copies.values()).size };
}

if (updateMode) {
  const sorted = Object.fromEntries(Object.keys(current).sort().map((k) => [k, current[k]]));
  writeFileSync(BASELINE, JSON.stringify({
    _note: 'Храповик общих реализаций: сколько различающихся вариантов тела допустимо у семьи ' +
      'сегодня. Число не должно расти. Уменьшили разброс - обновите линию: ' +
      'node tests/skills/check-inline-drift.mjs --update',
    families: sorted,
  }, null, 2) + '\n', 'utf8');
  console.log(`Базовая линия обновлена: ${Object.keys(sorted).length} семей.`);
  process.exit(0);
}

if (!existsSync(BASELINE)) {
  console.error(`ERROR: нет базовой линии ${BASELINE}. Создать: node tests/skills/check-inline-drift.mjs --update`);
  process.exit(1);
}
const baseline = JSON.parse(readFileSync(BASELINE, 'utf8')).families;

if (listMode) {
  const rows = Object.entries(current).sort((a, b) => b[1].variants - a[1].variants || b[1].skills - a[1].skills);
  console.log('Семья (вариантов / навыков), по убыванию разброса:');
  for (const [key, v] of rows) console.log(`  ${String(v.variants).padStart(3)} / ${String(v.skills).padStart(3)}  ${key}`);
  console.log('');
}

const grown = [];      // разброс вырос - регресс
const shrunk = [];     // разброс упал - линию пора подтянуть
const appeared = [];   // новая семья с разбросом

for (const [key, v] of Object.entries(current)) {
  const base = baseline[key];
  if (!base) {
    if (v.variants > 1) appeared.push({ key, ...v });
    continue;
  }
  if (v.variants > base.variants) grown.push({ key, was: base.variants, now: v.variants });
  else if (v.variants < base.variants) shrunk.push({ key, was: base.variants, now: v.variants });
}
const vanished = Object.keys(baseline).filter((k) => !(k in current));

const unified = Object.values(current).filter((v) => v.variants === 1).length;
console.log(`Семей: ${Object.keys(current).length}, из них едины: ${unified}`);

let bad = 0;
if (grown.length) {
  bad += grown.length;
  console.error(`\nРАЗЪЕХАЛОСЬ (${grown.length}) - копии разошлись сильнее, чем было:`);
  for (const g of grown) console.error(`  ${g.key}: было вариантов ${g.was}, стало ${g.now}`);
}
if (appeared.length) {
  bad += appeared.length;
  console.error(`\nНОВЫЕ СЕМЬИ С РАЗБРОСОМ (${appeared.length}) - копия заведена сразу разной:`);
  for (const a of appeared) console.error(`  ${a.key}: вариантов ${a.variants} в ${a.skills} навыках`);
}
// Сужение разброса тоже роняет прогон, и это не придирка: пока линия не подтянута, ничто не мешает
// вернуть прежнее число вариантов - храповик провернется обратно, и никто не заметит. Чинится одной
// командой, зато выигрыш закрепляется.
if (shrunk.length || vanished.length) {
  bad += shrunk.length + vanished.length;
  console.error(`\nЛИНИЯ УСТАРЕЛА В ЛУЧШУЮ СТОРОНУ (${shrunk.length + vanished.length}) - подтяните ее, иначе выигрыш не закреплен:`);
  for (const s of shrunk) console.error(`  ${s.key}: было вариантов ${s.was}, стало ${s.now}`);
  for (const v of vanished) console.error(`  ${v}: семьи больше нет`);
  console.error('  Обновить: node tests/skills/check-inline-drift.mjs --update');
}

if (bad) {
  console.error(`\n${bad} расхождений с базовой линией.`);
  process.exit(1);
}
console.log('OK - разброс общих реализаций не вырос.');
