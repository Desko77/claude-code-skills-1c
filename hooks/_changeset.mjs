// _changeset.mjs - каноническое множество изменений git-репозитория относительно
// базового коммита. Спецификация: skills/1c-code-review/references/changeset.md.
// Результат совпадает с tools/changeset.py байт в байт (сверяют тесты
// tests/tools/changeset/ по выводу CLI c --json). Экспорт computeChangeset
// предназначен хукам; CLI - тестам.
//
// CLI: node hooks/_changeset.mjs --repo <каталог> [--base <коммит>] [--json]
// Коды выхода: 0 расчет выполнен (в том числе пустое множество), 2 каталог не
// найден, не git-репозиторий, git недоступен, base не разрешается в коммит.

import { createHash } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { execFile as execFileCb } from 'node:child_process';
import { resolve } from 'node:path';
import { promisify } from 'node:util';

const execFile = promisify(execFileCb);
const GIT_MAX_BUFFER = 64 * 1024 * 1024;

class ChangesetError extends Error {}

// Выполнить git и вернуть stdout (Buffer); любой отказ - ChangesetError с
// диагностикой git из stderr.
async function runGit(args, cwd) {
  try {
    const { stdout } = await execFile('git', args, { cwd, maxBuffer: GIT_MAX_BUFFER, encoding: 'buffer' });
    return stdout;
  } catch (err) {
    const stderr = Buffer.isBuffer(err.stderr) ? err.stderr.toString('utf8') : String(err.stderr || '');
    throw new ChangesetError(`git ${args.join(' ')} завершился с кодом ${err.code}: ${stderr.trim()}`);
  }
}

// Декодировать вывод git как UTF-8; невалидные байты (toString заменяет их на
// U+FFFD, round-trip меняет байты) - ChangesetError.
function decode(data, what) {
  const s = data.toString('utf8');
  if (Buffer.from(s, 'utf8').equals(data)) return s;
  throw new ChangesetError(`${what}: путь не является валидным UTF-8`);
}

// Разделить NUL-terminated вывод git на токены (без хвостового пустого).
function splitNul(buf) {
  const out = [];
  let start = 0;
  while (start < buf.length) {
    const idx = buf.indexOf(0, start);
    if (idx === -1) {
      out.push(buf.subarray(start));
      break;
    }
    out.push(buf.subarray(start, idx));
    start = idx + 1;
  }
  return out;
}

// Разобрать git diff --name-status -z в Map NFC-путь -> запись
// { status, renamedFrom, fsPath } по правилам спецификации. У R/C после кода идут
// ДВА пути: прежний, затем новый (не как в git status -z, где первым идет новый).
function parseDiff(raw) {
  const tokens = splitNul(raw);
  const entries = new Map();
  let i = 0;
  while (i < tokens.length) {
    const code = decode(tokens[i], 'git diff').trim();
    let renamedFrom = null;
    let fsPath;
    if (code.startsWith('R') || code.startsWith('C')) {
      renamedFrom = decode(tokens[i + 1], 'git diff').normalize('NFC');
      fsPath = decode(tokens[i + 2], 'git diff');
      i += 3;
    } else {
      fsPath = decode(tokens[i + 1], 'git diff');
      i += 2;
    }
    let status;
    if (code.startsWith('R')) status = 'renamed';
    else if (code.startsWith('A') || code.startsWith('C')) status = 'added';
    else if (code.startsWith('D')) status = 'deleted';
    else status = 'modified';
    entries.set(fsPath.normalize('NFC'), { status, renamedFrom, fsPath });
  }
  return entries;
}

// Отличается ли рабочий файл от base (с учетом фильтров и конверсии пути); для
// конфликта "файл есть в base и на диске, но не в индексе" (git rm --cached):
// git diff такой путь всегда видит удалением (untracked для него невидим), поэтому
// сравниваются blob-хеши: hash-object --path (фильтры как при add) против ls-tree.
// Путь-операнд отделен --: имя с ведущим дефисом иначе читается как ключ, значение
// --path передается присоединенным (--path=).
async function differsFromBase(top, base, fsPath) {
  const lsLine = decode(await runGit(['ls-tree', base, '--', fsPath], top), 'git ls-tree').trim();
  const fields = lsLine.split(/\s+/);
  if (fields.length < 3) return true; // пути нет в base; для конфликта с D недостижимо
  const baseBlob = fields[2].split('\t')[0];
  const workBlob = decode(
    await runGit(['hash-object', `--path=${fsPath}`, '--', fsPath], top), 'git hash-object').trim();
  return workBlob !== baseBlob;
}

// Пути-гитлинки (подмодули): режим 160000 в индексе или в базовом коммите. Gitlink -
// запись о коммите другого репозитория, в рабочем дереве это каталог; такой путь
// исключается из множества целиком при любом статусе diff. Источники - ls-files -s
// (индекс: новый gitlink в base отсутствует) и ls-tree -r <base> (gitlink мог быть
// удален из индекса). Формат -z: метаданные, TAB, путь, NUL - первый TAB отделяет
// метаданные от пути, TAB внутри самого пути не мешает.
async function gitlinkPaths(top, base) {
  const paths = new Set();
  const outputs = [await runGit(['ls-files', '-s', '-z'], top),
                   await runGit(['ls-tree', '-r', '-z', base], top)];
  for (const raw of outputs) {
    for (const record of splitNul(raw)) {
      const tabIdx = record.indexOf(9); // TAB
      if (tabIdx === -1) continue;
      const mode = record.subarray(0, tabIdx).toString('latin1').split(' ')[0];
      if (mode === '160000') {
        paths.add(decode(record.subarray(tabIdx + 1), 'git ls-tree').normalize('NFC'));
      }
    }
  }
  return paths;
}

// Собрать байты для diffHash из записей, уже отсортированных по байтам пути.
// Запись кадрируется однозначно: длина пути в байтах UTF-8 (десятичная), ":",
// байты пути, NUL, статус, NUL, sha256 либо литерал null, NUL. Префикс длины
// разделяет записи - имя с табуляцией или переводом строки не может сложиться
// в ту же последовательность байтов, что имена других файлов.
export function buildDiffPayload(files) {
  const chunks = [];
  for (const r of files) {
    const pathBytes = Buffer.from(r.path, 'utf8');
    const sha = r.sha256 === null ? 'null' : r.sha256;
    chunks.push(
      Buffer.from(`${pathBytes.length}:`, 'ascii'),
      pathBytes,
      Buffer.from(`\0${r.status}\0${sha}\0`, 'ascii'),
    );
  }
  return Buffer.concat(chunks);
}

// Вычислить каноническое множество изменений относительно base; результат по
// спецификации skills/1c-code-review/references/changeset.md:
// { base, diffHash, files } с записями { path, sha256, status [, renamedFrom] }.
export async function computeChangeset(repoDir, base = 'HEAD') {
  const repoPath = resolve(repoDir);
  let repoStat;
  try {
    repoStat = await stat(repoPath);
  } catch {
    throw new ChangesetError(`каталог не найден: ${repoPath}`);
  }
  if (!repoStat.isDirectory()) throw new ChangesetError(`не каталог: ${repoPath}`);

  const top = decode(await runGit(['rev-parse', '--show-toplevel'], repoPath), 'git rev-parse').trim();
  const baseSha = decode(
    await runGit(['rev-parse', '--verify', `${base}^{commit}`], top), 'git rev-parse').trim();
  const diffRaw = await runGit(
    ['diff', '--name-status', '-z', '-M', '--no-color', '--no-ext-diff', '--no-textconv', base], top);
  const untrackedRaw = await runGit(['ls-files', '--others', '--exclude-standard', '-z'], top);

  const entries = parseDiff(diffRaw);
  for (const token of splitNul(untrackedRaw)) {
    const fsPath = decode(token, 'git ls-files');
    const path = fsPath.normalize('NFC');
    if (!entries.has(path)) {
      entries.set(path, { status: 'added', renamedFrom: null, fsPath });
    }
    // Путь, совпавший с записью diff (git rm --cached без игнора), отдельной
    // записью не становится: статус из diff - deleted, арбитраж - в финальном
    // проходе по факту файла на диске.
  }

  const gitlinks = await gitlinkPaths(top, base);
  const files = [];
  for (const [path, entryIn] of entries) {
    let entry = entryIn;
    if (gitlinks.has(path)) continue; // подмодуль: gitlink, в рабочем дереве каталог
    let isFile = false;
    try {
      isFile = (await stat(resolve(top, entry.fsPath))).isFile();
    } catch {
      isFile = false;
    }
    if (entry.status === 'deleted' && isFile) {
      // Файл есть в base и на диске, но не в индексе (git rm --cached), причем
      // путь игнорируемый - ls-files --others его не показывает. Отличие от base
      // решает сравнение blob-хешей: равен - записи нет, отличается - modified.
      if (!(await differsFromBase(top, base, entry.fsPath))) continue;
      entry = { status: 'modified', renamedFrom: null, fsPath: entry.fsPath };
    }
    if (!isFile) {
      if (entry.status === 'added' || entry.status === 'renamed') continue; // нет ни в base, ни в дереве
      files.push({ path, sha256: null, status: 'deleted' });
      continue;
    }
    const buf = await readFile(resolve(top, entry.fsPath));
    const record = {
      path,
      sha256: createHash('sha256').update(buf).digest('hex'),
      status: entry.status,
    };
    if (entry.renamedFrom !== null) record.renamedFrom = entry.renamedFrom;
    files.push(record);
  }

  files.sort((a, b) => Buffer.compare(Buffer.from(a.path, 'utf8'), Buffer.from(b.path, 'utf8')));
  const diffHash = createHash('sha256').update(buildDiffPayload(files)).digest('hex');
  return { base: baseSha, diffHash, files };
}

// Рекурсивно отсортировать ключи объектов: JSON.stringify не сортирует сам,
// а сериализация обязана совпадать с json.dumps(sort_keys=True) из Python.
function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeysDeep(value[key]);
    return out;
  }
  return value;
}

// Таблица множества для человека (формат спецификацией не фиксируется).
function renderTable(result) {
  const lines = [`base: ${result.base}`, `diffHash: ${result.diffHash}`, `файлов: ${result.files.length}`];
  for (const r of result.files) {
    const sha = r.sha256 === null ? '-' : r.sha256;
    const tail = 'renamedFrom' in r ? ` <- ${r.renamedFrom}` : '';
    lines.push(`${r.status.padEnd(8)} ${sha}  ${r.path}${tail}`);
  }
  return lines.join('\n');
}

async function cliMain() {
  const argv = process.argv.slice(2);
  const opts = { repo: '.', base: 'HEAD', json: false };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--repo' && i + 1 < argv.length) opts.repo = argv[++i];
    else if (argv[i] === '--base' && i + 1 < argv.length) opts.base = argv[++i];
    else if (argv[i] === '--json') opts.json = true;
    else {
      process.stderr.write(`неизвестный аргумент: ${argv[i]}\n`);
      process.exit(2);
    }
  }
  try {
    const result = await computeChangeset(opts.repo, opts.base);
    if (opts.json) process.stdout.write(JSON.stringify(sortKeysDeep(result), null, 2) + '\n');
    else process.stdout.write(renderTable(result) + '\n');
    process.exit(0);
  } catch (err) {
    process.stderr.write(`ошибка: ${err.message}\n`);
    process.exit(2);
  }
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('_changeset.mjs')) await cliMain();
