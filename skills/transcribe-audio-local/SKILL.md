---
name: transcribe-audio-local
description: "Локальная транскрибация аудиофайлов без отправки в облако. Используй когда пользователь просит транскрибировать запись, расшифровать аудио, сделать конспект встречи, преобразовать речь в текст. Только для аудио (m4a/mp3/wav/ogg/flac/aac/wma/opus). Движок: faster-whisper CUDA + опц. диаризация sherpa-onnx GPU (CUDA, RTF ~0.24). Поддерживает разделение по спикерам."
argument-hint: "<AudioPath> [--output-dir DIR] [--diarize] [--num-speakers N] [--language ru]"
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /transcribe-audio-local - Локальная транскрибация аудио

Локальный движок: `faster-whisper` (CUDA) + опц. диаризация `sherpa-onnx GPU` (CUDA) с моделями pyannote-segmentation-3.0 + 3D-Speaker eres2net. Нет затрат, ничего не уходит наружу.

На RTX 5070 Ti Laptop: ~6-7 мин на 30 мин аудио (RTF ~0.24). Только аудио, видео не поддерживается.

## Установка (один раз)

```bash
python scripts/setup.py
```

Подробнее в `README.md`. После установки venv-whisper и venv-sherpa создаются рядом со скилом, модели качаются в `models/`.

## Режимы

### Без диаризации (default)

Выходные файлы:
- `<имя> - транскрипция.md` - таймкоды + текст
- `<имя> - транскрипция.txt` - plain text

### С диаризацией (`--diarize`)

Дополнительно:
- `<имя> - со спикерами.md` - реплики с метками `[SPEAKER_XX, MM:SS]`

## Аргументы

| Параметр | Обязательный | По умолчанию | Описание |
|----------|:---:|---|---|
| AudioPath | да | - | Путь к аудиофайлу |
| --output-dir | нет | `<каталог>/Транскрипция/<имя>/` | Каталог результатов |
| --diarize | нет | выкл | Разделение по спикерам (sherpa-onnx) |
| --num-speakers N | нет | автодетект | Точное число спикеров |
| --threshold | нет | 0.5 | Порог кластеризации (меньше -> больше кластеров) |
| --language | нет | ru | Язык транскрипции |
| --model | нет | mobiuslabsgmbh/faster-whisper-large-v3-turbo | Модель faster-whisper |
| --device | нет | cuda | cuda или cpu |
| --compute-type | нет | float16 | Точность вычислений |

## Поддерживаемые форматы

mp3, wav, ogg, m4a, flac, aac, wma, opus.

## Зависимости

- **venv-whisper** (рядом со скилом): `faster-whisper`, `ctranslate2-CUDA`, `av`, nvidia-cublas/cudnn/cuda-runtime
- **venv-sherpa** (рядом со скилом, для `--diarize`): `sherpa_onnx` (GPU CUDA сборка), `onnxruntime-gpu`, `soundfile`
- `ffmpeg` в PATH
- NVIDIA GPU + CUDA 12 + cuDNN 9 (для GPU режима, рекомендуется)

## Инструкция

1. Получи `AudioPath` от пользователя. Проверь что расширение - аудио из поддерживаемого списка.

2. Запусти транскрипцию:

```bash
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
  python ~/.claude/skills/transcribe-audio-local/scripts/transcribe.py \
  "<AudioPath>" [--output-dir "<OutputDir>"] [--diarize] [--num-speakers N]
```

Время работы:
- Без диаризации: ~1.5-2 мин на 27-мин файл (RTF ~0.07)
- С диаризацией: ~10 мин на 27-мин файл (RTF ~0.4, параллельно)
- Часовое аудио с диаризацией: ~25 мин

3. После завершения покажи пользователю пути к файлам и прочитай начало транскрипции.

**ВАЖНО:** `PYTHONUNBUFFERED=1` обязательно для прогресса.

## Ограничения

- Только аудио, видео не поддерживается. Если нужно из видео - извлеките аудиодорожку через ffmpeg отдельно.
- Требуется NVIDIA GPU с CUDA 12+ (CPU-режим работает, но в 10+ раз медленнее).
- Точность таймкодов +/- несколько секунд.
- Кириллические имена файлов обрабатываются скриптом.

## Установка диагностика

Если транскрипция или диаризация падает - см. `README.md` секция «Troubleshooting».
