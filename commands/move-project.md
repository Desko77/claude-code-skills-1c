Перенеси проект в другую папку, сохранив память, сессии и планы Claude Code.

## Аргумент $ARGUMENTS

Пользователь передаёт:
- Путь к проекту-источнику (откуда)
- Путь назначения (куда)
- Или пустую строку — тогда спроси оба пути

Пример: `/move-project C:\Projects\my-app D:\Work\my-app`

## Выполнение

### 1. Подготовка

Проверь что источник существует, назначение свободно. Если назначение уже существует — спроси пользователя.

### 2. Перемещение файлов проекта

```bash
mv "<source>" "<target>"
```

Если `mv` не работает (Device or resource busy) — скопируй через PowerShell:
```bash
powershell -Command "Copy-Item -Path '<source>' -Destination '<target>' -Recurse -Force"
```
Потом попроси пользователя закрыть всё что держит папку и удали оригинал.

### 3. Определение папки памяти Claude Code

**ВАЖНО:** Claude Code нормализует путь проекта в имя папки `~/.claude/projects/`:
- Разделители (`\`, `/`, `:`) → дефис `-`
- **Подчёркивание (`_`) → дефис (`-`)**

Пример: `C:\My Projects\Sub_folder\my-app` → `C--My-Projects-Sub-folder-my-app`

Алгоритм:
1. Открой Claude Code в новом расположении (или попроси пользователя открыть)
2. Посмотри какую папку Claude Code реально создал:
   ```bash
   ls ~/.claude/projects/ | grep <имя-проекта>
   ```
3. Используй **ту папку, которую создал Claude Code** — НЕ конструируй имя вручную

### 4. Перенос памяти

Из **всех** старых папок проекта в `~/.claude/projects/` (может быть несколько вариантов):

```bash
OLD="~/.claude/projects/<old-project-folder>"
NEW="~/.claude/projects/<new-project-folder>"

# Память
cp "$OLD/memory/"* "$NEW/memory/"

# Сессии (.jsonl файлы)
cp "$OLD/"*.jsonl "$NEW/"

# Папки сессий (UUID-папки)
for d in "$OLD/"*/; do
  dirname=$(basename "$d")
  [ "$dirname" != "memory" ] && cp -r "$d" "$NEW/$dirname"
done
```

### 5. Планы

Планы хранятся в `~/.claude/plans/<имя-проекта>/` где имя = последний каталог пути. Если имя каталога проекта не изменилось — планы остаются на месте, ничего делать не нужно.

Если имя изменилось:
```bash
mv ~/.claude/plans/<old-name> ~/.claude/plans/<new-name>
```

### 6. Проверка

```bash
# Сравнить количество .jsonl файлов
echo "OLD:" && ls "$OLD/"*.jsonl 2>/dev/null | wc -l
echo "NEW:" && ls "$NEW/"*.jsonl 2>/dev/null | wc -l

# Проверить память
ls "$NEW/memory/"
```

### 7. Завершение

- Попроси пользователя **перезапустить Claude Code** в новом расположении — кэш пустого состояния не обновляется на лету
- После проверки что всё работает — предложи удалить старые папки из `~/.claude/projects/`
