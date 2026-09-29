// quality-gate.mjs - общий код гейта завершения хода: базовая отметка, правки сессии,
// файлы 1С, база diffHash сессии, путь к валидатору следа. Пользователи -
// hooks/quality-baseline.mjs, hooks/quality-stop.mjs и писатели событий; спецификация -
// skills/1c-code-review/references/evidence-format.md (типы baseline и armed).
// Правка сессии = файл канонического множества (hooks/_changeset.mjs), чей хеш
// отличается от хеша в отметке или которого в отметке нет, и на который есть
// событие этой сессии (armed либо applied/failed с целью-файлом); учитываются
// только файлы 1С.

import { access, readFile } from 'node:fs/promises';
import { execFile as execFileCb } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { computeChangeset } from '../_changeset.mjs';
import { claudeHome } from './home.mjs';
import { eventsDir, listEventFiles } from './quality-events.mjs';

const execFile = promisify(execFileCb);

// Расширения файлов 1С; XML выгрузки Конфигуратора - Configuration.xml в корне либо
// любой .xml с сегментом Ext/ в пути. Сравнение без учета регистра: выгрузка на Windows
// дает те же имена.
const ONEC_EXTENSIONS = ['.bsl', '.os', '.mdo', '.form', '.dcs', '.mxlx', '.cmi', '.rights', '.xdto'];

export function is1cFile(path) {
  const p = String(path || '').toLowerCase();
  if (ONEC_EXTENSIONS.some((ext) => p.endsWith(ext))) return true;
  if (!p.endsWith('.xml')) return false;
  return p === 'configuration.xml' || /(^|\/)ext\//.test(p);
}

// Найти событие baseline сессии: последнее по имени файла с type=baseline. Поврежденный
// JSON пропускается (гейт увидит отметку среди целых файлов либо сообщит об отсутствии).
// Возвращает событие либо null.
export async function findBaseline(top, session) {
  const dir = eventsDir(top, session);
  for (const name of [...await listEventFiles(top, session)].reverse()) {
    try {
      const data = JSON.parse(await readFile(join(dir, name), 'utf8'));
      if (data && data.type === 'baseline') return data;
    } catch {
      // поврежденный или недоступный файл - не отметка
    }
  }
  return null;
}

// Последнее событие scope сессии (любой diffHash) - источник перечня обязательных
// проверок для текста блока. Возвращает событие либо null.
export async function findLastScope(top, session) {
  const dir = eventsDir(top, session);
  for (const name of [...await listEventFiles(top, session)].reverse()) {
    try {
      const data = JSON.parse(await readFile(join(dir, name), 'utf8'));
      if (data && data.type === 'scope') return data;
    } catch {
      // поврежденный файл пропускается
    }
  }
  return null;
}

// Ключ сравнения путей события и множества: на Windows без учета регистра -
// инструмент и выгрузка дают один и тот же файл в разном регистре.
function pathKey(p) {
  return process.platform === 'win32' ? p.toLowerCase() : p;
}

// Приведение пути события (абсолютный либо относительный корню репозитория) к виду
// путей канонического множества: прямые слеши, NFC. Путь вне репозитория - null.
function toChangesetPath(file, top) {
  const p = String(file).replace(/\\/g, '/');
  const isAbsolute = /^[A-Za-z]:\//.test(p) || p.startsWith('/');
  if (!isAbsolute) return p.normalize('NFC');
  const topNorm = String(top).replace(/\\/g, '/').replace(/\/+$/, '');
  if (!pathKey(p).startsWith(`${pathKey(topNorm)}/`)) return null;
  return p.slice(topNorm.length + 1).normalize('NFC');
}

// Файлы, названные событиями сессии: armed (правка инструментом записи) и
// applied/failed (проверка с целью в target). Правка человека в EDT и правка
// другой сессии в том же репозитории событий здесь не имеют и правками сессии
// не считаются.
async function sessionTouchedPaths(top, session) {
  const keys = new Set();
  let names;
  try {
    names = await listEventFiles(top, session);
  } catch {
    return keys;
  }
  const dir = eventsDir(top, session);
  for (const name of names) {
    let event;
    try {
      event = JSON.parse(await readFile(join(dir, name), 'utf8'));
    } catch {
      continue;
    }
    const type = event && event.type;
    const file = type === 'armed' ? event.file
      : (type === 'applied' || type === 'failed') ? event.target : null;
    if (typeof file !== 'string' || !file) continue;
    const rel = toChangesetPath(file, top);
    if (rel) keys.add(pathKey(rel));
  }
  return keys;
}

// Правки сессии в файлах 1С: каноническое множество относительно базового коммита
// отметки против хешей отметки, ограниченное файлами со событиями сессии (armed,
// applied/failed). Возвращает [{ path, status }]; пустой список - правок нет
// или отметка неприменима (head null). Изменение с сеансом коммитов не скрывает:
// множество считается от того же base, закоммиченный за сессию файл остается
// в множестве.
export async function sessionEdits(cwd, baseline, top, session) {
  if (!baseline || typeof baseline !== 'object' || !baseline.head
      || !baseline.changeset || !Array.isArray(baseline.changeset.files)) {
    return null; // отметка без HEAD: гейт не применяется
  }
  const current = await computeChangeset(cwd, baseline.head);
  const touched = top && session ? await sessionTouchedPaths(top, session) : null;
  const marked = new Map(baseline.changeset.files.map((f) => [f.path, f.sha256]));
  const edits = [];
  for (const file of current.files) {
    if (!is1cFile(file.path)) continue;
    const was = marked.get(file.path);
    if (was === undefined || was !== file.sha256) {
      if (touched && !touched.has(pathKey(file.path))) continue;
      edits.push({ path: file.path, status: file.status });
    }
  }
  return edits;
}

// HEAD репозитория либо null (нет коммитов, git недоступен).
export async function resolveHead(cwd) {
  try {
    const { stdout } = await execFile('git', ['rev-parse', 'HEAD'],
                                      { cwd, maxBuffer: 16 * 1024 * 1024 });
    return stdout.toString('utf8').trim() || null;
  } catch {
    return null;
  }
}

// База diffHash событий сессии: HEAD из события baseline. Все писатели событий
// и валидатор считают хеш от одной базы, и коммит по ходу сессии не расщепляет
// прогон: иначе Stop требует прогон от отметки, а хуки и CLI пишут события от
// текущего HEAD. Нет отметки или отметка без HEAD - текущий HEAD.
export async function sessionBase(cwd, top, session) {
  let baseline = null;
  try {
    baseline = await findBaseline(top, session);
  } catch {
    return 'HEAD';
  }
  return baseline && typeof baseline.head === 'string' && baseline.head ? baseline.head : 'HEAD';
}

// Путь к tools/evidence.py в порядке поиска: CLAUDE_PLUGIN_ROOT/tools/evidence.py,
// ../tools от каталога хуков (репозиторий набора), домашняя установка
// <дом>/.claude/tools/1c-skills/evidence.py. null - не найден.
export async function resolveEvidencePy() {
  const hookDir = dirname(dirname(fileURLToPath(import.meta.url)));
  const candidates = [];
  if (process.env.CLAUDE_PLUGIN_ROOT) {
    candidates.push(join(process.env.CLAUDE_PLUGIN_ROOT, 'tools', 'evidence.py'));
  }
  candidates.push(join(hookDir, '..', 'tools', 'evidence.py'));
  candidates.push(join(claudeHome(), '.claude', 'tools', '1c-skills', 'evidence.py'));
  for (const path of candidates) {
    try {
      await access(path);
      return path;
    } catch {
      // кандидат отсутствует - следующий
    }
  }
  return null;
}
