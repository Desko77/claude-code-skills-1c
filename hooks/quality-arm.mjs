// quality-arm.mjs - хук PostToolUse: атрибуция правки инструменту. По факту записи через
// инструменты Write/Edit/MultiEdit/NotebookEdit и MCP-инструменты записи AI-EDT
// (write_module_source, edit_metadata, edit_form, config_io, мастерские *_workshop) пишет
// событие armed следа с файлом, инструментом и toolUseId. Это атрибуция, не источник
// полноты: правки сессии гейт завершения хода считает по каноническому множеству против
// базовой отметки (hooks/quality-stop.mjs). Внутренняя ошибка - выход 0 со строкой в stderr.
//
// stdin: PostToolUse JSON { tool_name, tool_input, tool_use_id, session_id, cwd }.
//
// Единственный источник выражения: строки матчера в hooks/hooks.json сверяются с константой
// ARM_MATCHER гардом tests/hooks/matcher-guard.test.mjs.

import { computeChangeset } from './_changeset.mjs';
import { nowIso, repoTop, writeEvent } from './common/quality-events.mjs';
import { scopeStatus } from './common/scope.mjs';

export const ARM_MATCHER =
  '^(Write|Edit|MultiEdit|NotebookEdit'
  + '|mcp__[A-Za-z0-9._-]+__(write_module_source|edit_metadata|edit_form|config_io|[a-z_]+_workshop))$';

const ARM_RE = new RegExp(ARM_MATCHER);

// Ключи доводов с путем или именем цели записи в порядке приоритета.
const FILE_KEYS = ['file_path', 'modulePath', 'fqn', 'inputPath'];

function pickFile(toolInput) {
  if (!toolInput || typeof toolInput !== 'object') return null;
  for (const key of FILE_KEYS) {
    if (typeof toolInput[key] === 'string' && toolInput[key]) return toolInput[key];
  }
  return null;
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает { stderr } для кода
// выхода 0; stdout не используется.
export async function processPayload(payload) {
  if (!payload || typeof payload !== 'object' || typeof payload.session_id !== 'string'
      || !payload.session_id) {
    return { stderr: '' };
  }
  const toolName = String(payload.tool_name || '');
  if (!ARM_RE.test(toolName)) return { stderr: '' };
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  let top;
  try {
    top = await repoTop(cwd);
  } catch (err) {
    return { stderr: `[quality-arm] ${err.message}` };
  }
  let diffHash = null;
  try {
    diffHash = (await computeChangeset(cwd, 'HEAD')).diffHash;
  } catch {
    // отметка атрибуции без хеша множества остается валидной
  }
  const event = {
    type: 'armed',
    at: nowIso(),
    session: payload.session_id,
    producer: 'hook',
    diffHash,
    file: pickFile(payload.tool_input),
    tool: toolName,
    toolUseId: typeof payload.tool_use_id === 'string' ? payload.tool_use_id : null,
  };
  try {
    await writeEvent(top, payload.session_id, event);
  } catch (err) {
    return { stderr: `[quality-arm] ${err.message}` };
  }
  return { stderr: '' };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('quality-arm.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const scope = scopeStatus(payload);
    if (scope.error) process.stderr.write(`${scope.error}\n`);
    if (scope.skip) process.exit(0);
    const { stderr } = await processPayload(payload);
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[quality-arm] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
