---
name: 1c-epf-scaffold
description: Создать пустую внешнюю обработку 1С (scaffold XML-исходников)
argument-hint: <Name> [Synonym]
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# /epf-init — Создание новой обработки

Генерирует минимальный набор XML-исходников для внешней обработки 1С: корневой файл метаданных и каталог обработки.

## Usage

```
/epf-init <Name> [Synonym] [SrcDir]
```

| Параметр  | Обязательный | По умолчанию | Описание                            |
|-----------|:------------:|--------------|-------------------------------------|
| Name      | да           | —            | Имя обработки (латиница/кириллица)  |
| Synonym   | нет          | = Name       | Синоним (отображаемое имя)          |
| SrcDir    | нет          | `src`        | Каталог исходников относительно CWD |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-epf-scaffold/scripts/init.ps1 -Name "<Name>" [-Synonym "<Synonym>"] [-SrcDir "<SrcDir>"]
```

## Дальнейшие шаги

- Добавить форму: `/epf-add-form`
- Добавить макет: `/template-add`
- Добавить справку: `/help-add`
- Собрать EPF: `/epf-build`
