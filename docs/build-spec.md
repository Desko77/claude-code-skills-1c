# Пакетный режим конфигуратора 1С

## Общие сведения

Конфигуратор 1С:Предприятия 8.3 поддерживает пакетный (безоконный) режим для автоматизации операций с конфигурациями, информационными базами и внешними обработками. Все операции выполняются через командную строку `1cv8.exe`.

**Два режима запуска:**

| Режим | Назначение |
|-------|-----------|
| `DESIGNER` | Конфигуратор — работа с конфигурацией, сборка EPF, обновление БД |
| `ENTERPRISE` | Предприятие — запуск обработок, навигация по ссылкам |
| `CREATEINFOBASE` | Создание новой информационной базы |

**Путь к 1cv8.exe** зависит от версии платформы: `C:\Program Files\1cv8\8.3.27.1859\bin\1cv8.exe`.

## Подключение к информационной базе

| Параметр | Описание |
|----------|----------|
| `/F <каталог>` | Файловая база — каталог с файлом `1Cv8.1CD` |
| `/S <адрес>` | Серверная база — формат `server/ibname` |
| `/IBName <имя>` | По имени из списка баз (в кавычках если содержит пробелы) |
| `/IBConnectionString` | Полная строка соединения |

Примеры:
```
1cv8.exe DESIGNER /F "C:\Bases\MyBase" ...
1cv8.exe DESIGNER /S server-pc/accounting ...
1cv8.exe DESIGNER /IBName "Бухгалтерия предприятия" ...
```

### Аутентификация

| Параметр | Описание |
|----------|----------|
| `/N<имя>` | Имя пользователя (**без пробела** после `/N`) |
| `/P<пароль>` | Пароль (**без пробела** после `/P`). Можно опустить если пароля нет |
| `/WA-` | Запретить аутентификацию ОС |
| `/WA+` | Обязательная аутентификация ОС (по умолчанию) |

> **Важно**: между `/N` и именем, а также между `/P` и паролем пробела нет: `/NАдмин /PSecret123`.

## Общие параметры пакетного режима

| Параметр | Описание |
|----------|----------|
| `/DisableStartupDialogs` | Подавляет интерактивные диалоги (Yes/No). **Обязательно** для пакетного режима — без него конфигуратор может зависнуть в ожидании ввода |
| `/DisableStartupMessages` | Подавляет стартовые предупреждения («Конфигурация БД не соответствует...» и т.п.). **Обязательно** — без него конфигуратор зависает при расхождении основной конфигурации и конфигурации БД |
| `/Out <файл> [-NoTruncate]` | Файл для вывода служебных сообщений (UTF-8). `-NoTruncate` — не очищать файл перед записью |
| `/DumpResult <файл>` | Записать числовой код результата в файл (0 — успех, 1 — ошибка, 101 — ошибки проверки) |
| `/Visible` | Показать окно конфигуратора (по умолчанию скрыто в пакетном режиме) |

## Создание информационной базы

```
1cv8.exe CREATEINFOBASE <строка_соединения> [/AddToList [<имя>]] [/UseTemplate <файл>] [/DumpResult <файл>]
```

### Файловая база

```
1cv8.exe CREATEINFOBASE File="C:\Bases\EmptyDB"
```

### Серверная база

```
1cv8.exe CREATEINFOBASE Srvr="server-pc";Ref="new_db"
```

### Параметры

| Параметр | Описание |
|----------|----------|
| `File="<путь>"` | Строка соединения для файловой базы |
| `Srvr="<сервер>";Ref="<имя>"` | Строка соединения для серверной базы |
| `/AddToList [<имя>]` | Добавить в список баз. Имя — необязательно |
| `/UseTemplate <файл>` | Создать по шаблону (.cf или .dt) |
| `/DumpResult <файл>` | Записать результат (0 — успех) |

## Работа с конфигурацией — бинарные файлы (CF)

### Выгрузка конфигурации в CF-файл

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpCfg config.cf /Out log.txt
```

**`/DumpCfg <файл> [-Extension <имя>]`** — сохранить конфигурацию в .cf-файл.

### Загрузка конфигурации из CF-файла

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /LoadCfg config.cf /Out log.txt
```

**`/LoadCfg <файл> [-Extension <имя>] [-AllExtensions]`** — загрузить конфигурацию из .cf-файла.

| Параметр | Описание |
|----------|----------|
| `-Extension <имя>` | Работа с расширением (указать имя) |
| `-AllExtensions` | Работа со всеми расширениями (файл — архив расширений) |

> После `/LoadCfg` конфигурация загружается в «основную» конфигурацию конфигуратора. Для применения к БД необходим `/UpdateDBCfg`.

## Работа с конфигурацией — XML-исходники

### Выгрузка `/DumpConfigToFiles`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles <каталог> [параметры] /Out log.txt
```

Полная сигнатура:
```
/DumpConfigToFiles <каталог> [-Extension <имя>] [-AllExtensions]
    [-update] [-force] [-getChanges <файл>]
    [-configDumpInfoForChanges <файл>] [-listFile <файл>]
    [-configDumpInfoOnly] [-Server] [-Format <формат>]
    [-Archive <файл>] [-ignoreUnresolvedReferences]
```

#### Режимы выгрузки

**Полная выгрузка** — все объекты конфигурации:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles "C:\src\config" /Out log.txt
```

**Инкрементальная выгрузка** — только изменённые объекты:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles "C:\src\config" -update -force /Out log.txt
```

Инкрементальная выгрузка с отслеживанием изменений:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles "C:\src\config" -update -getChanges "changes.txt" -configDumpInfoForChanges "old\ConfigDumpInfo.xml" /Out log.txt
```

**Частичная выгрузка** — выбранные объекты по списку:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles "C:\src\config" -listFile "dump_objects.txt" /Out log.txt
```

**Обновление ConfigDumpInfo.xml** — без выгрузки файлов:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigToFiles "C:\src\config" -configDumpInfoOnly /Out log.txt
```

#### Параметры выгрузки

| Параметр | Описание |
|----------|----------|
| `-update` | Обновляющая (инкрементальная) выгрузка — только изменённые объекты |
| `-force` | Принудительная полная выгрузка. Используется с `-update` при несовпадении версий |
| `-getChanges <файл>` | Записать список изменённых файлов |
| `-configDumpInfoForChanges <файл>` | Файл ConfigDumpInfo.xml для определения изменений |
| `-listFile <файл>` | Файл со списком выгружаемых объектов (по одному на строку) |
| `-configDumpInfoOnly` | Выгрузить только ConfigDumpInfo.xml |
| `-Extension <имя>` | Выгрузить расширение |
| `-AllExtensions` | Выгрузить все расширения |
| `-Server` | Выгрузка на стороне сервера |
| `-Format <формат>` | Формат файлов (Hierarchical / Plain) |
| `-Archive <файл>` | Выгрузка в архивный файл |
| `-ignoreUnresolvedReferences` | Игнорировать неразрешённые ссылки |

#### Формат listFile для выгрузки

Файл содержит **имена объектов метаданных** (одно на строку):
```
Справочник.Номенклатура
Справочник.Валюты
Документ.РеализацияТоваровУслуг
Отчет.АнализПродаж
```

Кодировка: UTF-8 с BOM.

### Загрузка `/LoadConfigFromFiles`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /LoadConfigFromFiles <каталог> [параметры] /Out log.txt
```

Полная сигнатура:
```
/LoadConfigFromFiles <каталог> [-Extension <имя>] [-AllExtensions]
    [-files "<файлы>"] [-listFile <файл>]
    [-Format <формат>] [-updateConfigDumpInfo] [-NoCheck]
    [-Server] [-Archive <файл>] [-partial]
```

#### Режимы загрузки

**Полная загрузка** — замена всей конфигурации:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /LoadConfigFromFiles "C:\src\config" /Out log.txt
```

**Частичная загрузка** — выбранные файлы по списку:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /LoadConfigFromFiles "C:\src\config" -listFile "load_list.txt" -Format Hierarchical -partial -updateConfigDumpInfo /Out log.txt
```

#### Параметры загрузки

| Параметр | Описание |
|----------|----------|
| `-files "<файлы>"` | Список файлов для частичной загрузки (через запятую, в кавычках). Несовместим с `-AllExtensions` |
| `-listFile <файл>` | Файл со списком загружаемых файлов (по одному на строку, UTF-8). Несовместим с `-AllExtensions` |
| `-partial` | Частичная загрузка — загружать только указанные элементы описания объекта, не заменяя всю конфигурацию |
| `-updateConfigDumpInfo` | Обновить ConfigDumpInfo.xml после загрузки |
| `-NoCheck` | Не проверять целостность при загрузке (ускоряет загрузку заведомо целостной конфигурации) |
| `-Extension <имя>` | Загрузить в расширение. Если расширения нет — оно создаётся |
| `-AllExtensions` | Загрузить все расширения (каждый подкаталог = расширение). Несовместим с `-files`/`-listFile` |
| `-Server` | Загрузка на стороне сервера |
| `-Archive <файл>` | Загрузка из ZIP-архива. Несовместим с указанием каталога загрузки |
| `-Format <формат>` | Формат файлов (Hierarchical / Plain). Обязателен при частичной загрузке (`-files`/`-listFile`) |

#### Формат listFile для загрузки

Файл содержит **относительные пути к файлам** в каталоге выгрузки (один на строку):
```
Catalogs/Валюты.xml
Catalogs/Валюты/Ext/ObjectModule.bsl
Documents/РеализацияТоваровУслуг.xml
Documents/РеализацияТоваровУслуг/Forms/ФормаДокумента.xml
```

Кодировка: UTF-8 с BOM.

#### Примеры listFile для типичных сценариев загрузки

**Изменение модуля объекта справочника:**
```
Catalogs/Номенклатура.xml
Catalogs/Номенклатура/Ext/ObjectModule.bsl
```

**Изменение формы справочника (модуль + XML формы):**
```
Catalogs/Номенклатура.xml
Catalogs/Номенклатура/Forms/ФормаЭлемента.xml
Catalogs/Номенклатура/Forms/ФормаЭлемента/Ext/Form.xml
Catalogs/Номенклатура/Forms/ФормаЭлемента/Ext/Form/Module.bsl
```

**Изменение макета:**
```
Catalogs/Номенклатура.xml
Catalogs/Номенклатура/Templates/МакетПечати.xml
Catalogs/Номенклатура/Templates/МакетПечати/Ext/Template.mxl
```

**Изменение модуля менеджера:**
```
Catalogs/Номенклатура.xml
Catalogs/Номенклатура/Ext/ManagerModule.bsl
```

> **Важно:** корневой XML объекта (`Catalogs/Номенклатура.xml`) нужно включать всегда — он содержит реестр подчинённых элементов (форм, макетов, модулей). Без него конфигуратор может не обнаружить изменения.

> **Важно: различие форматов listFile для dump и load:**
> - **Выгрузка** (`/DumpConfigToFiles -listFile`): **имена объектов метаданных** — `Справочник.Номенклатура`
> - **Загрузка** (`/LoadConfigFromFiles -listFile`): **относительные пути файлов** — `Catalogs/Валюты.xml`

## Обновление конфигурации БД

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /UpdateDBCfg /Out log.txt
```

Полная сигнатура:
```
/UpdateDBCfg [-Dynamic<режим>] [-Server]
    [-WarningsAsErrors]
    [-BackgroundStart] [-BackgroundFinish]
    [-BackgroundCancel] [-BackgroundSuspend] [-BackgroundResume]
    [-Extension <имя>] [-AllExtensions]
```

| Параметр | Описание |
|----------|----------|
| `-Dynamic+` | Использовать динамическое обновление |
| `-Dynamic-` | Не использовать динамическое обновление |
| `-Server` | Обновление на стороне сервера |
| `-WarningsAsErrors` | Предупреждения считать ошибками |
| `-Extension <имя>` | Обновить расширение |
| `-AllExtensions` | Обновить все расширения |

### Фоновое обновление

| Параметр | Описание |
|----------|----------|
| `-BackgroundStart` | Начать фоновое обновление |
| `-BackgroundFinish` | Дождаться окончания и завершить |
| `-BackgroundCancel` | Отменить фоновое обновление |
| `-BackgroundSuspend` | Приостановить |
| `-BackgroundResume` | Возобновить |

> После `/LoadCfg` или `/LoadConfigFromFiles` необходимо выполнить `/UpdateDBCfg` чтобы изменения применились к базе данных.

## Сборка и разборка внешних обработок (EPF/ERF)

### Сборка (XML → EPF)

```
1cv8.exe DESIGNER /F <путь_к_базе> /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles <корневой_xml> <путь_к_epf> /Out <лог_файл>
```

| Параметр | Описание |
|----------|----------|
| `<корневой_xml>` | Путь к корневому XML-файлу обработки (например, `src\МояОбработка.xml`) |
| `<путь_к_epf>` | Путь к выходному файлу `.epf` или `.erf` |

> **Важно**: первый аргумент — путь к **корневому XML-файлу** (не к каталогу). Если указать каталог, конфигуратор вернёт ошибку.

### Разборка (EPF → XML)

```
1cv8.exe DESIGNER /F <путь_к_базе> /DisableStartupDialogs /DumpExternalDataProcessorOrReportToFiles <каталог_выгрузки> <путь_к_epf> [-Format Hierarchical] /Out <лог_файл>
```

| Параметр | Описание |
|----------|----------|
| `<каталог_выгрузки>` | Каталог для XML-файлов |
| `<путь_к_epf>` | Исходный файл `.epf` или `.erf` |
| `-Format Hierarchical` | Иерархическая структура каталогов (по умолчанию) |
| `-Format Plain` | Плоская структура |

### Примечания

- Пустая ИБ достаточна для сборки, если обработка не ссылается на объекты конфигурации.
- Если обработка использует ссылочные типы конфигурации (`CatalogRef.*`, `DocumentRef.*` и т.п.) — в реквизитах, табличных частях или реквизитах форм — **сборка в пустой базе упадёт** с ошибкой XDTO. Необходима база с целевой конфигурацией.

## Запуск в режиме предприятия

```
1cv8.exe ENTERPRISE /F <база> [/N<имя> /P<пароль>] /DisableStartupDialogs [параметры]
```

| Параметр | Описание |
|----------|----------|
| `/Execute <файл.epf>` | Запуск внешней обработки сразу после старта. При указании `/Execute` параметр `/URL` игнорируется |
| `/URL <ссылка>` | Навигационная ссылка (формат `e1cib/...`) |
| `/C <строка>` | Передача параметра в прикладное решение |

Примеры:
```
1cv8.exe ENTERPRISE /F "C:\Bases\MyBase" /NАдмин /PSecret /DisableStartupDialogs /Execute "C:\scripts\process.epf"
```

```
1cv8.exe ENTERPRISE /IBName "Бухгалтерия" /NАдмин /DisableStartupDialogs /URL "e1cib/data/Справочник.Номенклатура"
```

## Коды возврата

| Код | Значение |
|-----|----------|
| `0` | Успешно |
| `1` | Ошибка |
| `101` | Ошибки при проверке конфигурации |

Числовой код можно записать в файл через `/DumpResult <файл>`.

При работе с расширениями (`-Extension`, `-AllExtensions`): 0 — успех, 1 — ошибка.

## ConfigDumpInfo.xml

`ConfigDumpInfo.xml` — служебный файл, создаваемый при выгрузке конфигурации в файлы (`/DumpConfigToFiles`). Содержит информацию о составе и версиях объектов конфигурации на момент выгрузки.

**Назначение:**
- Определение изменений при инкрементальной выгрузке (`-update`, `-configDumpInfoForChanges`)
- Синхронизация состояния выгрузки с конфигурацией ИБ

**Использование:**
- `-configDumpInfoForChanges <файл>` — передать предыдущий ConfigDumpInfo.xml для определения изменений
- `-configDumpInfoOnly` — обновить только этот файл без выгрузки объектов
- `-updateConfigDumpInfo` — обновить файл после частичной загрузки (`/LoadConfigFromFiles`)

**Расположение:** корень каталога выгрузки (рядом с `Configuration.xml`).

## Troubleshooting

### Зависание без `/DisableStartupMessages`

Если конфигурация БД не соответствует основной конфигурации, конфигуратор показывает интерактивный диалог «Конфигурация базы данных не соответствует сохраненной конфигурации. Продолжить?» и ждёт ввода пользователя. В пакетном режиме это приводит к зависанию процесса.

**Решение:** всегда добавлять `/DisableStartupMessages` в командную строку.

### Зависание без `/DisableStartupDialogs`

Конфигуратор может показывать интерактивные Yes/No диалоги (например, при удалении объектов, реструктуризации таблиц). В пакетном режиме без подавления диалогов процесс зависнет.

**Решение:** всегда добавлять `/DisableStartupDialogs` в командную строку. Оба параметра (`/DisableStartupMessages` и `/DisableStartupDialogs`) следует указывать вместе.

### XDTO-ошибка при сборке EPF в пустой базе

Если внешняя обработка ссылается на типы конфигурации (`CatalogRef.*`, `DocumentRef.*` и т.п.) в реквизитах, табличных частях или реквизитах форм, сборка в пустой базе упадёт с ошибкой XDTO — платформа не может разрешить ссылки на несуществующие типы.

**Решение:** использовать базу с целевой конфигурацией (в которой определены используемые объекты метаданных).

### «Несоответствие свойства» при частичной загрузке

Ошибка `Несоответствие свойства и элемента данных XDTO` возникает при неполном listFile. При изменении формы нужно загружать **все связанные файлы**: XML-дескриптор формы, весь каталог `Ext/` формы (Form.xml, Module.bsl) и корневой XML объекта.

**Решение:** использовать полные наборы файлов (см. примеры listFile выше).

### Кодировка listFile

Файл списка (`-listFile`) должен быть в кодировке **UTF-8 с BOM**. Без BOM кириллические символы в именах файлов интерпретируются некорректно, и конфигуратор не находит указанные файлы.

**Решение:** при генерации listFile из скрипта явно указывать UTF-8 с BOM:
```powershell
$enc = New-Object System.Text.UTF8Encoding($true)  # BOM
[System.IO.File]::WriteAllText($listFile, $content, $enc)
```

## Переменные окружения

| Переменная | Описание |
|-----------|----------|
| `V8_PATH` | Каталог `bin` платформы 1С (например, `C:\Program Files\1cv8\8.3.27.1859\bin`) |
| `V8_BASE` | Путь к пустой ИБ для EPF-сборки (создаётся автоматически при первом запуске) |

## Выгрузка и загрузка информационной базы (DT)

### Выгрузка `/DumpIB`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DisableStartupMessages /DumpIB <файл.dt> /Out log.txt
```

Выгружает информационную базу целиком в файл `.dt` (данные + конфигурация).

### Загрузка `/RestoreIB`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DisableStartupMessages /RestoreIB <файл.dt> /Out log.txt
```

Загружает информационную базу из файла `.dt`. **Полностью заменяет** содержимое базы.

| Параметр | Описание |
|----------|----------|
| `-JobsCount <N>` | Количество фоновых заданий для параллельной загрузки (0 = авто, по числу ядер CPU) |

### Восстановление структуры `/IBRestoreIntegrity`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /IBRestoreIntegrity /Out log.txt
```

Попытка восстановления структуры ИБ после аварийного завершения обновления конфигурации БД. Рекомендуется запускать, если предыдущий `/UpdateDBCfg` не завершился (сбой, выключение компьютера).

## Дополнительные команды работы с конфигурацией

### Сохранение конфигурации БД `/DumpDBCfg`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpDBCfg config_db.cf /Out log.txt
```

**`/DumpDBCfg <файл> [-Extension <имя>]`** — сохранить конфигурацию **базы данных** (не основную) в файл. Полезно для получения конфигурации в актуальном состоянии БД.

### Возврат к конфигурации БД `/RollbackCfg`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /RollbackCfg /Out log.txt
```

**`/RollbackCfg [-Extension <имя>]`** — откатить основную конфигурацию к конфигурации БД. С параметром `-Extension` — откатить конкретное расширение.

### Удаление расширения `/DeleteCfg`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DeleteCfg -Extension "МоёРасширение" /Out log.txt
```

**`/DeleteCfg [-Extension <имя>] [-AllExtensions]`** — удалить расширение. Использование команды без параметра не допускается.

### Объединение конфигураций `/MergeCfg`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /MergeCfg update.cf -Settings merge_settings.xml /Out log.txt
```

Полная сигнатура:
```
/MergeCfg <файл.cf/.cfe> -Settings <файл_настроек>
    [-EnableSupport | -DisableSupport]
    [-IncludeObjectsByUnresolvedRefs | -ClearUnresolvedRefs]
    [-Extension <имя>] [-force]
```

| Параметр | Описание |
|----------|----------|
| `-Settings <файл>` | Файл настроек объединения (обязательный) |
| `-EnableSupport` | Поставить на поддержку (с правилами из файла настроек) |
| `-DisableSupport` | Не выполнять постановку на поддержку |
| `-IncludeObjectsByUnresolvedRefs` | Автоматически включать зависимые объекты |
| `-ClearUnresolvedRefs` | Очищать неразрешённые ссылки |
| `-Extension <имя>` | Объединение с расширением |
| `-force` | Продолжать при предупреждениях об удалённых объектах |

## Выгрузка и загрузка свойств объектов

### Выгрузка модулей/макетов/справки `/DumpConfigFiles`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /DumpConfigFiles "C:\modules" -Module /Out log.txt
```

**`/DumpConfigFiles <каталог> [-Module] [-Template] [-Help] [-AllWritable] [-Picture] [-Right] [-Extension <имя>]`**

| Параметр | Описание |
|----------|----------|
| `-Module` | Выгрузить модули |
| `-Template` | Выгрузить макеты |
| `-Help` | Выгрузить справочную информацию |
| `-AllWritable` | Только доступные для записи объекты |
| `-Picture` | Выгрузить общие картинки |
| `-Right` | Выгрузить права |
| `-Extension <имя>` | Выгрузить для указанного расширения |

### Загрузка модулей/макетов/справки `/LoadConfigFiles`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /LoadConfigFiles "C:\modules" -Module /Out log.txt
```

Аналогичные параметры. При загрузке в расширение, подключённое к хранилищу — загружаемые объекты должны быть захвачены.

> **Отличие от `/DumpConfigToFiles` и `/LoadConfigFromFiles`:** команды `/DumpConfigFiles` и `/LoadConfigFiles` работают с **отдельными свойствами** объектов (модули, макеты, справка), а не с полной XML-выгрузкой конфигурации.

## Проверка конфигурации

### Синтаксический контроль модулей `/CheckModules`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CheckModules -Server -ThinClient -ExternalConnection -ExtendedModulesCheck /Out log.txt
```

Полная сигнатура:
```
/CheckModules [-ThinClient] [-WebClient] [-MobileClient] [-Server]
    [-MobileAppServer] [-ExternalConnection]
    [-ThickClientOrdinaryApplication] [-ExtendedModulesCheck]
    [-Extension <имя>] [-AllExtensions]
```

| Параметр | Описание |
|----------|----------|
| `-ThinClient` | Проверка в режиме тонкого клиента |
| `-WebClient` | Проверка в режиме веб-клиента |
| `-Server` | Проверка в режиме сервера |
| `-ExternalConnection` | Проверка в режиме внешнего соединения |
| `-ThickClientOrdinaryApplication` | Проверка в режиме обычного приложения |
| `-ExtendedModulesCheck` | Расширенная проверка: обращения через точку, строковые литералы функций (`ПолучитьФорму()` и т.д.) |
| `-Extension <имя>` | Проверка указанного расширения |
| `-AllExtensions` | Проверка всех расширений |

> **Важно:** должен быть указан хотя бы один режим проверки (`-Server`, `-ThinClient` и т.д.), иначе проверка выполнена не будет.

### Централизованная проверка конфигурации `/CheckConfig`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CheckConfig -ConfigLogIntegrity -IncorrectReferences -ThinClient -Server -ExternalConnection -ExtendedModulesCheck /Out log.txt
```

Полная сигнатура:
```
/CheckConfig [-ConfigLogIntegrity] [-IncorrectReferences]
    [-ThinClient] [-WebClient] [-Server] [-ExternalConnection]
    [-ExternalConnectionServer]
    [-ThickClientManagedApplication] [-ThickClientServerManagedApplication]
    [-ThickClientOrdinaryApplication] [-ThickClientServerOrdinaryApplication]
    [-DistributiveModules] [-UnreferenceProcedures]
    [-HandlersExistence] [-EmptyHandlers]
    [-ExtendedModulesCheck] [-CheckUseModality] [-CheckUseSynchronousCalls]
    [-UnsupportedFunctional]
    [-Extension <имя>] [-AllExtensions]
```

| Параметр | Описание |
|----------|----------|
| `-ConfigLogIntegrity` | Проверка логической целостности конфигурации |
| `-IncorrectReferences` | Поиск некорректных ссылок на удалённые объекты |
| `-DistributiveModules` | Проверка поставки модулей без исходных текстов |
| `-UnreferenceProcedures` | Поиск неиспользуемых локальных процедур и функций |
| `-HandlersExistence` | Проверка существования назначенных обработчиков событий |
| `-EmptyHandlers` | Поиск пустых обработчиков (снижают производительность) |
| `-ExtendedModulesCheck` | Расширенная проверка обращений через точку |
| `-CheckUseModality` | Поиск использования модальных методов (только с `-ExtendedModulesCheck`) |
| `-CheckUseSynchronousCalls` | Поиск использования синхронных вызовов (только с `-ExtendedModulesCheck`) |

> **Отличие от `/CheckModules`:** `/CheckConfig` — расширенная проверка, включающая логическую целостность, некорректные ссылки, неиспользуемые процедуры, пустые обработчики. `/CheckModules` — только синтаксический контроль модулей в указанных режимах.

### Проверка применимости расширений `/CheckCanApplyConfigurationExtensions`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CheckCanApplyConfigurationExtensions -Extension "МоёРасширение" /Out log.txt
```

**`/CheckCanApplyConfigurationExtensions [-Extension <имя>] [-AllZones] [-Z <разделители>]`** — проверяет, может ли расширение быть применено в конкретной информационной базе.

## Тестирование и исправление ИБ

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /IBCheckAndRepair -ReIndex -RecalcTotals -IBCompression -LogIntegrity /Out log.txt
```

Полная сигнатура:
```
/IBCheckAndRepair [-ReIndex] [-LogIntegrity | -LogAndRefsIntegrity]
    [-RecalcTotals] [-IBCompression] [-Rebuild]
    [-TestOnly | [[-BadRefCreate | -BadRefClear | -BadRefNone]
                   [-BadDataCreate | -BadDataDelete]]]
    [-UseStartPoint] [-TimeLimit:hhh:mm]
    [-ConfigurationExtensionsLogIntegrity]
    [-RebuildConfigurationExtension]
    [-RefreshTableLocation]
    [-JobsCount <N>]
```

| Параметр | Описание |
|----------|----------|
| `-ReIndex` | Реиндексация таблиц |
| `-LogIntegrity` | Проверка логической целостности |
| `-LogAndRefsIntegrity` | Проверка логической и ссылочной целостности |
| `-RecalcTotals` | Пересчёт итогов |
| `-IBCompression` | Сжатие таблиц |
| `-Rebuild` | Реструктуризация таблиц ИБ |
| `-TestOnly` | Только тестирование (без исправлений) |
| `-BadRefCreate` | При битых ссылках — создавать объекты |
| `-BadRefClear` | При битых ссылках — очищать |
| `-BadRefNone` | При битых ссылках — не изменять |
| `-BadDataCreate` | При частичной потере данных — создавать объекты |
| `-BadDataDelete` | При частичной потере данных — удалять |
| `-ConfigurationExtensionsLogIntegrity` | Проверка целостности расширений (не требует монопольного доступа) |
| `-RebuildConfigurationExtension` | Реструктуризация таблиц расширений (не требует монопольного доступа) |
| `-UseStartPoint` | Продолжить с точки остановки предыдущей проверки |
| `-TimeLimit:hhh:mm` | Ограничение времени выполнения |
| `-JobsCount <N>` | Количество фоновых заданий (0 = авто) |

Пример — только тестирование без исправлений:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /IBCheckAndRepair -LogAndRefsIntegrity -TestOnly /Out log.txt
```

## Создание файлов поставки и обновления

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CreateDistributionFiles -cffile dist.cf /Out log.txt
```

Полная сигнатура:
```
/CreateDistributionFiles [-cffile <файл.cf>]
    [-cfufile <файл.cfu> [-f <файл.cf> | -v <версия>]+]
    [-digisign <файл_лицензирования>] [-WarningAsError]
```

| Параметр | Описание |
|----------|----------|
| `-cffile <файл>` | Создать файл поставки (дистрибутив) |
| `-cfufile <файл>` | Создать файл обновления |
| `-f <файл.cf>` | Дистрибутив для включения в обновление (задан именем файла) |
| `-v <версия>` | Дистрибутив для включения в обновление (задан версией) |
| `-WarningAsError` | Несоответствие цифровой подписи считать ошибкой |

> Группа параметров `-f`/`-v` повторяется столько раз, сколько дистрибутивов включается в обновление.

Пример — создание поставки и обновления:
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CreateDistributionFiles -cffile release.cf -cfufile update.cfu -v "1.0.0.1" -v "1.0.0.2" /Out log.txt
```

## Хранилище конфигурации

### Параметры подключения к хранилищу

| Параметр | Описание |
|----------|----------|
| `/ConfigurationRepositoryF <каталог>` | Путь к хранилищу конфигурации |
| `/ConfigurationRepositoryN <имя>` | Имя пользователя хранилища |
| `/ConfigurationRepositoryP <пароль>` | Пароль пользователя хранилища |

Параметры подключения сочетаются с любой командой работы с хранилищем.

### Создание хранилища

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /ConfigurationRepositoryF "C:\Repo" /ConfigurationRepositoryN Admin /ConfigurationRepositoryP "" /ConfigurationRepositoryCreate /Out log.txt
```

**`/ConfigurationRepositoryCreate [-AllowConfigurationChanges -ChangesAllowedRule <правило> -ChangesNotRecommendedRule <правило>] [-NoBind] [-Extension <имя>]`**

| Параметр | Описание |
|----------|----------|
| `-AllowConfigurationChanges` | Включить возможность изменения (если на поддержке) |
| `-ChangesAllowedRule <правило>` | Правило для разрешённых изменений: `ObjectNotEditable`, `ObjectIsEditableSupportEnabled`, `ObjectNotSupported` |
| `-ChangesNotRecommendedRule <правило>` | Правило для нерекомендуемых изменений |
| `-NoBind` | Не подключать к созданному хранилищу |
| `-Extension <имя>` | Создать хранилище для расширения |

### Обновление конфигурации из хранилища

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /ConfigurationRepositoryF "C:\Repo" /ConfigurationRepositoryN Admin /ConfigurationRepositoryP "" /ConfigurationRepositoryUpdateCfg -force /Out log.txt
```

**`/ConfigurationRepositoryUpdateCfg [-v <номер>] [-revised] [-force] [-Objects <файл>] [-Extension <имя>]`**

| Параметр | Описание |
|----------|----------|
| `-v <номер>` | Номер версии (-1 или не указан — последняя). Игнорируется если подключены к хранилищу |
| `-revised` | Получать захваченные объекты, если потребуется |
| `-force` | Подтвердить добавление/удаление объектов при обновлении |
| `-Objects <файл>` | Список объектов для обновления |
| `-Extension <имя>` | Обновить расширение из его хранилища |

### Сохранение конфигурации из хранилища

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /ConfigurationRepositoryF "C:\Repo" /ConfigurationRepositoryN Admin /ConfigurationRepositoryP "" /ConfigurationRepositoryDumpCfg repo_config.cf /Out log.txt
```

**`/ConfigurationRepositoryDumpCfg <файл.cf> [-v <номер>] [-Extension <имя>]`** — сохранить конфигурацию из хранилища в CF-файл. `-v -1` или без `-v` — последняя версия.

### Захват и помещение объектов

**Захват:**
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /ConfigurationRepositoryF "C:\Repo" /ConfigurationRepositoryN Admin /ConfigurationRepositoryP "" /ConfigurationRepositoryLock -Objects objects.txt /Out log.txt
```

**`/ConfigurationRepositoryLock [-Objects <файл>] [-revised] [-Extension <имя>]`** — захватить объекты для редактирования.

**Помещение:**
```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /ConfigurationRepositoryF "C:\Repo" /ConfigurationRepositoryN Admin /ConfigurationRepositoryP "" /ConfigurationRepositoryCommit -comment "Описание изменений" /Out log.txt
```

**`/ConfigurationRepositoryCommit [-Objects <файл>] [-comment <текст>] [-keepLocked] [-force] [-Extension <имя>]`**

| Параметр | Описание |
|----------|----------|
| `-Objects <файл>` | Список объектов для помещения |
| `-comment <текст>` | Комментарий (в кавычках). Для многострочного — несколько `-comment` |
| `-keepLocked` | Оставить объекты захваченными после помещения |
| `-force` | Очищать ссылки на удалённые объекты |

**Отмена захвата:**

**`/ConfigurationRepositoryUnLock [-Objects <файл>] [-force] [-Extension <имя>]`** — отменить захват. С `-force` — локальные изменения будут потеряны.

### Подключение и отключение

**`/ConfigurationRepositoryBindCfg [-forceBindAlreadyBindedUser] [-forceReplaceCfg] [-Extension <имя>]`** — подключить ИБ к хранилищу.

**`/ConfigurationRepositoryUnbindCfg [-force] [-Extension <имя>]`** — отключить от хранилища. С `-force` — без аутентификации и при наличии захваченных объектов.

### Сравнение конфигураций `/CompareCfg`

```
1cv8.exe DESIGNER /F <база> /DisableStartupDialogs /CompareCfg -FirstConfigurationType MainConfiguration -SecondConfigurationType DBConfiguration -ReportType Full -ReportFormat txt -ReportFile compare.txt /Out log.txt
```

Сравнивает две конфигурации и формирует отчёт. Типы конфигураций: `MainConfiguration`, `DBConfiguration`, `VendorConfiguration`, `ExtensionConfiguration`, `ExtensionDBConfiguration`, `ConfigurationRepository`, `File`.

