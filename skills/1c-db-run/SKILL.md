---
name: 1c-db-run
description: Запуск 1С:Предприятие. Используй когда пользователь просит запустить 1С, открыть базу, запустить предприятие
argument-hint: "[database]"
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /db-run - Запуск 1С:Предприятие

Запускает информационную базу в режиме 1С:Предприятие (пользовательский режим).

## Usage

```
/db-run [database]
/db-run dev
/db-run dev /Execute process.epf
/db-run dev /C "параметр запуска"
```

## Параметры подключения

Прочитай `.v8-project.json` из корня проекта. Возьми `v8path` (путь к платформе) и разреши базу:
1. Если пользователь указал параметры подключения (путь, сервер) - используй напрямую
2. Если указал базу по имени - ищи по id / alias / name в `.v8-project.json`
3. Если не указал - сопоставь текущую ветку Git с `databases[].branches`
4. Если ветка не совпала - используй `default`
Если `v8path` не задан - автоопределение: `Get-ChildItem "C:\Program Files\1cv8\*\bin\1cv8.exe" | Sort -Desc | Select -First 1`
Если файла нет - предложи `/db-list add`.
Если использованная база не зарегистрирована - после выполнения предложи добавить через `/db-list add`.

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-db-run/scripts/db-run.ps1 <параметры>
```

### Параметры скрипта

| Параметр | Обязательный | Описание |
|----------|:------------:|----------|
| `-V8Path <путь>` | нет | Каталог bin платформы (или полный путь к 1cv8.exe) |
| `-InfoBasePath <путь>` | * | Файловая база |
| `-InfoBaseServer <сервер>` | * | Сервер 1С (для серверной базы) |
| `-InfoBaseRef <имя>` | * | Имя базы на сервере |
| `-UserName <имя>` | нет | Имя пользователя |
| `-Password <пароль>` | нет | Пароль |
| `-Execute <файл.epf>` | нет | Запуск внешней обработки сразу после старта |
| `-CParam <строка>` | нет | Параметр запуска (/C) |
| `-URL <ссылка>` | нет | Навигационная ссылка (формат `e1cib/...`) |
| `-AdditionalV8Arguments <список>` | нет | Аргументы платформы через запятую |
| `-StartupCheckSeconds <N>` | нет | Длина контрольного окна после запуска, по умолчанию 3 |

> `*` - нужен либо `-InfoBasePath`, либо пара `-InfoBaseServer` + `-InfoBaseRef`

## Важно

Скрипт запускает 1С в фоне (`Start-Process` без `-Wait`) - управление возвращается сразу.

## Примеры

```powershell
# Простой запуск
powershell.exe -NoProfile -File skills/1c-db-run/scripts/db-run.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin"

# Запуск с обработкой
powershell.exe -NoProfile -File skills/1c-db-run/scripts/db-run.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -Execute "C:\epf\МояОбработка.epf"

# Открыть по навигационной ссылке
powershell.exe -NoProfile -File skills/1c-db-run/scripts/db-run.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -URL "e1cib/data/Справочник.Номенклатура"

# Серверная база с параметром запуска
powershell.exe -NoProfile -File skills/1c-db-run/scripts/db-run.ps1 -InfoBaseServer "srv01" -InfoBaseRef "MyDB" -UserName "Admin" -Password "secret" -CParam "ЗапуститьОбновление"
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

## Контроль запуска

Режим предприятия запускается без ожидания завершения, поэтому навык выдерживает контрольное
окно и проверяет, что процесс жив. Ожидание прерывается, как только процесс завершился, поэтому
полный интервал ждет только успешный запуск; на загруженной машине его увеличивают ключом
`-StartupCheckSeconds`. Платформа с отвергнутыми параметрами завершается почти
сразу - в этом случае навык возвращает ошибку, а не сообщение о запуске.
