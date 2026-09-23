// Довод --only: чужой корень молчит (все девять хуков), свой корень и вложенный cwd
// работают как без ограничения, на win32 регистр и обратные слеши не мешают.

import { randomBytes } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, parse } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { makeTmpRepo, readEvents, runHook, writeRepoFile } from './helpers.mjs';
import { directoryInScope, ONLY_PARSE_ERROR, parseOnlyArgs, scopeStatus } from '../../hooks/common/scope.mjs';

function sid() {
  return `s${randomBytes(4).toString('hex')}`;
}

async function prepareGuard(top) {
  await mkdir(join(top, 'Ext'), { recursive: true });
  await writeFile(join(top, 'Ext', 'ParentConfigurations.bin'), `{6,1,1,${'x'.repeat(40)}`, 'utf8');
  await writeRepoFile(top, 'Catalogs/Items.xml', '<MetaDataObject/>\n');
}

async function prepareStop(top, session) {
  const b = runHook('quality-baseline.mjs', {
    hook_event_name: 'SessionStart', source: 'startup', session_id: session, cwd: top,
  });
  assertEq(b.status, 0, b.stderr);
  await writeRepoFile(top, 'proj/src/Module.bsl', 'Процедура Новая()\nКонецПроцедуры\n');
}

const CASES = [
  {
    name: 'evidence-writer',
    file: 'evidence-writer.mjs',
    payload: (cwd, session) => ({
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__1c-edt__validate_query',
      tool_input: { text: 'ВЫБРАТЬ 1' },
      tool_response: 'Ошибок нет',
      tool_use_id: 'toolu_scope_ev',
      cwd,
      session_id: session,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assertEq(events.length, 1);
      assertEq(events[0].type, 'applied');
      assertEq(events[0].check, 'validate_query@edt');
    },
  },
  {
    name: 'session-context',
    file: 'session-context.mjs',
    payload: (cwd, session) => ({
      hook_event_name: 'SessionStart', source: 'startup', session_id: session, cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assert(r.stdout.includes(`сессия: `), r.stdout);
      assertEq(events.length, 0);
    },
  },
  {
    name: 'release-writer',
    file: 'release-writer.mjs',
    payload: (cwd, session) => ({
      hook_event_name: 'UserPromptSubmit',
      prompt: '/quality release gate причина теста',
      session_id: session,
      cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assertEq(events.length, 1);
      assertEq(events[0].type, 'release');
      assert(r.stdout.includes('снятие записано'), r.stdout);
    },
  },
  {
    name: 'quality-baseline',
    file: 'quality-baseline.mjs',
    payload: (cwd, session) => ({
      hook_event_name: 'SessionStart', source: 'startup', session_id: session, cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assertEq(events.length, 1);
      assertEq(events[0].type, 'baseline');
    },
  },
  {
    name: 'quality-arm',
    file: 'quality-arm.mjs',
    payload: (cwd, session) => ({
      hook_event_name: 'PostToolUse',
      tool_name: 'Write',
      tool_input: { file_path: 'proj/New.bsl', content: 'Процедура А() КонецПроцедуры' },
      tool_use_id: 'toolu_scope_arm',
      session_id: session,
      cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assertEq(events.length, 1);
      assertEq(events[0].type, 'armed');
    },
  },
  {
    name: 'quality-stop',
    file: 'quality-stop.mjs',
    prepare: prepareStop,
    payload: (cwd, session) => ({
      hook_event_name: 'Stop', session_id: session, cwd, stop_hook_active: false,
    }),
    check(r, events) {
      assertEq(r.status, 2, r.stderr);
      assert(r.stderr.includes('правки сессии'), r.stderr);
      assertEq(events.filter((e) => e.type === 'baseline').length, 1);
    },
  },
  {
    name: 'edt-gate',
    file: 'edt-gate.mjs',
    env: { AI_EDT_GATE: 'off' },
    payload: (cwd, session) => ({
      hook_event_name: 'PreToolUse',
      tool_name: 'Read',
      tool_input: { file_path: 'a.bsl' },
      session_id: session,
      cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0);
      assert(r.stderr.includes('ворота отключены'), r.stderr);
      assertEq(events.length, 0);
    },
  },
  {
    name: 'support-guard',
    file: 'support-guard.mjs',
    prepare: async (top) => { await prepareGuard(top); },
    payload: (cwd, session) => ({
      hook_event_name: 'PreToolUse',
      tool_name: 'Edit',
      tool_input: { file_path: join(cwd, 'Catalogs', 'Items.xml') },
      session_id: session,
      cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assert(r.stdout.includes('"permissionDecision":"deny"'), r.stdout);
      assertEq(events.length, 0);
    },
  },
  {
    name: 'skill-suggester',
    file: 'skill-suggester.mjs',
    prepare: async (top) => { await prepareGuard(top); },
    payload: (cwd, session) => ({
      hook_event_name: 'PostToolUse',
      tool_name: 'Read',
      tool_input: { file_path: join(cwd, 'Catalogs', 'Items.xml') },
      session_id: session,
      cwd,
    }),
    check(r, events) {
      assertEq(r.status, 0, r.stderr);
      assert(r.stdout.includes('1c-meta-info'), r.stdout);
      assertEq(events.length, 0);
    },
  },
];

test('parseOnlyArgs: два корня и ошибка без значения', () => {
  const ok = parseOnlyArgs(['node', 'hook.mjs', '--only', 'C:/a', '--only', 'C:/b']);
  assertEq(ok.error, null);
  assertEq(ok.roots, ['C:/a', 'C:/b']);
  const missing = parseOnlyArgs(['node', 'hook.mjs', '--only']);
  assertEq(missing.roots, []);
  assertEq(missing.error, ONLY_PARSE_ERROR);
  const tail = parseOnlyArgs(['node', 'hook.mjs', '--only', 'C:/a', '--only']);
  assertEq(tail.roots, [], 'ошибка снимает уже разобранные корни');
  assertEq(tail.error, ONLY_PARSE_ERROR);
});

test('directoryInScope: пустой список, вложенный каталог, чужой префикс', async () => {
  const base = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-unit-')));
  const sibling = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-unit-')));
  try {
    assert(directoryInScope(base, []));
    const child = join(base, 'child');
    await mkdir(child);
    assert(directoryInScope(child, [base]));
    assert(directoryInScope(base, [base + (process.platform === 'win32' ? '\\' : '/')]));
    assert(!directoryInScope(sibling, [base]));
    const missingRoot = join(base, 'no-such-root');
    assert(directoryInScope(join(missingRoot, 'inner'), [missingRoot]));
    assert(!directoryInScope(join(base, 'no-such-other'), [missingRoot]));
  } finally {
    await rm(base, { recursive: true, force: true });
    await rm(sibling, { recursive: true, force: true });
  }
});

test('directoryInScope: корень файловой системы охватывает вложенные каталоги', async () => {
  const base = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-root-')));
  try {
    assert(directoryInScope(base, [parse(base).root]), `${base} внутри ${parse(base).root}`);
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test('scopeStatus: чужой корень пропускается, --only без значения не пропускает', async () => {
  const base = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-unit-')));
  const other = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-unit-')));
  try {
    const skip = scopeStatus({ cwd: other }, ['node', 'hook.mjs', '--only', base]);
    assertEq(skip.skip, true);
    assertEq(skip.error, null);
    const broken = scopeStatus({ cwd: other }, ['node', 'hook.mjs', '--only', base, '--only']);
    assertEq(broken.skip, false);
    assertEq(broken.error, ONLY_PARSE_ERROR);
  } finally {
    await rm(base, { recursive: true, force: true });
    await rm(other, { recursive: true, force: true });
  }
});

for (const c of CASES) {
  test(`--only чужой корень: ${c.name} - выход 0, пустой вывод, событий нет`, async () => {
    const ctx = await makeTmpRepo();
    const other = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-other-')));
    const session = sid();
    try {
      if (c.prepare) await c.prepare(ctx.top, session);
      const payload = c.payload(ctx.top, session);
      const before = await readEvents(ctx.top, session);
      const r = runHook(c.file, payload, { args: ['--only', other], env: c.env });
      assertEq(r.status, 0, r.stderr);
      assertEq(r.stdout, '');
      assertEq(r.stderr, '');
      const after = await readEvents(ctx.top, session);
      assertEq(after.length, before.length, 'хук записал событие вне области');
    } finally {
      await rm(other, { recursive: true, force: true });
      await ctx.cleanup();
    }
  });

  test(`--only корень репозитория: ${c.name} - обычное поведение`, async () => {
    const ctx = await makeTmpRepo();
    const session = sid();
    try {
      if (c.prepare) await c.prepare(ctx.top, session);
      const payload = c.payload(ctx.top, session);
      const r = runHook(c.file, payload, { args: ['--only', ctx.top], env: c.env });
      c.check(r, await readEvents(ctx.top, session));
    } finally {
      await ctx.cleanup();
    }
  });
}

test('--only корень репозитория, cwd во вложенном каталоге: evidence-writer', async () => {
  const ctx = await makeTmpRepo();
  const session = sid();
  const nested = join(ctx.top, 'nested', 'deeper');
  try {
    await mkdir(nested, { recursive: true });
    const c = CASES[0];
    const r = runHook(c.file, c.payload(nested, session), { args: ['--only', ctx.top] });
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await ctx.cleanup();
  }
});

test('--only корень репозитория, cwd во вложенном каталоге: session-context', async () => {
  const ctx = await makeTmpRepo();
  const session = sid();
  const nested = join(ctx.top, 'nested', 'deeper');
  try {
    await mkdir(nested, { recursive: true });
    const c = CASES[1];
    const r = runHook(c.file, c.payload(nested, session), { args: ['--only', ctx.top] });
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await ctx.cleanup();
  }
});

test('--only корень репозитория, cwd во вложенном каталоге: quality-stop', async () => {
  const ctx = await makeTmpRepo();
  const session = sid();
  const nested = join(ctx.top, 'nested', 'deeper');
  try {
    await mkdir(nested, { recursive: true });
    await prepareStop(ctx.top, session);
    const c = CASES[5];
    const r = runHook(c.file, c.payload(nested, session), { args: ['--only', ctx.top] });
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await ctx.cleanup();
  }
});

test('win32: --only в другом регистре и с обратными слешами - обычное поведение', async () => {
  if (process.platform !== 'win32') return;
  const ctx = await makeTmpRepo();
  const session = sid();
  try {
    const flipped = ctx.top.replace(/[A-Za-z]/g, (ch) => (
      ch === ch.toLowerCase() ? ch.toUpperCase() : ch.toLowerCase()
    )).replace(/\//g, '\\');
    assert(flipped !== ctx.top, 'регистр пути не изменился');
    const c = CASES[0];
    const r = runHook(c.file, c.payload(ctx.top, session), { args: ['--only', flipped] });
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await ctx.cleanup();
  }
});

test('два --only, подходит второй: evidence-writer работает', async () => {
  const ctx = await makeTmpRepo();
  const other = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-other-')));
  const session = sid();
  try {
    const c = CASES[0];
    const r = runHook(c.file, c.payload(ctx.top, session), {
      args: ['--only', other, '--only', ctx.top],
    });
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await rm(other, { recursive: true, force: true });
    await ctx.cleanup();
  }
});

test('--only без значения: обычное поведение и строка в stderr', async () => {
  const ctx = await makeTmpRepo();
  const session = sid();
  try {
    const c = CASES[0];
    const r = runHook(c.file, c.payload(ctx.top, session), { args: ['--only'] });
    assert(r.stderr.includes(ONLY_PARSE_ERROR), r.stderr);
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await ctx.cleanup();
  }
});

test('--only чужой корень и второй --only без значения: ограничение не применяется', async () => {
  const ctx = await makeTmpRepo();
  const other = realpathSync.native(await mkdtemp(join(tmpdir(), 'scope-other-')));
  const session = sid();
  try {
    const c = CASES[0];
    const r = runHook(c.file, c.payload(ctx.top, session), { args: ['--only', other, '--only'] });
    assert(r.stderr.includes(ONLY_PARSE_ERROR), r.stderr);
    c.check(r, await readEvents(ctx.top, session));
  } finally {
    await rm(other, { recursive: true, force: true });
    await ctx.cleanup();
  }
});

await run();
