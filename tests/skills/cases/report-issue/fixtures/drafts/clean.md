## Что произошло

Скил `1c-meta-compile` на входе `Catalog.Товары` с реквизитом `Цена: Number(15,2)` падает с ошибкой
`Неизвестный тип`.

## Как воспроизвести

1. Проект `C:/Projects/my-project`, выгрузка в `src/`.
2. Запуск: `pwsh skills/1c-meta-compile/scripts/meta-compile.ps1 -JsonPath object.json -OutputDir src`.

## Среда

Версия набора 1.11.0, PowerShell 7, платформа 8.3.27. Обсуждение: https://t.me/AI_EDT_1c/25
UUID для примера: 00000000-0000-0000-0000-000000000000
