---
name: 1c-form-decompile
description: Декомпиляция управляемой формы 1С (Form.xml) в JSON-черновик формата /form-compile. Используй когда нужно декомпилировать форму, преобразовать Form.xml в JSON, получить DSL из существующей формы для анализа или доработки
argument-hint: <Form.xml> [output.json]
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# /form-decompile - Декомпилятор формы в DSL

Принимает Form.xml управляемой формы 1С (формат выгрузки Конфигуратора) и генерирует JSON-определение в формате скила `1c-form-compile` (спецификация: `docs/form-dsl-spec.md`). Обратная операция к `/form-compile`.

**Результат - ЧЕРНОВИК, а не гарантированный lossless round-trip.** Конструкции, которые DSL не выражает, помечаются ключом `_todo` (массив строк-пояснений) на уровне элемента и/или корня JSON и дублируются предупреждением `[TODO]` в консоль. Перед скармливанием результата `/form-compile` просмотреть черновик и разрешить все `_todo`.

## Использование

```
/form-decompile <Form.xml> [output.json]
```

## Параметры

| Параметр   | Обязательный | Описание                                                        |
|------------|:------------:|------------------------------------------------------------------|
| InputFile  | да           | Путь к Form.xml (выгрузка Конфигуратора, UTF-8, допустим BOM)     |
| OutputFile | нет          | Путь для JSON. По умолчанию рядом с входным: `<имя>.form.json`    |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-form-decompile/scripts/form-decompile.ps1 -InputFile "<путь>/Form.xml" [-OutputFile "<путь>.json"]
```

Альтернатива (Python, тот же алгоритм):

```bash
python skills/1c-form-decompile/scripts/form-decompile.py -InputFile "<путь>/Form.xml" [-OutputFile "<путь>.json"]
```

## Коды возврата

| Код | Значение                                                              |
|-----|------------------------------------------------------------------------|
| 0   | Успех (JSON записан; наличие `_todo` кодом возврата не считается ошибкой) |
| 1   | Ошибка: файл не найден, XML не разбирается, корневой элемент не `<Form>` |
| 2   | Неверные аргументы (python-версия, argparse) |

## Что переносится в DSL

- Заголовок формы, свойства формы (скалярные), обработчики событий формы
- Исключенные стандартные команды (`excludedCommands`)
- Дерево элементов: group, input, check, label, labelField, table (с колонками), pages, page, button, picture, picField, calendar, cmdBar, popup
- События элементов: если имя обработчика совпадает с автоименованием `/form-compile` - только `on`, иначе `on` + `handlers`
- Реквизиты: тип (shorthand: `string(N)`, `decimal(D,F[,nonneg])`, `date`, ссылочные `CatalogRef.X`, платформенные, составные через `" | "`), main, savedData, колонки ValueTable, настройки DynamicList (mainTable, dynamicDataRead, manualQuery)
- Параметры формы (имя, тип, key)
- Команды формы (action, title, shortcut, picture, representation)

## Ограничения - черновик и маркеры _todo

В `_todo` уходит (JSON при этом создается, код возврата 0):

- Типы элементов вне списка выше (RadioButtonField, ChartField, SpreadSheetDocumentField, PlannerField и др.) - в дерево ставится заглушка `{"name": ..., "_todo": [...]}`
- Условное оформление (ConditionalAppearance), командный интерфейс (CommandInterface), содержимое командной панели формы
- Свойства элементов, не описанные в form-dsl-spec.md (цвета, шрифты, layout-тонкости) - каждое отдельной строкой с именем и значением
- Текст запроса динамического списка (DSL хранит только mainTable), настройки реквизита вне DynamicList
- Видимость по ролям (UserVisible/Value), мультиязычные заголовки (берется ru или первый язык), v8:TypeSet / v8:TypeId в типах

Служебные companion-элементы (ContextMenu, ExtendedTooltip, AutoCommandBar таблиц, SearchStringAddition и др.) не переносятся - `/form-compile` генерирует их заново; непустое содержимое такого элемента помечается в `_todo`.

Не предназначен для точечной правки одного поля живой формы: цикл декомпиляция -> правка JSON -> перекомпиляция перезаписывает Form.xml целиком и теряет непереносимые конструкции. Для точечных правок - `/form-edit`.

## Рабочий процесс

1. Claude вызывает `/form-decompile` для получения JSON из Form.xml
2. Claude просматривает `_todo` и решает каждый пункт (переносит вручную, упрощает или сознательно отбрасывает), затем удаляет ключи `_todo`
3. Claude модифицирует JSON (добавляет поля, меняет структуру)
4. Claude вызывает `/form-compile` для генерации нового Form.xml
5. Claude вызывает `/form-validate` для проверки

## Примеры

Декомпиляция с выводом рядом с исходником (получится `Form.form.json`):

```powershell
powershell.exe -NoProfile -File skills/1c-form-decompile/scripts/form-decompile.ps1 -InputFile "src/DataProcessors/Загрузка/Forms/Форма/Ext/Form.xml"
```

Декомпиляция в явный файл:

```powershell
powershell.exe -NoProfile -File skills/1c-form-decompile/scripts/form-decompile.ps1 -InputFile "C:/dump/Форма/Ext/Form.xml" -OutputFile "C:/work/форма-черновик.json"
```

## JSON-схема DSL

Полная спецификация формата: **`docs/form-dsl-spec.md`** (прочитать через Read tool). Справка по потреблению DSL - `skills/1c-form-compile/SKILL.md`.
