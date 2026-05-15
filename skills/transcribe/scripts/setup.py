"""
Установка зависимостей скила transcribe.

Что делает:
1. Проверяет системные требования (Python, ffmpeg).
2. Создает venv-whisper и ставит:
   - faster-whisper + ctranslate2-CUDA + av (для локальной транскрипции аудио)
   - google-genai + python-dotenv (для Gemini API: видео + analyze-ui)
3. Создает venv-sherpa и ставит sherpa_onnx (GPU CUDA) + onnxruntime-gpu + soundfile
4. Скачивает модели диаризации в models/:
   - sherpa-onnx-pyannote-segmentation-3-0 (~7 МБ)
   - 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx (~40 МБ)
5. Создает шаблон .env (без записи реальных ключей).

Запуск:
    python scripts/setup.py
    python scripts/setup.py --skip-models       # только venv'ы
    python scripts/setup.py --skip-sherpa       # без диаризации (только транскрипция)
    python scripts/setup.py --skip-gemini       # без Gemini (только локальный движок)
    python scripts/setup.py --skip-whisper      # пропустить пересоздание venv-whisper
    python scripts/setup.py --with-pyannote     # доп. поставить pyannote.audio 4.x (требует HF_TOKEN)

Требования:
    - Python 3.10+ (рекомендуется 3.12)
    - NVIDIA GPU + CUDA 12 + cuDNN 9 (для GPU режима)
    - ffmpeg + ffprobe в PATH
    - Windows x64 или Linux x64

После установки заполнить ~/.claude/skills/transcribe/.env:
    GEMINI_API_KEY=<ключ с https://aistudio.google.com/apikey>
    # Опционально, только если установлен pyannote 4.x:
    # HF_TOKEN=<read-токен https://huggingface.co/settings/tokens>
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
VENV_WHISPER = SKILL_ROOT / "venv-whisper"
VENV_SHERPA = SKILL_ROOT / "venv-sherpa"
MODELS_DIR = SKILL_ROOT / "models"
ENV_FILE = SKILL_ROOT / ".env"

IS_WIN = os.name == "nt"
VENV_BIN = "Scripts" if IS_WIN else "bin"
PY_EXE = "python.exe" if IS_WIN else "python"

MODEL_URLS = {
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
        "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx",
}

WHISPER_PACKAGES = [
    "faster-whisper>=1.0",
    "ctranslate2>=4.5",
    "av>=11",
    "huggingface-hub",
    "numpy<3",
    "nvidia-cublas-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cuda-nvrtc-cu12",
]

GEMINI_PACKAGES = [
    "google-genai",
    "python-dotenv",
]

PYANNOTE_PACKAGES = [
    "torch",
    "pyannote.audio>=4.0",
]

SHERPA_PACKAGES = [
    "onnxruntime-gpu>=1.18",
    "soundfile>=0.12",
    "numpy<2",
    "nvidia-cublas-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cuda-nvrtc-cu12",
    "nvidia-cufft-cu12",
    "nvidia-nvjitlink-cu12",
]

ENV_TEMPLATE = """# Скил transcribe - ключи API
# Получите ключ Gemini на https://aistudio.google.com/apikey
GEMINI_API_KEY=

# HF_TOKEN нужен ТОЛЬКО если установлен pyannote 4.x как fallback диаризация.
# Sherpa-onnx (default) не использует gated модели.
# Токен на https://huggingface.co/settings/tokens (read). Принять условия:
# pyannote/speaker-diarization-3.1, pyannote/segmentation-3.0
# HF_TOKEN=
"""


def step(msg: str) -> None:
    print(f"\n{'=' * 70}\n{msg}\n{'=' * 70}", flush=True)


def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def run(cmd: list[str], **kwargs) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, **kwargs).returncode


def check_requirements() -> bool:
    step("Проверка требований")
    ok = True
    py_version = sys.version_info
    if py_version < (3, 10):
        info(f"FAIL: Python {py_version.major}.{py_version.minor} < 3.10")
        ok = False
    else:
        info(f"OK:   Python {py_version.major}.{py_version.minor}.{py_version.micro}")

    if not shutil.which("ffmpeg"):
        info("FAIL: ffmpeg не найден в PATH")
        info("      Скачайте с https://www.gyan.dev/ffmpeg/builds/ (Windows) или apt install ffmpeg (Linux)")
        ok = False
    else:
        info(f"OK:   ffmpeg в {shutil.which('ffmpeg')}")

    if not shutil.which("ffprobe"):
        info("WARN: ffprobe не найден (нужен для разбивки видео >1ч в Gemini-режиме)")

    info(f"Платформа: {'Windows' if IS_WIN else sys.platform}")
    return ok


def create_venv(venv_path: Path) -> Path:
    py = venv_path / VENV_BIN / PY_EXE
    if py.exists():
        info(f"venv уже существует: {venv_path}")
        return py
    info(f"Создание venv: {venv_path}")
    rc = run([sys.executable, "-m", "venv", str(venv_path)])
    if rc != 0:
        raise RuntimeError(f"Не удалось создать venv {venv_path}")
    rc = run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    if rc != 0:
        raise RuntimeError("Не удалось обновить pip")
    return py


def pip_install(py: Path, packages: list[str], extra_args: list[str] | None = None) -> None:
    cmd = [str(py), "-m", "pip", "install"]
    if extra_args:
        cmd += extra_args
    cmd += packages
    rc = run(cmd)
    if rc != 0:
        raise RuntimeError(f"pip install упал на: {packages}")


def install_whisper(skip: bool, skip_gemini: bool, with_pyannote: bool) -> None:
    step("venv-whisper: faster-whisper + Gemini + опц. pyannote")
    if skip:
        info("Пропускаем по флагу --skip-whisper")
        return
    py = create_venv(VENV_WHISPER)
    pip_install(py, WHISPER_PACKAGES)
    if not skip_gemini:
        info("Установка Gemini-зависимостей (google-genai, python-dotenv)")
        pip_install(py, GEMINI_PACKAGES)
    if with_pyannote:
        info("Установка pyannote.audio 4.x (требует HF_TOKEN в .env при использовании)")
        pip_install(py, PYANNOTE_PACKAGES)
    info("OK")


def install_sherpa_gpu(py: Path) -> None:
    info("Установка sherpa_onnx (GPU/CUDA)...")
    extra_index = "https://k2-fsa.github.io/sherpa/onnx/cuda.html"
    try:
        rc = run([str(py), "-m", "pip", "install", "sherpa-onnx", "-f", extra_index])
        if rc == 0:
            info("sherpa_onnx установлен")
            return
    except Exception as e:
        info(f"WARN: {e}")
    info("ВНИМАНИЕ: автоматическая установка sherpa_onnx с CUDA не удалась.")
    info("Установите вручную:")
    info(f"  {py} -m pip install sherpa-onnx")
    info("Или скачайте GPU wheel с https://huggingface.co/csukuangfj2/sherpa-onnx-wheels")
    info(f"и установите:  {py} -m pip install <путь-к-wheel.whl>")


def install_sherpa(skip: bool) -> None:
    step("venv-sherpa: sherpa_onnx + onnxruntime-gpu")
    if skip:
        info("Пропускаем по флагу --skip-sherpa")
        return
    py = create_venv(VENV_SHERPA)
    pip_install(py, SHERPA_PACKAGES)
    install_sherpa_gpu(py)
    info("OK")


def download_file(url: str, dest: Path) -> None:
    if dest.exists():
        info(f"Уже скачан: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    info(f"Скачивание {dest.name}")
    info(f"  url: {url}")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 1 << 16
            last_pct = -1
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
                if total:
                    pct = int(100 * downloaded / total)
                    if pct >= last_pct + 10:
                        last_pct = pct
                        info(f"  [{pct:3d}%] {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB")
        tmp.rename(dest)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Не удалось скачать {url}: {e}") from e


def extract_segmentation_archive() -> None:
    archive = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
    target_dir = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0"
    if (target_dir / "model.onnx").exists():
        info(f"Уже распакован: {target_dir}")
        return
    info(f"Распаковка {archive.name}")
    with tarfile.open(archive, "r:bz2") as tf:
        tf.extractall(MODELS_DIR)
    if not (target_dir / "model.onnx").exists():
        raise RuntimeError(f"После распаковки нет {target_dir / 'model.onnx'}")


def download_models(skip: bool) -> None:
    step("Модели диаризации")
    if skip:
        info("Пропускаем по флагу --skip-models")
        return
    MODELS_DIR.mkdir(exist_ok=True)
    for fname, url in MODEL_URLS.items():
        download_file(url, MODELS_DIR / fname)
    extract_segmentation_archive()
    info("OK")


def create_env_template(skip_gemini: bool) -> None:
    step("Шаблон .env")
    if ENV_FILE.exists():
        info(f"Уже существует: {ENV_FILE}. НЕ перезаписываем.")
        return
    ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
    info(f"Создан: {ENV_FILE}")
    if not skip_gemini:
        info("Заполните GEMINI_API_KEY=<ключ> (нужен для Gemini-режима — видео).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Установка скила transcribe")
    ap.add_argument("--skip-whisper", action="store_true", help="Не пересоздавать venv-whisper")
    ap.add_argument("--skip-sherpa", action="store_true", help="Не ставить sherpa (без диаризации)")
    ap.add_argument("--skip-models", action="store_true", help="Не скачивать модели")
    ap.add_argument("--skip-gemini", action="store_true", help="Не ставить google-genai (без Gemini)")
    ap.add_argument("--with-pyannote", action="store_true",
                    help="Доп. поставить pyannote.audio 4.x как альтернативу sherpa-onnx (требует HF_TOKEN)")
    args = ap.parse_args()

    if not check_requirements():
        print("\nПроверка требований не пройдена. Исправьте и повторите.", file=sys.stderr)
        return 1

    try:
        install_whisper(args.skip_whisper, args.skip_gemini, args.with_pyannote)
        install_sherpa(args.skip_sherpa)
        download_models(args.skip_models)
        create_env_template(args.skip_gemini)
    except Exception as e:
        print(f"\nОшибка установки: {e}", file=sys.stderr)
        return 1

    step("Готово")
    info(f"Скил: {SKILL_ROOT}")
    info(f"venv-whisper: {VENV_WHISPER}")
    info(f"venv-sherpa:  {VENV_SHERPA}")
    info(f"models:       {MODELS_DIR}")
    info(f".env:         {ENV_FILE}")
    info("")
    info("Проверка (аудио, локально):")
    py = VENV_WHISPER / VENV_BIN / PY_EXE
    info(f"  {py} {SKILL_ROOT / 'scripts' / 'transcribe_local.py'} <audio.mp3> --diarize")
    info("")
    info("Проверка (видео, Gemini):")
    info(f"  {py} {SKILL_ROOT / 'scripts' / 'transcribe.py'} <video.mp4>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
