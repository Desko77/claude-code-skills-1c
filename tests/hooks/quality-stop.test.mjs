// Тесты hooks/quality-stop.mjs (гейт завершения хода): правки сессии считаются по
// каноническому множеству против базовой отметки (грязный до старта файл, staged,
// untracked, переименование, правка через запись файла), вердикт дает настоящий
// tools/evidence.py check --strict; события прогона тест пишет напрямую, как хук.

import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { git, makeTmpRepo, readEvents, runHook, writeRepoFile } from './helpers.mjs';
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
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 2, `stderr: ${r.stderr}`);
    assert(r.stderr.includes('правки сессии (файлы 1С):'), 'перечень правок в stderr');
    assert(r.stderr.includes('modified proj/src/Module.bsl'), 'файл правки в перечне');
    assert(r.stderr.includes('нет scope с текущим diffHash'), 'причина из вывода валидатора');
    assert(r.stderr.includes(`python tools/change_profile.py --session stop-session-1 --repo ${ctx.top}`),
      'прямой путь с командой профиля');
    assert(r.stderr.includes('/quality release gate'), 'команда снятия в прямом пути');
    assert(!r.stderr.includes('повторная попытка завершения'), 'без строки повторной попытки');
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

test('грязный до старта файл, измененный после отметки, - правка сессии', async () => {
  const ctx = await repoWithModule();
  try {
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Грязная()\nКонецПроцедуры\n');
    await startSession(ctx.top, 'stop-session-1');
    // Правка без инструмента записи (как через Bash): armed-события нет, множество видит.
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Грязрая2()\nКонецПроцедуры\n');
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

test('действующее снятие gate: код 0', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
    const diffHash = await currentDiffHash(ctx.top);
    await writeRun(ctx.top, 'stop-session-1', { required: ['code_review@edt'] });
    await writeEvent(ctx.top, 'stop-session-1', {
      type: 'release', at: nowIso(), session: 'stop-session-1', producer: 'hook', diffHash,
      scope: 'gate', reason: 'проверки прогонят после мержа', source: 'user_prompt',
      expiresAt: formatIso(new Date(Date.now() + 60 * 60 * 1000)),
    });
    const r = stop(ctx.top, 'stop-session-1');
    assertEq(r.status, 0, `снятие гейта снимает блок: ${r.stderr}`);
  } finally {
    await ctx.cleanup();
  }
});

test('stop_hook_active: блок сохраняется, текст дополняется', async () => {
  const ctx = await repoWithModule();
  try {
    await startSession(ctx.top, 'stop-session-1');
    await writeRepoFile(ctx.top, 'proj/src/Module.bsl', MODULE + '\nПроцедура Новая()\nКонецПроцедуры\n');
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
    const r = runHook('quality-stop.mjs', {
      hook_event_name: 'Stop', session_id: 'stop-session-1', cwd: ctx.top, stop_hook_active: false,
    }, { env: { PYTHON: 'python-no-such-binary-xyz' } });
    assertEq(r.status, 0, 'недоступный валидатор не блокирует работу (fail-open)');
    assert(r.stderr.includes('валидатор следа не запущен'), `диагностика в stderr: ${r.stderr}`);
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

await run();
