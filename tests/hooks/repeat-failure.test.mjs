// Тесты hooks/repeat-failure.mjs: подпись падения, счет подряд идущих одинаковых падений,
// указание модели с третьего падения, изоляция сессий, BOM, Cursor, выключающая переменная,
// битый JSON, довод --only и очистка записей старше 7 дней. Состояние хука лежит в домашнем
// каталоге, поэтому каждый тест подменяет HOME и USERPROFILE временным каталогом.

import { spawnSync } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { HOOKS, REPO_ROOT } from './helpers.mjs';
import { failureSignature, THRESHOLD } from '../../hooks/repeat-failure.mjs';

const SESSION = 'repeat-session-1';
const OTHER_SESSION = 'repeat-session-2';
const ERROR_TEXT = 'Ошибка: не найден файл "proj/src/Module.bsl", строка 12';
const OTHER_ERROR = 'Ошибка: команда не найдена';

// Временный домашний каталог: { home, cleanup }.
async function makeHome() {
  const home = realpathSync.native(await mkdtemp(join(tmpdir(), 'repeat-failure-home-')));
  return { home, cleanup: () => rm(home, { recursive: true, force: true }) };
}

// Окружение хука с подмененным домом; extra дополняет и переопределяет переменные.
function homeEnv(home, extra = {}) {
  return { HOME: home, USERPROFILE: home, ...extra };
}

function statePath(home, session) {
  return join(home, '.claude', 'state', 'repeat-failure', `${session}.json`);
}

// Payload падения с ошибкой, отличной от прочих вызовов.
function failPayload(session, extra = {}) {
  return {
    hook_event_name: 'PostToolUseFailure',
    tool_name: 'Bash',
    tool_input: { command: 'python skills/bsl-validate/scripts/bsl-validate.py' },
    error: ERROR_TEXT,
    tool_use_id: 'toolu_repeat',
    cwd: REPO_ROOT,
    session_id: session,
    ...extra,
  };
}

// Прогон хука сырым входом: нужно для BOM и битого JSON, где JSON.stringify не подходит.
function runRaw(input, env, args = []) {
  return spawnSync(process.execPath, [join(HOOKS, 'repeat-failure.mjs'), ...args], {
    input,
    encoding: 'utf8',
    cwd: REPO_ROOT,
    env: { ...process.env, ...env },
  });
}

// Прогон хука обычным payload с подмененным домом.
function runFail(payload, home, extra = {}) {
  return runRaw(JSON.stringify(payload), homeEnv(home, extra));
}

function contextOf(r) {
  const out = JSON.parse(r.stdout.trim());
  assertEq(out.hookSpecificOutput.hookEventName, 'PostToolUseFailure');
  return out.hookSpecificOutput.additionalContext;
}

test('подпись: первая непустая строка, числа, пути и кавычки', () => {
  assertEq(failureSignature('Bash', `\n  \n${ERROR_TEXT}\nвторая строка`),
    'Bash: Ошибка: не найден файл <p>, строка N');
  assertEq(failureSignature('Bash', 'сбой чтения C:\\proj\\Module.bsl:12'),
    'Bash: сбой чтения <p>:N');
  assertEq(failureSignature('Bash', 'сбой в /home/user/proj/Module.bsl и все'),
    'Bash: сбой в <p> и все');
  assertEq(failureSignature('Bash', 'много   пробелов\t\tи переводов'),
    'Bash: много пробелов и переводов');
  assertEq(failureSignature('Bash', ''), 'Bash');
  assertEq(failureSignature('Bash', 'x'.repeat(400)).length, 200, 'длина подписи');
});

test('два одинаковых падения: вывода нет, счетчик 2', async () => {
  const h = await makeHome();
  try {
    for (let i = 0; i < THRESHOLD - 1; i++) {
      const r = runFail(failPayload(SESSION), h.home);
      assertEq(r.status, 0, r.stderr);
      assertEq(r.stdout.trim(), '');
    }
    const state = JSON.parse(await readFile(statePath(h.home, SESSION), 'utf8'));
    assertEq(state.count, THRESHOLD - 1);
    assertEq(state.signature, failureSignature('Bash', ERROR_TEXT));
  } finally {
    await h.cleanup();
  }
});

test('третье падение дает указание модели, четвертое тоже', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION), h.home);
    runFail(failPayload(SESSION), h.home);
    const third = runFail(failPayload(SESSION), h.home);
    assertEq(third.status, 0, third.stderr);
    const text = contextOf(third);
    assert(text.includes(`упал ${THRESHOLD} раз подряд`), text);
    assert(text.includes('<p>'), text);
    assert(text.includes('смени подход или спроси пользователя'), text);
    assert(text.includes(failureSignature('Bash', ERROR_TEXT)), text);
    const fourth = runFail(failPayload(SESSION), h.home);
    assert(contextOf(fourth).includes(`упал ${THRESHOLD + 1} раз подряд`));
  } finally {
    await h.cleanup();
  }
});

test('другая ошибка сбрасывает счетчик', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION), h.home);
    runFail(failPayload(SESSION), h.home);
    const other = runFail(failPayload(SESSION, { error: OTHER_ERROR }), h.home);
    assertEq(other.stdout.trim(), '', 'новая ошибка начинает счет заново');
    let state = JSON.parse(await readFile(statePath(h.home, SESSION), 'utf8'));
    assertEq(state.count, 1);
    assertEq(state.signature, failureSignature('Bash', OTHER_ERROR));
    const repeat = runFail(failPayload(SESSION, { error: OTHER_ERROR }), h.home);
    assertEq(repeat.stdout.trim(), '', 'второе падение новой ошибки молчит');
    state = JSON.parse(await readFile(statePath(h.home, SESSION), 'utf8'));
    assertEq(state.count, 2);
  } finally {
    await h.cleanup();
  }
});

test('другое имя инструмента с той же ошибкой - другая подпись', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION), h.home);
    runFail(failPayload(SESSION), h.home);
    const other = runFail(failPayload(SESSION, { tool_name: 'Write' }), h.home);
    assertEq(other.stdout.trim(), '', 'инструмент входит в подпись');
    const state = JSON.parse(await readFile(statePath(h.home, SESSION), 'utf8'));
    assertEq(state.count, 1);
  } finally {
    await h.cleanup();
  }
});

test('другие аргументы вызова с той же ошибкой - не повтор', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION, { tool_input: { command: 'git status' } }), h.home);
    runFail(failPayload(SESSION, { tool_input: { command: 'npm test' } }), h.home);
    const third = runFail(failPayload(SESSION, { tool_input: { command: 'make build' } }), h.home);
    assertEq(third.stdout.trim(), '', 'три разные команды с одной ошибкой не склеиваются');
    const state = JSON.parse(await readFile(statePath(h.home, SESSION), 'utf8'));
    assertEq(state.count, 1);
  } finally {
    await h.cleanup();
  }
});

test('повтор, отличный только числами в аргументах, считается повтором', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION, { tool_input: { command: 'sleep 1 && run --port 8081' } }), h.home);
    runFail(failPayload(SESSION, { tool_input: { command: 'sleep 2 && run --port 8082' } }), h.home);
    const third = runFail(failPayload(SESSION, { tool_input: { command: 'sleep 3 && run --port 8083' } }), h.home);
    assert(contextOf(third).includes(`упал ${THRESHOLD} раз подряд`), third.stdout);
  } finally {
    await h.cleanup();
  }
});

test('запись состояния старше 7 дней не продолжает счет', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION), h.home);
    runFail(failPayload(SESSION), h.home);
    const file = statePath(h.home, SESSION);
    const old = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000);
    await utimes(file, old, old);
    const next = runFail(failPayload(SESSION), h.home);
    assertEq(next.stdout.trim(), '', 'устаревшее состояние отброшено');
    const state = JSON.parse(await readFile(file, 'utf8'));
    assertEq(state.count, 1);
  } finally {
    await h.cleanup();
  }
});

test('сессии не мешают друг другу', async () => {
  const h = await makeHome();
  try {
    runFail(failPayload(SESSION), h.home);
    runFail(failPayload(OTHER_SESSION), h.home);
    runFail(failPayload(SESSION), h.home);
    const second = runFail(failPayload(OTHER_SESSION), h.home);
    assertEq(second.stdout.trim(), '', 'счет второй сессии не сдвинулся');
    const third = runFail(failPayload(SESSION), h.home);
    assert(contextOf(third).includes('упал 3 раз подряд'));
    assertEq(JSON.parse(await readFile(statePath(h.home, OTHER_SESSION), 'utf8')).count, 2);
  } finally {
    await h.cleanup();
  }
});

test('BOM в начале входа не мешает разбору', async () => {
  const h = await makeHome();
  try {
    const input = `\uFEFF${JSON.stringify(failPayload(SESSION))}`;
    runRaw(input, homeEnv(h.home));
    runRaw(input, homeEnv(h.home));
    const third = runRaw(input, homeEnv(h.home));
    assertEq(third.status, 0, third.stderr);
    assert(contextOf(third).includes('упал 3 раз подряд'));
  } finally {
    await h.cleanup();
  }
});

test('cursor_version: тишина и запись состояния не создается', async () => {
  const h = await makeHome();
  try {
    for (let i = 0; i < THRESHOLD; i++) {
      const r = runFail(failPayload(SESSION, { cursor_version: '1.2.3' }), h.home);
      assertEq(r.status, 0, r.stderr);
      assertEq(r.stdout, '');
      assertEq(r.stderr, '');
    }
    assert(!existsSync(statePath(h.home, SESSION)), 'состояние не записано');
  } finally {
    await h.cleanup();
  }
});

test('REPEAT_FAILURE_OFF=1: тишина и запись состояния не создается', async () => {
  const h = await makeHome();
  try {
    for (let i = 0; i < THRESHOLD + 1; i++) {
      const r = runFail(failPayload(SESSION), h.home, { REPEAT_FAILURE_OFF: '1' });
      assertEq(r.status, 0, r.stderr);
      assertEq(r.stdout, '');
    }
    assert(!existsSync(statePath(h.home, SESSION)), 'состояние не записано');
  } finally {
    await h.cleanup();
  }
});

test('битый JSON: код 0 без вывода', async () => {
  const h = await makeHome();
  try {
    const r = runRaw('{ это не JSON', homeEnv(h.home));
    assertEq(r.status, 0);
    assertEq(r.stdout, '');
    assert(r.stderr.includes('[repeat-failure]'), r.stderr);
  } finally {
    await h.cleanup();
  }
});

test('пустой вход и нет имени инструмента: код 0 без вывода', async () => {
  const h = await makeHome();
  try {
    const empty = runRaw('', homeEnv(h.home));
    assertEq(empty.status, 0);
    assertEq(empty.stdout, '');
    assertEq(empty.stderr, '');
    const noTool = runFail(failPayload(SESSION, { tool_name: undefined }), h.home);
    assertEq(noTool.status, 0);
    assertEq(noTool.stdout, '');
    assert(!existsSync(statePath(h.home, SESSION)), 'состояние не записано');
  } finally {
    await h.cleanup();
  }
});

test('--only чужой каталог: тишина и запись состояния не создается', async () => {
  const h = await makeHome();
  const other = realpathSync.native(await mkdtemp(join(tmpdir(), 'repeat-failure-other-')));
  try {
    for (let i = 0; i < THRESHOLD; i++) {
      const r = runRaw(JSON.stringify(failPayload(SESSION)), homeEnv(h.home), ['--only', other]);
      assertEq(r.status, 0, r.stderr);
      assertEq(r.stdout, '');
      assertEq(r.stderr, '');
    }
    assert(!existsSync(statePath(h.home, SESSION)), 'состояние не записано');
    const inside = runRaw(JSON.stringify(failPayload(SESSION)), homeEnv(h.home), ['--only', REPO_ROOT]);
    assertEq(inside.status, 0, inside.stderr);
    assert(existsSync(statePath(h.home, SESSION)), 'свой каталог состояние пишет');
  } finally {
    await rm(other, { recursive: true, force: true });
    await h.cleanup();
  }
});

test('очистка: записи старше 7 дней удаляются, свежие остаются', async () => {
  const h = await makeHome();
  const day = 24 * 60 * 60 * 1000;
  try {
    const dir = join(h.home, '.claude', 'state', 'repeat-failure');
    await mkdir(dir, { recursive: true });
    const stale = join(dir, 'stale-session.json');
    const fresh = join(dir, 'fresh-session.json');
    await writeFile(stale, '{"signature":"Bash","count":1}\n', 'utf8');
    await writeFile(fresh, '{"signature":"Bash","count":1}\n', 'utf8');
    const old = new Date(Date.now() - 8 * day);
    await utimes(stale, old, old);
    const r = runFail(failPayload(SESSION), h.home);
    assertEq(r.status, 0, r.stderr);
    assert(!existsSync(stale), 'старая запись удалена');
    assert(existsSync(fresh), 'свежая запись осталась');
    assert(existsSync(statePath(h.home, SESSION)), 'запись текущей сессии на месте');
  } finally {
    await h.cleanup();
  }
});

await run();
