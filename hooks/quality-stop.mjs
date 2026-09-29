// quality-stop.mjs - гейт завершения хода (хук Stop). Ход ассистента не завершается, пока
// у правок сессии в файлах 1С нет вердикта прогона "чисто" либо "с пробелами" по текущему
// diffHash: правки считаются по каноническому множеству против базовой отметки сессии
// (hooks/quality-baseline.mjs), вердикт дает tools/evidence.py check --strict - хук вызывает
// его как процесс python и сам вердикт не пересчитывает. Известные обходы - прерывание
// пользователем и защита платформы от повторных блокировок - записаны в hooks/README.md.
// Внутренняя ошибка и недоступный валидатор - выход 0 с диагностикой в stderr (fail-open).
// После MAX_CONSECUTIVE_BLOCKS блоков подряд без новых событий следа гейт уступает: ход
// завершается, пользователю - systemMessage (без серии цикл дойдет до предохранителя
// платформы). Непустая переменная QUALITY_STOP_OFF отключает гейт (работники в worktree,
// разборы) - выход 0 без вызова валидатора.
//
// stdin: Stop JSON { session_id, cwd, stop_hook_active, ... }.
//
// Коды выхода: 0 ход завершается (правок нет, вердикт 0/1, гейт не применим, серия блоков
// без прогресса, ошибка вызова); 2 ход блокируется - stderr с перечнем правок, причинами
// и прямым путем.

import { spawnSync } from 'node:child_process';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { listEventFiles, repoTop, sessionDir } from './common/quality-events.mjs';
import { findBaseline, findLastScope, resolveEvidencePy, sessionEdits } from './common/quality-gate.mjs';
import { scopeStatus } from './common/scope.mjs';

const VALIDATOR_TIMEOUT_MS = 120000;

// Путей в перечне правок не больше этого числа: после смены ветки или импорта из хранилища
// их тысячи, и полный перечень съедает контекст модели (остальное - числом).
const MAX_PATHS_IN_BLOCK = 20;

// Блоков подряд без новых событий следа: после этого числа гейт завершает ход выходом 0
// с systemMessage. Новые события (прогон, пропуск, probe, снятие) сбрасывают серию.
const MAX_CONSECUTIVE_BLOCKS = 2;

// Файл состояния серии блоков в каталоге сессии следа (рядом с events/).
const BLOCK_STATE_FILE = 'stop-gate.json';

// Интерпретатор python: PYTHON из env, иначе python на Windows и python3 на POSIX
// (как tests/hooks/helpers.mjs).
function pythonBin() {
  return process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
}

// Непустое значение QUALITY_STOP_OFF отключает гейт завершения хода.
export function gateDisabled() {
  const value = process.env.QUALITY_STOP_OFF;
  return value != null && value !== '';
}

// Причины блока: строки "блокирует: ..." вывода check без шапки и строк пробелов.
function validatorReasons(validatorOut) {
  return String(validatorOut || '').split(/\r?\n/)
    .map((l) => l.replace(/^блокирует:[ \t]*/, '').trim())
    .filter((l) => l && !l.startsWith('вердикт:') && !l.startsWith('diffHash:')
      && !l.startsWith('пробел:'));
}

// Текст блока: перечень правок (не больше MAX_PATHS_IN_BLOCK путей и общее число), причины
// из вывода валидатора, прямой путь с абсолютными путями инструментов и полной базой
// diffHash. tools = { changeProfilePy, evidencePy, base }.
export function buildBlock(edits, validatorOut, session, cwd, retry, required, tools) {
  const py = pythonBin();
  const base = tools && tools.base ? ` --base ${tools.base}` : '';
  const common = `--session ${session} --repo "${cwd}"${base}`;
  const lines = ['гейт завершения хода: у правок сессии в файлах 1С нет вердикта прогона'];
  lines.push(`правки сессии (файлы 1С), всего ${edits.length}:`);
  for (const edit of edits.slice(0, MAX_PATHS_IN_BLOCK)) lines.push(`  ${edit.status} ${edit.path}`);
  if (edits.length > MAX_PATHS_IN_BLOCK) {
    lines.push(`  ... еще ${edits.length - MAX_PATHS_IN_BLOCK} файлов не перечислены`);
  }
  lines.push('причины (tools/evidence.py check --strict):');
  const reasons = validatorReasons(validatorOut);
  lines.push(...(reasons.length ? reasons.map((r) => `  ${r}`) : ['  вердикт заблокирован']));
  lines.push('прямой путь:');
  lines.push(`  1. ${py} -X utf8 "${tools.changeProfilePy}" ${common}`
    + ' - профиль правки и обязательный состав проверок');
  if (required && required.length) {
    lines.push(`  2. обязательные проверки из профиля: ${required.join(', ')}`);
  } else {
    lines.push('  2. обязательные проверки назовет команда из п.1 (сейчас прогона нет)');
  }
  lines.push('  3. прогон проверки пишет applied хук по факту вызова инструмента');
  lines.push(`  4. пропуск: ${py} -X utf8 "${tools.evidencePy}" add --type skipped`
    + ' --check <имя> --class tool_unavailable|not_applicable'
    + ' (--ref <файл failed или probe down> | --reason <мотив>)' + ` ${common}`);
  lines.push(`  5. доступность источника: ${py} -X utf8 "${tools.evidencePy}" add --type probe`
    + ` --source <${['ai-edt', 'naparnik', 'script'].join('|')}> --status ok|down${common}`);
  lines.push('  6. снятие человеком: /quality release gate <причина>');
  if (retry) {
    lines.push('повторная попытка завершения; блок снимает только прогон проверок или команда снятия');
  }
  return lines.join('\n');
}

// Прочитать состояние серии блоков сессии; нет файла или поврежден - null.
async function readBlockState(top, session) {
  try {
    const data = JSON.parse(
      await readFile(join(sessionDir(top, session), BLOCK_STATE_FILE), 'utf8'));
    if (data && typeof data === 'object' && Number.isInteger(data.count)) return data;
  } catch {
    // состояние серии не читается - серия начинается заново
  }
  return null;
}

// Записать состояние серии блоков атомарно; отказ записи не меняет решение гейта
// (следующий блок посчитается первым).
async function writeBlockState(top, session, state) {
  try {
    const dir = sessionDir(top, session);
    await mkdir(dir, { recursive: true });
    const tmp = join(dir, `${BLOCK_STATE_FILE}.tmp`);
    await writeFile(tmp, `${JSON.stringify(state)}\n`, 'utf8');
    await rename(tmp, join(dir, BLOCK_STATE_FILE));
  } catch {
    // состояние серии не записано
  }
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает { code, stderr,
// stdout }; stdout - JSON с systemMessage для пользователя (код 0 после серии блоков),
// иначе пуст.
export async function processPayload(payload) {
  if (gateDisabled()) {
    return { code: 0, stderr: '[quality-stop] гейт отключен переменной QUALITY_STOP_OFF', stdout: '' };
  }
  if (!payload || typeof payload !== 'object' || typeof payload.session_id !== 'string'
      || !payload.session_id) {
    return { code: 0, stderr: '', stdout: '' };
  }
  const session = payload.session_id;
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  let top;
  try {
    top = await repoTop(cwd);
  } catch {
    return { code: 0, stderr: '', stdout: '' }; // вне git-репозитория гейт не применяется
  }
  let baseline;
  try {
    baseline = await findBaseline(top, session);
  } catch (err) {
    return { code: 0, stderr: `[quality-stop] чтение каталога событий: ${err.message}`, stdout: '' };
  }
  if (!baseline) {
    return { code: 0, stderr: '[quality-stop] отметки сессии нет, гейт не применяется', stdout: '' };
  }
  let edits;
  try {
    edits = await sessionEdits(cwd, baseline, top, session);
  } catch (err) {
    return { code: 0, stderr: `[quality-stop] правки не посчитаны: ${err.message}`, stdout: '' };
  }
  if (edits === null) {
    return { code: 0, stderr: '[quality-stop] отметка без HEAD (репозиторий без коммитов), гейт не применяется', stdout: '' };
  }
  if (edits.length === 0) return { code: 0, stderr: '', stdout: '' };
  const evidencePy = await resolveEvidencePy();
  if (!evidencePy) {
    return { code: 0, stderr: '[quality-stop] tools/evidence.py не найден, гейт пропущен', stdout: '' };
  }
  // База валидатора - HEAD отметки сессии, а не текущий HEAD: коммит по ходу сессии сдвигает
  // HEAD, и прогон, снятый до коммита, перестал бы совпадать по diffHash (а пустое множество
  // после коммита пропускало бы непроверенные правки).
  const run = spawnSync(pythonBin(),
    ['-X', 'utf8', evidencePy, 'check', '--strict', '--session', session, '--repo', cwd,
      '--base', baseline.head],
    { encoding: 'utf8', timeout: VALIDATOR_TIMEOUT_MS });
  if (run.error) {
    return { code: 0, stderr: `[quality-stop] валидатор следа не запущен (${run.error.message}), гейт пропущен`, stdout: '' };
  }
  if (run.status === 0 || run.status === 1) return { code: 0, stderr: '', stdout: '' };
  if (run.status === 3) {
    // Серия блоков без новых событий следа: после MAX_CONSECUTIVE_BLOCKS повторов гейт
    // завершает ход сам, иначе цикл дойдет до предохранителя платформы (9 блоков).
    let names = [];
    try {
      names = await listEventFiles(top, session);
    } catch {
      // каталог событий недоступен - серия считается первой
    }
    const lastEvent = names.length ? names[names.length - 1] : '';
    const prev = await readBlockState(top, session);
    const reasons = validatorReasons(run.stdout + run.stderr);
    if (prev && prev.lastEvent === lastEvent && prev.count >= MAX_CONSECUTIVE_BLOCKS) {
      const what = reasons.length ? reasons.slice(0, 3).join('; ') : 'вердикт заблокирован';
      const out = JSON.stringify({
        systemMessage: `гейт не снят, проверки не выполнены: ${what}. Ход завершен после ${prev.count}`
          + ' блоков подряд без событий прогона (hooks/quality-stop.mjs).',
      });
      return { code: 0, stderr: '', stdout: out };
    }
    const count = prev && prev.lastEvent === lastEvent ? prev.count + 1 : 1;
    await writeBlockState(top, session, { count, lastEvent });
    let required = null;
    try {
      const scope = await findLastScope(top, session);
      required = scope && Array.isArray(scope.required) ? scope.required : null;
    } catch {
      // перечень обязательных проверок в тексте блока необязателен
    }
    const retry = payload.stop_hook_active === true;
    return {
      code: 2,
      stderr: buildBlock(edits, run.stdout + run.stderr, session, cwd, retry, required, {
        changeProfilePy: join(dirname(evidencePy), 'change_profile.py'),
        evidencePy,
        base: baseline.head,
      }),
      stdout: '',
    };
  }
  return { code: 0, stderr: `[quality-stop] валидатор следа завершился кодом ${run.status}, гейт пропущен: ${(run.stderr || '').trim()}`, stdout: '' };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

// Запуск CLI только при прямом вызове (не при импорте тестами).
if (process.argv[1]?.endsWith('quality-stop.mjs')) {
  try {
    const raw = await readStdin();
    const payload = raw.trim() ? JSON.parse(raw) : null;
    const scope = scopeStatus(payload);
    if (scope.error) process.stderr.write(`${scope.error}\n`);
    if (scope.skip) process.exit(0);
    const { code, stdout, stderr } = await processPayload(payload);
    if (stdout) process.stdout.write(`${stdout}\n`);
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(code);
  } catch (err) {
    process.stderr.write(`[quality-stop] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
