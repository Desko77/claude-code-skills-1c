// Тесты hooks/common/quality-events.mjs: запись события без перезаписи занятого имени
// (файл создается открытием с 'wx', коллизия id перегенерируется).

import { readFile, readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { makeTmpRepo } from './helpers.mjs';
import { sessionDir, writeEvent } from '../../hooks/common/quality-events.mjs';

test('коллизия имени события: существующий файл не перезаписывается, id перегенерируется', async () => {
  const ctx = await makeTmpRepo();
  try {
    const ids = ['aaaaaa', 'aaaaaa', 'bbbbbb'];
    let next = 0;
    const mk = (n) => ({ type: 'applied', at: '2026-09-22T10:00:00.000+03:00',
      session: 'col-1', producer: 'hook', check: `check${n}@edt` });
    const first = await writeEvent(ctx.top, 'col-1', mk(1), { nextId: () => ids[next++] });
    assert(first.endsWith('-hook-aaaaaa.json'), `имя первого события: ${first}`);

    // lock-файлы удалены: следующий вызов занимает тот же номер последовательности и
    // сначала получает то же имя - оно занято, id перегенерируется.
    const colDir = sessionDir(ctx.top, 'col-1');
    for (const name of await readdir(colDir)) {
      if (name.endsWith('.lock')) await rm(join(colDir, name));
    }
    const second = await writeEvent(ctx.top, 'col-1', mk(2), { nextId: () => ids[next++] });
    assert(second.endsWith('-hook-bbbbbb.json'), `имя второго события: ${second}`);

    const firstAgain = JSON.parse(await readFile(first, 'utf8'));
    assertEq(firstAgain.check, 'check1@edt', 'первое событие не перезаписано');
    const secondData = JSON.parse(await readFile(second, 'utf8'));
    assertEq(secondData.check, 'check2@edt', 'второе событие записано');
    assert(first !== second, 'события в разных файлах');
  } finally {
    await ctx.cleanup();
  }
});

await run();
