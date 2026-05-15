"""
Локальная транскрипция аудио/видео через faster-whisper (CUDA) + опц. диаризация (pyannote).

Архитектура: orchestrator + 2 subprocess (изоляция CUDA-DLL ctranslate2 vs torch).
При --diarize транскрипция и диаризация запускаются параллельно.

Использование:
    python transcribe_local.py <input_path> [--output-dir DIR] [--model MODEL]
                               [--language ru] [--diarize]
                               [--num-speakers N] [--min-speakers N] [--max-speakers N]

Зависимости:
    Whisper venv: faster-whisper, ctranslate2-CUDA, ffmpeg.
    Для --diarize: torch (CUDA), pyannote.audio>=3.1, HF_TOKEN в env.

Файлы вывода:
    <base> - транскрипция.md       Markdown c таймкодами по сегментам (без спикеров)
    <base> - транскрипция.txt      Plain text
    <base> - со спикерами.md       MD c [Спикер, MM:SS] (только при --diarize)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Подключаем ffmpeg из static-ffmpeg если есть (subprocess наследует PATH).
try:
    from static_ffmpeg import add_paths as _sff_add_paths
    _sff_add_paths()
except ImportError:
    pass


def _setup_cuda_dll_path() -> None:
    """Добавить bin-директории nvidia.* пакетов в PATH и DLL search (Windows, CUDA 12)."""
    for name in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime", "nvidia.cuda_nvrtc"):
        try:
            mod = __import__(name, fromlist=[""])
            bin_dir = os.path.join(mod.__path__[0], "bin")
            if os.path.isdir(bin_dir):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(bin_dir)
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        except ImportError:
            pass


def _load_dotenv() -> None:
    """Подгрузить переменные из ~/.claude/skills/transcribe/.env (HF_TOKEN, GEMINI_API_KEY и т.п.)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def format_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


# =====================================================================
# WORKER: транскрипция (запускается как subprocess)
# =====================================================================

def worker_transcribe(args) -> int:
    _setup_cuda_dll_path()
    from faster_whisper import WhisperModel  # noqa

    print(f"[T] Модель: {args.model} ({args.device}/{args.compute_type})", flush=True)
    t0 = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"[T] Модель загружена за {time.time() - t0:.1f}с", flush=True)

    print(f"[T] Транскрипция (word_timestamps={args.need_words})...", flush=True)
    t0 = time.time()
    segments_iter, info = model.transcribe(
        args.input,
        language=args.language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
        word_timestamps=args.need_words,
    )
    print(f"[T] Язык: {info.language} (p={info.language_probability:.2f}) длительность {info.duration:.1f}с", flush=True)

    segments: list[dict] = []
    last_pct = -1
    for seg in segments_iter:
        words = []
        if args.need_words and seg.words:
            for w in seg.words:
                words.append({"start": float(w.start), "end": float(w.end), "text": w.word})
        segments.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text.strip(),
            "words": words,
        })
        pct = int(100 * seg.end / max(info.duration, 1))
        if pct >= last_pct + 5:
            last_pct = pct
            print(f"[T] [{pct:3d}%] {format_ts(seg.start)}: {seg.text.strip()[:80]}", flush=True)

    info_dict = {
        "language": info.language,
        "language_probability": float(info.language_probability),
        "duration": float(info.duration),
    }

    out = {"segments": segments, "info": info_dict}
    Path(args.out_json).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[T] Готово за {time.time() - t0:.1f}с ({len(segments)} сегментов) → {args.out_json}", flush=True)
    # Обходим segfault в нативном cleanup ctranslate2 на Windows
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


# =====================================================================
# WORKER: диаризация (запускается как subprocess)
# =====================================================================

def worker_diarize(args) -> int:
    _setup_cuda_dll_path()
    _load_dotenv()

    import torch
    from pyannote.audio import Pipeline

    if args.tf32:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        try:
            from pyannote.audio.utils import reproducibility as _reprod
            if hasattr(_reprod, "fix_reproducibility"):
                _reprod.fix_reproducibility = lambda *a, **k: None
            for name in ("disable_tf32", "_disable_tf32"):
                if hasattr(_reprod, name):
                    setattr(_reprod, name, lambda *a, **k: None)
        except Exception:
            pass
        print("[D] TF32 включен + monkeypatch reproducibility (быстрее, чуть менее воспроизводимо)", flush=True)

    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not hf_token:
        print("[D] HF_TOKEN не задан в env", file=sys.stderr)
        return 2

    print("[D] Загрузка pipeline pyannote/speaker-diarization-3.1...", flush=True)
    t0 = time.time()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        print("[D] pipeline на CUDA", flush=True)
    else:
        print("[D] WARN: CUDA недоступна, диаризация на CPU очень медленная", flush=True)
    print(f"[D] Pipeline загружен за {time.time() - t0:.1f}с", flush=True)

    print("[D] Диаризация...", flush=True)
    t0 = time.time()
    kwargs = {}
    if args.num_speakers is not None:
        kwargs["num_speakers"] = args.num_speakers
    if args.min_speakers is not None:
        kwargs["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        kwargs["max_speakers"] = args.max_speakers

    result = pipeline(args.input, **kwargs)

    annotation = getattr(result, "exclusive_speaker_diarization", None) \
        or getattr(result, "speaker_diarization", None) \
        or result

    turns: list[dict] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    turns.sort(key=lambda t: t["start"])

    speakers_set = sorted({t["speaker"] for t in turns})
    Path(args.out_json).write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    print(f"[D] Готово за {time.time() - t0:.1f}с ({len(turns)} turns, {len(speakers_set)} спикеров) → {args.out_json}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


# =====================================================================
# MERGE / OUTPUT
# =====================================================================

def assign_speaker(midpoint: float, turns: list[dict]) -> str:
    for t in turns:
        if t["start"] <= midpoint <= t["end"]:
            return t["speaker"]
    if not turns:
        return "UNKNOWN"
    nearest = min(turns, key=lambda t: min(abs(t["start"] - midpoint), abs(t["end"] - midpoint)))
    return nearest["speaker"]


def smooth_word_speakers(words: list[dict], min_run: float = 1.2) -> None:
    """Сгладить короткие пробивки спикера в словах: если короткий run X между двумя длинными run Y,
    переаттрибутировать слова run X на спикера Y. Изменяет words на месте.
    """
    if not words:
        return
    runs: list[tuple[int, int, str, float]] = []
    i = 0
    n = len(words)
    while i < n:
        j = i
        spk = words[i]["speaker"]
        while j + 1 < n and words[j + 1]["speaker"] == spk:
            j += 1
        duration = words[j]["end"] - words[i]["start"]
        runs.append((i, j, spk, duration))
        i = j + 1

    changed = True
    while changed:
        changed = False
        for k in range(1, len(runs) - 1):
            ri, rj, rspk, rdur = runs[k]
            li, lj, lspk, ldur = runs[k - 1]
            ni, nj, nspk, ndur = runs[k + 1]
            if rdur < min_run and lspk == nspk and lspk != rspk:
                for x in range(ri, rj + 1):
                    words[x]["speaker"] = lspk
                runs[k - 1] = (li, rj, lspk, words[rj]["end"] - words[li]["start"])
                runs.pop(k)
                if k < len(runs):
                    nri, nrj, nrspk, _ = runs[k]
                    if nrspk == lspk:
                        runs[k - 1] = (li, nrj, lspk, words[nrj]["end"] - words[li]["start"])
                        runs.pop(k)
                changed = True
                break


def merge_with_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    all_words: list[dict] = []
    word_segments_no_words: list[dict] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            mid = (seg["start"] + seg["end"]) / 2
            spk = assign_speaker(mid, turns)
            word_segments_no_words.append({
                "start": seg["start"], "end": seg["end"], "speaker": spk, "text": seg["text"],
            })
            continue
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            spk = assign_speaker(mid, turns)
            all_words.append({"start": w["start"], "end": w["end"], "text": w["text"], "speaker": spk})

    smooth_word_speakers(all_words, min_run=1.2)

    utterances: list[dict] = []
    current: dict | None = None
    for w in all_words:
        if current and current["speaker"] == w["speaker"]:
            current["end"] = w["end"]
            current["text"] += w["text"]
        else:
            if current:
                utterances.append(current)
            current = {"start": w["start"], "end": w["end"], "speaker": w["speaker"], "text": w["text"]}
    if current:
        utterances.append(current)

    utterances.extend(word_segments_no_words)
    utterances.sort(key=lambda u: u["start"])

    merged: list[dict] = []
    for u in utterances:
        u["text"] = u["text"].strip()
        if not u["text"]:
            continue
        if merged and merged[-1]["speaker"] == u["speaker"] and u["start"] - merged[-1]["end"] < 1.5:
            merged[-1]["end"] = u["end"]
            merged[-1]["text"] += " " + u["text"]
        else:
            merged.append(u)
    return merged


def write_basic_md(path: Path, input_name: str, info: dict, segments: list[dict], model_name: str) -> None:
    lines = [
        f"# Транскрипция: {input_name}",
        "",
        f"- Модель: `{model_name}`",
        f"- Язык: {info['language']} (p={info['language_probability']:.2f})",
        f"- Длительность: {format_ts(info['duration'])} ({info['duration']:.1f}с)",
        "",
        "---",
        "",
    ]
    for seg in segments:
        lines.append(f"**[{format_ts(seg['start'])}]** {seg['text']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plain(path: Path, segments: list[dict]) -> None:
    path.write_text(" ".join(s["text"] for s in segments), encoding="utf-8")


def write_speakers_md(path: Path, input_name: str, info: dict, utterances: list[dict], model_name: str) -> None:
    speakers_set = sorted({u["speaker"] for u in utterances})
    lines = [
        f"# Транскрипция со спикерами: {input_name}",
        "",
        f"- Модель: `{model_name}`",
        f"- Диаризация: `pyannote/speaker-diarization-3.1`",
        f"- Длительность: {format_ts(info['duration'])} ({info['duration']:.1f}с)",
        f"- Найдено спикеров: {len(speakers_set)} ({', '.join(speakers_set)})",
        "",
        "---",
        "",
    ]
    for u in utterances:
        lines.append(f"**[{u['speaker']}, {format_ts(u['start'])}]** {u['text']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# =====================================================================
# ORCHESTRATOR
# =====================================================================

SHERPA_VENV_PYTHON = Path.home() / ".claude" / "skills" / "transcribe" / "venv-sherpa" / "Scripts" / "python.exe"
SHERPA_WORKER = Path(__file__).resolve().parent / "diarize_sherpa.py"


def spawn_worker(mode: str, env_extra: dict[str, str], cli: list[str]) -> subprocess.Popen:
    cmd = [sys.executable, __file__, "--worker", mode] + cli
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra)
    return subprocess.Popen(cmd, env=env)


def spawn_sherpa_diarize(env_extra: dict[str, str], cli: list[str]) -> subprocess.Popen:
    """Запустить sherpa-onnx диаризацию из отдельного venv-sherpa."""
    if not SHERPA_VENV_PYTHON.exists():
        raise RuntimeError(
            f"venv-sherpa не найден: {SHERPA_VENV_PYTHON}. "
            "Установите: python -m venv venv-sherpa && pip install onnxruntime-gpu sherpa-onnx soundfile"
        )
    cmd = [str(SHERPA_VENV_PYTHON), str(SHERPA_WORKER)] + cli
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra)
    return subprocess.Popen(cmd, env=env)


def orchestrate(args) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Файл не найден: {input_path}", file=sys.stderr)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent / "Транскрипция" / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    base = input_path.stem
    transcribe_json = output_dir / f"{base}.transcribe.json"
    turns_json = output_dir / f"{base}.turns.json"

    print(f"Файл: {input_path.name}", flush=True)
    print(f"Каталог: {output_dir}", flush=True)

    transcribe_cli = [
        "--input", str(input_path),
        "--out-json", str(transcribe_json),
        "--model", args.model,
        "--language", args.language,
        "--device", args.device,
        "--compute-type", args.compute_type,
    ]
    if args.diarize:
        transcribe_cli.append("--need-words")

    transcribe_proc = spawn_worker("transcribe", {}, transcribe_cli)

    diarize_proc = None
    if args.diarize:
        if args.diarize_engine == "sherpa-onnx":
            sherpa_cli = [
                "--input", str(input_path),
                "--out-json", str(turns_json),
                "--provider", "cuda",
                "--threshold", str(args.threshold),
            ]
            if args.num_speakers is not None:
                sherpa_cli += ["--num-speakers", str(args.num_speakers)]
            print(f"Диаризация: sherpa-onnx (pyannote-segmentation-3.0 + 3D-Speaker)", flush=True)
            diarize_proc = spawn_sherpa_diarize({}, sherpa_cli)
        else:
            diarize_cli = [
                "--input", str(input_path),
                "--out-json", str(turns_json),
            ]
            if args.num_speakers is not None:
                diarize_cli += ["--num-speakers", str(args.num_speakers)]
            if args.min_speakers is not None:
                diarize_cli += ["--min-speakers", str(args.min_speakers)]
            if args.max_speakers is not None:
                diarize_cli += ["--max-speakers", str(args.max_speakers)]
            if args.tf32:
                diarize_cli.append("--tf32")
            print(f"Диаризация: pyannote 4.x", flush=True)
            diarize_proc = spawn_worker("diarize", {}, diarize_cli)

    rc_t = transcribe_proc.wait()
    if rc_t != 0:
        if diarize_proc is not None:
            diarize_proc.terminate()
        print(f"Транскрипция упала с кодом {rc_t}", file=sys.stderr)
        return rc_t

    payload = json.loads(transcribe_json.read_text(encoding="utf-8"))
    segments = payload["segments"]
    info = payload["info"]

    transcript_md = output_dir / f"{base} - транскрипция.md"
    plain_txt = output_dir / f"{base} - транскрипция.txt"
    write_basic_md(transcript_md, input_path.name, info, segments, args.model)
    write_plain(plain_txt, segments)
    print(f"  MD:    {transcript_md}", flush=True)
    print(f"  Plain: {plain_txt}", flush=True)

    if diarize_proc is not None:
        rc_d = diarize_proc.wait()
        if rc_d != 0:
            print(f"Диаризация упала с кодом {rc_d} (транскрипция сохранена)", file=sys.stderr)
            return rc_d
        turns = json.loads(turns_json.read_text(encoding="utf-8"))
        utterances = merge_with_speakers(segments, turns)
        speakers_md = output_dir / f"{base} - со спикерами.md"
        write_speakers_md(speakers_md, input_path.name, info, utterances, args.model)
        print(f"  Spk:   {speakers_md}", flush=True)

    if not args.keep_intermediate:
        for f in (transcribe_json, turns_json):
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass

    return 0


# =====================================================================
# MAIN: разбор аргументов
# =====================================================================

def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        mode = sys.argv[2]
        worker_args = sys.argv[3:]
        ap = argparse.ArgumentParser()
        if mode == "transcribe":
            ap.add_argument("--input", required=True)
            ap.add_argument("--out-json", required=True)
            ap.add_argument("--model", default="mobiuslabsgmbh/faster-whisper-large-v3-turbo")
            ap.add_argument("--language", default="ru")
            ap.add_argument("--device", default="cuda")
            ap.add_argument("--compute-type", default="float16")
            ap.add_argument("--need-words", action="store_true")
            return worker_transcribe(ap.parse_args(worker_args))
        elif mode == "diarize":
            ap.add_argument("--input", required=True)
            ap.add_argument("--out-json", required=True)
            ap.add_argument("--num-speakers", type=int, default=None)
            ap.add_argument("--min-speakers", type=int, default=None)
            ap.add_argument("--max-speakers", type=int, default=None)
            ap.add_argument("--tf32", action="store_true")
            return worker_diarize(ap.parse_args(worker_args))
        else:
            print(f"Неизвестный worker mode: {mode}", file=sys.stderr)
            return 1

    ap = argparse.ArgumentParser(description="Локальная транскрипция через faster-whisper + опц. диаризация (parallel)")
    ap.add_argument("input", help="Путь к аудио/видео файлу")
    ap.add_argument("--output-dir", default=None, help="Каталог вывода")
    ap.add_argument("--model", default="mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    ap.add_argument("--language", default="ru")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--diarize", action="store_true", help="Включить диаризацию (параллельно с транскрипцией)")
    ap.add_argument("--diarize-engine", default="sherpa-onnx", choices=["sherpa-onnx", "pyannote"],
                    help="Движок: sherpa-onnx (default, GPU CUDA, RTF 0.24) или pyannote 4.x (GPU, RTF 0.36, fallback)")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--min-speakers", type=int, default=None, help="Только для pyannote")
    ap.add_argument("--max-speakers", type=int, default=None, help="Только для pyannote")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="Порог кластеризации для sherpa-onnx (default 0.5)")
    ap.add_argument("--no-tf32", dest="tf32", action="store_false", help="Отключить TF32 для pyannote (по умолчанию вкл)")
    ap.set_defaults(tf32=True)
    ap.add_argument("--keep-intermediate", action="store_true", help="Не удалять промежуточные JSON")
    args = ap.parse_args()
    return orchestrate(args)


if __name__ == "__main__":
    try:
        rc = main()
    except SystemExit:
        raise
    except BaseException:
        log_path = Path.home() / ".claude" / "skills" / "transcribe" / "transcribe_local.crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"argv: {sys.argv}\n")
            f.write(traceback.format_exc())
            f.write("\n")
        print(f"\nКраш записан в {log_path}", file=sys.stderr)
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
