---
name: 1c-db-load-git
description: Загрузка изменений из Git в базу 1С. Используй когда пользователь просит загрузить изменения из гита, обновить базу из репозитория, partial load из коммита
argument-hint: "[database] [source]"
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /db-load-git — Загрузка изменений из Git

Определяет изменённые файлы конфигурации по данным Git и выполняет частичную загрузку в информационную базу.

## Usage

```
/db-load-git [database]
/db-load-git dev                              — все незафиксированные изменения
/db-load-git dev -Source Staged               — только staged
/db-load-git dev -Source Commit -CommitRange "HEAD~3..HEAD"
/db-load-git dev -DryRun                      — только показать что будет загружено
```

## Параметры подключения

Прочитай `.v8-project.json` из корня проекта. Возьми `v8path` (путь к платформе) и разреши базу:
1. Если пользователь указал параметры подключения (путь, сервер) — используй напрямую
2. Если указал базу по имени — ищи по id / alias / name в `.v8-project.json`
3. Если не указал — сопоставь текущую ветку Git с `databases[].branches`
4. Если ветка не совпала — используй `default`
Если `v8path` не задан — автоопределение: `Get-ChildItem "C:\Program Files\1cv8\*\bin\1cv8.exe" | Sort -Desc | Select -First 1`
Если файла нет — предложи `/db-list add`.
Если использованная база не зарегистрирована — после выполнения предложи добавить через `/db-list add`.
Если в записи базы указан `configSrc` — используй как каталог конфигурации.

Спецификация пакетного режима: `docs/build-spec.md`

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 <параметры>
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
| `-ConfigDir <путь>` | да | Каталог XML-выгрузки (git-репозиторий) |
| `-Source <источник>` | нет | `All` (по умолч.) / `Staged` / `Unstaged` / `Commit` |
| `-CommitRange <range>` | для Commit | Диапазон коммитов (напр. `HEAD~3..HEAD`) |
| `-Extension <имя>` | нет | Загрузить в расширение |
| `-AllExtensions` | нет | Загрузить все расширения |
| `-Format <формат>` | нет | `Hierarchical` (по умолч.) / `Plain` |
| `-DryRun` | нет | Только показать что будет загружено (без загрузки) |

> `*` — нужен либо `-InfoBasePath`, либо пара `-InfoBaseServer` + `-InfoBaseRef`

### Источники изменений

| Source | Описание |
|--------|----------|
| `All` | Все незафиксированные: staged + unstaged + untracked |
| `Staged` | Только проиндексированные (git add) |
| `Unstaged` | Изменённые но не проиндексированные + новые (untracked) файлы |
| `Commit` | Файлы из диапазона коммитов (требует `-CommitRange`) |

### Автоматический маппинг файлов

Для каждого изменённого файла (`.xml`, `.bsl`, `.mxl`) скрипт автоматически определяет связанные файлы для загрузки. Логика зависит от позиции сегмента `Ext/` в пути.

**Модуль объекта** (`Type/Name/Ext/ObjectModule.bsl` — `Ext` на позиции 2):
- Корневой XML: `Type/Name.xml`
- Все файлы из `Type/Name/Ext/*`

Пример: изменён `Catalogs/Номенклатура/Ext/ObjectModule.bsl` → загружаются `Catalogs/Номенклатура.xml` + всё из `Catalogs/Номенклатура/Ext/`

**Модуль формы / макет** (`Type/Name/SubType/SubName/Ext/...` — `Ext` на позиции 4+):
- Корневой XML: `Type/Name.xml`
- Дескриптор подобъекта: `Type/Name/SubType/SubName.xml`
- Все файлы из `Type/Name/SubType/SubName/Ext/*`

Примеры:
- Изменён `Catalogs/Номенклатура/Forms/ФормаЭлемента/Ext/Form.xml` → загружаются `Catalogs/Номенклатура.xml` + `Catalogs/Номенклатура/Forms/ФормаЭлемента.xml` + всё из `.../ФормаЭлемента/Ext/`
- Изменён `DataProcessors/МояОбработка/Templates/Макет/Ext/Template.mxl` → загружаются `DataProcessors/МояОбработка.xml` + `DataProcessors/МояОбработка/Templates/Макет.xml` + всё из `.../Макет/Ext/`

**XML-дескриптор объекта** (без `Ext/` в пути, напр. `Type/Name.xml`):
- Сам файл
- Все файлы из `Type/Name/Ext/*` (если каталог существует)

Пример: изменён `Catalogs/Номенклатура.xml` → загружаются `Catalogs/Номенклатура.xml` + всё из `Catalogs/Номенклатура/Ext/`

**Дедупликация** — через `HashSet` (case-insensitive). Если несколько изменённых файлов ссылаются на одни и те же связанные файлы, дубликаты в listFile не попадают.

**Пропускаются:** `ConfigDumpInfo.xml`, файлы с расширениями отличными от `.xml`/`.bsl`/`.mxl`, файлы вне `ConfigDir`.

## Коды возврата

| Код | Описание |
|-----|----------|
| 0 | Успешно (или нет изменений) |
| 1 | Ошибка (см. лог) |

## После выполнения

1. Показать список загруженных файлов
2. **Предложить `/db-update`** — для применения изменений к БД

## Примеры

```powershell
# Загрузить все незафиксированные изменения (файловая база)
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 -V8Path "C:\Program Files\1cv8\8.3.25.1257\bin" -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Source All

# Только staged
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Source Staged

# Серверная база
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 -InfoBaseServer "srv01" -InfoBaseRef "MyApp_Dev" -UserName "Admin" -Password "secret" -ConfigDir "C:\WS\cfsrc" -Source All

# Из диапазона коммитов
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Source Commit -CommitRange "HEAD~3..HEAD"

# Только посмотреть (DryRun)
powershell.exe -NoProfile -File skills/1c-db-load-git/scripts/db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -ConfigDir "C:\WS\cfsrc" -DryRun
```
