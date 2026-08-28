---
name: 1c-skd-validate
description: Валидация схемы компоновки данных 1С (СКД). Используй после создания или модификации СКД для проверки корректности
argument-hint: <TemplatePath> [-IndexPath index.json] [-Detailed] [-MaxErrors 20]
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /skd-validate - валидация СКД (DataCompositionSchema)

Проверяет структурную корректность Template.xml схемы компоновки данных. Выявляет ошибки формата, битые ссылки, дубликаты имен.

## Параметры

| Параметр     | Обяз. | Умолч. | Описание                                              |
|--------------|:-----:|---------|---------------------------------------------------------|
| TemplatePath | да    | -       | Путь к Template.xml или каталогу макета                 |
| Detailed     | нет   | -       | Подробный вывод (все проверки, включая успешные)         |
| MaxErrors    | нет   | 20      | Остановиться после N ошибок                             |
| OutFile      | нет   | -       | Записать результат в файл                               |
| IndexPath    | нет   | -      | Индекс от `1c-config-index`: включает сверку наборов данных с конфигурацией |

## Команда

```powershell
powershell.exe -NoProfile -File skills/1c-skd-validate/scripts/skd-validate.ps1 -TemplatePath "src/МойОтчет/Templates/ОсновнаяСхема"
powershell.exe -NoProfile -File skills/1c-skd-validate/scripts/skd-validate.ps1 -TemplatePath "Catalogs/Номенклатура/Templates/СКД/Ext/Template.xml"
```

## Сверка наборов данных с конфигурацией

Набор данных типа `Query` несет текст запроса, типа `Object` - имя объекта. И то и другое
может ссылаться на объект, которого в конфигурации уже нет, - схема при этом остается
структурно корректной, и валидатор ее пропускал.

С `-IndexPath` разбирается ДВУХЧАСТНОЕ имя метаданных: `РегистрНакопления.Остатки` проверяется
на существование. Оба языка запроса. Третья часть не трогается: в запросе она бывает и
табличной частью, и виртуальной таблицей, и значением перечисления, а отличить их без разбора
структуры запроса нельзя.

Литералы и комментарии вырезаются до разбора. Тяжесть - предупреждение.

Полная проверка текста запроса - имена полей, псевдонимы, виртуальные таблицы - в отдельном
навыке `1c-query-validate`.

```bash
python skills/1c-config-index/scripts/config-index.py -ConfigPath src -OutFile .cache/index.json
python skills/1c-skd-validate/scripts/skd-validate.py -TemplatePath src/Reports/Продажи/Templates/Схема/Ext/Template.xml -IndexPath .cache/index.json
```
