// Гард единого источника матчера evidence-writer: выражение задано константой MATCHER в
// hooks/evidence-writer.mjs, строки в hooks/hooks.json обязаны совпадать с ним, README
// выражение не дублирует.

import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { assert, assertEq, run, test } from './harness.mjs';
import { REPO_ROOT } from './helpers.mjs';
import { MATCHER } from '../../hooks/evidence-writer.mjs';

test('строки матчера в hooks.json равны MATCHER из evidence-writer.mjs', async () => {
  const conf = JSON.parse(await readFile(join(REPO_ROOT, 'hooks', 'hooks.json'), 'utf8'));
  const matchers = [];
  for (const event of ['PostToolUse', 'PostToolUseFailure']) {
    for (const entry of conf.hooks[event] || []) {
      for (const h of entry.hooks) {
        if (String(h.command).includes('evidence-writer.mjs')) matchers.push(entry.matcher);
      }
    }
  }
  assertEq(matchers.length, 2, 'по одной строке на каждое событие');
  for (const m of matchers) {
    assertEq(m, MATCHER, 'строка hooks.json равна источнику MATCHER');
  }
});

test('README не дублирует выражение матчера', async () => {
  const text = await readFile(join(REPO_ROOT, 'hooks', 'README.md'), 'utf8');
  assert(!text.includes(MATCHER.source), 'README ссылается на hooks.json вместо копии выражения');
});

await run();
