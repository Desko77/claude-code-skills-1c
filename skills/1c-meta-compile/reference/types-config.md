# Конфигурационные объекты без собственных данных

Объекты, которые не хранят свои таблицы, а настраивают поведение конфигурации: общие реквизиты,
команды, формы, макеты, картинки, критерии отбора, последовательности, нумераторы, параметры сеанса,
хранилища настроек, функциональные опции и WS-ссылки.

Общее для всех: `name` обязателен, `synonym` по умолчанию выводится из имени, `comment` пишется как
задан.

## Ссылки на метаданные

Поля состава (`content`, `documents`, `use`, `documentMap`, `location` и подобные) принимают путь к
метаданным на русском или английском вперемешку - вид объекта переводится, имя остается как написано:

```
"Документ.РеализацияТоваров.Реквизит.Склад"  ->  Document.РеализацияТоваров.Attribute.Склад
"РегистрСведений.Настройки.Измерение.Организация" -> InformationRegister.Настройки.Dimension.Организация
```

Переводятся виды объектов (`Документ`, `Справочник`, `РегистрНакопления`, ...) и виды подчиненных
элементов: `Реквизит` -> Attribute, `ТабличнаяЧасть` -> TabularSection, `Измерение` -> Dimension,
`Ресурс` -> Resource, `Графа` -> Column, `ЗначениеПеречисления` -> EnumValue, `Форма` -> Form,
`Макет` -> Template, `Команда` -> Command, `ПризнакУчета` -> AccountingFlag,
`ПризнакУчетаСубконто` -> ExtDimensionAccountingFlag, `РеквизитАдресации` -> AddressingAttribute.

## CommonAttribute (Общий реквизит)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `valueType` | - | Type |
| `content` | `[]` | Content |
| `autoUse` | `DontUse` | AutoUse |
| `indexing` | `DontIndex` | Indexing |
| `fullTextSearch` | `Use` | FullTextSearch |
| `dataHistory` | `Use` | DataHistory |

`content` - массив, элемент строкой (`"Документ.РеализацияТоваров"`) или объектом
`{ "metadata": "...", "use": "Use" }`. Без `use` подставляется `Use`.

```json
{
  "type": "CommonAttribute", "name": "Организация",
  "valueType": "CatalogRef.Организации", "autoUse": "Use",
  "content": [ { "metadata": "Документ.РеализацияТоваров", "use": "Use" }, "Документ.ПоступлениеТоваров" ]
}
```

## CommonCommand (Общая команда)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `group` | пусто | Group |
| `commandParameterType` | пусто | CommandParameterType |
| `parameterUseMode` | `Single` | ParameterUseMode |
| `modifiesData` | `false` | ModifiesData |
| `representation` | `Auto` | Representation |
| `picture` | пусто | Picture |

Модули: `Ext/CommandModule.bsl` (создается пустым, обработчик пишется отдельно).

## CommandGroup (Группа команд)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `representation` | `Auto` | Representation |
| `category` | `FormCommandBar` | Category |
| `picture` | пусто | Picture |

`picture` - строка `"CommonPicture.Логотип"` либо объект
`{ "src": "CommonPicture.Логотип", "loadTransparent": false }`.

## CommonForm (Общая форма)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `formType` | `Managed` | FormType |
| `usePurposes` | `["PlatformApplication"]` | UsePurposes |
| `useStandardCommands` | `false` | UseStandardCommands |

Создает заготовку формы `Ext/Form.xml` (пустая командная панель и пустые элементы) и модуль
`Ext/Form/Module.bsl`. Наполнение формы - навык `1c-form-compile`.

## CommonTemplate (Общий макет)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `templateType` | `SpreadsheetDocument` | TemplateType |

Пишутся только метаданные макета. Содержимое макета - навыки `1c-mxl-compile` (табличный документ)
и `1c-skd-compile` (схема компоновки).

## CommonPicture (Общая картинка)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `availabilityForChoice` | `false` | AvailabilityForChoice |
| `availabilityForAppearance` | `false` | AvailabilityForAppearance |

Файл самой картинки не создается - его кладут в `Ext/Picture` отдельно.

## FilterCriterion (Критерий отбора)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `valueType` | - | Type |
| `useStandardCommands` | `true` | UseStandardCommands |
| `content` | `[]` | Content |

## Sequence (Последовательность)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `documents` | `[]` | Documents |
| `registerRecords` | `[]` | RegisterRecords |
| `moveBoundaryOnPosting` | `DontMove` | MoveBoundaryOnPosting |
| `dataLockControlMode` | `Managed` | DataLockControlMode |
| `dimensions` | `[]` | → Dimension |

Измерение: `{ "name": "...", "type": "CatalogRef.X", "documentMap": [...], "registerRecordsMap": [...] }`.
`documentMap` перечисляет реквизиты документов, откуда берется значение измерения.

```json
{
  "type": "Sequence", "name": "ВзаиморасчетыСКонтрагентами",
  "documents": ["Документ.ПоступлениеТоваров", "Document.РеализацияТоваров"],
  "dimensions": [{
    "name": "Организация", "type": "CatalogRef.Организации",
    "documentMap": ["Документ.ПоступлениеТоваров.Реквизит.Организация"]
  }]
}
```

## DocumentNumerator (Нумератор документов)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `numberType` | `String` | NumberType |
| `numberLength` | `9` | NumberLength |
| `numberAllowedLength` | `Variable` | NumberAllowedLength |
| `numberPeriodicity` | `Year` | NumberPeriodicity |
| `checkUnique` | `true` | CheckUnique |

## SessionParameter (Параметр сеанса)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `valueType` | - | Type |

Составной тип - через `+`: `"CatalogRef.Пользователи + CatalogRef.ВнешниеПользователи"`.

## SettingsStorage (Хранилище настроек)

Своих полей нет: только имя, синоним и комментарий. Формы сохранения и загрузки остаются пустыми.

## FunctionalOption (Функциональная опция)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `location` | пусто | Location |
| `privilegedGetMode` | `true` | PrivilegedGetMode |
| `content` | `[]` | Content |

`location` - где хранится значение опции: константа или реквизит
(`"Constant.ВестиУчетПоСкладам"`).

## FunctionalOptionsParameter (Параметр функциональных опций)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `use` | `[]` | Use |

`use` - измерения регистров, по которым параметризуется опция.

## WSReference (WS-ссылка)

| Поле JSON | Умолчание | XML элемент |
|-----------|----------|-------------|
| `locationURL` | пусто | LocationURL |

Адрес WSDL. Сам WSDL не скачивается и не разбирается.
