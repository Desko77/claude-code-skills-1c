---
name: 1c-erf-validate
description: Валидация внешнего отчета 1С (ERF). Используй после создания или модификации отчета для проверки корректности
argument-hint: <ObjectPath> [-Detailed] [-MaxErrors 30]
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /erf-validate - валидация внешнего отчета (ERF)

Проверяет структурную корректность XML-исходников внешнего отчета: корневую структуру, InternalInfo, свойства (включая MainDataCompositionSchema), ChildObjects, реквизиты, табличные части, уникальность имен, наличие файлов форм и макетов.

Использует тот же скрипт, что и `/epf-validate` - автоопределение по типу элемента (ExternalReport).

## Параметры

| Параметр   | Обяз. | Умолч. | Описание                                      |
|------------|:-----:|---------|-------------------------------------------------|
| ObjectPath | да    | -       | Путь к корневому XML или каталогу отчета        |
| Detailed   | нет   | -       | Подробный вывод (все проверки, включая успешные) |
| MaxErrors  | нет   | 30      | Остановиться после N ошибок                     |
| OutFile    | нет   | -       | Записать результат в файл (UTF-8 BOM)           |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-epf-validate/scripts/epf-validate.ps1 -ObjectPath "src/МойОтчет"
powershell.exe -NoProfile -File skills/1c-epf-validate/scripts/epf-validate.ps1 -ObjectPath "src/МойОтчет/МойОтчет.xml"
```

