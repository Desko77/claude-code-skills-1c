"""
Установка зависимостей скила transcribe-audio-local.

Что делает:
1. Проверяет системные требования (Python, ffmpeg).
2. Создает venv-whisper и ставит faster-whisper + ctranslate2 (CUDA) + av.
3. Создает venv-sherpa и ставит sherpa_onnx (GPU CUDA) + onnxruntime-gpu + soundfile.
4. Скачивает модели диаризации в models/:
   - sherpa-onnx-pyannote-segmentation-3-0 (~7 MB)
   - 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx (~40 MB)

Запуск:
    python scripts/setup.py
    python scripts/setup.py --skip-models       # только venv'ы
    python scripts/setup.py --skip-sherpa       # без диаризации
    python scripts/setup.py --skip-whisper      # пропустить пересоздание venv-whisper

Требования:
    - Python 3.10+ (рекомендуется 3.12)
    - NVIDIA GPU + CUDA 12 + cuDNN 9 (для GPU режима)
    - ffmpeg в PATH
    - Windows x64 или Linux x64
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

IS_WIN = os.name == "nt"
VENV_BIN = "Scripts" if IS_WIN else "bin"
PY_EXE = "python.exe" if IS_WIN else "python"

# URL моделей (k2-fsa официальные релизы)
MODEL_URLS = {
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
        "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx",
}

# Пакеты для venv-whisper (faster-whisper + GPU stack)
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

# Пакеты для venv-sherpa
# sherpa_onnx CUDA wheel ставится отдельно по индексу k2-fsa (см. install_sherpa_gpu)
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

    if IS_WIN:
        info("Платформа: Windows")
    else:
        info(f"Платформа: {sys.platform}")

    return ok


def create_venv(venv_path: Path) -> Path:
    """Создать venv если его нет, вернуть путь к python внутри."""
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


def install_whisper(skip: bool) -> None:
    step("venv-whisper: faster-whisper + CUDA stack")
    if skip:
        info("Пропускаем по флагу --skip-whisper")
        return
    py = create_venv(VENV_WHISPER)
    pip_install(py, WHISPER_PACKAGES)
    info("OK")


def install_sherpa_gpu(py: Path) -> None:
    """Установить sherpa_onnx с GPU поддержкой.

    Сначала пробуем с PyPI с extra-index-url от k2-fsa (содержит CUDA wheels).
    Если не вышло - инструкция пользователю.
    """
    info("Установка sherpa_onnx (GPU/CUDA)...")
    extra_index = "https://k2-fsa.github.io/sherpa/onnx/cuda.html"
    try:
        cmd = [str(py), "-m", "pip", "install", "sherpa-onnx",
               "-f", extra_index]
        rc = run(cmd)
        if rc == 0:
            info("sherpa_onnx установлен (попробуйте проверить наличие CUDA: см. README)")
            return
    except Exception as e:
        info(f"WARN: {e}")

    info("ВНИМАНИЕ: автоматическая установка sherpa_onnx с CUDA не удалась.")
    info("Установите вручную:")
    info(f"  {py} -m pip install sherpa-onnx")
    info("Или скачайте GPU wheel с https://huggingface.co/csukuangfj2/sherpa-onnx-wheels")
    info("и установите:")
    info(f"  {py} -m pip install <путь-к-wheel.whl>")


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
    """Распаковать sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 в models/."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Установка скила transcribe-audio-local")
    ap.add_argument("--skip-whisper", action="store_true", help="Не пересоздавать venv-whisper")
    ap.add_argument("--skip-sherpa", action="store_true", help="Не ставить sherpa (без диаризации)")
    ap.add_argument("--skip-models", action="store_true", help="Не скачивать модели")
    args = ap.parse_args()

    if not check_requirements():
        print("\nПроверка требований не пройдена. Исправьте и повторите.", file=sys.stderr)
        return 1

    try:
        install_whisper(args.skip_whisper)
        install_sherpa(args.skip_sherpa)
        download_models(args.skip_models)
    except Exception as e:
        print(f"\nОшибка установки: {e}", file=sys.stderr)
        return 1

    step("Готово")
    info(f"Скил: {SKILL_ROOT}")
    info(f"venv-whisper: {VENV_WHISPER}")
    info(f"venv-sherpa:  {VENV_SHERPA}")
    info(f"models:       {MODELS_DIR}")
    info("")
    info("Проверка:")
    info(f"  python {SKILL_ROOT / 'scripts' / 'transcribe.py'} <audio.mp3>")
    info(f"  python {SKILL_ROOT / 'scripts' / 'transcribe.py'} <audio.mp3> --diarize")
    return 0


if __name__ == "__main__":
    sys.exit(main())
