# Хуки: защита конфигураций на поддержке + подсказка навыков + след проверок + ворота MCP-first

> ⚠️ **Экспериментально, по умолчанию выключено.** Эти хуки **не подключаются автоматически** даже при
> установке плагина - их нужно включить вручную (см. "Установка" ниже). Базовая защита поддержки уже работает
> без хуков - встроена в сами навыки-мутаторы; хуки лишь добавляют перехват правок **в обход навыков** и
> подсказки. Фича новая, обкатывается; отзывы приветствуются.

Шесть хуков Claude Code для работы с типовыми конфигурациями 1С:

- **Защита от правки "на замке"** (`support-guard.mjs`). Если модель пытается напрямую (инструментами
  `Edit`/`Write`) изменить объект типовой конфигурации, который стоит на поддержке поставщика,
  редактирование **блокируется** - иначе оно молча сломает будущие обновления вендора. В отказе сразу дается,
  что делать дальше под конкретный случай (доработать в расширении или явно разрешить редактирование).
- **Подсказка навыков** (`skill-suggester.mjs`). Когда модель работает с исходниками 1С "вручную" (читает
  сырой XML или правит его напрямую), хук ненавязчиво напоминает про профильный навык - и по делу: при
  **чтении** ведет на `*-info` (понять структуру), при **правке** - на мутатор
  (`1c-meta-edit`/`1c-form-edit`/`1c-skd-edit`/...). Не блокирует, подсказывает не чаще одного раза за сессию
  на группу и действие.
- **След проверок** (`evidence-writer.mjs`, `session-context.mjs`, `release-writer.mjs`) - см. раздел ниже.
- **Ворота MCP-first** (`edt-gate.mjs`) - см. раздел "Ворота MCP-first". Пока проект загружен в живой AI-EDT, `Read`, `Grep`, `Glob`, `Bash` и `PowerShell` по исходникам этого проекта отклоняются с именем инструмента-замены.

Это дополнительный слой поверх проверок, которые уже встроены в сами навыки: навыки-мутаторы и так не дадут
испортить объект на поддержке. Хуки добавляют защиту для случаев, когда правят файлы **в обход навыков**.

> Хуки - возможность только Claude Code. На других платформах их нет; там работают встроенные в навыки проверки.

## Требования

**Node.js 18+** (тот же, что нужен для веб-тестирования). Команда `node` должна быть доступна в PATH.

## Установка (ручная - фича экспериментальная)

Хуки сейчас **не включаются автоматически** ни одним способом установки (плагин их не объявляет в манифесте).
Чтобы включить:

1. Скопируйте каталог `hooks/` в проект, например в `<проект>/.claude/hooks/`, и используйте в путях
   `${CLAUDE_PROJECT_DIR}/.claude/hooks/...`. Готовый фрагмент настроек - в `hooks.json` этого каталога.
2. Добавьте в `<проект>/.claude/settings.json` (пути ниже - для варианта с копированием; полный
   фрагмент - в `hooks.json` этого каталога). Строку матчера `evidence-writer` копируйте из
   `hooks/hooks.json` как есть - источник выражения задан константой `MATCHER` в
   `hooks/evidence-writer.mjs`, гард `tests/hooks/matcher-guard.test.mjs` сверяет копии,
   поэтому здесь выражение не повторяется:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "^(Read|Grep|Glob|Bash|PowerShell)$",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/edt-gate.mjs\"" }] },
      { "matcher": "Edit|Write|MultiEdit",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/support-guard.mjs\"" }] }
    ],
    "PostToolUse": [
      { "matcher": "Read|Edit|Write|MultiEdit",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/skill-suggester.mjs\"" }] },
      { "matcher": "<строка matcher из hooks/hooks.json - блоки evidence-writer.mjs>",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/evidence-writer.mjs\"" }] }
    ],
    "PostToolUseFailure": [
      { "matcher": "<строка matcher из hooks/hooks.json - блоки evidence-writer.mjs>",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/evidence-writer.mjs\"" }] },
      { "matcher": "<та же строка matcher, что у evidence-writer.mjs>",
        "hooks": [{ "type": "command",
          "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/edt-gate.mjs\"" }] }
    ],
    "SessionStart": [
      { "hooks": [{ "type": "command",
        "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/session-context.mjs\"" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command",
        "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/release-writer.mjs\"" }] }
    ]
  }
}
```

## Настройка (`.v8-project.json`)

Поведение настраивается в файле проекта `.v8-project.json` - глобально и/или по конкретной базе
(`databases[]....`, переопределяет глобальное):

| Поле | Значения | По умолчанию | Что делает |
|------|----------|--------------|------------|
| `editingAllowedCheck` | `deny` / `warn` / `off` | `deny` | Реакция защиты: блокировать правку объекта на замке / только предупреждать / выключить проверку. |
| `skillSuggester` | `on` / `off` | `on` | Включает/выключает подсказки навыков. |

Источник истины по состоянию поддержки - сама выгрузка конфигурации; `.v8-project.json` лишь настраивает
реакцию.

## След проверок

Три хука пишут машинный журнал прогона проверок (формат -
`skills/1c-code-review/references/evidence-format.md`; валидатор - `tools/evidence.py`).
События `applied`, `failed` и `release` записываются хуком по факту вызова инструмента,
набрать их из CLI невозможно.

- **evidence-writer** (`PostToolUse` / `PostToolUseFailure`): после вызова MCP-инструмента
  проверки (`validate_query`, `code_review`, `diagnostics`, `validate_for_export`,
  `get_project_errors`, `security_audit`, `ask_1c_ai`, `check_1c_code`, `syntaxcheck`,
  `detect_query_anti_patterns`, `insights` с операцией `detect_query_anti_patterns`;
  ключ сервера любой) пишет событие `applied` с итогом вызова, при отказе инструмента -
  `failed`. Для `Bash`/`PowerShell` пишет `applied` только когда команда запускает скрипт
  набора (`bsl-validate`, `query-validate`, `meta-validate`, `role-validate`,
  `form-validate` из `skills/*/scripts/`) и скрипт напечатал строку результата
  `EVIDENCE {...}` - прочие команды событием не становятся. Запуском считается путь
  скрипта исполняемым токеном: довод `python`/`python3 [-X utf8]`, довод `-File` у
  `pwsh`/`powershell` либо первый токен команды (в том числе вызов `& "<путь>"`);
  путь в комментарии или аргументе прочей команды запуском не считается. Известный
  предел: хук подтверждает запуск по форме команды, а не по факту процесса - подмена
  через `python -c` с кодом, печатающим строку `EVIDENCE`, или одноименный файл
  злоумышленника формой проходят. Не разбирается итог - пишется `status: "unknown"`
  с фрагментом ответа; такое событие валидатор не принимает. Итог не выдумывается.
- **session-context** (`SessionStart`): сообщает модели идентификатор сессии следа
  (строка `сессия: <id>` и путь каталога событий - его передают в CLI доводом
  `--session`) и вычищает каталоги сессий старше 7 дней. Работает одинаково при старте,
  `resume`, `clear` и `compact`.
- **release-writer** (`UserPromptSubmit`): команда
  `/quality release gate|check <область> <причина> [--for 30m|2h|1d]` (срок по умолчанию
  4 часа) записывает снятие проверки или гейта целиком с привязкой к текущему `diffHash`
  и сроком действия; подтверждение возвращается в контекст. Любой другой промпт хук
  игнорирует.

События пишутся в `.claude/.state/quality/<session_id>/events/` внутри репозитория
проекта (каталог исключается из git). Внутренняя ошибка любого хука - выход 0 со строкой
в stderr, работа сессии не блокируется.

Число Critical/Major для `code_review` считается по кодам диагностик из гейтового
конфига `skills/1c-code-review/assets/bsl-ls-gate.json`: хук ищет каталог скила через
`CLAUDE_PLUGIN_ROOT` либо рядом с собой (`../skills/`). При ручной установке хуков без
каталога скила числа не считаются, итог деградирует до `pass`/`unknown` - событие
записывается, но числа находок будут нулевыми.

## Ворота MCP-first

`hooks/edt-gate.mjs`, событие `PreToolUse`. Матчер - `Read`, `Grep`, `Glob`, `Bash`,
`PowerShell`; строка задана в `hooks/hooks.json` и стоит первой в списке `PreToolUse`.

Отказ (`permissionDecision: deny`), когда цель лежит в EDT-проекте и этот проект загружен
в живой AI-EDT. EDT-проект: вверх от файла или каталога есть `.project`, в тексте которого
есть `com._1c.g5.v8.dt`; имя проекта - первое `<name>`. Живой AI-EDT: среди включенных
серверов есть HTTP-сервер, ответ `GET <url без суффикса /mcp>/health` имеет `phase`
`ready`, поле `instance` начинается с `AI-EDT @`, и имя проекта входит в `projects`.
Таймаут запроса - 1 секунда. Ответ кэшируется 60 секунд в
`.claude/.state/quality/edt-health.json`, ключ кэша - URL `/health`.

Серверы читаются из трех мест: `.mcp.json` (от `cwd` вверх до корня диска), `mcpServers`
в `~/.claude.json`, `projects[<cwd>].mcpServers` в `~/.claude.json`. Сервер из `.mcp.json`
включен, если задан `enableAllProjectMcpServers` или его ключ есть в
`enabledMcpjsonServers`, и этого ключа нет в `disabledMcpjsonServers`. Флаги берутся из
`.claude/settings.local.json`, `.claude/settings.json` и записи `projects[<cwd>]`.
Учитывается только `type` `http`. Ключи плагинов (`plugin_...`) и инструменты
`mcp__plugin_*` не рассматриваются.

Цель: у `Read` это `file_path` с расширением `.bsl`, `.os`, `.mdo`, `.form`, `.dcs`,
`.mxlx`, `.cmi`, `.rights` или `.xdto`. У `Grep` и `Glob` это `path`, а если `path` нет -
`cwd`; каталог внутри EDT-проекта достаточен. У `Bash` и `PowerShell` отказ только когда
в тексте команды есть утилита `cat`, `head`, `tail`, `sed`, `grep`, `rg`, `find`, `awk`,
`python`, `Get-Content`, `Select-String` или `type` и рядом путь с таким расширением или
сегмент каталога `src`.

В причине отказа: путь, ключ сервера, инструмент-замена, раздел "Сначала индекс" правила
`rules/mcp-tool-priority.md` и команда `/quality release gate`. Замена по виду цели:
`.mdo` - `get_metadata_details`; `.bsl` и `.os` - `get_module_structure` и
`read_method_source`; `.form` - `get_form_structure`; `.dcs` - `dcs_workshop`; `Grep`,
`Glob` и остальные расширения - `code_search operation=text_search`. Для `Bash` и
`PowerShell` в причине есть фраза "Перебор исходников при живой EDT".

Вызов пропускается (выход 0, пустой stdout): цель не в EDT-проекте; имя проекта не входит
в `projects` ни одного живого AI-EDT; открыто окно-исключение; в следе сессии есть
действующее `release` с `scope` `gate` (тот же `diffHash`, `expiresAt` еще не наступил);
внутренняя ошибка хука. Текст внутренней ошибки пишется в stderr.

Окно-исключение открывает тот же `edt-gate.mjs` на `PostToolUseFailure`. Матчер совпадает
с матчером `evidence-writer` (строка в `hooks/hooks.json`). Ключ сервера берется из имени
инструмента `mcp__<ключ>__<имя>`, затем хук запрашивает `/health`. Нет ответа, статус 401
или 403, либо `phase` не `ready` - в след пишется `probe` со `status` `down` и `source`
`ai-edt`, и создается `.claude/.state/quality/<session>/edt-window.json` с полями `until`
(15 минут от записи) и `server`. Ошибка операции при `phase` `ready` пишет `probe` со
`status` `ok` и файл окна не создает. Каждый подтвержденный отказ `/health` заново
записывает `until`. Автоматического ослабления после серии отказов нет.

Снять ворота, не дожидаясь `until` и при живом сервере, может только команда человека
`/quality release gate <причина> [--for 30m|2h|1d]` (хук `release-writer`).

Известные пределы. `PreToolUse` не видит файлы, подключенные через `@` в промпте
пользователя. Для `Bash` и `PowerShell` хук смотрит текст команды, а не запущенный
процесс: обход через переменные shell, `cd` и дочерние процессы возможен.

## Что делать при отказе защиты

Текст отказа сам подсказывает варианты под конкретную ситуацию. Кратко:

- **Безопаснее всего** - вести доработку в расширении (навыки `1c-cfe-borrow` / `1c-cfe-patch-method`):
  состояние поддержки менять не нужно, обновления вендора сохраняются.
- **Либо** осознанно разрешить редактирование через навык `1c-support-state` (включить редактирование объекта,
  снять его с поддержки или включить возможность изменения всей конфигурации). Готовую команду под ваш
  случай печатает сам отказ.

## Проверка

```bash
node tests/hooks/run.mjs
```

Прогоняет тесты хуков следа проверок на payload-фикстурах и во временных git-репозиториях
(создаются в системном временном каталоге, в git не попадают; рабочие выгрузки не
затрагиваются). Сквозной тест вызывает Python-инструменты `tools/` - нужны `python` и
`git` в PATH. Гард `tests/skills/check-hooks.mjs` подключает этот раннер к общему прогону
`node tests/skills/check-all.mjs`.
