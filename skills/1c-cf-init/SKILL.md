---
name: 1c-cf-init
description: Создать пустую конфигурацию 1С (scaffold XML-исходников). Используй когда нужно начать новую конфигурацию с нуля
argument-hint: <Name> [-Synonym <name>] [-OutputDir src] [-FormatVersion 2.17]
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /cf-init — Создание пустой конфигурации 1С

Создаёт scaffold исходников пустой конфигурации 1С: `Configuration.xml`, `Languages/Русский.xml`,
`Ext/ClientApplicationInterface.xml` (раскладка командного интерфейса, на нее ссылается `InternalInfo`
конфигурации).

## Параметры и команда

| Параметр | Описание |
|----------|----------|
| `Name` | Имя конфигурации (обязат.) |
| `Synonym` | Синоним (= Name если не указан) |
| `OutputDir` | Каталог для создания (default: `src`) |
| `Version` | Версия конфигурации |
| `Vendor` | Поставщик |
| `CompatibilityMode` | Режим совместимости (default: `Version8_3_24`) |
| `FormatVersion` | Версия формата выгрузки: `2.17`, `2.18`, `2.20`, `2.21` (default: `2.17`) |

## Версия формата

Версия формата задает, какие теги платформа примет при загрузке. Ставить надо не «поновее», а под ту
платформу, куда конфигурация будет грузиться.

| Версия | Платформа | Что добавляет |
|--------|-----------|---------------|
| `2.17` | 8.3.24 и ниже | базовый набор |
| `2.18` | 8.3.25 | мобильная функциональность `TextToSpeech`, тег `TypeReductionMode` |
| `2.19` | 8.3.26 | своих признаков за версией не закреплено |
| `2.20` | 8.3.27 | то же, что 2.18 |
| `2.21` | 8.5 | пространство имен `pal`, свойства главного окна 8.5, формы `Auxiliary*` |

Полная лестница с отметкой, какие ступени сверены с живой платформой, - в
`docs/1c-configuration-spec.md` (§7.1). Она же эталон для навыков: диапазон правится там.

Грабля: `TextToSpeech` на формате 2.17 ломает загрузку XDTO-ошибкой, поэтому на 2.17 тег не пишется
вовсе. Обратное тоже верно - платформа 8.3.24 не примет выгрузку 2.21.

```powershell
powershell.exe -NoProfile -File skills/1c-cf-init/scripts/cf-init.ps1 -Name "МояКонфигурация"
```

## Примеры

```powershell
# Базовая конфигурация
... -Name МояКонфигурация -Synonym "Моя конфигурация" -OutputDir test-tmp/cf

# С версией и поставщиком
... -Name TestCfg -Synonym "Тестовая" -Version "1.0.0.1" -Vendor "Фирма 1С" -OutputDir test-tmp/cf2

# Другой режим совместимости
... -Name TestCfg -CompatibilityMode Version8_3_27 -OutputDir test-tmp/cf3

# Под платформу 8.5: формат 2.21 вместе с режимом совместимости
... -Name TestCfg -FormatVersion 2.21 -CompatibilityMode Version8_3_27 -OutputDir test-tmp/cf4
```

## Верификация

```
/cf-init TestConfig -OutputDir test-tmp/cf
/cf-info test-tmp/cf          — проверить созданное
/cf-validate test-tmp/cf      — валидировать
```
