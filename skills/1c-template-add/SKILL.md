---
name: 1c-template-add
description: Добавить макет к объекту 1С (обработка, отчет, справочник, документ и др.)
argument-hint: <ObjectName> <TemplateName> <TemplateType>
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# /template-add - Добавление макета

Создает макет указанного типа и регистрирует его в корневом XML объекта.

## Usage

```
/template-add <ObjectName> <TemplateName> <TemplateType>
```

| Параметр      | Обязательный | По умолчанию    | Описание                                         |
|---------------|:------------:|-----------------|--------------------------------------------------|
| ObjectName    | да           | -               | Имя объекта                                      |
| TemplateName  | да           | -               | Имя макета                                       |
| TemplateType  | да           | -               | Тип: HTML, Text, SpreadsheetDocument, BinaryData, DataCompositionSchema |
| Synonym       | нет          | = TemplateName  | Синоним макета                                   |
| SrcDir        | нет          | `src`           | Путь к папке типа объектов (`Reports`, `DataProcessors`, `Catalogs`, `Documents`...), внутри которой лежит `<ObjectName>.xml`. Дефолт `src` подходит для каталогов с внешними обработками/отчетами, лежащими рядом |
| -SetMainSKD   | нет          | -               | Принудительно установить MainDataCompositionSchema |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-template-add/scripts/add-template.ps1 -ObjectName "<ObjectName>" -TemplateName "<TemplateName>" -TemplateType "<TemplateType>" [-Synonym "<Synonym>"] [-SrcDir "<SrcDir>"] [-SetMainSKD]
```

## Пример

Добавить основную СКД к отчету в расширении:

```powershell
powershell.exe -NoProfile -File skills/1c-template-add/scripts/add-template.ps1 -ObjectName "ОтчетПродажи" -TemplateName "ОсновнаяСхемаКомпоновкиДанных" -TemplateType "DataCompositionSchema" -SrcDir "src/cfe/МоеРасширение/Reports"
```

## Маппинг типов

Пользователь может указать тип в свободной форме. Определи нужный по контексту:

| Пользователь пишет                          | TemplateType        | Расширение | Содержимое              |
|---------------------------------------------|---------------------|------------|-------------------------|
| HTML                                        | HTMLDocument        | `.html`    | Пустой HTML-документ    |
| Text, текстовый документ, текст             | TextDocument        | `.txt`     | Пустой файл             |
| SpreadsheetDocument, табличный документ, MXL | SpreadsheetDocument | `.xml`     | Минимальный spreadsheet |
| BinaryData, двоичные данные                 | BinaryData          | `.bin`     | Пустой файл             |
| DataCompositionSchema, СКД, схема компоновки | DataCompositionSchema | `.xml`   | Минимальная DCS-схема   |

## Конвенция именования

Для макетов **печатных форм** (тип SpreadsheetDocument) применяй префикс `ПФ_MXL_`:

| Контекст                                                         | Формат имени               | Пример                  |
|------------------------------------------------------------------|----------------------------|-------------------------|
| Печатная форма (дополнительная обработка вида ПечатнаяФорма, или пользователь явно говорит "печатная форма") | `ПФ_MXL_<КраткоеИмя>`     | `ПФ_MXL_М11`, `ПФ_MXL_СчетФактура`, `ПФ_MXL_КонвертDL` |
| Прочие макеты (загрузка данных, служебные, настройки)            | Без префикса               | `МакетЗагрузки`, `НастройкиПечати` |

Если пользователь указал имя макета без префикса, но контекст - печатная форма, **добавь префикс `ПФ_MXL_` автоматически** и сообщи об этом.

## MainDataCompositionSchema (авто)

При добавлении макета типа `DataCompositionSchema` к `ExternalReport` или `Report`:
- Если `MainDataCompositionSchema` пуст - автоматически заполняется ссылкой на макет
- Используй `--SetMainSKD` чтобы перезаписать существующее значение

## Что создается

```
<SrcDir>/<ObjectName>/Templates/
├── <TemplateName>.xml              # Метаданные макета (1 UUID)
└── <TemplateName>/
    └── Ext/
        └── Template.<ext>          # Содержимое макета
```

## Что модифицируется

- `<SrcDir>/<ObjectName>.xml` - добавляется `<Template>` в конец `ChildObjects`
- Для ExternalReport/Report: может обновляться `MainDataCompositionSchema`
