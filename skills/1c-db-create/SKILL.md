---
name: 1c-db-create
description: Создание информационной базы 1С. Используй когда пользователь просит создать базу, новую ИБ, пустую базу
argument-hint: <path|name>
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - AskUserQuestion
---

# /db-create — Создание информационной базы

Создаёт новую информационную базу 1С (файловую или серверную) и предлагает зарегистрировать в `.v8-project.json`.

## Usage

```
/db-create <path>                   — файловая база по указанному пути
/db-create <server>/<name>          — серверная база
/db-create                          — интерактивно
```

## Параметры подключения

Прочитай `.v8-project.json` из корня проекта для `v8path` (путь к платформе).
Если `v8path` не задан — автоопределение: `Get-ChildItem "C:\Program Files\1cv8\*\bin\1cv8.exe" | Sort -Desc | Select -First 1`
После создания базы предложи зарегистрировать через `/db-list add`.

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-db-create/scripts/db-create.ps1 <параметры>
```

### Параметры скрипта

| Параметр | Обязательный | Описание |
|----------|:------------:|----------|
| `-V8Path <путь>` | нет | Каталог bin платформы (или полный путь к 1cv8.exe) |
| `-InfoBasePath <путь>` | * | Путь к файловой базе |
| `-InfoBaseServer <сервер>` | * | Сервер 1С (для серверной базы) |
| `-InfoBaseRef <имя>` | * | Имя базы на сервере |
| `-UseTemplate <файл>` | нет | Создать из шаблона (.cf или .dt) |
| `-AddToList` | нет | Добавить в список баз 1С |
| `-ListName <имя>` | нет | Имя базы в списке |
| `-StrictLog` | нет | Отказ в журнале поднимает код возврата до 1, даже если платформа вернула 0 |
| `-AdditionalV8Arguments <список>` | нет | Аргументы платформы через запятую |
| `-AdditionalIbcmdArguments <список>` | нет | Аргументы утилиты администрирования через запятую |

> `*` — нужен либо `-InfoBasePath`, либо пара `-InfoBaseServer` + `-InfoBaseRef`

## Коды возврата

| Код | Описание |
|-----|----------|
| 0 | Успешно |
| 1 | Ошибка (см. лог) |

## После создания

1. Прочитай лог-файл и покажи результат
2. Предложи зарегистрировать базу в `.v8-project.json` (через `/db-list add`)
3. Если указан шаблон `/UseTemplate` — предупреди что конфигурация будет загружена из шаблона

## Примеры

```powershell
# Создать файловую базу
powershell.exe -NoProfile -File skills/1c-db-create/scripts/db-create.ps1 -InfoBasePath "C:\Bases\NewDB"

# Создать серверную базу
powershell.exe -NoProfile -File skills/1c-db-create/scripts/db-create.ps1 -InfoBaseServer "srv01" -InfoBaseRef "MyApp_Test"

# Создать из шаблона CF
powershell.exe -NoProfile -File skills/1c-db-create/scripts/db-create.ps1 -InfoBasePath "C:\Bases\NewDB" -UseTemplate "C:\Templates\config.cf"

# Создать и добавить в список баз
powershell.exe -NoProfile -File skills/1c-db-create/scripts/db-create.ps1 -InfoBasePath "C:\Bases\NewDB" -AddToList -ListName "Новая база"
```

## Дополнительные аргументы платформы

Аргумент, которого нет среди параметров навыка, передается ключом `-AdditionalV8Arguments`
списком через запятую: `-AdditionalV8Arguments "/UseHwLicenses+,/ClearCache"`. Разделитель
запятая, а не пробел, потому что значение аргумента платформы само содержит пробелы.

Постоянный набор задается в `.v8-project.json` рядом с проектом:

```json
{
  "v8args": ["/UseHwLicenses+"],
  "ibcmdargs": ["--verbose"]
}
```

Файл ищется вверх по дереву от целевого каталога. Аргументы вызова заменяют значение из
настроек целиком, а не дополняют его: иначе снять заданный в проекте аргумент было бы нечем.

### Утилита администрирования

Если `-V8Path` указывает на `ibcmd`, команда собирается по правилам утилиты администрирования:
`infobase create --db-path=...`. Ключи платформы (`/Out`, `/DumpResult`,
`/DisableStartupDialogs`) она не понимает, поэтому вердикт опирается на код возврата и
постусловие. Дополнительные аргументы для нее задаются ключом `-AdditionalIbcmdArguments` или
`ibcmdargs` в настройках проекта.

Навык отказывается работать, а не молчит, в двух случаях: `-AdditionalV8Arguments` при
выбранном `ibcmd` (аргумент относится к другому движку) и позиционный токен без дефиса в
`-AdditionalIbcmdArguments` (он встал бы в строку как часть команды и сменил бы ее смысл).

## Вывод платформы

Потоки процесса перехватываются в файлы и печатаются под заголовком `--- Вывод платформы ---`.
Кодировка определяется по содержимому: платформа пишет в кодировке консоли (866 на русской
Windows), утилита администрирования и часть сборок - в UTF-8. Вывод показывается и при
успешном завершении: платформа сообщает предупреждения, не меняя код возврата.
