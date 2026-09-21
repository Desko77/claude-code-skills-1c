#!/usr/bin/env node
// Гард блока "Сначала индекс": rules/mcp-tool-priority.md и agents/1c-explore.md несут один и тот
// же блок между маркерами index-first:begin/end. Агент копирует блок дословно из правила, ручная
// правка одной из копий без другой - дрейф. Печатает первую расходящуюся строку.
// Выход 1 при расхождении, отсутствии маркеров или пустом блоке.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const BEGIN = '<!-- index-first:begin -->';
const END = '<!-- index-first:end -->';

// Извлечь содержимое между маркерами (маркеры сами не входят в блок). EOL нормализуется:
// у правила и агента одна политика EOL репозитория, но рабочий файл мог быть записан
// с другой разметкой концов строк - предмет проверки текст блока, а не байты переводов.
function extractBlock(file) {
  const text = readFileSync(join(ROOT, file), 'utf8');
  const begin = text.indexOf(BEGIN);
  const end = text.indexOf(END);
  if (begin < 0) throw new Error(`${file}: нет маркера index-first:begin`);
  if (end < 0) throw new Error(`${file}: нет маркера index-first:end`);
  if (end < begin) throw new Error(`${file}: маркеры переставлены местами`);
  const block = text.slice(begin + BEGIN.length, end).replace(/\r\n/g, '\n');
  if (block.trim().length === 0) throw new Error(`${file}: блок между маркерами пуст`);
  return block;
}

const rule = extractBlock('rules/mcp-tool-priority.md');
const agent = extractBlock('agents/1c-explore.md');

if (rule === agent) {
  console.log('OK - блок "Сначала индекс" в правиле и агенте совпадает дословно');
  process.exit(0);
}

const ruleLines = rule.split('\n');
const agentLines = agent.split('\n');
for (let i = 0; i < Math.max(ruleLines.length, agentLines.length); i++) {
  if (ruleLines[i] !== agentLines[i]) {
    console.log(`DRIFT  строка ${i + 1} блока:`);
    console.log(`  правило: ${JSON.stringify(ruleLines[i] ?? null)}`);
    console.log(`  агент:   ${JSON.stringify(agentLines[i] ?? null)}`);
    process.exit(1);
  }
}
