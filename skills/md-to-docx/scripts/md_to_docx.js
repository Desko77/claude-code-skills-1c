#!/usr/bin/env node
/**
 * md_to_docx.js — Convert Markdown to DOCX with hyperlinks, tables, code blocks, images.
 *
 * Usage:
 *   NODE_PATH=<global_node_modules> node md_to_docx.js input.md [output.docx] \
 *       [--author "Имя Фамилия"] [--title "Заголовок документа"] \
 *       [--no-shading | --shading=on|off]
 *
 *   - Output is optional; if omitted, replaces .md with .docx next to input.
 *   - --author writes core property dc:creator and cp:lastModifiedBy.
 *   - --title overrides the default document title (basename of input).
 *   - --no-shading (alias: --shading=off) disables grey background fill
 *     for inline `code` and fenced ``` code blocks. Table header shading
 *     is structural and is NOT affected by this flag.
 *   - Both --flag value and --flag=value forms are supported.
 *
 * Requires: npm install -g docx
 */

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, ExternalHyperlink, InternalHyperlink,
  Bookmark, ImageRun,
  HeadingLevel, BorderStyle, WidthType, ShadingType, PageNumber,
  LevelFormat, PageBreak, TableLayoutType, PageOrientation
} = require("docx");

// --- Args ---
const rawArgs = process.argv.slice(2);
const positional = [];
let author = null;
let titleOverride = null;
let codeShading = true;
for (let k = 0; k < rawArgs.length; k++) {
  const a = rawArgs[k];
  if (a === "--author") {
    author = rawArgs[++k];
  } else if (a.startsWith("--author=")) {
    author = a.slice("--author=".length);
  } else if (a === "--title") {
    titleOverride = rawArgs[++k];
  } else if (a.startsWith("--title=")) {
    titleOverride = a.slice("--title=".length);
  } else if (a === "--no-shading") {
    codeShading = false;
  } else if (a === "--shading") {
    codeShading = (rawArgs[++k] || "").toLowerCase() !== "off";
  } else if (a.startsWith("--shading=")) {
    codeShading = a.slice("--shading=".length).toLowerCase() !== "off";
  } else {
    positional.push(a);
  }
}
const inputPath = positional[0];
if (!inputPath) {
  console.error('Usage: node md_to_docx.js input.md [output.docx] [--author "Author Name"] [--title "Document Title"] [--no-shading]');
  process.exit(1);
}
const outputPath = positional[1] || inputPath.replace(/\.md$/i, ".docx");
const docTitle = titleOverride || path.basename(inputPath, path.extname(inputPath));
const inputDir = path.dirname(path.resolve(inputPath));

if (!fs.existsSync(inputPath)) {
  console.error(`Error: file not found: ${inputPath}`);
  process.exit(1);
}
const md = fs.readFileSync(inputPath, "utf-8");
// Strip YAML front matter (---...---)
let content = md;
if (content.startsWith("---\n") || content.startsWith("---\r\n")) {
  const endIdx = content.indexOf("\n---", 3);
  if (endIdx !== -1) {
    content = content.slice(content.indexOf("\n", endIdx + 4) + 1);
  }
}
const lines = content.split("\n");

// --- Parse markdown into blocks ---
const blocks = [];
let i = 0;
let inCodeBlock = false;
let codeLines = [];
let codeLang = "";
let inTable = false;
let tableRows = [];
let pendingAnchor = null;

function flushTable() {
  if (inTable && tableRows.length > 0) {
    blocks.push({ type: "table", rows: tableRows });
    tableRows = [];
    inTable = false;
  }
}

// Начинает ли строка новый блок. Нужно, чтобы отличить перенос внутри абзаца
// (мягкий перенос исходника) от настоящей границы блока.
function startsNewBlock(line) {
  const t = line.trim();
  if (t === "") return true;
  if (t.startsWith("```")) return true;
  if (t.startsWith("|") && t.endsWith("|")) return true;
  if (/^#{1,6}\s+/.test(line)) return true;
  if (/^---+$/.test(t)) return true;
  if (/^[-*]\s+/.test(t)) return true;
  if (/^\d+\.\s+/.test(t)) return true;
  if (/^!\[[^\]]*\]\(/.test(t)) return true;
  if (/^<!--\s*(landscape|portrait)\s*-->$/i.test(t)) return true;
  if (/^<a\s+id="[^"]+"><\/a>$/i.test(t)) return true;
  return false;
}

// Собирает абзац или пункт списка из всех строк до границы блока.
// В Markdown одиночный перенос строки - мягкий: он склеивается пробелом, а не
// разрывает предложение. Без этого исходник, свернутый по ширине, рвался в DOCX
// на обрубки посреди фразы.
// Части склеиваются РОВНО одним пробелом: хвостовые и ведущие пробелы строк
// срезаются, внутренние повторы схлопываются - двойных пробелов в тексте не остается.
function gatherSoftWrapped(firstText, startIdx) {
  const parts = [firstText.trim()];
  let j = startIdx;
  while (j < lines.length && !startsNewBlock(lines[j])) {
    parts.push(lines[j].trim());
    j++;
  }
  const text = parts.filter(p => p !== "").join(" ").replace(/[ \t]{2,}/g, " ");
  return { text, next: j };
}

while (i < lines.length) {
  const line = lines[i];

  // Code block fences
  if (line.startsWith("```")) {
    if (inCodeBlock) {
      blocks.push({ type: "code", text: codeLines.join("\n"), lang: codeLang });
      codeLines = [];
      inCodeBlock = false;
      codeLang = "";
    } else {
      flushTable();
      inCodeBlock = true;
      codeLang = line.slice(3).trim();
    }
    i++;
    continue;
  }
  if (inCodeBlock) {
    codeLines.push(line);
    i++;
    continue;
  }

  // Table row
  if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
    if (!inTable) inTable = true;
    // Skip separator rows (|---|---|)
    // Разделитель обязан содержать дефис, иначе строка из пустых ячеек (|  |  |)
    // ошибочно принимается за разделитель и теряется.
    if (/^\|[\s\-:|]*-[\s\-:|]*\|$/.test(line.trim())) { i++; continue; }
    const cells = line.split("|").slice(1, -1).map(c => c.trim());
    tableRows.push(cells);
    i++;
    continue;
  } else {
    flushTable();
  }

  // Смена ориентации страницы: <!-- landscape --> / <!-- portrait -->.
  // Начинает новую секцию документа, широкие таблицы верстаются альбомно.
  const orientMatch = line.match(/^\s*<!--\s*(landscape|portrait)\s*-->\s*$/i);
  if (orientMatch) {
    blocks.push({ type: "orientation", value: orientMatch[1].toLowerCase() });
    i++;
    continue;
  }

  // HTML anchor <a id="..."></a> -> remember for next heading/block
  const anchorMatch = line.match(/^\s*<a\s+id="([^"]+)"><\/a>\s*$/i);
  if (anchorMatch) {
    pendingAnchor = anchorMatch[1];
    i++;
    continue;
  }

  // Heading
  const hMatch = line.match(/^(#{1,6})\s+(.*)/);
  if (hMatch) {
    blocks.push({ type: "heading", level: hMatch[1].length, text: hMatch[2], anchor: pendingAnchor });
    pendingAnchor = null;
    i++;
    continue;
  }

  // Horizontal rule
  if (/^---+\s*$/.test(line.trim())) {
    blocks.push({ type: "hr" });
    i++;
    continue;
  }

  // Empty line
  if (line.trim() === "") { i++; continue; }

  // List item (bullet)
  const bulletMatch = line.match(/^(\s*)[-*]\s+(.*)/);
  if (bulletMatch) {
    const indent = Math.floor((bulletMatch[1] || "").length / 2);
    const gathered = gatherSoftWrapped(bulletMatch[2], i + 1);
    blocks.push({ type: "bullet", indent, text: gathered.text });
    i = gathered.next;
    continue;
  }

  // List item (numbered)
  const numMatch = line.match(/^(\s*)\d+\.\s+(.*)/);
  if (numMatch) {
    const indent = Math.floor((numMatch[1] || "").length / 2);
    const gathered = gatherSoftWrapped(numMatch[2], i + 1);
    blocks.push({ type: "numbered", indent, text: gathered.text });
    i = gathered.next;
    continue;
  }

  // Standalone image line: ![alt](path)
  const imgMatch = line.match(/^!\[([^\]]*)\]\(((?:[^()]*|\([^)]*\))*)\)\s*$/);
  if (imgMatch) {
    blocks.push({ type: "image", alt: imgMatch[1], src: imgMatch[2] });
    i++;
    continue;
  }

  // Regular paragraph
  const para = gatherSoftWrapped(line, i + 1);
  blocks.push({ type: "paragraph", text: para.text });
  i = para.next;
}
flushTable();

// --- Inline markdown parser ---
// Handles: **bold**, *italic*, `code`, [text](url) with balanced parens in URLs
function parseInline(text) {
  const runs = [];
  const re = /(\*\*(.+?)\*\*)|(\[([^\]]+)\]\(((?:[^()]*|\([^)]*\))*)\))|(`([^`]+)`)|(\*(.+?)\*)/g;
  let lastIndex = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      runs.push({ text: text.slice(lastIndex, m.index) });
    }
    if (m[1]) {
      runs.push({ text: m[2], bold: true });
    } else if (m[3]) {
      runs.push({ text: m[4], link: m[5] });
    } else if (m[6]) {
      runs.push({ text: m[7], code: true });
    } else if (m[8]) {
      runs.push({ text: m[9], italic: true });
    }
    lastIndex = re.lastIndex;
  }
  if (lastIndex < text.length) {
    runs.push({ text: text.slice(lastIndex) });
  }
  return runs;
}

// Convert parsed inline to docx TextRun/ExternalHyperlink
function makeRuns(text, fontSize) {
  const sz = fontSize || 22;
  const parsed = parseInline(text);
  return parsed.map(r => {
    if (r.link) {
      if (r.link.startsWith("#")) {
        // Internal anchor link -> InternalHyperlink to Bookmark
        return new InternalHyperlink({
          anchor: r.link.slice(1),
          children: [new TextRun({ text: r.text, style: "Hyperlink", font: "Arial", size: sz })],
        });
      }
      let link = r.link;
      if (!/^https?:\/\//.test(link) && !/^mailto:/.test(link)) {
        link = decodeURIComponent(link);
      }
      return new ExternalHyperlink({
        children: [new TextRun({ text: r.text, style: "Hyperlink", font: "Arial", size: sz })],
        link,
      });
    }
    const opts = { text: r.text, font: r.code ? "Consolas" : "Arial", size: r.code ? sz - 2 : sz };
    if (r.bold) opts.bold = true;
    if (r.italic) opts.italics = true;
    if (r.code && codeShading) opts.shading = { type: ShadingType.CLEAR, fill: "F0F0F0" };
    return new TextRun(opts);
  });
}

// --- Image helpers ---
function resolveImagePath(src) {
  if (path.isAbsolute(src)) return src;
  // Decode percent-encoding
  const decoded = decodeURIComponent(src);
  return path.resolve(inputDir, decoded);
}

function getImageType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const map = { ".png": "png", ".jpg": "jpg", ".jpeg": "jpeg", ".gif": "gif", ".bmp": "bmp", ".svg": "svg" };
  return map[ext] || "png";
}

function tryLoadImage(src) {
  const filePath = resolveImagePath(src);
  if (!fs.existsSync(filePath)) {
    console.warn(`  Warning: image not found: ${filePath}`);
    return null;
  }
  const data = fs.readFileSync(filePath);
  const type = getImageType(filePath);
  // Get dimensions (simple approach: fit within content width)
  // Default: max 600px wide, auto height (assume 4:3 if unknown)
  let width = 600;
  let height = 450;
  // Try to read PNG/JPEG dimensions from header
  if (type === "png" && data.length >= 24) {
    width = data.readUInt32BE(16);
    height = data.readUInt32BE(20);
  } else if ((type === "jpg" || type === "jpeg") && data.length > 2) {
    // Simple JPEG dimension reader
    let off = 2;
    while (off < data.length - 1) {
      if (data[off] !== 0xFF) break;
      const marker = data[off + 1];
      if (marker === 0xC0 || marker === 0xC2) {
        height = data.readUInt16BE(off + 5);
        width = data.readUInt16BE(off + 7);
        break;
      }
      const segLen = data.readUInt16BE(off + 2);
      off += 2 + segLen;
    }
  }
  // Scale to fit content width (max ~6 inches = 576px at 96dpi)
  const maxWidth = 576;
  if (width > maxWidth) {
    const scale = maxWidth / width;
    width = maxWidth;
    height = Math.round(height * scale);
  }
  return { data, type, width, height };
}

// --- Build document ---
// Документ собирается посекционно: маркер ориентации закрывает текущую секцию
// и открывает новую. Переменная children всегда указывает на секцию, в которую
// сейчас пишем, поэтому весь код ниже работает с ней как раньше.
const docSections = [{ orientation: "portrait", children: [] }];
let children = docSections[0].children;
const headingMap = {
  1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2,
  3: HeadingLevel.HEADING_3, 4: HeadingLevel.HEADING_4,
  5: HeadingLevel.HEADING_5, 6: HeadingLevel.HEADING_6,
};
const border = { style: BorderStyle.SINGLE, size: 1, color: "999999" };
const cellBorders = { top: border, bottom: border, left: border, right: border };
// A4, поля по ГОСТ-обычаю деловых документов: левое 2.5 см, остальные 2.0 см.
const A4_W = 11906;          // 21.0 см
const A4_H = 16838;          // 29.7 см
const M_LEFT = 1418;         // 2.5 см
const M_RIGHT = 1134;        // 2.0 см
const M_TOP = 1134;
const M_BOTTOM = 1134;
const PORTRAIT_CONTENT = A4_W - M_LEFT - M_RIGHT;   // 9354 (16.5 см)
const LANDSCAPE_CONTENT = A4_H - M_LEFT - M_RIGHT;  // 14286 (25.2 см)
// Ширина полосы текущей секции. Меняется маркером <!-- landscape --> в markdown.
let CONTENT_WIDTH = PORTRAIT_CONTENT;

// Ширина колонок таблицы по содержимому, а не поровну.
// Колонка-счетчик ("№ п/п", "№ шага", "Номер версии") получает фиксированную узкую
// ширину, остальные делят остаток пропорционально сглаженной длине содержимого:
// корень гасит выбросы, иначе одна многострочная ячейка забирает почти всю таблицу.
const NUM_COL_WIDTH = 900;   // ~1.6 см, вмещает "№ п/п" и трехзначный номер
const MIN_TEXT_COL = 1200;   // ~2.1 см, чтобы короткая колонка не схлопывалась
const LEN_CAP = 400;         // длиннее уже не влияет на пропорцию

function plainLen(s) {
  return String(s || "").replace(/\*\*|__|`|\[|\]\([^)]*\)/g, "").trim().length;
}

function isCounterColumn(rows, col) {
  const header = String(rows[0] && rows[0][col] || "").trim();
  if (/^№/.test(header) || header === "Номер версии") return true;
  if (header.length > 14) return false;
  let seen = 0;
  for (let r = 1; r < rows.length; r++) {
    const v = String(rows[r][col] || "").trim();
    if (!v) continue;
    if (!/^\d{1,3}$/.test(v)) return false;
    seen++;
  }
  return seen > 0;
}

function computeColumnWidths(rows, numCols) {
  const counter = [];
  const weights = [];
  for (let c = 0; c < numCols; c++) {
    counter[c] = isCounterColumn(rows, c);
    let maxLen = 1;
    for (const row of rows) {
      const l = plainLen(row[c]);
      if (l > maxLen) maxLen = l;
    }
    weights[c] = Math.sqrt(Math.min(maxLen, LEN_CAP));
  }

  const widths = new Array(numCols).fill(0);
  let fixed = 0;
  let weightSum = 0;
  for (let c = 0; c < numCols; c++) {
    if (counter[c]) { widths[c] = NUM_COL_WIDTH; fixed += NUM_COL_WIDTH; }
    else weightSum += weights[c];
  }

  let free = CONTENT_WIDTH - fixed;
  if (weightSum > 0 && free > 0) {
    for (let c = 0; c < numCols; c++) {
      if (counter[c]) continue;
      widths[c] = Math.max(MIN_TEXT_COL, Math.floor(free * weights[c] / weightSum));
    }
  } else {
    // все колонки счетчики либо места не осталось - делим поровну
    const even = Math.floor(CONTENT_WIDTH / numCols);
    widths.fill(even);
  }

  // Снять перебор с самых широких, добор отдать последней колонке.
  let total = widths.reduce((a, b) => a + b, 0);
  let guard = 0;
  while (total > CONTENT_WIDTH && guard++ < 100) {
    let widest = -1;
    for (let c = 0; c < numCols; c++) {
      if (counter[c] || widths[c] <= MIN_TEXT_COL) continue;
      if (widest < 0 || widths[c] > widths[widest]) widest = c;
    }
    if (widest < 0) break;
    const cut = Math.min(total - CONTENT_WIDTH, widths[widest] - MIN_TEXT_COL);
    widths[widest] -= cut;
    total -= cut;
  }
  const diff = CONTENT_WIDTH - widths.reduce((a, b) => a + b, 0);
  if (diff !== 0) {
    let target = numCols - 1;
    for (let c = numCols - 1; c >= 0; c--) {
      if (!counter[c]) { target = c; break; }
    }
    widths[target] += diff;
  }
  return widths;
}

for (const block of blocks) {
  switch (block.type) {
    case "orientation": {
      CONTENT_WIDTH = block.value === "landscape" ? LANDSCAPE_CONTENT : PORTRAIT_CONTENT;
      if (children.length === 0) {
        // секция еще пуста - просто меняем ее ориентацию, лишнюю не плодим
        docSections[docSections.length - 1].orientation = block.value;
      } else {
        const next = { orientation: block.value, children: [] };
        docSections.push(next);
        children = next.children;
      }
      break;
    }

    case "heading": {
      const headingRuns = makeRuns(block.text);
      const headingChildren = block.anchor
        ? [new Bookmark({ id: block.anchor, children: headingRuns })]
        : headingRuns;
      children.push(new Paragraph({
        heading: headingMap[block.level],
        children: headingChildren,
        spacing: { before: block.level <= 2 ? 360 : 240, after: 120 },
      }));
      break;
    }

    case "paragraph":
      children.push(new Paragraph({
        children: makeRuns(block.text),
        spacing: { before: 80, after: 80 },
      }));
      break;

    case "bullet":
      children.push(new Paragraph({
        numbering: { reference: "bullets", level: Math.min(block.indent, 1) },
        children: makeRuns(block.text),
        spacing: { before: 40, after: 40 },
      }));
      break;

    case "numbered":
      children.push(new Paragraph({
        numbering: { reference: "numbers", level: Math.min(block.indent, 1) },
        children: makeRuns(block.text),
        spacing: { before: 40, after: 40 },
      }));
      break;

    case "code": {
      const codeRuns = block.text.split("\n").flatMap((line, idx, arr) => {
        const parts = [new TextRun({ text: line || " ", font: "Consolas", size: 18 })];
        if (idx < arr.length - 1) parts.push(new TextRun({ font: "Consolas", size: 18, break: 1 }));
        return parts;
      });
      children.push(new Paragraph({
        children: codeRuns,
        shading: codeShading ? { type: ShadingType.CLEAR, fill: "F5F5F5" } : undefined,
        spacing: { before: 120, after: 120 },
        indent: { left: 360 },
      }));
      break;
    }

    case "table": {
      const numCols = block.rows[0] ? block.rows[0].length : 1;
      const colWidths = computeColumnWidths(block.rows, numCols);

      const tRows = block.rows.map((cells, rowIdx) =>
        new TableRow({
          children: cells.map((cell, colIdx) => {
            const isHeader = rowIdx === 0;
            return new TableCell({
              borders: cellBorders,
              width: { size: colWidths[colIdx], type: WidthType.DXA },
              shading: isHeader ? { type: ShadingType.CLEAR, fill: "D9E2F3" } : undefined,
              margins: { top: 40, bottom: 40, left: 80, right: 80 },
              children: [new Paragraph({
                children: isHeader
                  ? [new TextRun({ text: cell, bold: true, font: "Arial", size: 20 })]
                  : makeRuns(cell, 20),
                spacing: { before: 20, after: 20 },
              })],
            });
          }),
        })
      );

      children.push(new Table({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        columnWidths: colWidths,
        // Без фиксированной раскладки Word пересчитывает ширины под содержимое
        // и заданные пропорции теряются.
        layout: TableLayoutType.FIXED,
        rows: tRows,
      }));
      break;
    }

    case "image": {
      const img = tryLoadImage(block.src);
      if (img) {
        children.push(new Paragraph({
          children: [new ImageRun({
            type: img.type,
            data: img.data,
            transformation: { width: img.width, height: img.height },
            altText: { title: block.alt || "Image", description: block.alt || "", name: block.alt || "image" },
          })],
          spacing: { before: 120, after: 120 },
          alignment: AlignmentType.CENTER,
        }));
        // Caption if alt text exists
        if (block.alt) {
          children.push(new Paragraph({
            children: [new TextRun({ text: block.alt, font: "Arial", size: 18, italics: true, color: "666666" })],
            alignment: AlignmentType.CENTER,
            spacing: { before: 40, after: 120 },
          }));
        }
      } else {
        // Fallback: show as text placeholder
        children.push(new Paragraph({
          children: [new TextRun({ text: `[Image: ${block.alt || block.src}]`, font: "Arial", size: 20, color: "CC0000" })],
          spacing: { before: 80, after: 80 },
        }));
      }
      break;
    }

    case "hr":
      children.push(new Paragraph({
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC", space: 1 } },
        spacing: { before: 200, after: 200 },
        children: [],
      }));
      break;
  }
}

const doc = new Document({
  creator: author || undefined,
  lastModifiedBy: author || undefined,
  title: docTitle,
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1F3864" },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Arial", color: "2E75B6" },
        paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "404040" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 2 } },
      { id: "Heading4", name: "Heading 4", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "404040" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 3 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "\u2013", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "-", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ] },
      { reference: "numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.DECIMAL, text: "%2.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ] },
    ],
  },
  sections: docSections.map(sec => ({
    properties: {
      page: {
        // width/height задаются как для книжной страницы: при LANDSCAPE
        // библиотека docx меняет их местами сама.
        size: {
          width: A4_W,
          height: A4_H,
          orientation: sec.orientation === "landscape"
            ? PageOrientation.LANDSCAPE
            : PageOrientation.PORTRAIT,
        },
        margin: { top: M_TOP, right: M_RIGHT, bottom: M_BOTTOM, left: M_LEFT },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          children: [new TextRun({ text: docTitle, font: "Arial", size: 18, color: "999999" })],
          alignment: AlignmentType.RIGHT,
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          children: [
            new TextRun({ text: "Стр. ", font: "Arial", size: 18, color: "999999" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "999999" }),
          ],
          alignment: AlignmentType.CENTER,
        })],
      }),
    },
    children: sec.children,
  })),
});

const totalBlocks = docSections.reduce((n, s) => n + s.children.length, 0);

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Created: ${outputPath} (${buffer.length} bytes, ${totalBlocks} blocks, ${docSections.length} sections)`);
}).catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
