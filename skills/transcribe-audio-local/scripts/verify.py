"""
Smoke-тест после установки скила transcribe-audio-local.

Что проверяет:
1. venv-whisper существует и в нём установлен faster-whisper
2. venv-sherpa существует и в нём установлены sherpa_onnx + onnxruntime
3. Модели sherpa-onnx и 3D-Speaker лежат в models/
4. ffmpeg доступен
5. (опционально) тестовый прогон на коротком сгенерированном WAV

Запуск:
    python scripts/verify.py             # все проверки кроме прогона
    python scripts/verify.py --full      # + тестовый прогон (создаёт 3-сек тон и транскрибирует)

Выход: 0 если все проверки прошли, 1 если есть FAIL.
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

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""), flush=True)


def check_venv(name: str, py_exe: Path, test_import: str) -> bool:
    if not py_exe.exists():
        check(f"venv-{name}", False, f"не найден: {py_exe}")
        return False
    check(f"venv-{name}", True, str(py_exe))
    try:
        result = subprocess.run(
            [str(py_exe), "-c", test_import],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            check(f"venv-{name} imports", True, result.stdout.strip())
            return True
        check(f"venv-{name} imports", False, result.stderr.strip().splitlines()[-1] if result.stderr else "ошибка импорта")
        return False
    except (subprocess.SubprocessError, OSError) as e:
        check(f"venv-{name} imports", False, str(e))
        return False


def create_silent_wav(path: Path, duration_sec: float = 3.0, sample_rate: int = 16000) -> None:
    n_samples = int(duration_sec * sample_rate)
    silence = b"\x00\x00" * n_samples
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(silence)


def run_transcribe_test() -> bool:
    print("\n  Тестовый прогон транскрипции на 3-сек silent WAV...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "test.wav"
        create_silent_wav(wav_path)
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        try:
            result = subprocess.run(
                [str(VENV_WHISPER_PY),
                 str(SKILL_ROOT / "scripts" / "transcribe.py"),
                 str(wav_path),
                 "--output-dir", str(out_dir),
                 "--model", "openai/whisper-tiny",
                 "--compute-type", "int8"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                check("smoke-test транскрипция", True, "транскрибация silent WAV прошла")
                return True
            check("smoke-test транскрипция", False, f"rc={result.returncode}: {result.stderr[-200:]}")
            return False
        except subprocess.TimeoutExpired:
            check("smoke-test транскрипция", False, "таймаут (>3 мин)")
            return False
        except OSError as e:
            check("smoke-test транскрипция", False, str(e))
            return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-тест скила transcribe-audio-local")
    ap.add_argument("--full", action="store_true", help="Включить тестовый прогон транскрипции (~1-2 мин)")
    args = ap.parse_args()

    print(f"Скил: {SKILL_ROOT}\n", flush=True)
    print("Проверка установки:", flush=True)

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        check("ffmpeg", True, f"в PATH: {ffmpeg_path}")
    else:
        # Может быть установлен через static-ffmpeg в venv-whisper
        try:
            r = subprocess.run(
                [str(VENV_WHISPER_PY), "-c",
                 "from static_ffmpeg import add_paths; add_paths(); "
                 "import shutil; print(shutil.which('ffmpeg') or 'NOT_FOUND')"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0 and "NOT_FOUND" not in r.stdout:
                check("ffmpeg", True, f"через static-ffmpeg в venv-whisper: {r.stdout.strip()}")
            else:
                check("ffmpeg", False, "не найден ни в PATH, ни через static-ffmpeg")
        except (subprocess.SubprocessError, OSError) as e:
            check("ffmpeg", False, f"не найден в PATH, static-ffmpeg тоже недоступен: {e}")

    check_venv("whisper", VENV_WHISPER_PY,
               "import faster_whisper; print('faster-whisper', faster_whisper.__version__)")

    check_venv("sherpa", VENV_SHERPA_PY,
               "import sherpa_onnx, onnxruntime; print('sherpa_onnx', sherpa_onnx.__version__, '| onnxruntime', onnxruntime.__version__)")

    check("модель сегментации (pyannote-3.0)", SEG_MODEL.exists(),
          f"{SEG_MODEL.stat().st_size / 1e6:.1f} MB" if SEG_MODEL.exists() else "не найдена")

    check("модель эмбеддингов (3D-Speaker)", EMB_MODEL.exists(),
          f"{EMB_MODEL.stat().st_size / 1e6:.1f} MB" if EMB_MODEL.exists() else "не найдена")

    if args.full and VENV_WHISPER_PY.exists():
        run_transcribe_test()

    print("", flush=True)
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"FAIL: {len(failed)} проверок не прошли: {', '.join(failed)}", flush=True)
        print("Запустите 'python scripts/setup.py' для (пере)установки.", flush=True)
        return 1
    print(f"OK: все {len(results)} проверок прошли. Скил готов к работе.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
