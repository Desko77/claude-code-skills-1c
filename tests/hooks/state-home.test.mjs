// Тесты расположения следа: ключ репозитория, согласие Node и Python, чистота дерева,
// база по умолчанию, очистка ключей и недоступное хранилище.

import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import {
  HOOKS, REPO_ROOT, git, makeTmpRepo, readEvents, runHook, runPythonSync,
} from './helpers.mjs';
import {
  eventsDir, normalizeTop, repoKey, sessionDir, stateBase, stateRoot,
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

await run();
