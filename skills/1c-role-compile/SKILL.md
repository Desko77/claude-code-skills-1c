---
name: 1c-role-compile
description: Создание роли 1С из описания прав. Используй когда нужно создать новую роль с набором прав на объекты
argument-hint: <JsonPath> <OutputDir>
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# /role-compile - генерация роли 1С из JSON DSL

Принимает JSON-определение роли → генерирует `Roles/Имя.xml` (метаданные) и `Roles/Имя/Ext/Rights.xml` (права). UUID автоматически.

## Параметры и команда

| Параметр | Описание |
|----------|----------|
| `JsonPath` | Путь к JSON-определению роли |
| `OutputDir` | Корень выгрузки конфигурации (где `Configuration.xml`, `Roles/` и т.д.) |

```powershell
powershell.exe -NoProfile -File skills/1c-role-compile/scripts/role-compile.ps1 -JsonPath "<json>" -OutputDir "<ConfigDir>"
```

Создает `{OutputDir}/Roles/Имя.xml` и `{OutputDir}/Roles/Имя/Ext/Rights.xml`. Регистрирует `<Role>` в `Configuration.xml`.

## JSON DSL

### Структура

```json
{ "name": "ИмяРоли", "synonym": "Отображаемое имя", "objects": [...], "templates": [...] }
```

Необязательные: `comment` (""), `setForNewObjects` (false), `setForAttributesByDefault` (true), `independentRightsOfChildObjects` (false).

### Shorthand-строки и объектная форма

```json
"objects": [
  "Catalog.Номенклатура: @view",
  "Document.Реализация: @edit",
  "DataProcessor.Загрузка: @view",
  "InformationRegister.Цены: Read, Update",
  { "name": "Document.Продажа", "preset": "view", "rights": {"Delete": false}, "rls": {"Read": "#Шаблон(\"\")"} }
]
```

- Shorthand: `"Тип.Имя: @пресет"` или `"Тип.Имя: Право1, Право2"`
- Объектная форма: `preset` + `rights` (переопределения) + `rls` (ограничения)

### Пресеты

| Пресет | Действие |
|--------|----------|
| `@view` | Просмотр - Read, View (+InputByString для справочников/документов; Use+View для обработок/отчетов) |
| `@edit` | Полное редактирование - CRUD + Interactive* + Posting (документы) |

`@` обязателен в shorthand. В объектной форме - `"preset": "view"` без `@`.

### Замыкание прав

Навык дописывает права, которые платформа добавляет сама при загрузке роли (замер 8.3.27):
`Edit` влечет `Read`, `Update`, `View`; `View` у обработки влечет `Use`; `InteractivePostingRegular`
влечет `InteractivePosting`, а тот - `Posting`, и далее по зависимостям. Полный набор правил - в
`scripts/role-compile.py` (`GLOBAL_RIGHT_IMPL` и `RIGHT_IMPL_BY_TYPE`). Файл роли после сборки
совпадает с выгрузкой после первой загрузки в базу.

Права выдаются в порядке выгрузки платформы (`RIGHT_ORDER`), а не в порядке ввода.

Явное `false` конфликтует с замыканием (`Edit` включен, `Read` выключен) - платформа отбрасывает
весь блок объекта при загрузке; навык предупреждает об этом в stderr.

### Права сервисов

У самих WebService и HTTPService прав нет - платформа отбрасывает такой блок при загрузке.
Право `Use` дается операции и методу: `"WebService.Обмен.Operation.Загрузить: Use"`,
`"HTTPService.Сервис.URLTemplate.Файлы.Method.get: Use"`.

### Русские синонимы

Поддерживаются русские типы (`Справочник`→Catalog, `Документ`→Document) и права (`Чтение`→Read, `Просмотр`→View). Смешивание допустимо: `"Справочник.Контрагенты: Чтение, View"`.

### Шаблоны RLS

```json
"templates": [{"name": "ДляОбъекта(Мод)", "condition": "ГДЕ Организация = &ТекОрг"}]
```

Ссылка в `rls`: `"#ДляОбъекта(\"\")"`. Символ `&` автоматически экранируется в XML.

## Примеры

### Простая роль

```json
{
  "name": "ЧтениеНоменклатуры", "synonym": "Чтение номенклатуры",
  "objects": ["Catalog.Номенклатура: @view", "Catalog.Контрагенты: @view", "DataProcessor.Загрузка: @view"]
}
```

### Роль с RLS

```json
{
  "name": "ЧтениеДокументовПоОрганизации",
  "synonym": "Чтение документов (ограничение по организации)",
  "objects": [
    "Catalog.Организации: @view",
    {"name": "Document.РеализацияТоваровУслуг", "preset": "view", "rls": {"Read": "#ДляОбъекта(\"\")"}}
  ],
  "templates": [{"name": "ДляОбъекта(Модификатор)", "condition": "ГДЕ Организация = &ТекущаяОрганизация"}]
}
```

Подробные таблицы пресетов, русских синонимов и дополнительные примеры - в `dsl-reference.md`.

## Верификация

```
/role-validate <RightsPath> [MetadataPath]  - проверка корректности XML, прав, RLS
/role-info <RightsPath>                     - визуальная сводка структуры
```
