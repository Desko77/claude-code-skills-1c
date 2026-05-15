# transcribe-audio-local

Локальная транскрибация аудио + опциональная диаризация. Без облака, без API-ключей.

- **Транскрипция**: faster-whisper (CUDA, large-v3-turbo)
- **Диаризация**: sherpa-onnx GPU (pyannote-segmentation-3.0 + 3D-Speaker eres2net)
- **Производительность** на RTX 5070 Ti Laptop: ~7 мин на 30 мин аудио с диаризацией (RTF ~0.24)

## Системные требования

- **Python 3.10+** (рекомендуется 3.12)
- **NVIDIA GPU** с CUDA 12 и cuDNN 9 (для GPU режима)
- **ffmpeg** в PATH ([Windows builds](https://www.gyan.dev/ffmpeg/builds/) или `apt install ffmpeg`)
- **Windows x64** или **Linux x64**
- **~5 ГБ свободного места** (venv-whisper ~2 ГБ, venv-sherpa ~3 ГБ, модели ~91 МБ)

CPU-режим работает, но в 10+ раз медленнее.

## Установка

### 1. Скопируйте папку скила

В Claude Code/Cursor скилы лежат в `~/.claude/skills/`. Скопируйте папку `transcribe-audio-local/` туда либо в любое другое место (если запускаете скрипты напрямую).

### 2. Запустите установщик

```bash
python ~/.claude/skills/transcribe-audio-local/scripts/setup.py
```

Что произойдёт:
1. Проверка Python и ffmpeg.
2. Создание `venv-whisper/` рядом со скилом и установка `faster-whisper` + CUDA-стека.
3. Создание `venv-sherpa/` и установка `sherpa-onnx` (GPU сборка) + `onnxruntime-gpu`.
4. Скачивание моделей в `models/`:
   - `sherpa-onnx-pyannote-segmentation-3-0.tar.bz2` (~7 МБ, распакуется)
   - `3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx` (~40 МБ)

Время установки: 5-15 минут (зависит от скорости интернета).

### Флаги установщика

| Флаг | Когда нужен |
|---|---|
| `--skip-whisper` | venv-whisper уже создан, повторное создание не нужно |
| `--skip-sherpa` | Диаризация не нужна, пропустить установку sherpa |
| `--skip-models` | Модели уже скачаны/положены вручную |

## Использование

### Без диаризации

```bash
python ~/.claude/skills/transcribe-audio-local/scripts/transcribe.py "путь/к/audio.mp3"
```

Создаёт в `путь/к/Транскрипция/audio/`:
- `audio - транскрипция.md` (markdown с таймкодами)
- `audio - транскрипция.txt` (plain text)

### С диаризацией (разделение по спикерам)

```bash
python ~/.claude/skills/transcribe-audio-local/scripts/transcribe.py "путь/к/audio.mp3" --diarize
```

Дополнительно создаёт:
- `audio - со спикерами.md` (реплики с `[SPEAKER_XX, MM:SS]`)

### Все опции

```
positional:
  AudioPath              Путь к аудиофайлу (m4a/mp3/wav/ogg/flac/aac/wma/opus)

options:
  --output-dir DIR       Каталог вывода (default: <каталог входа>/Транскрипция/<имя>/)
  --diarize              Включить диаризацию (параллельно с транскрипцией)
  --num-speakers N       Точное число спикеров (без авто-кластеризации)
  --threshold T          Порог кластеризации sherpa (default 0.5)
  --language LANG        Язык транскрипции (default ru)
  --model NAME           Модель faster-whisper (default mobiuslabsgmbh/faster-whisper-large-v3-turbo)
  --device DEV           cuda или cpu (default cuda)
  --compute-type CT      Точность (default float16)
  --keep-intermediate    Не удалять промежуточные JSON
```

## Поддерживаемые форматы

Только аудио: `mp3`, `wav`, `ogg`, `m4a`, `flac`, `aac`, `wma`, `opus`.

Видео не поддерживается. Если у вас видео - извлеките аудиодорожку через ffmpeg:

```bash
ffmpeg -i video.mp4 -vn -acodec libmp3lame -ab 192k audio.mp3
```

## Архитектура

```
скил/
├── SKILL.md                # описание для Claude Code
├── README.md               # эта инструкция
├── scripts/
│   ├── transcribe.py       # orchestrator (CLI)
│   ├── diarize_sherpa.py   # worker диаризации
│   └── setup.py            # установщик зависимостей
├── venv-whisper/           # создаётся setup.py: faster-whisper + CUDA
├── venv-sherpa/            # создаётся setup.py: sherpa-onnx + onnxruntime-gpu
└── models/                 # скачивается setup.py
    ├── sherpa-onnx-pyannote-segmentation-3-0/model.onnx
    └── 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx
```

Два venv нужны из-за конфликта CUDA DLL: `ctranslate2` (через faster-whisper) и `onnxruntime-gpu` (через sherpa-onnx) грузят несовместимые версии cuDNN. Изоляция через subprocess.

Транскрипция и диаризация запускаются параллельно (если `--diarize`).

## Troubleshooting

### `ffmpeg не найден в PATH`

Windows: скачайте с https://www.gyan.dev/ffmpeg/builds/, распакуйте, добавьте `bin/` в PATH.
Linux: `sudo apt install ffmpeg`.

### `CUDA out of memory`

Большая модель `large-v3-turbo` требует ~3 ГБ VRAM. Если не хватает - используйте меньшую:

```bash
python scripts/transcribe.py audio.mp3 --model openai/whisper-small --compute-type int8_float16
```

Или `--device cpu` (в 10+ раз медленнее).

### `sherpa_onnx не устанавливается с CUDA`

Установщик пробует `pip install sherpa-onnx -f https://k2-fsa.github.io/sherpa/onnx/cuda.html`. Если не вышло:

1. Скачайте wheel вручную с https://huggingface.co/csukuangfj2/sherpa-onnx-wheels (например, `sherpa_onnx-1.13.0+cuda12.cudnn9-cp312-cp312-win_amd64.whl` для Python 3.12 Windows).
2. Установите: `<skill>/venv-sherpa/Scripts/pip.exe install <путь-к-wheel.whl>`.

CPU-режим тоже работает: `pip install sherpa-onnx` без extra-index.

### `pyannote/speaker-diarization gated model`

Этот скил **НЕ** использует gated модели pyannote. Использует только открытые ONNX:
- pyannote-segmentation-3.0 (выложен k2-fsa в открытом доступе)
- 3D-Speaker eres2net (Apache 2.0)

HF_TOKEN не нужен.

### Модели не скачиваются

URL из `setup.py`:
- https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
- https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx

Если они недоступны - скачайте вручную, положите в `models/`, повторите `setup.py --skip-models` (распаковка архива всё равно произойдёт).

### Транскрипция падает с `dll not found`

CUDA DLL не подхватываются. Проверьте:
1. Установлен ли CUDA 12 Toolkit?
2. В `venv-whisper/Lib/site-packages/nvidia/` есть пакеты `cublas`, `cudnn`, `cuda_runtime`?
3. Перезапустите терминал после установки CUDA.

## Лицензии

- faster-whisper - MIT
- sherpa-onnx - Apache 2.0
- pyannote-segmentation-3.0 (ONNX) - MIT (k2-fsa)
- 3D-Speaker eres2net - Apache 2.0

## Происхождение

Адаптировано из скила `transcribe` (https://github.com/Desko77/claude-code-skills-1c) с урезанием поддержки видео и облачного Gemini-движка для self-contained передачи.
