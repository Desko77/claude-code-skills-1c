---
name: transcribe
description: "Транскрибирование видео и аудио файлов. Используй когда пользователь просит транскрибировать, расшифровать запись, сделать конспект встречи, извлечь речь из видео или аудио, преобразовать речь в текст. Для аудио (m4a/mp3/wav/ogg/flac/aac/wma) по умолчанию локальный faster-whisper + диаризация sherpa-onnx GPU (CUDA, RTF ~0.24, default). Для видео (mp4/mkv/webm/avi/mov) — Gemini API. Поддерживает разделение по спикерам."
argument-hint: "<FilePath> [--output-dir DIR] [--analyze-ui] [--with-summary] [--diarize] [--num-speakers N] [--diarize-engine sherpa-onnx|pyannote] [--engine local|gemini]"
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /transcribe - Транскрибация видео и аудио

Два движка:

- **Локальный (default для аудио)**: `faster-whisper` (CUDA) + опц. диаризация `sherpa-onnx GPU` (CUDA) с моделями pyannote-segmentation-3.0 + 3D-Speaker eres2net. Нет затрат, не уходит наружу. На RTX 5070 Ti Laptop: ~6-7 мин на 30 мин аудио (RTF ~0.24). **Только для аудио.** Альтернативный движок диаризации `--diarize-engine pyannote` (4.x, GPU, RTF 0.36).
- **Gemini (default для видео и `--analyze-ui`)**: облачный API, ~$0.10/час. Нужен интернет и квота. Стартовая модель `gemini-2.5-flash` (пин конкретной версии, дешевая); при перегрузке (503/429) переходит на `gemini-2.5-flash-lite`. Дорогие 3.5/pro сознательно исключены.

## Выбор движка по умолчанию

| Тип файла | Движок | Причина |
|---|---|---|
| Аудио (m4a, mp3, wav, ogg, flac, aac, wma) | local | Быстро, бесплатно, диаризация |
| Видео (mp4, mkv, webm, avi, mov) | gemini | Быстро, облако. Приватный вариант - `--engine local` (см. ниже) |
| Видео + `--engine local` | **local (150)** | Разбор экрана БЕЗ облака: whisper + Qwen3-VL на сервере 150 |
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
- `screenshots/` — PNG-кадры

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
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 python ~/.claude/skills/transcribe/scripts/analyze_video_local.py "<FilePath>" [--output-dir "<OutputDir>"] [--diarize] [--no-summary]
```

Речь - локальный whisper; разбор экрана - `qwen3-vl-8b-instruct` на локальном сервере LM Studio; саммари - `google/gemma-4-26b-a4b` там же. Клиентские кадры НЕ уходят в облако. Предусловия: сервер LM Studio доступен (по умолчанию `http://localhost:1234`, переопределяется env `LOCAL_150_BASE`), нужные модели загружены (скрипт проверяет `/v1/models` и внятно сообщает, если модели нет). Время ~20-35 мин на час записи (кадры идут последовательно ~14с/кадр, зависит от активности экрана). Выходные файлы те же, что у облачного analyze-ui (транскрипция / детальный / саммари / screenshots), но в `screenshots/` попадают ВСЕ scene-кадры. ВНИМАНИЕ: локальное зрение НЕ гарантирует посимвольную точность (в отличие от облака) - финансовые цифры сверять с экраном. Переопределяется через env: `LOCAL_150_BASE`, `LOCAL_VLM_MODEL`, `LOCAL_SUMMARY_MODEL`, `SCENE_THRESHOLD`, `FRAME_FLOOR_SEC`, `FRAME_CAP`, `WHISPER_PYTHON`.

4. Иначе (видео без `--engine local`, или явный `--engine gemini`, или `--analyze-ui`) — запускай Gemini:

```bash
PYTHONUNBUFFERED=1 python ~/.claude/skills/transcribe/scripts/transcribe.py "<FilePath>" [--output-dir "<OutputDir>"] [--analyze-ui] [--with-summary] [--format md|txt] [--model MODEL] [--fallback-models "m1,m2"] [--no-fallback]
```

Скрипт долгий (5-15 мин), файлы >1 ч разбиваются автоматически.

4. **Fallback при перегрузке Gemini** (503 / 429): скрипт сам перебирает пул моделей (см. "Авто-fallback по моделям Gemini"), доп. действий не требуется. Если весь пул недоступен и это аудио - крайний случай: локальный движок (см. шаг 2).

5. После завершения покажи пользователю пути к файлам и прочитай начало транскрипции / саммари.

**ВАЖНО:** `PYTHONUNBUFFERED=1` обязательно для прогресса.

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

- Локальный АУДИО-движок (whisper) сам по себе не делает анализ интерфейсов. Для локального разбора ЭКРАНА видео есть отдельный путь `--engine local` для видео (`analyze_video_local.py`: whisper + Qwen3-VL на сервере 150) - требует доступный сервер 150 и загруженные модели; посимвольная точность зрения не гарантирована.
- Локальный движок требует CUDA GPU.
- Pyannote 4.x (диаризация) — модели gated, нужны принятые условия + HF-токен.
- Кириллические имена файлов: скриптом обрабатываются.
- Точность таймкодов +/- несколько секунд.
- `--analyze-ui` с аудиофайлом → fallback на Gemini generic + саммари.
