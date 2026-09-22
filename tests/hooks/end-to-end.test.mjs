// Сквозной тест писателя следа: событие scope от tools/change_profile.py, applied от
// hooks/evidence-writer.mjs, probe от tools/evidence.py add и строгий вердикт
// tools/evidence.py check --strict. События, записанные хуком, обязаны читаться
// Python-валидатором и закрывать обязательные проверки из scope.

import { assert, assertEq, run, test } from './harness.mjs';
import {
  git, loadFixture, makeTmpRepo, readEvents, runHook, runPythonSync, writeRepoFile,
} from './helpers.mjs';

const MODULE = 'Процедура ПроверитьОбмен()\n\tНайденныеСтроки = СтроковоеПредставление(Обмен.Код);\nКонецПроцедуры\n';

const EDT_PROJECT = '<?xml version="1.0" encoding="UTF-8"?>\n'
  + '<projectDescription><name>proj</name><natures>'
  + '<nature>com._1c.g5.v8.dt.core.v8.nature</nature>'
  + '</natures></projectDescription>\n';

test('события хука читаются evidence.py check --strict и закрывают прогон', async () => {
  const ctx = await makeTmpRepo();
  try {
    await writeRepoFile(ctx.top, 'proj/.project', EDT_PROJECT);
    await writeRepoFile(ctx.top, 'proj/src/CommonModules/Обмен/Module.bsl', MODULE);
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'base', '--no-gpg-sign', '--no-verify');
    // Правка кода в среде EDT: обязательны code_review@edt и ask_1c_ai@edt.
    await writeRepoFile(ctx.top, 'proj/src/CommonModules/Обмен/Module.bsl', MODULE + '\nПроцедура Дополнить()\nКонецПроцедуры\n');

    const profile = runPythonSync(
      [ 'tools/change_profile.py', '--repo', ctx.top, '--session', 'e2e-1' ]);
    assertEq(profile.status, 0, `профиль: ${profile.stderr}`);
    const scopeEvents = await readEvents(ctx.top, 'e2e-1');
    assertEq(scopeEvents.filter((e) => e.type === 'scope').length, 1, 'событие scope записано');
    const required = scopeEvents.find((e) => e.type === 'scope').required;
    assert(required.includes('code_review@edt'), `code_review@edt в required: ${required.join(', ')}`);
    assert(required.includes('ask_1c_ai@edt'), `ask_1c_ai@edt в required: ${required.join(', ')}`);

    // applied от хука: code_review с двумя Major-находками (проверку закрывает,
    // critical нет) и ask_1c_ai без замечаний.
    const review = runHook('evidence-writer.mjs', {
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__1c-edt__code_review',
      tool_input: { modulePath: 'proj/src/CommonModules/Обмен/Module.bsl' },
      tool_response: 'Находки:\nCLIENT-04 DeprecatedMessage: строка 3\n'
        + 'MODEL-14 IfElseIfEndsWithElse: строка 7',
      tool_use_id: 'toolu_e2e_review',
      cwd: ctx.top,
      session_id: 'e2e-1',
    });
    assertEq(review.status, 0, review.stderr);
    const llm = runHook('evidence-writer.mjs', {
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__naparnik__ask_1c_ai',
      tool_input: { prompt: 'проверь фрагмент' },
      tool_response: 'Замечаний нет. Код корректен.',
      tool_use_id: 'toolu_e2e_llm',
      cwd: ctx.top,
      session_id: 'e2e-1',
    });
    assertEq(llm.status, 0, llm.stderr);
    const applied = (await readEvents(ctx.top, 'e2e-1')).filter((e) => e.type === 'applied');
    assertEq(applied.length, 2, 'два applied-события');
    assertEq(applied.find((e) => e.check === 'code_review@edt').diffHash,
      scopeEvents.find((e) => e.type === 'scope').diffHash,
      'diffHash applied совпадает со scope');

    for (const source of ['ai-edt', 'naparnik']) {
      const probe = runPythonSync(
        [ 'tools/evidence.py', 'add', '--repo', ctx.top, '--session', 'e2e-1',
          '--type', 'probe', '--source', source, '--status', 'ok' ]);
      assertEq(probe.status, 0, `probe ${source}: ${probe.stderr}`);
    }

    const check = runPythonSync(
      [ 'tools/evidence.py', 'check', '--strict', '--repo', ctx.top, '--session', 'e2e-1' ]);
    assertEq(check.status, 0, `вердикт: ${check.stdout}${check.stderr}`);
    assert(check.stdout.includes('чисто'), `строгий вердикт clean: ${check.stdout}`);
  } finally {
    await ctx.cleanup();
  }
});

await run();
