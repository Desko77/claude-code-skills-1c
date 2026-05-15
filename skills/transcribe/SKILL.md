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
- **Gemini (default для видео и `--analyze-ui`)**: облачный API, ~$0.10/час. Нужен интернет и квота.

## Выбор движка по умолчанию

| Тип файла | Движок | Причина |
|---|---|---|
| Аудио (m4a, mp3, wav, ogg, flac, aac, wma) | local | Быстро, бесплатно, диаризация |
| Видео (mp4, mkv, webm, avi, mov) | gemini | Локально нет работы с видео |
| Любой + `--analyze-ui` | gemini | Анализ интерфейсов — только Gemini |
| Любой + `--engine gemini` | gemini | Явный override |
| Любой + `--engine local` (только аудио) | local | Явный override |

Если Gemini API возвращает 503 / квоту — fallback на local для аудио.

## Для агента (Claude Code и подобные)

**Workflow первого использования:**

1. **Проверь, установлен ли скил** — есть ли файл `~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe` (на Linux: `venv-whisper/bin/python`). Если есть - переходи к шагу 4.

2. **Если не установлен — запусти setup**. Установка занимает 15-25 минут (faster-whisper + Gemini + sherpa-onnx + скачивание моделей). Дефолтный Bash-таймаут 2 минуты не подходит:

   - В Claude Code Bash tool используй `run_in_background: true` или `timeout: 1800000` (30 мин).
   - В других runtime - аналогичный длинный таймаут.

   ```bash
   python ~/.claude/skills/transcribe/scripts/setup.py
   ```

   Что setup сделает сам:
   - Создаст venv-whisper (faster-whisper + Gemini SDK + CUDA) и venv-sherpa
   - Если `ffmpeg`/`ffprobe` нет в PATH — поставит `static-ffmpeg` в venv-whisper. Без прав админа.
   - Скачает модели диаризации
   - Проверит версию NVIDIA-драйверов и предупредит, если ниже 525.x
   - Создаст шаблон `.env` (пустой `GEMINI_API_KEY`)

   Что setup НЕ может сделать сам:
   - Установить системные NVIDIA-драйверы / CUDA Toolkit (нужны админ-права)
   - Получить `GEMINI_API_KEY` за пользователя

   Если у машины нет GPU - setup упадёт с FAIL. Уточни у пользователя про CPU-режим и перезапусти с `--allow-cpu`.

3. **Запроси у пользователя ключ Gemini** (если планируется работа с видео или `--analyze-ui`). Открой `~/.claude/skills/transcribe/.env` и впиши `GEMINI_API_KEY=...`. Ключ берётся на https://aistudio.google.com/apikey. Без ключа локальный режим (только аудио) работает.

4. **Проверь установку**:

   ```bash
   python ~/.claude/skills/transcribe/scripts/verify.py --full
   ```

   Без `--full` (5 сек) - только проверка venv/моделей. С `--full` (1-2 мин) - реальный прогон транскрипции.

5. **Транскрибируй файл** (см. секцию «Инструкция» ниже).

## Режимы

### Локальный (аудио + faster-whisper + опц. pyannote)

Выходные файлы:
- `<имя> - транскрипция.md` — таймкоды + текст
- `<имя> - транскрипция.txt` — plain text
- `<имя> - со спикерами.md` — реплики с метками `[SPEAKER_XX, MM:SS]` (только при `--diarize`)

### Gemini generic

Выходные файлы:
- `<имя> - транскрипция.md` — речь с таймкодами + спикеры (если различимы)
- `<имя> - саммари.md` — краткое саммари (с флагом `--with-summary`)

### Gemini analyze-ui (только видео)

Анализ видеозаписи с разбором экранного интерфейса + скриншоты.

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

## Поддерживаемые форматы

- **Видео:** mp4, mkv, webm, avi, mov
- **Аудио:** mp3, wav, ogg, m4a, flac, aac, wma

## Зависимости

Все зависимости ставятся одним скриптом:

```bash
python ~/.claude/skills/transcribe/scripts/setup.py
```

Подробности в `README.md`. Скрипт создаёт:
- `~/.claude/skills/transcribe/venv-whisper/` - faster-whisper + ctranslate2-CUDA + google-genai + python-dotenv
- `~/.claude/skills/transcribe/venv-sherpa/` - sherpa-onnx GPU + onnxruntime-gpu (для диаризации)
- `~/.claude/skills/transcribe/models/` - pyannote-segmentation-3.0 + 3D-Speaker eres2net
- `~/.claude/skills/transcribe/.env` - шаблон, заполнить `GEMINI_API_KEY` для Gemini-режима

Системные: `ffmpeg`, `ffprobe` в PATH; NVIDIA GPU + CUDA 12 + cuDNN 9 для GPU.

Альтернативная диаризация `--diarize-engine pyannote` (4.x) ставится отдельно: `python scripts/setup.py --with-pyannote`. Требует `HF_TOKEN` в `.env`. По умолчанию используется sherpa-onnx (без gated моделей).

## Инструкция

1. Определи `FilePath` и флаги. По расширению файла и флагам выбери движок (см. таблицу выше).

2. Если расширение — аудио, и нет `--engine gemini`, и нет `--analyze-ui` → запускай локальный:

```bash
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
  ~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe_local.py \
  "<FilePath>" [--output-dir "<OutputDir>"] [--diarize] [--num-speakers N] [--min-speakers N] [--max-speakers N]
```

На Linux/Mac: `venv-whisper/bin/python` вместо `venv-whisper/Scripts/python.exe`.

Локальный пайплайн:
- Транскрипция и диаризация запускаются в **отдельных subprocess параллельно** (изоляция CUDA-DLL ctranslate2 vs torch).
- 27-мин аудио = ~10 мин общего времени (RTF ~0.4).
- Часовое аудио = ~25 мин общего времени.
- Диаризация — только при `--diarize`. Без неё ~1.5-2 мин на 27-мин файл.

3. Иначе (видео, или явный `--engine gemini`, или `--analyze-ui`) — запускай Gemini:

```bash
PYTHONUNBUFFERED=1 \
  ~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe.py \
  "<FilePath>" [--output-dir "<OutputDir>"] [--analyze-ui] [--with-summary] [--format md|txt]
```

Скрипт долгий (5-15 мин), файлы >1 ч разбиваются автоматически.

4. **Fallback при ошибке Gemini API** (503 / 429 / quota) для аудио: повторно запусти локальный движок (см. шаг 2).

5. После завершения покажи пользователю пути к файлам и прочитай начало транскрипции / саммари.

**ВАЖНО:** `PYTHONUNBUFFERED=1` обязательно для прогресса.

## Стоимость

- Локальный движок: бесплатно (только электричество).
- Gemini: ~$0.10 за 1 час записи (Gemini 2.5 Flash).

## Ограничения

- Локальный движок не делает анализ интерфейсов и не работает с видео без аудиодорожки.
- Локальный движок требует CUDA GPU.
- Pyannote 4.x (диаризация) — модели gated, нужны принятые условия + HF-токен.
- Кириллические имена файлов: скриптом обрабатываются.
- Точность таймкодов +/- несколько секунд.
- `--analyze-ui` с аудиофайлом → fallback на Gemini generic + саммари.
