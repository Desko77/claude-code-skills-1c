// helpers.mjs - общее для тестов hooks: временный git-репозиторий, запуск хука и CLI,
// чтение каталога событий. Тесты не зависят от машины: git настраивается локально,
// концы строк - LF, каталог следа исключен из git (как требует формат следа).

import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile, utimes } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const HOOKS = join(REPO_ROOT, 'hooks');
export const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

// Временный каталог с git-репозиторием внутри: { top, cleanup }.
export async function makeTmpRepo() {
  // Канонический путь: на раннерах Windows временный каталог приходит в короткой форме 8.3
  // (RUNNER~1), а хуки отдают длинную форму через git - сравнение путей в тестах иначе расходится.
  const base = realpathSync.native(await mkdtemp(join(tmpdir(), 'quality-hooks-')));
  const top = join(base, 'repo');
  await mkdir(top, { recursive: true });
  await git(top, 'init', '-q');
  await git(top, 'config', 'user.email', 'test@example.com');
  await git(top, 'config', 'user.name', 'Test');
  await git(top, 'config', 'core.autocrlf', 'false');
  await git(top, 'config', 'core.quotepath', 'false');
  await writeFile(join(top, '.gitignore'), '.claude/.state/\n', 'utf8');
  // Базовый коммит: без него HEAD не разрешается и diffHash не вычисляется.
  await git(top, 'add', '-A');
  await git(top, 'commit', '-q', '-m', 'base', '--no-gpg-sign', '--no-verify');
  return { top, cleanup: () => rm(base, { recursive: true, force: true }) };
}

export function git(repo, ...args) {
  const r = spawnSync('git', ['-C', repo, ...args], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`);
  return r.stdout;
}

export async function writeRepoFile(repo, rel, text) {
  const target = join(repo, rel);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, text, 'utf8');
}

// Запустить хук с payload на stdin; возвращает { status, stdout, stderr }.
// opts.env дополняет окружение процесса (например подмена PYTHON для недоступного валидатора).
export function runHook(hookFile, payload, opts = {}) {
  return spawnSync(process.execPath, [join(HOOKS, hookFile)], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    cwd: opts.cwd || REPO_ROOT,
    env: opts.env ? { ...process.env, ...opts.env } : process.env,
  });
}

// Запустить хук без ожидания (для параллельного теста); возвращает ChildProcess.
export function spawnHook(hookFile, payload) {
  const child = spawn(process.execPath, [join(HOOKS, hookFile)], { stdio: ['pipe', 'pipe', 'pipe'] });
  child.stdin.write(JSON.stringify(payload));
  child.stdin.end();
  return child;
}

// События сессии в порядке имен: [{...event, _file}].
export async function readEvents(top, session) {
  const dir = join(top, '.claude', '.state', 'quality', session, 'events');
  let names;
  try {
    names = readdirSync(dir).filter((n) => n.endsWith('.json')).sort();
  } catch {
    return [];
  }
  const out = [];
  for (const name of names) {
    const data = JSON.parse(await readFile(join(dir, name), 'utf8'));
    data._file = name;
    out.push(data);
  }
  return out;
}

// Подменить время изменения каталога сессии (тест очистки устаревших).
export async function touchSessionDir(top, session, ageMs) {
  const dir = join(top, '.claude', '.state', 'quality', session);
  const t = new Date(Date.now() - ageMs);
  await utimes(dir, t, t);
}

// Загрузить payload-фикстуру и дополнить cwd/session_id/tool_use_id.
export async function loadFixture(name, extra = {}) {
  const raw = JSON.parse(await readFile(join(REPO_ROOT, 'tests', 'hooks', 'fixtures', `${name}.json`), 'utf8'));
  return { ...raw, ...extra };
}

export function runCli(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { encoding: 'utf8', cwd: opts.cwd || REPO_ROOT });
}

export function runPythonSync(scriptArgs, opts = {}) {
  return runCli(PY, ['-X', 'utf8', ...scriptArgs], opts);
}
