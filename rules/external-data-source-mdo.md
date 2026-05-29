---
paths:
  - "**/*.mdo"
  - "**/ExternalDataSources/**"
---

# ExternalDataSource MDO Format (EDT)

Правила создания и работы с внешними источниками данных (ВИД) в формате EDT.

Применяется: при создании ExternalDataSource MDO-файлов в проектах 1C:EDT.

---

## Структура файлов

```
src/ExternalDataSources/<ИмяВИД>/
  <ИмяВИД>.mdo                          ← Корневой MDO внешнего источника
  Tables/
    <ИмяТаблицы1>/
      <ИмяТаблицы1>.mdo                 ← MDO таблицы (поля ВНУТРИ файла)
    <ИмяТаблицы2>/
      <ИмяТаблицы2>.mdo
```

**Важно:** Поля таблицы (`tableFields`) описываются ВНУТРИ MDO-файла таблицы — НЕ как отдельные файлы. Это отличает ExternalDataSource от справочников/документов, где реквизиты — отдельные файлы.

---

## Корневой MDO — ExternalDataSource

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:ExternalDataSource xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass" uuid="<UUID>">
  <producedTypes>
    <managerType typeId="<UUID>" valueTypeId="<UUID>"/>
    <tablesManagerType typeId="<UUID>" valueTypeId="<UUID>"/>
    <cubesManagerType typeId="<UUID>" valueTypeId="<UUID>"/>
  </producedTypes>
  <name>ИмяВИД</name>
  <synonym>
    <key>ru</key>
    <value>Синоним ВИД</value>
  </synonym>
  <dataLockControlMode>Managed</dataLockControlMode>
  <tables>ExternalDataSource.ИмяВИД.Table.ИмяТаблицы1</tables>
  <tables>ExternalDataSource.ИмяВИД.Table.ИмяТаблицы2</tables>
</mdclass:ExternalDataSource>
```

### producedTypes

ExternalDataSource имеет 3 типа (НЕ путать с Table, у которой 8):
- `managerType` — менеджер ВИД
- `tablesManagerType` — менеджер таблиц
- `cubesManagerType` — менеджер кубов

---

## MDO таблицы — Table

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mdclass:Table xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:core="http://g5.1c.ru/v8/dt/mcore" xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass" uuid="<UUID>">
  <producedTypes>
    <refType typeId="<UUID>" valueTypeId="<UUID>"/>
    <listType typeId="<UUID>" valueTypeId="<UUID>"/>
    <objectType typeId="<UUID>" valueTypeId="<UUID>"/>
    <managerType typeId="<UUID>" valueTypeId="<UUID>"/>
    <recordManagerType typeId="<UUID>" valueTypeId="<UUID>"/>
    <recordSetType typeId="<UUID>" valueTypeId="<UUID>"/>
    <recordType typeId="<UUID>" valueTypeId="<UUID>"/>
    <recordKeyType typeId="<UUID>" valueTypeId="<UUID>"/>
  </producedTypes>
  <name>ИмяТаблицы</name>
  <synonym>
    <key>ru</key>
    <value>Синоним таблицы</value>
  </synonym>
  <parentDataSource>ExternalDataSource.ИмяВИД</parentDataSource>
  <nameInDataSource>&quot;ИмяТаблицыВБД&quot;</nameInDataSource>
  <keyFields>ExternalDataSource.ИмяВИД.Table.ИмяТаблицы.Field.КлючевоеПоле</keyFields>
  <unfilledParentValue xsi:type="core:UndefinedValue"/>
  <useStandardCommands>true</useStandardCommands>
  <transactionsIsolationLevel>ReadUncommitted</transactionsIsolationLevel>
  <editType>InDialog</editType>
  <dataLockControlMode>Managed</dataLockControlMode>
  <!-- Поля таблицы (tableFields) идут далее -->
</mdclass:Table>
```

### producedTypes таблицы

Table имеет 8 типов:
- `refType`, `listType`, `objectType`, `managerType` — стандартные
- `recordManagerType`, `recordSetType`, `recordType`, `recordKeyType` — для работы с записями (МенеджерЗаписи)

### Ключевые атрибуты

| Атрибут | Формат | Описание |
|---------|--------|----------|
| `parentDataSource` | `ExternalDataSource.ИмяВИД` | Ссылка на родительский ВИД |
| `nameInDataSource` | `&quot;ИмяВБД&quot;` | Имя таблицы в БД (в XML-кавычках для case-sensitive) |
| `keyFields` | `ExternalDataSource.ИмяВИД.Table.Таблица.Field.Поле` | Ключевое поле (полный FQN) |
| `transactionsIsolationLevel` | `ReadUncommitted` | Уровень изоляции (обычно ReadUncommitted для внешних БД) |

---

## Поля таблицы — tableFields

Каждое поле — элемент `<tableFields>` внутри MDO таблицы.

### Числовое поле

```xml
<tableFields uuid="<UUID>">
  <name>RecNo</name>
  <type>
    <types>Number</types>
    <numberQualifiers>
      <precision>15</precision>
      <nonNegative>true</nonNegative>
    </numberQualifiers>
  </type>
  <minValue xsi:type="core:UndefinedValue"/>
  <maxValue xsi:type="core:UndefinedValue"/>
  <fillValue xsi:type="core:UndefinedValue"/>
  <nameInDataSource>&quot;RecNo&quot;</nameInDataSource>
</tableFields>
```

С дробной частью:
```xml
<numberQualifiers>
  <precision>15</precision>
  <scale>2</scale>
</numberQualifiers>
```

### Строковое поле

```xml
<tableFields uuid="<UUID>">
  <name>CustomerName</name>
  <type>
    <types>String</types>
    <stringQualifiers>
      <length>250</length>
    </stringQualifiers>
  </type>
  <minValue xsi:type="core:UndefinedValue"/>
  <maxValue xsi:type="core:UndefinedValue"/>
  <fillValue xsi:type="core:StringValue">
    <value></value>
  </fillValue>
  <nameInDataSource>&quot;CustomerName&quot;</nameInDataSource>
</tableFields>
```

### Поле даты

```xml
<tableFields uuid="<UUID>">
  <name>InvoiceDate</name>
  <type>
    <types>Date</types>
    <dateQualifiers>
      <dateFractions>Date</dateFractions>
    </dateQualifiers>
  </type>
  <minValue xsi:type="core:UndefinedValue"/>
  <maxValue xsi:type="core:UndefinedValue"/>
  <fillValue xsi:type="core:UndefinedValue"/>
  <nameInDataSource>&quot;InvoiceDate&quot;</nameInDataSource>
</tableFields>
```

---

## Маппинг типов PostgreSQL → 1С

| PostgreSQL | 1С тип | precision | scale | Примечания |
|------------|--------|-----------|-------|-----------|
| bigint / int8 | Number | 15 | — | nonNegative если unsigned |
| integer / int4 | Number | 10 | — | |
| smallint / int2 | Number | 5 | — | |
| numeric(p,s) | Number | p | s | |
| varchar(n) | String | length=n | — | |
| text | String | length=1024+ | — | Выбрать разумный лимит |
| date | Date | dateFractions=Date | — | |
| timestamp | Date | dateFractions=DateTime | — | |
| boolean | Number | 1 | — | 0/1 |

---

## fillValue — правила

| Тип | fillValue |
|-----|-----------|
| Number | `xsi:type="core:UndefinedValue"` |
| Date | `xsi:type="core:UndefinedValue"` |
| String | `xsi:type="core:StringValue"` с пустым `<value></value>` |

---

## PostgreSQL — case-sensitive имена

Если таблицы/поля в PostgreSQL созданы в кавычках (CamelCase, UPPERCASE), они case-sensitive. В MDO:
- `nameInDataSource` обязательно содержит `&quot;ИмяВТочности&quot;`
- Без кавычек PostgreSQL приведёт имя к lowercase и не найдёт таблицу

---

## Регистрация в конфигурации

После создания MDO-файлов:

1. **Configuration.mdo** — добавить `<externalDataSources>ExternalDataSource.ИмяВИД</externalDataSources>`
2. **Подсистема** — включить в нужную подсистему (например: `Расш_НовыеОбъекты`)
3. **Роли** — добавить права на чтение/запись обеих таблиц
4. **UUID-проверка** — убедиться в уникальности всех UUID

---

## Использование в запросах 1С

```bsl
Запрос = Новый Запрос;
Запрос.Текст =
"ВЫБРАТЬ
|    Таблица.Поле1 КАК Поле1,
|    Таблица.Поле2 КАК Поле2
|ИЗ
|    ВнешнийИсточникДанных.ИмяВИД.Таблица.ИмяТаблицы КАК Таблица
|ГДЕ
|    Таблица.Условие = &Параметр";
```

## Запись через МенеджерЗаписи

```bsl
Менеджер = ВнешниеИсточникиДанных.ИмяВИД.Таблицы.ИмяТаблицы.СоздатьМенеджерЗаписи();
Менеджер.КлючевоеПоле = ЗначениеКлюча;
Менеджер.Прочитать();
Менеджер.Поле = НовоеЗначение;
Менеджер.Записать();
```

**Ограничение:** МенеджерЗаписи работает построчно. Для массовых UPDATE рассмотреть хранимые процедуры.

---

## Подключение ВИД

Строка подключения ODBC настраивается администратором в режиме предприятия:
Администрирование → Внешние источники данных → [ИмяВИД] → Настроить подключение.

Программное подключение:
```bsl
ВнешниеИсточникиДанных.ИмяВИД.УстановитьСоединение();
```

Строка подключения хранится в ИБ, не в метаданных — при переносе между средами настраивается заново.

---

## Эталонные файлы-шаблоны

Копии рабочих MDO-файлов (проверены EDT, 0 ошибок) хранятся в:

```
~/.claude/templates/ExternalDataSource/
  ExternalDataSource.mdo    ← Корневой ВИД (3 producedTypes, 2 таблицы)
  Table.mdo                 ← Таблица EXP_DOCTABLE (22 поля, ключ RecNo)
  Table_with_FK.mdo         ← Таблица EXP_DOCLINE (14 полей, ключ RecNo, связь через TableRecNo)
```

### Как использовать

1. Скопировать нужный шаблон в проект
2. Заменить UUID (каждый — уникальный, генерировать через `[guid]::NewGuid()`)
3. Заменить имена (ВИД, таблица, поля)
4. Добавить/удалить поля по схеме внешней БД
5. Зарегистрировать в Configuration.mdo, подсистеме, ролях

### Особенности шаблонов

- PostgreSQL: все `nameInDataSource` содержат `&quot;ИмяВТочности&quot;` (case-sensitive)
- Типы полей: Number (precision/scale/nonNegative), String (length), Date (dateFractions)
- `Table_with_FK.mdo` — пример таблицы-детали с полем `TableRecNo` (ссылка на RecNo мастер-таблицы)
