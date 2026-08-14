---
paths:
  - "**/*.mdo"
---

# 1C MDO Integrity Rules

Правила целостности MDO-файлов конфигурации 1С (EDT-формат).

Применяется: при создании/модификации MDO-файлов (*.mdo), планов обмена, подсистем.

---

## UUID — уникальность обязательна

Каждый UUID в атрибутах `uuid`, `typeId`, `valueTypeId` должен быть **глобально уникальным** среди всех MDO-файлов проекта.

### Запрещено

- Копировать UUID из одного MDO-файла в другой
- Использовать последовательные/инкрементальные UUID (типа `a1b2c3d4...`, `b2c3d4e5...`)
- Использовать placeholder UUID при генерации метаданных

### Как генерировать

Каждый UUID генерировать отдельно через `uuid.uuid4()` (Python) или `[guid]::NewGuid()` (PowerShell).

### Проверка после создания/модификации MDO

После создания или массовой модификации MDO-файлов — запускать проверку дубликатов:

```
py commands/check_uuid_duplicates.py <путь_к_src>
```

Или через команду Claude Code: `/check-uuid`

Если найдены дубликаты — исправить через `--fix` флаг.

---

## Ссылки на метаданные — проверка существования

Перед добавлением ссылки на объект метаданных в:
- Планы обмена (`<content><mdObject>`)
- Подсистемы (`<content>`)
- Подписки на события
- Определяемые типы

**Обязательно проверить**, что указанный объект существует в конфигурации.

### Типичные ошибки

- Ссылка на `Catalog.Партнеры` в УТ 10.3 (этот справочник появился в УТ 11.x)
- Ссылка на объекты из другой конфигурации/версии
- Опечатки в имени объекта

### Последствия битой ссылки

Платформа 1С при загрузке выдаёт:
```
Несоответствие свойства и элемента данных XDTO:
Свойство: 'Metadata'
```
Ошибка появляется в `Content.xml` при попытке загрузить в базу через EDT.

---

## Стандартные атрибуты табличных частей

Блок `<standardAttributes><name>LineNumber</name>...</standardAttributes>` **НЕ должен** присутствовать в табличных частях MDO-файлов — платформа добавляет его автоматически.

---

## Типы данных реквизитов — ловушки, ломающие реструктуризацию БД

Следующие ошибки в описании типов НЕ ловятся EDT-валидацией (`get_project_errors`, `revalidate_objects`), но вызывают падение при `updateDatabaseConfiguration` (запуск ИБ из EDT / обновление через Конфигуратор) с труднодиагностируемыми сообщениями.

### String — длина > 1024 только для неограниченной

```xml
<!-- ОК: фиксированная длина до 1024 -->
<type>
  <types>String</types>
  <stringQualifiers>
    <length>250</length>
  </stringQualifiers>
</type>

<!-- ОК: неограниченная длина (LOB-хранение) -->
<type>
  <types>String</types>
  <stringQualifiers>
    <length>0</length>
  </stringQualifiers>
</type>

<!-- ❌ НЕПРАВИЛЬНО: длина > 1024 -->
<type>
  <types>String</types>
  <stringQualifiers>
    <length>2000</length>
  </stringQualifiers>
</type>
```

Максимум для **фиксированной** (inline) String — **1024 символа**. Для больших текстов — `<length>0</length>` (неограниченная, хранение в LOB).

**Симптом:** `Ошибка SDBL: Слишком большое значение описателя длины` при реструктуризации таблицы (справочник / документ / регистр).

**Проверка:** `grep -rE "<length>(1[0-9]{3}|[2-9][0-9]{3,})</length>" <src> --include="*.mdo" | grep -v "<length>1024</length>"`

### Number — `<scale>` опускается EDT для integer (это НОРМА, не баг)

EDT-сериализатор **опускает** `<scale>0</scale>` для целочисленных Number-реквизитов (0 = дефолт `NumberQualifiers`, EMF не пишет default-значения). Целое число сериализуется так:

```xml
<type>
  <types>Number</types>
  <numberQualifiers>
    <precision>10</precision>
  </numberQualifiers>
</type>
```

Это **нормальное, корректное поведение EDT** — НЕ требует вмешательства, НЕ нужно «восстанавливать» `<scale>0</scale>`.

**Эмпирически проверено 2026-07-28** (EDT 2026.1.2.2, ИБ Демо_БСП): integer Number-реквизит БЕЗ `<scale>` создан через `edit_metadata` -> `.mdo` без `<scale>` -> `update_database` -> `UPDATED`, «Database update finished successfully», **без ошибок**. Во всём конфиге Демо_БСП — **НОЛЬ** `<scale>0</scale>` при десятках integer-реквизитов (только non-zero: 1/2/3/4/5/90); ИБ работает штатно.

Платформа **НЕ падает** от отсутствующего `<scale>` — она трактует его как 0 (integer), а НЕ как «максимально допустимый».

> **ПРЕДУПРЕЖДЕНИЕ.** Прежняя редакция этого раздела утверждала, что отсутствие `<scale>` вызывает `Ошибка SDBL: Слишком большое значение описателя длины`, и рекомендовала принудительно восстанавливать `<scale>0</scale>` (grep + inject). **Это было неверно** — проверено экспериментом выше. Реальная причина ошибки SDBL «Слишком большое значение описателя длины» — String `length > 1024` (см. раздел выше), а НЕ missing Number scale. Принудительное восстановление `<scale>0` — борьба с правильной сериализацией EDT (он всё равно уберёт при следующей нормализации, что агент и наблюдал как «снова вырезали»).

### fillValue — никогда пустой NumberValue

```xml
<!-- ОК: UndefinedValue (нет значения по умолчанию) -->
<fillValue xsi:type="core:UndefinedValue"/>

<!-- ОК: конкретное значение -->
<fillValue xsi:type="core:NumberValue">
  <value>0</value>
</fillValue>

<!-- ❌ НЕПРАВИЛЬНО: пустой NumberValue без <value> -->
<fillValue xsi:type="core:NumberValue"/>
```

**Симптом:** `java.lang.NullPointerException: Cannot invoke "java.math.BigDecimal.toPlainString()"` в `ValueWriter.writeValue` при экспорте XML в ИБ.

**Касается только Number.** Пустые `<StringValue/>` и `<BooleanValue/>` — валидны (пустая строка / Ложь).

**Проверка:** `grep -rn 'core:NumberValue"/>' <src> --include="*.mdo"` — результат должен быть пустым.

---

## Form.form — пустой stringQualifiers ломает XDTO-сериализацию

В EDT-форматe `Form.form` для реквизитов формы (`<attributes>`) и колонок (`<columns>`) типа String **нельзя** оставлять пустой `<stringQualifiers/>`:

```xml
<!-- ❌ НЕПРАВИЛЬНО (в Form.form) -->
<valueType>
  <types>String</types>
  <stringQualifiers/>
</valueType>

<!-- ОК -->
<valueType>
  <types>String</types>
  <stringQualifiers>
    <length>1024</length>
  </stringQualifiers>
</valueType>
```

**Симптом:** `Исключение XDTO при чтении Form.xml. Свойство: 'Type'` при загрузке ИБ.

**Отличие от MDO:** в MDO `<stringQualifiers/>` без `<length>` иногда валиден как "неограниченная длина" (но лучше явно `<length>0</length>`). В Form.form — всегда нужен `<length>`.
