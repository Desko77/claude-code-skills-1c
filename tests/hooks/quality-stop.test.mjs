// Тесты hooks/quality-stop.mjs (гейт завершения хода): правки сессии считаются по
// каноническому множеству против базовой отметки (грязный до старта файл, staged,
// untracked, переименование, правка через запись файла), вердикт дает настоящий
// tools/evidence.py check --strict; события прогона тест пишет напрямую, как хук.

import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { git, HOOKS, makeTmpRepo, readEvents, runHook, runPythonSync, writeJournal,
  writeRepoFile } from './helpers.mjs';
import { computeChangeset } from '../../hooks/_changeset.mjs';
import { formatIso, nowIso, writeEvent } from '../../hooks/common/quality-events.mjs';
import { is1cFile } from '../../hooks/common/quality-gate.mjs';

const MODULE = 'Процедура Обмен()\nКонецПроцедуры\n';

// Репозиторий с одним коммитом .bsl: база для правок сессии.
async function repoWithModule() {
  const ctx = await makeTmpRepo();
  await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE);
  git(ctx.top, 'add', '-A');
  git(ctx.top, 'commit', '-q', '-m', 'module', '--no-gpg-sign', '--no-verify');
  return ctx;
}

async function startSession(top, session) {
  const r = runHook('quality-baseline.mjs', {
    hook_event_name: 'SessionStart', source: 'startup', session_id: session, cwd: top,
  });
  assertEq(r.status, 0, r.stderr);
}

function stop(top, session, extra = {}) {
  return runHook('quality-stop.mjs', {
    hook_event_name: 'Stop', session_id: session, cwd: top, stop_hook_active: false, ...extra,
  });
}

async function currentDiffHash(top) {
  return (await computeChangeset(top, 'HEAD')).diffHash;
}

// Записать прогон напрямую (как хук и профиль): scope с обязательными проверками,
// applied с итогом и probe доступности источника; diffHash - текущее множество.
async function writeRun(top, session, { required, applied, probe }) {
  const diffHash = await currentDiffHash(top);
  await writeEvent(top, session, {
    type: 'scope', at: nowIso(), session, producer: 'profile', diffHash, required,
    volume: { class: 'C1', bslLines: 10, bslFiles: 1 }, files: [], archetypes: [],
    env: 'edt', driver: 'agent', analyzerConfig: null, vendorCopy: null,
  });
  if (applied) {
    await writeEvent(top, session, {
      type: 'applied', at: nowIso(), session, producer: 'hook', diffHash,
      check: applied.check, detector: applied.check.split('@')[0], env: 'edt', level: 'semantic',
      target: 'proj/src/Module.bsl', toolUseId: 'toolu_stop_test_applied',
      inputHash: 'a'.repeat(64), responseHash: 'b'.repeat(64), outcome: applied.outcome,
    });
  }
  if (probe) {
    await writeEvent(top, session, {
      type: 'probe', at: nowIso(), session, producer: 'cli', diffHash,
      source: probe, status: 'ok', detail: 'тест',
    });
  }
}

// Событие armed как от quality-arm: файл - абсолютный путь, как его посылает Edit.
async function arm(top, session, rel) {
  await writeEvent(top, session, {
    type: 'armed', at: nowIso(), session, producer: 'hook',
    diffHash: await currentDiffHash(top), file: join(top, rel), tool: 'Edit', toolUseId: null,
  });
}

test('is1cFile: расширения 1С и XML выгрузки Конфигуратора', () => {
  for (const path of ['src/Module.bsl', 'src/Module.os', 'Catalog.mdo', 'Form.form',
    'Main.dcs', 'table.mxlx', 'CommandInterface.cmi', 'Admin.rights', 'Package.xdto',
    'Configuration.xml', 'Ext/CommandInterface.xml', 'src/Ext/Sub/Role.xml']) {
    assert(is1cFile(path), `файл 1С не распознан: ${path}`);
  }
  for (const path of ['README.md', 'notes.txt', 'src/Module.bsl.bak', 'plain.xml',
    'sub/Configuration.xml', 'Ext/source.bsl.txt']) {
    assert(!is1cFile(path), `файл ошибочно распознан как 1С: ${path}`);
  }
});

test('Stop без правок: код 0, молча', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0);
    assertEq(r.stdout.trim(), '');
    assertEq(r.stderr.trim(), '', 'без правок гейт молчит');
  } finally {
    await ctx.cleanup();
  }
});

test('Stop без отметки сессии: код 0, гейт не применяется', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    const r = stop(ctx.top, 'stop-no-baseline');
    assertEq(r.status, 0);
    assert(r.stderr.includes('отметки сессии нет, гейт не применяется'),
      `строка в stderr: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('Stop с правкой .bsl без прогона: код 2, перечень правок и прямой путь', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, `stderr: ${r.stderr}`);
    assert(r.stderr.includes('правки сессии (файлы 1С), всего 1:'), 'перечень правок в stderr');
    assert(r.stderr.includes('modified proj/src/Module.bsl'), 'файл правки в перечне');
    assert(r.stderr.includes('нет scope с текущим diffHash'), 'причина из вывода валидатора');
    // Команды прямого пути - абсолютные пути инструментов и база diffHash = HEAD отметки.
    const head = git(ctx.top, 'rev-parse', 'HEAD').trim();
    assert(r.stderr.includes(`"${join(HOOKS, '..', 'tools', 'change_profile.py')}"`),
      'абсолютный путь change_profile.py');
    assert(r.stderr.includes(`"${join(HOOKS, '..', 'tools', 'evidence.py')}"`),
      'абсолютный путь evidence.py');
    assert(r.stderr.includes(`--session stop-session-1 --repo "${ctx.top}" --base ${head}`),
      'полная команда с --base от HEAD отметки');
    assert(r.stderr.includes('/quality release gate'), 'команда снятия в прямом пути');
    assert(!r.stderr.includes('повторная попытка завершения'), 'без строки повторной попытки');
  } finally {
    await ctx.cleanup();
  }
});

test('перечень правок ограничен 20 путями, остальные - числом', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    // Имена с ведущими нулями: порядок множества лексикографический, без нулей он
    // не совпадает с числовым и границы перечня зависят от сортировки.
    for (let i = 1; i <= 25; i++) {
      const name = `Gen${String(i).padStart(2, '0')}.bsl`;
      await writeRepoFile(ctx.top, `proj/src/${name}`, `Процедура М${i}()\nКонецПроцедуры\n`);
      await arm(ctx.top, 'stop-session-1', `proj/src/${name}`);
    }
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, `stderr: ${r.stderr}`);
    assert(r.stderr.includes('всего 25:'), 'общее число правок');
    assert(r.stderr.includes('added proj/src/Gen20.bsl'), 'двадцатый путь в перечне');
    assert(!r.stderr.includes('Gen21.bsl'), 'двадцать первый путь не перечисляется');
    assert(r.stderr.includes('... еще 5 файлов не перечислены'), 'число неперечисленных');
  } finally {
    await ctx.cleanup();
  }
});

test('после 2 блоков подряд без новых событий - выход 0 и systemMessage', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    // Прогон и заявка на пропуск до первого блока: в сводке пользователю заявка идет
    // с командой подтверждения (заявка вне прогона к обязательным проверкам не относится).
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'skipped', at: nowIso(), session: 'stop-session-1', producer: 'cli',
      diffHash: await currentDiffHash(ctx.top), check: 'code_review@edt',
      class: 'not_applicable', reason: 'правка только документации',
    });
    assertEq(stop(ctx.top, 'stop-session-1').status, 2, 'первый блок');
    assertEq(stop(ctx.top, 'stop-session-1').status, 2, 'второй блок');
    const third = stop(ctx.top, 'stop-session-1');
    assertEq(third.status, 0, `третья попытка без событий прогона завершает ход: ${third.stderr}`);
    const message = JSON.parse(third.stdout.trim());
    assert(message.systemMessage && message.systemMessage.includes('гейт не снят, проверки не выполнены'),
      `systemMessage пользователю: ${third.stdout}`);
    assert(message.systemMessage.includes('code_review@edt [not_applicable] '
      + 'правка только документации, подтвердить: /quality release check code_review@edt '
      + 'правка только документации'), `заявка с командой в сводке: ${third.stdout}`);
    // Новое событие следа сбрасывает серию: следующий ход снова блокируется.
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'probe', at: nowIso(), session: 'stop-session-1', producer: 'cli',
      diffHash: await currentDiffHash(ctx.top), source: 'ai-edt', status: 'ok', detail: 'тест',
    });
    assertEq(stop(ctx.top, 'stop-session-1').status, 2, 'после события прогона серия начинается заново');
  } finally {
    await ctx.cleanup();
  }
});

test('scope и заявка на пропуск между блоками серию не прерывают', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    assertEq(stop(ctx.top, 'stop-session-1').status, 2, 'первый блок');
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'skipped', at: nowIso(), session: 'stop-session-1', producer: 'cli',
      diffHash: await currentDiffHash(ctx.top), check: 'code_review@edt',
      class: 'not_applicable', reason: 'правка только документации',
    });
    assertEq(stop(ctx.top, 'stop-session-1').status, 2, 'второй блок');
    const third = stop(ctx.top, 'stop-session-1');
    assertEq(third.status, 0, `третья попытка завершает ход: ${third.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('QUALITY_STOP_OFF отключает гейт', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const r = runHook('quality-stop.mjs', {
      hook_event_name: 'Stop', session_id: 'stop-session-1', cwd: ctx.top, stop_hook_active: false,
    }, { env: { QUALITY_STOP_OFF: '1' } });
    assertEq(r.status, 0, `гейт отключен переменной: ${r.stderr}`);
    assert(r.stderr.includes('QUALITY_STOP_OFF'), 'причина отключения в stderr');
  } finally {
    await ctx.cleanup();
  }
});

test('грязный до старта файл без изменений после отметки - не правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Грязная()\nКонецПроцедуры\n');
    await startSession(ctx.top, 'stop-session-1');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, `грязный до старта файл не блокирует: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('правка файла без событий сессии (человек в EDT) ход не блокирует', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    // Правка без инструмента записи и без событий сессии: как правка человека
    // в EDT или постороннего процесса.
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Чужая()\nКонецПроцедуры\n');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, `правка без событий сессии - не правка сессии: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('грязный до старта файл, измененный после отметки с armed - правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Грязная()\nКонецПроцедуры\n');
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Грязрая2()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'изменение грязного файла после отметки блокирует');
  } finally {
    await ctx.cleanup();
  }
});

test('staged-правка .bsl - правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    git(ctx.top, 'add', 'proj/src/Module.bsl');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'staged-файл входит в каноническое множество');
  } finally {
    await ctx.cleanup();
  }
});

test('untracked-файл .bsl - правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/New.bsl', MODULE);
    await arm(ctx.top, 'stop-session-1', 'proj/src/New.bsl');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'untracked-файл входит в каноническое множество');
    assert(r.stderr.includes('added proj/src/New.bsl'), 'статус added в перечне');
  } finally {
    await ctx.cleanup();
  }
});

test('переименование .mdo - правка сессии по новому пути', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'Catalogs/Контрагенты.mdo', '<mdo/>\n');
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'mdo', '--no-gpg-sign', '--no-verify');
    await startSession(ctx.top, 'stop-session-1');
    git(ctx.top, 'mv', 'Catalogs/Контрагенты.mdo', 'Catalogs/Партнеры.mdo');
    await arm(ctx.top, 'stop-session-1', 'Catalogs/Партнеры.mdo');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'переименованный файл - правка сессии');
    assert(r.stderr.includes('Catalogs/Партнеры.mdo'), 'новый путь в перечне');
  } finally {
    await ctx.cleanup();
  }
});

test('правка не-1С файла: гейт не применяется, код 0 молча', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'docs/readme.md', 'текст\n');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0);
    assertEq(r.stderr.trim(), '');
  } finally {
    await ctx.cleanup();
  }
});

test('правка XML выгрузки Конфигуратора под Ext/ - правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'Ext/CommandInterface.xml', '<ci/>\n');
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'ext', '--no-gpg-sign', '--no-verify');
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'Ext/CommandInterface.xml', '<ci><commands/></ci>\n');
    await arm(ctx.top, 'stop-session-1', 'Ext/CommandInterface.xml');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'XML выгрузки Конфигуратора учитывается гейтом');
  } finally {
    await ctx.cleanup();
  }
});

test('Stop после scope, applied и probe: код 0', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    await writeRun(ctx.top, 'stop-session-1', {
      required: ['code_review@edt'],
      applied: { check: 'code_review@edt', outcome: { status: 'pass', critical: 0, major: 0, minor: 0 } },
      probe: 'ai-edt',
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, `stderr: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('Stop после scope и applied с findings без critical: код 0', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    await writeRun(ctx.top, 'stop-session-1', {
      required: ['code_review@edt'],
      applied: { check: 'code_review@edt', outcome: { status: 'findings', critical: 0, major: 2, minor: 1 } },
      probe: 'ai-edt',
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, 'findings без critical дают чистый вердикт');
  } finally {
    await ctx.cleanup();
  }
});

test('applied с critical без снятия: код 2, причина в тексте блока', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    await writeRun(ctx.top, 'stop-session-1', {
      required: ['code_review@edt'],
      applied: { check: 'code_review@edt', outcome: { status: 'findings', critical: 2, major: 0, minor: 0 } },
      probe: 'ai-edt',
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'неснятый critical блокирует ход');
    assert(r.stderr.includes('applied с critical без снятия'), 'причина блока в stderr');
    assert(r.stderr.includes('code_review@edt'), 'проверка названа');
  } finally {
    await ctx.cleanup();
  }
});

test('снятие gate с командой в журнале сессии: код 0', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const diffHash = await currentDiffHash(ctx.top);
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'release', at: nowIso(), session: 'stop-session-1', producer: 'hook', diffHash,
      scope: 'gate', reason: 'проверки прогонят после мержа', source: 'user_prompt',
      expiresAt: formatIso(new Date(Date.now() + 60 * 60 * 1000)),
    });
    const journal = await writeJournal(join(ctx.top, '..', 'journal.jsonl'),
      ['/quality release gate проверки прогонят после мержа']);
    const r = stop(ctx.top, 'stop-session-1', { transcript_path: journal });
    assertEq(r.status, 0, `подтвержденное снятие гейта снимает блок: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('снятие gate без записи о нем в журнале сессии: код 2, причина в тексте блока', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const diffHash = await currentDiffHash(ctx.top);
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'release', at: nowIso(), session: 'stop-session-1', producer: 'hook', diffHash,
      scope: 'gate', reason: 'проверки прогонят после мержа', source: 'user_prompt',
      expiresAt: formatIso(new Date(Date.now() + 60 * 60 * 1000)),
    });
    // Журнал есть, но команды снятия в нем нет: запись release без подтверждения не снятие.
    const journal = await writeJournal(join(ctx.top, '..', 'journal.jsonl'),
      ['прогони проверки еще раз']);
    const r = stop(ctx.top, 'stop-session-1', { transcript_path: journal });
    assertEq(r.status, 2, 'неподтвержденная запись release ход не завершает');
    assert(r.stderr.includes('снятие gate: не найдено подтверждение пользователя'),
      `причина в тексте блока: ${r.stderr}`);
    // Журнал недоступен: подтверждения нет тоже.
    const missing = stop(ctx.top, 'stop-session-1', {
      transcript_path: join(ctx.top, '..', 'no-such-journal.jsonl'),
    });
    assertEq(missing.status, 2, 'недоступный журнал не дает подтверждения');
    assert(missing.stderr.includes('не найдено подтверждение пользователя'),
      `причина при недоступном журнале: ${missing.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('заявка на пропуск: код 2, текст блока с командой подтверждения', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const diffHash = await currentDiffHash(ctx.top);
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'skipped', at: nowIso(), session: 'stop-session-1', producer: 'cli', diffHash,
      check: 'code_review@edt', class: 'not_applicable', reason: 'правка только документации',
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, `пропуск от модели ход не завершает: ${r.stderr}`);
    assert(r.stderr.includes('проверка не закрыта, есть только заявка на пропуск '
      + '(not_applicable): code_review@edt'), 'причина называет заявку');
    assert(r.stderr.includes('заявки на пропуск (проверку не закрывают; подтвердить может '
      + 'только пользователь):'), 'раздел заявок в тексте блока');
    assert(r.stderr.includes('  code_review@edt [not_applicable] правка только документации'),
      'заявка с проверкой, видом и причиной');
    assert(r.stderr.includes('  команда подтверждения: /quality release check code_review@edt '
      + 'правка только документации'), 'готовая команда для человека');
    assert(r.stderr.includes('заявку на пропуск закрывает только пользователь'),
      'пояснение про роль человека в прямом пути');
  } finally {
    await ctx.cleanup();
  }
});

test('коммит посреди сессии: прогон от базы отметки закрывает гейт', async () => {
  const EDT_PROJECT = '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<projectDescription><name>proj</name><natures>'
    + '<nature>com._1c.g5.v8.dt.core.v8.nature</nature>'
    + '</natures></projectDescription>\n';
  const ctx = await makeTmpRepo();
  try {
    await writeRepoFile(ctx.top, 'proj/.project', EDT_PROJECT);
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE);
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'base', '--no-gpg-sign', '--no-verify');
    await startSession(ctx.top, 'stop-commit-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-commit-1', 'proj/src/Module.bsl');
    git(ctx.top, 'add', '-A');
    git(ctx.top, 'commit', '-q', '-m', 'правка', '--no-gpg-sign', '--no-verify');

    // Профиль без явного --base (как в подсказке блока): база - HEAD отметки.
    const profile = runPythonSync(
      ['tools/change_profile.py', '--repo', ctx.top, '--session', 'stop-commit-1']);
    assertEq(profile.status, 0, profile.stderr);

    // applied от хука после коммита: diffHash тоже от базы отметки.
    for (const [tool, check, response] of [
      ['mcp__1c-edt__code_review', 'code_review@edt', 'Ошибок нет'],
      ['mcp__naparnik__ask_1c_ai', 'ask_1c_ai@edt', 'Замечаний нет. Код корректен.'],
    ]) {
      const r = runHook('evidence-writer.mjs', {
        hook_event_name: 'PostToolUse', tool_name: tool,
        tool_input: { modulePath: 'proj/src/Module.bsl' },
        tool_response: response, tool_use_id: `toolu_commit_${check}`,
        cwd: ctx.top, session_id: 'stop-commit-1',
      });
      assertEq(r.status, 0, r.stderr);
    }
    for (const source of ['ai-edt', 'naparnik']) {
      const probe = runPythonSync(
        ['tools/evidence.py', 'add', '--repo', ctx.top, '--session', 'stop-commit-1',
          '--type', 'probe', '--source', source, '--status', 'ok']);
      assertEq(probe.status, 0, probe.stderr);
    }
    const r = stop(ctx.top, 'stop-commit-1');
    assertEq(r.status, 0, `коммит в сессии не блокирует навсегда: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('stop_hook_active: блок сохраняется, текст дополняется', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const r = stop(ctx.top, 'stop-session-1', { stop_hook_active: true });
    assertEq(r.status, 2, 'повторная попытка не снимает блок');
    assert(r.stderr.includes('повторная попытка завершения; блок снимает только прогон проверок или команда снятия'),
      'строка повторной попытки в stderr');
  } finally {
    await ctx.cleanup();
  }
});

test('вне git-репозитория: код 0 молча', async () => {
  const base = await mkdtemp(join(tmpdir(), 'quality-stop-nogit-'));
  try {
    const r = runHook('quality-stop.mjs', {
      hook_event_name: 'Stop', session_id: 'stop-nogit', cwd: base, stop_hook_active: false,
    });
    assertEq(r.status, 0);
    assertEq(r.stderr.trim(), '');
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test('валидатор недоступен (несуществующий PYTHON): код 0 с диагностикой', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-session-1', 'proj/src/Module.bsl');
    const r = runHook('quality-stop.mjs', {
      hook_event_name: 'Stop', session_id: 'stop-session-1', cwd: ctx.top, stop_hook_active: false,
    }, { env: { PYTHON: 'python-no-such-binary-xyz' } });
    assertEq(r.status, 0, 'недоступный валидатор не блокирует работу (fail-open)');
    assert(r.stderr.includes('валидатор следа не запущен'), `диагностика в stderr: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('applied с целью-файлом: файл считается правкой сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    // Правки инструментом записи не было, но проверка с целью-файлом уже бежала:
    // событие applied метит файл как затронутый сессией.
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'applied', at: nowIso(), session: 'stop-session-1', producer: 'hook',
      diffHash: await currentDiffHash(ctx.top), check: 'code_review@edt',
      detector: 'code_review', env: 'edt', level: 'static',
      target: join(ctx.top, 'proj/src/Module.bsl'), toolUseId: 'toolu_stop_target',
      inputHash: 'a'.repeat(64), responseHash: 'b'.repeat(64),
      outcome: { status: 'pass', critical: 0, major: 0, minor: 0 },
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, 'файл с событием applied входит в правки сессии');
    assert(r.stderr.includes('нет scope с текущим diffHash'), 'без прогона - блок');
  } finally {
    await ctx.cleanup();
  }
});

test('параллельная сессия с правками в другом репозитории не блокирует эту', async () => {
  const ctx = await repoWithModule();
  const other = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    // Параллельная сессия в другом воркспейсе: своя отметка и непроверенная правка.
    await startSession(other.top, 'stop-parallel');
    await writeRepoFile(other.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Чужая()\nКонецПроцедуры\n');
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, `чужой воркспейс не затронут: ${r.stderr}`);
    assertEq((await readEvents(ctx.top, 'stop-session-1')).length, 1,
      'гейт не писал событий в свою сессию');
  } finally {
    await ctx.cleanup();
    await other.cleanup();
  }
});

test('параллельная сессия в том же репозитории: ее armed не блокируют эту сессию', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-main');
    await startSession(ctx.top, 'stop-neighbor');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Чужая()\nКонецПроцедуры\n');
    await arm(ctx.top, 'stop-neighbor', 'proj/src/Module.bsl');
    const mine = stop(ctx.top, 'stop-main');
    assertEq(mine.status, 0, `правка соседней сессии не блокирует ход этой: ${mine.stderr}`);
    const neighbor = stop(ctx.top, 'stop-neighbor');
    assertEq(neighbor.status, 2, 'своя непроверенная правка блокирует свою сессию');
  } finally {
    await ctx.cleanup();
  }
});

await run();
