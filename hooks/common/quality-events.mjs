// quality-events.mjs - запись событий следа проверок хуками набора.
// Спецификация - skills/1c-code-review/references/evidence-format.md; Python-реализация
// того же каталога - tools/quality_events.py (ее читает tools/evidence.py). Схема записи
// совпадает: номер последовательности резервируется lock-файлом (открытие с 'wx'),
// тело - JSON с сортировкой ключей, отступом 2 и завершающим переводом строки, запись
// временным файлом с переименованием. Экспорт предназначен hooks/evidence-writer.mjs и
// hooks/release-writer.mjs.

import { createHash, randomUUID } from 'node:crypto';
import { mkdir, open, rm, writeFile, readdir, stat } from 'node:fs/promises';
import { execFile as execFileCb } from 'node:child_process';
import { rename, constants } from 'node:fs';
import { promisify } from 'node:util';
import { dirname, join } from 'node:path';

const execFile = promisify(execFileCb);
const renameP = promisify(rename);

// Идентификатор сессии: буква-цифра-подчеркивание-точка-дефис, без разделителей пути.
export const SESSION_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export class EventsError extends Error {}

// Корень git-репозитория: каталог следа один на репозиторий (tools/quality_events.py,
// repo_top). Отказ git и не-репозиторий - EventsError.
export async function repoTop(cwd) {
  try {
    const { stdout } = await execFile('git', ['rev-parse', '--show-toplevel'],
                                      { cwd, maxBuffer: 16 * 1024 * 1024 });
    return stdout.toString('utf8').trim();
  } catch (err) {
    const stderr = Buffer.isBuffer(err.stderr) ? err.stderr.toString('utf8') : String(err.stderr || '');
    throw new EventsError(`каталог не является git-репозиторием: ${cwd}${stderr ? `: ${stderr.trim()}` : ''}`);
  }
}

// Каталог событий сессии. Недопустимый идентификатор - EventsError.
export function eventsDir(top, session) {
  if (!SESSION_RE.test(session || '')) {
    throw new EventsError(`недопустимый идентификатор сессии: ${session}`);
  }
  return join(top, '.claude', '.state', 'quality', session, 'events');
}

// Рекурсивно отсортировать ключи объектов: сериализация совпадает с
// json.dumps(sort_keys=True) из tools/quality_events.py (ключи событий - ASCII).
export function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeysDeep(value[key]);
    return out;
  }
  return value;
}

// Момент в ISO 8601 с зоной и миллисекундами - локальное время со смещением зоны, как
// datetime.now().astimezone().isoformat() в tools/quality_events.py. Компоненты
// локального времени идут и в имя файла события; UTC отсортировался бы раньше
// Python-событий той же сессии.
export function formatIso(d) {
  const offsetMin = -d.getTimezoneOffset();
  const sign = offsetMin >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMin);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    + `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
    + `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

// Текущее время в том же формате (поле at события).
export function nowIso() {
  return formatIso(new Date());
}

// Часть имени файла из времени события: YYYY-MM-DDTHHMMSS-<мс> (как
// tools/quality_events.py, f"{stamp:%Y-%m-%dT%H%M%S}-{мс}"), самолексикографична.
function timePart(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?/.exec(iso);
  if (!m) throw new EventsError(`время события не ISO 8601: ${iso}`);
  const ms = (m[7] || '0').padEnd(3, '0').slice(0, 3);
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}${m[5]}${m[6]}-${ms}`;
}

// Занять номер последовательности отметки времени созданием lock-файла (O_CREAT|O_EXCL).
// Занятый номер перебирается дальше; lock-файлы остаются как занятые номера.
async function acquireSeq(sessionDir, stamp) {
  const { O_CREAT, O_EXCL, O_WRONLY } = constants;
  for (let seq = 0; ; seq++) {
    try {
      const handle = await open(join(sessionDir, `${stamp}-${String(seq).padStart(6, '0')}.lock`),
                               O_CREAT | O_EXCL | O_WRONLY, 0o644);
      await handle.close();
      return seq;
    } catch (err) {
      if (err.code !== 'EEXIST') throw new EventsError(`lock последовательности: ${err.message}`);
    }
  }
}

// Записать событие атомарно и вернуть путь файла. Каталог создается при отсутствии.
export async function writeEvent(top, session, event) {
  const targetDir = eventsDir(top, session);
  const sessionDir = dirname(targetDir);
  await mkdir(targetDir, { recursive: true });
  const stamp = timePart(String(event.at || ''));
  const producer = String(event.producer || 'hook');
  if (!/^[a-z]+$/.test(producer)) throw new EventsError(`недопустимый producer: ${producer}`);
  const seq = await acquireSeq(sessionDir, stamp);
  const payload = JSON.stringify(sortKeysDeep(event), null, 2) + '\n';
  // Занятое имя (коллизия случайного id) перегенерируется с тем же номером lock.
  while (true) {
    const id = randomUUID().replace(/-/g, '').slice(0, 6);
    const final = join(targetDir, `${stamp}-${String(seq).padStart(6, '0')}-${producer}-${id}.json`);
    try {
      const tmp = join(targetDir, `.tmp-${randomUUID().replace(/-/g, '')}`);
      await writeFile(tmp, payload, 'utf8');
      await renameP(tmp, final);
      return final;
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
    }
  }
}

// Список файлов каталога (без .lock и временных); отсутствующий каталог - пустой список.
export async function listEventFiles(top, session) {
  let dir;
  try {
    dir = eventsDir(top, session);
    const names = await readdir(dir);
    return names.filter((n) => n.endsWith('.json')).sort();
  } catch (err) {
    if (err.code === 'ENOENT') return [];
    throw err;
  }
}

// Вычистить каталоги сессий старше ttlMs (по времени изменения каталога сессии; его
// обновляет каждое событие - lock-файлы создаются именно там). Возвращает число удаленных.
export async function sweepStaleSessions(top, ttlMs) {
  const root = join(top, '.claude', '.state', 'quality');
  let names;
  try {
    names = await readdir(root);
  } catch (err) {
    if (err.code === 'ENOENT') return 0;
    throw err;
  }
  let removed = 0;
  for (const name of names) {
    const sessionDir = join(root, name);
    try {
      const info = await stat(sessionDir);
      if (info.isDirectory() && Date.now() - info.mtimeMs > ttlMs) {
        await rm(sessionDir, { recursive: true, force: true });
        removed++;
      }
    } catch {
      // каталог чужой или уже удален параллельным хуком - пропустить
    }
  }
  return removed;
}

// sha256 строки в hex (хеши inputHash/responseHash).
export function sha256Hex(text) {
  return createHash('sha256').update(String(text), 'utf8').digest('hex');
}
