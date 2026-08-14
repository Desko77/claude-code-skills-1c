"""
Worker для MOSS-Transcribe-Diarize (end-to-end ASR + диаризация).

Запускается как subprocess из transcribe_local.py orchestrator. Работает в отдельном venv:
    <home>/.claude/skills/transcribe/venv-moss   (default)
    либо env MOSS_PYTHON=путь_к_python.exe готового venv.

Использует OpenMOSS-Team/MOSS-Transcribe-Diarize 0.9B (Qwen3-0.6B + Whisper-Medium encoder,
bfloat16 на CUDA). End-to-end: текст + спикеры + таймстампы одним проходом. 50+ языков.

В отличие от sherpa/pyannote (которые только сегментируют спикеров, текст даёт whisper),
MOSS заменяет ОБА шага — поэтому при engine=="moss" orchestrator не запускает whisper,
а берёт текст и спикеры из этого воркера.

Аргументы:
    --input <audio>        путь к аудио/видео (конвертируется ffmpeg в 16kHz mono WAV)
    --out-json <path>      путь сохранения utterances JSON
    --provider cuda|cpu    (default cuda)
    --max-new-tokens N     лимит генерации (default 8192; ~3-5 мин аудио; для длинных поднять)

Вывод JSON: {"utterances": [{"start","end","speaker","text"}],
             "duration": float, "language": str, "rtf": float, "model": str}
             speaker в формате SPEAKER_XX (маппинг из MOSS [S01]→SPEAKER_00 по порядку появления).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def setup_nvidia_dll_path() -> None:
    """Зарегистрировать bin-директории nvidia.* пакетов (CUDA 12 для torch cu128)."""
    venv_root = Path(sys.executable).parent.parent
    nvidia_root = venv_root / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.exists():
        return
    for sub in nvidia_root.iterdir():
        bin_dir = sub / "bin"
        if bin_dir.is_dir():
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(bin_dir))
                except OSError:
                    pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


setup_nvidia_dll_path()

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoProcessor  # noqa: E402

from moss_transcribe_diarize import parse_transcript  # noqa: E402
from moss_transcribe_diarize.inference_utils import (  # noqa: E402
    build_transcription_messages,
    generate_transcription,
    resolve_device,
)

MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"


def ffmpeg_to_wav16k(input_path: Path, out_wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(out_wav)],
        check=True, capture_output=True,
    )


def moss_diarize(args) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio_16k.wav"
        print("[D] ffmpeg → 16k mono wav...", flush=True)
        ffmpeg_to_wav16k(Path(args.input), wav_path)

        samples, sr = sf.read(str(wav_path), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        duration = len(samples) / sr
        print(f"[D] Sample rate: {sr}, длительность: {duration:.1f}с", flush=True)

        device = resolve_device("cuda" if args.provider == "cuda" else "cpu")
        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        print(f"[D] device={device} dtype={dtype}", flush=True)

        print("[D] Загрузка MOSS (первый запуск качает ~2GB)...", flush=True)
        t0 = time.time()
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, trust_remote_code=True, dtype="auto"
        ).to(dtype=dtype).to(device).eval()
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        print(f"[D]   модель за {time.time() - t0:.1f}с", flush=True)

        max_tokens = args.max_new_tokens
        if max_tokens is None:
            max_tokens = max(8192, int(duration * 12))  # ~12 tok/сек с запасом; минимум 8192
            print(f"[D] max_new_tokens=авто: {max_tokens} (длительность {duration:.0f}с)", flush=True)

        messages = build_transcription_messages(str(wav_path))
        print("[D] Генерация (end-to-end ASR + диаризация)...", flush=True)
        t0 = time.time()
        result = generate_transcription(
            model, processor, messages,
            max_new_tokens=max_tokens, do_sample=False,
            device=device, dtype=dtype,
        )
        elapsed = time.time() - t0
        rtf = elapsed / duration if duration else 0.0
        print(f"[D]   за {elapsed:.1f}с (RTF {rtf:.3f})", flush=True)

        segs = list(parse_transcript(result["text"]))
        # Маппинг спикеров в порядке первого появления: [S01]→SPEAKER_00 (консистентно с sherpa)
        spk_map: dict[str, str] = {}
        utterances: list[dict] = []
        for s in segs:
            key = s.speaker
            if key not in spk_map:
                spk_map[key] = f"SPEAKER_{len(spk_map):02d}"
            utterances.append({
                "start": float(s.start),
                "end": float(s.end),
                "speaker": spk_map[key],
                "text": (s.text or "").strip(),
            })
        utterances = [u for u in utterances if u["text"]]
        n_spk = len({u["speaker"] for u in utterances})
        print(f"[D] {len(utterances)} сегментов, {n_spk} спикеров", flush=True)

        # Детект truncation: если последний сегмент заметно короче длительности —
        # генерация упёрлась в max_new_tokens (молча обрезалась).
        if utterances and utterances[-1]["end"] < duration - 30:
            print(f"[D] ВНИМАНИЕ: последний сегмент на {utterances[-1]['end']:.1f}с при длительности "
                  f"{duration:.1f}с — возможна truncation транскрипции "
                  f"(передайте --max-new-tokens больше {max_tokens})", file=sys.stderr)

        payload = {
            "utterances": utterances,
            "duration": duration,
            "language": args.language,
            "rtf": rtf,
            "model": MODEL_ID,
        }
        Path(args.out_json).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"[D]   → {args.out_json}", flush=True)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--provider", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--language", default="ru",
                    help="Метка языка в выходных метаданных (MOSS сама определяет язык речи)")
    ap.add_argument("--max-new-tokens", type=int, default=None,
                    help="Лимит генерации; None=авто по длительности (~12 tok/сек, мин 8192)")
    args = ap.parse_args()
    return moss_diarize(args)


if __name__ == "__main__":
    import traceback
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException:
        log_path = Path.home() / ".claude" / "skills" / "transcribe" / "diarize_moss.crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"argv: {sys.argv}\n")
            f.write(traceback.format_exc())
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
