// Тесты hooks/session-context.mjs: additionalContext с идентификатором сессии для трех
// source и очистка каталогов сессий старше 7 дней.

import { mkdir, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { mkdtemp } from 'node:fs/promises';
import { assert, assertEq, run, test } from './harness.mjs';
import { loadFixture, makeTmpRepo, runHook, touchSessionDir } from './helpers.mjs';

test('SessionStart source=startup: additionalContext с идентификатором и каталогом', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'ctx-session-1' });
    const r = runHook('session-context.mjs', payload);
    assertEq(r.status, 0);
    const out = JSON.parse(r.stdout.trim());
    const ctxOut = out.hookSpecificOutput;
    assertEq(ctxOut.hookEventName, 'SessionStart');
    const expectedDir = join(ctx.top, '.claude', '.state', 'quality', 'ctx-session-1', 'events');
    assertEq(ctxOut.additionalContext, `сессия: ctx-session-1\nкаталог событий: ${expectedDir}`);
  } finally {
    await ctx.cleanup();
  }
});

test('SessionStart source=resume: тот же ответ', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-resume', { cwd: ctx.top, session_id: 'ctx-session-1' });
    const r = runHook('session-context.mjs', payload);
    assertEq(r.status, 0);
    const out = JSON.parse(r.stdout.trim());
    assert(out.hookSpecificOutput.additionalContext.startsWith('сессия: ctx-session-1'));
  } finally {
    await ctx.cleanup();
  }
});

test('SessionStart source=compact: тот же ответ, отметка baseline не пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-compact', { cwd: ctx.top, session_id: 'ctx-session-1' });
    const r = runHook('session-context.mjs', payload);
    assertEq(r.status, 0);
    const out = JSON.parse(r.stdout.trim());
    assert(out.hookSpecificOutput.additionalContext.includes('каталог событий'));
    const eventsDir = join(ctx.top, '.claude', '.state', 'quality', 'ctx-session-1', 'events');
    assert(!existsSync(eventsDir) || (await import('node:fs/promises')).readdir(eventsDir).then(
      (names) => names.filter((n) => n.endsWith('.json')).length === 0, () => true),
    'baseline не пишется');
  } finally {
    await ctx.cleanup();
  }
});

test('очистка: каталоги сессий старше 7 дней удаляются, свежие остаются', async () => {
  const ctx = await makeTmpRepo();
  try {
    const stale = join(ctx.top, '.claude', '.state', 'quality', 'stale-session', 'events');
    const fresh = join(ctx.top, '.claude', '.state', 'quality', 'fresh-session', 'events');
    await mkdir(stale, { recursive: true });
    await mkdir(fresh, { recursive: true });
    await writeFile(join(stale, '2026-01-01T000000-000-000000-hook-abc123.json'), '{}\n', 'utf8');
    await touchSessionDir(ctx.top, 'stale-session', 8 * 24 * 60 * 60 * 1000);
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'live-session' });
    const r = runHook('session-context.mjs', payload);
    assertEq(r.status, 0);
    assert(!existsSync(stale), 'устаревший каталог сессии удален');
    assert(existsSync(fresh), 'свежий каталог сессии остался');
  } finally {
    await ctx.cleanup();
  }
});

test('cwd вне git-репозитория: код 0, stdout пуст, диагностика в stderr', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-nogit-'));
  try {
    const payload = await loadFixture('session-start-startup', { cwd: base, session_id: 'ctx-session-1' });
    const r = runHook('session-context.mjs', payload);
    assertEq(r.status, 0);
    assertEq(r.stdout.trim(), '');
    assert(r.stderr.includes('не является'), 'причина в stderr');
  } finally {
    await (await import('node:fs/promises')).rm(base, { recursive: true, force: true });
  }
});

await run();
