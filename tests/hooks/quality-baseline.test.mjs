// Тесты hooks/quality-baseline.mjs: базовая отметка сессии пишется один раз на
// session_id (startup), не перезаписывается при resume/compact/clear даже после нового
// коммита, вне git и в репозитории без коммитов - отметка с head null и пустым множеством.

import { mkdtemp, rm } from 'node:fs/promises';
import { mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { git, loadFixture, makeTmpRepo, readEvents, runHook, writeRepoFile } from './helpers.mjs';

const MODULE = 'Процедура Обмен()\nКонецПроцедуры\n';

test('startup: отметка baseline с HEAD, множеством и cwd', async () => {
  const ctx = await makeTmpRepo();
  try {
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE);
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'module', '--no-gpg-sign', '--no-verify');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'base-session-1' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const events = await readEvents(ctx.top, 'base-session-1');
    assertEq(events.filter((e) => e.type === 'baseline').length, 1, 'одно событие baseline');
    const [e] = events;
    const head = git(ctx.top, 'rev-parse', 'HEAD').trim();
    assertEq(e.head, head, 'head - текущий HEAD');
    assertEq(e.cwd, ctx.top);
    assertEq(e.changeset.base, head);
    assertEq(e.changeset.files.length, 1, 'грязный файл на старте входит в отметку');
    assertEq(e.changeset.files[0].path, 'proj/src/Module.bsl');
    assert(typeof e.changeset.files[0].sha256 === 'string' && e.changeset.files[0].sha256.length === 64,
      'хеш содержимого в отметке');
    assertEq(e.diffHash, e.changeset.diffHash, 'diffHash события равен хешу множества отметки');
  } finally {
    await ctx.cleanup();
  }
});

test('resume, compact и clear после startup: отметка одна и не перезаписывается', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'base-session-1' });
    assertEq(runHook('quality-baseline.mjs', payload).status, 0);
    const [first] = await readEvents(ctx.top, 'base-session-1');
    // Коммит после старта сместил HEAD - отметка обязана остаться на прежнем коммите.
    await writeRepoFile(ctx.top, 'new.bsl', MODULE);
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'later', '--no-gpg-sign', '--no-verify');
    for (const fixture of ['session-start-resume', 'session-start-compact', 'session-start-clear']) {
      const again = await loadFixture(fixture, { cwd: ctx.top, session_id: 'base-session-1' });
      assertEq(runHook('quality-baseline.mjs', again).status, 0);
    }
    const events = await readEvents(ctx.top, 'base-session-1');
    assertEq(events.filter((e) => e.type === 'baseline').length, 1, 'отметка не дублируется');
    assertEq(events[0].head, first.head, 'head отметки прежний');
  } finally {
    await ctx.cleanup();
  }
});

test('startup первым событием без правок: пустое множество с конкретным diffHash', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'base-clean' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'base-clean');
    assertEq(e.type, 'baseline');
    assertEq(e.changeset.files.length, 0, 'множество пусто');
    assertEq(e.diffHash, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      'diffHash пустого множества - sha256 пустого буфера');
  } finally {
    await ctx.cleanup();
  }
});

test('вне git: отметка с head null и пустым множеством, диагностика в stderr', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-base-nogit-'));
  try {
    const payload = await loadFixture('session-start-startup', { cwd: base, session_id: 'base-nogit' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0);
    const events = await readEvents(base, 'base-nogit');
    assertEq(events.length, 1, 'отметка записана от cwd как от корня');
    const [e] = events;
    assertEq(e.type, 'baseline');
    assertEq(e.head, null);
    assertEq(e.changeset.files.length, 0);
    assert(r.stderr.includes('вне git-репозитория'), `причина в stderr: ${r.stderr}`);
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test('репозиторий без коммитов: head null, пустое множество', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-base-nocommit-'));
  const top = join(base, 'repo');
  await mkdir(top, { recursive: true });
  git(top, 'init', '-q');
  git(top, 'config', 'user.email', 'test@example.com');
  git(top, 'config', 'user.name', 'Test');
  try {
    const payload = await loadFixture('session-start-startup', { cwd: top, session_id: 'base-nocommit' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(top, 'base-nocommit');
    assertEq(e.head, null, 'HEAD не разрешается');
    assertEq(e.changeset.files.length, 0);
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test('недопустимый идентификатор сессии: код 0, событие не пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: '../escape' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0, 'внутренняя ошибка хука не блокирует');
    assert(r.stderr.includes('недопустимый идентификатор'), `диагностика в stderr: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('payload без session_id: код 0 без события', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top });
    delete payload.session_id;
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0);
    assertEq(r.stderr.trim(), '', 'молча');
  } finally {
    await ctx.cleanup();
  }
});

test('множество не вычислено: отметка не пишется, диагностика в stderr', async () => {
  const ctx = await makeTmpRepo();
  try {
    // Битый индекс git: HEAD разрешается, а вычисление множества падает.
    await writeFile(join(ctx.top, '.git', 'index'), 'не индекс', 'utf8');
    const payload = await loadFixture('session-start-startup', { cwd: ctx.top, session_id: 'base-broken-1' });
    const r = runHook('quality-baseline.mjs', payload);
    assertEq(r.status, 0, 'хук не роняет сессию');
    assert(/множество не вычислено/.test(r.stderr), 'причина названа в stderr: ' + r.stderr);
    const events = await readEvents(ctx.top, 'base-broken-1');
    assertEq(events.length, 0, 'отметка с пустым множеством не пишется');
  } finally {
    await ctx.cleanup();
  }
});

await run();
