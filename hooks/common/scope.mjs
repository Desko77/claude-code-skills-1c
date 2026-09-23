// scope.mjs - ограничение хука списком корней воркспейсов (довод --only).
// Пустой список - хук работает в любом каталоге. Ошибка разбора не выключает хук:
// ограничение снимается, вызывающий пишет строку в stderr.

import { realpathSync } from 'node:fs';

export const ONLY_PARSE_ERROR = '[scope] довод --only без значения, ограничение не применяется';

// Повторяемый --only <путь> из argv. Ошибка (нет значения) - пустой список и строка.
export function parseOnlyArgs(argv = process.argv) {
  const roots = [];
  const args = argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    if (args[i] !== '--only') continue;
    const value = args[i + 1];
    if (value === undefined || value === '' || value.startsWith('-')) {
      return { roots: [], error: ONLY_PARSE_ERROR };
    }
    roots.push(value);
    i += 1;
  }
  return { roots, error: null };
}

// Каталог после realpath (отказ - путь как есть), слеши /, без завершающего /,
// на win32 в нижнем регистре.
function normalizeDir(p) {
  let resolved = String(p);
  try {
    resolved = realpathSync.native(resolved);
  } catch {
    // каталога нет - сравниваем строку как есть
  }
  let text = resolved.replace(/\\/g, '/');
  while (text.length > 1 && text.endsWith('/')) text = text.slice(0, -1);
  if (process.platform === 'win32') text = text.toLowerCase();
  return text;
}

// Список пуст - да. Иначе cwd равен корню либо лежит внутри него.
export function directoryInScope(cwd, roots) {
  if (!roots || roots.length === 0) return true;
  const dir = normalizeDir(cwd);
  for (const root of roots) {
    const base = normalizeDir(root);
    if (!base) continue;
    if (dir === base || dir.startsWith(`${base}/`)) return true;
  }
  return false;
}

// cwd из payload, без него - process.cwd(). error - строка в stderr, skip - выйти
// кодом 0 до любой работы.
export function scopeStatus(payload, argv = process.argv) {
  const parsed = parseOnlyArgs(argv);
  if (parsed.error) return { skip: false, error: parsed.error };
  const cwd = payload && typeof payload === 'object' && typeof payload.cwd === 'string' && payload.cwd
    ? payload.cwd
    : process.cwd();
  if (!directoryInScope(cwd, parsed.roots)) return { skip: true, error: null };
  return { skip: false, error: null };
}
