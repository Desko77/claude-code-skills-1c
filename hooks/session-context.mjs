// session-context.mjs - хук SessionStart: сообщает модели идентификатор сессии следа
// проверок и путь каталога событий (передается в CLI доводом --session), вычищает
// каталоги сессий старше 7 дней. Работает одинаково для source startup, resume, clear,
// compact и fork. Внутренняя ошибка - выход 0 со строкой в stderr.
//
// stdin: SessionStart JSON { source, session_id, cwd, ... }.

import { EventsError, eventsDir, repoTop, sweepStaleSessions } from './common/quality-events.mjs';

const STALE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

// Основная логика, отделенная от чтения stdin для тестов. Возвращает
// { stdout, stderr } для кода выхода 0.
export async function processPayload(payload) {
  if (!payload || typeof payload !== 'object' || typeof payload.session_id !== 'string'
      || !payload.session_id) {
    return { stdout: '', stderr: '' };
  }
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  const session = payload.session_id;
  let top;
  try {
    top = await repoTop(cwd);
  } catch (err) {
    return { stdout: '', stderr: `[session-context] ${err instanceof EventsError ? err.message : String(err)}` };
  }
  let swept = 0;
  try {
    swept = await sweepStaleSessions(top, STALE_TTL_MS);
  } catch (err) {
    // очистка вспомогательная: сбой не мешает сообщить сессию
    process.stderr.write(`[session-context] очистка не выполнена: ${err.message}\n`);
  }
  let dir;
  try {
    dir = eventsDir(top, session);
  } catch (err) {
    return { stdout: '', stderr: `[session-context] ${err.message}` };
  }
  const context = `сессия: ${session}\nкаталог событий: ${dir}`;
  const out = JSON.stringify({
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
  });
  return { stdout: out, stderr: swept ? `[session-context] вычищено устаревших сессий: ${swept}` : '' };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('session-context.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const { stdout, stderr } = await processPayload(payload);
    if (stdout) process.stdout.write(stdout + '\n');
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[session-context] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
