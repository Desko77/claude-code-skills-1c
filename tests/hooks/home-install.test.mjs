// Домашняя установка: копия раскладки установщика во временном доме (HOME и USERPROFILE).
// resolveEvidencePy из копии находит evidence.py в доме, evidence-writer считает critical
// по гейтовому конфигу скила, quality-stop доходит до вызова валидатора.

import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { makeTmpRepo, readEvents, REPO_ROOT, writeRepoFile } from './helpers.mjs';

const TOOL_NAMES = ['install_home.py', 'changeset.py', 'change_profile.py', 'evidence.py', 'quality_events.py'];

function slash(p) {
  let s = String(p).replace(/\\/g, '/');
  while (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1);
  return process.platform === 'win32' ? s.toLowerCase() : s;
}

function homeEnv(home) {
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  delete env.CLAUDE_PLUGIN_ROOT;
  return env;
}

async function makeHome(withSkill) {
  const home = realpathSync.native(await mkdtemp(join(tmpdir(), 'home-install-')));
  const claude = join(home, '.claude');
  const hooks = join(claude, 'hooks', '1c-skills');
  await cp(join(REPO_ROOT, 'hooks'), hooks, { recursive: true });
  const toolsDir = join(claude, 'tools', '1c-skills');
  await mkdir(toolsDir, { recursive: true });
  for (const name of TOOL_NAMES) {
    await cp(join(REPO_ROOT, 'tools', name), join(toolsDir, name));
  }
  if (withSkill) {
    const assetDir = join(claude, 'skills', '1c-code-review', 'assets');
    await mkdir(assetDir, { recursive: true });
    await cp(join(REPO_ROOT, 'skills', '1c-code-review', 'assets', 'bsl-ls-gate.json'),
      join(assetDir, 'bsl-ls-gate.json'));
  }
  return { home, hooks, cleanup: () => rm(home, { recursive: true, force: true }) };
}

function runCopy(script, payload, env, cwd) {
  return spawnSync(process.execPath, [script], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    cwd,
    env,
  });
}

const REVIEW_TEXT = 'CreateQueryInCycle: запрос в цикле, строка 12';

function reviewPayload(cwd, session) {
  return {
    hook_event_name: 'PostToolUse',
    tool_name: 'mcp__1c-edt__code_review',
    tool_input: { modulePath: 'proj/src/Module.bsl' },
    tool_response: REVIEW_TEXT,
    tool_use_id: 'toolu_home_review',
    cwd,
    session_id: session,
  };
}

test('репозиторий набора: resolveEvidencePy находит tools/evidence.py без лишнего tools/', async () => {
  const { resolveEvidencePy } = await import('../../hooks/common/quality-gate.mjs');
  const found = await resolveEvidencePy();
  assert(found, 'путь не найден');
  const norm = slash(found);
  assert(norm.endsWith('/tools/evidence.py'), found);
  assert(!norm.includes('/1c-skills/tools/evidence.py'), found);
});

test('домашняя копия: resolveEvidencePy возвращает evidence.py в доме', async () => {
  const layout = await makeHome(true);
  try {
    const probe = join(layout.home, 'probe-evidence.mjs');
    await writeFile(probe, [
      "import { pathToFileURL } from 'node:url';",
      'const mod = await import(pathToFileURL(process.argv[2]).href);',
      'const found = await mod.resolveEvidencePy();',
      "process.stdout.write(found || '');",
      '',
    ].join('\n'), 'utf8');
    const script = join(layout.hooks, 'common', 'quality-gate.mjs');
    const r = spawnSync(process.execPath, [probe, script], {
      encoding: 'utf8',
      env: homeEnv(layout.home),
    });
    assertEq(r.status, 0, r.stderr);
    const expected = join(layout.home, '.claude', 'tools', '1c-skills', 'evidence.py');
    assertEq(slash(r.stdout.trim()), slash(expected), r.stdout);
  } finally {
    await layout.cleanup();
  }
});

test('домашняя копия: code_review пишет applied с ненулевым critical', async () => {
  const layout = await makeHome(true);
  const ctx = await makeTmpRepo();
  try {
    const r = runCopy(join(layout.hooks, 'evidence-writer.mjs'),
      reviewPayload(ctx.top, 'home-review'), homeEnv(layout.home), ctx.top);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'home-review');
    assert(e, 'событие не записано');
    assertEq(e.type, 'applied');
    assertEq(e.check, 'code_review@edt');
    assertEq(e.outcome.status, 'findings');
    assert(e.outcome.critical > 0, `critical: ${e.outcome.critical}`);
  } finally {
    await ctx.cleanup();
    await layout.cleanup();
  }
});

test('домашняя копия без каталога скила: событие записано, числа нулевые', async () => {
  const layout = await makeHome(false);
  const ctx = await makeTmpRepo();
  try {
    const r = runCopy(join(layout.hooks, 'evidence-writer.mjs'),
      reviewPayload(ctx.top, 'home-noskill'), homeEnv(layout.home), ctx.top);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'home-noskill');
    assert(e, 'событие не записано');
    assertEq(e.type, 'applied');
    assertEq(e.outcome.critical, 0);
    assertEq(e.outcome.major, 0);
    assertEq(e.outcome.minor, 0);
  } finally {
    await ctx.cleanup();
    await layout.cleanup();
  }
});

test('домашняя копия: quality-stop доходит до evidence.py', async () => {
  const layout = await makeHome(true);
  const ctx = await makeTmpRepo();
  try {
    const env = homeEnv(layout.home);
    const session = 'home-stop';
    const baseline = runCopy(join(layout.hooks, 'quality-baseline.mjs'), {
      hook_event_name: 'SessionStart', source: 'startup', session_id: session, cwd: ctx.top,
    }, env, ctx.top);
    assertEq(baseline.status, 0, baseline.stderr);
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', 'Процедура Новая()\nКонецПроцедуры\n');
    const r = runCopy(join(layout.hooks, 'quality-stop.mjs'), {
      hook_event_name: 'Stop', session_id: session, cwd: ctx.top, stop_hook_active: false,
    }, env, ctx.top);
    assert(!String(r.stderr).includes('не найден'), r.stderr);
    assertEq(r.status, 2, `гейт не дошел до валидатора: ${r.stderr}`);
    assert(r.stderr.includes('правки сессии'), r.stderr);
  } finally {
    await ctx.cleanup();
    await layout.cleanup();
  }
});

await run();
