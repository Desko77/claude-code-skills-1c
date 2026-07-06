"""
local_backends.py - локальные бэкенды для стадии B (разбор экрана без облака).

Два независимых блока:

  1. HTTP-клиент к LM Studio на сервере 150 (OpenAI-совместимый /v1):
     - check_server()          - проверка доступности + список моделей (/v1/models).
     - vlm_read_frame(path)     - зрение по кадру (Qwen3-VL-8B), с ретраями и guard на ужатие.
     - llm_summary_pass(...)    - текстовый проход саммари (gemma-4-26b), с ретраями.

  2. Нарезка кадров видео (ffmpeg из PATH / imageio-ffmpeg):
     - extract_scene_frames(video, out_dir) - scene-detect + пол по частоте + dhash-дедуп + кап,
       возвращает (список (timecode_sec, Path), truncated: bool). Чистит старые кадры перед стартом.

Зависимости: PIL (dhash-дедуп), стандартная библиотека. ffmpeg - из PATH, fallback imageio-ffmpeg.
Никаких обращений в облако: модуль работает только с локальным сервером 150 и локальным ffmpeg.
"""
import os
import re
import sys
import json
import time
import base64
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


def _env_float(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        print(f"[warn] некорректный {name}={v!r} (не число), использую {default}", file=sys.stderr)
        return default


def _env_int(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        print(f"[warn] некорректный {name}={v!r} (не целое), использую {default}", file=sys.stderr)
        return default


def _load_dotenv() -> None:
    """Подгрузить ~/.claude/skills/transcribe/.env: LOCAL_150_BASE, WHISPER_PYTHON, GEMINI_API_KEY, HF_TOKEN.
    Приватные значения (адрес сервера, путь к venv, токены) держим в .env - он gitignore, не в паблик-репо.
    Грузится ПЕРЕД чтением конфига ниже; analyze_video_local импортирует этот модуль первым, поэтому
    его WHISPER_PYTHON тоже видит .env."""
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


_load_dotenv()


# ============================ Конфиг (env с дефолтами) ============================

LOCAL_150_BASE = os.environ.get("LOCAL_150_BASE", "http://localhost:1234/v1")  # адрес LM Studio;
#   реальный адрес сервера задаётся через env LOCAL_150_BASE (или .env, не в паблик-репо)
LOCAL_VLM_MODEL = os.environ.get("LOCAL_VLM_MODEL", "qwen3-vl-8b-instruct")
LOCAL_SUMMARY_MODEL = os.environ.get("LOCAL_SUMMARY_MODEL", "google/gemma-4-26b-a4b")
LOCAL_SPEAKER_MODEL = os.environ.get("LOCAL_SPEAKER_MODEL", "qwen2.5-32b-instruct")  # маппинг спикеров->имена
#   (qwen2.5-32b лучше gemma на связке адрес-ответ: 4/4 vs 3/4 на РБП; для саммари наоборот - gemma).

SCENE_THRESHOLD = _env_float("SCENE_THRESHOLD", 0.30)     # порог смены сцены (0..1)
FRAME_FLOOR_SEC = _env_float("FRAME_FLOOR_SEC", 25.0)     # пол: кадр минимум каждые N сек (ловит плавные
#                                                          изменения 1С-форм, не триггерящие scene-detect). 0=выкл.
FRAME_CAP = _env_int("FRAME_CAP", 400)                    # жёсткий потолок кадров
DEDUP_HAMMING = _env_int("DEDUP_HAMMING", 6)              # dhash: <= => почти-дубль, отбрасываем
FALLBACK_INTERVAL_SEC = _env_float("FALLBACK_INTERVAL_SEC", 20.0)  # выборка если сцен/пола не хватило

HTTP_TIMEOUT = _env_int("LOCAL_HTTP_TIMEOUT", 300)
HTTP_RETRIES = _env_int("LOCAL_HTTP_RETRIES", 2)
MIN_PROMPT_TOKENS = _env_int("LOCAL_MIN_PROMPT_TOKENS", 800)  # ниже => кадр ужат сервером
VLM_MAX_TOKENS = _env_int("LOCAL_VLM_MAX_TOKENS", 5500)   # целевой потолок вывода VLM на кадр (без обрезки
#   плотных 1С/Excel-экранов; исчерпывающий режим ~4500). Реальный лимит на запрос ограничен КОНТЕКСТОМ
#   модели - см. plan_vlm_budget (маркер finish=length отловит редкий выброс сверх лимита).
VLM_PARALLEL = _env_int("LOCAL_VLM_PARALLEL", 4)          # ПОТОЛОК параллельных кадров (== "Max Concurrent
#   Predictions" в LM Studio). Фактическая параллельность урезается под контекст (слоты делят ОДНО окно -
#   unified KV cache): parallel*(VLM_PROMPT_RESERVE + max_tokens) <= context.
VLM_PROMPT_RESERVE = _env_int("LOCAL_VLM_PROMPT_RESERVE", 2600)  # резерв контекста на картинку+промпт 1
#   запроса (наблюдалось ~2464 даже для 1440p - qwen3-vl тайлит с потолком, промпт предсказуем).
VLM_FALLBACK_CONTEXT = _env_int("LOCAL_VLM_CONTEXT", 8192)  # если /api/v0/models не отдал длину контекста.

DEFAULT_FRAME_PROMPT = (
    "Это кадр экрана рабочей встречи (обычно программа 1С). "
    "Прочитай ВЕСЬ видимый текст дословно: заголовок окна/документа, поля и их значения, "
    "ВСЕ строки таблиц, кнопки, пункты меню, вкладки. Точно сохраняй числа, даты, суммы и знаки, "
    "выписывай ВСЕ коды счетов до единого, ничего не пропуская. "
    "ВАЖНО: текст на РУССКОМ. Сохраняй кириллицу дословно, НЕ заменяй русские буквы на похожие "
    "латинские или цифры (например 'БУ' и 'НУ' - это кириллица, а не 'BU'/'HU'; 'ООО' - это буквы, не '000'). "
    "Затем одной-двумя фразами опиши, какая форма/раздел открыт и что на экране происходит "
    "(что выделено или активно). Без рассуждений, только факты с экрана. Отвечай по-русски."
)


class LocalBackendError(RuntimeError):
    """Ошибка локального бэкенда (сервер 150 или ffmpeg)."""


# ============================ Утилиты ============================

def format_tc(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def ffmpeg_exe() -> str:
    """Путь к ffmpeg: сначала PATH, затем imageio-ffmpeg. Бросает LocalBackendError если нет."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise LocalBackendError(
            "ffmpeg не найден: нет в PATH и не установлен imageio-ffmpeg "
            "(pip install imageio-ffmpeg)")


# ============================ HTTP-клиент к 150 ============================

def _post_chat(model, messages, base=None, max_tokens=1400, temperature=0.2,
               extra_body=None, timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES, label=""):
    """POST /chat/completions с ретраями (backoff 2s,4s). 4xx (кроме 429) не ретраим."""
    base = base or LOCAL_150_BASE
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    if extra_body:
        payload.update(extra_body)
    data = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": "Bearer lm-studio", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:400]
            last = LocalBackendError(f"HTTP {e.code} от 150 [{label}]: {body}")
            if e.code != 429 and 400 <= e.code < 500:
                raise last  # плохой запрос/модель - ретрай не поможет
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = LocalBackendError(f"Сеть/таймаут к 150 [{label}]: {type(e).__name__}: {e}")
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    raise last or LocalBackendError(f"150 недоступен [{label}]")


def check_server(base=None):
    """Список id доступных моделей на 150. Бросает LocalBackendError если сервер не отвечает."""
    base = base or LOCAL_150_BASE
    url = base.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer lm-studio"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("id") for m in data.get("data", [])]
    except Exception as e:
        raise LocalBackendError(f"Сервер 150 недоступен ({base}): {e}")


def get_loaded_context(model=None, base=None):
    """loaded_context_length модели из нативного API LM Studio (/api/v0/models). None если недоступно."""
    model = model or LOCAL_VLM_MODEL
    root = (base or LOCAL_150_BASE).rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    url = root + "/api/v0/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer lm-studio"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        for m in data.get("data", []):
            if m.get("id") == model:
                c = m.get("loaded_context_length") or m.get("max_context_length")
                return int(c) if c else None
    except Exception:
        return None
    return None


def plan_vlm_budget(model=None, base=None, max_tokens=None, parallel_cap=None):
    """Согласовать вывод и параллельность под контекст VLM на 150.

    Слоты параллелизма LM Studio делят ОДНО окно (unified KV cache), поэтому действует
    parallel*(VLM_PROMPT_RESERVE + max_tokens) <= context. max_tokens держим (приоритет - без обрезки),
    параллельность выводим из контекста. Возвращает (context, parallel, max_tokens, source)."""
    max_tokens = max_tokens or VLM_MAX_TOKENS
    parallel_cap = parallel_cap or VLM_PARALLEL
    ctx = get_loaded_context(model, base=base)
    source = "api"
    if not ctx:
        ctx, source = VLM_FALLBACK_CONTEXT, "fallback"
    per_req = VLM_PROMPT_RESERVE + max_tokens
    if per_req <= 0:   # только при порче env (max_tokens/reserve <= 0) - защита от ZeroDivision ниже
        max_tokens = max(256, max_tokens)
        per_req = max(1, VLM_PROMPT_RESERVE) + max_tokens
    if ctx < per_req:   # контекст не вмещает даже ОДИН запрос: ужимаем вывод, чтобы печатаемый бюджет не врал
        max_tokens = max(256, ctx - VLM_PROMPT_RESERVE)
        per_req = VLM_PROMPT_RESERVE + max_tokens
        print(f"[warn] контекст VLM {ctx} мал для резерва {VLM_PROMPT_RESERVE}+вывода: "
              f"ужал max_tokens до {max_tokens}", file=sys.stderr)
    parallel = max(1, min(parallel_cap, ctx // per_req))
    return ctx, parallel, max_tokens, source


def _extract_text(resp):
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("reasoning_content") or "").strip()  # думающая модель
    return content, ch.get("finish_reason"), resp.get("usage", {}) or {}


def vlm_read_frame(image_path, model=None, prompt=None, base=None, max_tokens=None):
    """Прочитать один кадр через VLM на 150. Возвращает dict(text, prompt_tokens, ...)."""
    model = model or LOCAL_VLM_MODEL
    prompt = prompt or DEFAULT_FRAME_PROMPT
    max_tokens = max_tokens or VLM_MAX_TOKENS
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if "qwen" in model.lower() else {}
    resp = _post_chat(model, messages, base=base, max_tokens=max_tokens,
                      extra_body=extra, label=f"vlm:{Path(image_path).name}")
    text, finish, usage = _extract_text(resp)
    if not text:
        raise LocalBackendError(f"Пустой ответ VLM (finish={finish}) на {Path(image_path).name}")
    pt = usage.get("prompt_tokens")
    if pt is not None and pt < MIN_PROMPT_TOKENS:
        text = (f"> [!] prompt_tokens={pt} (мало) - кадр мог быть ужат сервером, "
                f"мелкий текст ненадёжен.\n\n") + text
    if finish == "length":
        text = text + ("\n\n> [!] описание достигло лимита вывода "
                       f"(finish=length, max_tokens={max_tokens}) - возможен обрыв хвоста, "
                       "подними LOCAL_VLM_MAX_TOKENS.")
    return {"text": text, "prompt_tokens": pt,
            "completion_tokens": usage.get("completion_tokens"), "finish": finish}


def llm_summary_pass(data_text, instruction, model=None, base=None, max_tokens=4000):
    """Один текстовый проход саммари на 150 (порядок как build_summary: данные, затем инструкция)."""
    model = model or LOCAL_SUMMARY_MODEL
    combined = f"{data_text}\n\n---\n\n{instruction}"
    messages = [{"role": "user", "content": combined}]
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if "qwen" in model.lower() else {}
    resp = _post_chat(model, messages, base=base, max_tokens=max_tokens,
                      extra_body=extra, label=f"summary:{model}")
    out, finish, _ = _extract_text(resp)
    if not out:
        raise LocalBackendError(f"Пустой ответ summary-модели {model} (finish={finish})")
    return out


# ============================ Нарезка кадров ============================

def _dhash(path, size=8):
    """Difference-hash кадра (64 бита) для отсева почти-дублей."""
    from PIL import Image
    with Image.open(path) as im:
        img = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(img.getdata())
    w = size + 1
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * w + col]
            right = px[row * w + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _run_ffmpeg_select(video, out_dir, vf, prefix):
    """Прогнать ffmpeg с фильтром select+showinfo, вернуть [(pts_time, Path), ...] по порядку."""
    ff = ffmpeg_exe()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{prefix}_%05d.png")
    cmd = [ff, "-hide_banner", "-y", "-i", str(video),
           "-vf", vf, "-vsync", "vfr", pattern]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    times = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    frames = sorted(out_dir.glob(f"{prefix}_*.png"))
    if not frames and proc.returncode != 0:
        raise LocalBackendError(f"ffmpeg завершился с кодом {proc.returncode}: "
                                f"{proc.stderr.strip()[-400:]}")
    if len(times) != len(frames):
        print(f"[warn] ffmpeg: таймкодов {len(times)} != кадров {len(frames)} - "
              f"беру min, часть кадров может быть без точного времени", file=sys.stderr)
    n = min(len(times), len(frames))
    # лишние кадры сверх n удаляем, чтобы не осели как мусор
    for extra in frames[n:]:
        extra.unlink(missing_ok=True)
    return list(zip(times[:n], frames[:n]))


def _clean_frames(out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists():
        for f in list(out_dir.glob("raw_*.png")) + list(out_dir.glob("frame_*.png")):
            f.unlink(missing_ok=True)


def extract_scene_frames(video, out_dir, threshold=None, floor_sec=None, cap=None,
                         dedup_hamming=None):
    """
    Нарезать ключевые кадры видео. scene-detect + пол по частоте -> dhash-дедуп -> кап.
    Возвращает (frames: list[(timecode_sec, Path)], truncated: bool).
    Первый кадр всегда берётся (isnan(prev_selected_t)); при отсутствии сцен - равномерная выборка.
    Старые кадры в out_dir чистятся перед стартом.
    """
    threshold = SCENE_THRESHOLD if threshold is None else threshold
    floor_sec = FRAME_FLOOR_SEC if floor_sec is None else floor_sec
    cap = FRAME_CAP if cap is None else cap
    dedup_hamming = DEDUP_HAMMING if dedup_hamming is None else dedup_hamming
    out_dir = Path(out_dir)
    _clean_frames(out_dir)  # чистый старт: не смешивать с прошлым прогоном

    # isnan(...) гарантирует захват самого первого кадра и работу пола с начала записи
    sel = f"isnan(prev_selected_t)+gt(scene,{threshold})"
    if floor_sec and floor_sec > 0:
        sel = f"{sel}+gte(t-prev_selected_t,{floor_sec})"
    raw = _run_ffmpeg_select(video, out_dir, f"select='{sel}',showinfo", "raw")

    if not raw:  # почти статичное / очень короткое видео: равномерная выборка
        fps = 1.0 / max(FALLBACK_INTERVAL_SEC, 1.0)
        raw = _run_ffmpeg_select(video, out_dir, f"fps={fps},showinfo", "raw")

    # dedup почти-дублей (последовательно)
    kept, last_hash = [], None
    for t, p in raw:
        try:
            h = _dhash(p)
        except Exception:
            h = None
        if last_hash is not None and h is not None and _hamming(h, last_hash) <= dedup_hamming:
            p.unlink(missing_ok=True)
            continue
        if h is not None:
            last_hash = h
        kept.append((t, p))

    # кап (равномерно прореживаем)
    truncated = False
    if cap and len(kept) > cap:
        truncated = True
        step = len(kept) / cap
        keep_idx = {int(i * step) for i in range(cap)}
        new_kept = []
        for i, (t, p) in enumerate(kept):
            if i in keep_idx:
                new_kept.append((t, p))
            else:
                p.unlink(missing_ok=True)
        kept = new_kept

    # стабильные имена с таймкодом (round как в format_tc, чтобы имя и заголовок совпадали)
    result = []
    for i, (t, p) in enumerate(kept):
        newp = out_dir / f"frame_{i:04d}_{int(round(t))}s.png"
        try:
            if p.resolve() != newp.resolve():
                p.replace(newp)
        except OSError as e:
            print(f"[warn] не удалось переименовать {p.name} -> {newp.name}: {e}", file=sys.stderr)
            newp = p
        result.append((t, newp))
    return result, truncated


# ============================ Smoke-тест ============================

def _smoke(video):
    print(f"[smoke] сервер 150: {LOCAL_150_BASE}")
    models = check_server()
    print(f"[smoke] моделей доступно: {len(models)}")
    for need in (LOCAL_VLM_MODEL, LOCAL_SUMMARY_MODEL):
        print(f"  - {need}: {'OK' if need in models else 'НЕ НАЙДЕНА'}")

    tmp = Path(tempfile.mkdtemp(prefix="lb_smoke_"))
    print(f"[smoke] нарезка кадров из: {video} -> {tmp}")
    t0 = time.time()
    frames, truncated = extract_scene_frames(video, tmp)
    print(f"[smoke] кадров: {len(frames)} (truncated={truncated}) за {time.time()-t0:.1f}s")
    for t, p in frames[:8]:
        print(f"    {format_tc(t)}  {p.name}")
    if not frames:
        print("[smoke] нет кадров - прерываю"); return

    print("[smoke] VLM на первом кадре...")
    t0 = time.time()
    r = vlm_read_frame(frames[0][1])
    dt_vlm = time.time() - t0
    print(f"[smoke] VLM {dt_vlm:.1f}s, prompt_tokens={r['prompt_tokens']}, finish={r['finish']}")
    print("    ---\n    " + "\n    ".join(r["text"].splitlines()[:12]))

    print("[smoke] summary-модель (замер свопа VLM->summary)...")
    t0 = time.time()
    s = llm_summary_pass("Тестовая транскрипция: обсудили отпуск и премии.",
                         "Составь одну фразу-резюме.")
    dt_sum = time.time() - t0
    print(f"[smoke] summary {dt_sum:.1f}s (включая своп модели): {s[:200]}")
    print(f"[smoke] OK. VLM/кадр~{dt_vlm:.0f}s, своп+summary~{dt_sum:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python local_backends.py <video_for_smoke_test>")
        sys.exit(1)
    _smoke(sys.argv[1])
