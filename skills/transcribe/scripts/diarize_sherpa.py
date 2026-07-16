"""
Worker для sherpa-onnx диаризации (CUDA через onnxruntime-gpu).

Запускается как subprocess из transcribe_local.py orchestrator. Работает в отдельном venv:
    <home>/.claude/skills/transcribe/venv-sherpa

Использует:
    - pyannote-segmentation-3.0 в ONNX
    - 3D-Speaker eres2net 200k (multilingual) embedding extractor
    - Спектральная кластеризация (FastClustering) для группировки эмбеддингов

Аргументы:
    --input <audio>     путь к аудио (любой формат, конвертируется через ffmpeg в 16kHz mono WAV)
    --out-json <path>   путь сохранения turns JSON
    --num-speakers N    точное число спикеров (отключает кластеризацию по threshold)
    --threshold T       порог кластеризации (default 0.5, чем меньше — тем больше кластеров)
    --provider cuda|cpu (default cuda)
    --from-turns <json> режим "только отпечатки": диаризация НЕ выполняется, turns берутся из
                        файла (получены другим движком), считаются voiceprints на кластер
                        (eres2net — то же пространство, что и голосовая база)

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

import numpy as np
import soundfile as sf  # noqa: E402
import sherpa_onnx  # noqa: E402


MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
SEG_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB_MODEL = MODELS_DIR / "3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx"


def ffmpeg_to_wav16k(input_path: Path, out_wav: Path) -> None:
    """Конвертировать любое аудио/видео в 16kHz mono PCM_S16LE WAV через ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def compute_voiceprints(samples, sr, turns, provider, max_sec=60.0, min_seg=0.6):
    """Отпечаток голоса на КЛАСТЕР: eres2net-эмбеддинги сегментов SPEAKER_XX, усреднение по длительности.

    Тот же экстрактор, что и в диаризации (переиспользуем модель). На кластер берём самые длинные
    сегменты (чище) суммарно до max_sec, эмбеддинги усредняем с весом по длительности и нормируем
    (для косинусной близости). Возвращает {SPEAKER_XX: [float, ...], ...}.
    """
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL), provider=provider, num_threads=1))
    by_spk: dict[str, list[dict]] = {}
    for t in turns:
        by_spk.setdefault(t["speaker"], []).append(t)

    prints: dict[str, list] = {}
    for spk, segs in by_spk.items():
        segs = sorted(segs, key=lambda s: s["end"] - s["start"], reverse=True)
        embs, weights, total = [], [], 0.0
        for s in segs:
            if total >= max_sec:
                break
            a, b = int(s["start"] * sr), int(s["end"] * sr)
            seg = samples[a:b]
            dur = (b - a) / sr
            if dur < min_seg:
                continue
            stream = ext.create_stream()
            stream.accept_waveform(sr, seg)
            stream.input_finished()
            emb = np.array(ext.compute(stream), dtype=np.float32)
            if emb.size:
                embs.append(emb)
                weights.append(dur)
                total += dur
        if embs:
            v = np.average(np.stack(embs), axis=0, weights=weights)
            v = v / (np.linalg.norm(v) + 1e-8)
            prints[spk] = [round(float(x), 6) for x in v]
            print(f"[D] отпечаток {spk}: {total:.1f}с речи, dim={v.size}", flush=True)
    return prints


def voiceprints_only(args) -> int:
    """Посчитать отпечатки голоса по готовым turns (диаризацию делал другой движок)."""
    if not EMB_MODEL.exists():
        print(f"[D] Не найдена модель эмбеддингов: {EMB_MODEL}", file=sys.stderr)
        return 1
    turns = json.loads(Path(args.from_turns).read_text(encoding="utf-8"))
    print(f"[D] Отпечатки по готовым turns: {len(turns)} turns из {args.from_turns}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio_16k.wav"
        ffmpeg_to_wav16k(Path(args.input), wav_path)
        samples, sr = sf.read(str(wav_path), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        try:
            prints = compute_voiceprints(samples, sr, turns, args.provider)
            Path(args.emit_voiceprints).write_text(json.dumps(prints, ensure_ascii=False), encoding="utf-8")
            print(f"[D]   отпечатки → {args.emit_voiceprints} ({len(prints)} кластеров)", flush=True)
        except Exception as e:
            print(f"[D] отпечатки не посчитаны: {e}", file=sys.stderr, flush=True)
            return 1

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def diarize(args) -> int:
    if not SEG_MODEL.exists():
        print(f"[D] Не найдена модель сегментации: {SEG_MODEL}", file=sys.stderr)
        return 1
    if not EMB_MODEL.exists():
        print(f"[D] Не найдена модель эмбеддингов: {EMB_MODEL}", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    print(f"[D] Файл: {input_path.name}", flush=True)
    print(f"[D] Provider: {args.provider}", flush=True)
    print(f"[D] Сегментация: {SEG_MODEL.name}", flush=True)
    print(f"[D] Эмбеддинги: {EMB_MODEL.name}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio_16k.wav"
        print(f"[D] ffmpeg → {wav_path.name}...", flush=True)
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
        print(f"[D]   → {args.out_json}", flush=True)

        if args.emit_voiceprints:
            print("[D] Считаю отпечатки голоса на кластер...", flush=True)
            try:
                prints = compute_voiceprints(samples, sr, turns, args.provider)
                Path(args.emit_voiceprints).write_text(json.dumps(prints, ensure_ascii=False), encoding="utf-8")
                print(f"[D]   отпечатки → {args.emit_voiceprints} ({len(prints)} кластеров)", flush=True)
            except Exception as e:
                print(f"[D] отпечатки не посчитаны: {e}", file=sys.stderr, flush=True)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--provider", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--emit-voiceprints", default=None, help="Путь: сохранить отпечатки голоса на кластер (JSON)")
    ap.add_argument("--from-turns", default=None, help="Только отпечатки: turns JSON от другого движка")
    args = ap.parse_args()
    if args.from_turns:
        if not args.emit_voiceprints:
            print("[D] --from-turns требует --emit-voiceprints", file=sys.stderr)
            return 1
        return voiceprints_only(args)
    if not args.out_json:
        print("[D] нужен --out-json (либо режим --from-turns)", file=sys.stderr)
        return 1
    return diarize(args)


if __name__ == "__main__":
    import traceback
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException:
        log_path = Path.home() / ".claude" / "skills" / "transcribe" / "diarize_sherpa.crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"argv: {sys.argv}\n")
            f.write(traceback.format_exc())
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
