# Свойства объекта и complex properties

Справочник операций для скалярных свойств объекта и свойств со вложенной XML-структурой (Owners, RegisterRecords, BasedOn, InputByString).

## modify-property

Изменение скалярных свойств объекта. Формат: `Ключ=Значение` (batch через `;;`):
```powershell
-Operation modify-property -Value "CodeLength=11 ;; DescriptionLength=150"
-Operation modify-property -Value "Hierarchical=true"
```

## Complex properties

Свойства со вложенной XML-структурой. Поддерживаются через inline `add-*` / `remove-*` / `set-*` и через JSON `modify.properties`.

| Свойство | Объекты | Inline-значение |
|----------|---------|-----------------|
| Owners | Catalog, ChartOfCharacteristicTypes | `Catalog.XXX` |
| RegisterRecords | Document | `AccumulationRegister.XXX` |
| BasedOn | Document, Catalog, BP, Task | `Document.XXX` |
| InputByString | Catalog, ChartOf*, Task | `StandardAttribute.Description` |

### add-owner / add-registerRecord / add-basedOn

Полное имя метаданных `MetaType.Name`:
```powershell
-Operation add-owner -Value "Catalog.Контрагенты ;; Catalog.Организации"
-Operation add-registerRecord -Value "AccumulationRegister.ОстаткиТоваров"
-Operation add-basedOn -Value "Document.ЗаказКлиента"
```

### add-inputByString

Пути полей (префикс `MetaType.Name.` добавляется автоматически):
```powershell
-Operation add-inputByString -Value "StandardAttribute.Description ;; StandardAttribute.Code"
```

### remove-owner / remove-registerRecord / remove-basedOn / remove-inputByString

```powershell
-Operation remove-owner -Value "Catalog.Контрагенты"
-Operation remove-inputByString -Value "Catalog.МойСпр.StandardAttribute.Code"
```

### set-owners / set-registerRecords / set-basedOn / set-inputByString

Заменяют **весь список** (в отличие от add/remove):
```powershell
-Operation set-owners -Value "Catalog.Организации ;; Catalog.Контрагенты"
-Operation set-registerRecords -Value "AccumulationRegister.Продажи ;; AccumulationRegister.ОстаткиТоваров"
-Operation set-inputByString -Value "StandardAttribute.Description ;; StandardAttribute.Code"
```

## Структурные свойства реквизита

Семь свойств реквизита хранятся не текстом, а вложенной разметкой. Задаются через
`modify.attributes`; навык сам собирает нужную форму. Формы замерены на платформе 8.5.1
круговым прогоном исходники -> база -> выгрузка.

| Свойство | Что писать в DSL | Во что превращается |
|----------|------------------|---------------------|
| Format, EditFormat, ToolTip | строка | локализуемая строка (`v8:item` / `v8:lang` / `v8:content`) |
| MinValue, MaxValue | число | `xsi:type="xs:decimal"` |
| FillValue | число, строка, `EmptyRef` | `xs:decimal` / `xs:string` / `xr:DesignTimeRef` |
| LinkByType | `{ dataPath, linkItem }` | `xr:DataPath` + `xr:LinkItem` |
| ChoiceParameters | `[{ name, value }]` | `app:item` + `app:value` с типом значения |
| ChoiceParameterLinks | `["Параметр=ПутьКПолю"]` | `xr:Link` с `xr:Name` и `xr:DataPath` |

```json
{"modify": {"attributes": {"Контрагент": {
  "ToolTip": "Контрагент документа",
  "FillValue": "EmptyRef",
  "LinkByType": {"dataPath": "Catalog.Заказы.Attribute.Вид", "linkItem": 1},
  "ChoiceParameters": [{"name": "Отбор.ПометкаУдаления", "value": false}],
  "ChoiceParameterLinks": ["Отбор.Владелец=Catalog.Заказы.Attribute.Организация"]
}}}}
```

**Путь к полю пишется полностью** - `<Тип>.<Имя>.Attribute.<Имя>`. Это касается `LinkByType`
и `ChoiceParameterLinks`: краткую форму (`Ссылка`, `Вид`) платформа отвергает при загрузке
сообщением "Неверный путь к полю", и конфигурация не собирается.

`FillValue` понимает краткое `EmptyRef` - навык разворачивает его по типу реквизита
(`CatalogRef.Контрагенты` -> `Catalog.Контрагенты.EmptyRef`).
