// Тесты hooks/edt-gate.mjs: ворота PreToolUse и окно PostToolUseFailure.
// EDT-проект, .mcp.json и ~/.claude.json - временные каталоги. /health - локальная
// заглушка, живые серверы машины не вызываются. HOME и USERPROFILE подменены.

import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { spawn } from 'node:child_process';
import { assert, assertEq, run, test } from './harness.mjs';
import { HOOKS, REPO_ROOT, git, makeTmpRepo, readEvents, runHook, writeRepoFile } from './helpers.mjs';
import { FAIL_MATCHER, GATE_MATCHER } from '../../hooks/edt-gate.mjs';
import { sessionDir, stateRoot } from '../../hooks/common/quality-events.mjs';

const PROJECT_XML = `<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
  <name>Demo</name>
  <natures><nature>com._1c.g5.v8.dt.core.V8ConfigurationNature</nature></natures>
</projectDescription>
`;

function startStub(getBody) {
  let hits = 0;
  const server = createServer((req, res) => {
    const path = (req.url || '').split('?')[0];
    if (path !== '/health') {
      res.writeHead(404);
      res.end();
      return;
    }
    hits += 1;
    const body = getBody() || {};
    const status = body.status || 200;
    const payload = { ...body };
    delete payload.status;
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(JSON.stringify(payload));
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      let closed = false;
      resolve({
        hits: () => hits,
        mcpUrl: `http://127.0.0.1:${port}/mcp`,
        close() {
          if (closed) return Promise.resolve();
          closed = true;
          return new Promise((done) => {
            server.closeAllConnections?.();
            server.close(() => done());
          });
        },
      });
    });
  });
}

// Временный EDT-проект, заглушка /health и подмена домашнего каталога.
async function makeGate(options = {}) {
  const ctx = await makeTmpRepo();
  const home = join(dirname(ctx.top), 'home');
  await mkdir(home, { recursive: true });
  await writeRepoFile(ctx.top, '.project', PROJECT_XML);
  await writeRepoFile(ctx.top, 'src/Catalogs/Goods/Goods.mdo', '<mdclass/>\n');
  await writeRepoFile(ctx.top, 'src/Catalogs/Goods/ObjectModule.bsl', 'Процедура Тест() КонецПроцедуры\n');
  await writeRepoFile(ctx.top, 'src/Catalogs/Goods/Forms/Item/Form.form', '<form/>\n');
  await writeRepoFile(ctx.top, 'src/Catalogs/Goods/Templates/Main/Template.dcs', '<dcs/>\n');
  await writeRepoFile(ctx.top, 'README.md', 'readme\n');
  await git(ctx.top, 'add', '-A');
  await git(ctx.top, 'commit', '-q', '-m', 'project', '--no-gpg-sign', '--no-verify');

  let bodyFn = options.body || (() => ({
    phase: 'ready',
    instance: 'AI-EDT @ test',
    projects: ['Demo'],
  }));
  const stub = await startStub(() => bodyFn());
  const key = options.key || 'ai-edt';
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  delete env.AI_EDT_GATE;

  if (options.serverSpec) {
    await writeRepoFile(ctx.top, '.mcp.json', JSON.stringify({
      mcpServers: { [key]: options.serverSpec },
    }));
  } else if (options.mcp !== false) {
    await writeRepoFile(ctx.top, '.mcp.json', JSON.stringify({
      mcpServers: { [key]: { type: 'http', url: stub.mcpUrl } },
    }));
  }
  if (options.settings) {
    await writeRepoFile(ctx.top, options.settingsFile || '.claude/settings.local.json',
      JSON.stringify(options.settings));
  } else if (options.mcp !== false && !options.userServer && !options.localServer
    && !options.noEnable && !options.claudeJson && !options.serverSpec) {
    await writeRepoFile(ctx.top, '.claude/settings.local.json', JSON.stringify({
      enabledMcpjsonServers: [key],
    }));
  }
  if (options.userServer) {
    await writeFile(join(home, '.claude.json'), JSON.stringify({
      mcpServers: { [key]: { type: 'http', url: stub.mcpUrl } },
    }), 'utf8');
  }
  if (options.localServer) {
    await writeFile(join(home, '.claude.json'), JSON.stringify({
      projects: { [ctx.top]: { mcpServers: { [key]: { type: 'http', url: stub.mcpUrl } } } },
    }), 'utf8');
  }
  if (options.claudeJson) {
    await writeFile(join(home, '.claude.json'),
      JSON.stringify(options.claudeJson(ctx.top, stub.mcpUrl, key)), 'utf8');
  }

  // spawn, не spawnSync: синхронный дочерний процесс блокирует цикл событий,
  // и заглушка /health в этом же процессе не успевает ответить до таймаута.
  function run(payload, extra = {}) {
    const body = { session_id: 'edt-session', cwd: extra.cwd || ctx.top, ...payload };
    const childEnv = { ...env, ...(extra.env || {}) };
    return new Promise((resolvePromise) => {
      const child = spawn(process.execPath, [join(HOOKS, 'edt-gate.mjs')], {
        cwd: body.cwd,
        env: childEnv,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const out = [];
      const err = [];
      child.stdout.on('data', (chunk) => out.push(chunk));
      child.stderr.on('data', (chunk) => err.push(chunk));
      child.on('close', (status) => {
        resolvePromise({
          status: status ?? 1,
          stdout: Buffer.concat(out).toString('utf8'),
          stderr: Buffer.concat(err).toString('utf8'),
        });
      });
      child.stdin.write(JSON.stringify(body));
      child.stdin.end();
    });
  }

  return {
    ctx,
    stub,
    key,
    run,
    setBody(fn) { bodyFn = fn; },
    async cleanup() {
      await stub.close();
      await ctx.cleanup();
    },
  };
}

function readCall(top, rel) {
  return {
    hook_event_name: 'PreToolUse',
    tool_name: 'Read',
    tool_input: { file_path: join(top, rel) },
  };
}

function reasonOf(r) {
  assertEq(r.status, 0, r.stderr);
  assert(r.stdout.trim(), `ожидался отказ, stderr=${r.stderr}`);
  const out = JSON.parse(r.stdout);
  assertEq(out.hookSpecificOutput.hookEventName, 'PreToolUse');
  assertEq(out.hookSpecificOutput.permissionDecision, 'deny');
  return out.hookSpecificOutput.permissionDecisionReason;
}

function passed(r) {
  assertEq(r.status, 0, r.stderr);
  assertEq(r.stdout.trim(), '', `ожидался пропуск: ${r.stdout}`);
}

test('hooks.json: ворота первые в PreToolUse, окно с матчером писателя', async () => {
  const conf = JSON.parse(await readFile(join(REPO_ROOT, 'hooks', 'hooks.json'), 'utf8'));
  assertEq(conf.hooks.PreToolUse[0].matcher, GATE_MATCHER);
  assert(conf.hooks.PreToolUse[0].hooks[0].command.includes('edt-gate.mjs'));
  const fail = conf.hooks.PostToolUseFailure.filter((entry) =>
    entry.hooks.some((h) => String(h.command).includes('edt-gate.mjs')));
  assertEq(fail.length, 1);
  assertEq(fail[0].matcher, FAIL_MATCHER);
  assert(FAIL_MATCHER.includes('launch_debugger'));
  assert(FAIL_MATCHER.includes('debug_launch'));
  assert(FAIL_MATCHER.includes('start_client'));
});

test('Read .mdo при phase ready и проекте в списке отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assert(reason.includes('Goods.mdo'), reason);
    assert(reason.includes(g.key), reason);
    assert(reason.includes('get_metadata_details'), reason);
    assert(reason.includes('Сначала индекс'), reason);
    assert(reason.includes('/quality release gate'), reason);
    assert(!reason.includes('перебор исходников'), reason);
    assertEq(g.stub.hits(), 1);
  } finally {
    await g.cleanup();
  }
});

test('Read .bsl называет get_module_structure и read_method_source', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/ObjectModule.bsl')));
    assert(reason.includes('get_module_structure'), reason);
    assert(reason.includes('read_method_source'), reason);
  } finally {
    await g.cleanup();
  }
});

test('Read .form называет get_form_structure', async () => {
  const g = await makeGate({
    settings: { enableAllProjectMcpServers: true },
    settingsFile: '.claude/settings.json',
  });
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Forms/Item/Form.form')));
    assert(reason.includes('get_form_structure'), reason);
  } finally {
    await g.cleanup();
  }
});

test('Read .dcs называет dcs_workshop', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Templates/Main/Template.dcs')));
    assert(reason.includes('dcs_workshop'), reason);
  } finally {
    await g.cleanup();
  }
});

test('остановленный сервер: Read пропускается', async () => {
  const g = await makeGate();
  try {
    await g.stub.close();
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
  } finally {
    await g.cleanup();
  }
});

test('проект не в projects: Read пропускается', async () => {
  const g = await makeGate({
    body: () => ({ phase: 'ready', instance: 'AI-EDT @ test', projects: ['Other'] }),
  });
  try {
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assert(g.stub.hits() >= 1, 'health запрошен');
  } finally {
    await g.cleanup();
  }
});

test('Read фикстуры tests/catalog вне EDT-проекта пропускается без запроса /health', async () => {
  const home = await mkdtemp(join(tmpdir(), 'edt-gate-home-'));
  const stub = await startStub(() => ({ phase: 'ready', instance: 'AI-EDT @ test', projects: ['Demo'] }));
  try {
    await writeFile(join(home, '.claude.json'), JSON.stringify({
      mcpServers: { 'ai-edt': { type: 'http', url: stub.mcpUrl } },
    }), 'utf8');
    const file = join(REPO_ROOT, 'tests', 'catalog', 'TXN-01', 'clean.bsl');
    const payload = {
      hook_event_name: 'PreToolUse',
      tool_name: 'Read',
      tool_input: { file_path: file },
      cwd: REPO_ROOT,
      session_id: 'edt-outside',
    };
    const r = await new Promise((resolvePromise) => {
      const child = spawn(process.execPath, [join(HOOKS, 'edt-gate.mjs')], {
        cwd: REPO_ROOT,
        env: { ...process.env, HOME: home, USERPROFILE: home },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const out = [];
      const err = [];
      child.stdout.on('data', (chunk) => out.push(chunk));
      child.stderr.on('data', (chunk) => err.push(chunk));
      child.on('close', (status) => {
        resolvePromise({
          status: status ?? 1,
          stdout: Buffer.concat(out).toString('utf8'),
          stderr: Buffer.concat(err).toString('utf8'),
        });
      });
      child.stdin.write(JSON.stringify(payload));
      child.stdin.end();
    });
    passed(r);
    assertEq(stub.hits(), 0);
  } finally {
    await stub.close();
    await rm(home, { recursive: true, force: true });
  }
});

test('Grep по каталогу проекта отклоняется, замена code_search', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'Grep',
      tool_input: { pattern: 'Процедура', path: join(g.ctx.top, 'src') },
    }));
    assert(reason.includes('code_search operation=text_search'), reason);
    assert(!reason.includes('перебор исходников'), reason);
  } finally {
    await g.cleanup();
  }
});

test('Glob по каталогу проекта отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'Glob',
      tool_input: { pattern: '**/*.bsl', path: join(g.ctx.top, 'src') },
    }));
    assert(reason.includes('code_search operation=text_search'), reason);
  } finally {
    await g.cleanup();
  }
});

test('Bash cat src/.../Module.bsl отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'cat src/Catalogs/Goods/ObjectModule.bsl' },
    }));
    assert(reason.includes('Перебор исходников при живой EDT'), reason);
    assert(reason.includes('get_module_structure'), reason);
    assert(reason.includes(g.key), reason);
  } finally {
    await g.cleanup();
  }
});

test('Bash git diff пропускается', async () => {
  const g = await makeGate();
  try {
    passed(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'git diff' },
    }));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('Bash python tools/x.py без пути src пропускается', async () => {
  const g = await makeGate();
  try {
    passed(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'python tools/x.py' },
    }));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('PowerShell Get-Content отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run({
      hook_event_name: 'PreToolUse',
      tool_name: 'PowerShell',
      tool_input: { command: 'Get-Content -Path src/Catalogs/Goods/ObjectModule.bsl' },
    }));
    assert(reason.includes('Перебор исходников при живой EDT'), reason);
    assert(reason.includes('read_method_source'), reason);
  } finally {
    await g.cleanup();
  }
});

test('сервер из .mcp.json учитывается при поиске вверх от cwd', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(
      readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'),
      { cwd: join(g.ctx.top, 'src') },
    ));
    assert(reason.includes('get_metadata_details'), reason);
  } finally {
    await g.cleanup();
  }
});

test('сервер из mcpServers ~/.claude.json учитывается', async () => {
  const g = await makeGate({ mcp: false, userServer: true, key: '1c-edt' });
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assert(reason.includes('1c-edt'), reason);
  } finally {
    await g.cleanup();
  }
});

test('сервер из projects[cwd].mcpServers учитывается', async () => {
  const g = await makeGate({ mcp: false, localServer: true, key: 'ai-edt-local' });
  try {
    const reason = reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assert(reason.includes('ai-edt-local'), reason);
  } finally {
    await g.cleanup();
  }
});

test('сервер .mcp.json включен флагом projects[cwd].enabledMcpjsonServers', async () => {
  const g = await makeGate({
    noEnable: true,
    claudeJson: (top, _url, key) => ({
      projects: { [top]: { enabledMcpjsonServers: [key] } },
    }),
  });
  try {
    reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
  } finally {
    await g.cleanup();
  }
});

test('выключенный через disabledMcpjsonServers не учитывается', async () => {
  const g = await makeGate({
    settings: {
      enableAllProjectMcpServers: true,
      enabledMcpjsonServers: ['ai-edt'],
      disabledMcpjsonServers: ['ai-edt'],
    },
  });
  try {
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('сервер .mcp.json без флага включения не учитывается', async () => {
  const g = await makeGate({ noEnable: true });
  try {
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('ключ plugin_ не рассматривается', async () => {
  const g = await makeGate({
    key: 'plugin_ai',
    settings: { enabledMcpjsonServers: ['plugin_ai'] },
  });
  try {
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('сервер type не http не рассматривается', async () => {
  const g = await makeGate({
    serverSpec: { type: 'stdio', command: 'node' },
    settings: { enableAllProjectMcpServers: true },
  });
  try {
    passed(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('кэш /health: второй Read не запрашивает сервер', async () => {
  const g = await makeGate();
  try {
    reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo')));
    reasonOf(await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/ObjectModule.bsl')));
    assertEq(g.stub.hits(), 1);
  } finally {
    await g.cleanup();
  }
});

test('окно после отказа с phase building пропускает Read, после until снова отказ', async () => {
  const g = await makeGate();
  const session = 'win-session';
  try {
    g.setBody(() => ({ phase: 'building', instance: 'AI-EDT @ test', projects: ['Demo'] }));
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__validate_query',
      tool_input: { queryText: 'ВЫБРАТЬ 1' },
      error: 'connection closed',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const winFile = join(sessionDir(g.ctx.top, session), 'edt-window.json');
    const win = JSON.parse(await readFile(winFile, 'utf8'));
    assertEq(win.server, 'ai-edt');
    const left = Date.parse(win.until) - Date.now();
    assert(left > 14 * 60 * 1000 && left < 16 * 60 * 1000, `until около 15 минут: ${win.until}`);
    const events = await readEvents(g.ctx.top, session);
    const probe = events.find((e) => e.type === 'probe');
    assert(probe, 'событие probe');
    assertEq(probe.status, 'down');
    assertEq(probe.source, 'ai-edt');
    assert(String(probe.detail).includes('building'), probe.detail);

    g.setBody(() => ({ phase: 'ready', instance: 'AI-EDT @ test', projects: ['Demo'] }));
    await rm(join(stateRoot(g.ctx.top), 'edt-health.json'), { force: true });
    passed(await g.run({ ...readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'), session_id: session }));

    win.until = '2000-01-01T00:00:00.000Z';
    await writeFile(winFile, JSON.stringify(win), 'utf8');
    await rm(join(stateRoot(g.ctx.top), 'edt-health.json'), { force: true });
    const reason = reasonOf(await g.run({
      ...readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'),
      session_id: session,
    }));
    assert(reason.includes('get_metadata_details'), reason);
  } finally {
    await g.cleanup();
  }
});

test('отказ операции при phase ready окно не открывает', async () => {
  const g = await makeGate();
  const session = 'live-session';
  try {
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__validate_query',
      tool_input: {},
      error: 'ошибка разбора запроса',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const events = await readEvents(g.ctx.top, session);
    const probe = events.find((e) => e.type === 'probe');
    assert(probe, 'событие probe');
    assertEq(probe.status, 'ok');
    let missing = false;
    try {
      await readFile(join(sessionDir(g.ctx.top, session), 'edt-window.json'), 'utf8');
    } catch (err) {
      missing = err.code === 'ENOENT';
    }
    assert(missing, 'окно не создано');
    reasonOf(await g.run({ ...readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'), session_id: session }));
  } finally {
    await g.cleanup();
  }
});

test('отказ авторизации /health открывает окно', async () => {
  const g = await makeGate();
  const session = 'auth-session';
  try {
    g.setBody(() => ({ status: 401, phase: 'ready', instance: 'AI-EDT @ test', projects: ['Demo'] }));
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__code_review',
      tool_input: {},
      error: '401',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const events = await readEvents(g.ctx.top, session);
    assertEq(events.find((e) => e.type === 'probe').status, 'down');
    const win = JSON.parse(await readFile(
      join(sessionDir(g.ctx.top, session), 'edt-window.json'), 'utf8'));
    assertEq(win.server, 'ai-edt');
  } finally {
    await g.cleanup();
  }
});

test('действующее release gate пропускает Read', async () => {
  const g = await makeGate();
  const session = 'rel-session';
  try {
    reasonOf(await g.run({ ...readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'), session_id: session }));
    const rel = runHook('release-writer.mjs', {
      hook_event_name: 'UserPromptSubmit',
      prompt: '/quality release gate проверка вручную --for 1h',
      session_id: session,
      cwd: g.ctx.top,
    }, { cwd: g.ctx.top });
    assertEq(rel.status, 0, rel.stderr);
    passed(await g.run({ ...readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'), session_id: session }));
  } finally {
    await g.cleanup();
  }
});

test('Read README внутри проекта пропускается', async () => {
  const g = await makeGate();
  try {
    passed(await g.run(readCall(g.ctx.top, 'README.md')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

function launchCall(command, tool = 'Bash') {
  return {
    hook_event_name: 'PreToolUse',
    tool_name: tool,
    tool_input: { command },
  };
}

function clientCommand(top) {
  return '1cv8c.exe ENTERPRISE /F "' + top + '" /N"Admin" /P"secret"';
}

test('1cv8c.exe с /N и /P по проекту живого инстанса отклоняется и называет три выхода', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(launchCall(clientCommand(g.ctx.top))));
    assert(reason.includes('launch_debugger action=launch'), reason);
    assert(reason.includes('externalObjectName'), reason);
    assert(reason.includes('externalObjectProject'), reason);
    assert(reason.includes('startupOption'), reason);
    assert(reason.includes('enableExternalObjectDump=true'), reason);
    assert(reason.includes('set_infobase_credentials'), reason);
    assert(reason.includes('15 минут'), reason);
    assert(reason.includes('debug_launch'), reason);
    assert(reason.includes('start_client'), reason);
    assert(reason.includes('/quality release gate'), reason);
    assert(reason.includes('AI_EDT_GATE=off'), reason);
    assert(reason.includes('Demo'), reason);
  } finally {
    await g.cleanup();
  }
});

test('тот же запуск 1cv8c.exe при остановленном инстансе пропускается', async () => {
  const g = await makeGate();
  try {
    await g.stub.close();
    passed(await g.run(launchCall(clientCommand(g.ctx.top))));
  } finally {
    await g.cleanup();
  }
});

test('start-1c.ps1 по проекту живого инстанса отклоняется', async () => {
  const g = await makeGate();
  try {
    const command = 'powershell.exe -NoProfile -File "C:\\Users\\me\\.claude\\skills\\1c-mcp-toolkit\\scripts\\start-1c.ps1"'
      + ' -Database "' + g.ctx.top + '" -User Admin -Password secret';
    const reason = reasonOf(await g.run(launchCall(command, 'PowerShell')));
    assert(reason.includes('launch_debugger action=launch'), reason);
    assert(reason.includes('AI_EDT_GATE=off'), reason);
  } finally {
    await g.cleanup();
  }
});

test('запуск 1С по проекту, которого нет в projects, пропускается', async () => {
  const g = await makeGate({
    body: () => ({ phase: 'ready', instance: 'AI-EDT @ test', projects: ['Other'] }),
  });
  try {
    passed(await g.run(launchCall(clientCommand(g.ctx.top))));
    assert(g.stub.hits() >= 1, 'health запрошен');
  } finally {
    await g.cleanup();
  }
});

test('AI_EDT_GATE=off пропускает запуск и пишет диагностику', async () => {
  const g = await makeGate();
  try {
    const r = await g.run(launchCall(clientCommand(g.ctx.top)), { env: { AI_EDT_GATE: 'off' } });
    passed(r);
    assert(r.stderr.includes('ворота отключены переменной AI_EDT_GATE'), r.stderr);
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

test('AI_EDT_GATE=on оставляет ворота включенными', async () => {
  const g = await makeGate();
  try {
    const r = await g.run(launchCall(clientCommand(g.ctx.top)), { env: { AI_EDT_GATE: 'on' } });
    const reason = reasonOf(r);
    assert(reason.includes('launch_debugger action=launch'), reason);
    assert(!r.stderr.includes('отключены'), r.stderr);
  } finally {
    await g.cleanup();
  }
});

test('AI_EDT_GATE с прочим непустым значением отключает ворота', async () => {
  const g = await makeGate();
  try {
    const r = await g.run(launchCall(clientCommand(g.ctx.top)), { env: { AI_EDT_GATE: '0' } });
    passed(r);
    assert(r.stderr.includes('AI_EDT_GATE'), r.stderr);
  } finally {
    await g.cleanup();
  }
});

test('пустая AI_EDT_GATE ворота не отключает', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(launchCall(clientCommand(g.ctx.top)), { env: { AI_EDT_GATE: '' } }));
    assert(reason.includes('launch_debugger'), reason);
  } finally {
    await g.cleanup();
  }
});

test('отказ launch_debugger при phase ready открывает окно, после until запуск снова отклоняется', async () => {
  const g = await makeGate();
  const session = 'launch-win';
  try {
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__launch_debugger',
      tool_input: { action: 'launch' },
      error: 'порт отладки уже используется',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const events = await readEvents(g.ctx.top, session);
    const probe = events.find((e) => e.type === 'probe');
    assert(probe, 'событие probe');
    assertEq(probe.status, 'ok');
    assertEq(probe.source, 'ai-edt');
    const winFile = join(sessionDir(g.ctx.top, session), 'edt-window.json');
    const win = JSON.parse(await readFile(winFile, 'utf8'));
    assertEq(win.server, 'ai-edt');
    const left = Date.parse(win.until) - Date.now();
    assert(left > 14 * 60 * 1000 && left < 16 * 60 * 1000, `until около 15 минут: ${win.until}`);
    passed(await g.run({ ...launchCall(clientCommand(g.ctx.top)), session_id: session }));

    win.until = '2000-01-01T00:00:00.000Z';
    await writeFile(winFile, JSON.stringify(win), 'utf8');
    const reason = reasonOf(await g.run({
      ...launchCall(clientCommand(g.ctx.top)),
      session_id: session,
    }));
    assert(reason.includes('launch_debugger action=launch'), reason);
  } finally {
    await g.cleanup();
  }
});

test('отказ debug_launch при phase ready открывает окно', async () => {
  const g = await makeGate();
  const session = 'debug-launch-win';
  try {
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__debug_launch',
      tool_input: {},
      error: 'нет приложения',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const events = await readEvents(g.ctx.top, session);
    assertEq(events.find((e) => e.type === 'probe').status, 'ok');
    const win = JSON.parse(await readFile(
      join(sessionDir(g.ctx.top, session), 'edt-window.json'), 'utf8'));
    assertEq(win.server, 'ai-edt');
  } finally {
    await g.cleanup();
  }
});

test('отказ start_client при phase ready открывает окно', async () => {
  const g = await makeGate();
  const session = 'start-client-win';
  try {
    const fail = await g.run({
      hook_event_name: 'PostToolUseFailure',
      tool_name: 'mcp__ai-edt__start_client',
      tool_input: {},
      error: 'реструктуризация',
      session_id: session,
    });
    assertEq(fail.status, 0, fail.stderr);
    const events = await readEvents(g.ctx.top, session);
    assertEq(events.find((e) => e.type === 'probe').status, 'ok');
    const win = JSON.parse(await readFile(
      join(sessionDir(g.ctx.top, session), 'edt-window.json'), 'utf8'));
    assertEq(win.server, 'ai-edt');
    passed(await g.run({ ...launchCall(clientCommand(g.ctx.top)), session_id: session }));
  } finally {
    await g.cleanup();
  }
});

test('действующее release gate пропускает запуск клиента', async () => {
  const g = await makeGate();
  const session = 'rel-launch';
  try {
    reasonOf(await g.run({ ...launchCall(clientCommand(g.ctx.top)), session_id: session }));
    const rel = runHook('release-writer.mjs', {
      hook_event_name: 'UserPromptSubmit',
      prompt: '/quality release gate запуск вручную --for 1h',
      session_id: session,
      cwd: g.ctx.top,
    }, { cwd: g.ctx.top });
    assertEq(rel.status, 0, rel.stderr);
    passed(await g.run({ ...launchCall(clientCommand(g.ctx.top)), session_id: session }));
  } finally {
    await g.cleanup();
  }
});

test('битый .mcp.json на запуске клиента: пропуск и диагностика', async () => {
  const g = await makeGate({ noEnable: true });
  try {
    await writeRepoFile(g.ctx.top, '.mcp.json', '{ this is not json');
    const r = await g.run(launchCall(clientCommand(g.ctx.top)));
    passed(r);
    assert(r.stderr.includes('[edt-gate]'), r.stderr);
    assert(r.stderr.includes('.mcp.json'), r.stderr);
  } finally {
    await g.cleanup();
  }
});

test('запуск без пути базы из каталога EDT-проекта отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(launchCall('1cv8c.exe /N Admin /P secret')));
    assert(reason.includes('launch_debugger action=launch'), reason);
    assert(reason.includes(g.ctx.top), reason);
  } finally {
    await g.cleanup();
  }
});

test('запуск с /F вне EDT-проекта пропускается, даже если cwd внутри проекта', async () => {
  const g = await makeGate();
  const outside = await mkdtemp(join(tmpdir(), 'edt-gate-base-'));
  try {
    passed(await g.run(launchCall('1cv8c.exe /F "' + outside + '" /N Admin /P secret')));
    assertEq(g.stub.hits(), 0);
  } finally {
    await rm(outside, { recursive: true, force: true });
    await g.cleanup();
  }
});

test('1cv8c без расширения .exe отклоняется', async () => {
  const g = await makeGate();
  try {
    const reason = reasonOf(await g.run(launchCall('1cv8c ENTERPRISE /F "' + g.ctx.top + '" /N u /P p')));
    assert(reason.includes('launch_debugger'), reason);
  } finally {
    await g.cleanup();
  }
});

test('1cv8.exe и 1cv8s.exe по проекту живого инстанса отклоняются', async () => {
  const g = await makeGate();
  try {
    const thick = reasonOf(await g.run(launchCall('1cv8.exe ENTERPRISE /F "' + g.ctx.top + '" /N u /P p')));
    assert(thick.includes('launch_debugger action=launch'), thick);
    const server = reasonOf(await g.run(launchCall('"C:\\Program Files\\1cv8\\8.3.27.1508\\bin\\1cv8s.exe" /F "' + g.ctx.top + '"')));
    assert(server.includes('set_infobase_credentials'), server);
  } finally {
    await g.cleanup();
  }
});

test('хранилище недоступно: 1cv8c.exe /N /P по живому инстансу пропускается', async () => {
  const g = await makeGate();
  const base = await mkdtemp(join(tmpdir(), 'quality-blocker-'));
  const blocker = join(base, 'not-dir');
  await writeFile(blocker, 'x', 'utf8');
  try {
    const r = await g.run(launchCall('1cv8c.exe /N"u" /P"p"'), { env: { QUALITY_STATE_DIR: blocker } });
    passed(r);
    assert(r.stderr.includes('след недоступен'), r.stderr);
  } finally {
    await g.cleanup();
    await rm(base, { recursive: true, force: true });
  }
});

test('битый .mcp.json: пропуск и диагностика в stderr', async () => {
  const g = await makeGate({ noEnable: true });
  try {
    await writeRepoFile(g.ctx.top, '.mcp.json', '{ this is not json');
    const r = await g.run(readCall(g.ctx.top, 'src/Catalogs/Goods/Goods.mdo'));
    passed(r);
    assert(r.stderr.includes('[edt-gate]'), r.stderr);
    assert(r.stderr.includes('.mcp.json'), r.stderr);
    assertEq(g.stub.hits(), 0);
  } finally {
    await g.cleanup();
  }
});

await run();
