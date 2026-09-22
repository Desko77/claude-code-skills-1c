// evidence-writer.mjs - писатель событий applied и failed следа проверок.
// Спецификация - skills/1c-code-review/references/evidence-format.md. Запись идет по
// факту вызова инструмента проверки (PostToolUse) либо его отказа (PostToolUseFailure);
// модель события этого типа не пишет. Внутренняя ошибка хука - выход 0 со строкой в
// stderr, работа сессии не блокируется.
//
// stdin: PostToolUse / PostToolUseFailure JSON
// { tool_name, tool_input, tool_response | error, tool_use_id, session_id, cwd }.
//
// Матчер и таблица итогов - ниже; имена полей payload - документация Claude Code hooks.

import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeChangeset } from './_changeset.mjs';
import { nowIso, repoTop, sha256Hex, sortKeysDeep, writeEvent } from './common/quality-events.mjs';

// Заякоренный матчер инструментов проверки: ключ MCP-сервера содержит дефисы, точки и
// подчеркивания (mcp__ai-edt-3_1_38_92__validate_query). Bash и PowerShell ловят запуск
// скриптов набора; само решение принимает resolveCheck по команде и ответу.
export const MATCHER =
  '^(mcp__[A-Za-z0-9._-]+__(validate_query|code_review|diagnostics|validate_for_export|' +
  'security_audit|check_1c_code|ask_1c_ai|syntaxcheck|detect_query_anti_patterns|insights)' +
  '|Bash|PowerShell)$';

// Запуск скрипта набора в команде: skills/<скил>/scripts/<имя>-validate.ps1|py либо
// scripts/<имя>-validate.ps1|py от корня скила, оба разделителя пути.
const NABOR_SCRIPT_RE =
  /(?:skills[\\/][^\s;&|'"]*[\\/])?scripts[\\/][A-Za-z0-9._-]*(?:bsl|query|meta|role|form)-validate\.(?:ps1|py)(?![\w.-])/i;

// Строка результата скрипта набора: EVIDENCE {...} одной строкой (evidence-format.md).
const EVIDENCE_LINE_RE = /(?:^|\n)[ \t]*EVIDENCE[ \t]+(\{[^\n]*\})/;

const MCP_TOOL_RE = /^mcp__([A-Za-z0-9._-]+)__(.+)$/;

// Ключи доводов для поля target (путь модуля, FQN, проект) в порядке приоритета.
const TARGET_KEYS = ['modulePath', 'fqn', 'objectFqn', 'metadataFqn', 'filePath', 'path', 'Path',
  'projectName', 'repo', 'project'];

function pickTarget(toolInput) {
  if (!toolInput || typeof toolInput !== 'object') return null;
  for (const key of TARGET_KEYS) {
    if (typeof toolInput[key] === 'string' && toolInput[key]) return toolInput[key];
  }
  return null;
}

// Ответ инструмента в текст: строка, MCP content-массив, structuredContent либо
// канонический JSON прочей структуры.
export function responseToText(resp) {
  if (resp == null) return '';
  if (typeof resp === 'string') return resp;
  const parts = [];
  if (Array.isArray(resp.content)) {
    for (const item of resp.content) {
      if (typeof item === 'string') parts.push(item);
      else if (item && typeof item.text === 'string') parts.push(item.text);
    }
  }
  if (resp.structuredContent !== undefined) {
    try { parts.push(JSON.stringify(resp.structuredContent, null, 2)); } catch { /* ignore */ }
  }
  if (parts.length) return parts.join('\n');
  try { return JSON.stringify(resp, null, 2); } catch { return String(resp); }
}

// Канонический JSON значения (сортировка ключей) для inputHash и responseHash.
export function canonicalJson(value) {
  try { return JSON.stringify(sortKeysDeep(value)); } catch { return String(value); }
}

// Определить проверку по инструменту и доводам. Возвращает описание события либо null
// (событие не создается): не инструмент проверки, операция фасада - не проверка,
// Bash/PowerShell без запуска скрипта набора или без строки EVIDENCE в ответе.
export function resolveCheck(toolName, toolInput, responseText) {
  const m = MCP_TOOL_RE.exec(toolName || '');
  if (m) {
    const op = toolInput && typeof toolInput === 'object' ? toolInput.operation : undefined;
    switch (m[2]) {
      case 'validate_query':
        return { base: 'validate_query', check: 'validate_query@edt', detector: 'validate_query',
          level: 'semantic', env: 'edt' };
      case 'code_review':
        return { base: 'code_review', check: 'code_review@edt', detector: 'code_review',
          level: 'static', env: 'edt' };
      case 'validate_for_export':
        return { base: 'validate_for_export', check: 'validate_for_export@edt',
          detector: 'validate_for_export', level: 'semantic', env: 'edt' };
      case 'security_audit':
        return { base: 'security_audit', check: 'security_audit@edt', detector: 'security_audit',
          level: 'semantic', env: 'edt' };
      case 'ask_1c_ai':
      case 'check_1c_code':
        return { base: 'ask_1c_ai', check: 'ask_1c_ai@edt', detector: 'ask_1c_ai',
          level: 'llm', env: 'edt' };
      case 'syntaxcheck':
        return { base: 'syntaxcheck', check: 'syntaxcheck@configurator', detector: 'syntaxcheck',
          level: 'static', env: 'configurator' };
      case 'diagnostics':
        // Операции фасада: get_project_errors и validate_for_export - проверки,
        // revalidate_objects и прочие - нет.
        if (op === 'get_project_errors') {
          return { base: 'get_project_errors', check: 'get_project_errors@edt',
            detector: 'get_project_errors', level: 'semantic', env: 'edt' };
        }
        if (op === 'validate_for_export') {
          return { base: 'validate_for_export', check: 'validate_for_export@edt',
            detector: 'validate_for_export', level: 'semantic', env: 'edt' };
        }
        return null;
      case 'insights':
        if (op === 'detect_query_anti_patterns') {
          return { base: 'detect_query_anti_patterns', check: 'detect_query_anti_patterns@edt',
            detector: 'detect_query_anti_patterns', level: 'static', env: 'edt' };
        }
        return null;
      default:
        return null;
    }
  }
  if (toolName === 'Bash' || toolName === 'PowerShell') {
    const command = toolInput && typeof toolInput.command === 'string' ? toolInput.command : '';
    if (!NABOR_SCRIPT_RE.test(command)) return null;
    const line = EVIDENCE_LINE_RE.exec(responseText || '');
    if (!line) return null;
    let data;
    try { data = JSON.parse(line[1]); } catch { return null; }
    if (!data || typeof data.check !== 'string' || typeof data.status !== 'string') return null;
    return { base: 'script', check: data.check, detector: data.check.split('@')[0],
      level: 'static', env: data.check.split('@')[1] || 'configurator', evidence: data };
  }
  return null;
}

// Каталог скила 1c-code-review: CLAUDE_PLUGIN_ROOT (установка плагином) либо каталог
// над hooks/ репозитория набора.
function skillAssetRoot() {
  const hookDir = dirname(fileURLToPath(import.meta.url));
  return process.env.CLAUDE_PLUGIN_ROOT || join(hookDir, '..');
}

// Карты важностей: код диагностики bsl-language-server -> CRITICAL|MAJOR|MINOR (гейтовый
// конфиг, уровень равен важности карточки) и карточка -> Critical|Major|Minor (сводная
// матрица detectors.md). Отсутствие источников не останавливает разбор: карты пустые.
let severityMaps = null;
async function loadSeverityMaps() {
  if (severityMaps) return severityMaps;
  const diagnostic = new Map();
  const card = new Map();
  const root = skillAssetRoot();
  try {
    const conf = JSON.parse(await readFile(
      join(root, 'skills', '1c-code-review', 'assets', 'bsl-ls-gate.json'), 'utf8'));
    const meta = conf && conf.diagnostics && conf.diagnostics.metadata;
    if (meta) {
      for (const [code, info] of Object.entries(meta)) {
        if (info && typeof info.severity === 'string') diagnostic.set(code, info.severity);
      }
    }
  } catch { /* конфиг недоступен - карта диагностик пуста */ }
  try {
    const text = await readFile(
      join(root, 'skills', '1c-code-review', 'references', 'detectors.md'), 'utf8');
    for (const m of text.matchAll(/^\|\s*([A-Z]+-\d+)\s*\|\s*(Critical|Major|Minor)\s*\|/gm)) {
      card.set(m[1], m[2]);
    }
  } catch { /* сводная недоступна - карта карточек пуста */ }
  severityMaps = { diagnostic, card };
  return severityMaps;
}

// Строки-находки: содержат признак проблемы и не являются сводкой "ошибок нет".
// Отрицание привязано к самому слову-признаку, иначе текст находки ("поле не найдено")
// снимался бы как отрицание. Граница слова \b в JS не работает с кириллицей (\w без
// нее), поэтому отдельное слово ограничивается соседними не-буквами.
const FINDING_LINE_RE = /ошиб|нарушени|находк|замечан|finding|error|проблем/i;
const SUMMARY_NEGATION_RE = /(?:ошибок|ошибки|находок|находки|нарушений|нарушения|замечаний|замечания|проблемы|проблем)\s*(?:нет|:?\s*не\s+(?:обнаружено|найдено|выявлено))|отсутствуют\s+(?:ошибки|находки|нарушения|проблемы)|no\s+(?:errors|issues|findings)/i;
const PASS_RE = /ошибок нет|не обнаружено|не найдено|не выявлено|находок нет|нарушений не|замечаний нет|чисто|валиден|корректен|пройден|no\s+(?:errors|issues|findings)/i;

function findingLines(text) {
  return String(text || '').split(/\r?\n/).filter((line) => FINDING_LINE_RE.test(line) && !SUMMARY_NEGATION_RE.test(line));
}

// Подсчитать вхождения кодов диагностик по картам важностей; числа Critical/Major/Minor.
async function countDiagnostics(text) {
  const { diagnostic } = await loadSeverityMaps();
  const counts = { critical: 0, major: 0, minor: 0 };
  if (!diagnostic.size) return { counts, matched: 0 };
  let matched = 0;
  for (const [code, severity] of diagnostic) {
    const re = new RegExp(`\\b${code}\\b`, 'g');
    let hits = 0;
    for (const _m of String(text || '').matchAll(re)) hits++;
    if (hits > 0) {
      matched += hits;
      const key = { CRITICAL: 'critical', MAJOR: 'major', MINOR: 'minor' }[severity] || 'minor';
      counts[key] += hits;
    }
  }
  return { counts, matched };
}

// Важности идентификаторов карточек из строки EVIDENCE (карта detectors.md).
async function countCards(ids) {
  const { card } = await loadSeverityMaps();
  const counts = { critical: 0, major: 0, minor: 0 };
  for (const id of Array.isArray(ids) ? ids : []) {
    if (typeof id !== 'string') continue;
    const key = { Critical: 'critical', Major: 'major', Minor: 'minor' }[card.get(id)] || null;
    if (key) counts[key] += 1;
  }
  return counts;
}

// Разобрать итог проверки по инструменту. Возвращает outcome { status, critical, major,
// minor } либо status=unknown с сырым фрагментом ответа: событие пишется и валидатор
// такое событие не принимает (applied без итога) - итог не выдумывается.
export async function outcomeFor(base, text) {
  const raw = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 200);
  const unknown = { status: 'unknown', critical: 0, major: 0, minor: 0, raw };
  if (base === 'code_review') {
    const { counts, matched } = await countDiagnostics(text);
    if (matched > 0) return { status: 'findings', ...counts };
    return PASS_RE.test(text || '') ? { status: 'pass', critical: 0, major: 0, minor: 0 } : unknown;
  }
  if (base === 'get_project_errors') {
    const lines = findingLines(text);
    if (lines.length > 0) {
      // Ошибки валидатора платформы блокируют запись конфигурации в ИБ.
      const warns = String(text || '').split(/\r?\n/)
        .filter((l) => /предупрежд|warning/i.test(l) && !SUMMARY_NEGATION_RE.test(l)).length;
      return { status: 'findings', critical: lines.length, major: 0, minor: warns };
    }
    return PASS_RE.test(text || '') ? { status: 'pass', critical: 0, major: 0, minor: 0 } : unknown;
  }
  if (base === 'syntaxcheck') {
    const lines = findingLines(text);
    if (lines.length > 0) {
      // Сломанный синтаксис - error: проверку не закрывает, код требует правки.
      return { status: 'error', critical: 0, major: 0, minor: lines.length };
    }
    return PASS_RE.test(text || '') ? { status: 'pass', critical: 0, major: 0, minor: 0 } : unknown;
  }
  if (base === 'ask_1c_ai') {
    const lines = String(text || '').split(/\r?\n/)
      .filter((l) => /замечан|находк|проблем|улучшен|предложени/i.test(l) && !SUMMARY_NEGATION_RE.test(l));
    if (lines.length > 0) return { status: 'findings', critical: 0, major: 0, minor: lines.length };
    return PASS_RE.test(text || '') ? { status: 'pass', critical: 0, major: 0, minor: 0 } : unknown;
  }
  // validate_query, validate_for_export, security_audit, detect_query_anti_patterns:
  // важность находок в ответе не различается - все minor.
  const lines = findingLines(text);
  if (lines.length > 0) return { status: 'findings', critical: 0, major: 0, minor: lines.length };
  return PASS_RE.test(text || '') ? { status: 'pass', critical: 0, major: 0, minor: 0 } : unknown;
}

// diffHash на момент записи; отказ (не репозиторий, git недоступен) - null.
async function currentDiffHash(cwd) {
  try {
    const cs = await computeChangeset(cwd, 'HEAD');
    return { diffHash: cs.diffHash };
  } catch (err) {
    return { diffHash: null, diffError: err instanceof Error ? err.message : String(err) };
  }
}

// Собрать и записать событие по payload PostToolUse/PostToolUseFailure. Возвращает
// { written: path } | { written: null, reason } - причина для stderr, код выхода всегда 0.
export async function processPayload(payload, log = () => {}) {
  if (!payload || typeof payload !== 'object') return { written: null, reason: 'пустой payload' };
  const session = typeof payload.session_id === 'string' ? payload.session_id : '';
  if (!session) return { written: null, reason: 'payload без session_id' };
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  const toolName = String(payload.tool_name || '');
  const toolInput = payload.tool_input;
  const text = responseToText(payload.tool_response);
  const resolved = resolveCheck(toolName, toolInput, text);
  if (!resolved) return { written: null, reason: null };
  const isFailure = payload.hook_event_name === 'PostToolUseFailure';
  let top;
  try {
    top = await repoTop(cwd);
  } catch (err) {
    log(`[evidence-writer] ${err instanceof Error ? err.message : String(err)}`);
    return { written: null, reason: 'каталог не является git-репозиторием' };
  }
  const { diffHash, diffError } = await currentDiffHash(cwd);
  if (diffError) log(`[evidence-writer] diffHash не вычислен: ${diffError}`);
  const event = {
    type: isFailure ? 'failed' : 'applied',
    at: nowIso(),
    session,
    producer: 'hook',
    diffHash,
    check: resolved.check,
    detector: resolved.detector,
    toolUseId: typeof payload.tool_use_id === 'string' ? payload.tool_use_id : null,
  };
  if (isFailure) {
    event.error = payload.error === undefined ? 'отказ инструмента'
      : (typeof payload.error === 'string' ? payload.error : JSON.stringify(payload.error));
  } else {
    event.env = resolved.env;
    event.level = resolved.level;
    event.target = pickTarget(toolInput);
    event.inputHash = resolved.base === 'script' && typeof resolved.evidence.inputHash === 'string'
      ? resolved.evidence.inputHash : sha256Hex(canonicalJson(toolInput));
    event.responseHash = sha256Hex(canonicalJson(payload.tool_response));
    let outcome;
    if (resolved.base === 'script') {
      // Строка EVIDENCE несет итог скрипта; числа - по важностям карточек из ids.
      outcome = { status: resolved.evidence.status, ...(await countCards(resolved.evidence.ids)) };
    } else {
      outcome = await outcomeFor(resolved.base, text);
    }
    if (outcome.raw !== undefined) outcome.raw = String(outcome.raw).slice(0, 200);
    event.outcome = outcome;
  }
  try {
    const path = await writeEvent(top, session, event);
    return { written: path };
  } catch (err) {
    return { written: null, reason: err instanceof Error ? err.message : String(err) };
  }
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('evidence-writer.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const result = await processPayload(payload, (msg) => process.stderr.write(`${msg}\n`));
    if (result.reason) process.stderr.write(`[evidence-writer] ${result.reason}\n`);
    process.exit(0);
  } catch (err) {
    process.stderr.write(`[evidence-writer] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}

// Для тестов: перезагрузить кеш карт важностей (после подмены корня скила).
export function resetSeverityCache() {
  severityMaps = null;
}
