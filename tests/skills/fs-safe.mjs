// Удаление файлов и каталогов, устойчивое к не-ASCII путям на Windows.
//
// Замер на Node v24.11.1 (Windows): fs.rmSync МОЛЧА не удаляет путь, в котором есть кириллица -
// ни исключения, ни удаления, и это верно даже для пустого каталога. Тем же дефектом поражен
// fs.rmdirSync с recursive. При этом unlinkSync и rmdirSync без recursive работают.
//
// Для набора это боевой случай: временный каталог пользователя с русским именем учетной записи
// (C:\Users\Иванов\AppData\Local\Temp) делает нелатинским КАЖДЫЙ рабочий каталог прогона -
// эталоны перестают перезаписываться, мусор копится, и ни одной ошибки в выводе.
//
// Обход: рекурсивный обход дерева примитивами, которые дефектом не поражены.
import { readdirSync, lstatSync, unlinkSync, rmdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

function removeEntry(target, retries, delayMs) {
  let info;
  try {
    // lstat, а не stat: по симлинку и по junction (а их у нас заводят как раз для обхода
    // кириллицы в пути) stat уводит в цель, и рекурсия вычистила бы чужой каталог за
    // пределами рабочего. Сама ссылка удаляется как запись, ее цель не трогается.
    info = lstatSync(target);
  } catch {
    return; // уже нет
  }

  const isLink = info.isSymbolicLink();

  if (info.isDirectory() && !isLink) {
    for (const name of readdirSync(target)) {
      removeEntry(join(target, name), retries, delayMs);
    }
  }

  if (isLink) {
    // Симлинк на каталог и junction на Windows снимаются rmdir, файловый симлink - unlink.
    try {
      unlinkSync(target);
    } catch (e) {
      if (e.code === 'EPERM' || e.code === 'EISDIR') rmdirSync(target);
      else if (e.code !== 'ENOENT') throw e;
    }
    return;
  }

  // На Windows дескриптор только что завершившегося процесса живет еще несколько
  // миллисекунд, и удаление падает с EBUSY. Это единственная причина повторов.
  for (let attempt = 0; ; attempt++) {
    try {
      if (info.isDirectory()) rmdirSync(target);
      else unlinkSync(target);
      return;
    } catch (e) {
      if (e.code === 'ENOENT') return;
      if (attempt >= retries) throw e;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delayMs);
    }
  }
}

/**
 * Удалить файл или дерево каталогов.
 * @param {string} target путь
 * @param {{retries?: number, delayMs?: number, force?: boolean}} [opts]
 *   retries - число повторов при EBUSY, delayMs - пауза между ними,
 *   force - не бросать исключение, если удалить не удалось.
 *
 * force по умолчанию ВЫКЛЮЧЕН намеренно. Почти все удаления здесь подготовительные:
 * следом на то же место кладут эталон, кэш или новую базу. Проглоченный отказ оставляет
 * старое содержимое, и прогон сравнивает не то, что думает. Проглатывать ошибку осмысленно
 * только там, где удаление финальное и его неудача не влияет на результат.
 */
export function removeTree(target, opts = {}) {
  const { retries = 0, delayMs = 100, force = false } = opts;
  if (!target || !existsSync(target)) return;
  try {
    removeEntry(target, retries, delayMs);
  } catch (e) {
    if (!force) throw e;
  }
}
