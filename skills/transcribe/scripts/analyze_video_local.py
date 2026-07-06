"""
analyze_video_local.py - ПОЛНОСТЬЮ ЛОКАЛЬНЫЙ разбор видео (стадия B без облака).

Аналог `transcribe.py --analyze-ui`, но без Gemini: клиентское видео не покидает сеть.

Пайплайн:
  1. Речь   - transcribe_local.py (whisper venv, CUDA) -> `<имя> - транскрипция.md/.txt`.
  2. Кадры  - local_backends.extract_scene_frames (ffmpeg scene-detect + пол + dhash-дедуп + кап).
  3. Зрение - каждый кадр -> Qwen3-VL-8B на сервере 150 (инкрементально, маркер+circuit-breaker при сбое).
  4. Лог    - `<имя> - детальный.md`: механическая сшивка по таймкодам (VLM-описание кадра +
              реплики whisper за интервал). БЕЗ отдельного LLM-прохода (осознанный компромисс MVP).
  5. Саммари- `<имя> - саммари.md`: 2 прохода на 150 (копия логики build_summary, вход = только
              текст транскрипции; детальный лог в саммари НЕ подаётся).

Инвариант: все кадры через VLM ПОЛНОСТЬЮ до summary-стадии (один своп модели на прогон).
Запуск: python analyze_video_local.py "<video>" [--output-dir DIR] [--diarize] [--no-summary]
Требует: сервер 150 доступен, модели qwen3-vl-8b-instruct и google/gemma-4-26b-a4b загружены/скачаны, ffmpeg.
"""
import os
import re
import sys
import json
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_backends as lb  # noqa: E402
import text_stage as ts  # noqa: E402
import voiceprints as vp  # noqa: E402

# Whisper живет в отдельном venv (изоляция CUDA-DLL ctranslate2 vs torch). Дефолт - venv скилла;
# реальный путь задай через env WHISPER_PYTHON (или .env, он gitignore и не в паблик-репо).
# .env уже загружен импортом local_backends выше, поэтому os.environ здесь его видит.
_DEFAULT_WHISPER_PY = Path.home() / ".claude" / "skills" / "transcribe" / "venv-whisper" / "Scripts" / "python.exe"
WHISPER_PYTHON = os.environ.get("WHISPER_PYTHON", str(_DEFAULT_WHISPER_PY))
TRANSCRIBE_LOCAL = Path(__file__).resolve().parent / "transcribe_local.py"

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
CONSEC_FAIL_ABORT = 3  # столько подряд-сбоев VLM => разбор экрана прерываем (circuit breaker)

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
        print(f"[1/5 речь] переиспользую готовую транскрипцию ({note}, --reuse-transcript): {md.name}",
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
    print(f"[1/5 речь] whisper (diarize={diarize})...", flush=True)
    rc = subprocess.run(cmd, env=env).returncode
    if md.exists() and md.stat().st_size > 0:
        if rc != 0:
            print(f"[1/5 речь] whisper вернул код {rc}, но транскрипция создана - продолжаю "
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


def analyze_frames(video: Path, output_dir: Path, segs, detailed_path: Path, vlm_model=None,
                   parallel=None, max_tokens=None):
    """Нарезать кадры, прогнать через VLM ПАРАЛЛЕЛЬНО (parallel потоков, урезан под контекст),
    детальный лог писать инкрементально СТРОГО в порядке таймкодов. Вернуть кол-во распознанных."""
    parallel = parallel or lb.VLM_PARALLEL
    max_tokens = max_tokens or lb.VLM_MAX_TOKENS
    shots_dir = output_dir / "screenshots"
    print(f"[2/5 кадры] нарезка scene-кадров -> {shots_dir}", flush=True)
    frames, truncated = lb.extract_scene_frames(video, shots_dir)
    print(f"[2/5 кадры] кадров: {len(frames)} (параллельно {parallel}, вывод/кадр {max_tokens})"
          + (" (ДОСТИГНУТ КАП - часть кадров прорежена)" if truncated else ""), flush=True)

    # clean start: заголовок пишется всегда (перезаписывает возможный старый файл)
    detailed_path.write_text(
        f"# Детальный лог (локальный разбор экрана): {video.name}\n\n"
        f"Зрение: `{vlm_model or lb.LOCAL_VLM_MODEL}` (локально, сервер 150, параллельно {parallel}). "
        f"Кадров: {len(frames)}" + (" [достигнут кап]" if truncated else "") + "\n\n---\n\n",
        encoding="utf-8")
    if not frames:
        _append(detailed_path, "> **[!] Кадры не извлечены** (пустое/битое видео?).\n")
        return 0

    n = len(frames)
    results = {}        # i -> готовый текст описания (или маркер сбоя)
    ok = 0
    next_write = 0      # индекс следующего кадра к записи: пишем строго по возрастанию таймкода
    consec_fail = 0
    aborted = False

    def flush_ready():  # дозаписать все готовые кадры, идущие подряд от next_write
        nonlocal next_write
        while next_write in results:
            _append(detailed_path, _frame_block(next_write, frames, n, segs, results[next_write]))
            next_write += 1

    # ожидаемые сбои VLM (сеть/сервер/пустой ответ) маскируем маркером; программные ошибки
    # (KeyError и т.п.) прилетают из fut.result() и НЕ ловятся здесь - пусть падают громко.
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(lb.vlm_read_frame, fpath, model=vlm_model, max_tokens=max_tokens): i
                for i, (t, fpath) in enumerate(frames)}
        for fut in as_completed(futs):
            i = futs[fut]
            t = frames[i][0]
            try:
                r = fut.result()
                results[i] = r["text"]
                ok += 1
                consec_fail = 0
                print(f"  [кадр {i+1}/{n}] {lb.format_tc(t)}  VLM ok "
                      f"(pt={r['prompt_tokens']}, {r['finish']})", flush=True)
            except lb.LocalBackendError as e:
                results[i] = f"> **[!] Кадр не распознан.** Причина: {e}"
                consec_fail += 1
                print(f"  [кадр {i+1}/{n}] {lb.format_tc(t)}  VLM FAIL: {e}",
                      file=sys.stderr, flush=True)
            flush_ready()
            if consec_fail >= CONSEC_FAIL_ABORT:  # сервер лёг - прерываем, пишем маркер
                aborted = True
                for f in futs:
                    f.cancel()
                break

    if aborted:
        _append(detailed_path,
                f"\n> **[!] VLM сбоит {consec_fail} кадров подряд - разбор экрана прерван "
                f"(записано {next_write}/{n} кадров по порядку, остальные пропущены).**\n")
        raise lb.LocalBackendError(
            f"VLM недоступен/сбоит {consec_fail} кадров подряд - прерываю разбор экрана")
    return ok


# ---------------- Шаг 5: текстовая стадия (общий text_stage) ----------------

def _transcript_text(segs):
    """Текст транскрипции из сегментов [(sec, text)] для текстовой стадии."""
    return "\n".join(f"[{lb.format_tc(s)}] {txt}" for s, txt in segs if txt)


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser(description="Локальный разбор видео (whisper + VLM/LLM на 150), без облака")
    ap.add_argument("video", help="Путь к видеофайлу")
    ap.add_argument("--output-dir", "-o", default=None)
    ap.add_argument("--diarize", action="store_true", help="Диаризация речи (whisper); спикеры попадут в лог/саммари")
    ap.add_argument("--num-speakers", type=int, default=None, help="Точное число спикеров для диаризации (автодетект ненадёжен)")
    ap.add_argument("--no-summary", action="store_true", help="Не строить саммари")
    ap.add_argument("--no-coherent", action="store_true", help="Не строить связный лог (быстрее)")
    ap.add_argument("--reuse-transcript", action="store_true",
                    help="Переиспользовать готовую транскрипцию (не гонять whisper заново), если файл уже есть и непуст")
    ap.add_argument("--vlm-model", default=None, help=f"VLM на 150 (по умолч. {lb.LOCAL_VLM_MODEL})")
    ap.add_argument("--summary-model", default=None, help=f"Summary на 150 (по умолч. {lb.LOCAL_SUMMARY_MODEL})")
    ap.add_argument("--speaker-model", default=None, help=f"Маппинг спикеров (по умолч. {lb.LOCAL_SPEAKER_MODEL})")
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
        """LLM-вызов маппинга спикеров на 150 (qwen - лучше на связке имён, 4/4 vs 3/4)."""
        return lb.llm_summary_pass(data, instruction, model=speaker_model, max_tokens=2000)

    transcript_md = output_dir / f"{video.stem} - транскрипция.md"
    detailed_path = output_dir / f"{video.stem} - детальный.md"
    coherent_path = output_dir / f"{video.stem} - связный.md"
    summary_path = output_dir / f"{video.stem} - саммари.md"

    # ----- Предполётная проверка: 150 + модели + ffmpeg -----
    print(f"[0/5] проверка сервера 150: {lb.LOCAL_150_BASE}", flush=True)
    try:
        models = lb.check_server()
    except lb.LocalBackendError as e:
        print(f"ОШИБКА: {e}\nСервер 150 недоступен - локальный разбор невозможен. "
              f"Проверь LM Studio на {lb.LOCAL_150_BASE}.", file=sys.stderr)
        sys.exit(2)
    if vlm_model not in models:
        print(f"ОШИБКА: VLM-модель '{vlm_model}' не найдена на 150. Доступны: {', '.join(models)}",
              file=sys.stderr)
        sys.exit(2)
    if summary_model not in models:  # нужна для текстовой стадии (связный лог/саммари)
        print(f"ОШИБКА: text-модель '{summary_model}' не найдена на 150. Доступны: {', '.join(models)}",
              file=sys.stderr)
        sys.exit(2)
    if speaker_model not in models:  # маппинг спикеров->имена
        print(f"ОШИБКА: speaker-модель '{speaker_model}' не найдена на 150. Доступны: {', '.join(models)}",
              file=sys.stderr)
        sys.exit(2)
    try:
        lb.ffmpeg_exe()
    except lb.LocalBackendError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"[0/5] OK: VLM={vlm_model}, speakers={speaker_model}, summary={summary_model}", flush=True)
    ctx_len, vlm_parallel, vlm_max_tokens, ctx_src = lb.plan_vlm_budget(vlm_model)
    print(f"[0/5] VLM-бюджет: контекст={ctx_len} ({ctx_src}), вывод/кадр={vlm_max_tokens}, "
          f"параллельно={vlm_parallel} "
          f"[{vlm_parallel}*({lb.VLM_PROMPT_RESERVE}+{vlm_max_tokens}) <= {ctx_len}]", flush=True)

    # ----- clean start: не выдать результаты прошлого прогона за текущие -----
    if not args.reuse_transcript:
        transcript_md.write_text("", encoding="utf-8")
    if args.no_summary:
        summary_path.unlink(missing_ok=True)  # не оставляем старое саммари, раз его не просили
    else:
        summary_path.write_text("", encoding="utf-8")
    # detailed_path сбрасывается внутри analyze_frames

    # ----- 1. Речь -----
    diar_extra = ["--num-speakers", str(args.num_speakers)] if args.num_speakers else None
    transcript_md = run_whisper(video, output_dir, diarize=args.diarize, reuse=args.reuse_transcript,
                                extra=diar_extra)
    segs = parse_transcript(output_dir, video.stem)
    print(f"[1/5 речь] сегментов транскрипции: {len(segs)}"
          + (" (со спикерами)" if (output_dir / f'{video.stem} - со спикерами.md').exists() else ""),
          flush=True)

    # ----- 2-4. Кадры + зрение + детальный лог -----
    exit_code = 0
    try:
        ok = analyze_frames(video, output_dir, segs, detailed_path, vlm_model=vlm_model,
                            parallel=vlm_parallel, max_tokens=vlm_max_tokens)
    except lb.LocalBackendError as e:
        print(f"[3-4/5] разбор экрана прерван: {e}\n"
              f"         (транскрипция сохранена, перехожу к саммари).", file=sys.stderr)
        ok = 0
        exit_code = 3
    else:
        print(f"[3-4/5] детальный лог готов: распознано кадров {ok}", flush=True)
        if ok == 0:
            print("[3-4/5] ВНИМАНИЕ: ни один кадр не распознан - детальный лог только из маркеров.",
                  file=sys.stderr)
            exit_code = 3

    # ----- 5. Текстовая стадия на 150 (gemma): спикеры -> имена, связный лог, саммари -----
    # После всех кадров - один своп VLM -> gemma на весь блок.
    transcript_text = _transcript_text(segs)

    # 5.1 Спикеры -> имена. СЛОЙ 1 - голос (база отпечатков, cosine > порог): узнаёт различимых даже
    #     неназванных и между встречами (сверх Gemini). СЛОЙ 2 - текст (in-context, qwen): похожие голоса
    #     и остальные. Голос приоритетнее. Авто-enroll: названных текстом дописываем в базу (бутстрап).
    name_map = {}
    if transcript_text.strip():
        vp_path = output_dir / f"{video.stem}.voiceprints.json"
        use_voice = (not args.no_voiceprints) and vp_path.exists()
        db, prints, voice_ids = None, {}, {}
        if use_voice:
            try:
                db = vp.load_db(voiceprint_db)
                prints = json.loads(vp_path.read_text(encoding="utf-8"))
                voice_ids = vp.identify(prints, db)
                if voice_ids:
                    print("[5/7 спикеры] по голосу: "
                          + ", ".join(f"{k}->{n}({s})" for k, (n, s) in voice_ids.items()), flush=True)
            except Exception as e:
                use_voice = False
                print(f"[5/7 спикеры] голосовой слой пропущен ({e})", file=sys.stderr)
        try:
            text_names = ts.map_speakers(transcript_text, speaker_llm)
        except lb.LocalBackendError as e:
            text_names = {}
            print(f"[5/7 спикеры] текстовый слой пропущен ({e})", file=sys.stderr)
        for label, (name, _score) in voice_ids.items():   # голос приоритетнее текста
            name_map[label] = name
        for label, name in text_names.items():
            name_map.setdefault(label, name)
        if use_voice and db is not None and text_names:   # авто-enroll: текст назвал, голос - нет
            # Неоднозначные имена (текст повесил одно имя на >1 метку) НЕ заносим: иначе в одну запись
            # базы попадут голоса РАЗНЫХ людей и отпечаток испортится. Заносим только имена, однозначно
            # привязанные к одной метке в этом прогоне (защита персистентной базы от самопорчи).
            name_counts = {}
            for n in text_names.values():
                name_counts[n] = name_counts.get(n, 0) + 1
            added, skipped = 0, 0
            for label, name in text_names.items():
                if label in voice_ids or label not in prints:
                    continue
                if name_counts[name] > 1:   # имя висит на нескольких метках - неоднозначно, пропускаем
                    skipped += 1
                    continue
                if not vp.is_plausible_name(name):   # мусорное имя (КС/инициалы/огрызок) - не засоряем базу
                    skipped += 1
                    continue
                vp.enroll(db, name, prints[label], project=args.project, meeting=video.stem)
                added += 1
            if added:
                try:
                    vp.save_db(db, voiceprint_db)
                    msg = f"[5/7 спикеры] авто-enroll в базу: +{added} голос(ов)"
                    if skipped:
                        msg += f" (пропущено неоднозначных: {skipped})"
                    print(msg, flush=True)
                except Exception as e:
                    print(f"[5/7 спикеры] авто-enroll не сохранён ({e})", file=sys.stderr)
            elif skipped:
                print(f"[5/7 спикеры] авто-enroll пропущен: все {skipped} имён неоднозначны", flush=True)

    if name_map:
        print(f"[5/7 спикеры] итог: {', '.join(f'{k}->{v}' for k, v in name_map.items())}", flush=True)
        if detailed_path.exists():
            detailed_path.write_text(
                ts.apply_names(detailed_path.read_text(encoding="utf-8"), name_map), encoding="utf-8")
        segs = [(s, ts.apply_names(t, name_map)) for s, t in segs]
        transcript_text = _transcript_text(segs)
    else:
        print("[5/7 спикеры] имена не определены - оставляю метки", flush=True)

    # 5.2 Связный лог (нарратив из механического детального)
    coherent_path.unlink(missing_ok=True)  # чистый старт: не оставить старый связный лог
    if args.no_coherent:
        print("[6/7 связный] пропущено (--no-coherent)", flush=True)
    elif detailed_path.exists():
        print("[6/7 связный] сборка связного нарратива (чанками)...", flush=True)
        try:
            coherent = ts.build_coherent_log(detailed_path.read_text(encoding="utf-8"), gemma_llm)
            if coherent:
                coherent_path.write_text(
                    f"# Связный лог (экран + речь): {video.name}\n\n{coherent}\n", encoding="utf-8")
                print(f"[6/7 связный] сохранено: {coherent_path.name}", flush=True)
        except lb.LocalBackendError as e:
            print(f"[6/7 связный] ОШИБКА (пропускаю): {e}", file=sys.stderr)

    # 5.3 Саммари (протокол задач/решений из полного текста)
    if args.no_summary:
        print("[7/7 саммари] пропущено (--no-summary)", flush=True)
    else:
        print("[7/7 саммари] генерация протокола...", flush=True)
        try:
            summary = ts.build_summary(transcript_text, gemma_llm)
            if summary:
                summary_path.write_text(summary, encoding="utf-8")
                print(f"[7/7 саммари] сохранено: {summary_path.name}", flush=True)
            else:
                summary_path.write_text("> Транскрипция пуста - саммари не построено.\n", encoding="utf-8")
                print("[7/7 саммари] пустая транскрипция - саммари не построено", file=sys.stderr)
        except lb.LocalBackendError as e:
            summary_path.write_text(f"> **[!] Саммари не построено.** Причина: {e}\n", encoding="utf-8")
            print(f"[7/7 саммари] ОШИБКА (транскрипция и детальный лог сохранены): {e}", file=sys.stderr)

    print("\n" + "=" * 60)
    print(f"Готово (локально, без облака). Результаты в: {output_dir}")
    print(f"  - {transcript_md.name}")
    print(f"  - {detailed_path.name} (дословный)")
    if coherent_path.exists():
        print(f"  - {coherent_path.name} (связный)")
    if not args.no_summary:
        print(f"  - {summary_path.name}")
    print(f"  - screenshots/")
    if exit_code:
        print("[!] Разбор экрана неполный (см. предупреждения выше).", file=sys.stderr)
    print("=" * 60)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
