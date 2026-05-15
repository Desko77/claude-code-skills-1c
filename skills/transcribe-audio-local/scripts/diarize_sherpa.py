"""
Worker для sherpa-onnx диаризации (CUDA через onnxruntime-gpu).

Запускается как subprocess из transcribe.py orchestrator. Работает в отдельном venv:
    <skill_root>/venv-sherpa

Использует:
    - pyannote-segmentation-3.0 в ONNX
    - 3D-Speaker eres2net 200k (multilingual) embedding extractor
    - Спектральная кластеризация (FastClustering) для группировки эмбеддингов

Аргументы:
    --input <audio>     путь к аудио (любой формат, конвертируется через ffmpeg в 16kHz mono WAV)
    --out-json <path>   путь сохранения turns JSON
    --num-speakers N    точное число спикеров (отключает кластеризацию по threshold)
    --threshold T       порог кластеризации (default 0.5, чем меньше - тем больше кластеров)
    --provider cuda|cpu (default cuda)

Вывод JSON: list[{"start": float, "end": float, "speaker": "SPEAKER_XX"}].
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


SKILL_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = SKILL_ROOT / "models"
SEG_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB_MODEL = MODELS_DIR / "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx"


def setup_nvidia_dll_path() -> None:
    """Зарегистрировать bin-директории nvidia.* пакетов (CUDA 12 для onnxruntime-gpu)."""
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

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import sherpa_onnx  # noqa: E402


def ffmpeg_to_wav16k(input_path: Path, out_wav: Path) -> None:
    """Конвертировать любое аудио в 16kHz mono PCM_S16LE WAV через ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def diarize(args) -> int:
    if not SEG_MODEL.exists():
        print(f"[D] Не найдена модель сегментации: {SEG_MODEL}", file=sys.stderr)
        print(f"[D] Запустите установку: python scripts/setup.py", file=sys.stderr)
        return 1
    if not EMB_MODEL.exists():
        print(f"[D] Не найдена модель эмбеддингов: {EMB_MODEL}", file=sys.stderr)
        print(f"[D] Запустите установку: python scripts/setup.py", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    print(f"[D] Файл: {input_path.name}", flush=True)
    print(f"[D] Provider: {args.provider}", flush=True)
    print(f"[D] Сегментация: {SEG_MODEL.name}", flush=True)
    print(f"[D] Эмбеддинги: {EMB_MODEL.name}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio_16k.wav"
        print(f"[D] ffmpeg -> {wav_path.name}...", flush=True)
        t0 = time.time()
        ffmpeg_to_wav16k(input_path, wav_path)
        print(f"[D]   ffmpeg готов за {time.time() - t0:.1f}с", flush=True)

        samples, sr = sf.read(str(wav_path), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        print(f"[D] Sample rate: {sr}, длительность: {len(samples) / sr:.1f}с", flush=True)

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(SEG_MODEL),
                ),
                provider=args.provider,
                num_threads=1,
                debug=False,
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(EMB_MODEL),
                provider=args.provider,
                num_threads=1,
                debug=False,
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=args.num_speakers if args.num_speakers else -1,
                threshold=args.threshold,
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )

        if not config.validate():
            print("[D] Конфигурация невалидна", file=sys.stderr)
            return 1

        print("[D] Загрузка моделей...", flush=True)
        t0 = time.time()
        sd = sherpa_onnx.OfflineSpeakerDiarization(config)
        print(f"[D]   Готово за {time.time() - t0:.1f}с", flush=True)

        print("[D] Диаризация...", flush=True)
        t0 = time.time()
        last_pct = -1

        def progress(num_processed: int, num_total: int) -> int:
            nonlocal last_pct
            pct = int(100 * num_processed / max(num_total, 1))
            if pct >= last_pct + 5:
                last_pct = pct
                print(f"[D]   [{pct:3d}%]", flush=True)
            return 0

        result = sd.process(samples, callback=progress).sort_by_start_time()
        elapsed = time.time() - t0

        turns: list[dict] = []
        for r in result:
            turns.append({
                "start": float(r.start),
                "end": float(r.end),
                "speaker": f"SPEAKER_{int(r.speaker):02d}",
            })

        speakers_set = sorted({t["speaker"] for t in turns})
        rtf = elapsed / (len(samples) / sr) if len(samples) > 0 else 0
        print(f"[D] Готово за {elapsed:.1f}с (RTF {rtf:.3f}, {len(turns)} turns, {len(speakers_set)} спикеров)", flush=True)

        Path(args.out_json).write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
        print(f"[D]   -> {args.out_json}", flush=True)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--provider", default="cuda", choices=["cuda", "cpu"])
    args = ap.parse_args()
    return diarize(args)


if __name__ == "__main__":
    import traceback
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException:
        log_path = SKILL_ROOT / "diarize_sherpa.crash.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"argv: {sys.argv}\n")
            f.write(traceback.format_exc())
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
