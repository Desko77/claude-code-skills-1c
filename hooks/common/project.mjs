// project.mjs v1.0 — read reaction mode from .v8-project.json for Claude Code hooks
// Source: https://github.com/Nikolay-Shirokov/cc-1c-skills
//
// Canonical port of Get-EditMode / _sg_get_edit_mode
// (reference: .claude/skills/meta-edit/scripts/meta-edit.ps1:181-201, meta-edit.py:50-68).
// configSrc is matched here ONLY to fetch a per-database override — identically to the
// in-skill guard §1B, so that a raw Edit and an edit-via-skill behave the same under the
// same databases[].editingAllowedCheck. Never throws — falls back to the default.

import { readFileSync, existsSync, statSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';

const WIN = process.platform === 'win32';

function norm(p) {
  let s = resolve(p).replace(/[\\/]+$/, '');
  return WIN ? s.toLowerCase() : s;
}

function findV8Project(startDir) {
  let d = startDir;
  for (let i = 0; i < 20 && d; i++) {
    const pj = join(d, '.v8-project.json');
    if (existsSync(pj)) return pj;
    const parent = dirname(d);
    if (parent === d) break;
    d = parent;
  }
  return null;
}

// Generic reader: returns databases[].<key> for the matching configSrc, else global
// proj.<key>, else fallback. cwd is the hook's stdin cwd; cfgDir is the resolved config root.
export function getProjectSetting(key, cfgDir, cwd, fallback) {
  try {
    const pj = findV8Project(cwd) || (cfgDir ? findV8Project(cfgDir) : null);
    if (!pj) return fallback;
    let raw = readFileSync(pj, 'utf8');
    if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1); // strip BOM
    const proj = JSON.parse(raw);
    if (cfgDir && Array.isArray(proj.databases)) {
      const cfgFull = norm(cfgDir);
      for (const db of proj.databases) {
        if (db && db.configSrc) {
          const src = norm(db.configSrc);
          if (cfgFull === src || cfgFull.startsWith(src + sep)) {
            if (db[key]) return db[key];
          }
        }
      }
    }
    if (proj[key]) return proj[key];
    return fallback;
  } catch {
    return fallback;
  }
}

// Guard reaction: deny (default) | warn | off.
export function getEditMode(cfgDir, cwd) {
  return getProjectSetting('editingAllowedCheck', cfgDir, cwd, 'deny');
}

// Suggester switch: on (default) | off.
export function getSuggesterMode(cfgDir, cwd) {
  return getProjectSetting('skillSuggester', cfgDir, cwd, 'on');
}
