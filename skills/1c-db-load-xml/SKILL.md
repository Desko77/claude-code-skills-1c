---
name: 1c-db-load-xml
description: Загрузка конфигурации 1С из XML-файлов. Используй когда пользователь просит загрузить конфигурацию из файлов, XML, исходников, LoadConfigFromFiles
argument-hint: <configDir> [database]
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /db-load-xml — Загрузка конфигурации из XML

Загружает конфигурацию в информационную базу из XML-файлов (исходников). Поддерживает полную и частичную загрузку.

> **EDT MCP**: Если проект открыт в EDT и доступен EDT MCP-сервер - этот скил не нужен. EDT работает напрямую с XML-исходниками, а для обновления БД используй `update_database` через MCP. Используй этот скил только если пользователь явно просит загрузку через конфигуратор.

## Usage

```
/db-load-xml <configDir> [database]
/db-load-xml src/config dev
/db-load-xml src/config dev -Mode Partial -Files "Catalogs/Номенклатура.xml,Catalogs/Номенклатура/Ext/ObjectModule.bsl"
```

> **Внимание**: полная загрузка **заменяет всю конфигурацию** в базе. Перед выполнением запроси подтверждение у пользователя.

## Параметры подключения

Прочитай `.v8-project.json` из корня проекта. Возьми `v8path` (путь к платформе) и разреши базу:
1. Если пользователь указал параметры подключения (путь, сервер) — используй напрямую
2. Если указал базу по имени — ищи по id / alias / name в `.v8-project.json`
3. Если не указал — сопоставь текущую ветку Git с `databases[].branches`
4. Если ветка не совпала — используй `default`
Если `v8path` не задан — автоопределение: `Get-ChildItem "C:\Program Files\1cv8\*\bin\1cv8.exe" | Sort -Desc | Select -First 1`
Если файла нет — предложи `/db-list add`.
Если использованная база не зарегистрирована — после выполнения предложи добавить через `/db-list add`.
Если в записи базы указан `configSrc` — используй как каталог загрузки по умолчанию.

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-db-load-xml/scripts/db-load-xml.ps1 <параметры>
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
| `-ConfigDir <путь>` | да | Каталог XML-исходников |
| `-Mode <режим>` | нет | `Full` (по умолч.) / `Partial` |
| `-Files <список>` | для Partial | Относительные пути файлов через запятую |
| `-ListFile <путь>` | для Partial | Путь к файлу со списком (альтернатива `-Files`) |
| `-Extension <имя>` | нет | Загрузить в расширение |
| `-AllExtensions` | нет | Загрузить все расширения |
| `-Format <формат>` | нет | `Hierarchical` (по умолч.) / `Plain` |
| `-UpdateDB` | нет | После загрузки сразу обновить конфигурацию БД (`/UpdateDBCfg`) |

> `*` — нужен либо `-InfoBasePath`, либо пара `-InfoBaseServer` + `-InfoBaseRef`

### Режимы загрузки

| Режим | Описание |
|-------|----------|
| `Full` | Полная загрузка — замена всей конфигурации из каталога XML |
| `Partial` | Частичная — загрузка выбранных файлов (с `-partial -updateConfigDumpInfo`) |

### Формат файла списка (listFile)

Файл содержит **относительные пути к файлам** в каталоге выгрузки (один на строку), кодировка **UTF-8 с BOM**:

```
Catalogs/Номенклатура.xml
Catalogs/Номенклатура/Ext/ObjectModule.bsl
Documents/Заказ.xml
Documents/Заказ/Forms/ФормаДокумента.xml
```

## Коды возврата

| Код | Описание |
|-----|----------|
| 0 | Успешно |
| 1 | Ошибка (см. лог) |

## После выполнения

1. Прочитай лог и покажи результат
2. Если `-UpdateDB` не был указан — **предложи выполнить `/db-update`** для применения изменений к БД

## Примеры

```powershell
# Полная загрузка
powershell.exe -NoProfile -File skills/1c-db-load-xml/scripts/db-load-xml.ps1 -V8Path "C:\Program Files\1cv8\8.3.25.1257\bin" -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Mode Full

# Частичная загрузка конкретных файлов
powershell.exe -NoProfile -File skills/1c-db-load-xml/scripts/db-load-xml.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Mode Partial -Files "Catalogs/Номенклатура.xml,Catalogs/Номенклатура/Ext/ObjectModule.bsl"

# Загрузка расширения
powershell.exe -NoProfile -File skills/1c-db-load-xml/scripts/db-load-xml.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\ext_src" -Mode Full -Extension "МоёРасширение"

# Загрузка + обновление БД в одном запуске
powershell.exe -NoProfile -File skills/1c-db-load-xml/scripts/db-load-xml.ps1 -InfoBasePath "C:\Bases\MyDB" -UserName "Admin" -ConfigDir "C:\WS\cfsrc" -Mode Full -UpdateDB
```

## Troubleshooting загрузки расширений

### Загрузка виснет на 60+ секунд, /Out пустой, без ошибки

**Причина: блок прав на новый Enum в `Roles/<Role>/Ext/Rights.xml`.**

EDT при выгрузке роли в XML может включить в Rights.xml блок:
```xml
<object>
    <name>Enum.<НовоеПеречисление></name>
    <right><name>Read</name><value>true</value></right>
    <right><name>View</name><value>true</value></right>
</object>
```

Платформа 8.3.27 (DESIGNER) виснет на резолве этих прав при `LoadConfigFromFiles -Extension`. Обходной путь — удалить блок из `Rights.xml` перед загрузкой:

```powershell
# Pre-flight check: найти права на Enum в ролях расширения
Get-ChildItem -Path "$ConfigDir\Roles" -Recurse -Filter "Rights.xml" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    if ($content -match '<name>Enum\.[^<]+</name>') {
        Write-Warning "Найдены права на Enum в $($_.FullName) — могут вызвать зависание загрузки"
    }
}
```

После удаления — перевыгрузить роль в EDT (снять права на Enum) или отредактировать Rights.xml перед каждой загрузкой.

### Сборка диагностики при зависании

1. Прибить процесс: `Get-Process -Name '1cv8' | Stop-Process -Force`
2. Удалить лок: `Remove-Item "<DbPath>\1Cv8.cfl" -Force`
3. Включить технологический журнал и повторить — см. `logcfg.xml` в `C:\Program Files\1cv8\conf\`
4. Если /Out пустой 60+ сек — почти наверняка проблема в Rights.xml ролей или в кросс-ссылках между новыми объектами

### Двухпроходная загрузка (для проблемных расширений)

Если расширение добавляет новые объекты + роль с правами на них:

```powershell
# Проход 1: всё кроме роли (или с минимальной ролью)
db-load-xml.ps1 -ConfigDir <path-without-role> -Extension <name> -UpdateDB

# Проход 2: полная выгрузка с ролью (объекты уже в БД-схеме)
db-load-xml.ps1 -ConfigDir <full-path> -Extension <name> -UpdateDB
```
