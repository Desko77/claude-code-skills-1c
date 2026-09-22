// harness.mjs - мини-раннер тестов hooks без внешних зависимостей. Каждый *.test.mjs
// регистрирует проверки функцией test и завершается await run(); файл запускается
// отдельным процессом из run.mjs, падение одного файла не останавливает остальные.

const tests = [];

export function test(name, fn) {
  tests.push({ name, fn });
}

export function assert(cond, message) {
  if (!cond) throw new Error(message || 'утверждение ложно');
}

export function assertEq(actual, expected, message) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${message || 'значения различаются'}: ${a} != ${b}`);
}

export async function run() {
  let failed = 0;
  for (const t of tests) {
    try {
      await t.fn();
      console.log(`ok - ${t.name}`);
    } catch (err) {
      failed++;
      console.log(`FAIL - ${t.name}`);
      console.log(`  ${err instanceof Error ? err.stack : String(err)}`);
    }
  }
  const total = tests.length;
  console.log(failed === 0 ? `все ${total} прошли` : `${failed} из ${total} провалено`);
  process.exitCode = failed === 0 ? 0 : 1;
}
