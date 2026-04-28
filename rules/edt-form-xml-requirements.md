---
paths:
  - "**/Form.form"
  - "**/Forms/**"
---

# Требования EDT к XML-формам (Form.form)

Требования к формату Form.form, которые EDT предъявляет сверх того, что MCP-генератор обрабатывает автоматически.

Применяется: при генерации и ручной правке Form.form в EDT-проектах.

---

## Что MCP-генератор обрабатывает автоматически

Не дублировать вручную - генератор уже добавляет:

- Типы: `String`, `Boolean`, `Number`, `Date` (маппинг из xs:, cfg:, v8:)
- Типы: `ExternalDataProcessor.` (маппинг из `ExternalDataProcessorObject.`)
- visible/enabled/userVisible на всех элементах
- Свойства таблиц: changeRowSet, selectionMode, scrollbars, header/footer, drag (16 свойств)
- Companion-элементы таблиц: autoCommandBar, extendedTooltip, contextMenu, searchStringAddition, viewStatusAddition
- InputFieldExtInfo: chooseType, typeDomainEnabled, textEdit
- Колонки таблиц: editMode, showInHeader, headerHorizontalAlign, showInFooter
- Button type=UsualButton вне CommandBar
- Корневые свойства: autoTitle, autoUrl, autoFillCheck, enabled, showTitle, showCloseButton

---

## Что генератор НЕ добавляет - нужно вручную

### 1. Root extInfo (обязательно для обработок/отчетов)

```xml
<extInfo xsi:type="form:ObjectFormExtInfo"/>
```

Тип зависит от владельца формы:

| Объект | xsi:type |
|--------|----------|
| Внешняя обработка / Обработка | `form:ObjectFormExtInfo` |
| Справочник | `form:CatalogFormExtInfo` |
| Документ | `form:DocumentFormExtInfo` |
| РегистрСведений | `form:InformationRegisterFormExtInfo` |

Без extInfo дизайнер EDT может показать пустую форму.

### 2. commandInterface

```xml
<commandInterface>
  <navigationPanel/>
  <commandBar/>
</commandInterface>
```

Требуется по Xcore-модели (FormCommandInterface[1]). EDT может добавить автоматически при сохранении, но лучше указать явно.

### 3. formCommands (команды формы)

Имя тега в EDT - `<formCommands>` (НЕ `<commands>` как в logform).

```xml
<formCommands>
  <name>ИмяКоманды</name>
  <id>100</id>
  <action>ИмяОбработчика</action>
</formCommands>
```

### 4. ValueTable - columns с view/edit и уникальными `<id>`

Реквизит типа ValueTable требует вложенных `<columns>` с **обязательным `<id>`**, `view/edit`:

```xml
<attributes>
  <name>ТаблицаДанных</name>
  <id>5</id>
  <valueType><types>ValueTable</types></valueType>
  <view><common>true</common></view>
  <edit><common>true</common></edit>
  <columns>
    <name>Колонка1</name>
    <title><key>ru</key><value>Колонка 1</value></title>
    <id>500</id>
    <valueType><types>String</types></valueType>
    <view><common>true</common></view>
    <edit><common>true</common></edit>
  </columns>
  <columns>
    <name>Колонка2</name>
    <title><key>ru</key><value>Колонка 2</value></title>
    <id>501</id>
    <valueType><types>Number</types></valueType>
    <view><common>true</common></view>
    <edit><common>true</common></edit>
  </columns>
</attributes>
```

**`<id>` обязателен у каждой колонки** — без него платформа не может связать FormField-элементы в таблице с конкретной колонкой реквизита. Симптом: на форме **все колонки показывают заголовок первой колонки** (например, все 12 колонок называются "Пометка"), хотя FormField имеют правильные `dataPath`.

id колонок должны быть уникальны в рамках всего Form.form (не пересекаться с id других элементов). Безопасный подход — начинать нумерацию колонок от большого числа (500+), чтобы не пересечься с id-шниками, которые EDT-дизайнер генерирует для FormField/FormGroup (обычно 1-300).

Без view/edit у columns - колонки помечены крестиком в дизайнере.

---

## Частые ошибки

### Namespace prefix

- Каноничный формат EDT: `form:` ТОЛЬКО на корневом элементе, дети БЕЗ prefix
- lxml при генерации добавляет `form:` ко всем элементам - EDT принимает оба варианта
- Оба формата валидны. Если форма не рендерится - причина НЕ в prefix, искать в другом

### view/edit у колонок-элементов

- `<view>`/`<edit>` принадлежат ТОЛЬКО реквизитам формы (`<attributes>` и их `<columns>`)
- НЕ добавлять view/edit к items (элементам-колонкам таблицы формы)

### Кнопки команд

- Кнопки команд формы размещать в autoCommandBar (командная панель формы)
- НЕ создавать отдельную UsualGroup для кнопок команд
- EDT при пересохранении перенесет кнопки из UsualGroup в autoCommandBar

### Типы данных

- `String`, `Boolean`, `Number`, `Date` - без prefix (НЕ xs:string, НЕ v8:ValueTable)
- `ExternalDataProcessor.` - без "Object" (НЕ ExternalDataProcessorObject.)
- `ExternalReport.` - без "Object" (НЕ ExternalReportObject.)

---

## form:Table - специфичные требования (частая причина "форма не рендерится")

У `<items xsi:type="form:Table">` структура свойств **отличается** от `form:FormGroup` и `form:FormField`. Ошибка здесь даёт "валидная форма, 0 ошибок в EDT, но дизайнер показывает пустоту".

### Запрещено

1. **`<extInfo xsi:type="form:TableExtInfo">`** — НЕ писать у form:Table. EDT не создаёт extInfo для таблиц вообще. Все свойства таблицы идут **прямо на уровне `<items xsi:type="form:Table">`**, а НЕ внутри extInfo.

   ```xml
   <!-- НЕПРАВИЛЬНО -->
   <items xsi:type="form:Table">
     <name>МояТЧ</name>
     ...
     <extInfo xsi:type="form:TableExtInfo">
       <autoMaxRowsCount>true</autoMaxRowsCount>
       <rowInputMode>EnterAsDefault</rowInputMode>
       <selectionShowMode>WhenMultiRowSelection</selectionShowMode>
     </extInfo>
   </items>

   <!-- ПРАВИЛЬНО: свойства на уровне самого items -->
   <items xsi:type="form:Table">
     <name>МояТЧ</name>
     ...
     <autoMaxRowsCount>true</autoMaxRowsCount>
   </items>
   ```

2. **`<commandBarLocation>Top</commandBarLocation>`** — не валидно для form:Table.

3. **`<rowsPicture xsi:type="core:PictureRef"/>`** — не нужно.

### Обязательно (на уровне самого items, не в extInfo)

- `<titleLocation>None</titleLocation>` — если заголовок не нужен
- `<changeRowSet>true</changeRowSet>` / `<changeRowOrder>true</changeRowOrder>`
- `<autoMaxWidth>true</autoMaxWidth>` / `<autoMaxHeight>true</autoMaxHeight>`
- `<autoMaxRowsCount>true</autoMaxRowsCount>`
- `<selectionMode>MultiRow</selectionMode>` (или SingleRow)
- `<header>true</header>` + `<headerHeight>1</headerHeight>` + `<footerHeight>1</footerHeight>`
- `<horizontalScrollBar>AutoUse</horizontalScrollBar>` / `<verticalScrollBar>AutoUse</verticalScrollBar>`
- `<horizontalLines>true</horizontalLines>` / `<verticalLines>true</verticalLines>`
- `<autoInsertNewRow>true</autoInsertNewRow>`
- `<searchOnInput>Auto</searchOnInput>` / `<initialListView>Auto</initialListView>`
- `<horizontalStretch>true</horizontalStretch>` / `<verticalStretch>true</verticalStretch>`
- `<enableStartDrag>true</enableStartDrag>` / `<enableDrag>true</enableDrag>`
- `<fileDragMode>AsFileRef</fileDragMode>` (EDT добавляет сам)
- `<rowFilter xsi:type="core:UndefinedValue"/>` (EDT добавляет сам)

### Три дополнения таблицы — разные вещи

У ТЧ-таблицы могут присутствовать **три** дополнения (одновременно):
- `<searchStringAddition>` — строка поиска (внутри `source` = имя таблицы)
- `<viewStatusAddition>` — строка состояния просмотра
- `<searchControlAddition>` — контрол поиска (`<type>SearchControlAddition</type>`)

### FormField внутри form:Table

У каждого `<items xsi:type="form:FormField">` внутри таблицы обязательны:
- `<contextMenu>` с уникальным именем и `<autoFill>true</autoFill>` — БЕЗ него EDT не принимает
- `<editMode>EnterOnInput</editMode>` (не `Enter` — EDT переписывает)
- `<extendedTooltip>` с `<type>Label</type>` и `<extInfo xsi:type="form:LabelDecorationExtInfo">`
- `<showInHeader>true</showInHeader>` / `<headerHorizontalAlign>Left</headerHorizontalAlign>` / `<showInFooter>true</showInFooter>`
- Для `InputField`: в `<extInfo xsi:type="form:InputFieldExtInfo">` обязателен `<wrap>true</wrap>`

### Обработчики таблицы (handlers)

События таблицы (`OnActivateRow`, `BeforeRowChange`, `OnStartEdit`, `OnEndEditRow` и др.) — блок `<handlers>` **внутри `<items xsi:type="form:Table">`**, после `<userVisible>` и до `<dataPath>`:

```xml
<items xsi:type="form:Table">
  <name>МояТЧ</name>
  <id>202</id>
  <visible>true</visible>
  <enabled>true</enabled>
  <userVisible><common>true</common></userVisible>
  <handlers>
    <event>OnActivateRow</event>
    <name>МояТЧПриАктивизацииСтроки</name>
  </handlers>
  <dataPath xsi:type="form:DataPath">
    <segments>МояТЧ</segments>
  </dataPath>
  ...
</items>
```

**ВНИМАНИЕ:** при пересоздании таблицы в EDT-дизайнере блок `<handlers>` **теряется** — всегда проверять и восстанавливать после пересоздания.

### Диагностика

- `get_project_errors` / `validate_form` / `revalidate_objects` НЕ ловят ошибки структуры `form:Table`. Форма валидна в EDT-смысле, но дизайнер её не рисует.
- Сигнал от пользователя: "пересоздал таблицу в дизайнере, теперь работает" = ручная структура была некорректной.
- Проверка: сравнить diff между ручной версией и пересозданной EDT-дизайнером.

### Рекомендация

При ручной генерации Form.form с таблицами:
1. **Предпочтительно** — скопировать структуру `<items xsi:type="form:Table">` из эталонного примера в том же проекте (форма, которая точно открывается) и адаптировать имена/колонки.
2. **Альтернатива** — оставить items-таблицу пустой заготовкой, попросить пользователя пересоздать в дизайнере, затем добавить привязки данных (handlers, dataPath) вручную.
3. **Не рекомендуется** — писать form:Table с нуля по памяти. Ручная генерация — hit-or-miss, с высоким шансом получить валидный но не рендерящийся XML.

### attributes (реквизиты формы) с ValueTable - без изменений

При пересоздании таблиц в дизайнере блок `<attributes>` с `<types>ValueTable</types>` и колонками остаётся как был (только EDT может переставить `<title>` перед `<id>` - не критично). Дело только в `<items xsi:type="form:Table">`.
