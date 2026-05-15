"""
Smoke-тест после установки скила transcribe.

Что проверяет:
1. venv-whisper существует и в нём установлены faster-whisper + google-genai
2. venv-sherpa существует и в нём установлены sherpa_onnx + onnxruntime
3. Модели sherpa-onnx и 3D-Speaker лежат в models/
4. ffmpeg + ffprobe доступны
5. .env существует и GEMINI_API_KEY заполнен (предупреждение если нет)
6. (опционально) тестовый прогон локальной транскрипции на коротком WAV

Запуск:
    python scripts/verify.py             # все проверки кроме прогона
    python scripts/verify.py --full      # + тестовый прогон (создаёт 3-сек тон и транскрибирует)

Выход: 0 если все проверки прошли (предупреждения не считаются), 1 если FAIL.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = "Scripts" if os.name == "nt" else "bin"
PY_EXE = "python.exe" if os.name == "nt" else "python"

VENV_WHISPER_PY = SKILL_ROOT / "venv-whisper" / VENV_BIN / PY_EXE
VENV_SHERPA_PY = SKILL_ROOT / "venv-sherpa" / VENV_BIN / PY_EXE
MODELS_DIR = SKILL_ROOT / "models"
SEG_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB_MODEL = MODELS_DIR / "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx"
ENV_FILE = SKILL_ROOT / ".env"

results: list[tuple[str, str, str]] = []


def check(name: str, level: str, detail: str = "") -> None:
    """level: OK | FAIL | WARN"""
    results.append((name, level, detail))
    print(f"  [{level:4}] {name}" + (f": {detail}" if detail else ""), flush=True)


def check_venv(name: str, py_exe: Path, test_import: str) -> bool:
    if not py_exe.exists():
        check(f"venv-{name}", "FAIL", f"не найден: {py_exe}")
        return False
    check(f"venv-{name}", "OK", str(py_exe))
    try:
        result = subprocess.run(
            [str(py_exe), "-c", test_import],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            check(f"venv-{name} imports", "OK", result.stdout.strip())
            return True
        last_line = result.stderr.strip().splitlines()[-1] if result.stderr else "ошибка импорта"
        check(f"venv-{name} imports", "FAIL", last_line)
        return False
    except (subprocess.SubprocessError, OSError) as e:
        check(f"venv-{name} imports", "FAIL", str(e))
        return False


def check_env_file() -> None:
    if not ENV_FILE.exists():
        check(".env", "WARN", "не найден (для Gemini-режима нужен GEMINI_API_KEY)")
        return
    content = ENV_FILE.read_text(encoding="utf-8", errors="replace")
    has_gemini = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY=") and len(line) > len("GEMINI_API_KEY="):
            value = line[len("GEMINI_API_KEY="):].strip().strip('"').strip("'")
            if value and value != "<ключ":
                has_gemini = True
                break
    if has_gemini:
        check(".env GEMINI_API_KEY", "OK", "заполнен")
    else:
        check(".env GEMINI_API_KEY", "WARN", "пустой - Gemini-режим (видео) работать не будет")


def create_silent_wav(path: Path, duration_sec: float = 3.0, sample_rate: int = 16000) -> None:
    n_samples = int(duration_sec * sample_rate)
    silence = b"\x00\x00" * n_samples
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(silence)


def run_transcribe_test() -> bool:
    print("\n  Тестовый прогон локальной транскрипции на 3-сек silent WAV...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "test.wav"
        create_silent_wav(wav_path)
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        try:
            result = subprocess.run(
                [str(VENV_WHISPER_PY),
                 str(SKILL_ROOT / "scripts" / "transcribe_local.py"),
                 str(wav_path),
                 "--output-dir", str(out_dir),
                 "--model", "openai/whisper-tiny",
                 "--compute-type", "int8"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                check("smoke-test транскрипция", "OK", "transcribe_local прошёл")
                return True
            check("smoke-test транскрипция", "FAIL", f"rc={result.returncode}: {result.stderr[-200:]}")
            return False
        except subprocess.TimeoutExpired:
            check("smoke-test транскрипция", "FAIL", "таймаут (>3 мин)")
            return False
        except OSError as e:
            check("smoke-test транскрипция", "FAIL", str(e))
            return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-тест скила transcribe")
    ap.add_argument("--full", action="store_true", help="Включить тестовый прогон локальной транскрипции (~1-2 мин)")
    args = ap.parse_args()

    print(f"Скил: {SKILL_ROOT}\n", flush=True)
    print("Проверка установки:", flush=True)

    check("ffmpeg в PATH", "OK" if shutil.which("ffmpeg") else "FAIL",
          shutil.which("ffmpeg") or "не найден")

    check("ffprobe в PATH", "OK" if shutil.which("ffprobe") else "WARN",
          shutil.which("ffprobe") or "не найден (нужен для разбивки видео >1ч)")

    check_venv("whisper", VENV_WHISPER_PY,
               "import faster_whisper; "
               "try:\n  import google.genai as g\n  gv = 'OK'\nexcept ImportError:\n  gv = 'MISSING'\n"
               "print(f'faster-whisper {faster_whisper.__version__} | google-genai {gv}')")

    check_venv("sherpa", VENV_SHERPA_PY,
               "import sherpa_onnx, onnxruntime; print('sherpa_onnx', sherpa_onnx.__version__, '| onnxruntime', onnxruntime.__version__)")

    check("модель сегментации (pyannote-3.0)",
          "OK" if SEG_MODEL.exists() else "FAIL",
          f"{SEG_MODEL.stat().st_size / 1e6:.1f} MB" if SEG_MODEL.exists() else "не найдена")

    check("модель эмбеддингов (3D-Speaker)",
          "OK" if EMB_MODEL.exists() else "FAIL",
          f"{EMB_MODEL.stat().st_size / 1e6:.1f} MB" if EMB_MODEL.exists() else "не найдена")

    check_env_file()

    if args.full and VENV_WHISPER_PY.exists():
        run_transcribe_test()

    print("", flush=True)
    failed = [name for name, lvl, _ in results if lvl == "FAIL"]
    warned = [name for name, lvl, _ in results if lvl == "WARN"]
    if failed:
        print(f"FAIL: {len(failed)} проверок не прошли: {', '.join(failed)}", flush=True)
        print("Запустите 'python scripts/setup.py' для (пере)установки.", flush=True)
        return 1
    if warned:
        print(f"OK с предупреждениями: {len(warned)} ({', '.join(warned)})", flush=True)
    else:
        print(f"OK: все {len(results)} проверок прошли. Скил готов к работе.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
