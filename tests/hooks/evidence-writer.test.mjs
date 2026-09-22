// Тесты hooks/evidence-writer.mjs: матчер, определение проверки, разбор итогов и запись
// событий applied/failed по payload-фикстурам. Чтение событий - прямым разбором каталога
// следа; сквозная совместимость с tools/evidence.py - в end-to-end.test.mjs.

import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { loadFixture, makeTmpRepo, readEvents, runHook, spawnHook } from './helpers.mjs';
import { MATCHER, crossReviewOutcome, outcomeFor, resolveCheck, responseToText }
  from '../../hooks/evidence-writer.mjs';

const RE = new RegExp(MATCHER);

test('матчер покрывает инструменты проверки двух ключей сервера и Bash/PowerShell', () => {
  for (const name of ['mcp__1c-edt__validate_query', 'mcp__ai-edt-3_1_38_92__validate_query',
    'mcp__ai-edt__code_review', 'mcp__1c-edt__diagnostics', 'mcp__1c-edt__validate_for_export',
    'mcp__1c-edt__get_project_errors', 'mcp__1c-edt__detect_query_anti_patterns',
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

test('resolveCheck: standalone get_project_errors закрывает ту же проверку, что фасад', () => {
  const standalone = resolveCheck('mcp__1c-edt__get_project_errors', {}, '');
  assertEq(standalone.check, 'get_project_errors@edt');
  assertEq(standalone.detector, 'get_project_errors');
  assertEq(standalone.check,
    resolveCheck('mcp__1c-edt__diagnostics', { operation: 'get_project_errors' }, '').check,
    'standalone и фасад дают один идентификатор');
});

test('resolveCheck: standalone detect_query_anti_patterns закрывает ту же проверку, что фасад', () => {
  const standalone = resolveCheck('mcp__1c-edt__detect_query_anti_patterns', {}, '');
  assertEq(standalone.check, 'detect_query_anti_patterns@edt');
  assertEq(standalone.level, 'static');
  assertEq(standalone.check,
    resolveCheck('mcp__1c-edt__insights', { operation: 'detect_query_anti_patterns' }, '').check,
    'standalone и фасад дают один идентификатор');
});

test('applied для standalone validate_for_export: то же событие, что у операции фасада', async () => {
  const ctx = await makeTmpRepo();
  try {
    const mk = (toolName, toolInput, id) => ({
      hook_event_name: 'PostToolUse',
      tool_name: toolName,
      tool_input: toolInput,
      tool_response: 'Ошибок нет',
      tool_use_id: id,
      cwd: ctx.top,
      session_id: 'test-session-1',
    });
    const a = runHook('evidence-writer.mjs',
      mk('mcp__1c-edt__validate_for_export', {}, 'toolu_vfe_standalone'));
    const b = runHook('evidence-writer.mjs',
      mk('mcp__1c-edt__diagnostics', { operation: 'validate_for_export' }, 'toolu_vfe_facade'));
    assert(a.status === 0 && b.status === 0, `${a.stderr}${b.stderr}`);
    const events = await readEvents(ctx.top, 'test-session-1');
    assertEq(events.length, 2);
    assertEq(events[0].check, 'validate_for_export@edt');
    assertEq(events[0].detector, events[1].detector);
    assertEq(events[0].env, events[1].env);
    assertEq(events[0].level, events[1].level);
  } finally {
    await ctx.cleanup();
  }
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
  assertEq(r.critical, 1, 'сводка "Ошибок: 2" не считается отдельной ошибкой');
  assertEq(r.minor, 1);
});

test('outcomeFor: строка-сводка без реальных ошибок - unknown', async () => {
  const r = await outcomeFor('get_project_errors', 'Ошибок: 2');
  assertEq(r.status, 'unknown');
});

test('outcomeFor: фраза "не найдено" внутри текста ответа - не pass', async () => {
  const r = await outcomeFor('get_project_errors', 'Поле Родитель не найдено в таблице');
  assertEq(r.status, 'unknown', 'голое отрицание без подлежащего не сводка чистоты');
  const en = await outcomeFor('validate_for_export', 'Field Parent not found in table');
  assertEq(en.status, 'unknown');
});

test('outcomeFor: явная сводка чистоты - pass', async () => {
  assertEq((await outcomeFor('validate_query', 'Ошибок нет')).status, 'pass');
  assertEq((await outcomeFor('validate_query', 'Нарушений не обнаружено')).status, 'pass');
  assertEq((await outcomeFor('validate_query', 'No findings')).status, 'pass');
  assertEq((await outcomeFor('validate_query', 'Запрос корректен')).status, 'pass');
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

test('законные формы запуска скрипта набора - проверка распознается', () => {
  const evidence = 'EVIDENCE {"check":"bsl_validate@configurator","ids":[],"inputHash":"x","status":"pass"}';
  const forms = [
    'python skills/1c-bsl-validate/scripts/bsl-validate.py --path x',
    'python3 -X utf8 scripts/query-validate.py',
    'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/role-validate.ps1',
    'pwsh -File skills\\1c-form-validate\\scripts\\form-validate.ps1',
    '& "scripts/meta-validate.py"',
    "cd skills/1c-meta-validate && python scripts/meta-validate.py",
    'scripts/form-validate.ps1 -Check all',
  ];
  for (const command of forms) {
    const r = resolveCheck('Bash', { command }, evidence);
    assert(r !== null, `форма запуска не распознана: ${command}`);
    assertEq(r.check, 'bsl_validate@configurator');
  }
});

test('путь скрипта в комментарии, литерале или аргументе echo - запуском не считается', () => {
  const evidence = 'EVIDENCE {"check":"bsl_validate@configurator","ids":[],"inputHash":"x","status":"pass"}';
  const fake = [
    'echo done # python scripts/bsl-validate.py --path x',
    "echo 'python scripts/bsl-validate.py --path x'",
    'echo scripts/bsl-validate.py',
    'python -c "print(1)"',
    'cat scripts/bsl-validate.py',
    'python proj/scripts/foreign.py',
  ];
  for (const command of fake) {
    assertEq(resolveCheck('Bash', { command }, evidence), null,
      `подделка распознана как запуск: ${command}`);
  }
});

test('Bash с путем скрипта в комментарии - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-comment-path', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('Bash с путем скрипта в строковом литерале - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-literal-path', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('Bash с путем скрипта аргументом echo - события нет', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = await loadFixture('bash-echo-path-arg', { cwd: ctx.top, session_id: 'test-session-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}`);
    assertEq((await readEvents(ctx.top, 'test-session-1')).length, 0);
  } finally {
    await ctx.cleanup();
  }
});

test('PowerShell с законной формой -File: applied пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = {
      hook_event_name: 'PostToolUse',
      tool_name: 'PowerShell',
      tool_input: { command: 'pwsh -NoProfile -File skills\\1c-role-validate\\scripts\\role-validate.ps1 --path roles/Admin.rights' },
      tool_response: 'EVIDENCE {"check":"role_validate@configurator","ids":["SEC-02"],"inputHash":"y","status":"findings"}',
      tool_use_id: 'toolu_pwsh_file',
      cwd: ctx.top,
      session_id: 'test-session-1',
    };
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.type, 'applied');
    assertEq(e.check, 'role_validate@configurator');
    assertEq(e.outcome.status, 'findings');
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

test('responseToText: массив элементов content верхнего уровня', () => {
  const resp = [
    { type: 'text', text: 'Проверка CLIENT-04: найдено' },
    { type: 'text', text: 'EVIDENCE {"check":"bsl_validate@configurator","ids":[],"inputHash":"x","status":"pass"}' },
    'итоговая строка',
  ];
  const text = responseToText(resp);
  assert(text.includes('EVIDENCE'), 'строка EVIDENCE извлечена из массива');
  assert(text.includes('итоговая строка'), 'строковый элемент массива извлечен');
});

test('Bash с ответом-массивом content и строкой EVIDENCE внутри text - applied пишется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const payload = {
      hook_event_name: 'PostToolUse',
      tool_name: 'Bash',
      tool_input: { command: 'python skills/1c-bsl-validate/scripts/bsl-validate.py --path x' },
      tool_response: [
        { type: 'text', text: 'Проверено строк: 42' },
        { type: 'text', text: 'EVIDENCE {"check":"bsl_validate@configurator","ids":[],"inputHash":"x","status":"pass"}' },
      ],
      tool_use_id: 'toolu_array_content',
      cwd: ctx.top,
      session_id: 'test-session-1',
    };
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0, `код выхода ${r.status}: ${r.stderr}`);
    const [e] = await readEvents(ctx.top, 'test-session-1');
    assertEq(e.type, 'applied');
    assertEq(e.check, 'bsl_validate@configurator');
    assertEq(e.outcome.status, 'pass');
  } finally {
    await ctx.cleanup();
  }
});

test('cwd вне git-репозитория: диагностика в stderr ровно один раз', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-dup-'));
  try {
    const payload = await loadFixture('validate-query-pass', { cwd: base, session_id: 'dup-1' });
    const r = runHook('evidence-writer.mjs', payload);
    assert(r.status === 0);
    assert(r.stderr.includes('не является git-репозиторием'), `причина в stderr: ${r.stderr}`);
    assertEq(r.stderr.split('\n').filter((l) => l.includes('[evidence-writer]')).length, 1,
      'диагностика напечатана один раз без дубля');
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test('crossReviewOutcome: находка P0 считается Critical', () => {
  const p0 = crossReviewOutcome('Full review comments:\n\n- [P0] Утечка ключа - file.mjs:10\n');
  assertEq(p0.status, 'findings');
  assertEq(p0.critical, 1, 'P0 - Critical, иначе гейт пропустит блокирующую находку');
  const p1 = crossReviewOutcome('- [P1] Ошибка - file.mjs:20\n');
  assertEq(p1.critical, 1, 'P1 остается Critical');
  const p3 = crossReviewOutcome('- [P3] Стиль - file.mjs:30\n');
  assertEq(p3.minor, 1, 'P3 - Minor');
});

await run();
