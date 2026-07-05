# transcribe

Транскрибация аудио и видео с двумя движками:
- **Локальный** (default для аудио): `faster-whisper` (CUDA) + опц. диаризация `sherpa-onnx` GPU. Бесплатно, не уходит наружу. Видео тоже можно разобрать полностью локально - `--engine local` (разбор экрана локальной VLM через LM Studio + распознавание спикеров по голосу).
- **Gemini API** (default для видео и `--analyze-ui`): `gemini-2.5-flash`, разбор экрана + скриншоты. ~$0.10/час.

Спикеры в локальном видео определяются по ГОЛОСУ (накопительная голосовая база - узнает людей между встречами) и по репликам. Подробнее - в `SKILL.md`, раздел "Спикеры и голосовая база".

Производительность на RTX 5070 Ti Laptop: ~7 мин на 30 мин аудио с диаризацией (RTF ~0.24).

Если нужна только локальная транскрипция аудио (без видео и Gemini) - используйте более лёгкий скил `transcribe-audio-local` в этом же репо.

## Системные требования

- **Python 3.10+** (рекомендуется 3.12)
- **NVIDIA GPU** с CUDA 12 и cuDNN 9 (для локального GPU режима)
- **ffmpeg** и **ffprobe** — либо в PATH, либо setup поставит `static-ffmpeg` (pip-пакет с обоими бинарниками) в venv-whisper автоматически. Системные права не нужны.
- **Windows x64** или **Linux x64**
- **~6 ГБ свободного места** (venv-whisper ~2 ГБ, venv-sherpa ~3 ГБ, модели ~91 МБ)
- Для Gemini-режима: API-ключ с https://aistudio.google.com/apikey

## Установка

```bash
# 1. Скопировать папку скила в ~/.claude/skills/transcribe/
# 2. Запустить установщик
python ~/.claude/skills/transcribe/scripts/setup.py
```

Что произойдёт:
1. Проверка Python и ffmpeg.
2. Создание `venv-whisper/` со всеми зависимостями (faster-whisper, ctranslate2-CUDA, google-genai, python-dotenv, nvidia-*).
3. Создание `venv-sherpa/` с sherpa-onnx GPU + onnxruntime-gpu.
4. Скачивание моделей в `models/` с GitHub releases k2-fsa.
5. Создание шаблона `.env`.

Время установки: 10-20 минут (зависит от скорости интернета).

### Флаги setup.py

| Флаг | Когда нужен |
|---|---|
| `--skip-whisper` | venv-whisper уже создан |
| `--skip-sherpa` | Диаризация не нужна |
| `--skip-models` | Модели уже скачаны |
| `--skip-gemini` | Только локальный движок, без Gemini |
| `--with-pyannote` | Доп. поставить pyannote.audio 4.x для fallback диаризации (требует HF_TOKEN) |
| `--allow-cpu` | Разрешить установку на машине без NVIDIA GPU (CPU-режим, в 10+ раз медленнее) |

### Проверка установки

```bash
python scripts/verify.py             # быстрая проверка (5 сек)
python scripts/verify.py --full      # с реальным прогоном локальной транскрипции (~1-2 мин)
```

Что проверяется: venv-whisper (faster-whisper + google-genai) и venv-sherpa с импортами, модели, ffmpeg/ffprobe в PATH, заполнен ли `GEMINI_API_KEY` в `.env`. С `--full` дополнительно запускает локальную транскрипцию tiny-модели.

### Для AI-агентов

Установка длинная (~20-30 минут с загрузкой моделей и Gemini-зависимостей). Перед запуском `setup.py` через subprocess/Bash увеличьте таймаут до 30 минут или используйте фоновый режим. См. раздел «Для агента» в `SKILL.md`.

### Заполнить .env

После setup откройте `~/.claude/skills/transcribe/.env` и впишите ключ Gemini:

```
GEMINI_API_KEY=AIza...
```

Получить ключ: https://aistudio.google.com/apikey (бесплатная квота ~1500 запросов/день для Gemini 2.5 Flash).

Если установлен `pyannote 4.x` (флаг `--with-pyannote`) и хотите им пользоваться - дополнительно:

```
HF_TOKEN=hf_...
```

Read-токен с https://huggingface.co/settings/tokens, нужно принять условия моделей: `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`. Для default sherpa-onnx HF_TOKEN не нужен.

## Использование

Запуск из venv-whisper:

```bash
# Аудио, локально (по умолчанию)
~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe_local.py \
  "audio.mp3"

# Аудио с диаризацией
~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe_local.py \
  "audio.mp3" --diarize

# Видео через Gemini + анализ интерфейса (с скриншотами)
~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe.py \
  "video.mp4" --analyze-ui --with-summary

# Видео ПОЛНОСТЬЮ ЛОКАЛЬНО (без облака): экран локальной VLM + спикеры по голосу
python ~/.claude/skills/transcribe/scripts/analyze_video_local.py \
  "video.mp4" --diarize --num-speakers 4 --project "МойПроект"
```

На Linux/Mac: `venv-whisper/bin/python` вместо `venv-whisper/Scripts/python.exe`.

### Выходные файлы

Сохраняются в `<каталог-входа>/Транскрипция/<имя>/`:

| Файл | Когда создаётся |
|---|---|
| `<имя> - транскрипция.md` | всегда (md с таймкодами) |
| `<имя> - транскрипция.txt` | локальный движок (plain text) |
| `<имя> - со спикерами.md` | `--diarize` (реплики с `[Имя/SPEAKER_XX, MM:SS]`) |
| `<имя> - детальный.md` | `--analyze-ui` (Gemini) или `--engine local` - дословный лог экрана |
| `<имя> - связный.md` | `--engine local` (видео) - связный нарратив экран+речь |
| `<имя> - саммари.md` | Gemini `--with-summary`/`--analyze-ui` или `--engine local` |
| `<имя>.voiceprints.json` | `--engine local` (видео) - отпечатки голоса спикеров |
| `screenshots/` | `--analyze-ui` (Gemini) или `--engine local` (PNG-кадры) |

## Архитектура

```
скил/
├── SKILL.md                    # описание для Claude Code
├── README.md                   # эта инструкция
├── .env                        # ключи API (создаётся setup)
├── scripts/
│   ├── transcribe_local.py     # orchestrator локального аудио (faster-whisper + diarize)
│   ├── transcribe.py           # Gemini API клиент (видео + analyze-ui, chunked+parallel)
│   ├── analyze_video_local.py  # локальный разбор видео (экран + речь + спикеры по голосу)
│   ├── local_backends.py       # VLM/LLM на LM Studio + нарезка кадров ffmpeg
│   ├── text_stage.py           # общий текст-модуль: спикеры->имена, связный лог, саммари
│   ├── voiceprints.py          # голосовая база (enrollment + матчинг по голосу)
│   ├── diarize_sherpa.py       # worker диаризации sherpa-onnx (+ отпечатки голоса)
│   ├── setup.py                # установщик
│   └── verify.py               # проверка установки
├── venv-whisper/               # создаётся setup: faster-whisper + Gemini + CUDA
├── venv-sherpa/                # создаётся setup: sherpa-onnx + onnxruntime-gpu
└── models/                     # скачивается setup
    ├── sherpa-onnx-pyannote-segmentation-3-0/model.onnx
    └── 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx
```

Два venv нужны из-за конфликта CUDA DLL: `ctranslate2` (faster-whisper) и `onnxruntime-gpu` (sherpa-onnx) грузят несовместимые версии cuDNN. Изоляция через subprocess.

При `--diarize` транскрипция и диаризация запускаются параллельно.

## Стоимость

- Локальный движок: бесплатно (только электричество).
- Gemini 2.5 Flash: ~$0.10 за 1 час записи. Бесплатная квота AI Studio покрывает большинство личных задач.

## Troubleshooting

### `ffmpeg не найден в PATH`

Windows: скачайте с https://www.gyan.dev/ffmpeg/builds/, распакуйте, добавьте `bin/` в PATH.
Linux: `sudo apt install ffmpeg`.

### `CUDA out of memory`

Большая модель `large-v3-turbo` требует ~3 ГБ VRAM. Используйте меньшую:

```bash
~/.claude/skills/transcribe/venv-whisper/Scripts/python.exe \
  ~/.claude/skills/transcribe/scripts/transcribe_local.py \
  audio.mp3 --model openai/whisper-small --compute-type int8_float16
```

Или `--device cpu` (в 10+ раз медленнее).

### `sherpa_onnx не устанавливается с CUDA`

Setup пробует `pip install sherpa-onnx -f https://k2-fsa.github.io/sherpa/onnx/cuda.html`. Если упало:

1. Скачайте wheel вручную с https://huggingface.co/csukuangfj2/sherpa-onnx-wheels (например `sherpa_onnx-1.13.0+cuda12.cudnn9-cp312-cp312-win_amd64.whl` для Python 3.12 Windows).
2. Установите: `~/.claude/skills/transcribe/venv-sherpa/Scripts/pip.exe install <wheel>`.

CPU-вариант: `pip install sherpa-onnx` без `-f`.

### Gemini 503 / 429 / quota

Бесплатная квота Gemini 2.5 Flash ~1500 запросов/день. На больших файлах (>1ч) может закончиться. Варианты:
- Подождать сброса квоты (00:00 PT)
- Для аудио — fallback на локальный движок (`transcribe_local.py`)
- Заплатить за PAYG-тарифа в AI Studio

### Модели не скачиваются

URL k2-fsa releases:
- https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
- https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx

Если недоступны - скачайте вручную в `models/`, повторите `setup.py --skip-models` (распаковка архива всё равно произойдёт).

### CUDA DLL не находятся

1. Установлен ли CUDA 12 Toolkit?
2. В `venv-whisper/Lib/site-packages/nvidia/` есть пакеты cublas/cudnn/cuda_runtime?
3. Перезапустите терминал после установки CUDA.

## Лицензии

- faster-whisper - MIT
- sherpa-onnx - Apache 2.0
- pyannote-segmentation-3.0 (ONNX) - MIT (k2-fsa)
- 3D-Speaker eres2net - Apache 2.0
- Gemini API - условия Google
