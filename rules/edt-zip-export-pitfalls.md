# EDT Zip Export Pitfalls

Грабли EDT при экспорте конфигурации в инфобазу (incremental sync через zip-архив).

Применяется: при создании/правке объектов метаданных в EDT-проектах (Configuration или Extension),
особенно через MCP `edit_metadata` / прямую правку `.mdo`. Касается агента разработчика mcp-edt.

Симптомы общие: EDT-валидация (`get_project_errors`) чистая, но при запуске/обновлении ИБ платформа
падает с `RuntimeCoreException` и сообщением `Файл не обнаружен 'zip:///...'`.

---

## 1. Подсистема с командным интерфейсом без CommandInterface.cmi

### Симптом

```
Ошибка загрузки/выгрузки конфигурации
по причине:
Файл не обнаружен 'zip:///Ext/CommandInterface.xml'
```

Стек: `DesignerSessionThickClientLauncher.importIncrementalXmlToInfobase` →
`LoadFilesQuery.processExecutionResponses`.

### Условие

Создана собственная подсистема (не Adopted) с `<includeInCommandInterface>true</includeInCommandInterface>`
в `.mdo`, но рядом нет файла `CommandInterface.cmi`.

### Фикс

Создать минимальный `CommandInterface.cmi` рядом с `.mdo` подсистемы:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<cmi:CommandInterface xmlns:cmi="http://g5.1c.ru/v8/dt/cmi"/>
```

Затем `clean_project` + `revalidate_objects` для подсистемы.

### Когда применять профилактически

При создании любой новой собственной подсистемы расширения через `edit_metadata create_object Subsystem`,
если предполагается `includeInCommandInterface=true` - сразу создавать пустой `CommandInterface.cmi`.

В типовой конфигурации (без расширения) у части подсистем `.cmi` отсутствует и всё работает - там
индекс EDT давно собран. Для свежедобавленных в расширение лучше создавать явно.

---

## 2. Профилактический чеклист при создании объекта метаданных через EDT MCP

Для агента разработчика mcp-edt - перед каждым `update_database` или запуском ИБ:

### Subsystem (новая собственная)

- [ ] `<name>` уникальное (свой уникальный префикс для расширения)
- [ ] `<includeInCommandInterface>true</includeInCommandInterface>` - **обязателен `CommandInterface.cmi` рядом**
- [ ] Все ссылки `<content>` указывают на существующие объекты конфигурации
- [ ] Объект зарегистрирован в `Configuration.mdo` (`<subsystems>Subsystem.Имя</subsystems>`)

### CommonCommand

- [ ] `<commandParameterType>` корректный (тип ссылки или Undefined для безпараметрических)
- [ ] `CommandModule.bsl` существует и содержит `Процедура ОбработкаКоманды(ПараметрКоманды, ПараметрыВыполненияКоманды)`
- [ ] Включена в подсистему через `<content>CommonCommand.Имя</content>`

### CommonForm

- [ ] `Form.form` существует и валиден (см. `1c-mdo-integrity.md` про `stringQualifiers`)
- [ ] `Module.bsl` существует (даже минимальный, иначе EDT может ругаться)
- [ ] У `.mdo` есть `<form>` ссылка на Form.form

### Adopted-объект (заимствованный)

- [ ] `<objectBelonging>Adopted</objectBelonging>` указано
- [ ] НЕ добавлять `<predefined>` блок с собственными элементами (см. `feedback_adopted_predefined_items`)
- [ ] Реквизиты типа `DocumentRef.X` / `CatalogRef.X` - править `.mdo` вручную через Edit, MCP не персистит (см. `feedback_mdo_ref_types_via_mcp`)

---

## 3. Алгоритм диагностики при ошибке `zip:///...`

При получении `RuntimeCoreException: Файл не обнаружен 'zip:///...'`:

1. **Извлечь путь из ошибки** - например `Ext/CommandInterface.xml`, `Subsystems/X/Ext/CommandInterface.xml`,
   `CommonForms/X/Ext/Form.xml` и т.п.
2. **Определить уровень** - корень `Ext/...` (конфигурация) или `Subsystems/X/Ext/...` (подсистема) или
   объектный.
3. **Найти EDT-источник** - `.cmi` / `.form` / `.mdo` рядом с соответствующим объектом.
4. **Если файл-источник отсутствует** - создать минимальный валидный.
5. **Если файл есть, но повреждён** - сравнить с эталоном (типовая конфигурация рядом).
6. **`clean_project` + `revalidate_objects`** на затронутом объекте.
7. **Повторить экспорт в ИБ.**

---

## 4. Когда обращаться к пользователю

- Если `clean_project` + создание минимального источника не помогает - возможно проблема с самой EDT (workspace .metadata).
  Тогда: попросить пользователя сделать `File → Restart` EDT и попробовать снова. Не пытаться чинить
  `.metadata` напрямую (риск потерять часть workspace-настроек).
- Если ошибка касается типового объекта (не нашего расширения) - не править. Возможна порча типовой
  конфигурации, нужен `Reset to base` со стороны пользователя.

---

## Связанные правила

- `1c-mdo-integrity.md` - целостность MDO (UUID, String length, scale, fillValue, stringQualifiers)
- `mcp-tool-priority.md` - последовательность инструментов EDT MCP
- Memory: `feedback_edt_subsystem_command_interface.md`, `feedback_adopted_predefined_items.md`,
  `feedback_mdo_ref_types_via_mcp.md`
