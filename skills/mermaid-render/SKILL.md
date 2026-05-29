---
name: mermaid-render
description: "Рендерит mermaid-диаграммы в PNG/SVG/PDF через локальный mermaid-cli (mmdc). Используй когда пользователь просит отрендерить mermaid, сделать PNG из диаграммы, превратить mermaid в картинку, конвертировать .mmd в png/svg/pdf, извлечь mermaid из markdown в картинки, сохранить блок mermaid как изображение, нарисовать диаграмму. Принимает .mmd / .mermaid (одна диаграмма) или .md (рендерит каждый блок ```mermaid в отдельную картинку). Поддерживает темы (default/forest/dark/neutral), цвет фона и масштаб для retina. Без Docker и MCP - чистый локальный mmdc."
argument-hint: "<входной_файл> [-o OUTPUT] [-t THEME] [-b BG] [-f png|svg|pdf] [-s SCALE]"
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /mermaid-render - Рендер mermaid-диаграмм в изображения

Тонкая обёртка над `mmdc` (mermaid-cli). Внутри Puppeteer + Chrome headless + mermaid.js, как в peng-shawn/mermaid-mcp-server, но без MCP-сервера и без Docker.

## Зависимости

- `mmdc` (`@mermaid-js/mermaid-cli`) - проверь: `mmdc --version`. Если нет - `npm install -g @mermaid-js/mermaid-cli`.
- Python 3 в PATH (для скрипта-обёртки).

## Использование

```bash
python ~/.claude/skills/mermaid-render/scripts/render.py <вход> [опции]
```

### Сценарии входа

| Расширение | Поведение |
|-----------|-----------|
| `.mmd` / `.mermaid` | Один файл с диаграммой -> одна картинка |
| `.md` / `.markdown` | Извлекает все блоки ` ```mermaid ` -> по картинке на блок (`<имя>-1.png`, `<имя>-2.png`, ...) |

### Опции

| Флаг | По умолчанию | Назначение |
|------|--------------|-----------|
| `-o, --output` | рядом с входом | Выходной файл (для .md - префикс перед `-N.<ext>`) |
| `-t, --theme` | `default` | `default` / `forest` / `dark` / `neutral` |
| `-b, --bg` | `white` | `white`, `transparent`, `#F0F0F0` |
| `-f, --format` | `png` | `png` / `svg` / `pdf` |
| `-w, --width` | mmdc default 800 | Ширина в пикселях |
| `-H, --height` | mmdc default 600 | Высота в пикселях |
| `-s, --scale` | `2` | Puppeteer scale - 2 для retina |
| `--verbose` | выкл | Показать вывод mmdc |

## Примеры

```bash
# Простой PNG рядом с входом, дефолтная тема, scale=2
python ~/.claude/skills/mermaid-render/scripts/render.py ./diagram.mmd

# Тёмная тема, прозрачный фон, SVG
python ~/.claude/skills/mermaid-render/scripts/render.py ./diagram.mmd -t dark -b transparent -f svg

# Все блоки mermaid из markdown в PNG-файлы
python ~/.claude/skills/mermaid-render/scripts/render.py ./README.md

# Указать выходной путь
python ~/.claude/skills/mermaid-render/scripts/render.py ./d.mmd -o ./out/result.png
```

## Алгоритм работы для Claude

1. Уточни у пользователя входной файл, если не передан явно. Поддерживаются `.mmd`, `.mermaid`, `.md`.
2. Если пользователь не указал параметры рендера - используй дефолты (PNG, default-тема, белый фон, scale=2).
3. Запусти скрипт через Bash:
   ```bash
   python ~/.claude/skills/mermaid-render/scripts/render.py "<путь>" [-t ...] [-b ...] [-f ...]
   ```
4. Скрипт печатает список созданных файлов с размерами - покажи пользователю.
5. Если пользователь хочет встроить картинки в Markdown/Word - после рендера используй существующие скилы (`md-to-docx` для Word, обычные `![]()` ссылки для Markdown).

## Поведение при ошибках

- mmdc не найден - скрипт выйдет с кодом 2 и подскажет команду установки.
- Входной файл не найден или неподдерживаемое расширение - код 2 с понятным сообщением.
- mmdc вернул ошибку (синтаксис mermaid) - код мммдц проброшен, stderr показан.
- В .md нет блоков ```mermaid - код 1, предупреждение пользователю.

## Связь с другими скилами

- `mermaid-diagrams` - руководство как СОСТАВЛЯТЬ читаемые mermaid-диаграммы. Этот скилл делает шаг рендера ПОСЛЕ составления.
- `md-to-visio` - конвертация mermaid из markdown в нативный Visio (.vsdx). Использовать когда нужен редактируемый чертеж, а не растровая картинка.
- `md-to-docx` - подключение результирующих PNG к Word-документу.
