// repeat-failure.mjs - хук PostToolUseFailure: подряд идущие одинаковые падения одного
// вызова с той же ошибкой. На третьем таком падении и каждом следующем в контекст модели
// уходит указание сменить подход или спросить пользователя. Хук ничего не блокирует:
// stdout - только additionalContext, код выхода 0. Основание - документация Anthropic по
// промптингу Opus 5.5: автоматические повторы одной задачи останавливают после двух-трех.
//
// Подпись падения - имя инструмента и первая непустая строка ошибки после нормализации
// (числа -> N, пути и строки в кавычках -> <p>, пробелы свернуты, длина не больше 200).
// Состояние сессии - <домашний каталог>/.claude/state/repeat-failure/<session_id>.json:
// подпись последнего падения и счетчик. Другая подпись начинает счет заново. Файлы и
// каталоги старше 7 дней удаляются при записи. Переменная REPEAT_FAILURE_OFF со значением
// кроме пустого и 0 выключает хук. Поле cursor_version во входе означает, что хук исполняет
// Cursor, - выход без вывода. Внутренняя ошибка - выход 0 со строкой в stderr.
//
// stdin: PostToolUseFailure JSON { session_id, tool_name, tool_input, error, cwd };

import { createHash } from 'node:crypto';
import { mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { claudeHome } from './common/home.mjs';
import { SESSION_RE } from './common/quality-events.mjs';
import { scopeStatus } from './common/scope.mjs';

// Порог подряд идущих одинаковых падений: с него и дальше хук говорит в контекст.
export const THRESHOLD = 3;

// Срок жизни записи состояния сессии.
export const STALE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

// Предельная длина подписи.
const SIGNATURE_LIMIT = 200;

// Строки в кавычках - обычные, угловые (коды 00AB и 00BB) и обратные.
const QUOTED_RE = /"[^"\n]*"|'[^'\n]*'|\u00ab[^\u00bb\n]*\u00bb|`[^`\n]*`/g;

// Сетевой путь (два обратных слеша) или путь с буквой диска; двоеточие номера строки
// остается за подписью. Оба выражения идут после кавычек: путь в кавычках уже заменен.
const UNC_PATH_RE = /\\\\[^\s"']+/g;
const WINDOWS_PATH_RE = /[A-Za-z]:[\\/][^\s"':]*/g;

// Путь вида /a/b (не меньше двух сегментов); ведущий пробел сохраняется.
const UNIX_PATH_RE = /(^|\s)(?:\/[^\s"'/:]+){2,}/g;

// Подпись падения: имя инструмента и нормализованная первая непустая строка ошибки.
export function failureSignature(toolName, error) {
  const raw = typeof error === 'string' ? error : '';
  const line = raw.split(/\r?\n/).find((part) => part.trim() !== '') || '';
  let text = line.trim();
  text = text.replace(QUOTED_RE, '<p>');
  text = text.replace(UNC_PATH_RE, '<p>');
  text = text.replace(WINDOWS_PATH_RE, '<p>');
  text = text.replace(UNIX_PATH_RE, '$1<p>');
  text = text.replace(/\d+/g, 'N');
  text = text.replace(/\s+/g, ' ').trim();
  const prefix = toolName && text ? `${toolName}: ` : toolName;
  return (prefix + text).slice(0, SIGNATURE_LIMIT).trimEnd();
}

// База состояния: <домашний каталог>/.claude/state/repeat-failure. Домашний каталог
// берется тем же home.mjs, что и у следа проверок: подмена USERPROFILE и HOME в тестах
// уводит состояние из дома пользователя.
export function stateBase() {
  return join(claudeHome(), '.claude', 'state', 'repeat-failure');
}

// Путь записи состояния сессии.
export function stateFile(session) {
  return join(stateBase(), `${session}.json`);
}

// Переменная выключения: задана, не пуста и не 0.
export function isOff(env = process.env) {
  const value = env.REPEAT_FAILURE_OFF;
  return value !== undefined && value !== '' && value !== '0';
}

// Отпечаток аргументов вызова: разные вызовы одного инструмента с одинаковой первой
// строкой ошибки (у Bash это часто "Exit code 1") не считаются повтором. Числа
// нормализуются, чтобы повтор с другим счетчиком или временем оставался повтором.
export function inputFingerprint(toolInput) {
  const text = JSON.stringify(toolInput ?? null).replace(/\d+/g, 'N');
  return createHash('sha1').update(text).digest('hex').slice(0, 12);
}

// Состояние сессии из файла. Отсутствие, битый JSON, поля не того вида и запись старше
// STALE_TTL_MS - null, счет тогда начинается заново.
async function readState(file, now = Date.now()) {
  let raw;
  try {
    const info = await stat(file);
    if (now - info.mtimeMs > STALE_TTL_MS) return null;
    raw = await readFile(file, 'utf8');
  } catch {
    return null;
  }
  try {
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || typeof data.signature !== 'string') return null;
    const count = Number(data.count);
    if (!Number.isInteger(count) || count < 1) return null;
    return { signature: data.signature, key: typeof data.key === 'string' ? data.key : '', count };
  } catch {
    return null;
  }
}

// Удалить файлы и каталоги базы старше ttlMs по времени изменения. Сбой чтения базы и
// сбой отдельной записи - пропуск: состояние вспомогательное, ошибка очистки не мешает
// сообщению о повторных падениях.
async function sweepStale(base, ttlMs, now) {
  let entries;
  try {
    entries = await readdir(base, { withFileTypes: true });
  } catch {
    return 0;
  }
  let removed = 0;
  for (const ent of entries) {
    const path = join(base, ent.name);
    try {
      const info = await stat(path);
      if (now - info.mtimeMs <= ttlMs) continue;
      await rm(path, { recursive: true, force: true });
      removed++;
    } catch {
      // запись недоступна - пропуск
    }
  }
  return removed;
}

// Текст указания модели на пороге и дальше.
export function failureContext(count, signature) {
  return `Один и тот же вызов упал ${count} раз подряд с той же ошибкой: ${signature}.`
    + ' Не повторяй его в том же виде: смени подход или спроси пользователя';
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает { stdout, stderr }
// для кода выхода 0.
export async function processPayload(payload) {
  if (!payload || typeof payload !== 'object') return { stdout: '', stderr: '' };
  // Поле cursor_version в payload означает, что хук исполняет Cursor.
  if (payload.cursor_version !== undefined && payload.cursor_version !== null) {
    return { stdout: '', stderr: '' };
  }
  const session = payload.session_id;
  if (typeof session !== 'string' || !session) return { stdout: '', stderr: '' };
  if (!SESSION_RE.test(session)) {
    return { stdout: '', stderr: `[repeat-failure] недопустимый идентификатор сессии: ${session}` };
  }
  const tool = typeof payload.tool_name === 'string' ? payload.tool_name : '';
  if (!tool) return { stdout: '', stderr: '' };
  const signature = failureSignature(tool, payload.error);
  const key = `${signature}|${inputFingerprint(payload.tool_input)}`;
  const file = stateFile(session);
  let count = 1;
  try {
    const prev = await readState(file);
    if (prev && prev.key === key) count = prev.count + 1;
    await mkdir(stateBase(), { recursive: true });
    await writeFile(file, `${JSON.stringify({ signature, key, count })}\n`, 'utf8');
    await sweepStale(stateBase(), STALE_TTL_MS, Date.now());
  } catch (err) {
    return { stdout: '', stderr: `[repeat-failure] ${err.message}` };
  }
  if (count < THRESHOLD) return { stdout: '', stderr: '' };
  const out = JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PostToolUseFailure',
      additionalContext: failureContext(count, signature),
    },
  });
  return { stdout: out, stderr: '' };
}

// Прочитать stdin целиком как текст UTF-8.
async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('repeat-failure.mjs')) {
  try {
    if (isOff()) process.exit(0);
    let raw = await readStdin();
    if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1); // BOM в начале входа
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const scope = scopeStatus(payload);
    if (scope.error) process.stderr.write(`${scope.error}\n`);
    if (scope.skip) process.exit(0);
    const { stdout, stderr } = await processPayload(payload);
    if (stdout) process.stdout.write(`${stdout}\n`);
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[repeat-failure] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
