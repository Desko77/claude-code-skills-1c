---
name: 1c-role-validate
description: Валидация роли 1С. Используй после создания или модификации роли для проверки корректности
argument-hint: <RightsPath> [-IndexPath index.json] [-Detailed] [-MaxErrors 30]
allowed-tools:
  - Bash
  - Read
---

# /role-validate - валидация роли 1С

Проверяет корректность `Rights.xml` роли: формат XML, namespace, глобальные флаги, типы объектов, имена прав, RLS-ограничения, шаблоны. Опционально проверяет метаданные роли (UUID, имя, синоним).

## Параметры

| Параметр     | Обяз. | Умолч. | Описание                                        |
|--------------|:-----:|---------|-------------------------------------------------|
| RightsPath   | да    | -       | Путь к роли (директория или `Rights.xml`)        |
| Detailed     | нет   | -       | Подробный вывод (все проверки, включая успешные)  |
| MaxErrors    | нет   | 30      | Макс. ошибок до остановки (по умолчанию 30)      |
| IndexPath  | нет   | -      | Индекс от `1c-config-index`: включает сверку объектов прав с конфигурацией |
| OutFile      | нет   | -       | Записать результат в файл (UTF-8 BOM)            |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-role-validate/scripts/role-validate.ps1 -RightsPath "Roles/МояРоль"
```

## Дополнительно - проверка прав на перечисления

После запуска валидатора отдельно проверь наличие прав на `Enum.*` в Rights.xml - это анти-паттерн в любой роли:

```powershell
$content = Get-Content -Raw "Roles/МояРоль/Ext/Rights.xml"
if ($content -match '<name>Enum\.[^<]+</name>') {
    Write-Warning "Найдены права на перечисления - удалить (Enum общедоступны, явные права избыточны и ломают LoadConfigFromFiles)"
}
```

Если найдены - предложить пользователю удалить блоки `<object><name>Enum.*</name>...</object>`. См. `1c-role-rights.md`.

## Сверка объектов прав с конфигурацией (проверка 7)

Права на удаленный объект - обычный след рефакторинга: объект убрали, роль осталась. Платформа
такую роль загрузит, а право просто повиснет.

С `-IndexPath` валидатор сверяет каждое имя из `<object><name>`. Имена там те же, что ключи
индекса (`Catalog.Контрагенты`), поэтому карта соответствий не нужна.

Разбираются три формы имени:

- две части - сам объект;
- четыре части - вложенная сущность: `Attribute`, `StandardAttribute`, `TabularSection`,
  `Command`, `Form`, `Template`;
- шесть частей - реквизит табличной части.

Остальные формы (в том числе `Configuration` целиком) не трогаются. Тяжесть - предупреждение.

```bash
python skills/1c-config-index/scripts/config-index.py -ConfigPath src -OutFile .cache/index.json
python skills/1c-role-validate/scripts/role-validate.py -RightsPath src/Roles/Кладовщик -IndexPath .cache/index.json
```
