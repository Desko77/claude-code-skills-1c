// skill-suggester.mjs v1.0 — PostToolUse hook: nudge toward the matching 1C skill when
// the model works the sources with raw tools (forgot a skill, or went manual).
// Source: https://github.com/Nikolay-Shirokov/cc-1c-skills
//
// stdin: PostToolUse JSON { tool_name, tool_input, session_id, cwd, ... }.
// Non-blocking: emits stdout JSON hookSpecificOutput.additionalContext (model-visible).
// Throttled to 1×/session/skill-group via marker files. Switch: skillSuggester (on|off)
// in .v8-project.json. Never throws.

import { classifyFile } from './common/object-class.mjs';
import { findConfigRoot } from './common/support-state.mjs';
import { getSuggesterMode } from './common/project.mjs';
import { resolve, isAbsolute, join } from 'node:path';
import { existsSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';

// Only file-targeting tools — these are where a skill genuinely substitutes the raw action.
// Content search (Grep/Glob) is intentionally NOT nudged: *-info skills help understand a
// located object, not find one by content.
function pickTarget(input, cwd) {
  const ti = input.tool_input || {};
  const tool = input.tool_name;
  if (tool !== 'Read' && tool !== 'Edit' && tool !== 'Write' && tool !== 'MultiEdit') return null;
  const raw = typeof ti.file_path === 'string' ? ti.file_path
    : (Array.isArray(ti.file_edits) && ti.file_edits[0]?.file_path) || null;
  if (!raw) return null;
  return isAbsolute(raw) ? raw : resolve(cwd, raw);
}

function sanitize(s) {
  return String(s || 'nosession').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 80);
}

// Core. opts.throttleDir overrides the marker directory (tests). Returns {stdout,stderr,exitCode}.
export function processInput(input, opts = {}) {
  const empty = { stdout: '', stderr: '', exitCode: 0 };
  try {
    const cwd = typeof input.cwd === 'string' ? input.cwd : process.cwd();
    const path = pickTarget(input, cwd);
    if (!path) return empty;

    const hit = classifyFile(path);
    if (!hit) return empty;

    // Read → info-skill; Edit/Write/MultiEdit → mutator-skill.
    const action = input.tool_name === 'Read' ? 'read' : 'write';
    const message = hit[action];
    if (!message) return empty;

    const { cfgDir } = findConfigRoot(path);
    if (getSuggesterMode(cfgDir, cwd) === 'off') return empty;

    // Throttle per (session, group, action): at most one read-nudge and one write-nudge
    // per skill-group per session.
    const dir = opts.throttleDir || tmpdir();
    const marker = join(dir, `cc-1c-suggest-${sanitize(input.session_id)}-${hit.group}-${action}`);
    if (existsSync(marker)) return empty;
    try { writeFileSync(marker, ''); } catch { /* throttle best-effort */ }

    const decision = {
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: `[1c-skills] ${message}`,
      },
    };
    return { stdout: JSON.stringify(decision), stderr: '', exitCode: 0 };
  } catch {
    return empty;
  }
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('skill-suggester.mjs')) {
  const raw = await readStdin();
  let input = {};
  try { input = raw.trim() ? JSON.parse(raw) : {}; } catch { input = {}; }
  const { stdout, stderr, exitCode } = processInput(input);
  if (stdout) process.stdout.write(stdout);
  if (stderr) process.stderr.write(stderr + '\n');
  process.exit(exitCode);
}
