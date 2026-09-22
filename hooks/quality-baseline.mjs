// quality-baseline.mjs - хук SessionStart: базовая отметка сессии для гейта завершения
// хода. Один раз на session_id: если в каталоге сессии еще нет события baseline - пишет
// его с HEAD и каноническим множеством изменений с хешами содержимого на момент старта.
// При resume, compact и clear существующая отметка не трогается. Вне git-репозитория
// пишется отметка с head: null и пустым множеством - гейт завершения хода тогда не
// применяется. Внутренняя ошибка - выход 0 со строкой в stderr.
//
// stdin: SessionStart JSON { source, session_id, cwd, ... }.

import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { buildDiffPayload, computeChangeset } from './_changeset.mjs';
import { EventsError, nowIso, repoTop, writeEvent } from './common/quality-events.mjs';
import { findBaseline, resolveHead } from './common/quality-gate.mjs';

// diffHash пустого множества: та же формула, что у computeChangeset на пустом списке.
function emptyChangeset() {
  return { base: null, diffHash: createHash('sha256').update(buildDiffPayload([])).digest('hex'),
    files: [] };
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает { stderr } для
// кода выхода 0; stdout не используется.
export async function processPayload(payload, log = () => {}) {
  if (!payload || typeof payload !== 'object' || typeof payload.session_id !== 'string'
      || !payload.session_id) {
    return { stderr: '' };
  }
  const session = payload.session_id;
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  let top;
  let outsideGit = '';
  try {
    top = await repoTop(cwd);
  } catch (err) {
    // Вне git отметка пишется от cwd как от корня: head null, пустое множество.
    top = resolve(cwd);
    outsideGit = err instanceof EventsError ? err.message : String(err);
  }
  try {
    if (await findBaseline(top, session)) return { stderr: '' }; // отметка уже есть
  } catch (err) {
    return { stderr: `[quality-baseline] чтение каталога событий: ${err.message}` };
  }
  const head = outsideGit ? null : await resolveHead(cwd);
  let changeset = emptyChangeset();
  if (head) {
    try {
      const cs = await computeChangeset(cwd, head);
      changeset = { base: cs.base, diffHash: cs.diffHash, files: cs.files };
    } catch (err) {
      log(`[quality-baseline] множество не вычислено, отметка с пустым множеством: ${err.message}`);
      changeset = emptyChangeset();
    }
  }
  const event = {
    type: 'baseline',
    at: nowIso(),
    session,
    producer: 'hook',
    diffHash: changeset.diffHash,
    head,
    changeset,
    cwd,
  };
  try {
    await writeEvent(top, session, event);
  } catch (err) {
    return { stderr: `[quality-baseline] ${err.message}` };
  }
  return { stderr: outsideGit ? `[quality-baseline] вне git-репозитория: ${outsideGit}` : '' };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('quality-baseline.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const { stderr } = await processPayload(payload, (msg) => process.stderr.write(`${msg}\n`));
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[quality-baseline] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
