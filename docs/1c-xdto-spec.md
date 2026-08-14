# Спецификация формата XML пакетов XDTO 1С

Формат: XML-выгрузка конфигурации 1С:Предприятие 8.3 (Конфигуратор → Конфигурация → Выгрузить конфигурацию в файлы).
Проверенный диапазон версий формата: `2.17` (платформа 8.3.24) … `2.21` (8.5); полная лестница — [1c-configuration-spec.md §7.1](1c-configuration-spec.md#71-лестница-версий).

Источники: выгрузки Бухгалтерия предприятия (8.3.24), ERP 2 (8.3.24) — 760 пакетов.

> **Связанные спецификации:**
> - Корневая структура конфигурации — [1c-configuration-spec.md](1c-configuration-spec.md)
> - DSL навыков (XSD как формат описания) — [xdto-dsl-spec.md](xdto-dsl-spec.md)
> - Сводный индекс — [1c-specs-index.md](1c-specs-index.md)

---

## 1. Структура каталогов

```
XDTOPackages/
├── ОбменСБанком.xml              # Объект метаданных — 4 свойства, и всё
├── ОбменСБанком/
│   └── Ext/
│       └── Package.bin           # Модель пакета
└── ...
```

Регистрация в корневом `Configuration.xml`:

```xml
<ChildObjects>
    ...
    <XDTOPackage>ОбменСБанком</XDTOPackage>
</ChildObjects>
```

Ни форм, ни модулей, ни макетов у пакета XDTO нет.

---

## 2. Объект метаданных `<Имя>.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" ... version="2.17">
    <XDTOPackage uuid="6417d7c8-6436-4907-98eb-44cd7638f3f1">
        <Properties>
            <Name>ApdexExport</Name>
            <Synonym>
                <v8:item>
                    <v8:lang>ru</v8:lang>
                    <v8:content>Apdex export</v8:content>
                </v8:item>
            </Synonym>
            <Comment/>
            <Namespace>www.v8.1c.ru/ssl/performace-assessment/apdexExport</Namespace>
        </Properties>
    </XDTOPackage>
</MetaDataObject>
```

| Свойство | Описание |
|---|---|
| `Name` | Имя объекта метаданных. Должно быть валидным идентификатором 1С |
| `Synonym` | Многоязычное представление |
| `Comment` | Комментарий |
| `Namespace` | URI целевого пространства имён. Дублирует `targetNamespace` в `Package.bin` |

Других свойств у пакета XDTO нет.

---

## 3. `Ext/Package.bin` — модель пакета

Несмотря на расширение `.bin`, это **текстовый XML**: UTF-8 с BOM, перевод строки CRLF,
отступ — символы табуляции.

```xml
<package xmlns="http://v8.1c.ru/8.1/xdto"
         xmlns:xs="http://www.w3.org/2001/XMLSchema"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         targetNamespace="urn:1C.ru:ClientBankExchange">
    <property xmlns:d2p1="urn:1C.ru:ClientBankExchange" name="ClientBankExchange" type="d2p1:ClientBankExchange"/>
    <valueType name="СуммаТип" base="xs:decimal" variety="Atomic" totalDigits="18" fractionDigits="2"/>
    <objectType name="ClientBankExchange">
        <property xmlns:d3p1="urn:1C.ru:ClientBankExchange" name="ВерсияФормата" type="d3p1:ВерсияСхемы"/>
        <property name="Отправитель">
            <typeDef xsi:type="ValueType" base="xs:string" variety="Atomic" maxLength="160"/>
        </property>
    </objectType>
</package>
```

### 3.1. Вложенность элементов

```
package > objectType | valueType | property | import
objectType > property
valueType  > enumeration | pattern | typeDef
property   > typeDef
typeDef    > property | enumeration | pattern
```

Всего восемь имён элементов. `typeDef` — анонимный (встроенный) тип; его разновидность
задаёт `xsi:type` = `ValueType` либо `ObjectType`.

**Порядок элементов верхнего уровня обязателен:**

```
import* → property* → valueType* → objectType*
```

Ему удовлетворяют все 760 пакетов корпуса. Нарушение порядка платформа не прощает —
`db-update` падает с «Ошибка преобразования данных XDTO: Чтение объекта типа
`{http://v8.1c.ru/8.1/xdto}Package`… Проверка свойства 'property'». Это существенно
при сборке из XML-схемы, где порядок объявлений верхнего уровня произвольный.

### 3.2. `<package>`

| Атрибут | Значения | Описание |
|---|---|---|
| `targetNamespace` | URI | Целевое пространство имён |
| `elementFormQualified` | `true` \| `false` | Умолчание при отсутствии — `true` |
| `attributeFormQualified` | `true` \| `false` | Умолчание при отсутствии — `false` |

Порядок атрибутов: `targetNamespace`, `elementFormQualified`, `attributeFormQualified`.

### 3.3. `<import>`

`<import namespace="URI"/>` — объявление зависимости от другого пакета. Разрешается
по namespace среди пакетов конфигурации; `schemaLocation` в модели XDTO нет.

### 3.4. `<objectType>` и `<typeDef xsi:type="ObjectType">`

| Атрибут | Значения | Описание |
|---|---|---|
| `name` | идентификатор | Только у именованного `objectType` |
| `base` | QName | Базовый тип (наследование) |
| `open` | `true` \| `false` | Допускает произвольные элементы и атрибуты |
| `abstract` | `true` \| `false` | Абстрактный тип |
| `mixed` | `true` \| `false` | Смешанное содержимое |
| `ordered` | `true` \| `false` | `false` — выбор одного из вариантов (аналог `xs:choice`) |
| `sequenced` | `true` | Последовательное содержимое |

Порядок атрибутов `objectType`: `name`, `base`, `open`, `abstract`, `mixed`, `ordered`, `sequenced`.
Порядок атрибутов `typeDef`: `xsi:type`, `base`, `mixed`, `open`, `ordered`, `sequenced`, далее атрибуты простого типа.

### 3.5. `<valueType>` и `<typeDef xsi:type="ValueType">`

| Атрибут | Значения |
|---|---|
| `name` | идентификатор (только у именованного `valueType`) |
| `base` | QName базового типа |
| `variety` | `Atomic` \| `List` \| `Union` |
| `itemType` | QName — тип элемента списка (`variety="List"`) |
| `memberTypes` | список типов объединения (`variety="Union"`) |

Фасеты задаются **атрибутами**, а не дочерними элементами:
`length`, `minLength`, `maxLength`, `totalDigits`, `fractionDigits`,
`minInclusive`, `maxInclusive`, `minExclusive`, `maxExclusive`,
`whiteSpace` (`preserve` \| `collapse`).

Базовый тип может задаваться не атрибутом `base`, а вложенным анонимным `typeDef`
**без** `xsi:type` — соответствует анонимному `xs:simpleType` внутри `xs:restriction`:

```xml
<valueType name="INN12Type" variety="Atomic" length="12">
    <typeDef base="xs:string" variety="Atomic"/>
    <pattern>[0-9]{12}</pattern>
</valueType>
```

Дочерними элементами идут только `<pattern>` и `<enumeration>` — значение в тексте узла:

```xml
<valueType name="НомерСчетаТип" base="xs:string" variety="Atomic" length="20">
    <pattern>[0-9]{20}</pattern>
</valueType>
```

У `<enumeration>` встречается атрибут `xsi:type` (например `xs:string`), указывающий тип литерала.

### 3.6. `<property>`

| Атрибут | Значения | Описание |
|---|---|---|
| `name` | идентификатор | Имя свойства |
| `ref` | QName | Ссылка на глобальное свойство вместо собственного объявления |
| `type` | QName | Тип свойства. При отсутствии и `type`, и вложенного `typeDef` — произвольный тип |
| `lowerBound` | `0` \| `1` | Минимальная кратность. Умолчание при отсутствии — `1` |
| `upperBound` | число \| `-1` | Максимальная кратность; `-1` — неограниченно. Умолчание — `1` |
| `nillable` | `true` \| `false` | Допускает `xsi:nil` |
| `fixed` | значение | Фиксированное значение |
| `default` | значение | Значение по умолчанию |
| `form` | `Element` \| `Attribute` \| `Text` | Форма представления в XML. Умолчание — `Element` |
| `localName` | строка | Исходное XML-имя, если оно не является валидным идентификатором 1С |
| `qualified` | `true` \| `false` | Переопределение `*FormQualified` для конкретного свойства |

Порядок атрибутов: `name`, `ref`, `type`, `lowerBound`, `upperBound`, `nillable`,
`fixed`, `default`, `form`, `localName`, `qualified`.

**`form="Text"`** — свойство хранит собственное значение элемента (аналог `xs:simpleContent`).
Такое свойство платформа всегда называет `__content`:

```xml
<objectType name="Error">
    <property name="code" type="xs:NCName" lowerBound="1" form="Attribute"/>
    <property name="__content" type="xs:string" form="Text"/>
</objectType>
```

Наличие `form="Text"` не отменяет флагов самого типа — `mixed`, `sequenced` и прочие
задаются как обычно:

```xml
<objectType name="Account" mixed="true" sequenced="true">
    <property name="bic" type="d3p1:BicType" lowerBound="1" form="Attribute"/>
    <property name="__content" type="d3p1:AccNumType" form="Text"/>
</objectType>
```

**`localName`** — при импорте XML-схемы имя, недопустимое как идентификатор 1С,
санируется, а оригинал сохраняется:

```xml
<property name="isFixPlaceResidence_" type="xs:boolean" localName="isFixPlaceResidence "/>
```

### 3.7. Порядок свойств внутри типа

Свойства с `form="Attribute"` обычно идут перед остальными — так записаны 96.5% типов
корпуса. Оставшиеся 3.5% содержат произвольное чередование; порядок значим и сохраняется
платформой как есть.

---

## 4. Схема префиксов пространств имён

Каждая ссылка на тип из пространства имён, отличного от `xs:`/`xsi:`, требует объявления
префикса вида `dNpM`:

```xml
<property xmlns:d3p1="urn:1C.ru:ClientBankExchange" name="ВерсияФормата" type="d3p1:ВерсияСхемы"/>
```

- `N` — глубина узла: `package` = 1, его прямые потомки = 2, свойство внутри `objectType` = 3,
  свойство внутри `typeDef` = 5, глубже — 7, 9 и т.д.
- `M` — порядковый номер нового пространства имён, объявляемого на этом узле (с 1).

Префикс объявляется **на первом узле, которому он нужен**; потомки переиспользуют его из
области видимости, а не объявляют заново:

```xml
<objectType xmlns:d2p1="…/Permissions/1.0.0.1" name="InternetConnectionBase" base="d2p1:PermissionBase">
    <property name="Protocol" type="d2p1:NetworkProtocols" lowerBound="0" nillable="true"/>
</objectType>
```

Целевое пространство имён самого пакета исключением не является — ссылка на собственный
тип тоже требует локального объявления.

Частоты по корпусу: `d3p1` — 109 738, `d2p1` — 13 108, `d5p1` — 9 581, далее по убыванию до `d16p1`.

### 4.1. Нотация Кларка в `memberTypes`

Значения `memberTypes` записываются нотацией Кларка `{URI}Локальное`, без префикса
(125 случаев из 135 в корпусе; остальные — обычные префиксные QName):

```xml
<valueType xmlns:d2p1="http://v8.1c.ru/8.1/data/core" name="UUID" variety="Union"
           memberTypes="{http://v8.1c.ru/8.1/data/core}UUID {http://www.w3.org/2001/XMLSchema}base64Binary"/>
```

Обратите внимание: объявление `xmlns:d2p1` присутствует, хотя в значении не используется —
пространство имён всё равно проходит через общий механизм выделения префиксов. Если оно уже
объявлено предком, нового объявления не появляется.

Остальные атрибуты-QName (`type`, `base`, `ref`, `itemType`) всегда префиксные.

### 4.2. Осмысленные префиксы

Изредка вместо сгенерированного `dNpM` встречается содержательный префикс — например
`dcsset` для настроек компоновки данных:

```xml
<property xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings"
          name="Настройка" type="dcsset:Filter" lowerBound="0"/>
```

### 4.3. Свойство с `qualified` сериализуется с префиксом

Если у свойства задан `qualified`, платформа пишет и сам тег, и имя атрибута с явным
префиксом пространства имён модели XDTO (хотя по умолчанию оно и так объявлено как `xmlns=`):

```xml
<d3p2:property xmlns:d3p1="http://bssys.com/upg/request" xmlns:d3p2="http://v8.1c.ru/8.1/xdto"
               name="numCheck" type="d3p1:BoolType" lowerBound="0" form="Attribute"
               d3p2:qualified="false"/>
```

Префикс для XDTO выделяется последним, после префиксов типов. Такое встречается редко
(16 узлов на весь корпус) и появляется при импорте XML-схемы, где `form` задан на
объявлении в unqualified-пакете.

---

## 5. Умолчания записываются непоследовательно

Один и тот же смысл в корпусе встречается в двух написаниях: `nillable="false"` присутствует
явно 6 899 раз, `objectType open="false"` — 6 раз, `abstract="false"` — 2 раза, явное
`form="Element"` — 44 раза. Пакеты, полученные импортом XML-схемы, и пакеты, созданные
руками в Конфигураторе, отличаются стилем.

Практическое следствие: приведение пакета к «каноническому» виду меняет байты реальных
файлов. Инструменты, которым важен точный round-trip, обязаны сохранять literal-форму.

---

## 6. Тихая деградация в `xs:anyType`

При импорте XML-схемы через Конфигуратор тип из чужого пространства имён, для которого
в конфигурации нет соответствующего пакета, **молча** заменяется на `xs:anyType` —
без ошибки и без предупреждения:

```xml
<!-- в схеме было type="ns2:contact" -->
<property name="contact" type="xs:anyType"/>
```

При этом `<import namespace="…"/>` в пакете остаётся. Признак «объявлен импорт, но
ни один тип из этого пространства имён не используется» — надёжный индикатор проблемы.
