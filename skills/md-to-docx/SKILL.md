---
name: md-to-docx
description: "Конвертируй Markdown-файл в DOCX. Используй когда пользователь просит конвертировать, преобразовать .md в .docx, сделать Word из Markdown"
argument-hint: "<input.md> [output.docx]"
allowed-tools:
  - Bash
  - Read
---

# /md-to-docx — конвертация Markdown в DOCX

Конвертирует Markdown-файл в Word-документ (.docx) с форматированием.

## Использование

```
/md-to-docx <input.md> [output.docx]
```

| Параметр | Обязательный | Описание |
|----------|:------------:|----------|
| `input.md` | Да | Путь к исходному Markdown-файлу |
| `output.docx` | Нет | Путь к выходному файлу (по умолчанию: рядом с исходным, .md → .docx) |

Если путь не указан — спроси у пользователя.

## Зависимости

- **Node.js** — для выполнения скрипта
- **npm-пакет `docx`** — установить глобально: `npm install -g docx`

## Команда

```bash
# Определить путь к глобальным node_modules
NODE_MODULES=$(npm root -g)

# Запустить конвертацию
NODE_PATH="$NODE_MODULES" node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]"
```

На Windows (PowerShell):
```powershell
$env:NODE_PATH = (npm root -g)
node skills/md-to-docx/scripts/md_to_docx.js "<input.md>" "[output.docx]"
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
