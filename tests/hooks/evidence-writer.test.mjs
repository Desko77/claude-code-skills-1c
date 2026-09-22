// Тесты hooks/evidence-writer.mjs: матчер, определение проверки, разбор итогов и запись
// событий applied/failed по payload-фикстурам. Чтение событий - прямым разбором каталога
// следа; сквозная совместимость с tools/evidence.py - в end-to-end.test.mjs.

import { assert, assertEq, run, test } from './harness.mjs';
import { loadFixture, makeTmpRepo, readEvents, runHook, spawnHook } from './helpers.mjs';
import { MATCHER, outcomeFor, resolveCheck } from '../../hooks/evidence-writer.mjs';

const RE = new RegExp(MATCHER);

test('матчер покрывает инструменты проверки двух ключей сервера и Bash/PowerShell', () => {
  for (const name of ['mcp__1c-edt__validate_query', 'mcp__ai-edt-3_1_38_92__validate_query',
    'mcp__ai-edt__code_review', 'mcp__1c-edt__diagnostics', 'mcp__1c-edt__validate_for_export',
    'mcp__1c-edt__security_audit', 'mcp__naparnik__ask_1c_ai', 'mcp__naparnik__check_1c_code',
    'mcp__1c-syntax-checker-mcp__syntaxcheck', 'mcp__1c-edt__insights', 'Bash', 'PowerShell']) {
    assert(RE.test(name), `матчер не покрыл: ${name}`);
  }
});

test('матчер не пускает прочие инструменты', () => {
  for (const name of ['mcp__1c-edt__write_module_source', 'mcp__1c-edt__read_module_source',
    'Edit', 'Read', 'Write', 'Grep', 'Glob', 'Task']) {
    assert(!RE.test(name), `матчер ошибочно покрыл: ${name}`);
  }
});

test('resolveCheck: фасад diagnostics различает операции', () => {
  const gpe = resolveCheck('mcp__1c-edt__diagnostics', { operation: 'get_project_errors' }, '');
  assertEq(gpe.check, 'get_project_errors@edt');
  const vfe = resolveCheck('mcp__1c-edt__diagnostics', { operation: 'validate_for_export' }, '');
  assertEq(vfe.check, 'validate_for_export@edt');
  assertEq(resolveCheck('mcp__1c-edt__diagnostics', { operation: 'revalidate_objects' }, ''), null);
  assertEq(resolveCheck('mcp__1c-edt__diagnostics', {}, ''), null);
});

test('resolveCheck: фасад insights открывает только detect_query_anti_patterns', () => {
  const ok = resolveCheck('mcp__1c-edt__insights', { operation: 'detect_query_anti_patterns' }, '');
  assertEq(ok.check, 'detect_query_anti_patterns@edt');
  assertEq(resolveCheck('mcp__1c-edt__insights', { operation: 'coverage' }, ''), null);
});

test('resolveCheck: check_1c_code и ask_1c_ai закрывают одну проверку', () => {
  const a = resolveCheck('mcp__naparnik__ask_1c_ai', {}, '');
  const b = resolveCheck('mcp__naparnik__check_1c_code', {}, '');
  assertEq(a.check, 'ask_1c_ai@edt');
  assertEq(a.level, 'llm');
  assertEq(b.check, 'ask_1c_ai@edt');
});

test('outcomeFor: validate_query при отсутствии ошибок - pass', async () => {
  const r = await outcomeFor('validate_query', 'Запрос корректен. Ошибок не обнаружено.');
  assertEq(r.status, 'pass');
});

test('outcomeFor: validate_query со строками ошибок - findings по числу строк', async () => {
  const r = await outcomeFor('validate_query', 'Ошибка 1: поле не найдено\nОшибка 2: неверный параметр');
  assertEq(r.status, 'findings');
  assertEq(r.minor, 2);
  assertEq(r.critical, 0);
});

test('outcomeFor: code_review считает находки по важностям карточек', async () => {
  const text = 'PERF-01 CreateQueryInCycle: запрос в цикле, строка 12\n'
    + 'SEC-02 SetPrivilegedMode: привилегированный режим, строка 40\n'
    + 'MODEL-14 IfElseIfEndsWithElse: ветка иначе, строка 7';
  const r = await outcomeFor('code_review', text);
  assertEq(r.status, 'findings');
  assertEq(r.critical, 2);
  assertEq(r.major, 1);
  assertEq(r.minor, 0);
});

test('outcomeFor: code_review без находок и с фразой чистоты - pass', async () => {
  const r = await outcomeFor('code_review', 'Нарушений не найдено.');
  assertEq(r.status, 'pass');
});

test('outcomeFor: code_review без находок и без фразы - unknown с фрагментом', async () => {
  const r = await outcomeFor('code_review', 'Обработано 3 модуля');
  assertEq(r.status, 'unknown');
  assertEq(r.raw, 'Обработано 3 модуля');
});

test('outcomeFor: get_project_errors - ошибки critical, предупреждения minor', async () => {
  const text = 'Ошибок: 2\nОшибка: не разрешена ссылка на метод\nПредупреждение: переменная не используется';
  const r = await outcomeFor('get_project_errors', text);
  assertEq(r.status, 'findings');
  assertEq(r.critical, 2);
  assertEq(r.minor, 1);
});

test('outcomeFor: syntaxcheck с ошибками - error, проверку не закрывает', async () => {
  const r = await outcomeFor('syntaxcheck', 'Синтаксическая ошибка: ожидается символ ;');
  assertEq(r.status, 'error');
});

test('outcomeFor: ask_1c_ai с замечанием - findings, без замечаний - pass', async () => {
  assertEq((await outcomeFor('ask_1c_ai', 'Замечание: missing cast')).status, 'findings');
  assertEq((await outcomeFor('ask_1c_ai', 'Замечаний нет. Код корректен.')).status, 'pass');
});

test('applied для validate_query (pass): событие с полями и хешами', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('validate-query-pass', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const events = await readEvents(ctx.top, 'test-session-1');
    assertEq(events.length, 1);
    const e = events[0];
    assertEq(e.type, 'applied');
    assertEq(e.check, 'validate_query@edt');
    assertEq(e.producer, 'hook');
    assertEq(e.toolUseId, 'toolu_fixture_validate_pass');
    assertEq(e.env, 'edt');
    assertEq(e.level, 'semantic');
    assertEq(e.outcome.status, 'pass');
    assert(typeof e.inputHash === 'string' && e.inputHash.length === 64, 'inputHash - sha256');
    assert(typeof e.responseHash === 'string' && e.responseHash.length === 64, 'responseHash - sha256');
    assert(typeof e.diffHash === 'string' && e.diffHash.length === 64, 'diffHash вычислен');
    assert(/^\d{4}-\d{2}-\d{2}T\d{6}-\d{3}-\d{6}-hook-[0-9a-f]{6}\.json$/.test(e._file),
      `имя файла по формату: ${e._file}`);
  } finally {
    await ctx.cleanup();
  }
});

test('applied для validate_query (findings): итог findings', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('validate-query-findings', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.check, 'validate_query@edt');
    assertEq(e.outcome.status, 'findings');
    assertEq(e.outcome.minor, 2);
  } finally {
    await ctx.cleanup();
  }
});

test('applied для code_review: две находки Critical по карточкам', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('code-review-findings', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.type, 'applied');
    assertEq(e.check, 'code_review@edt');
    assertEq(e.level, 'static');
    assertEq(e.outcome.status, 'findings');
    assertEq(e.outcome.critical, 2);
    assertEq(e.target, 'proj/src/CommonModules/Обмен/Module.bsl');
  } finally {
    await ctx.cleanup();
  }
});

test('applied для diagnostics с operation=get_project_errors', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('diagnostics-get-project-errors', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.check, 'get_project_errors@edt');
    assertEq(e.outcome.status, 'findings');
    assertEq(e.outcome.critical, 2);
    assertEq(e.outcome.minor, 1);
  } finally {
    await ctx.cleanup();
  }
});

test('Bash со скриптом набора и строкой EVIDENCE - applied по строке', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-evidence', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.type, 'applied');
    assertEq(e.check, 'bsl_validate@configurator');
    assertEq(e.detector, 'bsl_validate');
    assertEq(e.level, 'static');
    assertEq(e.outcome.status, 'findings');
    assertEq(e.outcome.major, 1, 'CLIENT-04 - Major');
    assertEq(e.inputHash, 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2');
  } finally {
    await ctx.cleanup();
  }
});

test('Bash со скриптом набора без строки EVIDENCE - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-no-evidence', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('Bash с echo-подделкой строки EVIDENCE без запуска скрипта - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-foreign-echo', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('Edit - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('edit-tool', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('PostToolUseFailure - событие failed с текстом ошибки', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('post-tool-use-failure', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.type, 'failed');
    assertEq(e.check, 'validate_query@edt');
    assertEq(e.error, 'MCP error -32000: Connection closed');
    assertEq(e.toolUseId, 'toolu_fixture_failure');
    assert(e.outcome === undefined, 'failed не несет итог');
  } finally {
    await ctx.cleanup();
  }
});

test('два одновременных писателя - два файла событий без потери', async () => {
  const ctx = await makeTmpRepo();
  try {
    const base = await loadFixture('validate-query-pass', { cwd: ctx.top, session_id: 'test-session-1' });
    const a = spawnHook('evidence-writer.mjs', { ...base, tool_use_id: 'toolu_parallel_a' });
    const b = spawnHook('evidence-writer.mjs', { ...base, tool_use_id: 'toolu_parallel_b' });
    const codes = await Promise.all([a, b].map((child) => new Promise((res) => {
      child.on('exit', (code) => res(code));
    })));
    assertEq(codes, [0, 0]);
    const events = await readEvents(ctx.top, 'test-session-1');
    assertEq(events.length, 2);
    const ids = events.map((e) => e.toolUseId).sort();
    assertEq(ids, ['toolu_parallel_a', 'toolu_parallel_b']);
    assert(events[0]._file !== events[1]._file, 'имена файлов различаются');
  } finally {
    await ctx.cleanup();
  }
});

test('недопустимый идентификатор сессии - код 0, событие не пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('validate-query-pass',
      { cwd: ctx.top, session_id: '../escape' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, 'внутренняя ошибка хука не блокирует');
    assert(r.stderr.includes('недопустимый идентификатор'), 'диагностика в stderr');
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('payload без session_id - код 0 без события', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('validate-query-pass', { cwd: ctx.top });
    delete payload.session_id;
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

await run();
