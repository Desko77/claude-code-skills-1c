// home.mjs - домашний каталог пользователя для следа и ворот.
// На win32 первым идет USERPROFILE, на остальных платформах - HOME.

import { homedir } from 'node:os';

export function claudeHome() {
  if (process.platform === 'win32') return process.env.USERPROFILE || process.env.HOME || homedir();
  return process.env.HOME || process.env.USERPROFILE || homedir();
}
