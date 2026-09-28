---
name: 1c-db-cfe-admin
description: "Управление расширениями в базе 1С через ibcmd: список, проверка применимости, безопасный режим, активность, удаление. Используй когда EDT нет и нужно включить или выключить расширение, снять безопасный режим либо удалить расширение из базы. Не используй, если EDT открыта (infobase_admin AI-EDT) или нужна сборка .cfe (скилы 1c-cfe-*)."
argument-hint: "list|check|set-properties|delete"
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /db-cfe-admin - Расширения в информационной базе

Управляет расширениями, которые уже лежат в информационной базе: список, проверка,
свойства, удаление. Движок один - `ibcmd`. Конфигуратор и EDT не вызываются.

## Когда применять

- EDT недоступна, а расширение в базе надо включить, выключить, снять с безопасного режима
  или удалить.
- Нужно увидеть, какие расширения есть в базе, и проверить, применимо ли названное расширение.

## Когда не применять

- Проект открыт в EDT и доступен AI-EDT. Свойства расширения в базе меняет `infobase_admin`.
- Нужно создать исходники расширения, заимствовать объект или собрать файл `.cfe`.
  Это скилы `1c-cfe-*`.
- Нужно загрузить `.cfe` или XML в базу. Это `/db-load-cf` и `/db-load-xml`.

## Параметры подключения

Прочитай `.v8-project.json` из корня проекта. Возьми `v8path` (каталог `bin` или путь к
`ibcmd.exe`) и разреши базу:

1. Если пользователь указал параметры подключения (путь, сервер) - используй напрямую
2. Если указал базу по имени - ищи по id / alias / name в `.v8-project.json`
3. Если не указал - сопоставь текущую ветку Git с `databases[].branches`
4. Если ветка не совпала - используй `default`

Если `v8path` не задан - автоопределение: `Get-ChildItem "C:\Program Files\1cv8\*\bin\ibcmd.exe" | Sort FullName | Select -Last 1`
Если файла нет - попроси путь к `ibcmd.exe` в `-V8Path`.
Если использованная база не зарегистрирована - после выполнения предложи добавить через `/db-list add`.

`ibcmd` не ходит в кластер 1С. Файловая база передается ключом `--db-path` (`-InfoBasePath`).
Пара `-InfoBaseServer` и `-InfoBaseRef` передается как `--db-server` и `--db-name`: сервер и имя
базы СУБД, как в справке `ibcmd`. Тип СУБД - `-Dbms` (`--dbms`). Без `-Dbms` утилита считает базу
файловой. Если заданы и путь, и пара сервер/имя, в команду попадает пара: так же цель выбирает
защита боевой базы.

База с ролью `prod` в `.v8-project.json` отказывает операциям `set-properties` и `delete`:
скрипт завершается кодом 1, пока не передан `-AllowProd`. Операции `list` и `check` защиту не
проходят: они базу не меняют.

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 <операция> <параметры>
```

Порт Python: `skills/1c-db-cfe-admin/scripts/db-cfe-admin.py`. Имена параметров те же.
`-WhatIf` и `--dry-run` печатают команду `ibcmd` и не запускают ее.

### Операции

| Операция | Команда ibcmd | Что делает |
|----------|---------------|------------|
| `list` | `infobase config extension list` | Список расширений базы |
| `check` | `infobase config check --extension=<имя>` | Проверка конфигурации расширения в этой базе |
| `set-properties` | `infobase config extension update` | Свойства расширения |
| `delete` | `infobase config extension delete` | Удаление одного расширения или всех (`-All`) |

`check` соответствует команде `infobase config check` из справки `ibcmd`: проверка конфигурации
названного расширения. Ключ `-Name` обязателен.

### Параметры скрипта

| Параметр | Обязательный | Описание |
|----------|:------------:|----------|
| `Operation` | да | `list`, `check`, `set-properties`, `delete` |
| `-V8Path <путь>` | нет | Каталог bin, `ibcmd.exe` или `1cv8.exe` (тогда берется `ibcmd.exe` рядом) |
| `-InfoBasePath <путь>` | * | Файловая база, ключ `--db-path` |
| `-InfoBaseServer <сервер>` | * | Сервер СУБД, ключ `--db-server` |
| `-InfoBaseRef <имя>` | * | Имя базы СУБД, ключ `--db-name` |
| `-Dbms <тип>` | нет | `MSSQLServer`, `PostgreSQL`, `IBMDB2`, `OracleDatabase` |
| `-DataPath <путь>` | нет | Каталог данных автономного сервера, ключ `--data` |
| `-UserName <имя>` | нет | Пользователь информационной базы, ключ `--user` |
| `-Password <пароль>` | нет | Пароль, ключ `--password`. В печатной команде значение заменено на `***` |
| `-AllowProd` | нет | Разрешить `set-properties` и `delete` на базе с `role: prod` |
| `-WhatIf` | нет | Напечатать команду `ibcmd` и выйти с кодом 0. В Python то же делает `--dry-run` |
| `-Name <имя>` | ** | Имя расширения |
| `-All` | нет | Удалить все расширения. Только с `delete`, вместе с `-Name` не задается |

> `*` - нужен либо `-InfoBasePath`, либо пара `-InfoBaseServer` + `-InfoBaseRef`
>
> `**` - обязателен для `check`, `set-properties` и `delete` без `-All`

### Свойства set-properties

Хотя бы одно свойство обязательно. Значения `yes` и `no` - как в справке `ibcmd`.

| Параметр | Ключ ibcmd | Значение |
|----------|------------|----------|
| `-Active` | `--active` | `yes` или `no` |
| `-SafeMode` | `--safe-mode` | `yes` или `no` |
| `-SecurityProfileName` | `--security-profile-name` | Имя профиля безопасности. В справке у ключа написано `yes\|no`, описание ключа - имя профиля. Скрипт передает строку как есть. На ibcmd 8.3.27.1989 строка с именем принимается; в том же запуске безопасный режим становится `yes`, даже если `--safe-mode` не передавался |
| `-UnsafeActionProtection` | `--unsafe-action-protection` | `yes` или `no` |
| `-UsedInDistributedInfobase` | `--used-in-distributed-infobase` | `yes` или `no` |
| `-Scope` | `--scope` | `infobase` или `data-separation` |

## Коды возврата

| Код | Описание |
|-----|----------|
| 0 | Успешно, либо `-WhatIf` |
| 1 | Ошибка параметров, отказ защиты боевой базы или ненулевой код `ibcmd` |

## Ограничения

- `ibcmd.exe` входит в компонент автономного сервера и ставится с платформой не всегда: в каталоге
  `bin` установленной платформы его может не быть. Тогда путь к `ibcmd.exe` передается в `-V8Path`.
- Для серверной базы `ibcmd` подключается к СУБД: `-InfoBaseServer` и `-InfoBaseRef` - сервер и имя базы
  СУБД, а не кластер 1С. Защита боевой базы сравнивает их с полями `server` и `ref` записи
  `.v8-project.json`; если там записаны имена кластера, запись не совпадет и защита не сработает.
  Для серверной боевой базы указывать в записи сервер и имя базы СУБД либо не выполнять изменяющие
  операции без явной команды пользователя.
- `set-properties -SecurityProfileName` в одном вызове с другими свойствами может вернуть безопасный
  режим во включенное состояние (замер 8.3.27.1989): после вызова проверить свойства командой `list`.

## Примеры

```powershell
# Список расширений файловой базы
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 list -InfoBasePath "C:\Bases\MyDB"

# Проверка применимости расширения
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 check -InfoBasePath "C:\Bases\MyDB" -Name "МоеРасширение"

# Снять безопасный режим и оставить расширение активным
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 set-properties -InfoBasePath "C:\Bases\MyDB" -Name "МоеРасширение" -SafeMode no -Active yes

# Удаление
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 delete -InfoBasePath "C:\Bases\MyDB" -Name "МоеРасширение"

# Команда без запуска
powershell.exe -NoProfile -File skills/1c-db-cfe-admin/scripts/db-cfe-admin.ps1 delete -InfoBasePath "C:\Bases\MyDB" -Name "МоеРасширение" -WhatIf
```
