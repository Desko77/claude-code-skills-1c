---
name: 1c-erf-init
description: Создать пустой внешний отчет 1С (scaffold XML-исходников)
argument-hint: <Name> [Synonym] [--with-skd]
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# /erf-init - Создание нового отчета

Генерирует минимальный набор XML-исходников для внешнего отчета 1С: корневой файл метаданных и каталог отчета.

## Usage

```
/erf-init <Name> [Synonym] [SrcDir] [--with-skd]
```

| Параметр  | Обязательный | По умолчанию | Описание                              |
|-----------|:------------:|--------------|---------------------------------------|
| Name      | да           | -            | Имя отчета (латиница/кириллица)       |
| Synonym   | нет          | = Name       | Синоним (отображаемое имя)            |
| SrcDir    | нет          | `src`        | Каталог исходников относительно CWD   |
| --WithSKD | нет          | -            | Создать пустую СКД и привязать к MainDataCompositionSchema |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-erf-init/scripts/init.ps1 -Name "<Name>" [-Synonym "<Synonym>"] [-SrcDir "<SrcDir>"] [-WithSKD]
```

## Дальнейшие шаги

- Добавить форму: `/form-add`
- Добавить макет: `/template-add`
- Добавить справку: `/help-add`
- Собрать ERF: `/erf-build`
