// Тесты расположения следа: ключ репозитория, согласие Node и Python, чистота дерева,
// база по умолчанию, очистка ключей и недоступное хранилище.

import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import {
  HOOKS, REPO_ROOT, git, makeTmpRepo, readEvents, runHook, runPythonSync, writeRepoFile,
} from './helpers.mjs';
import { computeChangeset } from '../../hooks/_changeset.mjs';
import {
  absoluteStateDir, eventsDir, normalizeTop, repoKey, sessionDir, stateBase, stateRoot,
} from '../../hooks/common/quality-events.mjs';

const VECTORS = join(REPO_ROOT, 'tests', 'hooks', 'fixtures', 'state-key-vectors.json');
const DAY = 8 * 24 * 60 * 60 * 1000;

test('векторы ключа репозитория', async () => {
  const vectors = JSON.parse(await readFile(VECTORS, 'utf8'));
  assertEq(vectors.length, 10);
  for (const vector of vectors) {
    const normalized = normalizeTop(vector.input, vector.platform);
    assertEq(normalized, vector.normalized, vector.input);
    assertEq(repoKey(normalized), vector.key, vector.input);
  }
});

test('eventsDir совпадает с quality_events.events_dir', async () => {
  const ctx = await makeTmpRepo();
  try {
    const code = [
      'import sys',
      'sys.path.insert(0, sys.argv[1])',
      'import quality_events',
      'print(quality_events.events_dir(sys.argv[2], "s1"))',
    ].join('\n');
    const r = runPythonSync(['-c', code, join(REPO_ROOT, 'tools'), ctx.top]);
    assertEq(r.status, 0, r.stderr);
    assertEq(r.stdout.trim(), eventsDir(ctx.top, 's1'));
  } finally {
    await ctx.cleanup();
  }
});

test('чистота рабочего дерева: хуки и CLI не создают файлов в репозитории', async () => {
  const ctx = await makeTmpRepo();
  const session = 'clean-session';
  try {
    const base = { cwd: ctx.top, session_id: session };
    const steps = [
      ['session-context.mjs', { hook_event_name: 'SessionStart', source: 'startup', ...base }],
      ['evidence-writer.mjs', {
        hook_event_name: 'PostToolUse',
        tool_name: 'mcp__1c-edt__validate_for_export',
        tool_input: {},
        tool_response: 'Ошибок нет',
        tool_use_id: 'toolu_clean',
        ...base,
      }],
      ['release-writer.mjs', {
        hook_event_name: 'UserPromptSubmit',
        prompt: '/quality release gate проверка вручную --for 1h',
        ...base,
      }],
      ['quality-baseline.mjs', { hook_event_name: 'SessionStart', source: 'startup', ...base }],
      ['quality-arm.mjs', {
        hook_event_name: 'PostToolUse',
        tool_name: 'Write',
        tool_input: { file_path: 'README.md' },
        tool_use_id: 'toolu_arm',
        ...base,
      }],
      ['edt-gate.mjs', {
        hook_event_name: 'PostToolUseFailure',
        tool_name: 'mcp__ai-edt__launch_debugger',
        tool_input: { action: 'launch' },
        error: 'порт отладки уже используется',
        ...base,
      }, { AI_EDT_GATE: '' }],
    ];
    for (const [hook, payload, env] of steps) {
      const r = runHook(hook, payload, { cwd: ctx.top, env });
      assertEq(r.status, 0, `${hook}: ${r.stderr}`);
    }
    const py = runPythonSync([
      join(REPO_ROOT, 'tools', 'evidence.py'), 'add',
      '--type', 'skipped', '--check', 'code_review@edt',
      '--class', 'not_applicable', '--reason', 'вне среды',
      '--repo', ctx.top, '--session', session,
    ], { cwd: ctx.top });
    assertEq(py.status, 0, py.stderr);
    const status = git(ctx.top, 'status', '--porcelain', '--untracked-files=all', '--ignored');
    assertEq(status, '', `рабочее дерево не пусто: ${status}`);
    const dir = eventsDir(ctx.top, session);
    assert(dir.startsWith(stateBase()), dir);
    const events = await readEvents(ctx.top, session);
    const types = new Set(events.map((e) => e.type));
    for (const kind of ['applied', 'release', 'baseline', 'armed', 'probe', 'skipped']) {
      assert(types.has(kind), `нет события ${kind}: ${[...types].join(',')}`);
    }
    assert(existsSync(join(sessionDir(ctx.top, session), 'edt-window.json')), 'окно не открыто');
  } finally {
    await ctx.cleanup();
  }
});

test('база по умолчанию - домашний каталог, когда QUALITY_STATE_DIR не задана', async () => {
  const ctx = await makeTmpRepo();
  const home = await mkdtemp(join(tmpdir(), 'quality-home-'));
  const session = 'home-session';
  const savedState = process.env.QUALITY_STATE_DIR;
  const savedHome = process.env.HOME;
  const savedProfile = process.env.USERPROFILE;
  try {
    const env = { ...process.env, HOME: home, USERPROFILE: home };
    delete env.QUALITY_STATE_DIR;
    const payload = {
      hook_event_name: 'SessionStart', source: 'startup', cwd: ctx.top, session_id: session,
    };
    const r = spawnSync(process.execPath, [join(HOOKS, 'quality-baseline.mjs')], {
      input: JSON.stringify(payload),
      encoding: 'utf8',
      cwd: ctx.top,
      env,
    });
    assertEq(r.status, 0, r.stderr);
    delete process.env.QUALITY_STATE_DIR;
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    const dir = eventsDir(ctx.top, session);
    assert(dir.startsWith(join(home, '.claude', 'state', 'quality')), dir);
    const names = readdirSync(dir).filter((name) => name.endsWith('.json'));
    assert(names.length >= 1, 'событие в домашнем каталоге');
  } finally {
    if (savedState === undefined) delete process.env.QUALITY_STATE_DIR;
    else process.env.QUALITY_STATE_DIR = savedState;
    if (savedHome === undefined) delete process.env.HOME;
    else process.env.HOME = savedHome;
    if (savedProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = savedProfile;
    await ctx.cleanup();
    await rm(home, { recursive: true, force: true });
  }
});

test('очистка: старые сессии двух ключей удалены, свежие на месте, пустой ключ снят', async () => {
  const a = await makeTmpRepo();
  const b = await makeTmpRepo();
  const orphan = await makeTmpRepo();
  try {
    async function plant(top, session, age) {
      const dir = sessionDir(top, session);
      await mkdir(join(dir, 'events'), { recursive: true });
      await writeFile(join(dir, 'events', 'marker.json'), '{}\n', 'utf8');
      if (age) {
        const t = new Date(Date.now() - age);
        await utimes(dir, t, t);
      }
    }
    await plant(a.top, 'old-a', DAY);
    await plant(a.top, 'new-a', 0);
    await plant(b.top, 'old-b', DAY);
    await plant(b.top, 'new-b', 0);
    const health = join(stateRoot(orphan.top), 'edt-health.json');
    await mkdir(dirname(health), { recursive: true });
    await writeFile(health, '{}\n', 'utf8');
    const old = new Date(Date.now() - DAY);
    await utimes(health, old, old);
    const r = runHook('session-context.mjs', {
      hook_event_name: 'SessionStart', source: 'startup', cwd: a.top, session_id: 'live-sweep',
    }, { cwd: a.top });
    assertEq(r.status, 0, r.stderr);
    assert(!existsSync(sessionDir(a.top, 'old-a')), 'старая сессия первого ключа');
    assert(existsSync(sessionDir(a.top, 'new-a')), 'свежая сессия первого ключа');
    assert(!existsSync(sessionDir(b.top, 'old-b')), 'старая сессия второго ключа');
    assert(existsSync(sessionDir(b.top, 'new-b')), 'свежая сессия второго ключа');
    assert(!existsSync(stateRoot(orphan.top)), 'каталог ключа без сессий удален');
  } finally {
    await a.cleanup();
    await b.cleanup();
    await orphan.cleanup();
  }
});

test('пустая QUALITY_STATE_DIR равносильна отсутствию переменной', async () => {
  const ctx = await makeTmpRepo();
  const home = await mkdtemp(join(tmpdir(), 'quality-home-'));
  const session = 'empty-env-session';
  const savedState = process.env.QUALITY_STATE_DIR;
  const savedHome = process.env.HOME;
  const savedProfile = process.env.USERPROFILE;
  try {
    const env = { ...process.env, HOME: home, USERPROFILE: home, QUALITY_STATE_DIR: '' };
    const r = spawnSync(process.execPath, [join(HOOKS, 'quality-baseline.mjs')], {
      input: JSON.stringify({
        hook_event_name: 'SessionStart', source: 'startup', cwd: ctx.top, session_id: session,
      }),
      encoding: 'utf8',
      cwd: ctx.top,
      env,
    });
    assertEq(r.status, 0, r.stderr);
    process.env.QUALITY_STATE_DIR = '';
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    const dir = eventsDir(ctx.top, session);
    assert(dir.startsWith(join(home, '.claude', 'state', 'quality')), dir);
    const names = readdirSync(dir).filter((name) => name.endsWith('.json'));
    assert(names.length >= 1, 'событие в домашнем каталоге');
  } finally {
    if (savedState === undefined) delete process.env.QUALITY_STATE_DIR;
    else process.env.QUALITY_STATE_DIR = savedState;
    if (savedHome === undefined) delete process.env.HOME;
    else process.env.HOME = savedHome;
    if (savedProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = savedProfile;
    await ctx.cleanup();
    await rm(home, { recursive: true, force: true });
  }
});

test('очистка оставляет ключ со свежим edt-health.json без сессий', async () => {
  const orphan = await makeTmpRepo();
  try {
    const health = join(stateRoot(orphan.top), 'edt-health.json');
    await mkdir(dirname(health), { recursive: true });
    await writeFile(health, '{}\n', 'utf8');
    const r = runHook('session-context.mjs', {
      hook_event_name: 'SessionStart', source: 'startup', cwd: orphan.top, session_id: 'live-fresh-health',
    }, { cwd: orphan.top });
    assertEq(r.status, 0, r.stderr);
    assert(existsSync(health), 'свежий кэш /health сохраняет каталог ключа');
  } finally {
    await orphan.cleanup();
  }
});

test('хранилище недоступно: evidence-writer и session-context выходят 0 со stderr', async () => {
  const ctx = await makeTmpRepo();
  const base = await mkdtemp(join(tmpdir(), 'quality-blocker-'));
  const blocker = join(base, 'not-dir');
  await writeFile(blocker, 'x', 'utf8');
  try {
    const env = { QUALITY_STATE_DIR: blocker };
    const evidence = runHook('evidence-writer.mjs', {
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__1c-edt__validate_for_export',
      tool_input: {},
      tool_response: 'Ошибок нет',
      tool_use_id: 'toolu_block',
      cwd: ctx.top,
      session_id: 'block-session',
    }, { cwd: ctx.top, env });
    assertEq(evidence.status, 0);
    assert(evidence.stderr.trim(), 'evidence-writer без stderr');
    const session = runHook('session-context.mjs', {
      hook_event_name: 'SessionStart',
      source: 'startup',
      cwd: ctx.top,
      session_id: 'block-session',
    }, { cwd: ctx.top, env });
    assertEq(session.status, 0);
    assert(session.stderr.trim(), 'session-context без stderr');
  } finally {
    await ctx.cleanup();
    await rm(base, { recursive: true, force: true });
  }
});

async function plantSession(top, session, age) {
  const dir = sessionDir(top, session);
  await mkdir(join(dir, 'events'), { recursive: true });
  await writeFile(join(dir, 'events', 'marker.json'), '{}\n', 'utf8');
  if (age) {
    const t = new Date(Date.now() - age);
    await utimes(dir, t, t);
  }
}

function runSweep(top, session) {
  return runHook('session-context.mjs', {
    hook_event_name: 'SessionStart', source: 'startup', cwd: top, session_id: session,
  }, { cwd: top });
}

test('очистка не трогает посторонний каталог и файл базы', async () => {
  const ctx = await makeTmpRepo();
  try {
    const base = stateBase();
    const notes = join(base, 'notes');
    const child = join(notes, 'old');
    await mkdir(child, { recursive: true });
    const old = new Date(Date.now() - DAY);
    await utimes(child, old, old);
    await utimes(notes, old, old);
    const stray = join(base, 'stray.txt');
    await writeFile(stray, 'x\n', 'utf8');
    await utimes(stray, old, old);
    const r = runSweep(ctx.top, 'live-foreign');
    assertEq(r.status, 0, r.stderr);
    assert(existsSync(notes), 'посторонний каталог notes');
    assert(existsSync(child), 'старый подкаталог notes');
    assert(existsSync(stray), 'посторонний файл базы');
  } finally {
    await ctx.cleanup();
  }
});

test('очистка оставляет в ключе подкаталог с именем вне SESSION_RE', async () => {
  const ctx = await makeTmpRepo();
  try {
    const gitDir = join(stateRoot(ctx.top), '.git');
    await mkdir(gitDir, { recursive: true });
    await writeFile(join(gitDir, 'config'), 'x\n', 'utf8');
    const old = new Date(Date.now() - DAY);
    await utimes(gitDir, old, old);
    const r = runSweep(ctx.top, 'live-dotgit');
    assertEq(r.status, 0, r.stderr);
    assert(existsSync(gitDir), 'подкаталог .git на месте');
    assert(existsSync(stateRoot(ctx.top)), 'каталог ключа на месте');
  } finally {
    await ctx.cleanup();
  }
});

test('очистка удаляет старую сессию и оставляет ключ с посторонним файлом', async () => {
  const ctx = await makeTmpRepo();
  try {
    await plantSession(ctx.top, 'old-sess', DAY);
    const stray = join(stateRoot(ctx.top), 'stray.txt');
    await writeFile(stray, 'x\n', 'utf8');
    const r = runSweep(ctx.top, 'live-stray');
    assertEq(r.status, 0, r.stderr);
    assert(!existsSync(sessionDir(ctx.top, 'old-sess')), 'старая сессия удалена');
    assert(existsSync(stray), 'посторонний файл на месте');
    assert(existsSync(stateRoot(ctx.top)), 'каталог ключа остается');
  } finally {
    await ctx.cleanup();
  }
});

test('очистка удаляет ключ со старой сессией и старым edt-health.json', async () => {
  const ctx = await makeTmpRepo();
  try {
    await plantSession(ctx.top, 'old-sess', DAY);
    const health = join(stateRoot(ctx.top), 'edt-health.json');
    await writeFile(health, '{}\n', 'utf8');
    const old = new Date(Date.now() - DAY);
    await utimes(health, old, old);
    const r = runSweep(ctx.top, 'live-old-health');
    assertEq(r.status, 0, r.stderr);
    assert(!existsSync(stateRoot(ctx.top)), 'каталог ключа удален');
  } finally {
    await ctx.cleanup();
  }
});

function pythonStateBase() {
  const code = [
    'import sys',
    'sys.path.insert(0, sys.argv[1])',
    'import quality_events',
    'print(quality_events.state_base())',
  ].join('\n');
  const r = runPythonSync(['-c', code, join(REPO_ROOT, 'tools')]);
  assertEq(r.status, 0, r.stderr);
  return r.stdout.trim();
}

function slashFold(value) {
  const text = String(value).replace(/\\/g, '/');
  return process.platform === 'win32' ? text.toLowerCase() : text;
}

test('относительный QUALITY_STATE_DIR не задает базу', async () => {
  const home = await mkdtemp(join(tmpdir(), 'quality-home-'));
  const savedState = process.env.QUALITY_STATE_DIR;
  const savedHome = process.env.HOME;
  const savedProfile = process.env.USERPROFILE;
  const expected = join(home, '.claude', 'state', 'quality');
  try {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    for (const value of ['rel/dir', './x', 'x']) {
      process.env.QUALITY_STATE_DIR = value;
      assertEq(stateBase(), expected, value);
      assertEq(slashFold(pythonStateBase()), slashFold(expected), value);
    }
    if (process.platform === 'win32') {
      process.env.QUALITY_STATE_DIR = '/foo';
      assertEq(stateBase(), expected, '/foo');
      assertEq(slashFold(pythonStateBase()), slashFold(expected), '/foo');
      process.env.QUALITY_STATE_DIR = 'C:/x';
      assertEq(stateBase(), 'C:/x');
      assertEq(slashFold(pythonStateBase()), 'c:/x');
      const unc = '\\\\server\\share\\x';
      process.env.QUALITY_STATE_DIR = unc;
      assertEq(stateBase(), unc);
      assertEq(slashFold(pythonStateBase()), '//server/share/x');
    }
  } finally {
    if (savedState === undefined) delete process.env.QUALITY_STATE_DIR;
    else process.env.QUALITY_STATE_DIR = savedState;
    if (savedHome === undefined) delete process.env.HOME;
    else process.env.HOME = savedHome;
    if (savedProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = savedProfile;
    await rm(home, { recursive: true, force: true });
  }
});

test('правило абсолютного пути одинаково для win32 и остальных платформ', () => {
  for (const value of ['rel/dir', './x', 'x']) {
    assert(!absoluteStateDir(value, 'win32'), value);
    assert(!absoluteStateDir(value, 'linux'), value);
  }
  assert(!absoluteStateDir('/foo', 'win32'));
  assert(absoluteStateDir('/foo', 'linux'));
  assert(absoluteStateDir('C:/x', 'win32'));
  assert(absoluteStateDir('C:\\x', 'win32'));
  assert(!absoluteStateDir('C:/x', 'linux'));
  assert(absoluteStateDir('\\\\server\\share\\x', 'win32'));
  assert(absoluteStateDir('//server/share/x', 'win32'));
  assert(!absoluteStateDir('\\\\server\\share\\x', 'linux'));
});

function pathsOf(files) {
  return files.map((file) => file.path);
}

function assertNoQstate(files) {
  for (const file of files) {
    const folded = slashFold(file.path);
    assert(folded !== '.qstate' && !folded.startsWith('.qstate/'), file.path);
  }
}

async function bothChangesets(top) {
  const node = await computeChangeset(top);
  const py = runPythonSync([
    join(REPO_ROOT, 'tools', 'changeset.py'), '--repo', top, '--json',
  ]);
  assertEq(py.status, 0, py.stderr);
  return { node, py: JSON.parse(py.stdout) };
}

function flipCase(text) {
  return text.replace(/[A-Za-z]/g, (ch) => (
    ch === ch.toLowerCase() ? ch.toUpperCase() : ch.toLowerCase()));
}

test('след вне множества: diffHash Python и Node совпадают и не меняются', async () => {
  const ctx = await makeTmpRepo();
  const savedState = process.env.QUALITY_STATE_DIR;
  const session = 'qstate-session';
  try {
    process.env.QUALITY_STATE_DIR = join(ctx.top, '.qstate');
    const baseline = runHook('quality-baseline.mjs', {
      hook_event_name: 'SessionStart', source: 'startup', cwd: ctx.top, session_id: session,
    }, { cwd: ctx.top });
    assertEq(baseline.status, 0, baseline.stderr);
    const dir = eventsDir(ctx.top, session);
    const jsonCount = () => readdirSync(dir).filter((name) => name.endsWith('.json')).length;
    assert(jsonCount() >= 1, 'хук записал событие');
    const first = await bothChangesets(ctx.top);
    assertNoQstate(first.node.files);
    assertNoQstate(first.py.files);
    assertEq(first.node.diffHash, first.py.diffHash);
    assertEq(pathsOf(first.node.files), pathsOf(first.py.files));
    const applied = runHook('evidence-writer.mjs', {
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__1c-edt__validate_for_export',
      tool_input: {},
      tool_response: 'Ошибок нет',
      tool_use_id: 'toolu_qstate',
      cwd: ctx.top,
      session_id: session,
    }, { cwd: ctx.top });
    assertEq(applied.status, 0, applied.stderr);
    assert(jsonCount() >= 2, 'второе событие');
    const second = await bothChangesets(ctx.top);
    assertNoQstate(second.node.files);
    assertNoQstate(second.py.files);
    assertEq(second.node.diffHash, first.node.diffHash);
    assertEq(second.py.diffHash, first.node.diffHash);
    if (process.platform === 'win32') {
      process.env.QUALITY_STATE_DIR = flipCase(join(ctx.top, '.qstate'));
      const again = runHook('evidence-writer.mjs', {
        hook_event_name: 'PostToolUse',
        tool_name: 'mcp__1c-edt__validate_for_export',
        tool_input: {},
        tool_response: 'Ошибок нет',
        tool_use_id: 'toolu_qstate_case',
        cwd: ctx.top,
        session_id: session,
      }, { cwd: ctx.top });
      assertEq(again.status, 0, again.stderr);
      const cased = await bothChangesets(ctx.top);
      assertNoQstate(cased.node.files);
      assertNoQstate(cased.py.files);
      assertEq(cased.node.diffHash, first.node.diffHash);
      assertEq(cased.py.diffHash, first.node.diffHash);
    }
    await writeRepoFile(ctx.top, 'outside.txt', 'вне\n');
    const control = await bothChangesets(ctx.top);
    assert(control.node.files.some((file) => file.path === 'outside.txt'), 'untracked вне следа');
    assert(control.py.files.some((file) => file.path === 'outside.txt'), 'untracked вне следа');
    assertNoQstate(control.node.files);
    assertNoQstate(control.py.files);
    assertEq(control.node.diffHash, control.py.diffHash);
  } finally {
    if (savedState === undefined) delete process.env.QUALITY_STATE_DIR;
    else process.env.QUALITY_STATE_DIR = savedState;
    await ctx.cleanup();
  }
});

await run();
