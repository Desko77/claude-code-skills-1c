#!/usr/bin/env node
// Исполняемые вызовы дочерних скриптов и тестов не должны запускать Windows PowerShell 5.1.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const files = [
  'skills/1c-cf-edit/scripts/cf-edit.ps1',
  'skills/1c-interface-edit/scripts/interface-edit.ps1',
  'skills/1c-meta-edit/scripts/meta-edit.ps1',
  'skills/1c-role-edit/scripts/role-edit.ps1',
  'skills/1c-subsystem-edit/scripts/subsystem-edit.ps1',
  'skills/1c-xdto-edit/scripts/xdto-edit.ps1',
  'tests/skills/runner.mjs',
  'tests/skills/check-uuid-invariant.mjs',
  'tests/skills/check-lint-catalog.mjs',
  'tests/skills/verify-snapshots.mjs',
  'tests/skills/build-webtest-db.mjs',
];
for (const entry of readdirSync(resolve(root, 'skills'), { withFileTypes: true })) {
  if (entry.isDirectory()) {
    const path = `skills/${entry.name}/SKILL.md`;
    try { readFileSync(resolve(root, path)); files.push(path); } catch (err) { if (err.code !== 'ENOENT') throw err; }
  }
}
const failures = [];
for (const path of files) {
  const text = readFileSync(resolve(root, path), 'utf8');
  const lines = text.split(/\r?\n/);
  lines.forEach((line, i) => {
    if (/^\s*(?:#|\/\/)/.test(line)) return;
    if ((path.endsWith('/SKILL.md') && /powershell\.exe\s+-NoProfile\s+-File/i.test(line)) || /&\s*powershell\.exe\b|(?:spawnSync|execFileSync)\s*\(\s*['"]powershell\.exe['"]|\[\s*['"]powershell\.exe['"]\s*,/i.test(line)) {
      failures.push(`${path}:${i + 1}`);
    }
  });
}
if (failures.length) {
  console.error(`Windows PowerShell 5.1 вызывается в:\n${failures.join('\n')}`);
  process.exit(1);
}
console.log(`OK - ${files.length} точек запуска не используют powershell.exe.`);
