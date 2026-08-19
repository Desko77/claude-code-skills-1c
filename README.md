# Claude Code Skills for 1C:Enterprise

Набор скилов, правил и команд для [Claude Code](https://docs.anthropic.com/en/docs/claude-code):
агент работает с 1С не вслепую по тексту файлов, а по формату платформы.

[![Лицензия MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Релиз](https://img.shields.io/github/v/release/Desko77/claude-code-skills-1c)](https://github.com/Desko77/claude-code-skills-1c/releases)
[![Тесты](https://github.com/Desko77/claude-code-skills-1c/actions/workflows/tests.yml/badge.svg)](https://github.com/Desko77/claude-code-skills-1c/actions/workflows/tests.yml)

Скилы дают агенту готовые операции над исходниками: собрать объект метаданных, форму, роль, схему
компоновки, расширение, внешнюю обработку - и разобрать их обратно. Правила задают, как он это
делает: стандарты BSL, антипаттерны, требования EDT, работа с БСП. Скрипты правят XML-выгрузку
напрямую, поэтому базовые операции идут без запущенной платформы и без Конфигуратора. Вместе с нашим
плагином [AI-EDT](https://github.com/Desko77/ai-edt) агент получает еще и семантическую модель самой
1C:EDT - об этом ниже.

Проверка результата тоже идет по выгрузке, без внешних инструментов. Четырнадцать валидаторов
разбирают XML объекта, формы, роли, схемы компоновки, макета, расширения. Сверх этого
`1c-config-index` собирает индекс конфигурации, и валидаторы сверяют объект с ОСТАЛЬНОЙ
конфигурацией: ссылочные типы реквизитов, пути данных формы, состав подсистемы, права роли, наборы
данных СКД, имена таблиц и полей в запросе, вызовы общих модулей. Ни платформа, ни EDT, ни запущенная
база для этого не нужны. Границу набор обозначает прямо: это проверка имен и структуры, а типы
выражений, семантика BSL и план запроса без платформы недоступны.

Кому пригодится: разработчику 1С, который держит исходники под git и готов отдать агенту рутину -
scaffold объектов, разбор чужих обработок, выгрузку и загрузку конфигурации, ревью, тесты.

Отдельный класс - **справочники API прикладных конфигураций**. Агент не угадывает, какой метод
типовой вызвать, а берет его из справочника. Первый такой скил - `zup-hr-api-reference` для
1С:ЗУП 3.1: кадровый учет, средний заработок и начисления, пособия и обмен с СФР,
регламентированная отчетность.

## Что умеет

| Группа | Что делает | Скилов |
|--------|------------|--------|
| Маршрутизатор | подсказывает, каким скилом решать задачу | 1 |
| Конфигурация | создать с нуля, изменить свойства, проанализировать, проиндексировать, прочитать состояние поддержки | 8 |
| Объекты метаданных | собрать из JSON, разобрать обратно в JSON, править реквизиты и табличные части | 6 |
| Управляемые формы | собрать из DSL или по метаданным объекта, править, разобрать, проверить | 8 |
| Расширения | создать, заимствовать объект, поставить перехватчик на метод, сверить с основной | 6 |
| Обработки и отчеты | собрать .epf и .erf из исходников и разобрать обратно | 10 |
| Базы данных | создать, выгрузить и загрузить .cf, .dt и XML, обновить, запустить | 11 |
| Роли, подсистемы, макеты, СКД, XDTO | сборка и разбор своим DSL под каждый вид | 25 |
| Веб-публикация и тестирование | опубликовать базу через Apache, прогнать сценарий в браузере | 5 |
| БСП, 1С 7.7, обмены | поиск функций БСП, разработка под 7.7, правила КД 2.0 и 3.1 | 7 |
| Справочные и утилитарные | документация платформы, справочники API типовых, транскрибация, docx и xlsx, окружение агента | 28 |

Полный перечень с описанием каждого скила - в разделе [Скилы](#скилы-115) ниже.

И **35 правил** - подключаются один раз и действуют во всех задачах, без напоминаний в каждом
промпте:

- **код и запросы** - стандарты BSL, антипаттерны вроде запроса в цикле, оптимизация, чеклист ревью;
- **формы, метаданные, EDT** - требования к XML форм, целостность MDO, ограничения экспорта из EDT;
- **БСП и типовые** - переиспользовать готовое вместо своего велосипеда, размечать правки типовых;
- **процесс и сам агент** - SDD-workflow, выбор модели под задачу, рабочая память, безопасность git.

## Как это выглядит

Справочник с реквизитами и табличной частью. На входе пятнадцать строк JSON:

```json
{
  "type": "Справочник",
  "name": "Контрагенты",
  "codeLength": 11,
  "descriptionLength": 150,
  "hierarchical": true,
  "attributes": [
    "ИНН: Строка(12), index",
    "Покупатель: Булево",
    "ОсновнойМенеджер: СправочникСсылка.Пользователи"
  ],
  "tabularSections": {
    "КонтактныеЛица": ["ФИО: Строка(150), req", "Телефон: Строка(20)"]
  }
}
```

Один вызов скила `1c-meta-compile` - и на диске почти шестьсот строк корректного XML:

- `Catalogs/Контрагенты.xml` - 580 строк со всеми обязательными секциями, стандартными реквизитами
  и сгенерированными UUID;
- `Catalogs/Контрагенты/Ext/ObjectModule.bsl` - заготовка модуля объекта;
- запись `<Catalog>Контрагенты</Catalog>` в `Configuration.xml`, то есть объект сразу в составе
  конфигурации, а не сиротой на диске;
- `Validation OK: Catalog.Контрагенты (11 checks)` от валидатора набора.

Структуру файла агент не выдумывает и не подсматривает в чужих выгрузках: формат зашит в скил и
закреплен снапшот-тестами, которые сравнивают результат с эталоном.

## Установка

Два пути на выбор: попросить агента или сделать руками.

### Вариант 1: попросить агента, без единой команды

Скопируйте текст ниже, подставьте свой каталог вместо `<КАТАЛОГ>` и отдайте агенту в новой сессии.
Дальше он все сделает сам: склонирует репозиторий, снимет опись машины, покажет план и поставит
только то, что вы выберете.

```
Установи мне набор скилов, правил и связанных инструментов для работы с 1С
из репозитория https://github.com/Desko77/claude-code-skills-1c

Порядок:
1. Склонируй репозиторий в <КАТАЛОГ>, если он уже там - выполни git pull.
2. Прочитай в нем skills/claude-env-setup/SKILL.md и ОБА файла из
   skills/claude-env-setup/references/ - safety.md и components.md.
   Дальше действуй строго по ним.
3. Сними опись моей машины: что уже установлено, какие MCP-серверы
   прописаны, какие порты заняты, что есть из зависимостей
   (Python, Node, Docker, ffmpeg, платформа 1С).
4. Покажи план таблицей и дождись моего выбора. Ничего не ставь
   до моего ответа.

Ограничения:
- Ничего не перезаписывай молча. Файл, который у меня уже есть
  и отличается, - покажи diff и спроси.
- Конфигурацию MCP (~/.claude/settings.json, ~/.claude.json,
  .mcp.json проекта) правь СЛИЯНИЕМ: добавляй только отсутствующие
  ключи, файл целиком не переписывай.
- Не трогай мои скилы и правила, которых нет в наборе.
- Не завершай запущенные сеансы 1С и EDT, не пересоздавай
  существующие venv и Docker-контейнеры.
- Перед первой правкой любого конфига сделай резервную копию
  с меткой времени.

В конце дай отчет: что поставлено, что не встало и почему,
и отдельным списком - что мне нужно сделать руками: перезапустить
клиент, вписать ключи API, поставить плагин в EDT.
```

Этот же путь годится для обновления: агент доставит недостающее и не тронет ваши правки. Готовые
промпты под остальные случаи - обновление рабочей машины, проверка без установки, установка одного
компонента - лежат в [`skills/claude-env-setup/PROMPT.md`](skills/claude-env-setup/PROMPT.md).

### Вариант 2: руками, если вы знаете, что делаете

```bash
cp -r skills/* ~/.claude/skills/     # или один скил: cp -r skills/1c-meta-compile ~/.claude/skills/
cp rules/*.md ~/.claude/rules/
cp commands/* ~/.claude/commands/
```

> Копирование затрет ваши правки, если вы дорабатывали скилы под себя. На такой машине берите
> вариант 1: он показывает diff и спрашивает по каждому расхождению.

## Первая задача

Откройте Claude Code в каталоге с исходниками 1С и скажите задачу обычными словами: «создай
справочник Контрагенты с ИНН и табличной частью контактных лиц». Скил агент подберет сам.

Проверить, что набор работает: `node tests/skills/runner.mjs cases/meta-compile` (нужен Node.js 18+).

## AI-EDT: агентная разработка прямо в 1C:EDT

Набор раскрывается полностью вместе с **[AI-EDT](https://github.com/Desko77/ai-edt)** - MCP-сервером,
который работает плагином **внутри запущенной 1C:EDT** и дает ассистенту не текст файлов, а
семантическую модель самой среды.

| | |
|---|---|
| Репозиторий | **https://github.com/Desko77/ai-edt** |
| Установка | update site **https://desko77.github.io/ai-edt/** (в EDT: Help -> Install New Software) |
| Требования | 1C:EDT 2026.2 или 2026.1 |

Что это меняет на практике: ассистент разрешает ссылки на объекты метаданных, строит иерархии
вызовов, спрашивает у EDT выведенный тип в позиции BSL, правит метаданные без ручного XML, ставит
точки останова и читает переменные в приостановленной сессии - а результат тут же проверяет
валидаторами самой EDT. Ошибка всплывает на месте, а не при первой загрузке конфигурации в базу.
Больше сотни операций собраны в фасады `code_search`, `edit_metadata`, `launch_debugger`,
`diagnostics`, `insights`, `security_audit`, поэтому клиент видит компактный набор инструментов
вместо длинного списка почти одинаковых команд.

Скил `ai-edt-tools` в этом наборе - каталог этих инструментов и типовых сценариев: что вызывать под
задачу, в каком порядке и какие проверки обязательны после правки.

Обратное тоже стоит знать: **часть набора не зависит от плагина вообще**. 1С 7.7, веб-публикация и
тестирование через браузер, правила конвертации данных 2.0 и 3.1, Cleverence, справочники API типовых
конфигураций - в AI-EDT ничего этого нет, и там маршрут только через скилы. Базовые операции над
исходниками (собрать объект, форму, роль, СКД, расширение, разобрать обработку) тоже идут без EDT и
без платформы - плагин добавляет к ним семантику и проверку, но не заменяет их.

Часть проверок, прежде доступных только в EDT, тоже работает по выгрузке. `1c-config-index` собирает
индекс конфигурации в один JSON, валидаторы читают его параметром `-IndexPath` и сверяют объект с
остальной конфигурацией: типы реквизитов, пути данных формы, состав подсистемы, права роли, наборы
данных СКД, имена в запросе, вызовы общих модулей. Это проверка имен: типы выражений, семантика BSL
и план запроса без платформы недоступны.

## Типовые сценарии

| Задача | Чем решается |
|--------|--------------|
| Добавить в конфигурацию документ, а к нему форму | `1c-meta-compile`, затем `1c-form-compile` |
| Доработать типовую, не снимая с поддержки | `1c-cfe-init`, `1c-cfe-borrow`, `1c-cfe-patch-method` |
| Собрать внешнюю обработку из исходников и загрузить в базу | `1c-epf-build`, `1c-db-load-cf` |
| Разобрать чужую .epf, чтобы понять, что она делает | `1c-epf-dump`, затем `1c-form-info` |
| Выгрузить конфигурацию в XML и положить под git | `1c-db-dump-xml` |
| Написать запрос и проверить его до запуска | скил `composing-1c-queries`; имена таблиц и полей - `1c-query-validate` по выгрузке, типы и план - `validate_query` из AI-EDT |
| Найти битые ссылки после рефакторинга: типы реквизитов, пути данных форм, состав подсистем, права ролей | `1c-config-index`, затем валидаторы с `-IndexPath` |
| Не угадывать, каким скилом решать задачу | `1c-config-router` |

## Зависимости

| Компонент | Обязательно | Для чего |
|-----------|-------------|----------|
| PowerShell 5.1+ (Windows) | Да | Скрипты скилов (.ps1) |
| Python 3.8+ | Нет | Альтернативные скрипты (.py), `v8unpack-cf`, `check-uuid`, `img-grid-analysis` |
| [v8unpack](https://pypi.org/project/v8unpack/) | Нет | Распаковка/сборка CF/CFE/EPF без платформы |
| 1C:Enterprise 8.3 | Нет | Скилы группы `db-*`, сборка EPF/ERF |
| Node.js + npm-пакет `docx` | Нет | `md-to-docx` (конвертация Markdown в DOCX) |
| `ffmpeg`, `ffprobe` | Нет | `transcribe`, `transcribe-audio-local` (извлечение аудио, разбивка длинных файлов) |
| NVIDIA GPU + CUDA 12 + cuDNN 9 | Нет | `transcribe`, `transcribe-audio-local` (локальный движок faster-whisper + sherpa-onnx). CPU тоже работает, но в 10+ раз медленнее |
| `gcomp` | Нет | `1c77-dev` (разбор/сборка .ert и 1Cv7.MD для 1С 7.7) |
| Node.js + `@mermaid-js/mermaid-cli` (mmdc) | Нет | `mermaid-render` (рендер диаграмм в PNG/SVG/PDF) |
| Обработка `MCP_Toolkit.epf` ([ROCTUP](https://github.com/ROCTUP/1c-mcp-toolkit)) | Нет | `1c-mcp-toolkit` (HTTP API к живой запущенной базе 1С) |
| MCP-серверы (см. таблицу ниже) | Нет | Анализ кода, валидация запросов, документация ИТС/платформы/конфигураций |

Скилы спроектированы по слоям - базовые (генерация XML) работают без платформы, продвинутые требуют 1С или MCP.

### MCP-серверы, на которые ссылаются скилы

Сами серверы в этот репозиторий не входят - они ставятся и настраиваются отдельно, в `.mcp.json`
проекта или в пользовательских настройках Claude Code. Здесь перечислены ключи ровно в том виде, в
каком они пишутся в скилах и правилах, чтобы ссылки читались однозначно.

| Ключ сервера | Для чего | Кто использует |
|--------------|----------|----------------|
| [`ai-edt`](https://github.com/Desko77/ai-edt) | BSL-код, метаданные, формы, валидация запросов, ошибки проекта, отладка, обновление ИБ. Плагин внутри 1C:EDT, 100+ операций в фасадах. [Update site](https://desko77.github.io/ai-edt/) | `ai-edt-tools`, `composing-1c-queries`, `1c-query-optimization` |
| [`bsl-platform-help`](https://github.com/Desko77/mcp-bsl-platform-help-context) | API платформы: методы, типы, сигнатуры, конструкторы, стиль и строгая типизация | `1c-platform-docs` |
| [`1c-naparnik`](https://github.com/Desko77/1c-ai-mcp) | Ревью кода, стандарты ИТС, документация платформы и конфигураций | `1c-naparnik` |
| `1c-mcp_ssl_server` | Поиск функций БСП по описанию задачи | `1c-ssl-patterns` |
| [`1c-forms-mcp`](https://github.com/Desko77/1c-formsserver) | Генерация обычных (неуправляемых) форм вне EDT-проекта | правило `forms_generation.md` |
| `1c77-metadata` | Конфигурация 1С 7.7: объекты, реквизиты, модули ([установка](https://github.com/ivanarama/77MCP)) | `1c77-dev` |
| `1c-syntax-checker-mcp` | Проверка синтаксиса BSL без запущенной EDT | правило `mcp-tool-priority.md` |
| [`1c-templates-mcp`](https://github.com/Desko77/1c-templates-mcp) | Семантический поиск по 2200+ шаблонам кода BSL | правило `mcp-tool-priority.md` |

Скил `ai-edt-tools` и правила написаны под **AI-EDT**: ключ сервера `ai-edt`, инструменты свернуты
в фасады с маршрутизацией через `operation=`. Если у вас подключен другой MCP-плагин для EDT, каталог
из `references/` к нему неприменим - имена инструментов и их состав там свои: берите фактические из
`tools/list` своей сессии.

Отдельно: `1c-mcp-toolkit` - это скил репозитория, а не MCP-сервер. Он ходит в живую базу по HTTP через
обработку `MCP_Toolkit.epf`, поэтому в `.mcp.json` его прописывать не нужно.

## Совместимые сторонние плагины

Основной спутник набора - собственный **[AI-EDT](https://github.com/Desko77/ai-edt)** (см. раздел в начале).
Кроме него с набором сочетаются:

**[bsl-language-server](https://github.com/1c-syntax/claude-code-bsl-lsp)** - полноценная интеграция
BSL Language Server в Claude Code как LSP: диагностики, go to definition, find references, hover,
форматирование, code actions для `.bsl` и `.os`.

```
/plugin marketplace add 1c-syntax/claude-code-bsl-lsp
/plugin install bsl-language-server@bsl-language-server
```

**Плагины Anthropic** - `code-review` и `pr-review-toolkit` для ревью PR агентами, `mcp-server-dev`
для разработки MCP-серверов, `claude-md-management` для поддержания CLAUDE.md, `security-guidance`
для security-ревью.

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install <name>@claude-plugins-official
```

## Скилы (115)

Начать проще всего с `1c-config-router`: он сам определяет, каким скилом или workflow
решать задачу.

<table>
<thead><tr><th align="left">Скил</th><th align="left">Описание</th></tr></thead>
<tbody>
<tr><th colspan="2" align="left">Маршрутизатор</th></tr>
<tr><td><code>1c-config-router</code></td><td>Определяет нужный workflow или скил для задачи</td></tr>
<tr><th colspan="2" align="left">Конфигурация (cf-*, support-*)</th></tr>
<tr><td><code>1c-cf-init</code></td><td>Создать пустую конфигурацию (scaffold XML), версии формата 2.17-2.21</td></tr>
<tr><td><code>1c-cf-info</code></td><td>Анализ структуры конфигурации</td></tr>
<tr><td><code>1c-config-index</code></td><td>Индекс всей выгрузки одним JSON: объекты, реквизиты, измерения регистров, экспортные методы общих модулей. Основа проверок, где объект сверяется с остальной конфигурацией</td></tr>
<tr><td><code>1c-cf-edit</code></td><td>Изменить свойства конфигурации</td></tr>
<tr><td><code>1c-cf-validate</code></td><td>Валидация конфигурации</td></tr>
<tr><td><code>1c-cf-add-object</code></td><td>Workflow: добавить объект в конфигурацию</td></tr>
<tr><td><code>1c-cf-new-project</code></td><td>Workflow: создать конфигурацию с нуля</td></tr>
<tr><td><code>1c-support-state</code></td><td>Состояние поддержки в XML-выгрузке: чтение, editable/off-support/locked, возможность изменения</td></tr>
<tr><th colspan="2" align="left">Объекты метаданных (meta-*)</th></tr>
<tr><td><code>1c-meta-compile</code></td><td>Создать объект метаданных из JSON DSL (37 типов)</td></tr>
<tr><td><code>1c-meta-decompile</code></td><td>Декомпиляция объекта в JSON-заготовку формата meta-compile - черновик нового объекта по образцу</td></tr>
<tr><td><code>1c-meta-edit</code></td><td>Изменить реквизиты, ТЧ, свойства объекта</td></tr>
<tr><td><code>1c-meta-info</code></td><td>Анализ структуры объекта</td></tr>
<tr><td><code>1c-meta-remove</code></td><td>Удалить объект из конфигурации</td></tr>
<tr><td><code>1c-meta-validate</code></td><td>Валидация объекта метаданных</td></tr>
<tr><th colspan="2" align="left">Формы (form-*)</th></tr>
<tr><td><code>1c-form-compile</code></td><td>Создать форму из JSON DSL</td></tr>
<tr><td><code>1c-form-decompile</code></td><td>Разобрать Form.xml в JSON-черновик DSL</td></tr>
<tr><td><code>1c-form-edit</code></td><td>Добавить элементы, реквизиты, команды в форму</td></tr>
<tr><td><code>1c-form-add</code></td><td>Добавить форму к объекту конфигурации</td></tr>
<tr><td><code>1c-form-info</code></td><td>Анализ структуры формы</td></tr>
<tr><td><code>1c-form-patterns</code></td><td>Паттерны проектирования форм</td></tr>
<tr><td><code>1c-form-remove</code></td><td>Удалить форму</td></tr>
<tr><td><code>1c-form-validate</code></td><td>Валидация формы</td></tr>
<tr><th colspan="2" align="left">Расширения (cfe-*)</th></tr>
<tr><td><code>1c-cfe-init</code></td><td>Создать расширение конфигурации</td></tr>
<tr><td><code>1c-cfe-borrow</code></td><td>Заимствовать объект из конфигурации</td></tr>
<tr><td><code>1c-cfe-patch-method</code></td><td>Перехватить метод (Before/After/ModificationAndControl)</td></tr>
<tr><td><code>1c-cfe-diff</code></td><td>Анализ расширения</td></tr>
<tr><td><code>1c-cfe-validate</code></td><td>Валидация расширения</td></tr>
<tr><td><code>1c-cfe-full-cycle</code></td><td>Workflow: полный цикл создания расширения</td></tr>
<tr><th colspan="2" align="left">Обработки и отчеты (epf-*, erf-*)</th></tr>
<tr><td><code>1c-epf-scaffold</code></td><td>Создать пустую обработку</td></tr>
<tr><td><code>1c-epf-add-form</code></td><td>Добавить форму к обработке</td></tr>
<tr><td><code>1c-epf-build</code></td><td>Собрать EPF из XML-исходников</td></tr>
<tr><td><code>1c-epf-dump</code></td><td>Разобрать EPF в XML-исходники</td></tr>
<tr><td><code>1c-epf-validate</code></td><td>Валидация обработки</td></tr>
<tr><td><code>1c-epf-full-cycle</code></td><td>Workflow: полный цикл создания обработки</td></tr>
<tr><td><code>1c-erf-init</code></td><td>Создать пустой отчет</td></tr>
<tr><td><code>1c-erf-build</code></td><td>Собрать ERF</td></tr>
<tr><td><code>1c-erf-dump</code></td><td>Разобрать ERF</td></tr>
<tr><td><code>1c-erf-validate</code></td><td>Валидация отчета</td></tr>
<tr><th colspan="2" align="left">Пакеты XDTO (xdto-*)</th></tr>
<tr><td><code>1c-xdto-compile</code></td><td>Создать пакет XDTO из XML-схемы (XSD)</td></tr>
<tr><td><code>1c-xdto-decompile</code></td><td>Выгрузить пакет XDTO обратно в XSD</td></tr>
<tr><td><code>1c-xdto-edit</code></td><td>Точечная правка типов и свойств пакета</td></tr>
<tr><td><code>1c-xdto-info</code></td><td>Структура пакета: типы, свойства, точки входа</td></tr>
<tr><td><code>1c-xdto-validate</code></td><td>Валидация пакета XDTO</td></tr>
<tr><th colspan="2" align="left">Подсистемы и интерфейс</th></tr>
<tr><td><code>1c-subsystem-compile</code></td><td>Создать подсистему</td></tr>
<tr><td><code>1c-subsystem-edit</code></td><td>Изменить состав подсистемы</td></tr>
<tr><td><code>1c-subsystem-info</code></td><td>Анализ подсистемы</td></tr>
<tr><td><code>1c-subsystem-validate</code></td><td>Валидация подсистемы</td></tr>
<tr><td><code>1c-interface-edit</code></td><td>Настроить командный интерфейс</td></tr>
<tr><td><code>1c-interface-validate</code></td><td>Валидация интерфейса</td></tr>
<tr><th colspan="2" align="left">Макеты (mxl-*, template-*)</th></tr>
<tr><td><code>1c-mxl-compile</code></td><td>Создать макет из JSON DSL</td></tr>
<tr><td><code>1c-mxl-decompile</code></td><td>Разобрать макет в JSON</td></tr>
<tr><td><code>1c-mxl-info</code></td><td>Анализ макета</td></tr>
<tr><td><code>1c-mxl-validate</code></td><td>Валидация макета</td></tr>
<tr><td><code>1c-template-add</code></td><td>Добавить макет к объекту</td></tr>
<tr><td><code>1c-template-remove</code></td><td>Удалить макет</td></tr>
<tr><th colspan="2" align="left">Роли (role-*)</th></tr>
<tr><td><code>1c-role-compile</code></td><td>Создать роль из описания прав</td></tr>
<tr><td><code>1c-role-info</code></td><td>Анализ роли</td></tr>
<tr><td><code>1c-role-validate</code></td><td>Валидация роли</td></tr>
<tr><th colspan="2" align="left">СКД (skd-*)</th></tr>
<tr><td><code>1c-skd-compile</code></td><td>Создать схему компоновки данных</td></tr>
<tr><td><code>1c-skd-decompile</code></td><td>Разобрать XML СКД в JSON-черновик DSL</td></tr>
<tr><td><code>1c-skd-edit</code></td><td>Изменить существующую СКД</td></tr>
<tr><td><code>1c-skd-info</code></td><td>Анализ СКД</td></tr>
<tr><td><code>1c-skd-validate</code></td><td>Валидация СКД</td></tr>
<tr><th colspan="2" align="left">Базы данных (db-*)</th></tr>
<tr><td><code>1c-db-list</code></td><td>Управление реестром баз</td></tr>
<tr><td><code>1c-db-create</code></td><td>Создать информационную базу</td></tr>
<tr><td><code>1c-db-dump-cf</code></td><td>Выгрузить конфигурацию в CF</td></tr>
<tr><td><code>1c-db-dump-dt</code></td><td>Выгрузить всю ИБ в DT (полный бэкап)</td></tr>
<tr><td><code>1c-db-dump-xml</code></td><td>Выгрузить конфигурацию в XML</td></tr>
<tr><td><code>1c-db-load-cf</code></td><td>Загрузить конфигурацию из CF</td></tr>
<tr><td><code>1c-db-load-dt</code></td><td>Восстановить ИБ из DT (деструктивная)</td></tr>
<tr><td><code>1c-db-load-xml</code></td><td>Загрузить конфигурацию из XML</td></tr>
<tr><td><code>1c-db-load-git</code></td><td>Загрузить изменения из Git</td></tr>
<tr><td><code>1c-db-update</code></td><td>Обновить конфигурацию БД</td></tr>
<tr><td><code>1c-db-run</code></td><td>Запустить 1С:Предприятие</td></tr>
<tr><th colspan="2" align="left">Веб-публикация и тестирование (web-*)</th></tr>
<tr><td><code>1c-web-publish</code></td><td>Публикация ИБ на веб-сервере (Apache/IIS)</td></tr>
<tr><td><code>1c-web-unpublish</code></td><td>Отмена публикации ИБ</td></tr>
<tr><td><code>1c-web-info</code></td><td>Информация о веб-публикациях</td></tr>
<tr><td><code>1c-web-stop</code></td><td>Остановка веб-сервера</td></tr>
<tr><td><code>1c-web-test</code></td><td>Тестирование 1С через веб-клиент (автоматизация браузера)</td></tr>
<tr><th colspan="2" align="left">БСП</th></tr>
<tr><td><code>1c-bsp-registration</code></td><td>Регистрация обработки в БСП</td></tr>
<tr><td><code>1c-bsp-command</code></td><td>Добавить команду БСП</td></tr>
<tr><td><code>1c-ssl-patterns</code></td><td>Паттерны подсистем БСП</td></tr>
<tr><th colspan="2" align="left">Разработка 1С 7.7</th></tr>
<tr><td><code>1c77-dev</code></td><td>Разработка под 1С 7.7: .1s/.ert/.frm, 1Cv7.MD, gcomp, кодировка CP1251</td></tr>
<tr><th colspan="2" align="left">Конвертация данных и интеграции</th></tr>
<tr><td><code>kd2-rules</code></td><td>Правила обмена «Конвертация данных 2.0» через MCP-toolkit</td></tr>
<tr><td><code>kd31-rules</code></td><td>Правила обмена «Конвертация данных 3.1» через MCP-toolkit</td></tr>
<tr><td><code>cleverence-mslx</code></td><td>Mobile SMARTS (Клеверенс): .mslx-алгоритмы ТСД, online-вызов 1С</td></tr>
<tr><th colspan="2" align="left">Справочные и утилитарные</th></tr>
<tr><td><code>ai-edt-tools</code></td><td>Справочник инструментов AI-EDT (MCP-плагин для 1С:EDT): фасады, сценарии, грабли</td></tr>
<tr><td><code>1c-naparnik</code></td><td>Справочник инструментов 1С:Напарник (анализ кода, ИТС, документация)</td></tr>
<tr><td><code>1c-mcp-toolkit</code></td><td>Прямой HTTP API к живой запущенной базе 1С (запросы, BSL-код, метаданные, журнал)</td></tr>
<tr><td><code>1c-platform-docs</code></td><td>Поиск по документации API платформы</td></tr>
<tr><td><code>1c-query-validate</code></td><td>Проверка текста запроса по выгрузке: существуют ли таблицы, табличные части, виртуальные таблицы регистров и поля</td></tr>
<tr><td><code>1c-bsl-validate</code></td><td>Проверка вызовов общих модулей в BSL по выгрузке: существует ли модуль и экспортный ли метод</td></tr>
<tr><td><code>1c-query-optimization</code></td><td>Продвинутая оптимизация запросов</td></tr>
<tr><td><code>zup-hr-api-reference</code></td><td>Справочник API 1С:ЗУП 3.1: кадровый учет (физлица, стажи, договоры ГПХ, представления СКД) и расчет (средний заработок, начисления, пособия/СФР, взносы, отчетность)</td></tr>
<tr><td><code>1c-help-manage</code></td><td>Встроенная справка объектов 1С</td></tr>
<tr><td><code>composing-1c-queries</code></td><td>Руководство по языку запросов 1С</td></tr>
<tr><td><code>1c-vanessa-steps</code></td><td>Реестр 1569 шагов Vanessa Automation: поиск шага по смыслу и валидация сценария .feature перед прогоном</td></tr>
<tr><td><code>v8unpack-cf</code></td><td>Распаковка/сборка CF/CFE/EPF</td></tr>
<tr><td><code>img-grid-analysis</code></td><td>Анализ изображений для макетов</td></tr>
<tr><td><code>md-to-docx</code></td><td>Конвертация Markdown в DOCX</td></tr>
<tr><td><code>docx-from-sample</code></td><td>Новый DOCX в оформлении готового образца: стили, нумерация заголовков, таблицы, колонтитулы наследуются из файла-образца</td></tr>
<tr><td><code>transcribe</code></td><td>Транскрибация аудио (локально, faster-whisper + sherpa-onnx GPU) и видео (Gemini API). Установка через <code>scripts/setup.py</code></td></tr>
<tr><td><code>transcribe-audio-local</code></td><td>Только аудио, только локально, self-contained - для передачи на другую машину без облака</td></tr>
<tr><td><code>meeting-to-tasks</code></td><td>Полный цикл «запись встречи -&gt; список задач -&gt; план разработки по SDD на каждую задачу»</td></tr>
<tr><td><code>mermaid-diagrams</code></td><td>Генерация диаграмм Mermaid</td></tr>
<tr><td><code>mermaid-render</code></td><td>Рендер Mermaid в PNG/SVG/PDF через локальный mmdc</td></tr>
<tr><td><code>powershell-windows</code></td><td>PowerShell на Windows</td></tr>
<tr><td><code>lmstudio-api</code></td><td>Справочник HTTP-API LM Studio: загрузка/выгрузка моделей, контекст, отключение reasoning, грабли протокола</td></tr>
<tr><td><code>sync-fork</code></td><td>Синхронизация git-форка с upstream без потери своих доработок</td></tr>
<tr><td><code>skill-creator</code></td><td>Создание, тестирование и оптимизация скилов (evals, grading, description loop)</td></tr>
<tr><td><code>prompt-enhancer</code></td><td>Улучшение и структурирование коротких промптов и постановок задач в подробные ТЗ</td></tr>
<tr><td><code>humanize-ai-text</code></td><td>Переписывание AI-текста (отчеты, README, доки, письма) в живой человеческий стиль: ломает ровный ритм, убирает штампы и буферные вступления</td></tr>
<tr><td><code>claude-env-setup</code></td><td>Установка и обновление окружения агента: опись машины -&gt; план -&gt; установка выбранного; конфиги MCP правятся слиянием, чужое не затирается</td></tr>
<tr><td><code>claude-md-bootstrap</code></td><td>Генерация проектного CLAUDE.md - контекста проекта для AI-агента (IF-THEN правила, work-protocol, progressive disclosure)</td></tr>
</tbody>
</table>

## Правила (35)

| Файл | Описание |
|------|----------|
| `1c-coding-standards.md` | Стандарты кода BSL: именование, форматирование, запросы, коллекции, директива РАЗРЕШЕННЫЕ |
| `anti_patterns.md` | Критические антипаттерны: запрос в цикле, точка, O(n^2) |
| `query-optimization-tips.md` | Оптимизация запросов: ВЫРАЗИТЬ, ВТ, индексы, СКД |
| `async-methods-1c.md` | Асинхронные методы (Асинх/Ждать/Обещание) |
| `1c-extension-patterns.md` | Паттерны расширений CFE: перехватчики, маркеры |
| `form_module_rules.md` | Клиент-серверное разделение в модулях форм |
| `1c-form-reserved-names.md` | Зарезервированные имена свойств элементов в модулях форм |
| `forms_events.md` | Привязка обработчиков событий в Form.xml |
| `forms_generation.md` | Генерация и модификация форм 1С через 1c-forms-mcp |
| `edt-form-xml-requirements.md` | Требования EDT к XML-формам (Form.form): extInfo, дефолты полей |
| `code-review-checklist.md` | Чеклист ревью BSL-кода (Critical/High/Medium/Low) |
| `code-exploration-guide.md` | Методология исследования кодовой базы 1С |
| `testing-patterns.md` | Паттерны тестирования: YaXUnit, Vanessa Automation |
| `1c-mdo-integrity.md` | Целостность MDO-файлов: UUID, ссылки, ограничения типов String/Number |
| `external-data-source-mdo.md` | Внешние источники данных (ВИД) в формате EDT |
| `v8unpack-source-structure.md` | Структура исходников v8unpack |
| `refactoring.md` | Правила рефакторинга 1С: техники, критерии, примеры BSL |
| `routine_assignment_ext_processor.md` | Фоновые задания из внешней обработки через БСП |
| `bsp-profile-rights-api.md` | Программная работа с профилями групп доступа БСП: ссылки на ИдентификаторыОбъектовМетаданных, шаблон создания/обновления |
| `mcp-tool-priority.md` | Маршрутизатор MCP-серверов под задачу: какой сервер брать, обязательные проверки, фасады AI-EDT, троттлинг |
| `model-selection.md` | Стратегия выбора моделей: Opus/Sonnet/Haiku по типу задачи |
| `sdd-workflow.md` | Specification-Driven Development: 9-фазный workflow разработки |
| `skill-design.md` | Проектирование скилов: модельный и пользовательский вызов, лестница информации, критерии завершения шага |
| `agent-working-memory.md` | Рабочая память агента: файлы плана, передача сессии, правила проекта как журнал инцидентов |
| `git-safety-rules.md` | Безопасная работа с git: запрет AI-атрибуции и секретов, деструктивные команды, force push, amend, политика EOL для 1С-репозиториев (`.gitattributes`) |
| `text-formatting.md` | Запрещенные символы в генерируемом тексте (длинное тире, е, елочки): EDT режет их при сохранении |
| `file-edit-efficiency.md` | Выбор инструмента чтения и правки файлов по стоимости токенов; кэширование крупных карт проекта |
| `1c-role-rights.md` | Права ролей 1С: настройка прав на объекты, RLS, наследование |
| `1c-report-direct-query.md` | Прямой запрос в отчетах (СКД) без схемы компоновки |
| `edt-zip-export-pitfalls.md` | Ограничения инкрементального экспорта конфигурации из EDT в ИБ |
| `agent-verification-patterns.md` | Паттерны проверки результата работы агента (reconciliation loop) |
| `bsl-ssl.md` | Переиспользование БСП, разметка правок типовых модулей, устаревшие объекты |
| `edt-bsl-write-safety.md` | Безопасная запись BSL-модулей через EDT MCP |
| `integrations.md` | Python-first подход к HTTP-интеграциям 1С |
| `1c-skd-two-pass-preprocessing.md` | Двухпроходный СКД: предобработка деталей до свертки |

## Команды (5)

| Файл | Описание |
|------|----------|
| `check-uuid.md` | Проверка уникальности UUID в MDO-файлах |
| `check_uuid_duplicates.py` | Python-скрипт проверки дубликатов UUID |
| `docx-to-md.md` | Конвертация DOCX в Markdown |
| `move-project.md` | Перенос проекта Claude Code с сохранением памяти, сессий и планов |
| `browser-debug.md` | Запуск браузера с CDP-отладкой для веб-приложений |

## Документация (docs/)

Справочные спецификации и руководства для скилов:

| Файл | Описание |
|------|----------|
| `1c-specs-index.md` | Индекс всех спецификаций |
| `1c-config-objects-spec.md` | Спецификация объектов метаданных |
| `1c-configuration-spec.md` | Спецификация конфигурации |
| `1c-extension-spec.md` | Спецификация расширений |
| `1c-form-spec.md` | Спецификация управляемых форм |
| `1c-epf-spec.md` | Спецификация внешних обработок |
| `1c-erf-spec.md` | Спецификация внешних отчетов |
| `1c-role-spec.md` | Спецификация ролей |
| `1c-subsystem-spec.md` | Спецификация подсистем |
| `1c-support-state-spec.md` | Спецификация состояния поддержки (ParentConfigurations.bin) |
| `1c-xdto-spec.md` | Спецификация пакетов XDTO |
| `1c-spreadsheet-spec.md` | Спецификация табличных документов |
| `1c-dcs-spec.md` | Спецификация СКД |
| `1c-help-spec.md` | Спецификация справки |
| `build-spec.md` | Спецификация пакетного режима 1С |
| `meta-dsl-spec.md` | DSL метаданных |
| `form-dsl-spec.md` | DSL форм |
| `mxl-dsl-spec.md` | DSL макетов |
| `role-dsl-spec.md` | DSL ролей |
| `skd-dsl-spec.md` | DSL СКД |
| `python-porting-guide.md` | Руководство по портированию скриптов PowerShell на Python |
| `v8-project-guide.md` | Руководство по .v8-project.json |
| `web-guide.md` | Руководство по веб-публикации 1С |
| `web-spec.md` | Спецификация веб-публикации |
| `web-test-guide.md` | Руководство по веб-тестированию |
| `web-test-recording-guide.md` | Руководство по записи видео веб-тестов |
| `*-guide.md` | Руководства по отдельным подсистемам (cf, cfe, db, epf, form, meta, mxl, role, skd, subsystem) |

## Регресс-тесты скилов

Скрипты скилов покрыты снапшот-тестами: скил получает вход, генерирует файлы, результат сравнивается
с эталоном. Быстро, файлово, без платформы 1С.

```bash
node tests/skills/runner.mjs                       # весь набор
node tests/skills/runner.mjs cases/1c-meta-compile # один скил
node tests/skills/runner.mjs --update-snapshots    # перегенерировать эталоны
node tests/skills/runner.mjs --runtime python      # прогнать python-версии скриптов
```

Прогон идет в CI на каждый push и pull request - [.github/workflows/tests.yml](.github/workflows/tests.yml),
раннер windows-latest, потому что скриптам нужен PowerShell. Интеграционные прогоны идут там же;
те из них, которым нужна установленная платформа 1С, раннер пропускает сам.

Рядом со снапшотами работают гарды инвариантов - они проверяют не вывод скилов, а согласованность
самих исходников: карты типов метаданных против спецификации, диапазон версий формата, сохранение
uuid при правке объекта, разброс продублированных по скилам функций.

```bash
node tests/skills/check-all.mjs                    # все гарды разом
node tests/skills/check-type-maps.mjs --list       # что с чем сверяется
```

Требуется Node.js 18+. Текущее состояние: **528 зеленых из 802**, 46 пропущено по условиям среды.
Остальные 228 - реестр незакрытой функциональности `tests/skills/known-gaps.json`: скрипт не знает
типа объекта, операции или параметра, которые поддерживает исходный набор. Раннер использует реестр
как гейт для обоих наборов сразу - падение ИЗ реестра ожидаемо, падение ВНЕ его означает регресс
и роняет прогон. Подробности
и порядок работы с реестром - `tests/skills/README.md`.

## Хуки (экспериментально, по умолчанию выключены)

В каталоге `hooks/` два хука Claude Code, дополняющие проверки, встроенные в сами скилы:

- **support-guard** - блокирует прямую правку через `Edit`/`Write` объекта типовой конфигурации,
  стоящего на поддержке поставщика, и в отказе говорит, что делать вместо этого.
- **skill-suggester** - при ручной работе с исходниками 1С напоминает про профильный скил: при
  чтении ведет на `*-info`, при правке - на мутатор. Не блокирует, срабатывает не чаще раза за
  сессию на группу.

Требуется Node.js 18+. Автоматически не подключаются: порядок ручного включения и настройки - в
`hooks/README.md`.

## История версий

Что изменилось по версиям - [CHANGELOG.md](CHANGELOG.md).

## Лицензия

MIT
