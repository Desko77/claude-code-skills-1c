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

## Типы данных реквизитов — ограничения, ломающие реструктуризацию БД

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

### Number — всегда явный `<scale>` в `<numberQualifiers>`

```xml
<!-- ОК: целое число -->
<type>
  <types>Number</types>
  <numberQualifiers>
    <precision>10</precision>
    <scale>0</scale>
  </numberQualifiers>
</type>

<!-- ❌ НЕПРАВИЛЬНО: scale отсутствует -->
<type>
  <types>Number</types>
  <numberQualifiers>
    <precision>10</precision>
  </numberQualifiers>
</type>
```

**EDT-линтер склонен удалять `<scale>0</scale>`** из MDO при нормализации (считает что 0 — дефолт). Формально это валидно для EDT, но при реструктуризации БД платформа интерпретирует отсутствующий scale как максимально допустимый — SDBL падает.

**Симптом:** та же `Ошибка SDBL: Слишком большое значение описателя длины`.

**Проверка после работы EDT-линтера:**
```bash
git diff <base>..HEAD -- '**/*.mdo' | grep -cE "^-[ ]+<scale>0</scale>"
```

**Автоисправление:**
```python
import re
from pathlib import Path
def fix(p):
    text = Path(p).read_text(encoding='utf-8')
    def fix_block(m):
        b = m.group(0)
        if '<scale>' in b: return b
        return re.sub(r'(<precision>\d+</precision>\n)(\s*)',
                      lambda pm: pm.group(1) + pm.group(2) + '<scale>0</scale>\n' + pm.group(2),
                      b, count=1)
    new = re.sub(r'<numberQualifiers>.*?</numberQualifiers>', fix_block, text, flags=re.DOTALL)
    if new != text: Path(p).write_text(new, encoding='utf-8')
```

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
