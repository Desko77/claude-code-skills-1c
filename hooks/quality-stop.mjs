// quality-stop.mjs - гейт завершения хода (хук Stop). Ход ассистента не завершается, пока
// у правок сессии в файлах 1С нет вердикта прогона "чисто" либо "с пробелами" по текущему
// diffHash: правки считаются по каноническому множеству против базовой отметки сессии
// (hooks/quality-baseline.mjs), вердикт дает tools/evidence.py check --strict - хук вызывает
// его как процесс python и сам вердикт не пересчитывает. Известные обходы - прерывание
// пользователем и защита платформы от повторных блокировок - записаны в hooks/README.md.
// Внутренняя ошибка и недоступный валидатор - выход 0 с диагностикой в stderr (fail-open).
//
// stdin: Stop JSON { session_id, cwd, stop_hook_active, ... }.
//
// Коды выхода: 0 ход завершается (правок нет, вердикт 0/1, гейт не применим, ошибка
// вызова); 2 ход блокируется - stderr с перечнем правок, причинами и прямым путем.

import { spawnSync } from 'node:child_process';
import { repoTop } from './common/quality-events.mjs';
import { findBaseline, findLastScope, resolveEvidencePy, sessionEdits } from './common/quality-gate.mjs';

const VALIDATOR_TIMEOUT_MS = 120000;

// Интерпретатор python: PYTHON из env, иначе python на Windows и python3 на POSIX
// (как tests/hooks/helpers.mjs).
function pythonBin() {
  return process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
}

// Текст блока: перечень правок, причины из вывода валидатора, прямой путь и строка
// повторной попытки. Причины - строки "блокирует: ..." вывода check.
export function buildBlock(edits, validatorOut, session, cwd, retry, required) {
  const lines = ['гейт завершения хода: у правок сессии в файлах 1С нет вердикта прогона'];
  lines.push('правки сессии (файлы 1С):');
  for (const edit of edits) lines.push(`  ${edit.status} ${edit.path}`);
  lines.push('причины (tools/evidence.py check --strict):');
  const reasons = String(validatorOut || '').split(/\r?\n/)
    .map((l) => l.replace(/^блокирует:[ \t]*/, '').trim())
    .filter((l) => l && !l.startsWith('вердикт:') && !l.startsWith('diffHash:')
      && !l.startsWith('пробел:'));
  lines.push(...(reasons.length ? reasons.map((r) => `  ${r}`) : ['  вердикт заблокирован']));
  lines.push('прямой путь:');
  lines.push(`  1. python tools/change_profile.py --session ${session} --repo ${cwd}`
    + ' - профиль правки и обязательный состав проверок');
  if (required && required.length) {
    lines.push(`  2. обязательные проверки из профиля: ${required.join(', ')}`);
  } else {
    lines.push('  2. обязательные проверки назовет команда из п.1 (сейчас прогона нет)');
  }
  lines.push('  3. закрыть каждую проверку: applied пишет хук по факту вызова инструмента,'
    + ' пропуск - python tools/evidence.py add --type skipped, доступность источника - probe');
  lines.push('  4. снятие человеком: /quality release gate <причина>');
  if (retry) {
    lines.push('повторная попытка завершения; блок снимает только прогон проверок или команда снятия');
  }
  return lines.join('\n');
}

// Основная логика, отделенная от чтения stdin для тестов. Возвращает { code, stderr };
// stdout гейт не использует.
export async function processPayload(payload) {
  if (!payload || typeof payload !== 'object' || typeof payload.session_id !== 'string'
      || !payload.session_id) {
    return { code: 0, stderr: '' };
  }
  const session = payload.session_id;
  const cwd = typeof payload.cwd === 'string' && payload.cwd ? payload.cwd : process.cwd();
  let top;
  try {
    top = await repoTop(cwd);
  } catch {
    return { code: 0, stderr: '' }; // вне git-репозитория гейт не применяется
  }
  let baseline;
  try {
    baseline = await findBaseline(top, session);
  } catch (err) {
    return { code: 0, stderr: `[quality-stop] чтение каталога событий: ${err.message}` };
  }
  if (!baseline) {
    return { code: 0, stderr: '[quality-stop] отметки сессии нет, гейт не применяется' };
  }
  let edits;
  try {
    edits = await sessionEdits(cwd, baseline);
  } catch (err) {
    return { code: 0, stderr: `[quality-stop] правки не посчитаны: ${err.message}` };
  }
  if (edits === null) {
    return { code: 0, stderr: '[quality-stop] отметка без HEAD (репозиторий без коммитов), гейт не применяется' };
  }
  if (edits.length === 0) return { code: 0, stderr: '' };
  const evidencePy = await resolveEvidencePy();
  if (!evidencePy) {
    return { code: 0, stderr: '[quality-stop] tools/evidence.py не найден, гейт пропущен' };
  }
  // База валидатора - HEAD отметки сессии, а не текущий HEAD: коммит по ходу сессии сдвигает
  // HEAD, и прогон, снятый до коммита, перестал бы совпадать по diffHash (а пустое множество
  // после коммита пропускало бы непроверенные правки).
  const run = spawnSync(pythonBin(),
    ['-X', 'utf8', evidencePy, 'check', '--strict', '--session', session, '--repo', cwd,
      '--base', baseline.head],
    { encoding: 'utf8', timeout: VALIDATOR_TIMEOUT_MS });
  if (run.error) {
    return { code: 0, stderr: `[quality-stop] валидатор следа не запущен (${run.error.message}), гейт пропущен` };
  }
  if (run.status === 0 || run.status === 1) return { code: 0, stderr: '' };
  if (run.status === 3) {
    let required = null;
    try {
      const scope = await findLastScope(top, session);
      required = scope && Array.isArray(scope.required) ? scope.required : null;
    } catch {
      // перечень обязательных проверок в тексте блока необязателен
    }
    const retry = payload.stop_hook_active === true;
    return { code: 2, stderr: buildBlock(edits, run.stdout + run.stderr, session, cwd, retry, required) };
  }
  return { code: 0, stderr: `[quality-stop] валидатор следа завершился кодом ${run.status}, гейт пропущен: ${(run.stderr || '').trim()}` };
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
    const { code, stderr } = await processPayload(payload);
    if (stderr) process.stderr.write(`${stderr}\n`);
    process.exit(code);
  } catch (err) {
    process.stderr.write(`[quality-stop] ${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(0);
  }
}
