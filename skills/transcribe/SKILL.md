---
name: transcribe
description: "Транскрибирование видео и аудио файлов. Используй когда пользователь просит транскрибировать, расшифровать запись, сделать конспект встречи, извлечь речь из видео или аудио, преобразовать речь в текст. Для аудио (m4a/mp3/wav/ogg/flac/aac/wma) по умолчанию локальный faster-whisper + диаризация sherpa-onnx GPU (CUDA, RTF ~0.24). Для видео (mp4/mkv/webm/avi/mov) - Gemini API (разбор экрана + скриншоты) либо полностью локально (--engine local: whisper + локальная VLM). Разделение по спикерам с распознаванием имен по голосу между встречами (голосовая база) и по репликам."
argument-hint: "<FilePath> [--output-dir DIR] [--engine local|gemini] [--analyze-ui] [--with-summary] [--diarize] [--num-speakers N] [--diarize-engine sherpa-onnx|pyannote] [--project NAME] [--no-voiceprints] [--no-coherent]"
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /transcribe - Транскрибация видео и аудио

Два движка:

- **Локальный (default для аудио)**: `faster-whisper` (CUDA) + опц. диаризация `sherpa-onnx GPU` (CUDA) с моделями pyannote-segmentation-3.0 + 3D-Speaker eres2net. Нет затрат, не уходит наружу. На RTX 5070 Ti Laptop: ~6-7 мин на 30 мин аудио (RTF ~0.24). Альтернативный движок диаризации `--diarize-engine pyannote` (4.x, GPU, RTF 0.36). ВИДЕО тоже можно разобрать полностью локально - `--engine local` (разбор экрана локальной VLM + спикеры по голосу, см. ниже).
- **Gemini (default для видео и `--analyze-ui`)**: облачный API, ~$0.10/час. Нужен интернет и квота. Стартовая модель `gemini-2.5-flash` (пин конкретной версии, дешевая); при перегрузке (503/429) переходит на `gemini-2.5-flash-lite`. Дорогие 3.5/pro сознательно исключены.

## Выбор движка по умолчанию

| Тип файла | Движок | Причина |
|---|---|---|
| Аудио (m4a, mp3, wav, ogg, flac, aac, wma) | local | Быстро, бесплатно, диаризация |
| Видео (mp4, mkv, webm, avi, mov) | gemini | Быстро, облако. Приватный вариант - `--engine local` (см. ниже) |
| Видео + `--engine local` | **local** | Разбор экрана БЕЗ облака: whisper + локальная VLM (LM Studio) + спикеры по голосу |
| Любой + `--analyze-ui` | gemini | Детальный разбор интерфейсов в облаке |
| Любой + `--engine gemini` | gemini | Явный override на облако |
| Аудио + `--engine local` | local | Явный override (аудио) |

При 503/429 Gemini-движок сначала сам перебирает пул моделей (см. раздел "Авто-fallback по моделям Gemini"). Если весь пул недоступен и это аудио - можно вручную переключиться на local (`--engine local`).

## Режимы

### Локальный (аудио + faster-whisper + опц. pyannote)

Выходные файлы:
- `<имя> - транскрипция.md` — таймкоды + текст
- `<имя> - транскрипция.txt` — plain text
- `<имя> - со спикерами.md` — реплики с метками `[SPEAKER_XX, MM:SS]` (только при `--diarize`)

### Gemini generic

Выходные файлы:
- `<имя> - транскрипция.md` — речь с таймкодами + спикеры (если различимы)
- `<имя> - саммари.md` — протокол встречи (с флагом `--with-summary`); строится из текста транскрипции в 2 прохода (экстрактор всех фактов -> протокол) для полноты задач/решений

### Gemini analyze-ui (только видео)

Анализ видеозаписи с разбором экранного интерфейса + скриншоты.
Детальный лог и транскрипция пишутся по частям сразу (инкрементально): сбой на поздней части длинного видео не теряет ранние. Саммари строится в конце из полной транскрипции (2 прохода) - это протокол задач/решений; разбор показанных интерфейсов - в детальном логе.

Выходные файлы:
- `<имя> - саммари.md`
- `<имя> - детальный.md`
- `<имя> - транскрипция.md`
- `screenshots/` - PNG-кадры

### Локальный разбор видео (`--engine local`, только видео)

Полностью локальный разбор экрана + речи БЕЗ облака (подробности в "Инструкция" ниже). Спикеры распознаются по голосу (голосовая база) и по репликам - см. "Спикеры и голосовая база".

Выходные файлы:
- `<имя> - транскрипция.md` / `.txt`
- `<имя> - со спикерами.md` (при `--diarize`)
- `<имя> - детальный.md` - дословный лог: описание экрана по кадрам + реплики за интервал
- `<имя> - связный.md` - связный нарратив экран+речь (если не `--no-coherent`)
- `<имя> - саммари.md` - протокол задач/решений (если не `--no-summary`)
- `<имя>.voiceprints.json` - отпечатки голоса кластеров
- `screenshots/` - ВСЕ scene-кадры

## Аргументы

| Параметр | Обязательный | По умолчанию | Описание |
|----------|:---:|---|---|
| FilePath | да | — | Путь к аудио/видеофайлу |
| --output-dir | нет | `<каталог>/Транскрипция/<имя>/` | Каталог результатов |
| --engine | нет | auto (local для аудио, gemini для видео) | `local` или `gemini` |
| --diarize | нет | выкл | Локальный движок: разделение по спикерам |
| --num-speakers N | нет | автодетект | Точное число спикеров |
| --min-speakers N / --max-speakers N | нет | — | Границы для автодетекта |
| --analyze-ui | нет | выкл | Gemini: анализ интерфейсов (только видео) |
| --with-summary | нет | выкл | Gemini: добавить саммари |
| --format | нет | md | Формат: md или txt |
| --model | нет | gemini-2.5-flash | Gemini: стартовая модель (или env GEMINI_MODEL) |
| --fallback-models | нет | встроенный пул | Gemini: цепочка fallback через запятую (или env GEMINI_FALLBACK_MODELS) |
| --no-fallback | нет | выкл | Gemini: только стартовая модель, без перебора |
| --project NAME | нет | - | local видео: пометить встречу в голосовой базе (провенанс) |
| --voiceprint-db PATH | нет | `voiceprints/db.json` скилла | local видео: путь к голосовой базе |
| --no-voiceprints | нет | выкл | local видео: не использовать и не пополнять голосовую базу |
| --no-coherent | нет | выкл | local видео: не строить связный лог (быстрее) |
| --no-summary | нет | выкл | local видео: не строить саммари |
| --speaker-model M | нет | qwen2.5-32b | local видео: LLM для маппинга спикеров -> имена |
| --reuse-transcript | нет | выкл | local видео: не гонять whisper заново, если транскрипция уже есть |

## Поддерживаемые форматы

- **Видео:** mp4, mkv, webm, avi, mov
- **Аудио:** mp3, wav, ogg, m4a, flac, aac, wma

## Зависимости

**Локальный движок:**
- venv whisper (отдельный, изоляция CUDA-DLL): путь в env `WHISPER_PYTHON`; дефолт `~/.claude/skills/transcribe/venv-whisper` (faster-whisper, ctranslate2-CUDA, ffmpeg)
- Для `--diarize` (default `sherpa-onnx` GPU CUDA): `~/.claude/skills/transcribe/venv-sherpa` с GPU-сборкой `sherpa_onnx 1.13.0+cuda12.cudnn9` от k2-fsa maintainer (HuggingFace `csukuangfj2/sherpa-onnx-wheels`). Использует pyannote-segmentation-3.0 + 3D-Speaker eres2net эмбеддинги в ONNX. RTF ~0.24, никаких HF gated моделей.
- Альтернатива `--diarize-engine pyannote`: `torch` + `pyannote.audio>=4` в основном venv, `HF_TOKEN` в `.env` (read-токен с принятыми условиями `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`, `pyannote/speaker-diarization-community-1`). RTF ~0.36, чуть медленнее sherpa.
- CUDA GPU обязателен для обоих движков

**Gemini движок:**
- Python-пакеты: `google-genai`, `python-dotenv`
- Системные: `ffmpeg`, `ffprobe` в PATH
- API-ключ в `~/.claude/skills/transcribe/.env`: `GEMINI_API_KEY=...`

## Установка и настройка (для агента)

Перед первым запуском проверь, установлен ли скилл: есть ли каталог `~/.claude/skills/transcribe/venv-whisper/`.

Если НЕ установлен - запусти установщик. Он ДОЛГИЙ (~20-30 мин: venv'ы, CUDA-пакеты, модели) - ставь длинный таймаут или фоновый режим:

```bash
python ~/.claude/skills/transcribe/scripts/setup.py
```

Полезные флаги: `--skip-gemini` (без облака), `--skip-sherpa` (без диаризации), `--with-pyannote` (альт. движок диаризации), `--allow-cpu` (без GPU). После установки - проверка:

```bash
python ~/.claude/skills/transcribe/scripts/verify.py --full
```

Настрой `.env` (`~/.claude/skills/transcribe/.env`, он в gitignore, НЕ коммить):
- `GEMINI_API_KEY=...` - для Gemini (видео + fallback аудио), ключ https://aistudio.google.com/apikey.
- `HF_TOKEN=...` - только если ставил `--with-pyannote`.
- `WHISPER_PYTHON=...` - путь к python из venv-whisper, если venv НЕ в дефолтном месте (локальное видео зовет whisper этим python).
- `LOCAL_150_BASE=http://ХОСТ:ПОРТ/v1` - если LM Studio не на `localhost:1234`.

Для `--engine local` (локальный разбор ВИДЕО) дополнительно нужен запущенный **LM Studio** с 3 моделями: `qwen3-vl-8b-instruct` (зрение), `google/gemma-4-26b-a4b` (связный лог + саммари), `qwen2.5-32b-instruct` (спикеры). Плюс в python, которым запускается `analyze_video_local.py`, нужны `Pillow` и `numpy` (`pip install Pillow numpy`). Пошаговая настройка LM Studio - в README. Скрипт проверяет `/v1/models` и внятно сообщает, если модели нет - тогда предложи пользователю догрузить модель или запустить сервер.

## Инструкция

1. Определи `FilePath` и флаги. По расширению файла и флагам выбери движок (см. таблицу выше).

2. Если расширение — аудио, и нет `--engine gemini`, и нет `--analyze-ui` → запускай локальный:

```bash
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
  ~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe_local.py \
  "<FilePath>" [--output-dir "<OutputDir>"] [--diarize] [--num-speakers N] [--min-speakers N] [--max-speakers N]
```

Локальный пайплайн:
- Транскрипция и диаризация запускаются в **отдельных subprocess параллельно** (изоляция CUDA-DLL ctranslate2 vs torch).
- 27-мин аудио = ~10 мин общего времени (RTF ~0.4).
- Часовое аудио = ~25 мин общего времени.
- Диаризация — только при `--diarize`. Без неё ~1.5-2 мин на 27-мин файл.

3. Если это ВИДЕО и указан `--engine local` → запускай ПОЛНОСТЬЮ ЛОКАЛЬНЫЙ разбор экрана (без облака):

```bash
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 python ~/.claude/skills/transcribe/scripts/analyze_video_local.py "<FilePath>" [--output-dir "<OutputDir>"] [--diarize] [--num-speakers N] [--project NAME] [--voiceprint-db PATH] [--no-voiceprints] [--no-coherent] [--no-summary]
```

Речь - локальный whisper; разбор экрана - `qwen3-vl-8b-instruct` на локальном сервере LM Studio; связный лог и саммари - `google/gemma-4-26b-a4b`; маппинг спикеров по репликам - `qwen2.5-32b`. Кадры обрабатываются параллельно (число слотов выводится из контекста VLM под unified KV cache). Клиентские кадры НЕ уходят в облако. Спикеры распознаются слоями: по ГОЛОСУ (голосовая база, узнает людей между встречами) и по репликам - см. "Спикеры и голосовая база". Предусловия: сервер LM Studio доступен (по умолчанию `http://localhost:1234`, env `LOCAL_150_BASE`), модели `qwen3-vl-8b-instruct` + `google/gemma-4-26b-a4b` + `qwen2.5-32b-instruct` загружены (скрипт проверяет и внятно сообщает, если модели нет). Выход: транскрипция / со спикерами / детальный / связный / саммари / `voiceprints.json` / `screenshots/` (ВСЕ scene-кадры). ВНИМАНИЕ: локальное зрение НЕ гарантирует посимвольную точность (в отличие от облака) - финансовые цифры сверять с экраном. Env-переопределения: `LOCAL_150_BASE`, `LOCAL_VLM_MODEL`, `LOCAL_SUMMARY_MODEL`, `LOCAL_SPEAKER_MODEL`, `SCENE_THRESHOLD`, `FRAME_FLOOR_SEC`, `FRAME_CAP`, `WHISPER_PYTHON`.

4. Иначе (видео без `--engine local`, или явный `--engine gemini`, или `--analyze-ui`) — запускай Gemini:

```bash
PYTHONUNBUFFERED=1 python ~/.claude/skills/transcribe/scripts/transcribe.py "<FilePath>" [--output-dir "<OutputDir>"] [--analyze-ui] [--with-summary] [--format md|txt] [--model MODEL] [--fallback-models "m1,m2"] [--no-fallback]
```

Скрипт долгий (5-15 мин), файлы >1 ч разбиваются автоматически.

4. **Fallback при перегрузке Gemini** (503 / 429): скрипт сам перебирает пул моделей (см. "Авто-fallback по моделям Gemini"), доп. действий не требуется. Если весь пул недоступен и это аудио - крайний случай: локальный движок (см. шаг 2).

5. После завершения покажи пользователю пути к файлам и прочитай начало транскрипции / саммари.

**ВАЖНО:** `PYTHONUNBUFFERED=1` обязательно для прогресса.

## Спикеры и голосовая база

В локальном разборе видео (`--engine local`) имена спикеров определяются ДВУМЯ слоями (голос приоритетнее):

1. **По голосу (голосовая база).** Диаризация считает отпечаток голоса каждого спикера (eres2net-эмбеддинг). Отпечаток сверяется с накопительной базой `voiceprints/db.json` по косинусной близости - так узнаются даже неназванные люди и ОДИН человек между разными встречами. Это больше, чем делает облако (оно вяжет имена только внутри одной записи).
2. **По репликам (текст).** LLM (`qwen2.5-32b`) читает транскрипт и вяжет имена по обращениям ("Иван, что скажешь?"), самопредставлениям, ссылкам. Голос приоритетнее текста.

Авто-пополнение (бутстрап): если человек назван текстом, но в базе его еще нет - его отпечаток заносится в базу, и на будущих встречах он узнается уже по голосу. Неоднозначные имена (одно имя на нескольких спикеров в одной записи) НЕ заносятся.

Провенанс: `--project NAME` помечает, в каком проекте/встрече встречался человек (полезно при пересечении людей между проектами).

Управление: `--no-voiceprints` (не трогать базу), `--voiceprint-db PATH` (своя база), `--speaker-model` (модель текстового слоя). Голоса - чувствительные данные: база хранится ЛОКАЛЬНО и не коммитится.

Просмотр / ручной enroll базы:
```bash
python ~/.claude/skills/transcribe/scripts/voiceprints.py list
python ~/.claude/skills/transcribe/scripts/voiceprints.py match --prints "<имя>.voiceprints.json"
```

## Авто-fallback по моделям Gemini

При 503 (перегрузка серверов Google) или 429 (лимит) скрипт автоматически переходит к следующей модели из пула, пока одна не ответит. Ретрай одной модели делает SDK, смену модели - скрипт.

Дефолтная цепочка (только дешевые модели 2.5):
`gemini-2.5-flash` -> `gemini-2.5-flash-lite`.

Дорогие модели (`gemini-3.5-flash`, `*-pro`, плавающие `*-latest`) сознательно НЕ в цепочке: плавающий `gemini-flash-latest` дрейфовал в `gemini-3.5-flash` и дал 96% счета за июнь 2026 (видео-вход в 5x дороже 2.5-flash). Нужна максимальная надежность любой ценой - добавить их через `--fallback-models`.

Управление:
- `--model MODEL` - стартовая модель (или env `GEMINI_MODEL`).
- `--fallback-models "m1,m2,..."` - переопределить цепочку (или env `GEMINI_FALLBACK_MODELS`).
- `--no-fallback` - только стартовая модель, без перебора.

503 - серверная перегрузка Gemini, она НЕ зависит от тарифа (платный тариф не помогает). Перебор моделей - официально рекомендованный обход. По умолчанию перебор идет только по дешевым 2.5-моделям.

## Стоимость

- Локальный движок: бесплатно (только электричество).
- Gemini: flash-класс ~$0.10-0.30 за 1 час записи. По умолчанию перебор только по дешевым 2.5-моделям (дорогие 3.5/pro исключены).

## Ограничения

- Локальный АУДИО-движок (whisper) сам по себе не делает анализ интерфейсов. Для локального разбора ЭКРАНА видео есть отдельный путь `--engine local` (`analyze_video_local.py`: whisper + локальная VLM на LM Studio + спикеры по голосу) - требует доступный сервер LM Studio и загруженные модели; посимвольная точность зрения не гарантирована.
- Локальный движок требует CUDA GPU.
- Pyannote 4.x (диаризация) — модели gated, нужны принятые условия + HF-токен.
- Кириллические имена файлов: скриптом обрабатываются.
- Точность таймкодов +/- несколько секунд.
- `--analyze-ui` с аудиофайлом → fallback на Gemini generic + саммари.
