---
name: 1c-subsystem-validate
description: Валидация подсистемы 1С. Используй после создания или модификации подсистемы для проверки корректности
argument-hint: <SubsystemPath> [-IndexPath index.json] [-Detailed] [-MaxErrors 30]
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /subsystem-validate — валидация подсистемы 1С

Проверяет структурную корректность XML-файла подсистемы из выгрузки конфигурации.

## Параметры

| Параметр      | Обяз. | Умолч. | Описание                                  |
|---------------|:-----:|---------|--------------------------------------------|
| SubsystemPath | да    | —       | Путь к XML-файлу подсистемы                |
| Detailed      | нет   | —       | Подробный вывод (все проверки, включая успешные) |
| MaxErrors     | нет   | 30      | Остановиться после N ошибок                |
| OutFile       | нет   | —       | Записать результат в файл                  |
| IndexPath     | нет   | -       | Индекс от `1c-config-index`: включает сверку состава с конфигурацией |

## Команда

```powershell
powershell.exe -NoProfile -File "skills/1c-subsystem-validate/scripts/subsystem-validate.ps1" -SubsystemPath "Subsystems/Продажи"
powershell.exe -NoProfile -File "skills/1c-subsystem-validate/scripts/subsystem-validate.ps1" -SubsystemPath "Subsystems/Продажи.xml"
```

## Сверка состава с конфигурацией (проверка 14)

Раньше валидатор проверял ФОРМУ записей состава - что это `xr:MDObjectRef`, что имя не во
множественном числе, что нет дублей. Существует ли объект на самом деле, он не знал: про
конфигурацию ему было ничего не известно.

С `-IndexPath` знает. Ссылка на удаленный объект больше не проходит молча.

Имена в составе (`Catalog.Контрагенты`) совпадают с ключами индекса, поэтому карта
соответствий не нужна. Ссылка по UUID не проверяется - разбирать ее нечем.

Тяжесть - предупреждение. В расширении формулировка мягче: объект может лежать в основной
конфигурации, которой в этой выгрузке нет.

```bash
python skills/1c-config-index/scripts/config-index.py -ConfigPath src -OutFile .cache/index.json
python skills/1c-subsystem-validate/scripts/subsystem-validate.py -SubsystemPath src/Subsystems/Продажи -IndexPath .cache/index.json
```
