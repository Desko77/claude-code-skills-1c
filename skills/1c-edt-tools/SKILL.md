---
name: 1c-edt-tools
description: "1C:Enterprise (1С:Предприятие) development tools via EDT MCP server — BSL code analysis, metadata inspection, module navigation, error checking, debugging, configuration management. Use when working with 1C code, BSL modules, 1C metadata, 1C queries, 1C forms, or any 1C:Enterprise development task."
---

# 1C:EDT MCP Tools — Reference Guide

MCP-сервер **1c-edt** предоставляет прямой доступ к семантическому индексу EDT (BM model), платформенной документации, проверкам и управлению проектом. Все инструменты работают через живой экземпляр EDT и используют реальный AST/семантику, а не текстовый поиск.

## When to Use

Используй инструменты 1c-edt когда:
- Нужно прочитать исходный код модуля или отдельного метода
- Нужно понять структуру модуля (список процедур/функций) без чтения всего файла
- Нужно найти все вызывающие места метода (call hierarchy)
- Нужно найти все ссылки на объект метаданных (references)
- Нужно проверить ошибки проекта или конкретного объекта
- Нужна документация по типам платформы (ТаблицаЗначений, Массив и т.д.)
- Нужно получить автодополнение (content assist) в конкретной позиции кода
- Нужно найти код по тексту/регулярному выражению во всех модулях
- Нужно получить свойства объектов метаданных или конфигурации
- Нужно обновить базу данных или запустить отладку

## Prerequisites Check

Перед первым использованием любого инструмента проверь доступность MCP-сервера — вызови любой инструмент EDT-MCP (например `get_edt_version`).
Если сервер **не отвечает** — сообщи пользователю:
> EDT MCP сервер недоступен. Для использования инструментов анализа кода необходимо:
> 1. Запустить 1C:EDT с открытым workspace
> 2. Убедиться, что плагин EDT MCP Server установлен и активен (порт 8765)

Не пытайся вызывать инструменты без работающего сервера.

## Important

- Параметр `projectName` — имя проекта в EDT workspace (например `РНК_ЕРПУХ` или `РНК_ЕРПУХ.Расширение1`)
- Параметр `modulePath` — путь относительно папки `src/` проекта (например `CommonModules/Пользователи/Module.bsl`)
- Параметр `objectFqn` — полное квалифицированное имя (например `Document.SalesOrder`, `Catalog.Products`, `CommonModule.Common`). Поддерживает русские имена типов: `Справочник.Номенклатура`, `Документ.ЗаказКлиента`, `ОбщийМодуль.ОбщегоНазначения`
- Все инструменты требуют предварительной загрузки через `ToolSearch` с запросом `select:mcp__1c-edt__<tool_name>`

---

## Tools by Category

### 0. Unified facades (1.42 — предпочтительные точки входа)

В 1.42 добавлены 4 канонических фасада, которые объединяют наборы standalone-инструментов в одну точку входа. Используй их по умолчанию для нового кода — они делегируют к standalone-тулзам, но дают единый интерфейс через `operation` / `action`.

| Фасад | Зачем | Operations / Actions |
|---|---|---|
| `code_search` | Единый поиск по коду | `text_search`, `object_references`, `method_references`, `resolve_symbol`, `call_hierarchy`, `help` |
| `launch_debugger` | Единая отладка BSL | `launch`, `add_breakpoint`, `remove_breakpoint`, `list_breakpoints`, `wait_for_break`, `get_state`, `get_variables`, `step_over`, `step_into`, `step_out`, `resume`, `evaluate`, `start_profiling`, `get_profiling_results`, `debug_status`, `help` |
| `edit_metadata` | Конструктор метаданных, ~80 операций в 7 группах | Object, Specialized, Forms, Templates, Extensions, DCS, Common. См. `operation=help topic=workflow\|composerWorkflow\|matrixWorkflow\|availability` |
| `yaxunit_tests` | Юнит-тесты YAxUnit | `mode=run\|debug`, фильтры (extensions/modules/tests/suites/tags/contexts), `updateBeforeLaunch=true`, Pending-механизм, `help=topics\|writing\|assertions\|setup\|events\|advanced` |

**Naming convention 1.42:** tool names — `snake_case` (`search_in_code`, `code_search`, `launch_debugger`); operation names в multi-op инструментах — `snake_case` (`create_object`, `add_form_event_handler`, `text_search`, `add_breakpoint`); JSON параметры — `camelCase` (`projectName`, `ownerFqn`, `dryRun`).

Standalone-инструменты (`search_in_code`, `find_references`, `go_to_definition`, `get_method_call_hierarchy`, `debug_launch`, `set_breakpoint`, ...) остаются доступны для backward compatibility и описаны в секциях ниже.

---

### 1. Code Reading, Navigation and Editing

#### `read_module_source` — Чтение исходного кода модуля
Читает весь BSL-файл или диапазон строк. Возвращает код с номерами строк.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | да | Путь к BSL-файлу (`CommonModules/MyModule/Module.bsl`) |
| `startLine` | нет | Начальная строка (1-based) |
| `endLine` | нет | Конечная строка (1-based, включительно) |

**Совет:** Для больших модулей используй `startLine`/`endLine` вместо чтения целиком.

#### `write_module_source` — Запись BSL-кода в модуль
Записывает BSL-код в модули объектов метаданных с автоматической проверкой синтаксиса. Поддерживает три режима: поиск и замена фрагмента, полная замена модуля, добавление в конец. Модуль можно указать либо через `modulePath`, либо через `objectName` + `moduleType`.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | нет* | Путь от `src/` (`Documents/MyDoc/ObjectModule.bsl`). Альтернатива `objectName` + `moduleType` |
| `objectName` | нет* | Полное имя объекта (`Document.MyDoc`, `CommonModule.MyModule`). Поддерживает русские имена |
| `moduleType` | нет | Тип модуля: `ObjectModule` (по умолчанию), `ManagerModule`, `FormModule`, `CommandModule`, `RecordSetModule` |
| `source` | да | BSL-код: для `searchReplace` — новый код замены, для `replace` — полное содержимое, для `append` — добавляемый код |
| `oldSource` | нет** | Существующий код для замены (обязателен для `searchReplace`). Должен совпадать ровно в одном месте файла |
| `mode` | нет | Режим: `searchReplace` (по умолчанию), `replace`, `append` |
| `formName` | нет | Имя формы (обязательно при `moduleType=FormModule`) |
| `commandName` | нет | Имя команды (обязательно при `moduleType=CommandModule`) |
| `skipSyntaxCheck` | нет | Пропустить проверку синтаксиса (по умолчанию false). Проверяет парность `Процедура/КонецПроцедуры`, `Если/КонецЕсли` и т.д. |

**Преимущество:** автоматическая проверка синтаксиса после записи — ошибки обнаруживаются сразу.

#### `read_method_source` — Чтение одного метода
Извлекает код конкретной процедуры/функции по имени. Не нужно читать весь модуль.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | да | Путь к BSL-файлу |
| `methodName` | да | Имя процедуры/функции (регистронезависимо) |

#### `get_module_structure` — Структура модуля
Возвращает список всех процедур/функций с сигнатурами, номерами строк, регионами, директивами компиляции и флагом Экспорт. Позволяет понять модуль без чтения всего кода.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | да | Путь к BSL-файлу |
| `includeVariables` | нет | Включить объявления переменных модуля (по умолчанию false) |
| `includeComments` | нет | Включить doc-комментарии методов (по умолчанию false) |

#### `get_method_call_hierarchy` — Иерархия вызовов (callers/callees)
Находит вызывающие (callers) или вызываемые (callees) методы через семантический индекс EDT (AST, не текстовый поиск). Аналог Call Hierarchy в IDE.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | да | Путь к BSL-файлу, где определён метод |
| `methodName` | да | Имя процедуры/функции (регистронезависимо) |
| `direction` | нет | `callers` (кто вызывает, по умолчанию) или `callees` (что вызывает метод) |
| `limit` | нет | Макс. результатов (по умолчанию 100, макс. 500) |

#### `go_to_definition` — Переход к определению символа
Навигация к определению метода или объекта метаданных. Обратная операция к `find_references`: вместо поиска использований — находит, где символ определён. Поддерживает русские имена типов метаданных.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `symbol` | да | Символ для поиска определения. Форматы: `МодульИмя.МетодИмя` (метод общего модуля), `МетодИмя` (метод в контекстном модуле, требует `modulePath`), FQN метаданных (`Catalog.Products`, `Документ.ЗаказКлиента`) |
| `modulePath` | нет | Контекстный модуль (`Documents/SalesOrder/ObjectModule.bsl`). Обязателен когда `symbol` — неквалифицированное имя метода |
| `includeSource` | нет | Включить исходный код метода (по умолчанию true) |

#### `get_symbol_info` — Информация о символе в позиции кода
Получает type/hover информацию о символе в конкретной позиции BSL-файла — то же, что EDT показывает при наведении мыши. Полезно для понимания типов переменных в динамически типизированном BSL.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `filePath` | да | Путь к BSL-файлу относительно `src/` |
| `line` | да | Номер строки (1-based) |
| `column` | да | Номер колонки (1-based) |

**Возвращает:** имя символа, тип (Function/Procedure/Parameter и др.), сигнатуру, параметры, документацию.

#### `list_modules` — Список модулей
Перечисляет все BSL-модули объекта или всего проекта (МодульОбъекта, МодульМенеджера, МодулиФорм и т.д.).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objectName` | нет | Имя объекта (`Products`). Без него — все модули проекта |
| `metadataType` | нет | Фильтр по типу (`documents`, `catalogs`, `commonModules`, `informationRegisters`, `accumulationRegisters`, `reports`, `dataProcessors`, `exchangePlans`, `businessProcesses`, `tasks`, `constants`, `commonCommands`, `commonForms`, `webServices`, `httpServices`) |
| `nameFilter` | нет | Подстрока для фильтрации по пути модуля (регистронезависимо) |
| `limit` | нет | Макс. результатов (по умолчанию 200, макс. 1000) |

#### `ai_context` - Агрегированный контекст объекта
Собирает в одном вызове metadata, список BSL-модулей и структуру модуля. Заменяет последовательность `get_metadata_details` + `list_modules` + `get_module_structure` одним запросом - экономит round-trips. Поддерживает уровни детализации.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `target` | да | FQN объекта (`Catalog.Products`, `CommonModule.MyModule`, `Справочник.Номенклатура`) или путь модуля (`CommonModules/MyModule/Module.bsl`) |
| `depth` | нет | `minimal` (metadata + список модулей), `standard` (+ структура методов, по умолчанию), `full` (+ исходный код) |
| `focusMethod` | нет | Имя метода для детального анализа - только его исходник включается в режиме `full` |
| `includeSource` | нет | Включать исходный код независимо от `depth`. По умолчанию: `false` для minimal/standard, `true` для full |
| `maxMethods` | нет | Макс. методов в структуре на модуль (по умолчанию 30) |

**Совет:** Используй перед тем как начать доработку объекта - один вызов вместо трех.

#### `diff_module` - Сравнение модуля с VCS
Показывает что изменилось в BSL-модуле по сравнению с предыдущей версией в git: добавленные/измененные/удаленные методы, построчный diff. Критично для code review.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `modulePath` | нет* | Путь от `src/` (`Documents/MyDoc/ObjectModule.bsl`). Альтернатива `objectName` + `moduleType` |
| `objectName` | нет* | Полное имя объекта (`Document.MyDoc`, `DataProcessor.MyProcessor`, `Документ.МойДок`) |
| `moduleType` | нет | Тип модуля (с `objectName`): `ObjectModule` (по умолчанию), `ManagerModule`, `FormModule`, `CommandModule`, `RecordSetModule` |
| `mode` | нет | `summary` (обзор методов, по умолчанию), `unified` (полный git diff), `methods` (отдельный diff на каждый измененный метод) |
| `contextLines` | нет | Количество строк контекста для `unified` (по умолчанию 3) |
| `formName` | нет | Имя формы (обязательно при `moduleType=FormModule`) |
| `commandName` | нет | Имя команды (обязательно при `moduleType=CommandModule`) |

**Новый файл:** если модуль не в VCS - вернет `isNewFile: true` и список всех методов как добавленных.

---

### 2. Code Search

#### `search_in_code` — Полнотекстовый поиск по коду
Поиск по всем BSL-модулям конфигурации. Поддерживает текст и regex, регистрозависимость, контекстные строки, фильтрацию по пути и типу метаданных.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `query` | да | Текст поиска или regex-паттерн |
| `isRegex` | нет | Использовать как regex (по умолчанию false) |
| `caseSensitive` | нет | Регистрозависимый поиск (по умолчанию false) |
| `fileMask` | нет | Фильтр по подстроке пути модуля (`CommonModules`, `Documents/SalesOrder`) |
| `metadataType` | нет | Фильтр по типу метаданных (`documents`, `catalogs`, `commonModules` и т.д.) |
| `contextLines` | нет | Кол-во строк контекста (по умолчанию 2, макс. 5) |
| `maxResults` | нет | Макс. совпадений (по умолчанию 100, макс. 500) |
| `outputMode` | нет | Режим вывода: `full` (совпадения с контекстом, по умолчанию), `count` (только количество, быстро), `files` (список файлов с числом совпадений) |

#### `get_content_assist` — Автодополнение кода
Получает предложения автодополнения в конкретной позиции BSL-файла. Открывает файл в редакторе EDT.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `filePath` | да | Путь к BSL-файлу |
| `line` | да | Номер строки (1-based) |
| `column` | да | Номер колонки (1-based) |
| `contains` | нет | Фильтр по подстроке (через запятую: `Insert,Add`) |
| `extendedDocumentation` | нет | Полная документация (по умолчанию false) |
| `limit` | нет | Макс. предложений |
| `offset` | нет | Пропустить N предложений (пагинация) |

---

### 3. Metadata Inspection

#### `get_metadata_objects` — Список объектов метаданных
Возвращает Name, Synonym, Comment, Type, наличие модулей. Поддерживает фильтрацию.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `metadataType` | нет | Тип: `all`, `documents`, `catalogs`, `informationRegisters`, `accumulationRegisters`, `commonModules`, `enums`, `constants`, `reports`, `dataProcessors`, `exchangePlans`, `businessProcesses`, `tasks`, `commonAttributes`, `eventSubscriptions`, `scheduledJobs` |
| `nameFilter` | нет | Частичное совпадение имени (регистронезависимо) |
| `language` | нет | Язык синонимов (`en`, `ru`) |
| `limit` | нет | Макс. результатов (по умолчанию 100) |

#### `get_metadata_details` — Детальные свойства объектов
Возвращает полные свойства объектов метаданных (реквизиты, ТЧ, формы, макеты и т.д.).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objectFqns` | да | Массив FQN: `['Catalog.Products', 'Document.SalesOrder']` |
| `full` | нет | Все свойства (true) или ключевые (false, по умолчанию) |
| `language` | нет | Язык синонимов |

#### `find_references` — Поиск ссылок на объект метаданных
Находит все места использования объекта: в других метаданных, в BSL-коде с номерами строк, формах, ролях, подсистемах. Работает только для top-level объектов.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objectFqn` | да | FQN объекта (`Catalog.Products`, `CommonModule.Common`) |
| `limit` | нет | Макс. результатов на категорию (по умолчанию 100) |
| `deep` | нет | `true` — производные типы (Type[Reference]/[Manager]/[Selection]/[Object]/[Cache]/[List]) (1.31) |
| `skipBsl` | нет | `true` — пропустить медленную BSL-фазу, вернуть только metadata-ссылки за секунды. Полезно для крупных объектов вроде `Справочник.Сотрудники` (1.40.6) |
| `bslOnly` | нет | `true` — только BSL-код, без metadata back-references. Взаимоисключим с `skipBsl` (1.40.6) |
| `categories` | нет | CSV whitelist: `back,produced,predefined,fields,bsl`. Default — все включены (1.40.6) |
| `timeoutSeconds` | нет | Soft timeout до возврата Pending JSON. Range `[5, 120]`, default 30 (1.41) |
| `runKey` | нет | Resume polling предыдущего запроса — передать `runKey` из Pending response. Те же params → тот же runKey (1.41) |

**Pending pattern (1.41):** на больших объектах BSL-фаза легко 30-120 сек. При timeout инструмент возвращает JSON `{status:"Pending", runKey, elapsedMs}` — повторный вызов с тем же `runKey` ждёт finальный результат. Bounded executor 2/8/queue=20 предотвращает thread starvation при параллельных запросах.

#### `rename_metadata_object` — Переименование с рефакторингом
Переименовывает объект метаданных или реквизит с каскадным обновлением всех ссылок: BSL-код, формы, метаданные. Работает в режиме preview + confirm.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objectFqn` | да | FQN объекта. Top-level: `Catalog.Products`. Вложенный: `Document.SalesOrder.Attribute.Amount` |
| `newName` | да | Новое имя |
| `confirm` | нет | `true` — выполнить. По умолчанию `false` — только preview |
| `disableIndices` | нет | Индексы точек изменений для пропуска через запятую (`'2,3,5'`) |
| `maxResults` | нет | Макс. точек изменений в preview (по умолчанию 20, `0` = без ограничений) |

**Workflow:** первый вызов без `confirm` → просмотр изменений → второй вызов с `confirm=true`. Через `disableIndices` можно исключить отдельные изменения.

#### `delete_metadata_object` — Удаление с очисткой ссылок
Удаляет объект метаданных или реквизит с очисткой ссылок. Работает в режиме preview + confirm.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objectFqn` | да | FQN объекта (`Catalog.Products`, `Document.SalesOrder.Attribute.Amount`) |
| `confirm` | нет | `true` — выполнить. По умолчанию `false` — только preview |

#### `add_metadata_attribute` — Добавление реквизита
Добавляет новый реквизит к объекту метаданных (справочник, документ, регистр и др.) через EDT.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `parentFqn` | да | FQN родительского объекта (`Catalog.Products`, `Document.SalesOrder`) |
| `attributeName` | да | Имя нового реквизита |

#### `get_configuration_properties` — Свойства конфигурации
Имя, синоним, комментарий, вариант скрипта, режим совместимости и т.д.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта (без него — первый проект конфигурации) |

---

### 4. Platform Documentation

#### `get_platform_documentation` — Документация платформы
Документация по типам, методам, свойствам и встроенным функциям платформы 1С. Поддерживает русские и английские имена.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `typeName` | да | Имя типа: `ValueTable`, `ТаблицаЗначений`, `Array`, `Structure` |
| `memberName` | нет | Фильтр по методу/свойству: `Add`, `Insert`, `Count` |
| `memberType` | нет | Тип: `method`, `property`, `constructor`, `event`, `all` |
| `category` | нет | Категория: `type` (типы платформы) или `builtin` (встроенные функции) |
| `language` | нет | Язык вывода: `en` или `ru` (по умолчанию `en`) |
| `projectName` | нет | Для определения версии платформы |
| `limit` | нет | Макс. результатов (по умолчанию 50) |

---

### 5. Error Checking and Validation

#### `get_problem_summary` — Сводка проблем
Количество проблем по проектам и уровням серьёзности (ERRORS, BLOCKER, CRITICAL, MAJOR, MINOR, TRIVIAL).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта (без него — все проекты) |

#### `get_project_errors` — Детальные ошибки проекта
Возвращает код проверки, описание, расположение объекта, уровень серьёзности. Фильтрация по объектам, серьёзности, ID проверки.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта |
| `objects` | нет | Фильтр по FQN: `['Document.SalesOrder', 'Catalog.Products']` |
| `severity` | нет | Фильтр: `ERRORS`, `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `TRIVIAL` |
| `checkId` | нет | Фильтр по ID проверки (подстрока, например `ql-temp-table-index`) |
| `limit` | нет | Макс. результатов (по умолчанию 100, макс. 1000) |

#### `get_check_description` — Описание проверки EDT
Markdown-описание проверки: объяснение, примеры, как исправить.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `checkId` | да | ID проверки (например `begin-transaction`, `ql-temp-table-index`) |

#### `revalidate_objects` — Перевалидация объектов
Запускает повторную валидацию проекта или конкретных объектов.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `objects` | нет | Массив FQN для валидации. Пустой массив = весь проект |

#### `validate_query` — Валидация запросов 1С
Проверяет текст запроса в контексте проекта — синтаксис и семантика. Поддерживает режим СКД (DCS).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `queryText` | да | Текст запроса на языке запросов 1С |
| `dcsMode` | нет | Режим СКД (по умолчанию false). Включить для запросов СКД |

#### `clean_project` — Очистка проекта
Обновляет файлы с диска, очищает маркеры валидации, запускает полную перевалидацию.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта (без него — все проекты EDT) |

---

### 6. Form Inspection and Editing

#### `get_form_screenshot` — Скриншот формы
Получает PNG-скриншот формы из WYSIWYG-редактора EDT. Возвращает изображение как embedded resource. Без параметров — снимает скриншот текущего открытого редактора формы.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта EDT. Обязателен если указан `formPath` |
| `formPath` | нет | FQN формы через точку: `Catalog.Products.Forms.ItemForm`, `Document.SalesOrder.Forms.DocumentForm`, `CommonForm.MyForm`. Без него — текущий открытый редактор |
| `refresh` | нет | Принудительное обновление WYSIWYG перед снимком (по умолчанию false) |

**Примечание:** Нестабильно — иногда возвращает чёрное изображение. Попробовать `refresh: true` или перезапустить EDT.

#### `edit_form` — Редактирование управляемой формы (backward-compat alias в 1.42)

**В 1.42 предпочтительно использовать `edit_metadata`** — там собран полный набор форменных операций (~22 ops) включая новые из 1.42:

- `add_field`, `add_group`, `add_button`, `add_table`, `add_decoration`, `add_radio_button` — UI-элементы
- `add_button standardCommand=PostAndClose|Write|Generate|...` — 22 stock platform commands с auto-icon (1.42)
- `add_table autoGenerateColumns=true` — автогенерация колонок из ТЧ с префиксом родителя (1.42)
- `add_decoration elementType=Picture picture=StdPicture.X` — декорация-картинка (1.42)
- `add_form_attribute`, `remove_form_attribute` (с `deleteDataItems`+`preservedDataPaths`) (1.42)
- `add_form_attribute_column`, `add_dynamic_list_table`
- `add_command_handler`, `add_form_event_handler` (auto-stub в модуле формы) (1.42)
- `add_form_command_interface_item` / `remove_form_command_interface_item` / `set_form_command_interface_item_property` — навигационная панель + панель команд (1.42)
- `set_property` (с formatHelp tag для format/editFormat и picture-without-representation warning в 1.42)
- `setup_settings_composer_on_form` — СКД на любой форме
- `list_pictures` — поиск среди 763 stock + CommonPicture.*
- `move_item` / `remove_form_item`

`edit_form` остаётся как backward-compat alias к `edit_metadata` form-операциям.

| Параметр edit_form | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `formFqn` | да | FQN формы (`Catalog.Products.Form.ItemForm`) |
| `operation` | да | `add_field`, `add_group`, `add_button`, `add_table`, `add_decoration`, `remove_item`, `help` |
| `name` | нет | Имя элемента (обязателен для add/remove операций) |
| `title` | нет | Подпись/заголовок элемента |
| `elementType` | нет | Для `add_field`: `InputField` (по умолчанию), `CheckBox`, `RadioButton`, `Label`, `Image`. Для `add_group`: `UsualGroup` (по умолчанию), `Pages`, `Page`, `Column`, `CommandBar`. Для `add_decoration`: `Label` (по умолчанию) или `Picture` |
| `dataPath` | нет | Путь данных для привязки поля (`Object.Name`, `Object.Products`) |
| `parentName` | нет | Имя родительского контейнера. С 1.42 принимает `<TableName>КоманднаяПанель` / `<TableName>КонтекстноеМеню` для размещения в командной панели или контекстном меню таблицы |
| `beforeName` | нет | Вставить перед элементом с этим именем |
| `standardCommand` | нет | (1.42) Bind кнопки к stock-команде платформы (PostAndClose, Write, Generate, Refresh, ...). 22 frequent с auto-icon |
| `autoGenerateColumns` | нет | (1.42) В `add_table` с dataPath — автогенерация FormField для каждой колонки ТЧ с префиксом родителя |
| `picture` | нет | (1.42) Картинка для `add_decoration elementType=Picture`. Валидируется PictureValidator |

**Совет:** Начинай с `operation: "help"` — возвращает детальную документацию операций с примерами.
**Совет:** `add_button` без `standardCommand` автоматически создает связанную команду с именем `<name> + Command` и обработчик в модуле.
**B1 коллизия имён** (1.42): операции `add_field`/`add_group`/`add_button`/`add_table`/`add_decoration` отказывают если имя уже занято на форме (включая command bars / context menus таблиц) — это предотвращает render-time crash 1С клиента.

---

### 7. Tags and Organization

#### `get_tags` — Список тегов проекта
Пользовательские метки для организации объектов. Возвращает имя, цвет, описание, количество объектов.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |

#### `get_objects_by_tags` — Объекты по тегам
Объекты с указанными тегами (ANY из списка). Возвращает описания тегов и FQN объектов.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `tags` | нет | Массив имён тегов: `['Important', 'NeedsReview']` |
| `limit` | нет | Макс. объектов на тег (по умолчанию 100) |

---

### 8. Workspace and Tasks

#### `list_projects` — Список проектов workspace
Все проекты с именами, путями, типами и natures. Без параметров.

#### `get_bookmarks` — Закладки
Сообщение закладки, путь к файлу, номер строки.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Фильтр по проекту |
| `filePath` | нет | Фильтр по подстроке пути |
| `limit` | нет | Макс. результатов (по умолчанию 100, макс. 1000) |

#### `get_tasks` — Задачи (TODO/FIXME)
Задачи из кода (TODO, FIXME и т.д.) с приоритетами.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Фильтр по проекту |
| `filePath` | нет | Фильтр по подстроке пути |
| `priority` | нет | Фильтр: `high`, `normal`, `low` |
| `limit` | нет | Макс. результатов (по умолчанию 100, макс. 1000) |

#### `get_edt_version` — Версия EDT
Возвращает версию 1C:EDT. Без параметров.

---

### 9. Application Management

#### `get_applications` — Список приложений (информационных баз)
ID приложения, имя, тип, состояние обновления. ID нужен для `update_database` и `debug_launch`.

**Важно:** Вызывать от основного проекта конфигурации, не от расширения. Приложения привязаны к конфигурации, расширение не имеет собственных приложений.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT (основная конфигурация, не расширение) |

#### `update_database` — Обновление базы данных
Полное (full reload) или инкрементальное обновление. Требует `applicationId` из `get_applications`.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `applicationId` | да | ID приложения из `get_applications` |
| `fullUpdate` | нет | Полная перезагрузка (true) или инкрементальная (false, по умолчанию) |
| `autoRestructure` | нет | Автоматическая реструктуризация (по умолчанию true) |

#### `debug_launch` — Запуск отладки
Запускает приложение в режиме отладки через существующую конфигурацию запуска.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `applicationId` | да | ID приложения из `get_applications` |
| `updateBeforeLaunch` | нет | Обновить БД перед запуском (по умолчанию true) |

---

### 10. Debugging

Группа инструментов для пошаговой отладки BSL-кода: точки останова, ожидание срабатывания, инспекция переменных, вычисление выражений, управление выполнением, запуск YAXUnit-тестов.

**Типичный цикл:** `debug_launch` (или `yaxunit_tests mode=debug`) → `set_breakpoint` → `wait_for_break` → `get_variables` / `evaluate_expression` → `step` / `resume`.

#### `debug_status` - Статус debug-сессий
Возвращает активные debug-запуски: режим (debug/run), приостановлена ли цель, количество потоков, строка верхнего frame если приостановлено.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `applicationId` | нет | Фильтр по id приложения |

#### `set_breakpoint` - Установка breakpoint
Устанавливает точку останова на строку BSL-модуля. Принимает EDT-относительный путь (`CommonModules/Foo/Module.bsl`) или абсолютный путь файла.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Имя проекта EDT (обязателен при EDT-относительном пути) |
| `module` | да | Путь к модулю (EDT-относительный или абсолютный) |
| `lineNumber` | да | Номер строки (1-based) |

**Совет:** После установки вызывай `wait_for_break` чтобы блокирующе ждать срабатывания.

#### `list_breakpoints` - Список активных breakpoints
Возвращает все установленные точки останова. Опциональный фильтр по проекту.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | нет | Фильтр по проекту |

#### `remove_breakpoint` - Удаление breakpoint
Удаляет точку останова. Можно передать либо `breakpointId` (возвращенный из `set_breakpoint`), либо координаты `projectName` + `module` + `lineNumber`.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `breakpointId` | нет | ID маркера из `set_breakpoint` |
| `projectName` | нет | Имя проекта (при поиске по координатам) |
| `module` | нет | Путь модуля (при поиске по координатам) |
| `lineNumber` | нет | Номер строки (при поиске по координатам) |

#### `wait_for_break` - Ожидание срабатывания breakpoint
Блокирующе ждет suspend-событие (срабатывание breakpoint) на указанном приложении. При срабатывании возвращает снимок приостановленного потока/frame. При таймауте возвращает `{hit: false}` (не прерывая запуск - можно вызвать снова).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `applicationId` | да | ID приложения запущенной debug-сессии |
| `timeout` | нет | Окно ожидания в секундах (по умолчанию 60) |

#### `resume` - Продолжить выполнение
Возобновляет приостановленный debug-поток или все потоки debug-цели. Передать `threadId` (из `wait_for_break`) или `applicationId` (возобновить все потоки цели).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `threadId` | нет | ID потока из `wait_for_break` |
| `applicationId` | нет | ID приложения (возобновляет все потоки цели) |

#### `step` - Пошаговое выполнение
Шагает приостановленный debug-поток. Блокирующе ждет следующего SUSPEND-события (или таймаута), возвращает новый снимок frame.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `threadId` | да | ID потока из `wait_for_break` |
| `kind` | да | Вид шага: `over`, `into`, `out` |
| `timeout` | нет | Окно ожидания в секундах (по умолчанию 30) |

#### `get_variables` - Переменные стек-frame
Читает переменные из stack-frame приостановленного потока. Передать `frameRef` из `wait_for_break` (предпочтительно) или `threadId` + `frameIndex`. Для раскрытия вложенных структур используй `expandPath`.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `frameRef` | нет | Стабильная ссылка на frame из `wait_for_break` |
| `threadId` | нет | ID потока (альтернатива `frameRef`) |
| `frameIndex` | нет | Индекс frame (0-based, при использовании `threadId`) |
| `expandPath` | нет | Путь через точку для раскрытия вложенной переменной (`Объект.Товары`) |

#### `evaluate_expression` - Вычисление BSL-выражения
Вычисляет произвольное BSL-выражение в контексте приостановленного stack-frame. **ВНИМАНИЕ:** выполняет произвольный BSL-код в запущенном 1С-приложении - может изменить состояние.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `frameRef` | да | Стабильная ссылка на frame из `wait_for_break` |
| `expression` | да | BSL-выражение для вычисления |

#### `yaxunit_tests` (1.40) - Унифицированный запуск YAXUnit-тестов
Объединяет `run` и `debug` режимы в одном инструменте + 6 встроенных help-топиков + auto-sync ИБ перед запуском.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `mode` | нет | `run` (default) — синхронный polling до timeout, или `debug` — запуск с breakpoints. |
| `help` | нет | `topics` / `writing` / `assertions` / `setup` / `events` / `advanced` — Markdown справка по YAxUnit. Когда задан, остальные параметры игнорируются. |
| `launchConfigurationName` | нет | Имя Run Configuration EDT (preferred). |
| `projectName` | нет | Имя проекта EDT (если launchConfigurationName не указан). |
| `applicationId` | нет | ID приложения из `get_applications`. |
| `extensions` | нет | Имена расширений через запятую (фильтр). |
| `modules` | нет | Имена общих модулей с тестами через запятую. |
| `tests` | нет | Имена тестов `Module.Method` через запятую. |
| `suites` | нет | Имена тестовых наборов через запятую. |
| `tags` | нет | Имена тегов тестов через запятую. |
| `contexts` | нет | `Server` / `Client` / `ExternalConnection` через запятую. |
| `timeout` | нет | Окно polling в секундах (default 60). |
| `updateBeforeLaunch` | нет | Default `true` — auto-sync ИБ через `ApplicationUpdater` (FULL_UPDATE_REQUIRED auto-switch). Установи `false` чтобы пропустить. |

**Pending-механизм:** при истечении timeout возвращается `status=Pending` с `runKey`. Повторный вызов с теми же параметрами забирает финальный отчёт. Запуск НЕ убивается. Полный отчёт также пишется в `report.md` рядом с `junit.xml`.

**Сценарий debug + breakpoint:** `set_breakpoint` → `yaxunit_tests mode=debug tests=Module.Method` → ждёт через `wait_for_break` или возвращает `Pending` если breakpoint hit → `get_variables` / `evaluate_expression` / `step` / `resume` → повторный `yaxunit_tests` за финальным отчётом.

**Hint при 0 тестов:** Markdown-отчёт автоматически содержит 3 типичные причины (тесты не зарегистрированы в `ИсполняемыеСценарии` / фильтры не совпадают / расширение YAxUnit не подключено) + ссылку на `help=writing` / `help=setup`.

**Требования:** существующая Run Configuration в EDT + расширение YAxUnit (`.cfe`) подключено к ИБ. См. `yaxunit_tests help=setup`.

**Legacy backward-compat:** `run_yaxunit_tests` / `debug_yaxunit_tests` остаются зарегистрированы как aliases. В новом коде используй `yaxunit_tests`.

---

### 11. Profiling

Замер производительности (profiling) BSL-кода: счетчики вызовов и тайминги на каждую выполненную строку. Требует активную debug-сессию.

#### `start_profiling` - Включить замер производительности
Переключает замер производительности на активной debug-цели. После включения - запустить тестовый сценарий, затем вызвать `get_profiling_results`.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `applicationId` | да | ID приложения запущенной debug-сессии |

**Требования:** активная debug-сессия (`debug_launch` или `yaxunit_tests mode=debug`).

#### `get_profiling_results` - Результаты профилирования
Возвращает данные профилирования: по модулю, по строке - количество вызовов, время, процент. Опциональный фильтр по имени модуля и минимальной частоте вызовов.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `moduleFilter` | нет | Фильтр подстроки по имени модуля |
| `minFrequency` | нет | Включать только строки вызванные минимум N раз (по умолчанию 1) |

---

### 12. Extension Borrowing & HTTP Services

#### `extension_workshop` — Заимствование объектов в расширение (1.35, child-FQN в 1.43)

Конфигурационное расширение заимствует объекты из базовой конфигурации через `IModelObjectAdopter.adoptAndAttach`. Поддерживает 6 операций.

| Операция | Назначение |
|---|---|
| `borrow_object` | Заимствует один FQN (Catalog / Document / HTTPService / ...). Опц. `recursive=true` для children. |
| `borrow_objects` | Batch-режим. `objectFqns=["Catalog.A","Document.B"]`. Результат на каждый FQN. |
| `borrow_child` | Один дочерний элемент: `Catalog.X.Form.Y`, `Document.X.Attribute.Y`, `Catalog.X.Template.Y` и т.п. Параметр `childKind=Form/Attribute/TabularSection/Template/Command/Dimension/Resource` (русские aliasы тоже). |
| `borrow_form_item` | Элемент внутри заимствованной формы (`itemName`). |
| `borrow_module` | Конкретный модуль объекта (`moduleType=ObjectModule/ManagerModule/RecordSetModule/CommandModule/ValueModule`). |
| `list_borrowed` | Сводка discovered adopt API + hint про GUI. |

**Обязательные параметры:** `projectName` (имя проекта-расширения), `baseProjectName` (имя проекта-базовой конфигурации), `objectFqn`.

**Поддерживаемые child-FQN форматы (1.43):**
```
Catalog.Products.Form.ItemForm
Document.SalesOrder.Attribute.Total
Document.SalesOrder.TabularSection.Items
Catalog.Products.Template.PrintForm
Catalog.Products.Command.OpenCard
InformationRegister.Rates.Dimension.Currency
InformationRegister.Rates.Resource.Rate
```

**Резолвер:** `BmExtensionHelper.resolveSourceEObject` сначала пробует `IBmTransaction.getTopObjectByFqn(fqn)` (формы/шаблоны/команды — BM top objects в EDT 2026.1), при null — EMF-walk через рефлексию `getForms()/getAttributes()/getTabularSections()/getTemplates()/getCommands()/getDimensions()/getResources()` от parent MdObject. До 1.43 любой FQN глубже двух сегментов отвергался как «Source object not found».

**Lifecycle wait (1.43):** перед резолвом extension-проекта вызывается `LifecycleWaiter.waitForProjectStarted(dtProject, 30s)`, чтобы первая попытка после открытия workspace / `clean_project` не падала с «DT project layer not initialised».

**Эквивалент в `edit_metadata`:** `adopt_object`, `adopt_objects`, `adopt_child`, `adopt_form_item`, `adopt_module` — те же 5 операций через единый конструктор. `adopt_child` композирует FQN автоматически из `ownerFqn + childKind + name` если не передан полный `targetFqn`.

**Когда использовать:**
- Прямые заимствования удобнее через `extension_workshop` (отдельный tool, описание операций сразу под рукой)
- В составе batch-workflow по правке расширения — через `edit_metadata batch=true` с `adopt_*` операциями

#### `edit_metadata create_http_service` — Композитное создание HTTP-сервиса (1.43)

Создаёт HTTPService root + первый URLTemplate + Method + `HTTPServices/<Name>/Module.bsl` с handler-стабом за один вызов. Работает в основной конфигурации и в расширении (паттерн `IBmGlobalEditingContext.execute()` + `attachTopObject`).

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта (основной или расширения) |
| `name` | да | Имя HTTP-сервиса |
| `rootURL` | нет | Single identifier (`apiOrders`, `api_orders`). Default `<name>`. Слэши в начале/конце убираются автоматически. `/` **внутри** отвергается с подсказкой (платформа требует один сегмент). |
| `aliases` | нет | Comma-separated псевдонимы пути |
| `reuseSessions` | нет | Boolean — переиспользовать HTTP-сессии |
| `sessionMaxAge` | нет | Int секунд |
| `urlTemplateName` | нет | Имя первого URLTemplate. Default `Template1` |
| `urlTemplate` | нет | URL pattern (`/clients/{id}`). Default `/<urlTemplateName>`. Bare `/` подменяется (отвергается валидатором). |
| `methodName` | нет | Имя первого Method. Default `Get` |
| `httpMethod` | нет | GET/POST/PUT/DELETE/MERGE/PATCH/HEAD/OPTIONS/TRACE/CONNECT/PROPFIND/PROPPATCH/MKCOL/COPY/MOVE/LOCK/UNLOCK/Any. Default `GET` |
| `handler` | нет | Имя процедуры-обработчика. Default `<urlTemplateName><methodName>` (EDT wizard convention) |
| `createModule` | нет | Создавать Module.bsl. Default `true` |
| `withHandlerStub` | нет | Вставить процедуру `Функция <handler>(Запрос) Возврат Новый HTTPСервисОтвет(200); КонецФункции` в Module.bsl. Default `true` |
| `dryRun` | нет | Превью BM-транзакции с откатом |

#### Связанные HTTP-services операции

| Операция | Назначение |
|---|---|
| `add_url_template` | Добавить URLTemplate в существующий HTTPService (`projectName`, `ownerFqn=HTTPService.X`, `name`, `template`). |
| `add_url_template_method` | Добавить Method в URLTemplate. Параметры: `templateName`, `name`, `httpMethod`, `handler`, `withHandlerStub`. `withHandlerStub=true` идемпотентно append-ит процедуру в Module.bsl. |
| `remove_url_template` | Удалить URLTemplate (и все его методы) из HTTPService. |
| `remove_url_template_method` | Удалить Method из URLTemplate. |

**Правила валидации (1С платформа, EDT 2026.1):**
- `rootURL` — single identifier `[a-zA-Z0-9_]+`. Слэши внутри запрещены. Используйте `apiOrders`, `api_orders`.
- `urlTemplate` — непустой `/path` или `/path/{param}`. Голый `/` отвергается.
- `httpMethod` — уникален в рамках одной URLTemplate. Два метода с `httpMethod=POST` в одном template → MAJOR error.

---

## Typical Workflows

### Анализ незнакомого модуля
1. `get_module_structure` — получить список методов
2. `read_method_source` — прочитать нужные методы
3. `get_method_call_hierarchy` — понять, откуда вызываются

### Поиск использований объекта метаданных
1. `find_references` — все ссылки на объект (код, формы, роли, подсистемы)
2. `search_in_code` — дополнительный текстовый поиск если нужно

### Проверка качества после изменений
1. `revalidate_objects` — перевалидировать изменённые объекты
2. `get_project_errors` с фильтром по объектам — получить ошибки
3. `get_check_description` — понять суть ошибки и как исправить

### Валидация запросов
1. `validate_query` — проверить текст запроса на синтаксис и семантику
2. `validate_query` с `dcsMode=true` — проверить запрос СКД

### Обновление и тестирование
1. `get_applications` — получить ID приложения
2. `update_database` — обновить базу
3. `debug_launch` — запустить в отладке

### Навигация к определению
1. `go_to_definition` с `symbol` — найти определение метода или объекта
2. `get_symbol_info` — получить тип символа в конкретной позиции
3. `read_method_source` — прочитать код, если нужно больше контекста

### Рефакторинг метаданных
1. `find_references` — проверить все ссылки перед изменением
2. `rename_metadata_object` с `preview=true` — просмотр каскадных изменений
3. `rename_metadata_object` с `confirm=true` — выполнить переименование
4. `revalidate_objects` — проверить результат

### Модификация метаданных через EDT
1. `add_metadata_attribute` — добавить реквизит (вместо ручного редактирования XML)
2. `delete_metadata_object` — удалить объект/реквизит с очисткой ссылок
3. `write_module_source` — записать BSL-код с автопроверкой синтаксиса

### Изучение API платформы
1. `get_platform_documentation` с `typeName` — документация по типу
2. `get_content_assist` — автодополнение в контексте кода

### Сбор контекста перед доработкой
1. `ai_context` с `target=<FQN объекта>` и `depth=standard` - одним вызовом получить метаданные + список модулей + структуру методов
2. При необходимости углубиться в конкретный метод - `depth=full` + `focusMethod=<имя>`

### Code review изменений модуля
1. `diff_module` с `mode=summary` - обзор какие методы добавлены/изменены/удалены
2. Если нужен детальный разбор - `mode=methods` (отдельный diff на каждый измененный метод)
3. Для полного контекста изменений - `mode=unified` (git diff)

### Отладка BSL-кода
1. `get_applications` - получить `applicationId`
2. `debug_launch` - запустить приложение в режиме отладки
3. `set_breakpoint` - установить breakpoint в нужном методе
4. Запустить сценарий через UI приложения или `yaxunit_tests mode=debug`
5. `wait_for_break` - дождаться срабатывания breakpoint
6. `get_variables` с `frameRef` - посмотреть значения переменных
7. `evaluate_expression` - вычислить BSL-выражение в контексте остановки
8. `step` (over/into/out) или `resume` - продолжить выполнение
9. `remove_breakpoint` - снять breakpoint после завершения

### Профилирование BSL-кода
1. `debug_launch` или `yaxunit_tests mode=debug` - активная debug-сессия
2. `start_profiling` с `applicationId` - включить замер
3. Выполнить тестовый сценарий (через UI или YaxUnit)
4. `get_profiling_results` с `moduleFilter` - получить данные по вызовам/времени
5. Использовать `minFrequency` для фильтрации редко вызываемых строк

### Модификация формы без ручного XML (1.42 snake_case + расширенные ops)
1. `edit_metadata operation=help topic=workflow` или `edit_form operation=help` - справка по операциям
2. `get_form_screenshot` - визуально оценить текущее состояние формы
3. `edit_metadata operation=add_field|add_group|add_button|add_table|add_decoration` (через `edit_form` тоже работает) - добавить элементы. Имена проверяются на коллизию (1.42 guard)
4. `edit_metadata operation=add_button standardCommand=Записать` - 22 stock команд платформы с auto-icon (1.42)
5. `edit_metadata operation=add_table autoGenerateColumns=true` - один FormField на каждую колонку ТЧ с префиксом родителя (1.42)
6. `edit_metadata operation=add_decoration kind=Picture picture="StdPicture.Find" projectName=...` - валидация картинки через `PictureValidator` (1.42)
7. `edit_metadata operation=add_form_event_handler event=ПриСозданииНаСервере` - auto-stub в модуль формы (22 события из FormEventRegistry в 1.42)
8. `edit_metadata operation=remove_form_attribute name=... deleteDataItems=true` - удаляет реквизит со всеми bound items (1.42)
9. `edit_metadata operation=remove_item path=...` - удалить любой элемент по FQN
10. `get_form_screenshot` с `refresh=true` - проверить результат

### Запуск YAxUnit-тестов (1.40 unified)
1. `yaxunit_tests help=writing` - первое знакомство с YAxUnit (см. также `help=assertions|setup|events|advanced`)
2. `yaxunit_tests mode=run` с `applicationId` или `configName` - синхронный прогон с timeout polling
3. При истечении timeout вернётся JSON `Pending` + `runKey` - повторить вызов с **теми же** параметрами (НЕ менять filters/configName), забирается финальный отчёт
4. Filters: `tests=Тест_X,Тест_Y`, `suites=ТестыКадры`, `extensions=YAxUnit`, `modules=*Тесты*`, `tags=smoke,fast`, `contexts=Server,Client`
5. При `0 tests run` - проверить активность YAxUnit-расширения в ИБ (Конфигурация → Расширения → Active = Yes), затем `help=setup`
6. Отладка теста: `set_breakpoint` → `yaxunit_tests mode=debug tests=Тест_X` → `wait_for_break` → `get_variables`/`step`
7. `updateBeforeLaunch=true` (default) - автоматический `update_database` перед запуском, чтобы не висеть на модальном "Обновить?"

### Создание метаданных через edit_metadata (1.42 snake_case)
1. `edit_metadata operation=help topic=workflow` - типичный сценарий "от нуля до готовой подсистемы"
2. `edit_metadata operation=help topic=availability` - probe какие группы реально доступны на текущем EDT runtime
3. `edit_metadata operation=create_object objectType=Catalog name=Products` - для `CommonForm` автоматически создаётся вторая форма-обёртка (3.8.4). С 1.42 операции в `snake_case`.
4. `edit_metadata operation=add_object_attribute name=Article type=String` - идемпотентно. При несовпадении свойств возвращается тег `propertyMismatch` с массивом `mismatches` - НЕ ретраить, использовать `set_object_property`
5. `edit_metadata operation=create_form formType=Generic layout=empty` - 11 базовых свойств применяются автоматически (3.8.3), без них форма не открывается в редакторе
6. `edit_metadata operation=remove_object_attribute name=Article` - если поле используется в формах, нужно `cascadeForms=true` (без него получите `requiresCascadeForms` + preview `affectedForms`)
7. EventSubscription: `add_event_subscription_handler handler="CommonModule.X.Method"` или `"X.Method"` - префикс добавляется автоматически (3.8.1)
8. Extension-проект: НЕ передавать `privileged=true` для CommonModule, НЕ комбинировать `global=true+server=true` - early-fail (3.8.2)
9. HTTP services (1.42): `add_url_template` (URL-шаблон) → `add_url_template_method` (метод GET/POST/PUT/DELETE; default handler = `<template><method>`; возвращает hint с сигнатурой для `write_module_source`)
10. Object commands (1.42): `create_object_command` → автоматически создаёт `CommandModule.bsl` со стабом `ОбработкаКоманды`. `remove_command` для удаления.

---

## Release timeline 1.31 — 1.43

**1.43.0** — fix: child-FQN borrow + IExtensionProject resolve в EDT 2026.1, feat: HTTP-service composite create + remove ops + auto handler-stub. Tool count: без изменений (70+).

- **Child-FQN в `extension_workshop` / `edit_metadata adopt_*`** — `BmExtensionHelper.resolveSourceMdObject` переименован в `resolveSourceEObject` и расширен. Теперь распознаёт FQN с child-сегментами: `Catalog.X.Form.Y`, `Document.X.Attribute.Y`, `Document.X.TabularSection.Y`, `Catalog.X.Template.Y`, `Catalog.X.Command.Y`, `InformationRegister.X.Dimension.Y`, `InformationRegister.X.Resource.Y`. Стратегия: сначала `IBmTransaction.getTopObjectByFqn(fqn)` (формы и шаблоны в 2026.1 — top objects), при null — EMF-fallback через рефлексию (`getForms()`/`getAttributes()`/`getTabularSections()`/`getTemplates()`/`getCommands()`/`getDimensions()`/`getResources()`). Поддержаны русские aliasы childKind в FQN: `Форма`, `Реквизит`, `ТабличнаяЧасть`, `Макет`, `Команда`, `Измерение`, `Ресурс`. До 1.43 резолвер резал FQN на 2 сегмента и любая глубина возвращала `Source object not found`.
- **`adopt_child` композирует FQN из `ownerFqn + childKind + name`** — параметр `name` раньше игнорировался, дочерний элемент никогда не заимствовался. Теперь, если `targetFqn` не передан или короче 3 сегментов, FQN собирается автоматически. `adopt_form_item` без `childKind` подразумевает `Form` (короткая запись). Кто передаёт полный FQN через `targetFqn` — поведение не изменилось.
- **Schema `edit_metadata`** — параметры `baseProjectName` / `targetFqn` / `objectFqn` / `childKind` объявлены явно. Раньше читались из params, но не были в `getInputSchema()` — строгие MCP-клиенты дропали их.
- **Fix "Could not resolve IExtensionProject"** — корневой баг в EDT 2026.1: `BmExtensionHelper.resolveExtensionProject` ходил через `IDtProjectManager.getDtProject()` → `instanceof IExtensionProject` (всегда false) и `IDtProject.getAdapter(IExtensionProject)` (всегда null). Правильный путь — `IV8ProjectManager.getProject(IDtProject)` → `IV8Project instanceof IExtensionProject`. Используется в `GetConfigurationPropertiesTool` и теперь в `BmExtensionHelper`. Симптом до фикса: каждый `borrow_*` падал даже на чистом V8ExtensionNature-проекте.
- **Lifecycle wait** — перед резолвом extension project вызывается `LifecycleWaiter.waitForProjectStarted(dtProject, 30s)`. Первая попытка после открытия workspace / `clean_project` больше не падает с "DT project layer not initialised".
- **`ExtensionWorkshopTool.help workflow`** — добавлены примеры child-FQN форматов; описание `objectFqn` в schema перечисляет все поддерживаемые формы.
- **`edit_metadata create_http_service`** (новая операция) — композитное создание HTTP-сервиса в один вызов. Создаёт корневой `HTTPService` + первый `URLTemplate` + `Method` + `HTTPServices/<Name>/Module.bsl` со стабом handler-процедуры. Работает в основной конфигурации и в расширении (паттерн `IBmGlobalEditingContext.execute()` + `attachTopObject` — тот же что в `opCreateObject`). Параметры: `projectName`, `name`, `rootURL` (default `/<name>`), `aliases`, `reuseSessions`, `sessionMaxAge`, `urlTemplateName` (default `Template1`), `urlTemplate` (default `/`), `methodName` (default `Get`), `httpMethod` (default `GET`), `handler` (default `<urlTemplateName><methodName>` по EDT-конвенции), `createModule` (default `true`), `withHandlerStub` (default `true`), `dryRun`.
- **`add_url_template_method withHandlerStub=true`** — опциональная авто-вставка handler-процедуры в `Module.bsl` HTTP-сервиса. Если процедура с таким именем уже есть — идемпотентно пропускает. По умолчанию `false` (обратная совместимость с 1.42).
- **`remove_url_template` / `remove_url_template_method`** (новые операции) — симметричные удалители для URLTemplate и Method. Параметры: `projectName`, `ownerFqn=HTTPService.X`, `name` (и `templateName` для method). При удалении URLTemplate все его методы убираются вместе.
- **Pre-dispatch fix для HTTP-services ops** — `add_url_template` и `add_url_template_method` (1.42) отсутствовали в `OPERATIONS` map и до 1.43 отклонялись pre-dispatch проверкой как «Unknown operation». Добавлены вместе с новыми ops 1.43.

**1.42** — крупное расширение работы с формами, командами и поиском. **Tool count: 70+** (добавлены два фасада + новые операции в `edit_metadata`). Главное:

- **Naming** — все operation names в `edit_metadata`, `code_search`, `launch_debugger` переведены на `snake_case` (`create_object`, `add_form_event_handler`, `text_search`, `add_breakpoint`, ...). Ранее использовались camelCase aliases — больше не работают. Tool names и JSON parameter keys остались в своих конвенциях (snake_case и camelCase соответственно).
- **`code_search`** — единый фасад с шестью операциями (`text_search`, `object_references`, `method_references`, `resolve_symbol`, `call_hierarchy`, `help`). Делегирует к `search_in_code` / `find_references` / `go_to_definition` / `get_method_call_hierarchy`. Standalone тулзы остаются для backward compat.
- **`launch_debugger`** — единый фасад с 16 действиями (`launch`, `add_breakpoint`, `wait_for_break`, `get_state`, `get_variables`, `step_over`, `step_into`, `step_out`, `resume`, `evaluate`, `start_profiling`, ...). Делегирует к 11 standalone debug-тулзам.
- **Forms** — добавлены `add_form_event_handler` (auto-stub в модуль формы по `FormEventRegistry` с 22 событиями), `remove_form_attribute` (с `deleteDataItems` обоих режимов и `preservedDataPaths`), `add_form_command_interface_item` / `remove_form_command_interface_item` / `set_form_command_interface_item_property` (навигационная панель и панель команд формы). `add_button` принимает `standardCommand` для 22 stock platform commands с auto-icon. `add_table` принимает `auto_generate_columns=true` (FormField для каждой колонки ТЧ с префиксом родителя). `set_form_item_property` валидирует `picture` через `PictureValidator` и возвращает `formatHelp` / picture-without-representation warning.
- **Object commands** — `create_object_command` / `remove_command` создают/удаляют Command в дереве объекта-владельца с заглушкой `ОбработкаКоманды` в `CommandModule.bsl`.
- **`find_references` multi-project scope** — `projectName` опционален. При отсутствии тулз через Eclipse-граф references находит проект-владелец FQN и расширяет scope на sister extensions / external. ProjectScopeResolver через `IProject.getReferencedProjects()`.
- **`search_in_code`** — pre-filter (быстрая проверка содержимого до line-by-line, ускорение в разы на больших конфигах), `wholeWord=true` (без префиксных false positives), `compact=true` (top-5 файлов + первые N matches).
- **External support** — `ExternalProjectResolver` резолвит DT-проекты `.epf`/`.erf` через `IBmTransaction.getTopObjectByFqn`. Прокинуто в `get_metadata_details`, `get_metadata_objects`, `find_references`. Ранее эти инструменты возвращали "Object not found" на DT-проектах.
- **Severity translation** — `get_project_errors` принимает группы `ERROR`/`WARNING`/`INFO`/`ALL` (с семантикой "не строже X") плюс legacy концретные `ERRORS`/`BLOCKER`/`CRITICAL`/`MAJOR`/`MINOR`/`TRIVIAL`/`NONE`. Ранее `MarkerSeverity.valueOf("ERROR")` тихо валился (правильное имя — `ERRORS`) и фильтр становился null. Теперь правильно покрывает все семь категорий и читает Eclipse `IMarker.PROBLEM` параллельно с EDT `IMarkerManager`.
- **Form name collision guard** — при `add_field`/`add_group`/`add_button`/`add_table`/`add_decoration` имя проверяется на коллизию с уже существующими элементами формы (включая command bars и context menus таблиц). Без guard две элемента с одним именем крашили клиент 1С при render формы.
- **EDT 2026.1 совместимость** — тот же ZIP работает на EDT 2025.x.

**1.42.2** — native MXL cell editing. `mxl_workshop` ops `set_cell`, `merge_cells`, `draw` теперь реально работают через `com._1c.g5.v8.dt.moxel.SpreadsheetDocument` model (без `ITemplateLayoutService`). Координаты 1-based. `getOrCreateSpreadsheet` отказывает на templates с `templateType ≠ SpreadsheetDocument` (защита от уничтожения DCS). `draw` валидирует JSON layout до открытия BM transaction (без partial writes). `Import-Package` для moxel помечены `resolution:=optional`, `cellOpsAvailable()` ловит `NoClassDefFoundError`.

**1.42.1** — type-specific factory dispatch для EDT 2026.1. В EDT 2026.1 `MdClassFactory` НЕ имеет generic `createAttribute()` / `createTabularSection()` / `createForm()` / `createCommand()` — только type-specific (`createCatalogAttribute`, `createDocumentForm` и т.д.). Расширен `BmObjectHelper` методами `createOwnerScopedObject(owner, kind)` и `createGenericObject(typeName)` с 3-стратегией dispatch: type-specific factory → generic factory → `MdClassPackage.eINSTANCE.get<Type>()` + `EFactory.create(eClass)`. Заменено 12 call sites (add_object_attribute, add_tabular_section, add_tabular_section_attribute, create_object_command, add_register_field, add_enum_value, op_create_object, add_url_template, add_url_template_method, create_form, add_template, BmDcsHelper, MxlWorkshopTool). Special case для `DataProcessor`/`Report` TabularSection (создаёт собственные subclasses `createDataProcessorTabularSectionAttribute`, не fall-through к generic). HTTP services фиксы: `createHTTPServiceURLTemplate` → `createURLTemplate`, `createHTTPServiceMethod` → `createMethod`.

**1.41** — закрытие 4 крупных deferred блоков. (1) `find_references` Pending bounded executor (2/8/queue=20) + clamps `timeoutSeconds∈[5,120]` — Variant A полностью работает. (2) `export_object` native: auto-detect ExternalDataProcessor → .epf, ExternalReport → .erf через project nature; 7 candidate APIs; Pending pattern; новый `PendingExportRegistry` (independent class). (3) Forms 3 ops landed natively через `BmFormHelper` extensions: `addFormAttributeColumn` (idempotent), `addDynamicListTable` (FormAttribute(DynamicList) + UI Table + wizard properties), `setupSettingsComposerOnForm` (Composer + 2 UI tables + RU/EN BSL snippets). (4) DCS 13 ops landed natively через `DcsWorkshopTool` extensions + 13 camelCase→snake_case aliases в `DCS_OP_ALIASES`. Tool count: 67 (без новых tools, только deeper coverage).

**1.40** — `edit_metadata` покрывает все 7 групп (~64 ops): Object 8 + propertyMismatch idempotency + cascadeForms; Specialized 7 (register fields/enum values/subsystem content/role rights/defined types/event subscription handler с auto-prefix); Forms 15 (11 native, 4 deferred в 1.40.x); Templates 4 (1 native + 3 graceful mxlApiNotFound); Extensions 5 (все native); DCS 27 (14 native + 13 deferred в 1.40.x); Common 2 (универсальные moveItem/removeItem). `yaxunit_tests` объединяет run/debug, добавляет Pending polling и 6 help-топиков. 4 защитных слоя (3.8.1-3.8.4) для headless метаданных. ApplicationUpdater FULL_UPDATE_REQUIRED auto-switch. Tool count: 64+ операций в одном инструменте.

**1.35 (consolidated)** — три tool: `dcs_workshop` (27 ops для DCS-схем), `mxl_workshop` (4 ops для MXL-макетов, runtime-probe), `extension_workshop` (5 ops для borrow-операций, runtime-probe). DCS direct save в расширениях через DcsExtensionExportHelper. edit_metadata расширен 10 ops (Specialized 8 + Common 2) с snake_case primary + camelCase aliases. EventStubGenerator three-tier (known map + runtime probe + fallback). Tool count: 54 → 57.

Серия additive-релизов 1.31 — 1.40 — все фичи реализованы через открытые EDT API без декомпиляции защищённых классов.

**Обновлённые tools (additive, без breaking changes):**

| Tool | Что добавлено | Версия |
|------|---------------|--------|
| `write_module_source` | Режимы `insertBefore`, `insertAfter` (параметр `line`); `validateAfterWrite=true` (default) с блоком `validation` в ответе; `persistenceSync*` — гарантированный sync на диск; `confirmFullReplace=true` обязателен при удалении >50%; 7 режимов вместо 5 | 1.31, рефакторинг на BmExportHelper в 1.34 |
| `get_project_errors` | `scope=session\|object\|project\|all` (default `session`, использует SessionChangeTracker); `fileFilter`, `waitForRefresh`; `tooManyErrors` summary при >200 на scope=project | 1.31 |
| `find_references` | `deep=true` помечает производные типы (Type[Reference] / Type[Manager] / Type[Selection] / Type[Object] / Type[Cache] / Type[List]) | 1.31 |
| `go_to_definition` | Levenshtein fallback для опечаток (через `MetadataTypeUtils.findSimilarObjects`) | 1.31 |

**Новые tools (всего +4, tool count 50 → 54):**

- **`get_form_structure`** (1.32) — JSON-дерево управляемой формы. Параметры `formPath`, `depth` (default 5, 0=unlimited), `subtree` (имя элемента-старта), `maxElements` (default 500). Возвращает `{root: {type, name, title, items[], properties: {dataPath, kind, commandName, visible, ...}}}`. Дополняет `get_form_screenshot` (PNG).
- **`get_object_help`** (1.32) — встроенная HTML-справка объекта в Markdown. Параметры `objectName` (FQN), `format` (markdown/html/text), `language` (ru/en/auto). Двухуровневая стратегия: BM API (`MdObject.getHelp()`) с fallback на disk scan `src/<dir>/<name>/Help/*.html`. Конвертация через CopyDown.
- **`export_object`** (1.32 → 1.41 native) — сборка проекта внешней обработки/отчёта в .epf/.erf. Auto-detect kind через extension `outputPath` или project nature (`V8External*Nature`); rejection unsupported extensions (`.txt` и т.п.). 7 candidate API services probed via reflection (`IEpfExportService`, `IExternalObjectExporter`, `IExportPlatformService`, `IBinaryDataExporter`, `EpfExportService`, `IMetadataExporter`, `IBmExporter`). `BmExportHelper.forceExportAndWait` синхронизирует BM перед probe. Pending pattern с `timeoutSeconds`/`runKey` (как у `find_references`). При недоступности всех 7 API — структурированный тег `exportApiNotFound` с `phase=probe|invocation` + `triedServices` array + GUI-fallback hint.
- **`edit_metadata`** (1.33-1.40) — единый конструктор с ~64 операциями в 7 группах. В 1.40 все 7 групп implemented: Objects 8 + propertyMismatch idempotency + cascadeForms; Specialized 7 (register fields/enum values/subsystem content/role rights/defined types/event subscription handler с auto-prefix); Forms 15 (11 native, 4 deferred в 1.40.x); Templates 4 (1 native + 3 graceful mxlApiNotFound); Extensions 5 (все native); DCS 27 (14 native + 13 deferred в 1.40.x); Common 2 (универсальные moveItem/removeItem). Все поддерживают `dryRun=true`.

**Использование `edit_metadata`:**
```
edit_metadata operation=help                          # каталог ~64 операций
edit_metadata operation=help topic=workflow           # типичный сценарий
edit_metadata operation=help topic=availability       # probe API runtime
edit_metadata operation=help topic=types              # English/Russian типы
edit_metadata operation=help topic=composerWorkflow   # SettingsComposer на форме
edit_metadata operation=help topic=matrixWorkflow     # матричный отчёт

# Object группа
edit_metadata operation=createObject projectName=X objectType=Catalog name=Products dryRun=true
edit_metadata operation=addObjectAttribute ownerFqn=Catalog.Products name=Article
edit_metadata operation=removeObjectAttribute ownerFqn=Catalog.Products name=Article cascadeForms=true

# Forms группа (1.40, alias к edit_form для add*/removeFormItem)
edit_metadata operation=createForm projectName=X ownerFqn=Catalog.Products formName=ItemForm formType=ItemForm setAsDefault=true
edit_metadata operation=addField formFqn=Catalog.Products.Form.ItemForm name=Article dataPath=Object.Article
edit_metadata operation=listPictures projectName=X filter=add  # поиск картинок (StandardPictures + CommonPicture.*)

# Templates группа (1.40)
edit_metadata operation=addTemplate projectName=X ownerFqn=Catalog.Products name=PrintForm templateType=Spreadsheet  # 10 типов: Spreadsheet/Text/DCS/Appearance/Binary/HTML/Geo/Graph/ActiveDocument/AddIn

# HTTP-services (1.43): композитное создание + удаление
edit_metadata operation=create_http_service projectName=X name=Orders                              # минимум: один вызов = HTTPService + Template1 + Get GET + Module.bsl со стабом
edit_metadata operation=create_http_service projectName=X name=Orders rootURL=/api/orders \
  urlTemplateName=ByID urlTemplate=/order/{id} methodName=Read httpMethod=GET handler=ReadOrderByID
edit_metadata operation=add_url_template projectName=X ownerFqn=HTTPService.Orders name=List template=/orders
edit_metadata operation=add_url_template_method projectName=X ownerFqn=HTTPService.Orders templateName=List name=All httpMethod=GET withHandlerStub=true  # auto-stub в Module.bsl
edit_metadata operation=remove_url_template_method projectName=X ownerFqn=HTTPService.Orders templateName=List name=All
edit_metadata operation=remove_url_template projectName=X ownerFqn=HTTPService.Orders name=List
# В расширении тот же синтаксис, projectName=<extension project name>

# Extensions группа (1.40 batch + 1.43 child-FQN)
edit_metadata operation=adopt_objects projectName=Ext baseProjectName=Base targetFqn=Catalog.A,Document.B,Document.C  # CSV per-object result
edit_metadata operation=adopt_object projectName=Ext baseProjectName=Base targetFqn=Document.SalesOrder recursive=true  # с детьми
# 1.43: adopt_child / adopt_form_item принимают composed FQN или явные ownerFqn + childKind + name
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base ownerFqn=Catalog.Products childKind=Form name=ItemForm
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base targetFqn=Document.Sales.Attribute.Discount  # equivalent
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base targetFqn=InformationRegister.Rates.Resource.Rate
# childKind aliases на русском также поддержаны: Форма / Реквизит / ТабличнаяЧасть / Макет / Команда / Измерение / Ресурс

# Specialized группа (1.40)
edit_metadata operation=addEnumValue ownerFqn=Enum.Statuses name=Active
edit_metadata operation=addRegisterField ownerFqn=InformationRegister.Q name=Status fieldKind=resource
edit_metadata operation=addEventSubscriptionHandler eventName=BeforeWrite handler="MyModule.Handler"  # 3.8.1 нормализация в "CommonModule.MyModule.Handler"

# DCS группа (1.40, 14 native via DcsWorkshopTool delegate)
edit_metadata operation=createReportSchema projectName=X ownerFqn=Report.Sales
edit_metadata operation=addDataSet projectName=X ownerFqn=Report.Sales name=Main type=Query queryText="ВЫБРАТЬ..."
edit_metadata operation=addCalculatedField projectName=X ownerFqn=Report.Sales name=Total expression="Sum * Qty"
edit_metadata operation=repairReportSchema projectName=X ownerFqn=Report.Sales  # лечение схемы-фантома в расширениях
```

**Идемпотентность 1.40 (новое):**
- При повторном вызове `addObjectAttribute`/`addTabularSection`/`createObject` с уже существующим именем + другими свойствами — ответ содержит `propertyMismatch` тег с массивом `[{name, requested, existing}]`. AI агент должен вызвать `setObjectProperty` для каждого diff'а, а НЕ ретраить add*.
- При совпадении свойств — `idempotentSkip` тег (success no-op).

**Cascade form cleanup 1.40 (новое):**
- При `removeObjectAttribute`/`removeTabularSection`/`removeTabularSectionAttribute` с активными ссылками на удаляемое поле в формах — операция отказывает с `requiresCascadeForms` тегом + `affectedForms` preview.
- Передать `cascadeForms=true` (или `force=true`) — поля автоматически удаляются со всех форм владельца.

**Защитные слои (1.34):**
- **Standard attribute conflict guard** — `edit_metadata addObjectAttribute` блокирует имена, совпадающие с платформенными стандартными реквизитами (Code, Date, Number, Posted, LineNumber и др., включая русские варианты). Через `MdObject.getStandardAttributes()` reflection с fallback на захардкоженный список.
- **Supplier lock guard** — best-effort detection через рефлексию `getUserSupportMode` / `getSupportMode` / `getSupport` / `isOnSupport`. При обнаружении `NOT_ALLOWED` / `DENIED` / `DISABLED` блокирует с инструкцией "включить редактирование в EDT или работать через расширение". При недоступности API guard НЕ блокирует.
- **BmExportHelper** — гарантированный sync на диск для всех BM-mutating tools. `forceExportAndWait()` ждёт сегменты EXP_O / EXP_B / FORM_EXT (10s soft cap).

**Защитные слои (1.40, headless метаданные):**
- **3.8.1 EventSubscription handler auto-prefix** — `addEventSubscriptionHandler handler="..."` принимает `"Method"` или `"CommonModule.X.Method"`, нормализуется к полной форме. Если CommonModule не существует — early-fail с тегом `commonModuleNotFound`.
- **3.8.2 Extension CommonModule guards** — в проекте-расширении блокирует `privileged=true` и комбинацию `global=true+server=true` (платформа отвергает на UpdateDBCfg).
- **3.8.3 Generic+empty form 11 base properties** — `createForm formType=Generic layout=empty` автоматически получает 11 базовых свойств (групповая раскладка, командная панель и др.), без них форма не открывается в EDT-редакторе и таблицы схлопываются до нулевой высоты.
- **3.8.4 CommonForm auto inner form** — `createObject CommonForm.X` автоматически создаёт внутреннюю форму вторым шагом (.mdo + Form.form + Module.bsl рядом).

**Closed in 1.40.x / 1.41:**
- **1.40.1**: `setRoleRight` / `setDefinedTypeTypes` mutation writers (BmRightsHelper + BmDefinedTypeHelper + cached Class.forName + EAccess enum probe + EcoreUtil.copy для TypeItem)
- **1.40.2**: `addRadioButton` (delegate к `addField` с `elementType=RadioButton`)
- **1.40.6**: `find_references` filters `skipBsl`/`bslOnly`/`categories` (Variant B)
- **1.41 Phase 1**: `find_references` Pending Variant A — bounded executor + clamps
- **1.41 Phase 2**: `export_object` kind detection + 7 candidate APIs + Pending
- **1.41 Phase 3**: Forms 3 ops native — `addFormAttributeColumn`, `addDynamicListTable`, `setupSettingsComposerOnForm`
- **1.41 Phase 4**: DCS 13 ops native — `addUserField`, `addSettingsTable`/`Chart`/`Variant`/`Order`/`FilterGroup`, `addSettingsSelectedField`/`removeSettingsSelectedField`, `setSettingsParameter`, `removeSettingsItem` (universal cascade by path), `removeConditionalAppearance`, `setDataSetFieldAppearance`, `setOutputParameter`. При недоступности EDT factory методов — структурированный тег `dcsFactoryMethodNotFound` с `triedMethods` array.

**Closed in 1.42.x:**
- HTTP services tooling — `add_url_template` + `add_url_template_method` (1.42; URLTemplate + Method native через `MoxelFactory`-style `MdClassFactory.createURLTemplate/createMethod`)
- 3 Template cell ops: `set_cell`, `merge_cells`, `draw` — **native в 1.42.2** через `com._1c.g5.v8.dt.moxel.SpreadsheetDocument` API (раньше surface `mxlApiNotFound`). Координаты 1-based. `draw` принимает batch JSON `{cells:[{row,col,text,language}], merges:[{fromRow,fromCol,toRow,toCol}]}`.
- Type-specific factory dispatch (1.42.1) — `add_object_attribute`, `add_tabular_section`, `create_object_command`, `create_form`, `add_register_field` теперь работают на EDT 2026.1 через `create<OwnerType><Kind>()` (раньше падали на `MdClassFactory.createAttribute() not available`).

**Still deferred (1.43+):**
- WSDL/SOAP tooling, REST endpoint generator
- Removal of `RunYaxunitTestsTool` / `DebugYaxunitTestsTool` aliases (до 2.0)
- Сжатие `EditFormTool` / `DcsWorkshopTool` до alias-стабов (до 2.0)

## AI-agent helper tools (1.40.x)

Три композитных tool, добавленных в 1.40.x patches для AI-friendly workflows.

#### `generate_health_snapshot` — Полный health snapshot за один вызов
Объединяет errors + metadata stats + project metrics + anti-patterns в одном response, заменяя 5+ tool-calls. Один вызов даёт AI агенту полную картину состояния проекта.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `includeAntiPatterns` | нет | Запустить `detect_query_anti_patterns` (default true) |
| `includeMetrics` | нет | Запустить `project_metrics` (default true) |
| `errorScope` | нет | `session\|project\|all` (default `session`) |

#### `code_template` — Boilerplate BSL templates
11 готовых шаблонов BSL-кода для типичных задач: HTTP-service handler, scheduled job, event subscription, form module skeleton, object events, print form, background job, EDP method, YAxUnit test suite и др.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `template` | да | Имя шаблона: `httpService`, `scheduledJob`, `eventSubscription`, `formModule`, `objectEvents`, `printForm`, `backgroundJob`, `edpMethod`, `yaxunit`, `commonModule`, `apiClient` |
| `params` | нет | JSON-объект с подстановками (имена методов/реквизитов) |
| `language` | нет | `ru\|en` (default `ru`) |

#### `extension_lifecycle` — Workflow для расширений
Многошаговый guided workflow: probe extension → adopt object → generate event handler → revalidate. Заменяет цепочку из 4-5 tool calls для типичного сценария "добавить перехватчик метода в расширении".

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя расширения (V8ExtensionNature project) |
| `step` | да | `probe\|adopt\|generateHandler\|validate\|all` |
| `targetFqn` | нет | FQN заимствуемого объекта (для adopt/generateHandler) |
| `methodName` | нет | Имя метода для перехвата (для generateHandler) |
| `interceptType` | нет | `before\|after\|instead` (default `before`) |

При вызове deferred операции `edit_metadata` возвращает понятное сообщение с probe API availability и подсказкой про GUI fallback — это нормальное поведение, не ошибка реализации.
