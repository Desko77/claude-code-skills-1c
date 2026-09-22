// Тесты hooks/release-writer.mjs: разбор команды снятия, событие release с diffHash и
// сроком, молчание на прочие промпты.

import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { git, loadFixture, makeTmpRepo, readEvents, runHook } from './helpers.mjs';
import { parseReleaseCommand } from '../../hooks/release-writer.mjs';

test('parseReleaseCommand: gate с причиной и сроком', () => {
  const r = parseReleaseCommand('/quality release gate горячий фикс --for 2h');
  assertEq(r.scope, 'gate');
  assertEq(r.reason, 'горячий фикс');
  assertEq(r.ttlMs, 2 * 60 * 60 * 1000);
});

test('parseReleaseCommand: check с идентификатором проверки, срок по умолчанию', () => {
  const r = parseReleaseCommand('/quality release check validate_query@edt сервер останавливается');
  assertEq(r.scope, 'check');
  assertEq(r.check, 'validate_query@edt');
  assertEq(r.reason, 'сервер останавливается');
  assertEq(r.ttlMs, 4 * 60 * 60 * 1000);
});

test('parseReleaseCommand: отказы разбора', () => {
  assert(parseReleaseCommand('/quality release').parseError);
  assert(parseReleaseCommand('/quality release gate').parseError);
  assert(parseReleaseCommand('/quality release zap причина').parseError);
  assert(parseReleaseCommand('/quality release check').parseError);
  assert(parseReleaseCommand('/quality release gate причина --for 0m').parseError);
});

test('release gate со сроком --for 2h: событие с diffHash и expiresAt', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('release-gate', { cwd: ctx.top, session_id: 'rel-session-1' });
    const before = Date.now();
    const r = runHook('release-writer.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const events = await readEvents(ctx.top, 'rel-session-1');
    assertEq(events.length, 1);
    const e = events[0];
    assertEq(e.type, 'release');
    assertEq(e.scope, 'gate');
    assertEq(e.source, 'user_prompt');
    assertEq(e.reason, 'горячий фикс на проде, проверки прогоню после');
    assert(e.check === undefined, 'gate не называет проверку');
    assert(typeof e.diffHash === 'string' && e.diffHash.length === 64, 'diffHash вычислен');
    const delta = Date.parse(e.expiresAt) - before;
    assert(delta > 1.9 * 60 * 60 * 1000 && delta < 2.1 * 60 * 60 * 1000, `срок около 2 часов: ${e.expiresAt}`);
    assert(/[+-]\d{2}:\d{2}$/.test(e.expiresAt), 'expiresAt с зоной');
    const out = JSON.parse(r.stdout.trim());
    assertEq(out.hookSpecificOutput.hookEventName, 'UserPromptSubmit');
    assert(out.hookSpecificOutput.additionalContext.includes('снятие записано'));
  } finally {
    await ctx.cleanup();
  }
});

test('release check без срока: срок по умолчанию 4 часа', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('release-check', { cwd: ctx.top, session_id: 'rel-session-1' });
    const before = Date.now();
    const r = runHook('release-writer.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'rel-session-1');
    assertEq(e.scope, 'check');
    assertEq(e.check, 'validate_query@edt');
    const delta = Date.parse(e.expiresAt) - before;
    assert(delta > 3.9 * 60 * 60 * 1000 && delta < 4.1 * 60 * 60 * 1000, `срок около 4 часов: ${e.expiresAt}`);
  } finally {
    await ctx.cleanup();
  }
});

test('чужой промпт: нет вывода и нет события', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('release-foreign', { cwd: ctx.top, session_id: 'rel-session-1' });
    const r = runHook('release-writer.mjs', payload);
    assertEq(r.status, 0);
    assertEq(r.stdout.trim(), '');
    assertEq((await readEvents(ctx.top, 'rel-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('нераспознанная команда снятия: диагностика в stderr, события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('release-foreign');
    payload.prompt = '/quality release zap причина';
    payload.cwd = ctx.top;
    payload.session_id = 'rel-session-1';
    const r = runHook('release-writer.mjs', payload);
    assertEq(r.status, 0);
    assert(r.stderr.includes('не разобрана'), 'диагностика в stderr');
    assertEq((await readEvents(ctx.top, 'rel-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('репозиторий без коммитов: diffHash null, предупреждение в stderr один раз, событие пишется', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-nocommit-'));
  const top = join(base, 'repo');
  await mkdir(top, { recursive: true });
  git(top, 'init', '-q');
  git(top, 'config', 'user.email', 'test@example.com');
  git(top, 'config', 'user.name', 'Test');
  try {
    const payload = await loadFixture('release-gate', { cwd: top, session_id: 'rel-nocommit' });
    const r = runHook('release-writer.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(top, 'rel-nocommit');
    assertEq(e.type, 'release');
    assertEq(e.diffHash, null, 'HEAD не разрешается - diffHash null');
    assert(r.stderr.includes('diffHash не вычислен'), `предупреждение в stderr: ${r.stderr}`);
    assertEq(r.stderr.split('\n').filter((l) => l.includes('diffHash не вычислен')).length, 1,
      'предупреждение напечатано один раз без дубля');
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

await run();
