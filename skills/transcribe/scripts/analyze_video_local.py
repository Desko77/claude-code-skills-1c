"""
analyze_video_local.py - ПОЛНОСТЬЮ ЛОКАЛЬНЫЙ разбор видео (стадия B без облака).

Аналог `transcribe.py --analyze-ui`, но без Gemini: клиентское видео не покидает сеть.

Пайплайн:
  1. Речь    - transcribe_local.py (whisper venv, CUDA) -> `<имя> - транскрипция.md/.txt`.
  2. Спикеры - имена за метками: голосовая база отпечатков, затем модель на 150, затем
               ОБЯЗАТЕЛЬНАЯ программная проверка по обращениям (speaker_validator).
  3. Кадры   - extract_scene_frames (ffmpeg scene-detect + пол + dhash-дедуп + кап) и зрение:
               каждый кадр -> VLM на сервере 150, лог пишется инкрементально по таймкодам.
  4. Связный - `<имя> - связный.md`: нарратив из механического лога.
  5. Саммари - `<имя> - саммари.md`: 2 прохода на 150, вход - только текст транскрипции.

Стадии деградируют ПООТДЕЛЬНОСТИ. Нет модели зрения - будут речь, спикеры и саммари; нет 150
вообще - будут речь и спикеры (голос и разбор обращений моделей не требуют). Сбой кадра не
прерывает разбор: кадр помечается, прогон идёт дальше. Что сделано, а что нет, пишется в
`<имя>.status.json` - по нему же работает резюм `--reuse-frames`.

Спикеры считаются ДО зрения: раньше стадия стояла после него, и любая проблема с VLM обнуляла
именование и авто-enroll голосовой базы, к зрению отношения не имеющие.

Запуск: python analyze_video_local.py "<video>" [--output-dir DIR] [--diarize] [--no-vlm]
        [--no-summary] [--no-coherent] [--reuse-transcript] [--reuse-frames]
"""
import os
import re
import sys
import json
import argparse
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_backends as lb  # noqa: E402
import text_stage as ts  # noqa: E402
import voiceprints as vp  # noqa: E402
import speaker_validator as sv  # noqa: E402
import glossary as gloss  # noqa: E402

# Whisper живет в отдельном venv (изоляция CUDA-DLL ctranslate2 vs torch). Дефолт - venv скилла;
# реальный путь задай через env WHISPER_PYTHON (или .env, он gitignore и не в паблик-репо).
# .env уже загружен импортом local_backends выше, поэтому os.environ здесь его видит.
_DEFAULT_WHISPER_PY = Path.home() / ".claude" / "skills" / "transcribe" / "venv-whisper" / "Scripts" / "python.exe"
WHISPER_PYTHON = os.environ.get("WHISPER_PYTHON", str(_DEFAULT_WHISPER_PY))
TRANSCRIBE_LOCAL = Path(__file__).resolve().parent / "transcribe_local.py"

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
CONSEC_FAIL_ABORT = 3  # столько сбоев подряд => проверить сервер и модель. Раньше это обрывало
#   разбор совсем и бросало весь хвост кадров без единой попытки; теперь по этому порогу идёт
#   попытка восстановления, и стадия останавливается, только если сервер действительно не поднялся.

# Промпты и текстовая обработка (спикеры -> имена, связный лог, саммари) вынесены в общий
# модуль text_stage - единый источник истины для локального и облачного движков.


def _append(path: Path, text: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


# ---------------- Шаг 1: речь ----------------

def run_whisper(video: Path, output_dir: Path, diarize=False, extra=None, reuse=False):
    """Запустить transcribe_local.py в whisper-venv. Вернуть путь к `<имя> - транскрипция.md`.

    Транскрипция пишется ДО ожидания диаризации, поэтому при падении ТОЛЬКО диаризации
    (rc != 0, но файл создан и непуст) считаем речь успешной и продолжаем.
    reuse=True: если транскрипция уже есть и непуста - не гонять whisper заново (resume-режим,
    напр. речь посчитана раньше, а разбор экрана делаем позже, когда поднялся сервер 150).
    """
    md = output_dir / f"{video.stem} - транскрипция.md"
    if reuse and md.exists() and md.stat().st_size > 0:
        spk = output_dir / f"{video.stem} - со спикерами.md"
        note = "со спикерами" if spk.exists() else "без спикеров"
        print(f"[речь] переиспользую готовую транскрипцию ({note}, --reuse-transcript): {md.name}",
              flush=True)
        return md
    if not Path(WHISPER_PYTHON).exists():
        raise lb.LocalBackendError(
            f"whisper-venv python не найден: {WHISPER_PYTHON}. "
            "Задай env WHISPER_PYTHON с корректным путём.")
    cmd = [WHISPER_PYTHON, str(TRANSCRIBE_LOCAL), str(video), "--output-dir", str(output_dir)]
    if diarize:
        cmd.append("--diarize")
    if extra:
        cmd += extra
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"[речь] whisper (diarize={diarize})...", flush=True)
    rc = subprocess.run(cmd, env=env).returncode
    if md.exists() and md.stat().st_size > 0:
        if rc != 0:
            print(f"[речь] whisper вернул код {rc}, но транскрипция создана - продолжаю "
                  f"(вероятно упала только диаризация).", file=sys.stderr)
        return md
    raise lb.LocalBackendError(f"transcribe_local.py упал (код {rc}), транскрипция не создана: {md}")


def parse_transcript(output_dir: Path, base: str):
    """Разобрать транскрипцию -> [(start_sec, text)]. При наличии диаризации берёт файл со спикерами
    и добавляет метку спикера в текст (чтобы речь в логе/саммари была атрибутирована)."""
    speakers = output_dir / f"{base} - со спикерами.md"
    plain = output_dir / f"{base} - транскрипция.md"
    src = speakers if speakers.exists() else plain
    if not src.exists():
        return []
    segs = []
    pat = re.compile(r"\*\*\[(?:([^,\]]+),\s*)?([\d:]+)\]\*\*\s*(.*)")
    for line in src.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        speaker, tstr, text = m.group(1), m.group(2), m.group(3).strip()
        sec = 0
        for part in tstr.split(":"):
            sec = sec * 60 + int(part)
        if speaker:
            text = f"{speaker}: {text}"
        if text:
            segs.append((sec, text))
    return segs


# ---------------- Шаги 2-4: кадры + зрение + детальный лог ----------------

def _frame_block(i, frames, n, segs, desc):
    """Markdown-блок одного кадра: описание экрана + реплики речи за интервал до следующего кадра."""
    t, fpath = frames[i]
    lo = 0 if i == 0 else t
    hi = frames[i + 1][0] if i + 1 < n else float("inf")
    desc = desc.replace("```", "` ` `")  # нейтрализуем code-fence, чтобы не сломать рендер MD
    speech = [(s, txt) for s, txt in segs if lo <= s < hi and txt]
    block = [f"## [{lb.format_tc(t)}] экран\n",
             f"![screenshot](screenshots/{fpath.name})\n",
             "**На экране (распознано локально):**\n", desc, "\n"]
    if speech:
        block.append("\n**Речь в этот интервал:**\n")
        for s, txt in speech:
            block.append(f"- [{lb.format_tc(s)}] {txt}\n")
    block.append("\n---\n\n")
    return "".join(block)


def load_status(path: Path):
    """Статус прошлого прогона. Пустой словарь, если файла нет или он испорчен."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_status(path: Path, data):
    """Машиночитаемый статус рядом с выходами: что разобрано, что нет и чем упало.

    Нужен и человеку, и агенту: по нему видно, какие кадры остались непокрытыми, и не приходится
    вычитывать весь детальный лог, чтобы это выяснить.
    """
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"[warn] не удалось записать статус прогона: {e}", file=sys.stderr)


def _vlm_worker(fpath, vlm_model, max_tokens, state, lock):
    """Один кадр через VLM. Выгрузку модели по TTL лечим на месте и сбоем НЕ считаем."""
    if state["abort"]:
        return {"state": "skipped", "error": state["abort"]}
    try:
        r = lb.vlm_read_frame(fpath, model=vlm_model, max_tokens=max_tokens)
        return {"state": "ok", "text": r["text"], "prompt_tokens": r["prompt_tokens"]}
    except lb.LocalBackendError as e:
        if not lb.looks_unloaded(e):
            return {"state": "failed", "error": str(e)}
        with lock:                       # грузим один раз на всех, а не каждым потоком
            ready = lb.ensure_loaded(vlm_model)
        if ready:
            try:
                r = lb.vlm_read_frame(fpath, model=vlm_model, max_tokens=max_tokens)
                return {"state": "ok", "text": r["text"], "prompt_tokens": r["prompt_tokens"],
                        "recovered": True}
            except lb.LocalBackendError as again:
                return {"state": "failed", "error": str(again), "unloaded": True}
        return {"state": "failed", "error": str(e), "unloaded": True}


def analyze_frames(video: Path, output_dir: Path, segs, detailed_path: Path, status_path: Path,
                   vlm_model=None, budget=None, reuse=False):
    """Нарезать кадры, прогнать через VLM параллельно, детальный лог писать инкрементально
    СТРОГО в порядке таймкодов. Возвращает сводку dict(frames, ok, failed, skipped, reused).

    Сбой кадра больше не прерывает стадию: неудачный помечается маркером, разбор идёт дальше.
    Останавливаемся только если сервер действительно не отвечает и поднять его не удалось -
    тогда остаток честно помечается неразобранным, а пайплайн продолжается.
    """
    budget = budget or lb.plan_vlm_budget(vlm_model)
    max_tokens = budget["max_tokens"]
    shots_dir = output_dir / "screenshots"
    print(f"[кадры] нарезка scene-кадров -> {shots_dir}", flush=True)
    frames, truncated = lb.extract_scene_frames(video, shots_dir)
    n = len(frames)

    done = {}
    if reuse:   # резюм: описания прошлого прогона берём готовыми, заново зрение не гоняем
        for item in load_status(status_path).get("frames", []):
            if item.get("state") == "ok" and item.get("text") and item.get("file"):
                done[item["file"]] = item["text"]
        if done:
            print(f"[кадры] переиспользую готовые описания: {len(done)} (--reuse-frames)",
                  flush=True)

    header = (f"# Детальный лог (локальный разбор экрана): {video.name}\n\n"
              f"Зрение: `{vlm_model or lb.LOCAL_VLM_MODEL}` (локально, сервер 150). "
              f"Кадров: {n}"
              + (" [достигнут кап - часть прорежена]" if truncated else "") + "\n\n---\n\n")
    detailed_path.write_text(header, encoding="utf-8")
    if not frames:
        _append(detailed_path, "> **[!] Кадры не извлечены** (пустое или битое видео?).\n")
        return {"frames": 0, "ok": 0, "failed": 0, "skipped": 0, "reused": 0, "truncated": truncated}

    results = {}
    records = [None] * n
    next_write = 0      # пишем строго по возрастанию таймкода, независимо от порядка ответов
    state = {"abort": ""}
    lock = threading.Lock()

    def remember(i, res):
        t, fpath = frames[i]
        rec = {"index": i, "tc": lb.format_tc(t), "file": fpath.name, "state": res["state"]}
        if res.get("error"):
            rec["error"] = res["error"][:400]
        if res.get("text"):
            rec["text"] = res["text"]
        records[i] = rec
        if res["state"] == "ok":
            results[i] = res["text"]
        else:
            results[i] = (f"> **[!] Кадр не распознан.** Причина: "
                          f"{res.get('error') or 'стадия зрения остановлена'}")

    def flush_ready():
        nonlocal next_write
        while next_write < n and next_write in results:
            _append(detailed_path, _frame_block(next_write, frames, n, segs, results[next_write]))
            next_write += 1

    counters = {"ok": 0, "failed": 0, "skipped": 0, "reused": 0}
    pending = []
    for i, (t, fpath) in enumerate(frames):
        if fpath.name in done:
            remember(i, {"state": "ok", "text": done[fpath.name]})
            counters["reused"] += 1
        else:
            pending.append(i)
    flush_ready()

    # Первый кадр идём ОДИН: его prompt_tokens и есть настоящий резерв контекста под картинку
    # (он зависит от разрешения, а не от содержимого экрана). До этого замера параллельность
    # считается от оценки из конфига, обычно завышенной вдвое - и зря режет пропускную способность.
    if pending:
        first = pending.pop(0)
        res = _vlm_worker(frames[first][1], vlm_model, max_tokens, state, lock)
        remember(first, res)
        counters[res["state"]] += 1
        flush_ready()
        if res.get("prompt_tokens"):
            budget = lb.replan_with_measured(budget, res["prompt_tokens"])
            print(f"[кадры] замер на первом кадре: промпт {res['prompt_tokens']} ток. "
                  f"-> резерв {budget['reserve']}, параллельно {budget['parallel']}", flush=True)
    parallel = budget["parallel"]
    print(f"[кадры] всего {n}, к разбору {len(pending)} (параллельно {parallel}, "
          f"вывод/кадр {max_tokens})", flush=True)

    consec_fail = 0
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(_vlm_worker, frames[i][1], vlm_model, max_tokens, state, lock): i
                for i in pending}
        # Ожидаемые сбои VLM возвращаются воркером как state=failed; программные ошибки
        # (KeyError и прочее) прилетают из fut.result() и НЕ ловятся - пусть падают громко.
        for fut in as_completed(futs):
            i = futs[fut]
            res = fut.result()
            remember(i, res)
            counters[res["state"]] += 1
            if res["state"] == "ok":
                consec_fail = 0
                mark = " (после перезагрузки модели)" if res.get("recovered") else ""
                print(f"  [кадр {i+1}/{n}] {lb.format_tc(frames[i][0])}  ok{mark}", flush=True)
            elif res["state"] == "failed":
                consec_fail += 1
                print(f"  [кадр {i+1}/{n}] {lb.format_tc(frames[i][0])}  СБОЙ: "
                      f"{res.get('error', '')[:200]}", file=sys.stderr, flush=True)
            flush_ready()
            if consec_fail >= CONSEC_FAIL_ABORT and not state["abort"]:
                # Подряд идущие сбои - повод проверить сервер, а не молча бросить остаток кадров.
                print(f"[кадры] {consec_fail} сбоя подряд - проверяю сервер и модель",
                      file=sys.stderr, flush=True)
                try:
                    lb.check_server()
                    alive = lb.ensure_loaded(vlm_model)
                except lb.LocalBackendError:
                    alive = False
                if alive:
                    consec_fail = 0
                    print("[кадры] сервер жив, модель загружена - продолжаю", flush=True)
                else:
                    state["abort"] = ("сервер 150 не отвечает или модель зрения не поднялась - "
                                      "остаток кадров не разобран")
                    print(f"[кадры] {state['abort']}", file=sys.stderr, flush=True)

    # Переполнение контекста - не отказ сервера, а слишком большая параллельность: слоты делят
    # ОДНО окно. Политика прямо требует снизить параллельность и ПОВТОРИТЬ, а не терять кадры.
    # Без этого шага исправный VLM оставлял бы почти все кадры неразобранными.
    overflow = [i for i in range(n) if records[i] and records[i]["state"] == "failed"
                and lb.looks_context_overflow(records[i].get("error"))]
    if overflow and not state["abort"]:
        print(f"[кадры] {len(overflow)} кадров не влезли в контекст при параллельности {parallel}"
              f" - повторяю по одному", flush=True)
        for i in overflow:
            res = _vlm_worker(frames[i][1], vlm_model, max_tokens, state, lock)
            was = records[i]["state"]
            remember(i, res)
            counters[was] -= 1
            counters[res["state"]] += 1
            print(f"  [кадр {i+1}/{n}] {lb.format_tc(frames[i][0])}  повтор: {res['state']}",
                  flush=True)
        # Лог пишется инкрементально, поэтому маркеры сбоя по этим кадрам уже на диске:
        # пересобираем его целиком из накопленных описаний, иначе повтор починил бы только статус.
        detailed_path.write_text(header, encoding="utf-8")
        next_write = 0
        flush_ready()

    flush_ready()
    for i in range(n):   # кадры, до которых очередь не дошла из-за остановки стадии
        if records[i] is None:
            remember(i, {"state": "skipped", "error": state["abort"] or "не обработан"})
            counters["skipped"] += 1
    flush_ready()

    if counters["failed"] or counters["skipped"]:
        _append(detailed_path,
                f"\n> **[!] Разбор экрана неполный:** распознано {counters['ok'] + counters['reused']}"
                f" из {n}, сбоев {counters['failed']}, не обработано {counters['skipped']}."
                + (f" Причина остановки: {state['abort']}." if state["abort"] else "") + "\n")

    summary = {"frames": n, "truncated": truncated, **counters,
               "aborted_reason": state["abort"] or None,
               "records": [r for r in records if r]}
    return summary


# ---------------- Шаг 5: текстовая стадия (общий text_stage) ----------------

def _transcript_text(segs):
    """Текст транскрипции из сегментов [(sec, text)] для текстовой стадии."""
    return "\n".join(f"[{lb.format_tc(s)}] {txt}" for s, txt in segs if txt)


# ---------------- main ----------------

def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description="Локальный разбор видео (whisper + VLM/LLM на 150), без облака")
    ap.add_argument("video", help="Путь к видеофайлу")
    ap.add_argument("--output-dir", "-o", default=None)
    ap.add_argument("--diarize", action="store_true", help="Диаризация речи (whisper); спикеры попадут в лог/саммари")
    ap.add_argument("--num-speakers", type=int, default=None,
                    help="Точное число спикеров (опционально; без него автодетект pyannote community-1)")
    ap.add_argument("--no-summary", action="store_true", help="Не строить саммари")
    ap.add_argument("--no-coherent", action="store_true", help="Не строить связный лог (быстрее)")
    ap.add_argument("--no-vlm", action="store_true",
                    help="Не разбирать экран моделью зрения (речь, спикеры и саммари считаются как обычно). "
                         "Кадры при этом всё равно нарезаются - их можно посмотреть глазами")
    ap.add_argument("--reuse-transcript", action="store_true",
                    help="Переиспользовать готовую транскрипцию (не гонять whisper заново), если файл уже есть и непуст")
    ap.add_argument("--reuse-frames", action="store_true",
                    help="Переиспользовать описания кадров из статуса прошлого прогона (дораспознать только оставшиеся)")
    ap.add_argument("--vlm-model", default=None, help=f"VLM на 150 (по умолч. {lb.LOCAL_VLM_MODEL})")
    ap.add_argument("--summary-model", default=None, help=f"Summary на 150 (по умолч. {lb.LOCAL_SUMMARY_MODEL})")
    ap.add_argument("--speaker-model", default=None, help=f"Маппинг спикеров (по умолч. {lb.LOCAL_SPEAKER_MODEL})")
    ap.add_argument("--glossary", default=None,
                    help="Файл глоссария терминов (по умолч. glossary.txt в корне скила). "
                         "Правильные написания подсказываются распознавателю, ослышки правятся в "
                         "готовом тексте - иначе DAX уходит в отчет как 'ДАКС'")
    ap.add_argument("--no-glossary", action="store_true", help="Не использовать глоссарий терминов")
    ap.add_argument("--voiceprint-db", default=None, help=f"База голосов (по умолч. {vp.DEFAULT_DB})")
    ap.add_argument("--project", default=None, help="Проект/заказчик - провенанс в базе голосов")
    ap.add_argument("--no-voiceprints", action="store_true", help="Не использовать голосовую базу")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"Файл не найден: {video}", file=sys.stderr)
        sys.exit(1)
    if video.suffix.lower() not in VIDEO_EXTS:
        print(f"Не видео: {video.suffix}. Локальный разбор экрана - только для видео "
              f"({', '.join(sorted(VIDEO_EXTS))}).", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else video.parent / "Транскрипция" / video.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    vlm_model = args.vlm_model or lb.LOCAL_VLM_MODEL
    summary_model = args.summary_model or lb.LOCAL_SUMMARY_MODEL
    speaker_model = args.speaker_model or lb.LOCAL_SPEAKER_MODEL
    voiceprint_db = args.voiceprint_db or str(vp.DEFAULT_DB)

    def gemma_llm(data, instruction):
        """LLM-вызов текстовой стадии на 150 (gemma): связный лог + саммари. Callable для text_stage."""
        return lb.llm_summary_pass(data, instruction, model=summary_model, max_tokens=6000)

    def speaker_llm(data, instruction):
        """Маппинг спикеров на 150 строгим JSON по схеме: формат гарантирует сервер, а не
        послушание модели. Отдаём текстом - text_stage разбирает ответ сам и одинаково понимает
        движки со строгими схемами и без них."""
        return json.dumps(lb.llm_json_pass(data, instruction, ts.SPEAKERS_SCHEMA,
                                           model=speaker_model, max_tokens=2000),
                          ensure_ascii=False)

    transcript_md = output_dir / f"{video.stem} - транскрипция.md"
    detailed_path = output_dir / f"{video.stem} - детальный.md"
    coherent_path = output_dir / f"{video.stem} - связный.md"
    summary_path = output_dir / f"{video.stem} - саммари.md"
    status_path = output_dir / f"{video.stem}.status.json"

    # ----- Предполётная проверка: постадийно, а не всё-или-ничего -----
    # Отсутствие одной модели гасит ТОЛЬКО свою стадию. Раньше любая недостача обрывала прогон
    # целиком, и человек не получал даже транскрипцию, хотя речь считается локально и от 150
    # вообще не зависит.
    print(f"[0] проверка сервера 150: {lb.LOCAL_150_BASE}", flush=True)
    models = []
    try:
        models = lb.check_server()
    except lb.LocalBackendError as e:
        print(f"[0] сервер 150 недоступен ({e}). Речь и спикеры посчитаю, разбор экрана и саммари - нет.",
              file=sys.stderr, flush=True)

    use_vlm = not args.no_vlm
    if args.no_vlm:
        print("[0] разбор экрана отключён (--no-vlm)", flush=True)
    elif vlm_model not in models:
        use_vlm = False
        print(f"[0] модель зрения '{vlm_model}' на 150 недоступна - кадры будут нарезаны, "
              f"но не разобраны", file=sys.stderr, flush=True)
    if use_vlm:
        try:
            lb.ffmpeg_exe()
        except lb.LocalBackendError as e:
            use_vlm = False
            print(f"[0] {e} - разбор экрана невозможен", file=sys.stderr, flush=True)

    use_text = summary_model in models
    if not use_text:
        print(f"[0] text-модель '{summary_model}' на 150 недоступна - связного лога и саммари не будет",
              file=sys.stderr, flush=True)
    use_speaker_llm = speaker_model in models
    if not use_speaker_llm:
        print(f"[0] speaker-модель '{speaker_model}' на 150 недоступна - имена определю "
              f"по голосовой базе и обращениям в тексте", file=sys.stderr, flush=True)

    budget = None
    if use_vlm:
        budget = lb.plan_vlm_budget(vlm_model)
        print(f"[0] бюджет зрения: контекст={budget['context']} ({budget['source']}), "
              f"вывод/кадр={budget['max_tokens']}, параллельно={budget['parallel']} "
              f"(резерв промпта {budget['reserve']}, уточню на первом кадре)", flush=True)

    # ----- clean start: не выдать результаты прошлого прогона за текущие -----
    if not args.reuse_transcript:
        transcript_md.write_text("", encoding="utf-8")
    if args.no_summary:
        summary_path.unlink(missing_ok=True)  # не оставляем старое саммари, раз его не просили
    else:
        summary_path.write_text("", encoding="utf-8")
    # detailed_path сбрасывается внутри analyze_frames

    # ----- 1. Речь -----
    whisper_extra = ["--num-speakers", str(args.num_speakers)] if args.num_speakers else []
    if args.glossary:
        whisper_extra += ["--glossary", args.glossary]
    if args.no_glossary:
        whisper_extra.append("--no-glossary")
    transcript_md = run_whisper(video, output_dir, diarize=args.diarize, reuse=args.reuse_transcript,
                                extra=whisper_extra or None)
    segs = parse_transcript(output_dir, video.stem)
    print(f"[речь] сегментов транскрипции: {len(segs)}"
          + (" (со спикерами)" if (output_dir / f'{video.stem} - со спикерами.md').exists() else ""),
          flush=True)

    # Страховочная правка ослышек по глоссарию. Whisper уже правит свой вывод, но при
    # --reuse-transcript он не запускался вовсе, а старые транскрипции сделаны до глоссария.
    # Замена идемпотентна (правильные написания не входят в список ослышек), так что повтор безвреден.
    gl = gloss.load(args.glossary, enabled=not args.no_glossary)
    for w in gl.warnings:
        print(f"[термины] {w}", file=sys.stderr)
    if gl:
        print(f"[термины] {gloss.describe(gl)}", flush=True)
        seg_dicts = [{"text": t} for _s, t in segs]
        stats = gl.fix_segments(seg_dicts)
        if stats:
            segs = [(s, d["text"]) for (s, _t), d in zip(segs, seg_dicts)]
            print("[термины] исправлено: "
                  + ", ".join(f"{k} x{v}" for k, v in sorted(stats.items())), flush=True)

    exit_code = 0

    # ----- 2. Спикеры -> имена. ДО разбора экрана -----
    # Стадия к зрению отношения не имеет, а раньше стояла после него: любая проблема с VLM
    # обнуляла и именование, и авто-enroll голосовой базы. Свопа моделей перенос не создаёт -
    # на 150 они со-резидентны.
    transcript_text = _transcript_text(segs)

    # СЛОЙ 1 - голос (база отпечатков, cosine > порог): узнаёт различимых даже неназванных и между
    # встречами. СЛОЙ 2 - текст (модель на 150). СЛОЙ 3 - программная проверка по обращениям
    # (speaker_validator): без неё модель систематически вешает имя на того, кто его ПРОИЗНОСИТ,
    # а не на адресата. Голос приоритетнее текста, и проверка его не пересматривает.
    name_map = {}
    if transcript_text.strip():
        vp_path = output_dir / f"{video.stem}.voiceprints.json"
        use_voice = (not args.no_voiceprints) and vp_path.exists()
        db, prints, voice_ids = None, {}, {}
        if use_voice:
            try:
                db = vp.load_db(voiceprint_db)
                prints = json.loads(vp_path.read_text(encoding="utf-8"))
                voice_ids = vp.identify(prints, db, project=args.project)
                if voice_ids:
                    print("[спикеры] по голосу: "
                          + ", ".join(f"{k}->{n}({s})" for k, (n, s) in voice_ids.items()), flush=True)
            except Exception as e:
                use_voice = False
                print(f"[спикеры] голосовой слой пропущен ({e})", file=sys.stderr)
        text_names = {}
        if use_speaker_llm:
            # log обязателен: map_speakers гасит ошибку модели внутри себя, и без него сбой
            # текстового слоя прошёл бы молча.
            text_names = ts.map_speakers(
                transcript_text, speaker_llm, validate=False,   # проверка - ниже, по общей картине
                log=lambda m: print(f"[спикеры] {m}", file=sys.stderr, flush=True))

        merged = {label: name for label, (name, _score) in voice_ids.items()}
        for label, name in text_names.items():   # голос приоритетнее текста
            merged.setdefault(label, name)
        name_map, checks = sv.validate(merged, transcript_text, voice_confirmed=set(voice_ids))
        for line in checks:
            print(f"[спикеры] проверка: {line}", flush=True)

        if use_voice and db is not None and name_map:   # авто-enroll: голос не узнал, но имя есть
            # Проверка уже гарантирует, что одно имя не висит на двух метках, поэтому отдельный
            # подсчёт неоднозначностей больше не нужен: в базу не попадут голоса разных людей
            # под одной записью.
            added, skipped = 0, 0
            for label, name in name_map.items():
                if label in voice_ids or label not in prints:
                    continue
                if not vp.is_plausible_name(name):   # мусорное имя (КС/инициалы/огрызок) - не засоряем базу
                    skipped += 1
                    continue
                vp.enroll(db, name, prints[label], project=args.project, meeting=video.stem)
                added += 1
            if added:
                try:
                    vp.save_db(db, voiceprint_db)
                    msg = f"[спикеры] авто-enroll в базу: +{added} голос(ов)"
                    if skipped:
                        msg += f" (пропущено неоднозначных: {skipped})"
                    print(msg, flush=True)
                except Exception as e:
                    print(f"[спикеры] авто-enroll не сохранён ({e})", file=sys.stderr)
            elif skipped:
                print(f"[спикеры] авто-enroll пропущен: все {skipped} имён неоднозначны", flush=True)

    if name_map:
        print(f"[спикеры] итог: {', '.join(f'{k}->{v}' for k, v in name_map.items())}", flush=True)
        # Имена подставляются ДО разбора экрана, поэтому детальный лог сразу пишется с ними и
        # переписывать его задним числом больше не нужно.
        segs = [(s, ts.apply_names(t, name_map)) for s, t in segs]
        transcript_text = _transcript_text(segs)
    else:
        print("[спикеры] имена не определены - оставляю метки", flush=True)

    # ----- 3. Кадры + зрение + детальный лог -----
    vision = None
    if use_vlm:
        vision = analyze_frames(video, output_dir, segs, detailed_path, status_path,
                                vlm_model=vlm_model, budget=budget, reuse=args.reuse_frames)
        recognized = vision["ok"] + vision["reused"]
        print(f"[кадры] детальный лог готов: распознано {recognized} из {vision['frames']}"
              + (f", сбоев {vision['failed']}" if vision["failed"] else "")
              + (f", не обработано {vision['skipped']}" if vision["skipped"] else ""), flush=True)
        if vision["frames"] and recognized < vision["frames"]:
            exit_code = 3
    else:
        # Зрение выключено - кадры всё равно нарезаем: их можно посмотреть глазами, а речь по
        # интервалам уже разложена. Раньше единственным способом сюда попасть было убийство процесса.
        detailed_path.write_text(
            f"# Детальный лог (речь по интервалам кадров): {video.name}\n\n"
            f"> Разбор экрана не выполнялся"
            f"{' (--no-vlm)' if args.no_vlm else ' - модель зрения недоступна'}. "
            f"Скриншоты нарезаны в `screenshots/`.\n\n---\n\n", encoding="utf-8")
        try:
            frames, _trunc = lb.extract_scene_frames(video, output_dir / "screenshots")
            for i in range(len(frames)):
                _append(detailed_path, _frame_block(i, frames, len(frames), segs,
                                                    "_(экран не разобран)_"))
            print(f"[кадры] нарезано без разбора: {len(frames)}", flush=True)
            # Кадры перечисляем поимённо даже без разбора: по этому списку человек или агент
            # находит, что именно осталось непокрытым, не вычитывая весь детальный лог.
            vision = {"frames": len(frames), "ok": 0, "failed": 0, "skipped": len(frames),
                      "reused": 0, "aborted_reason": "зрение отключено",
                      "records": [{"index": i, "tc": lb.format_tc(t), "file": p.name,
                                   "state": "skipped"} for i, (t, p) in enumerate(frames)]}
        except lb.LocalBackendError as e:
            print(f"[кадры] нарезка не удалась: {e}", file=sys.stderr)
        if not args.no_vlm:   # выключили не мы, а недоступность модели - это неполный результат
            exit_code = 3

    # ----- 4. Связный лог (нарратив из механического детального) -----
    coherent_path.unlink(missing_ok=True)  # чистый старт: не оставить старый связный лог
    if args.no_coherent:
        print("[связный] пропущено (--no-coherent)", flush=True)
    elif not use_text:
        print("[связный] пропущено: text-модель недоступна", file=sys.stderr)
    elif detailed_path.exists():
        print("[связный] сборка связного нарратива (чанками)...", flush=True)
        try:
            unsupported = []
            coherent = ts.build_coherent_log(detailed_path.read_text(encoding="utf-8"), gemma_llm,
                                             report=unsupported)
            if coherent:
                # Числа, которых нет в описаниях кадров, выносим сноской в конец файла: молча
                # вырезать их из нарратива нельзя (порвется фраза), а молча оставить - значит выдать
                # выдумку модели за прочитанное с экрана. На реальном прогоне таких было восемь -
                # суммы, коды счетов и годы, которых кадры не содержали.
                note = ""
                if unsupported:
                    note = ("\n\n---\n\n> **Не подтверждено кадрами.** Эти числа и коды есть в "
                            "нарративе, но их нет в описаниях экрана, из которых он собран - "
                            "проверь по скриншотам, прежде чем использовать:\n>\n"
                            + "".join(f"> - {line}\n" for line in unsupported))
                coherent_path.write_text(
                    f"# Связный лог (экран + речь): {video.name}\n\n{coherent}\n{note}",
                    encoding="utf-8")
                print(f"[связный] сохранено: {coherent_path.name}", flush=True)
                if unsupported:
                    print(f"[связный] ВНИМАНИЕ: {len(unsupported)} фрагмент(ов) с числами, которых "
                          f"нет в кадрах - сноска в конце файла", file=sys.stderr, flush=True)
        except lb.LocalBackendError as e:
            print(f"[связный] ОШИБКА (пропускаю): {e}", file=sys.stderr)

    # ----- 5. Саммари (протокол задач и решений из полного текста) -----
    summary_done = False   # именно ФАКТ построения, а не "модель была доступна": иначе статус-файл
    #                        отрапортует успех там, где в саммари лежит маркер ошибки
    if args.no_summary:
        print("[саммари] пропущено (--no-summary)", flush=True)
    elif not use_text:
        summary_path.write_text(
            "> **[!] Саммари не построено:** text-модель на 150 недоступна.\n", encoding="utf-8")
        print("[саммари] пропущено: text-модель недоступна", file=sys.stderr)
        exit_code = exit_code or 3
    else:
        print("[саммари] генерация протокола...", flush=True)
        try:
            summary = ts.build_summary(transcript_text, gemma_llm)
            if summary:
                summary_path.write_text(summary, encoding="utf-8")
                summary_done = True
                print(f"[саммари] сохранено: {summary_path.name}", flush=True)
            else:
                summary_path.write_text("> Транскрипция пуста - саммари не построено.\n", encoding="utf-8")
                print("[саммари] пустая транскрипция - саммари не построено", file=sys.stderr)
        except lb.LocalBackendError as e:
            summary_path.write_text(f"> **[!] Саммари не построено.** Причина: {e}\n", encoding="utf-8")
            print(f"[саммари] ОШИБКА (транскрипция и детальный лог сохранены): {e}", file=sys.stderr)
            exit_code = exit_code or 3

    # ----- Статус прогона: что сделано, что нет и почему -----
    save_status(status_path, {
        "video": video.name,
        "speakers": name_map,
        "stages": {
            "speech": {"segments": len(segs)},
            "vision": {"enabled": use_vlm,
                       **({k: v for k, v in vision.items() if k != "records"} if vision else {})},
            "coherent": {"done": coherent_path.exists()},
            "summary": {"done": summary_done, "skipped": bool(args.no_summary)},
        },
        "exit_code": exit_code,
        "frames": (vision or {}).get("records", []),
    })

    print("\n" + "=" * 60)
    print(f"Готово (локально, без облака). Результаты в: {output_dir}")
    print(f"  - {transcript_md.name}")
    print(f"  - {detailed_path.name} (дословный)")
    if coherent_path.exists():
        print(f"  - {coherent_path.name} (связный)")
    if not args.no_summary:
        print(f"  - {summary_path.name}")
    print(f"  - {status_path.name} (статус прогона)")
    print("  - screenshots/")
    if exit_code:
        print("[!] Результат неполный (см. предупреждения выше и статус-файл).", file=sys.stderr)
    print("=" * 60)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
