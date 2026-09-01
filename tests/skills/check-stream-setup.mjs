#!/usr/bin/env node
// Инвариант: поток вывода в скриптах навыков настраивается ОДНИМ способом, и навык,
// заявивший работу на стандартной библиотеке, ее не покидает.
//
// Обе проверки статические, потому что кейсами они не ловятся. Подмена потока через
// codecs дает отказ только на Windows, а отсутствующая внешняя зависимость - только на
// машине, где ее не установили. И то и другое проявляется у пользователя, а не на
// прогоне.
//
// Первая проверка сформулирована через ОТСУТСТВИЕ устаревшего способа, а не через запрет
// сочетания: файл, где осталась только подмена, тоже неверен, хотя исключения не дает.
//
// Область второй проверки сужена намеренно. Список ниже - навыки, чье описание обещает
// только стандартную библиотеку. Навык, объявивший зависимость, под нее не подпадает.
//
// Выход 1 при нарушении. Запуск: node tests/skills/check-stream-setup.mjs
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SKILLS = join(ROOT, 'skills');

// Навыки, обещающие в описании работу без внешних зависимостей.
const STDLIB_ONLY = new Set(['1c-vanessa-steps']);

// Подмена потока писателем из codecs: несовместима с последующей перенастройкой и
// заменена во всем наборе на reconfigure.
const RE_CODECS = /codecs\.getwriter\s*\([^)]*\)\s*\(\s*sys\.std(out|err)\.buffer/;
const RE_YAML = /^\s*(import\s+yaml|from\s+yaml\s+import)\b/m;

function* pyScripts() {
  for (const skill of readdirSync(SKILLS)) {
    const dir = join(SKILLS, skill, 'scripts');
    let entries;
    try {
      entries = readdirSync(dir);
    } catch {
      continue;
    }
    for (const name of entries) {
      const file = join(dir, name);
      if (!name.endsWith('.py') || !statSync(file).isFile()) continue;
      yield { skill, file };
    }
  }
}

let failures = 0;
let checked = 0;

for (const { skill, file } of pyScripts()) {
  checked++;
  const text = readFileSync(file, 'utf8');
  const rel = relative(ROOT, file).replace(/\\/g, '/');

  if (RE_CODECS.test(text)) {
    console.error(`  ПОДМЕНА ПОТОКА: ${rel}`);
    console.error(`    codecs.getwriter поверх sys.std*.buffer; в наборе принят reconfigure`);
    failures++;
  }

  if (STDLIB_ONLY.has(skill) && RE_YAML.test(text)) {
    console.error(`  ВНЕШНЯЯ ЗАВИСИМОСТЬ: ${rel}`);
    console.error(`    навык ${skill} обещает только стандартную библиотеку, а импортирует yaml`);
    failures++;
  }
}

if (failures) {
  console.error(`\nНастройка потоков и зависимости: нарушений ${failures}`);
  process.exit(1);
}
console.log(`Настройка потоков и зависимости: проверено скриптов ${checked}, нарушений нет`);
