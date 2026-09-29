---
name: 1c-role-edit
description: Точечная правка существующей роли 1С. Используй когда нужно добавить, изменить или снять права объекта, условие RLS, шаблон ограничения или свойства роли. Новую роль собирает 1c-role-compile
argument-hint: -RolePath <path> -DefinitionFile <json>
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# /role-edit - точечная правка существующей роли 1С

Меняет уже собранную роль: `Roles/<Имя>.xml` и `Roles/<Имя>/Ext/Rights.xml`. UUID роли, права других объектов и их порядок в файле остаются. После правки набор прав затронутого объекта замыкается так же, как при сборке роли, и выстраивается в каноническом порядке выгрузки платформы 8.3.27.

## Когда применять

Роль уже лежит в выгрузке, и нужно изменить ее права, ограничение RLS, шаблон или свойства.

## Когда не применять

| Задача | Куда |
|--------|------|
| Роли еще нет, ее надо создать | `1c-role-compile` |
| Показать состав роли | `1c-role-info` |
| Проверить файл роли | `1c-role-validate` |

## Параметры и команда

| Параметр | Описание |
|----------|----------|
| `RolePath` | `Roles/<Имя>.xml`, каталог роли или `Ext/Rights.xml` |
| `DefinitionFile` | JSON: одна операция, массив или объект с полем `operations` |
| `Operation` | Одна операция без JSON-файла |
| `Object` | Объект метаданных, например `Catalog.Товары` |
| `Rights` | Права для `add-rights`, `set-rights`, `remove-rights`, `deny-rights` |
| `Right` | Одно право для `set-rls` и `remove-rls` |
| `Template` | Имя шаблона ограничения |
| `Condition` | Текст условия RLS или шаблона |
| `Property` | `synonym`, `comment`, `setForNewObjects`, `setForAttributesByDefault`, `independentRightsOfChildObjects` |
| `Value` | Значение свойства или запасной носитель прав и условия |
| `NoValidate` | Не вызывать `1c-role-validate` после записи |

```powershell
powershell.exe -NoProfile -File skills/1c-role-edit/scripts/role-edit.ps1 -RolePath "Roles/Кладовщик.xml" -DefinitionFile "edit.json"
```

```powershell
python skills/1c-role-edit/scripts/role-edit.py -RolePath "Roles/Кладовщик.xml" -Operation add-rights -Object "Catalog.Товары" -Rights "Edit"
```

`-DefinitionFile` и `-Operation` вместе не задают. Неизвестная операция и право, которого нет у типа объекта, завершают команду с кодом 1 до записи.

## Операции

| Операция | Что меняет |
|----------|------------|
| `add-rights` | Добавляет права к объекту. Уже заданные права другого объекта не переписываются |
| `set-rights` | Заменяет набор прав объекта. Условие RLS сохраняется у права, которое осталось в наборе |
| `remove-rights` | Снимает перечисленные права. Пустой набор удаляет блок объекта |
| `deny-rights` | Записывает явное `false`. Если включенное право требует это право, в stderr предупреждение: платформа отбросит блок объекта при загрузке |
| `set-rls` | Ставит условие на право и включает это право |
| `remove-rls` | Снимает условие, само право не снимает |
| `add-template` | Добавляет шаблон. Если имя уже есть, код 1: для замены нужен `set-template` |
| `set-template` | Задает текст шаблона, при отсутствии шаблон создается |
| `remove-template` | Удаляет шаблон по имени |
| `modify-property` | Синоним и комментарий в файле метаданных роли, три признака в `Rights.xml` |

Имена типов и прав можно давать по-русски (`Справочник.Товары`, `Чтение`): они переводятся в канонические английские имена. Ключи JSON читаются без учета регистра.

Замыкание включенных прав совпадает с `1c-role-compile`: `Edit` влечет `Read`, `Update`, `View`, и дальше по зависимостям, замер платформы 8.3.27. У вложенного объекта (`Catalog.Товары.Attribute.Код`) зависимости не дописываются.

`View` и `Edit` реквизита, табличной части, стандартного реквизита, измерения и ресурса регистра после операции совпадают с выгрузкой: `Edit=true` при `View=false` дает `View=true`, `View=false` без явного `Edit` дает `Edit=false`, право, равное `setForAttributesByDefault`, из файла уходит. Право стандартного реквизита с условием RLS остается при любом значении; `set-rls` на реквизит, измерение или ресурс - ошибка ввода. Если при `setForAttributesByDefault=true` и `independentRightsOfChildObjects=false` остаются права на поля объекта без прав на сам объект, в stderr предупреждение со ссылкой на стандарт #std532.

## Примеры

Добавить редактирование справочника и условие на чтение:

```json
[
  { "operation": "add-rights", "object": "Catalog.Товары", "rights": "Edit" },
  { "operation": "set-rls", "object": "Catalog.Товары", "right": "Read", "condition": "#ПоОрганизации(\"\")" },
  { "operation": "add-template", "template": "ПоОрганизации(Мод)", "condition": "ГДЕ Организация = &ТекущаяОрганизация" }
]
```

Снять просмотр у обработки, явно запретить интерактивное удаление, сменить синоним:

```json
[
  { "operation": "remove-rights", "object": "DataProcessor.Загрузка", "rights": ["View"] },
  { "operation": "deny-rights", "object": "Catalog.Товары", "rights": "InteractiveDelete" },
  { "operation": "modify-property", "property": "synonym", "value": "Кладовщик склада" },
  { "operation": "modify-property", "property": "setForNewObjects", "value": true }
]
```

`rights` принимает строку через запятую, список имен или словарь `{"Read": true, "Delete": false}`. Для `deny-rights` перечисленные права записываются как `false` независимо от словаря.
