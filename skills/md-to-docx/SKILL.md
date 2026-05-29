---
name: md-to-docx
description: "Конвертируй Markdown-файл в DOCX. Используй когда пользователь просит конвертировать, преобразовать .md в .docx, сделать Word из Markdown"
argument-hint: "<input.md> [output.docx] [--author \"Имя\"] [--title \"Заголовок\"] [--no-shading]"
allowed-tools:
  - Bash
  - Read
---

# /md-to-docx — конвертация Markdown в DOCX

Конвертирует Markdown-файл в Word-документ (.docx) с форматированием.

## Использование

```
/md-to-docx <input.md> [output.docx] [--author "Имя Фамилия"] [--title "Заголовок"] [--no-shading]
```

| Параметр | Обязательный | Описание |
|----------|:------------:|----------|
| `input.md` | Да | Путь к исходному Markdown-файлу |
| `output.docx` | Нет | Путь к выходному файлу (по умолчанию: рядом с исходным, .md → .docx) |
| `--author` | Нет | Автор документа. Записывается в core properties (`dc:creator` + `cp:lastModifiedBy`). Поддерживается форма `--author=Имя` |
| `--title` | Нет | Заголовок документа в core properties и в верхнем колонтитуле. По умолчанию — имя входного файла без расширения |
| `--no-shading` | Нет | Отключает серый фон у inline-кода (`код`) и у блоков ``` code ``` . Эквивалент: `--shading=off`. По умолчанию фон включён. На шапку таблиц не влияет — она остаётся со структурным фоном |

Если путь не указан — спроси у пользователя. Флаги `--author`, `--title`, `--no-shading` опциональны — пиши их только когда пользователь явно попросил указать автора, собственный заголовок или убрать серый фон выделения кода.

## Зависимости

- **Node.js** — для выполнения скрипта
- **npm-пакет `docx`** — установить глобально: `npm install -g docx`

## Команда

```bash
# Определить путь к глобальным node_modules
NODE_MODULES=$(npm root -g)

# Базовый запуск
NODE_PATH="$NODE_MODULES" node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]"

# С автором и заголовком
NODE_PATH="$NODE_MODULES" node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]" --author "Иванов И. И." --title "Аналитическая записка"

# Без серого фона у кода
NODE_PATH="$NODE_MODULES" node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]" --no-shading
```

На Windows (PowerShell):
```powershell
$env:NODE_PATH = (npm root -g)
node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]" --author "Иванов И. И." --no-shading
```

## Что поддерживается

- Заголовки (H1–H6) со стилями и цветами
- Таблицы с заголовочной строкой
- Блоки кода (моноширинный шрифт, серый фон)
- Списки: маркированные и нумерованные (с вложенностью)
- Инлайн-форматирование: **жирный**, *курсив*, `код`, [гиперссылки](url)
- Картинки (`![alt](path)`) — ищутся относительно папки MD-файла
- Горизонтальные разделители (`---`)
- Колонтитулы: имя файла в верхнем, номер страницы в нижнем

Если картинка не найдена — вставляется текстовый placeholder красного цвета.

## Пример вывода

```
Created: output.docx (45231 bytes, 42 blocks)
```
