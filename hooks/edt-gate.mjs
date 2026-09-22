// edt-gate.mjs - ворота MCP-first.
// PreToolUse: Read, Grep, Glob, Bash, PowerShell по исходникам EDT-проекта
// отклоняются, когда проект загружен в живой AI-EDT (phase ready, имя в projects).
// PostToolUseFailure: окно-исключение на 15 минут, если /health сервера из имени
// инструмента не отвечает, отказал в авторизации или phase не ready.
// Внутренняя ошибка - выход 0, диагностика в stderr, вызов не блокируется.
//
// stdin: JSON PreToolUse или PostToolUseFailure
// { hook_event_name, tool_name, tool_input, session_id, cwd, error }.

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join, basename, resolve, isAbsolute, parse } from 'node:path';
import { homedir } from 'node:os';
import { computeChangeset } from './_changeset.mjs';
import { eventsDir, formatIso, listEventFiles, nowIso, repoTop, writeEvent } from './common/quality-events.mjs';

// Заякоренный матчер PreToolUse. Строка в hooks/hooks.json сверяется тестом.
export const GATE_MATCHER = '^(Read|Grep|Glob|Bash|PowerShell)$';

const SOURCE_EXTS = ['.bsl', '.os', '.mdo', '.form', '.dcs', '.mxlx', '.cmi', '.rights', '.xdto'];
const UTILITIES = new Set([
  'cat', 'head', 'tail', 'sed', 'grep', 'rg', 'find', 'awk', 'python',
  'get-content', 'select-string', 'type',
]);
const HEALTH_TTL_MS = 60 * 1000;
const WINDOW_MS = 15 * 60 * 1000;
const MCP_TOOL_RE = /^mcp__([A-Za-z0-9._-]+)__(.+)$/;

function allow(stderr = '') {
  return { stdout: '', stderr, exitCode: 0 };
}

function deny(reason) {
  return {
    stdout: JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reason,
      },
    }),
    stderr: '',
    exitCode: 0,
  };
}

// Домашний каталог: на Windows USERPROFILE, иначе HOME. Тесты подменяют оба.
export function claudeHome() {
  if (process.platform === 'win32') return process.env.USERPROFILE || process.env.HOME || homedir();
  return process.env.HOME || process.env.USERPROFILE || homedir();
}

// Расширение исходника EDT из списка ворот, иначе null.
export function sourceExt(file) {
  const lower = String(file || '').toLowerCase();
  for (const ext of SOURCE_EXTS) {
    if (lower.endsWith(ext)) return ext;
  }
  return null;
}

// Сегмент каталога src: /src/, \src\, начало пути src/ или токен src.
export function hasSrcSegment(token) {
  const norm = String(token || '').replace(/\\/g, '/');
  return /(^|\/)src(\/|$)/.test(norm);
}

function baseName(token) {
  const norm = String(token).replace(/\\/g, '/');
  const i = norm.lastIndexOf('/');
  return i === -1 ? norm : norm.slice(i + 1);
}

// Токены команды: кавычки снимаются, комментарий # до конца строки отбрасывается,
// разделители ; & | и пробелы делят токены.
function commandTokens(command) {
  const tokens = [];
  let cur = '';
  let quote = null;
  const s = String(command || '');
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quote) {
      if (ch === quote) quote = null;
      else cur += ch;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '#' && (i === 0 || /[\s;&|(<>]/.test(s[i - 1]))) break;
    if (/[\s;&|()]/.test(ch)) {
      if ((ch === '&' || ch === '|') && s[i + 1] === ch) i++;
      if (cur) {
        tokens.push(cur);
        cur = '';
      }
      continue;
    }
    cur += ch;
  }
  if (cur) tokens.push(cur);
  return tokens;
}

function isUtility(token) {
  let name = baseName(token).toLowerCase();
  if (name.endsWith('.exe')) name = name.slice(0, -4);
  return UTILITIES.has(name);
}

// Пути команды, которые имеют смысл для ворот: утилита чтения есть, и токен
// несет расширение исходника либо сегмент src. Иначе пустой список (пропуск).
export function shellTargets(command) {
  const tokens = commandTokens(command);
  if (!tokens.some(isUtility)) return [];
  const targets = [];
  for (const token of tokens) {
    if (token.startsWith('-')) continue;
    if (isUtility(token)) continue;
    if (sourceExt(token) || hasSrcSegment(token)) targets.push(token);
  }
  return targets;
}

// Инструмент-замена в причине отказа.
export function replacementFor(tool, file) {
  if (tool === 'Grep' || tool === 'Glob') return 'code_search operation=text_search';
  const ext = sourceExt(file) || '';
  if (ext === '.mdo') return 'get_metadata_details';
  if (ext === '.bsl' || ext === '.os') return 'get_module_structure и read_method_source';
  if (ext === '.form') return 'get_form_structure';
  if (ext === '.dcs') return 'dcs_workshop';
  return 'code_search operation=text_search';
}

function denyReason({ file, serverKey, replacement, shell }) {
  const shellNote = shell ? ' Перебор исходников при живой EDT.' : '';
  return 'Ворота MCP-first: ' + file + '. Сервер ' + serverKey + '. Замена: ' + replacement + '.'
    + shellNote + ' Раздел "Сначала индекс" (rules/mcp-tool-priority.md).'
    + ' Снятие: /quality release gate <причина>.';
}

function absPath(p, cwd) {
  return isAbsolute(p) ? p : resolve(cwd, p);
}

// Каталог, с которого искать .project: у файла с расширением это родитель.
function startDir(target) {
  const trimmed = String(target).replace(/[\\/]+$/, '');
  const base = basename(trimmed);
  if (base.includes('.') && !base.startsWith('.')) return dirname(trimmed);
  return trimmed || target;
}

// Ближайший вверх EDT-проект: .project содержит com._1c.g5.v8.dt, имя - первое <name>.
export async function findEdtProject(target) {
  let dir = startDir(target);
  const root = parse(dir).root;
  while (dir) {
    try {
      const text = await readFile(join(dir, '.project'), 'utf8');
      if (text.includes('com._1c.g5.v8.dt')) {
        const m = /<name>([^<]*)<\/name>/.exec(text);
        const name = m ? m[1].trim() : '';
        if (name) return { dir, name };
      }
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    if (dir === root) return null;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

async function findUpFile(startDir, rel) {
  let dir = startDir;
  const root = parse(dir).root;
  while (dir) {
    const candidate = join(dir, rel);
    try {
      await readFile(candidate, 'utf8');
      return candidate;
    } catch (err) {
      if (err.code !== 'ENOENT' && err.code !== 'EISDIR') throw err;
    }
    if (dir === root) return null;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

async function readJsonFile(file) {
  let text;
  try {
    text = await readFile(file, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`${file}: ${err.message}`);
  }
}

function isPluginKey(key) {
  return /^plugin([_-]|$)/.test(key) || key.startsWith('mcp__plugin_');
}

// URL /health: суффикс /mcp у адреса MCP снимается.
export function healthUrlFrom(mcpUrl) {
  const u = new URL(mcpUrl);
  let path = u.pathname.replace(/\/+$/, '');
  if (path.endsWith('/mcp')) path = path.slice(0, -4);
  u.pathname = `${path}/health`.replace(/\/{2,}/g, '/') || '/health';
  u.search = '';
  u.hash = '';
  return u.toString();
}

function addServers(map, servers, origin) {
  if (!servers || typeof servers !== 'object' || Array.isArray(servers)) return;
  for (const [key, spec] of Object.entries(servers)) {
    if (!spec || typeof spec !== 'object') continue;
    if (isPluginKey(key)) continue;
    if (spec.type !== 'http' || typeof spec.url !== 'string' || !spec.url) continue;
    if (map.has(key)) continue;
    let healthUrl;
    try {
      healthUrl = healthUrlFrom(spec.url);
    } catch {
      continue;
    }
    map.set(key, { key, url: spec.url, healthUrl, origin });
  }
}

function absorbFlags(obj, acc) {
  if (!obj || typeof obj !== 'object') return;
  if (Array.isArray(obj.disabledMcpjsonServers)) {
    for (const name of obj.disabledMcpjsonServers) {
      if (typeof name === 'string') acc.disabled.add(name);
    }
  }
  if (Array.isArray(obj.enabledMcpjsonServers)) {
    for (const name of obj.enabledMcpjsonServers) {
      if (typeof name === 'string') acc.enabled.add(name);
    }
  }
  if (obj.enableAllProjectMcpServers === true) acc.enableAll = true;
}

function matchProjectRecord(projects, cwd) {
  if (!projects || typeof projects !== 'object') return null;
  const norm = cwd.replace(/[\\/]+$/, '');
  const variants = new Set([norm, norm.replace(/\\/g, '/'), norm.replace(/\//g, '\\')]);
  for (const [key, val] of Object.entries(projects)) {
    const k = key.replace(/[\\/]+$/, '');
    const forms = [k, k.replace(/\\/g, '/'), k.replace(/\//g, '\\')];
    if (forms.some((form) => variants.has(form))) return val;
  }
  return null;
}

// Кандидаты: .mcp.json (с флагами включения), mcpServers ~/.claude.json и
// projects[cwd].mcpServers. Сервер .mcp.json включен при enableAll или при
// наличии ключа в enabledMcpjsonServers и отсутствии в disabledMcpjsonServers.
export async function collectServers(cwd) {
  const flags = { disabled: new Set(), enabled: new Set(), enableAll: false };
  const fromMcpJson = new Map();
  const always = new Map();

  const mcpFile = await findUpFile(cwd, '.mcp.json');
  const mcpJson = mcpFile ? await readJsonFile(mcpFile) : null;
  if (mcpJson) addServers(fromMcpJson, mcpJson.mcpServers, 'mcpjson');

  const settingsFile = await findUpFile(cwd, join('.claude', 'settings.json'));
  const localFile = await findUpFile(cwd, join('.claude', 'settings.local.json'));
  if (settingsFile) absorbFlags(await readJsonFile(settingsFile), flags);
  if (localFile) absorbFlags(await readJsonFile(localFile), flags);

  const claudeJson = await readJsonFile(join(claudeHome(), '.claude.json'));
  if (claudeJson) {
    const projectRecord = matchProjectRecord(claudeJson.projects, cwd);
    if (projectRecord) {
      addServers(always, projectRecord.mcpServers, 'local');
      absorbFlags(projectRecord, flags);
    }
    addServers(always, claudeJson.mcpServers, 'user');
  }

  const out = [...always.values()];
  const seen = new Set(out.map((server) => server.key));
  for (const server of fromMcpJson.values()) {
    if (seen.has(server.key)) continue;
    if (flags.disabled.has(server.key)) continue;
    if (!flags.enableAll && !flags.enabled.has(server.key)) continue;
    out.push(server);
  }
  return out;
}

// Сервер по ключу из имени инструмента: среди объявленных, без фильтра включения
// (инструмент уже вызван). Плагины и не-http не возвращаются.
export async function findServerByKey(cwd, key) {
  if (!key || isPluginKey(key)) return null;
  const mcpFile = await findUpFile(cwd, '.mcp.json');
  const mcpJson = mcpFile ? await readJsonFile(mcpFile) : null;
  const claudeJson = await readJsonFile(join(claudeHome(), '.claude.json'));
  const buckets = [];
  if (mcpJson && mcpJson.mcpServers) buckets.push(mcpJson.mcpServers);
  if (claudeJson && claudeJson.mcpServers) buckets.push(claudeJson.mcpServers);
  const projectRecord = claudeJson ? matchProjectRecord(claudeJson.projects, cwd) : null;
  if (projectRecord && projectRecord.mcpServers) buckets.push(projectRecord.mcpServers);
  for (const bucket of buckets) {
    const spec = bucket[key];
    if (!spec || spec.type !== 'http' || typeof spec.url !== 'string') continue;
    try {
      return { key, url: spec.url, healthUrl: healthUrlFrom(spec.url) };
    } catch {
      return null;
    }
  }
  return null;
}

async function fetchHealth(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1000);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { accept: 'application/json' } });
    const text = await res.text();
    let body = null;
    try { body = JSON.parse(text); } catch { body = null; }
    return { status: res.status, body, error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { status: 0, body: null, error: message };
  } finally {
    clearTimeout(timer);
  }
}

// kind: ready (AI-EDT phase ready), down (нет ответа, авторизация, phase не ready),
// foreign (ответ не AI-EDT).
export function classifyHealth(result) {
  if (!result || result.error || !result.status) return { kind: 'down', detail: 'нет ответа', projects: [] };
  if (result.status === 401 || result.status === 403) {
    return { kind: 'down', detail: 'отказ авторизации', projects: [] };
  }
  const body = result.body && typeof result.body === 'object' && !Array.isArray(result.body)
    ? result.body : null;
  const instance = body && typeof body.instance === 'string' ? body.instance : '';
  const phase = body && typeof body.phase === 'string' ? body.phase : '';
  const ai = instance.startsWith('AI-EDT @');
  if (instance && !ai) return { kind: 'foreign', detail: '', projects: [] };
  if (phase === 'ready') {
    if (!ai) return { kind: 'foreign', detail: '', projects: [] };
    const projects = Array.isArray(body.projects)
      ? body.projects.filter((p) => typeof p === 'string') : [];
    return { kind: 'ready', detail: 'phase=ready', projects };
  }
  return {
    kind: 'down',
    detail: phase ? `phase=${phase}` : (ai ? 'нет phase' : 'нет ответа'),
    projects: [],
  };
}

async function stateTop(cwd) {
  try {
    return await repoTop(cwd);
  } catch {
    return cwd;
  }
}

function cachePath(top) {
  return join(top, '.claude', '.state', 'quality', 'edt-health.json');
}

function windowPath(top, session) {
  return join(top, '.claude', '.state', 'quality', session, 'edt-window.json');
}

async function readCache(file) {
  try {
    const data = JSON.parse(await readFile(file, 'utf8'));
    return data && typeof data === 'object' ? data : {};
  } catch (err) {
    if (err.code === 'ENOENT') return {};
    return {};
  }
}

async function writeCache(file, cache) {
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(cache), 'utf8');
}

// Ответы /health по URL. refresh=true всегда ходит в сеть и обновляет кэш.
async function loadHealth(servers, top, refresh) {
  const file = cachePath(top);
  const cache = await readCache(file);
  const now = Date.now();
  let dirty = false;
  const rows = await Promise.all(servers.map(async (server) => {
    const hit = cache[server.healthUrl];
    if (!refresh && hit && typeof hit.at === 'number' && now - hit.at < HEALTH_TTL_MS && hit.result) {
      return { server, result: hit.result };
    }
    const result = await fetchHealth(server.healthUrl);
    cache[server.healthUrl] = { at: now, result };
    dirty = true;
    return { server, result };
  }));
  if (dirty) {
    try { await writeCache(file, cache); } catch { /* решение не зависит от записи кэша */ }
  }
  return rows;
}

async function currentDiff(cwd) {
  try {
    return (await computeChangeset(cwd, 'HEAD')).diffHash || null;
  } catch {
    return null;
  }
}

async function activeWindow(top, session, now) {
  if (!session) return false;
  let data;
  try {
    data = JSON.parse(await readFile(windowPath(top, session), 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return false;
    throw err;
  }
  const until = Date.parse(data && data.until);
  return Number.isFinite(until) && until > now;
}

async function activeReleaseGate(top, session, diffHash, now) {
  if (!session || !diffHash) return false;
  let names;
  try {
    names = await listEventFiles(top, session);
  } catch {
    return false;
  }
  const dir = eventsDir(top, session);
  for (const name of names) {
    let event;
    try {
      event = JSON.parse(await readFile(join(dir, name), 'utf8'));
    } catch {
      continue;
    }
    if (!event || event.type !== 'release' || event.scope !== 'gate') continue;
    if (event.diffHash !== diffHash) continue;
    const exp = Date.parse(event.expiresAt);
    if (Number.isFinite(exp) && exp > now) return true;
  }
  return false;
}

// Цели PreToolUse. null - инструмент не смотрит исходники EDT, ворота молчат.
function targetsOf(payload, cwd) {
  const tool = String(payload.tool_name || '');
  const input = payload.tool_input && typeof payload.tool_input === 'object' ? payload.tool_input : {};
  if (tool === 'Read') {
    if (typeof input.file_path !== 'string' || !input.file_path) return [];
    if (!sourceExt(input.file_path)) return [];
    return [{ tool, file: absPath(input.file_path, cwd), shell: false }];
  }
  if (tool === 'Grep' || tool === 'Glob') {
    const raw = typeof input.path === 'string' && input.path ? input.path : cwd;
    return [{ tool, file: absPath(raw, cwd), shell: false }];
  }
  if (tool === 'Bash' || tool === 'PowerShell') {
    const command = typeof input.command === 'string' ? input.command : '';
    return shellTargets(command).map((token) => ({
      tool, file: absPath(token, cwd), shell: true,
    }));
  }
  return [];
}

export async function processGate(payload) {
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  const targets = targetsOf(payload, cwd);
  if (!targets.length) return allow();

  const hits = [];
  for (const target of targets) {
    const project = await findEdtProject(target.file);
    if (project) hits.push({ ...target, project });
  }
  if (!hits.length) return allow();

  const session = typeof payload.session_id === 'string' ? payload.session_id : '';
  const top = await stateTop(cwd);
  const now = Date.now();
  if (session && await activeWindow(top, session, now)) return allow();
  if (session) {
    const diffHash = await currentDiff(cwd);
    if (await activeReleaseGate(top, session, diffHash, now)) return allow();
  }

  const servers = await collectServers(cwd);
  if (!servers.length) return allow();
  const rows = await loadHealth(servers, top, false);
  for (const hit of hits) {
    for (const row of rows) {
      const health = classifyHealth(row.result);
      if (health.kind === 'ready' && health.projects.includes(hit.project.name)) {
        return deny(denyReason({
          file: hit.file,
          serverKey: row.server.key,
          replacement: replacementFor(hit.tool, hit.file),
          shell: hit.shell,
        }));
      }
    }
  }
  return allow();
}

async function writeProbe(top, session, cwd, status, detail) {
  const event = {
    type: 'probe',
    at: nowIso(),
    session,
    producer: 'hook',
    diffHash: await currentDiff(cwd),
    source: 'ai-edt',
    status,
    detail,
  };
  await writeEvent(top, session, event);
}

async function openWindow(top, session, serverKey) {
  const file = windowPath(top, session);
  await mkdir(dirname(file), { recursive: true });
  const body = {
    until: formatIso(new Date(Date.now() + WINDOW_MS)),
    server: serverKey,
  };
  await writeFile(file, JSON.stringify(body), 'utf8');
}

export async function processFailure(payload) {
  const toolName = String(payload.tool_name || '');
  if (toolName.startsWith('mcp__plugin_')) return allow();
  const parsed = MCP_TOOL_RE.exec(toolName);
  if (!parsed) return allow();
  const key = parsed[1];
  const session = typeof payload.session_id === 'string' ? payload.session_id : '';
  if (!session) return allow('[edt-gate] payload без session_id');
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  const server = await findServerByKey(cwd, key);
  if (!server) return allow(`[edt-gate] сервер ${key} не найден`);
  const top = await stateTop(cwd);
  const rows = await loadHealth([server], top, true);
  const health = classifyHealth(rows[0] ? rows[0].result : null);
  if (health.kind === 'foreign') return allow();
  const notes = [];
  if (health.kind === 'ready') {
    try {
      await writeProbe(top, session, cwd, 'ok', health.detail);
    } catch (err) {
      notes.push(`[edt-gate] probe: ${err instanceof Error ? err.message : String(err)}`);
    }
    return allow(notes.join('\n'));
  }
  try {
    await writeProbe(top, session, cwd, 'down', health.detail);
  } catch (err) {
    notes.push(`[edt-gate] probe: ${err instanceof Error ? err.message : String(err)}`);
  }
  await openWindow(top, session, key);
  return allow(notes.join('\n'));
}

export async function processPayload(payload) {
  try {
    if (!payload || typeof payload !== 'object') return allow();
    if (payload.hook_event_name === 'PostToolUseFailure') return await processFailure(payload);
    return await processGate(payload);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return allow(`[edt-gate] ${msg}`);
  }
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

if (process.argv[1]?.endsWith('edt-gate.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const { stdout, stderr, exitCode } = await processPayload(payload);
    if (stdout) process.stdout.write(stdout.endsWith('\n') ? stdout : `${stdout}\n`);
    if (stderr) process.stderr.write(stderr.endsWith('\n') ? stderr : `${stderr}\n`);
    process.exit(exitCode);
  } catch (err) {
    process.stderr.write(`[edt-gate] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
