# Формат следа проверок

След - машинный журнал прогона проверок: что обязательно (событие `scope`), что
выполнено и с каким итогом (`applied`), что пропущено и почему (`skipped`), что не
измерялось (`not_verified`), жив ли источник (`probe`), что снято человеком (`release`).
Валидатор - `tools/evidence.py` (`check`, `render`); события `skipped`, `not_verified`
и `probe` пишет он же (подкоманда `add`). Записи `applied`, `failed` и `release` пишет
только хук: набрать их через CLI невозможно.

## Каталог событий

`.claude/.state/quality/<session_id>/events/` - внутри репозитория, для которого идет
прогон. Идентификатор сессии дает хук `SessionStart`; командам и инструментам он
передается доводом `--session`. Допустимые символы идентификатора: буквы, цифры, точка,
подчеркивание, дефис; разделители пути недопустимы.

Одно событие - один файл `<время>-<источник>-<id>.json`:

- `<время>` - локальное время записи, `YYYY-MM-DDTHHMMSS-<миллисекунды>`;
- `<источник>` - producer: `profile`, `cli`, `hook`;
- `<id>` - 6 шестнадцатеричных цифр; занятое имя перегенерируется.

Тело - UTF-8 JSON с сортировкой ключей, отступом 2 и завершающим переводом строки.
Запись идет во временный файл с переименованием; созданный файл не изменяется. Чтение
возвращает события в порядке имен (время в имени самолексикографично). Поврежденный JSON
не поднимает исключение: чтение возвращает для него событие `type=corrupt` с именем
файла и текстом ошибки.

Каталог `.claude/.state/` исключается из git: строка `.claude/.state/` в `.gitignore`
репозитория (в наборе добавлена) и `.gitignore` воркспейсов (добавляет установщик).
След, не исключенный из git, меняет каноническое множество и ломает привязку событий
к `diffHash`.

## Общие поля

| Поле | Значение |
|---|---|
| `type` | тип события (таблица ниже) |
| `at` | время записи, ISO 8601 с зоной и миллисекундами |
| `session` | идентификатор сессии |
| `diffHash` | хеш канонического множества на момент записи (`changeset.md`) |
| `producer` | кто записал: `profile`, `cli`, `hook` |

## Типы событий

| Тип | Кто пишет | Назначение |
|---|---|---|
| `scope` | профиль | обязательный состав прогона |
| `applied` | только хук | выполненная проверка с итогом |
| `failed` | только хук | отказ инструмента проверки |
| `skipped` | CLI, профиль | пропуск проверки с классом причины |
| `not_verified` | CLI | неизмеренное измерение с причиной |
| `probe` | CLI | проверка доступности источника |
| `release` | только хук `UserPromptSubmit` | снятие проверки или гейта человеком |
| `baseline` | хук `SessionStart` | базовая отметка сессии (спринт 6) |
| `armed` | хук `PostToolUse` | атрибуция правки инструменту (спринт 6) |

### scope

Пишет `tools/change_profile.py` (`profile-map.md`). Поля: `volume` (`class`, `bslLines`,
`bslFiles`), `files` (пути множества), `archetypes`, `env`, `driver`, `required` -
идентификаторы проверок с указанием среды, `analyzerConfig`, `vendorCopy` (обоснование
кальки типового либо `null`).

### applied

Пишет хук `PostToolUse` по факту вызова инструмента. Поля: `check` (идентификатор из
`required`), `detector`, `env`, `level` (`semantic`, `static`, `llm`, `project-config`),
`target`, `toolUseId`, `inputHash`, `responseHash`, `outcome` - `status` (`pass` |
`findings` | `error`) и числа находок `critical`, `major`, `minor`. Выполнено не значит
пройдено: `findings` с `critical` больше 0 блокирует вердикт до снятия.

### failed

Пишет хук `PostToolUseFailure`. Поля: `check`, `detector`, `toolUseId`, `error`.
На `failed` ссылается пропуск класса `tool_unavailable`.

### skipped

Поля: `check`, `class` и либо `ref`, либо `reason`:

- `tool_unavailable` - инструмент недоступен; `ref` - имя файла события `failed` или
  `probe` со статусом `down` в том же прогоне;
- `not_applicable` - проверка неприменима; `reason` - причина.

Пропуск без `check`, без класса, с неизвестным классом, без `ref` у `tool_unavailable`
или без `reason` у `not_applicable` - невалидный прогон.

### not_verified

Поля: `dimension` (измерение: производительность, поведение в режиме Предприятия и
прочее), `reason`. Вердикт не меняет, попадает в отчет `render`.

### probe

Поля: `source`, `status` (`ok` | `down`), `detail`. Источники: `ai-edt` (инструменты
AI-EDT), `naparnik` (1c-naparnik), `script` (скрипты набора). Вердикты `clean` и
`with_gaps` требуют `probe ok` по каждому источнику, на который опираются закрывающие
`applied`-события:

| Проверки | Источник |
|---|---|
| `code_review`, `validate_query`, `validate_for_export`, `get_project_errors`, `security_audit` | `ai-edt` |
| `ask_1c_ai` | `naparnik` |
| `syntaxcheck`, `bsl_validate`, `query_validate`, `meta_validate`, `role_validate` | `script` |
| `catalog_read:*`, `cross_review`, `adversarial_audit` | не требует probe |

### release

Пишет только хук `UserPromptSubmit`, когда промпт человека - команда снятия
(`/quality release <область> <причина>`); модель промпты не отправляет, источник всегда
человек. Поля: `scope` (`gate` | `check`), `check` (для `scope=check`), `reason`,
`source` (`user_prompt`), `expiresAt` (ISO 8601 с зоной). Действующее снятие: `diffHash`
равен текущему и `expiresAt` позже момента проверки. Снятие `gate` закрывает все
обязательные проверки прогона, `check` - одну.

### baseline и armed

Хуки спринта 6: `baseline` (`head`, `changeset`) - базовая отметка сессии; `armed`
(`file`, `tool`, `toolUseId`) - атрибуция правки. Валидатору достаточно знать тип.

## Прогон

Прогон - последнее событие `scope` с текущим `diffHash` и все события с тем же `diffHash`
после него (порядок - имена файлов). События с другим `diffHash` к прогону не относятся,
кроме `release`: снятие с чужим `diffHash`, найденное в каталоге сессии, и просроченное
снятие - невалидный прогон независимо от прогона.

## Вердикт check --strict

Проверка всегда строгая; флаг `--strict` принят для явности.

- `clean` (код 0): есть `scope` с текущим `diffHash`; каждая проверка из `required`
  закрыта `applied` с итогом `pass` или `findings` без `critical`; есть `probe ok` по
  каждому источнику, на который опираются закрывающие `applied`; пропусков и снятий нет.
- `with_gaps` (код 1): блокирующих условий нет, каждая проверка из `required` закрыта
  одним из трех способов - `applied` (как в `clean`), `skipped` с классом, действующим
  `release`; есть хотя бы один пропуск или снятие.
- `blocked` (код 3): нет `scope` с текущим `diffHash` (прогон устарел или не создан);
  поврежденный файл события; обязательная проверка без события; `applied` с `critical`
  больше 0 без действующего снятия этой проверки; `applied` без `toolUseId` или без
  итога; пропуск без класса или без ссылки; `release` с чужим `diffHash` или
  просроченное; нет `probe ok` по источнику закрывающего `applied`.
- код 2 - ошибка вызова (каталог, git, base, идентификатор сессии).

## CLI

```
python tools/evidence.py add --repo <каталог> --session <id> [--base <коммит>]
    --type skipped --check <проверка> --class <tool_unavailable|not_applicable>
        [--ref <файл события> | --reason <причина>]
python tools/evidence.py add ... --type not_verified --dimension <измерение> --reason <причина>
python tools/evidence.py add ... --type probe --source <ai-edt|naparnik|script>
    --status <ok|down> [--detail <пояснение>]
python tools/evidence.py check [--strict] --repo <каталог> --session <id> [--base <коммит>]
python tools/evidence.py render --repo <каталог> --session <id> [--base <коммит>]
```

`add` с типом `applied` или `release` завершается кодом 2 с сообщением "пишет только
хук". `check` печатает вердикт, блокирующие причины и пробелы. `render` печатает
markdown-отчет: вердикт, таблицы "Проверено", "С пробелами" (с классами пропусков),
"Не проверено" (обязательные без события и события `not_verified`); код 0 при любом
вердикте, 2 при ошибке вызова.
