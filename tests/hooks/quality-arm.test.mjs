// Тесты hooks/quality-arm.mjs: атрибуция правки инструменту записи - событие armed по
// Edit/Write/MultiEdit/NotebookEdit и MCP-инструментам записи AI-EDT (реальные имена
// инструментов с дефисами и номерами версий в ключе сервера), матчер не пускает чтение.

import { assert, assertEq, run, test } from './harness.mjs';
import { loadFixture, makeTmpRepo, readEvents, runHook } from './helpers.mjs';
import { ARM_MATCHER } from '../../hooks/quality-arm.mjs';

const RE = new RegExp(ARM_MATCHER);

test('матчер покрывает инструменты записи и MCP-инструменты AI-EDT', () => {
  for (const name of ['Write', 'Edit', 'MultiEdit', 'NotebookEdit',
    'mcp__1c-edt__write_module_source', 'mcp__ai-edt-3_1_38_92__write_module_source',
    'mcp__ai-edt__edit_metadata', 'mcp__1c-edt__edit_form', 'mcp__1c-edt__config_io',
    'mcp__1c-edt__xdto_workshop', 'mcp__1c-edt__external_object_workshop']) {
    assert(RE.test(name), `матчер не покрыл: ${name}`);
  }
});

test('матчер не пускает чтение и прочие инструменты', () => {
  for (const name of ['Read', 'Grep', 'Glob', 'Bash', 'PowerShell', 'Task',
    'mcp__1c-edt__read_module_source', 'mcp__1c-edt__get_module_structure',
    'mcp__1c-edt__validate_query', 'mcp__1c-edt__diagnostics']) {
    assert(!RE.test(name), `матчер ошибочно покрыл: ${name}`);
  }
});

test('Edit: событие armed с файлом, инструментом и toolUseId', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('edit-tool', { cwd: ctx.top, session_id: 'arm-session-1' });
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'arm-session-1');
    assertEq(e.type, 'armed');
    assertEq(e.file, 'proj/src/CommonModules/Обмен/Module.bsl', 'файл из file_path');
    assertEq(e.tool, 'Edit');
    assertEq(e.toolUseId, 'toolu_fixture_edit');
    assertEq(e.producer, 'hook');
    assert(typeof e.diffHash === 'string' && e.diffHash.length === 64, 'diffHash вычислен');
  } finally {
    await ctx.cleanup();
  }
});

test('Write: событие armed', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = {
      hook_event_name: 'PostToolUse',
      tool_name: 'Write',
      tool_input: { file_path: 'proj/src/CommonModules/Обмен/New.bsl', content: 'Процедура А() КонецПроцедуры' },
      tool_response: 'File created',
      tool_use_id: 'toolu_arm_write',
      cwd: ctx.top,
      session_id: 'arm-session-1',
    };
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'arm-session-1');
    assertEq(e.type, 'armed');
    assertEq(e.tool, 'Write');
    assertEq(e.file, 'proj/src/CommonModules/Обмен/New.bsl');
  } finally {
    await ctx.cleanup();
  }
});

test('MCP write_module_source: armed с файлом из modulePath', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('arm-mcp-write-module', { cwd: ctx.top, session_id: 'arm-session-1' });
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'arm-session-1');
    assertEq(e.type, 'armed');
    assertEq(e.tool, 'mcp__1c-edt__write_module_source');
    assertEq(e.file, 'proj/src/CommonModules/Обмен/Module.bsl', 'файл из modulePath');
  } finally {
    await ctx.cleanup();
  }
});

test('MCP edit_metadata с номером версии в ключе сервера: armed с файлом из fqn', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('arm-mcp-edit-metadata', { cwd: ctx.top, session_id: 'arm-session-1' });
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0, r.stderr);
    const [e] = await readEvents(ctx.top, 'arm-session-1');
    assertEq(e.type, 'armed');
    assertEq(e.tool, 'mcp__ai-edt-3_1_38_92__edit_metadata');
    assertEq(e.file, 'Catalog.Контрагенты.Attribute.Комментарий', 'файл из fqn');
  } finally {
    await ctx.cleanup();
  }
});

test('MCP config_io и мастерская: armed с файлом из inputPath и fqn', async () => {
  const ctx = await makeTmpRepo();
  try {
    for (const [fixture, expectedFile] of [['arm-mcp-config-io', 'dump/xml'],
      ['arm-mcp-workshop', 'CommonModule.Обмен']]) {
      const payload = await loadFixture(fixture, { cwd: ctx.top, session_id: 'arm-session-1' });
      const r = runHook('quality-arm.mjs', payload);
      assertEq(r.status, 0, r.stderr);
    }
    const events = await readEvents(ctx.top, 'arm-session-1');
    assertEq(events.length, 2);
    assertEq(events[0].file, 'dump/xml', 'config_io: файл из inputPath');
    assertEq(events[1].file, 'CommonModule.Обмен', 'мастерская: файл из fqn');
  } finally {
    await ctx.cleanup();
  }
});

test('Read: события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('arm-read', { cwd: ctx.top, session_id: 'arm-session-1' });
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0);
    assertEq(r.stderr.trim(), '', 'молча');
    assertEq((await readEvents(ctx.top, 'arm-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('cwd вне git-репозитория: код 0, событие не пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('edit-tool', { cwd: ctx.top, session_id: 'arm-session-1' });
    payload.cwd = ctx.top + '-нет';
    const r = runHook('quality-arm.mjs', payload);
    assertEq(r.status, 0, 'внутренняя ошибка хука не блокирует');
    assert(r.stderr.includes('не является git-репозиторием'), `причина в stderr: ${r.stderr}`);
    assertEq((await readEvents(ctx.top, 'arm-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

await run();
