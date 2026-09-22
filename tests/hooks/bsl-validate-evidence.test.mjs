// Интеграционный тест строки EVIDENCE скрипта набора: реальный вывод bsl-validate.py
// (режим -Catalog) подается хуку evidence-writer.mjs как ответ Bash с командой запуска
// скрипта; событие applied закрывает проверку bsl_validate@configurator в прогоне
// tools/evidence.py check --strict. Сквозная связка скрипт -> хук -> валидатор.

import { assert, assertEq, run, test } from './harness.mjs';
import {
  REPO_ROOT, git, makeTmpRepo, readEvents, runHook, runPythonSync, writeRepoFile,
} from './helpers.mjs';

const SCRIPT_REL = 'skills/1c-bsl-validate/scripts/bsl-validate.py';
const FIXTURE = 'tests/catalog/TXN-01/defect.bsl';

test('EVIDENCE реального запуска bsl-validate: applied у хука, проверка закрыта в evidence.py', async () => {
  // Реальный запуск: вывод несет находку TXN-01 и строку EVIDENCE по контракту следа.
  const res = runPythonSync(
    [SCRIPT_REL, '-ModulePath', FIXTURE, '-Catalog', '-RuleId', 'TXN-01']);
  assertEq(res.status, 1, 'скрипт с находками завершается кодом 1');
  const evLine = res.stdout.split(/\r?\n/).find((l) => l.startsWith('EVIDENCE '));
  assert(evLine, 'строка EVIDENCE в выводе скрипта');
  const evidence = JSON.parse(evLine.slice('EVIDENCE '.length));
  assertEq(evidence.check, 'bsl_validate@configurator');
  assertEq(evidence.status, 'findings');
  assertEq(evidence.ids, ['TXN-01']);
  assert(/^[0-9a-f]{64}$/.test(evidence.inputHash), 'inputHash - полный sha256 (64 hex)');

  // Среда Конфигуратора: правка .bsl вне EDT-проекта делает bsl_validate обязательной.
  const ctx = await makeTmpRepo();
  try {
    const before = 'Процедура ЗаполнитьПакетОбмена(Данные)\nКонецПроцедуры\n';
    const after = 'Процедура ЗаполнитьПакетОбмена(Данные)\n'
      + '\tДанные = ДополнитьРеквизитами(Данные);\nКонецПроцедуры\n';
    await writeRepoFile(ctx.top, 'src/Exchange/Module.bsl', before);
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'base', '--no-gpg-sign', '--no-verify');
    await writeRepoFile(ctx.top, 'src/Exchange/Module.bsl', after);

    const profile = runPythonSync(
      ['tools/change_profile.py', '--repo', ctx.top, '--session', 'bslval-1']);
    assertEq(profile.status, 0, `профиль: ${profile.stderr}`);
    const scope = (await readEvents(ctx.top, 'bslval-1')).find((e) => e.type === 'scope');
    assert(scope, 'событие scope записано');
    assert(scope.required.includes('bsl_validate@configurator'),
      `bsl_validate@configurator в required: ${scope.required.join(', ')}`);

    // Вывод реального запуска - как ответ Bash с командой запуска скрипта набора.
    const hook = runHook('evidence-writer.mjs', {
      hook_event_name: 'PostToolUse',
      tool_name: 'Bash',
      tool_input: {
        command: `python ${SCRIPT_REL} -ModulePath ${FIXTURE} -Catalog -RuleId TXN-01`,
      },
      tool_response: res.stdout,
      tool_use_id: 'toolu_bslval_integration',
      cwd: ctx.top,
      session_id: 'bslval-1',
    });
    assertEq(hook.status, 0, hook.stderr);
    const applied = (await readEvents(ctx.top, 'bslval-1')).find((e) => e.type === 'applied');
    assert(applied, 'событие applied записано');
    assertEq(applied.check, 'bsl_validate@configurator');
    assertEq(applied.detector, 'bsl_validate');
    assertEq(applied.env, 'configurator');
    assertEq(applied.outcome.status, 'findings');
    assertEq(applied.outcome.major, 1, 'TXN-01 - Major');
    assertEq(applied.outcome.critical, 0, 'critical нет - вердикт не блокируется');
    assertEq(applied.inputHash, evidence.inputHash, 'inputHash события - из строки EVIDENCE');

    const probe = runPythonSync(
      ['tools/evidence.py', 'add', '--repo', ctx.top, '--session', 'bslval-1',
        '--type', 'probe', '--source', 'script', '--status', 'ok']);
    assertEq(probe.status, 0, `probe script: ${probe.stderr}`);
    const skip = runPythonSync(
      ['tools/evidence.py', 'add', '--repo', ctx.top, '--session', 'bslval-1',
        '--type', 'skipped', '--check', 'syntaxcheck@configurator',
        '--class', 'not_applicable', '--reason', 'тест покрывает только bsl_validate']);
    assertEq(skip.status, 0, `skipped syntaxcheck: ${skip.stderr}`);

    const check = runPythonSync(
      ['tools/evidence.py', 'check', '--strict', '--repo', ctx.top, '--session', 'bslval-1']);
    assertEq(check.status, 1, `with_gaps (код 1): ${check.stdout}${check.stderr}`);
    assert(check.stdout.includes('с пробелами'), `вердикт with_gaps: ${check.stdout}`);
    const blockers = check.stdout.split(/\r?\n/).filter((l) => l.startsWith('блокирует:'));
    assertEq(blockers, [], 'блокирующих причин нет');
    const gaps = check.stdout.split(/\r?\n/).filter((l) => l.startsWith('пробел:'));
    assert(gaps.includes('пробел: syntaxcheck@configurator'),
      `пробел только по syntaxcheck: ${gaps.join(', ')}`);
  } finally {
    await ctx.cleanup();
  }
});

await run();
