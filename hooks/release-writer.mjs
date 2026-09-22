// release-writer.mjs - хук UserPromptSubmit: записывает событие release следа проверок
// по команде снятия, набранной пользователем. Модель промпты не отправляет, источник
// снятия всегда человек (source: user_prompt). Синтаксис команды:
//   /quality release gate <причина> [--for 30m|2h|1d]
//   /quality release check <проверка@среда> <причина> [--for 30m|2h|1d]
// Срок по умолчанию 4 часа; expiresAt - ISO 8601 с зоной. Любой другой промпт - выход 0
// без вывода. Внутренняя ошибка - выход 0 со строкой в stderr.
//
// stdin: UserPromptSubmit JSON { prompt, session_id, cwd, ... }.

import { computeChangeset } from './_changeset.mjs';
import { formatIso, repoTop, writeEvent } from './common/quality-events.mjs';

const RELEASE_PREFIX = '/quality release ';
const DEFAULT_TTL_MS = 4 * 60 * 60 * 1000;
const TTL_RE = /--for[ \t]+(\d+)([mhd])(?![\w])/;
const TTL_UNITS = { m: 60 * 1000, h: 60 * 60 * 1000, d: 24 * 60 * 60 * 1000 };
const CHECK_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:@-]*$/;

// Разобрать команду снятия: область (gate | check <идентификатор>), причина и срок.
// Возвращает { scope, check, reason, ttlMs } либо { parseError }.
export function parseReleaseCommand(prompt) {
  const body = String(prompt || '').slice(RELEASE_PREFIX.length).trim();
  const ttlMatch = TTL_RE.exec(body);
  let ttlMs = DEFAULT_TTL_MS;
  let rest = body;
  if (ttlMatch) {
    const value = Number(ttlMatch[1]);
    if (value <= 0) return { parseError: 'срок снятия должен быть положительным' };
    ttlMs = value * TTL_UNITS[ttlMatch[2]];
    rest = body.replace(ttlMatch[0], '').trimEnd();
  }
  const words = rest.split(/\s+/);
  const area = words[0];
  if (area === 'gate') {
    const reason = rest.slice(area.length).trim();
    if (!reason) return { parseError: 'не указана причина снятия' };
    return { scope: 'gate', check: null, reason, ttlMs };
  }
  if (area === 'check') {
    const check = words[1] || '';
    if (!CHECK_ID_RE.test(check)) {
      return { parseError: 'не указан идентификатор проверки (например validate_query@edt)' };
    }
    const reason = rest.slice(area.length + 1 + check.length).trim();
    if (!reason) return { parseError: 'не указана причина снятия' };
    return { scope: 'check', check, reason, ttlMs };
  }
  return { parseError: 'область снятия - gate либо check' };
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает
// { stdout, stderr }: stdout - JSON с additionalContext, stderr - диагностика.
export async function processPayload(payload, now = () => new Date()) {
  if (!payload || typeof payload !== 'object' || typeof payload.prompt !== 'string') {
    return { stdout: '', stderr: '' };
  }
  if (!payload.prompt.startsWith(RELEASE_PREFIX)) return { stdout: '', stderr: '' };
  const parsed = parseReleaseCommand(payload.prompt);
  if (parsed.parseError) {
    return {
      stdout: '',
      stderr: `[release-writer] команда снятия не разобрана: ${parsed.parseError}`,
    };
  }
  const session = typeof payload.session_id === 'string' ? payload.session_id : '';
  if (!session) return { stdout: '', stderr: '[release-writer] payload без session_id' };
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  let top;
  try {
    top = await repoTop(cwd);
  } catch (err) {
    return { stdout: '', stderr: `[release-writer] ${err.message}` };
  }
  let diffHash = null;
  try {
    diffHash = (await computeChangeset(cwd, 'HEAD')).diffHash;
  } catch (err) {
    process.stderr.write(`[release-writer] diffHash не вычислен: ${err.message}\n`);
  }
  const expiresAt = formatIso(new Date(now().getTime() + parsed.ttlMs));
  const event = {
    type: 'release',
    at: formatIso(now()),
    session,
    producer: 'hook',
    diffHash,
    scope: parsed.scope,
    reason: parsed.reason,
    source: 'user_prompt',
    expiresAt,
  };
  if (parsed.scope === 'check') event.check = parsed.check;
  try {
    await writeEvent(top, session, event);
  } catch (err) {
    return { stdout: '', stderr: `[release-writer] ${err.message}` };
  }
  const what = parsed.scope === 'gate' ? 'гейт целиком' : `проверка ${parsed.check}`;
  const out = JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: `снятие записано: ${what}, до ${expiresAt}. Причина: ${parsed.reason}`,
    },
  });
  return { stdout: out, stderr: '' };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('release-writer.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const { stdout, stderr } = await processPayload(payload);
    if (stdout) process.stdout.write(stdout + '\n');
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[release-writer] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
