# AI-EDT: типовые сценарии работы

> Накопленный практикой порядок вызовов. Каталог инструментов - остальные файлы `references/`.
> Имена сверялись с реестром проекта на ревизии `4fb31770` (28.07.2026); полноты снимок не гарантирует.
>
> **Синтаксис.** Сценарии ниже записаны короткими standalone-именами (`find_references`, `search_in_code`,
> `get_project_errors`, `debug_launch`, `go_to_definition`, `get_method_call_hierarchy`). Под пресетом
> Canonical эти имена скрыты из `tools/list`, хотя и остаются вызываемыми, поэтому канонический вызов - через
> фасад:
>
> | Короткое имя в сценарии | Канонический вызов |
> |---|---|
> | `search_in_code` | `code_search operation=text_search` |
> | `find_references` | `code_search operation=object_references` |
> | `go_to_definition` | `code_search operation=resolve_symbol` |
> | `get_method_call_hierarchy` | `code_search operation=call_hierarchy` |
> | `get_project_errors`, `revalidate_objects`, `clean_project`, `validate_for_export` | `diagnostics operation=<то же имя>` |
> | `debug_launch` | `launch_debugger action=launch` |
> | `set_breakpoint` | `launch_debugger action=add_breakpoint` |
> | `remove_breakpoint`, `list_breakpoints`, `set_exception_breakpoint`, `run_to_line`, `wait_for_break`, `get_variables`, `set_variable`, `resume`, `debug_status`, `start_profiling`, `get_profiling_results` | `launch_debugger action=<то же имя>` |
> | `evaluate_expression` | `launch_debugger action=evaluate` |
> | `step mode=over/into/out` | `launch_debugger action=step_over` / `step_into` / `step_out` |
> | `terminate_launch` | `launch_debugger action=terminate` |
> | `get_applications`, `update_database` | `infobase_admin operation=<то же имя>` |
> | `sync_control` | проще напрямую: `sync_control operation=status`. Через фасад действие идет отдельным параметром: `infobase_admin operation=sync_control syncOperation=status` |
> | `get_tags`, `get_objects_by_tags`, `get_bookmarks`, `get_tasks` | `workspace_marks operation=<то же имя>` |
>
> Старые имена (`debug_launch`, `set_breakpoint`, `terminate_launch`) фасад отладчика принимает и как алиасы,
> но канонические - из таблицы. Полный список действий - `launch_debugger action=help`.
>
> Инструменты без фасада (`write_module_source`, `validate_query`, `read_method_source`,
> `get_module_structure`, `ai_context` и другие) вызываются по имени.

## Typical Workflows

### Анализ незнакомого модуля
1. `get_module_structure` - получить список методов
2. `read_method_source` - прочитать нужные методы
3. `get_method_call_hierarchy` - понять, откуда вызываются

### Поиск использований объекта метаданных
1. `find_references` - все ссылки на объект (код, формы, роли, подсистемы)
2. `search_in_code` - дополнительный текстовый поиск если нужно

### Проверка качества после изменений
1. `revalidate_objects` - перевалидировать измененные объекты
2. `get_project_errors` с фильтром по объектам - получить ошибки
3. `get_check_description` - понять суть ошибки и как исправить
4. `ask_1c_ai` (1c-naparnik) - обязательная проверка качества после любого изменения BSL, включая код,
   записанный через `write_module_source`, и стабы, созданные операциями `edit_metadata`

### Валидация запросов
1. `validate_query` - проверить текст запроса на синтаксис и семантику
2. `validate_query` с `dcsMode=true` - проверить запрос СКД

### Обновление и тестирование
1. `get_applications` - получить ID приложения
2. `validate_for_export` - ОБЯЗАТЕЛЬНО до записи в ИБ; findings блокируют обновление, сперва исправить
3. `update_database` - обновить базу
4. `debug_launch` - запустить в отладке

Тот же пункт 2 нужен и когда обновление неявное: у `yaxunit_tests` по умолчанию `updateBeforeLaunch=true`,
то есть запуск тестов сам вызывает `update_database`.

### Навигация к определению
1. `go_to_definition` с `symbol` - найти определение метода или объекта
2. `get_symbol_info` - получить тип символа в конкретной позиции
3. `read_method_source` - прочитать код, если нужно больше контекста

### Перед разрушительной операцией

`insights operation=impact_analysis` считает радиус поражения объекта: что на него ссылается, какой
уровень серьезности (LOW / MEDIUM / HIGH) и что рекомендуется. Плагин прямо предписывает звать его
ПЕРЕД `delete_metadata_object`, `rename_metadata_object`, `remove_object_attribute` и прочими
операциями, которые что-то убирают. Одного `find_references` для этого мало: он показывает ссылки,
но не оценивает последствия.

### Рефакторинг метаданных
1. `find_references` - проверить все ссылки перед изменением
2. `rename_metadata_object` с `preview=true` - просмотр каскадных изменений
3. `rename_metadata_object` с `confirm=true` - выполнить переименование
4. `revalidate_objects` - проверить результат

### Модификация метаданных через EDT
1. `add_metadata_attribute` - добавить реквизит (вместо ручного редактирования XML)
2. `delete_metadata_object` - удалить объект/реквизит с очисткой ссылок
3. `write_module_source` - записать BSL-код с автопроверкой синтаксиса

### Изучение API платформы
1. `get_platform_documentation` с `typeName` - документация по типу
2. `get_content_assist` - автодополнение в контексте кода

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

### Модификация формы без ручного XML
1. `edit_metadata operation=help topic=workflow` или `edit_form operation=help` - справка по операциям
2. `get_form_screenshot` - визуально оценить текущее состояние формы
3. `edit_metadata operation=add_field|add_group|add_button|add_table|add_decoration` (через `edit_form` тоже работает) - добавить элементы. Имена проверяются на коллизию
4. `edit_metadata operation=add_button standardCommand=Записать` - 22 stock команд платформы с auto-icon
5. `edit_metadata operation=add_table autoGenerateColumns=true` - один FormField на каждую колонку ТЧ с префиксом родителя
6. `edit_metadata operation=add_decoration kind=Picture picture="StdPicture.Find" projectName=...` - валидация картинки через `PictureValidator`
7. `edit_metadata operation=add_form_event_handler event=ПриСозданииНаСервере` - auto-stub в модуль формы (22 события из FormEventRegistry)
8. `edit_metadata operation=remove_form_attribute name=... deleteDataItems=true` - удаляет реквизит со всеми bound items
9. `edit_metadata operation=remove_item path=...` - удалить любой элемент по FQN
10. `get_form_screenshot` с `refresh=true` - проверить результат

### Запуск YAxUnit-тестов
1. `yaxunit_tests help=writing` - первое знакомство с YAxUnit (см. также `help=assertions|setup|events|advanced`)
2. `validate_for_export` - обязательно, когда `updateBeforeLaunch` не выключен явно (по умолчанию `true`,
   см. пункт 8): тогда запуск тестов сам выполняет `update_database`, то есть пишет конфигурацию в ИБ. При
   явном `updateBeforeLaunch=false` записи нет и проверка не требуется
3. `yaxunit_tests mode=run` с `applicationId` или `configName` - синхронный прогон с timeout polling
4. При истечении timeout вернется JSON `Pending` + `runKey` - повторить вызов с **теми же** параметрами (НЕ менять filters/configName), забирается финальный отчет
5. Filters: `tests=Тест_X,Тест_Y`, `suites=ТестыКадры`, `extensions=YAxUnit`, `modules=*Тесты*`, `tags=smoke,fast`, `contexts=Server,Client`
6. При `0 tests run` - проверить активность YAxUnit-расширения в ИБ (Конфигурация → Расширения → Active = Yes), затем `help=setup`
7. Отладка теста: `set_breakpoint` → `yaxunit_tests mode=debug tests=Тест_X` → `wait_for_break` → `get_variables`/`step`
8. `updateBeforeLaunch=true` (default) - автоматический `update_database` перед запуском, чтобы не висеть на модальном "Обновить?"

### Создание метаданных через edit_metadata

> Набор операций `edit_metadata` меняется чаще остального каталога. Авторитетный перечень - `operation=help`
> (и `topic=availability` для текущего runtime); ниже - проверенные практикой приемы и порядок, а не полный
> список операций.
1. `edit_metadata operation=help topic=workflow` - типичный сценарий "от нуля до готовой подсистемы"
2. `edit_metadata operation=help topic=availability` - probe какие группы реально доступны на текущем EDT runtime
3. `edit_metadata operation=create_object objectType=Catalog name=Products` - для `CommonForm` автоматически создается вторая форма-обертка.
4. `edit_metadata operation=add_object_attribute name=Article type=String` - идемпотентно. При несовпадении свойств возвращается тег `propertyMismatch` с массивом `mismatches` - НЕ ретраить, использовать `set_object_property`
5. `edit_metadata operation=create_form formType=Generic layout=empty` - 11 базовых свойств применяются автоматически, без них форма не открывается в редакторе
6. `edit_metadata operation=remove_object_attribute name=Article` - если поле используется в формах, нужно `cascadeForms=true` (без него получите `requiresCascadeForms` + preview `affectedForms`)
7. EventSubscription: `add_event_subscription_handler handler="CommonModule.X.Method"` или `"X.Method"` - префикс добавляется автоматически
8. Extension-проект: НЕ передавать `privileged=true` для CommonModule, НЕ комбинировать `global=true+server=true` - early-fail
9. HTTP services: `add_url_template` (URL-шаблон) → `add_url_template_method` (метод GET/POST/PUT/DELETE; default handler = `<template><method>`; возвращает hint с сигнатурой для `write_module_source`)
10. Object commands: `create_object_command` → автоматически создает `CommandModule.bsl` со стабом `ОбработкаКоманды`. `remove_command` для удаления.
11. **МАССОВОЕ создание (batch=true) - против N round-trip'ов.** За ОДИН вызов много операций: `edit_metadata batch=true operations=[{"operation":"create_object",...},{"operation":"add_object_attribute",...},...]`. Массив идет по порядку, КАЖДАЯ op в своей BM-транзакции, `projectName`/`ownerFqn`/`dryRun` наследуются от внешнего вызова (per-item переопределяет). Поздние op видят ранние (`create_object` -> `add_object_attribute` к новому объекту). Ответ: `batchResults[]` (index/operation/ok/response) + счетчики ok/fail. **Кейс "38 ролей": НЕ 38+ пар вызовов, а ОДИН** `batch=true` с `[{create_object Role1},{set_role_right ...},{create_object Role2},...]`. Работает для ЛЮБЫХ операций, не только adopt_*. Оговорка: не атомарно на все (каждая op - своя транзакция); нужна атомарность "все или ничего" - это отдельный запрос.
12. **Внешние обработки/отчеты - все через тулзы, руками в `.mdo` НЕ лезть.** Создание: `external_object_workshop operation=create kind=ExternalDataProcessor|ExternalReport name=X [parentProjectName=Y]` (создает DT-проект `.epf`/`.erf`, nature `V8ExternalObjectsNature`, `.mdo` c UUID; parentProjectName опционален). Наполнение - штатным `edit_metadata` по FQN корня: `add_object_attribute` / `add_tabular_section` / `add_template` на `ownerFqn=ExternalDataProcessor.X` РАБОТАЮТ. Формы - `create_form`; сборка - `validate_for_export` (обязательная проверка перед сборкой артефакта), затем `export_object` -> `.epf`.

---

```
# Object группа
edit_metadata operation=createObject projectName=X objectType=Catalog name=Products dryRun=true
edit_metadata operation=addObjectAttribute ownerFqn=Catalog.Products name=Article
edit_metadata operation=removeObjectAttribute ownerFqn=Catalog.Products name=Article cascadeForms=true

# Forms группа (alias к edit_form для add*/removeFormItem)
edit_metadata operation=createForm projectName=X ownerFqn=Catalog.Products formName=ItemForm formType=ItemForm setAsDefault=true
edit_metadata operation=addField formFqn=Catalog.Products.Form.ItemForm name=Article dataPath=Object.Article
edit_metadata operation=listPictures projectName=X filter=add  # поиск картинок (StandardPictures + CommonPicture.*)

# Templates группа
edit_metadata operation=addTemplate projectName=X ownerFqn=Catalog.Products name=PrintForm templateType=Spreadsheet  # 10 типов: Spreadsheet/Text/DCS/Appearance/Binary/HTML/Geo/Graph/ActiveDocument/AddIn

# HTTP-services: композитное создание + удаление
edit_metadata operation=create_http_service projectName=X name=Orders                              # минимум: один вызов = HTTPService + Template1 + Get GET + Module.bsl со стабом
edit_metadata operation=create_http_service projectName=X name=Orders rootURL=/api/orders \
  urlTemplateName=ByID urlTemplate=/order/{id} methodName=Read httpMethod=GET handler=ReadOrderByID
edit_metadata operation=add_url_template projectName=X ownerFqn=HTTPService.Orders name=List template=/orders
edit_metadata operation=add_url_template_method projectName=X ownerFqn=HTTPService.Orders templateName=List name=All httpMethod=GET withHandlerStub=true  # auto-stub в Module.bsl
edit_metadata operation=remove_url_template_method projectName=X ownerFqn=HTTPService.Orders templateName=List name=All
edit_metadata operation=remove_url_template projectName=X ownerFqn=HTTPService.Orders name=List
# В расширении тот же синтаксис, projectName=<extension project name>

# Extensions группа (batch + child-FQN)
edit_metadata operation=adopt_objects projectName=Ext baseProjectName=Base targetFqn=Catalog.A,Document.B,Document.C  # CSV per-object result
edit_metadata operation=adopt_object projectName=Ext baseProjectName=Base targetFqn=Document.SalesOrder recursive=true  # с детьми
# adopt_child / adopt_form_item принимают composed FQN или явные ownerFqn + childKind + name
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base ownerFqn=Catalog.Products childKind=Form name=ItemForm
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base targetFqn=Document.Sales.Attribute.Discount  # equivalent
edit_metadata operation=adopt_child projectName=Ext baseProjectName=Base targetFqn=InformationRegister.Rates.Resource.Rate
# childKind aliases на русском также поддержаны: Форма / Реквизит / ТабличнаяЧасть / Макет / Команда / Измерение / Ресурс

# Specialized группа
edit_metadata operation=addEnumValue ownerFqn=Enum.Statuses name=Active
edit_metadata operation=addRegisterField ownerFqn=InformationRegister.Q name=Status fieldKind=resource
edit_metadata operation=addEventSubscriptionHandler eventName=BeforeWrite handler="MyModule.Handler"  # нормализация в "CommonModule.MyModule.Handler"

# DCS группа
edit_metadata operation=createReportSchema projectName=X ownerFqn=Report.Sales
edit_metadata operation=addDataSet projectName=X ownerFqn=Report.Sales name=Main type=Query queryText="ВЫБРАТЬ..."
edit_metadata operation=addCalculatedField projectName=X ownerFqn=Report.Sales name=Total expression="Sum * Qty"
edit_metadata operation=repairReportSchema projectName=X ownerFqn=Report.Sales  # лечение схемы-фантома в расширениях
```

**Идемпотентность:**
- При повторном вызове `addObjectAttribute`/`addTabularSection`/`createObject` с уже существующим именем + другими свойствами - ответ содержит `propertyMismatch` тег с массивом `[{name, requested, existing}]`. AI агент должен вызвать `setObjectProperty` для каждого diff'а, а НЕ ретраить add*.
- При совпадении свойств - `idempotentSkip` тег (success no-op).

**Cascade form cleanup:**
- При `removeObjectAttribute`/`removeTabularSection`/`removeTabularSectionAttribute` с активными ссылками на удаляемое поле в формах - операция отказывает с `requiresCascadeForms` тегом + `affectedForms` preview.
- Передать `cascadeForms=true` (или `force=true`) - поля автоматически удаляются со всех форм владельца.

**Защитные слои:**
- **Standard attribute conflict guard** - `edit_metadata addObjectAttribute` блокирует имена, совпадающие с платформенными стандартными реквизитами (Code, Date, Number, Posted, LineNumber и др., включая русские варианты).
- **Supplier lock guard** - при обнаружении что объект на поддержке и режим прав `NOT_ALLOWED` / `DENIED` / `DISABLED` блокирует с инструкцией "включить редактирование в EDT или работать через расширение".
- **Гарантированный sync на диск** для всех BM-mutating tools (10s soft cap).

**Защитные слои (headless метаданные):**
- **EventSubscription handler auto-prefix** - `addEventSubscriptionHandler handler="..."` принимает `"Method"` или `"CommonModule.X.Method"`, нормализуется к полной форме. Если CommonModule не существует - early-fail с тегом `commonModuleNotFound`.
- **Extension CommonModule guards** - в проекте-расширении блокирует `privileged=true` и комбинацию `global=true+server=true` (платформа отвергает на UpdateDBCfg).
- **Generic+empty form 11 base properties** - `createForm formType=Generic layout=empty` автоматически получает 11 базовых свойств (групповая раскладка, командная панель и др.), без них форма не открывается в EDT-редакторе и таблицы схлопываются до нулевой высоты.
- **CommonForm auto inner form** - `createObject CommonForm.X` автоматически создает внутреннюю форму вторым шагом (.mdo + Form.form + Module.bsl рядом).

## AI-agent helper tools

Три композитных tool для AI-friendly workflows.

#### `generate_health_snapshot` - Полный health snapshot за один вызов
Объединяет errors + metadata stats + project metrics + anti-patterns в одном response, заменяя 5+ tool-calls. Один вызов дает AI агенту полную картину состояния проекта.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя проекта EDT |
| `includeAntiPatterns` | нет | Запустить `detect_query_anti_patterns` (default true) |
| `includeMetrics` | нет | Запустить `project_metrics` (default true) |
| `errorScope` | нет | `session\|project\|all` (default `session`) |

#### `code_template` - Boilerplate BSL templates
11 готовых шаблонов BSL-кода для типичных задач: HTTP-service handler, scheduled job, event subscription, form module skeleton, object events, print form, background job, EDP method, YAxUnit test suite и др.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `template` | да | Имя шаблона: `httpService`, `scheduledJob`, `eventSubscription`, `formModule`, `objectEvents`, `printForm`, `backgroundJob`, `edpMethod`, `yaxunit`, `commonModule`, `apiClient` |
| `params` | нет | JSON-объект с подстановками (имена методов/реквизитов) |
| `language` | нет | `ru\|en` (default `ru`) |

#### `extension_lifecycle` - Workflow для расширений
Многошаговый guided workflow: probe extension → adopt object → generate event handler → revalidate. Заменяет цепочку из 4-5 tool calls для типичного сценария "добавить перехватчик метода в расширении".

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `projectName` | да | Имя расширения (V8ExtensionNature project) |
| `step` | да | `probe\|adopt\|generateHandler\|validate\|all` |
| `targetFqn` | нет | FQN заимствуемого объекта (для adopt/generateHandler) |
| `methodName` | нет | Имя метода для перехвата (для generateHandler) |
| `interceptType` | нет | `before\|after\|instead` (default `before`) |

При вызове deferred операции `edit_metadata` возвращает понятное сообщение с probe API availability и подсказкой про GUI fallback - это нормальное поведение, не ошибка реализации.