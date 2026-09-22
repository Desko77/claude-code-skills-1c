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
// Единственный источник выражения: строки матчера в hooks/hooks.json сверяются с ним
// гардом tests/hooks/matcher-guard.test.mjs.
export const MATCHER =
  '^(mcp__[A-Za-z0-9._-]+__(validate_query|code_review|diagnostics|validate_for_export|' +
  'get_project_errors|security_audit|check_1c_code|ask_1c_ai|syntaxcheck|' +
  'detect_query_anti_patterns|insights)' +
  '|Bash|PowerShell)$';

// Путь скрипта набора как целый токен команды: skills/<скил>/scripts/<имя>-validate.ps1|py
// либо scripts/<имя>-validate.ps1|py от корня скила, оба разделителя пути.
const SCRIPT_PATH_RE =
  /^(?:skills[\\/][^\\/]+[\\/])?scripts[\\/][A-Za-z0-9._-]*(?:bsl|query|meta|role|form)-validate\.(?:ps1|py)$/i;

// Скрипт кросс-ревью как целый токен команды: имя файла в любом каталоге (личный контур,
// в набор не входит). Запуск - исполняемым токеном, как у скриптов набора.
const REVIEW_SCRIPT_RE = /(?:^|[\\/])(?:codex-code-review\.sh|cursor-run\.ps1)$/i;

// Убрать комментарии: # вне кавычек в начале слова до конца строки (bash, PowerShell).
// Содержимое кавычек не трогается: путь скрипта передается и в кавычках.
function stripComments(command) {
  let quote = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '#' && (i === 0 || /[\s;&|(<>]/.test(command[i - 1]))) return command.slice(0, i);
  }
  return command;
}

// Разбить команду на сегменты по ; && || | & и переводам строк вне кавычек: сегмент -
// одна простая команда. Одиночный & - тоже граница: следующая простая команда (вызов
// через & в PowerShell, фоновый запуск в bash) начинается первым токеном сегмента.
function splitSegments(command) {
  const segments = [''];
  let quote = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === "'" || ch === '"') {
      quote = ch;
    } else if (ch === ';' || ch === '&' || ch === '|' || ch === '\n' || ch === '\r') {
      if ((ch === '&' || ch === '|') && command[i + 1] === ch) i++;
      segments.push('');
      continue;
    }
    segments[segments.length - 1] += ch;
  }
  return segments.map((s) => s.trim()).filter(Boolean);
}

// Токены сегмента с учетом кавычек: кавычки снимаются, содержимое - один токен.
function tokenize(segment) {
  const tokens = [];
  let cur = '';
  let quote = null;
  for (const ch of segment) {
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        cur += ch;
      }
    } else if (ch === "'" || ch === '"') {
      quote = ch;
    } else if (/\s/.test(ch)) {
      if (cur) {
        tokens.push(cur);
        cur = '';
      }
    } else {
      cur += ch;
    }
  }
  if (cur) tokens.push(cur);
  return tokens;
}

// Запускает ли команда скрипт набора: путь скрипта - исполняемый токен, то есть
// python|python3 [-X utf8] <путь>, pwsh|powershell ... -File <путь> либо <путь> первым
// токеном сегмента (в том числе вызов & "<путь>"). Путь в комментарии, строковом
// литерале-аргументе прочей команды или после псевдовызова запуском не считается.
function runsNaborScript(command) {
  return runsScriptWith(String(command || ''), (token) => SCRIPT_PATH_RE.test(token));
}

// Тот же обход для скриптов кросс-ревью: имя файла - исполняемый токен напрямую, после
// python/python3 [-X utf8], после -File у pwsh/powershell либо аргумент bash/sh.
function runsReviewScript(command) {
  return runsScriptWith(String(command || ''), (token) => REVIEW_SCRIPT_RE.test(token));
}

// Обход сегментов команды с проверкой исполняемых токенов против predicate.
function runsScriptWith(command, predicate) {
  const clean = stripComments(command);
  for (const segment of splitSegments(clean)) {
    const tokens = tokenize(segment);
    if (!tokens.length) continue;
    const [first, ...rest] = tokens;
    if (predicate(first)) return true;
    if (first === 'python' || first === 'python3') {
      if (predicate(rest[0] || '')) return true;
      if (rest[0] === '-X' && rest[1] === 'utf8' && predicate(rest[2] || '')) return true;
    }
    if (first === 'pwsh' || first === 'powershell') {
      for (let i = 1; i < tokens.length - 1; i++) {
        if (tokens[i].toLowerCase() === '-file' && predicate(tokens[i + 1])) return true;
      }
    }
    if (first === 'bash' || first === 'sh') {
      if (predicate(rest[0] || '')) return true;
    }
  }
  return false;
}

// Строка результата скрипта набора: EVIDENCE {...} одной строкой (evidence-format.md).
const EVIDENCE_LINE_RE = /(?:^|\n)[ \t]*EVIDENCE[ \t]+(\{[^\n]*\})/;

const MCP_TOOL_RE = /^mcp__([A-Za-z0-9._-]+)__(.+)$/;

// Маркеры вердикта кросс-ревью в выводе скрипта: строка ВЕРДИКТ: (codex-обертки),
// шапка списка комментариев Cursor и находки - [P1] в формате codex review.
const REVIEW_VERDICT_RE = /ВЕРДИКТ:/i;
const REVIEW_APPROVED_RE = /ВЕРДИКТ:[ \t]*APPROVED/i;
const REVIEW_COMMENTS_RE = /Full review comments:/i;
const REVIEW_FINDING_RE = /-[ \t]*\[P([1-9])\]/g;

// Разобрать итог кросс-ревью по маркерам вывода. Возвращает outcome либо null - запуск
// был, но маркера вердикта нет, событие не создается. Находки приоритетнее APPROVED:
// список - [P1] и шапка комментариев дают findings даже при строке APPROVED.
export function crossReviewOutcome(text) {
  const t = String(text || '');
  const findings = [...t.matchAll(REVIEW_FINDING_RE)];
  const hasMarker = REVIEW_VERDICT_RE.test(t) || REVIEW_COMMENTS_RE.test(t) || findings.length > 0;
  if (!hasMarker) return null;
  if (findings.length === 0 && !REVIEW_COMMENTS_RE.test(t) && REVIEW_APPROVED_RE.test(t)) {
    return { status: 'pass', critical: 0, major: 0, minor: 0 };
  }
  const counts = { critical: 0, major: 0, minor: 0 };
  for (const m of findings) {
    const n = Number(m[1]);
    if (n === 1) counts.critical += 1;
    else if (n === 2) counts.major += 1;
    else counts.minor += 1;
  }
  return { status: 'findings', ...counts };
}

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

// Ответ инструмента в текст: строка, массив элементов content верхнего уровня,
// MCP content-массив, structuredContent либо канонический JSON прочей структуры.
export function responseToText(resp) {
  if (resp == null) return '';
  if (typeof resp === 'string') return resp;
  const parts = [];
  const pushContent = (items) => {
    for (const item of items) {
      if (typeof item === 'string') parts.push(item);
      else if (item && typeof item.text === 'string') parts.push(item.text);
    }
  };
  if (Array.isArray(resp)) pushContent(resp);
  if (Array.isArray(resp.content)) pushContent(resp.content);
  if (resp.structuredContent !== undefined) {
    try { parts.push(JSON.stringify(resp.structuredContent, null, 2)); } catch { /* не сериализуемый фрагмент пропускается */ }
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
      case 'get_project_errors':
        // Standalone-имя закрывает ту же проверку, что операция фасада diagnostics.
        return { base: 'get_project_errors', check: 'get_project_errors@edt',
          detector: 'get_project_errors', level: 'semantic', env: 'edt' };
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
      case 'detect_query_anti_patterns':
        // Standalone-имя закрывает ту же проверку, что операция фасада insights.
        return { base: 'detect_query_anti_patterns', check: 'detect_query_anti_patterns@edt',
          detector: 'detect_query_anti_patterns', level: 'static', env: 'edt' };
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
    if (runsReviewScript(command)) {
      // Кросс-ревью: событие только при маркере вердикта в выводе скрипта.
      if (crossReviewOutcome(responseText) === null) return null;
      return { base: 'cross_review', check: 'cross_review@any', detector: 'cross_review',
        level: 'llm', env: 'any' };
    }
    if (!runsNaborScript(command)) return null;
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
// Строка-сводка счетчика ("Ошибок: 2", "Errors: 2") - не находка: ее сумма не
// прибавляется к числу строк-находок.
const SUMMARY_COUNT_RE = /^\s*(?:ошибок|ошибки|находок|находки|нарушений|нарушения|замечаний|замечания|проблем|errors?|issues|findings)\s*[:=]?\s*\d+\s*$/i;
// Итоговая фраза чистоты - только явная сводка с подлежащим. Голое "не найдено"
// встречается в текстах находок ("Поле Родитель не найдено в таблице") и прохода
// не подтверждает: без явной сводки итог - unknown с фрагментом ответа.
const PASS_RE = /(?:ошибок|ошибки|находок|находки|нарушений|нарушения|замечаний|замечания|проблемы|проблем)\s*(?:нет|:?\s*не\s+(?:обнаружено|обнаружены|найдено|найдены|выявлено|выявлены))|отсутствуют\s+(?:ошибки|находки|нарушения|проблемы)|no\s+(?:errors|issues|findings)|(?:запрос|код|синтаксис|файл|форма|валидация|проверка|конфигурация)\s+(?:корректен|корректна|пройден|пройдена|успешна|успешно)/i;

function findingLines(text) {
  return String(text || '').split(/\r?\n/)
    .filter((line) => FINDING_LINE_RE.test(line) && !SUMMARY_NEGATION_RE.test(line)
      && !SUMMARY_COUNT_RE.test(line));
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
  if (base === 'cross_review') {
    return crossReviewOutcome(text) || unknown;
  }
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
  } catch {
    // Причина возвращается для печати CLI-блоком; дополнительная запись в stderr
    // из processPayload дублировала бы ее.
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
