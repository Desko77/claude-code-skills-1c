# Claude Code Skills for 1C:Enterprise

Набор скилов, правил и команд для [Claude Code](https://docs.anthropic.com/en/docs/claude-code), ориентированных на разработку 1С:Предприятие.

**94 скила** для работы с конфигурациями, расширениями, обработками, формами, макетами, запросами, ролями, подсистемами, базами данных, веб-публикацией и веб-тестированием 1С, а также разработкой под 1С 7.7, правилами обмена «Конвертация данных» и интеграцией с Mobile SMARTS (Клеверенс).

Отдельный класс - справочники API прикладных конфигураций (см. раздел «Справочные и утилитарные»). Первый такой скил - `zup-hr-api-reference` для 1С:ЗУП 3.1.

**25 правил** — стандарты кода BSL, антипаттерны, оптимизация запросов, паттерны расширений, генерация форм, требования EDT, БСП API, права ролей, прямой запрос в отчётах, грабли экспорта EDT, верификация работы агента, тестирование, ревью, выбор моделей, SDD-workflow.

## Установка

### Скилы

Скопировать папку `skills/` в `~/.claude/skills/`:

```bash
# Весь набор
cp -r skills/* ~/.claude/skills/

# Или конкретные скилы
cp -r skills/1c-meta-compile ~/.claude/skills/
```

### Правила

Скопировать файлы из `rules/` в `~/.claude/rules/`:

```bash
cp rules/*.md ~/.claude/rules/
```

### Команды

Скопировать файлы из `commands/` в `~/.claude/commands/`:

```bash
cp commands/* ~/.claude/commands/
```

## Зависимости

| Компонент | Обязательно | Для чего |
|-----------|-------------|----------|
| PowerShell 5.1+ (Windows) | Да | Скрипты скилов (.ps1) |
| Python 3.8+ | Нет | Альтернативные скрипты (.py), `v8unpack-cf`, `check-uuid`, `img-grid-analysis` |
| [v8unpack](https://pypi.org/project/v8unpack/) | Нет | Распаковка/сборка CF/CFE/EPF без платформы |
| 1C:Enterprise 8.3 | Нет | Скилы группы `db-*`, сборка EPF/ERF |
| Node.js + npm-пакет `docx` | Нет | `md-to-docx` (конвертация Markdown → DOCX) |
| `ffmpeg`, `ffprobe` | Нет | `transcribe`, `transcribe-audio-local` (извлечение аудио, разбивка длинных файлов) |
| NVIDIA GPU + CUDA 12 + cuDNN 9 | Нет | `transcribe`, `transcribe-audio-local` (локальный движок faster-whisper + sherpa-onnx). CPU тоже работает, но в 10+ раз медленнее |
| `gcomp` | Нет | `1c77-dev` (разбор/сборка .ert и 1Cv7.MD для 1С 7.7) |
| Node.js + `@mermaid-js/mermaid-cli` (mmdc) | Нет | `mermaid-render` (рендер диаграмм в PNG/SVG/PDF) |
| Обработка `MCP_Toolkit.epf` ([ROCTUP](https://github.com/ROCTUP/1c-mcp-toolkit)) | Нет | `1c-mcp-toolkit` (HTTP API к живой запущенной базе 1С) |
| MCP-серверы (EDT, BSP, 1С:Напарник) | Нет | Анализ кода, валидация запросов, документация ИТС/платформы/конфигураций |

Скилы спроектированы по слоям — базовые (генерация XML) работают без платформы, продвинутые требуют 1С или MCP.

## Совместимые сторонние плагины

Полезные плагины Claude Code, дополняющие этот набор:

| Плагин | Установка | Что даёт |
|--------|-----------|----------|
| [`bsl-language-server`](https://github.com/1c-syntax/claude-code-bsl-lsp) | `/plugin marketplace add 1c-syntax/claude-code-bsl-lsp` + `/plugin install bsl-language-server@bsl-language-server` | Полноценная интеграция BSL Language Server в Claude Code как LSP — диагностики, go to definition, find references, hover, форматирование, code actions для `.bsl` и `.os` |
| Anthropic plugins (`/plugin marketplace add anthropics/claude-plugins-official`) | `/plugin install <name>@claude-plugins-official` | `code-review`, `pr-review-toolkit` — ревью PR агентами; `mcp-server-dev` — разработка MCP-серверов; `claude-md-management` — поддержание CLAUDE.md; `hookify` — создание hooks; `security-guidance` — security-ревью |

## Скилы (94)

### Маршрутизатор

| Скил | Описание |
|------|----------|
| `1c-config-router` | Определяет нужный workflow или скил для задачи |

### Конфигурация (cf-*)

| Скил | Описание |
|------|----------|
| `1c-cf-init` | Создать пустую конфигурацию (scaffold XML) |
| `1c-cf-info` | Анализ структуры конфигурации |
| `1c-cf-edit` | Изменить свойства конфигурации |
| `1c-cf-validate` | Валидация конфигурации |
| `1c-cf-add-object` | Workflow: добавить объект в конфигурацию |
| `1c-cf-new-project` | Workflow: создать конфигурацию с нуля |

### Объекты метаданных (meta-*)

| Скил | Описание |
|------|----------|
| `1c-meta-compile` | Создать объект метаданных из JSON DSL (23 типа) |
| `1c-meta-edit` | Изменить реквизиты, ТЧ, свойства объекта |
| `1c-meta-info` | Анализ структуры объекта |
| `1c-meta-remove` | Удалить объект из конфигурации |
| `1c-meta-validate` | Валидация объекта метаданных |

### Формы (form-*)

| Скил | Описание |
|------|----------|
| `1c-form-compile` | Создать форму из JSON DSL |
| `1c-form-edit` | Добавить элементы, реквизиты, команды в форму |
| `1c-form-add` | Добавить форму к объекту конфигурации |
| `1c-form-info` | Анализ структуры формы |
| `1c-form-patterns` | Паттерны проектирования форм |
| `1c-form-remove` | Удалить форму |
| `1c-form-validate` | Валидация формы |

### Расширения (cfe-*)

| Скил | Описание |
|------|----------|
| `1c-cfe-init` | Создать расширение конфигурации |
| `1c-cfe-borrow` | Заимствовать объект из конфигурации |
| `1c-cfe-patch-method` | Перехватить метод (Before/After/ModificationAndControl) |
| `1c-cfe-diff` | Анализ расширения |
| `1c-cfe-validate` | Валидация расширения |
| `1c-cfe-full-cycle` | Workflow: полный цикл создания расширения |

### Обработки и отчёты (epf-*, erf-*)

| Скил | Описание |
|------|----------|
| `1c-epf-scaffold` | Создать пустую обработку |
| `1c-epf-add-form` | Добавить форму к обработке |
| `1c-epf-build` | Собрать EPF из XML-исходников |
| `1c-epf-dump` | Разобрать EPF в XML-исходники |
| `1c-epf-validate` | Валидация обработки |
| `1c-epf-full-cycle` | Workflow: полный цикл создания обработки |
| `1c-erf-init` | Создать пустой отчёт |
| `1c-erf-build` | Собрать ERF |
| `1c-erf-dump` | Разобрать ERF |
| `1c-erf-validate` | Валидация отчёта |

### Подсистемы и интерфейс

| Скил | Описание |
|------|----------|
| `1c-subsystem-compile` | Создать подсистему |
| `1c-subsystem-edit` | Изменить состав подсистемы |
| `1c-subsystem-info` | Анализ подсистемы |
| `1c-subsystem-validate` | Валидация подсистемы |
| `1c-interface-edit` | Настроить командный интерфейс |
| `1c-interface-validate` | Валидация интерфейса |

### Макеты (mxl-*, template-*)

| Скил | Описание |
|------|----------|
| `1c-mxl-compile` | Создать макет из JSON DSL |
| `1c-mxl-decompile` | Разобрать макет в JSON |
| `1c-mxl-info` | Анализ макета |
| `1c-mxl-validate` | Валидация макета |
| `1c-template-add` | Добавить макет к объекту |
| `1c-template-remove` | Удалить макет |

### Роли (role-*)

| Скил | Описание |
|------|----------|
| `1c-role-compile` | Создать роль из описания прав |
| `1c-role-info` | Анализ роли |
| `1c-role-validate` | Валидация роли |

### СКД (skd-*)

| Скил | Описание |
|------|----------|
| `1c-skd-compile` | Создать схему компоновки данных |
| `1c-skd-edit` | Изменить существующую СКД |
| `1c-skd-info` | Анализ СКД |
| `1c-skd-validate` | Валидация СКД |

### Базы данных (db-*)

| Скил | Описание |
|------|----------|
| `1c-db-list` | Управление реестром баз |
| `1c-db-create` | Создать информационную базу |
| `1c-db-dump-cf` | Выгрузить конфигурацию в CF |
| `1c-db-dump-xml` | Выгрузить конфигурацию в XML |
| `1c-db-load-cf` | Загрузить конфигурацию из CF |
| `1c-db-load-xml` | Загрузить конфигурацию из XML |
| `1c-db-load-git` | Загрузить изменения из Git |
| `1c-db-update` | Обновить конфигурацию БД |
| `1c-db-run` | Запустить 1С:Предприятие |

### Веб-публикация и тестирование (web-*)

| Скил | Описание |
|------|----------|
| `1c-web-publish` | Публикация ИБ на веб-сервере (Apache/IIS) |
| `1c-web-unpublish` | Отмена публикации ИБ |
| `1c-web-info` | Информация о веб-публикациях |
| `1c-web-stop` | Остановка веб-сервера |
| `1c-web-test` | Тестирование 1С через веб-клиент (автоматизация браузера) |

### БСП

| Скил | Описание |
|------|----------|
| `1c-bsp-registration` | Регистрация обработки в БСП |
| `1c-bsp-command` | Добавить команду БСП |
| `1c-ssl-patterns` | Паттерны подсистем БСП |

### Разработка 1С 7.7

| Скил | Описание |
|------|----------|
| `1c77-dev` | Разработка под 1С 7.7: .1s/.ert/.frm, 1Cv7.MD, gcomp, кодировка CP1251 |

### Конвертация данных и интеграции

| Скил | Описание |
|------|----------|
| `kd2-rules` | Правила обмена «Конвертация данных 2.0» через MCP-toolkit |
| `kd31-rules` | Правила обмена «Конвертация данных 3.1» через MCP-toolkit |
| `cleverence-mslx` | Mobile SMARTS (Клеверенс): .mslx-алгоритмы ТСД, online-вызов 1С |

### Справочные и утилитарные

**Справочники API прикладных конфигураций 1С** - отдельный класс скилов, рассчитанный на объёмные тематические справочники (методы, поля, паттерны конфигурации), которые дорого держать в глобальном контексте. Устройство: полный текст справочника лежит в `references/` внутри папки скила, а SKILL.md содержит только короткое описание-триггер (~150 токенов). Модель подтягивает справочник через Read **только когда видит, что задача касается этой конфигурации** - остальное время он не потребляет контекст. Паттерн легко расширяется: `erp-api-reference`, `ut-api-reference`, `buh-api-reference` и т.п. делаются по той же схеме - собрать API-справочник в `references/имя-справочника.md` и написать SKILL.md с точным описанием-триггером.

Для фиксированной привязки к конкретному проекту (всегда грузить, без опоры на триггер) в CLAUDE.md проекта можно добавить `@~/.claude/skills/<skill>/references/<file>.md`.

| Скил | Описание |
|------|----------|
| `1c-edt-tools` | Справочник инструментов EDT MCP |
| `1c-naparnik` | Справочник инструментов 1С:Напарник (анализ кода, ИТС, документация) |
| `1c-mcp-toolkit` | Прямой HTTP API к живой запущенной базе 1С (запросы, BSL-код, метаданные, журнал) |
| `1c-platform-docs` | Поиск по документации API платформы |
| `1c-query-optimization` | Продвинутая оптимизация запросов |
| `zup-hr-api-reference` | Справочник API 1С:ЗУП 3.1 (кадровый учет, физлица, стажи, договоры ГПХ, представления СКД) |
| `1c-help-manage` | Встроенная справка объектов 1С |
| `composing-1c-queries` | Руководство по языку запросов 1С |
| `v8unpack-cf` | Распаковка/сборка CF/CFE/EPF |
| `img-grid-analysis` | Анализ изображений для макетов |
| `md-to-docx` | Конвертация Markdown в DOCX |
| `transcribe` | Транскрибация аудио (локально, faster-whisper + sherpa-onnx GPU) и видео (Gemini API). Установка через `scripts/setup.py` |
| `transcribe-audio-local` | Только аудио, только локально, self-contained — для передачи на другую машину без облака |
| `mermaid-diagrams` | Генерация диаграмм Mermaid |
| `mermaid-render` | Рендер Mermaid в PNG/SVG/PDF через локальный mmdc |
| `powershell-windows` | PowerShell на Windows |
| `skill-creator` | Создание, тестирование и оптимизация скилов (evals, grading, description loop) |
| `prompt-enhancer` | Улучшение и структурирование коротких промптов и постановок задач в подробные ТЗ |
| `dehumanize-ai-text` | Переписывание AI-текста (отчеты, README, доки, письма) в живой человеческий стиль: ломает ровный ритм, убирает штампы и буферные вступления |

## Правила (25)

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
| `1c-mdo-integrity.md` | Целостность MDO-файлов: UUID, ссылки, ловушки типов String/Number |
| `external-data-source-mdo.md` | Внешние источники данных (ВИД) в формате EDT |
| `v8unpack-source-structure.md` | Структура исходников v8unpack |
| `refactoring.md` | Правила рефакторинга 1С: техники, критерии, примеры BSL |
| `routine_assignment_ext_processor.md` | Фоновые задания из внешней обработки через БСП |
| `bsp-profile-rights-api.md` | Программная работа с профилями групп доступа БСП: ссылки на ИдентификаторыОбъектовМетаданных, шаблон создания/обновления |
| `model-selection.md` | Стратегия выбора моделей: Opus/Sonnet/Haiku по типу задачи |
| `sdd-workflow.md` | Specification-Driven Development: 9-фазный workflow разработки |
| `1c-role-rights.md` | Права ролей 1С: настройка прав на объекты, RLS, наследование |
| `1c-report-direct-query.md` | Прямой запрос в отчётах (СКД) без схемы компоновки |
| `edt-zip-export-pitfalls.md` | Грабли инкрементального экспорта конфигурации из EDT в ИБ |
| `agent-verification-patterns.md` | Паттерны проверки результата работы агента (reconciliation loop) |

## Команды (4)

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
| `1c-erf-spec.md` | Спецификация внешних отчётов |
| `1c-role-spec.md` | Спецификация ролей |
| `1c-subsystem-spec.md` | Спецификация подсистем |
| `1c-spreadsheet-spec.md` | Спецификация табличных документов |
| `1c-dcs-spec.md` | Спецификация СКД |
| `1c-help-spec.md` | Спецификация справки |
| `build-spec.md` | Спецификация пакетного режима 1С |
| `meta-dsl-spec.md` | DSL метаданных |
| `form-dsl-spec.md` | DSL форм |
| `mxl-dsl-spec.md` | DSL макетов |
| `role-dsl-spec.md` | DSL ролей |
| `skd-dsl-spec.md` | DSL СКД |
| `python-porting-guide.md` | Руководство по портированию скриптов PowerShell → Python |
| `v8-project-guide.md` | Руководство по .v8-project.json |
| `web-guide.md` | Руководство по веб-публикации 1С |
| `web-spec.md` | Спецификация веб-публикации |
| `web-test-guide.md` | Руководство по веб-тестированию |
| `web-test-recording-guide.md` | Руководство по записи видео веб-тестов |
| `*-guide.md` | Руководства по отдельным подсистемам (cf, cfe, db, epf, form, meta, mxl, role, skd, subsystem) |

## Лицензия

MIT
