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

## Для агента (Claude Code и подобные)

**Workflow первого использования:**

1. **Проверь, установлен ли скил** — есть ли файл `~/.claude/skills/transcribe-audio-local/venv-whisper/Scripts/python.exe` (на Linux: `venv-whisper/bin/python`). Если есть - переходи к шагу 4.

2. **Если не установлен — запусти setup**. Установка занимает 10-20 минут (faster-whisper + ctranslate2-CUDA + sherpa-onnx + скачивание моделей). Дефолтный Bash-таймаут 2 минуты не подходит:

   - В Claude Code Bash tool используй `run_in_background: true` или `timeout: 1500000` (25 мин).
   - В других runtime - аналогичный длинный таймаут.

   ```bash
   python ~/.claude/skills/transcribe-audio-local/scripts/setup.py
   ```

   Что setup сделает сам:
   - Создаст venv-whisper и venv-sherpa
   - Если `ffmpeg` нет в PATH — поставит `static-ffmpeg` (pip-пакет с бинарниками) в venv-whisper. Без прав админа.
   - Скачает модели диаризации
   - Проверит версию драйверов NVIDIA и предупредит, если они старее 525.x

   Что setup НЕ может сделать сам (нужны действия пользователя):
   - Установить системные драйверы NVIDIA / CUDA Toolkit (нужны админ-права)
   - Поставить NVIDIA GPU в машину 😉

   Если у машины нет GPU - setup упадёт с FAIL. Уточни у пользователя, согласен ли на CPU-режим (в 10+ раз медленнее), и перезапусти с `--allow-cpu`.

3. **Проверь установку** smoke-тестом (1-2 минуты, с реальной транскрипцией):

   ```bash
   python ~/.claude/skills/transcribe-audio-local/scripts/verify.py --full
   ```

   Без `--full` (5 сек) - только проверка наличия venv'ов и моделей, без реального прогона.

4. **Транскрибируй файл** (см. секцию «Инструкция» ниже). На CPU добавляй `--device cpu --compute-type int8`.

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
