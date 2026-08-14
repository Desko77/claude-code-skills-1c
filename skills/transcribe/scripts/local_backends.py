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
VLM_PROMPT_RESERVE = _env_int("LOCAL_VLM_PROMPT_RESERVE", 2600)  # НАЧАЛЬНАЯ оценка резерва контекста
#   на картинку+промпт одного запроса. Оценка сверху и обычно завышена вдвое (замер на видео - 1196),
#   поэтому фактическое значение меряется на первом кадре: см. replan_with_measured.
VLM_FALLBACK_CONTEXT = _env_int("LOCAL_VLM_CONTEXT", 8192)  # если /api/v0/models не отдал длину контекста.

DEFAULT_FRAME_PROMPT = (
    "Это кадр экрана рабочей встречи (обычно программа 1С). "
    "Прочитай ВЕСЬ видимый текст дословно: заголовок окна/документа, поля и их значения, "
    "ВСЕ строки таблиц, кнопки, пункты меню, вкладки. Точно сохраняй числа, даты, суммы и знаки, "
    "выписывай ВСЕ коды счетов до единого, ничего не пропуская. "
    "ВАЖНО: текст на РУССКОМ. Сохраняй кириллицу дословно, НЕ заменяй русские буквы на похожие "
    "латинские или цифры (например 'БУ' и 'НУ' - это кириллица, а не 'BU'/'HU'; 'ООО' - это буквы, не '000'). "
    "НИЧЕГО НЕ ДОДУМЫВАЙ. Пиши только то, что реально видно на этом кадре. Нечитаемое "
    "(размыто, мелко, перекрыто, обрезано) так и помечай: 'не читается'. Пустое поле описывай "
    "как пустое. НЕ подставляй правдоподобные названия организаций, суммы, номера документов, "
    "даты и коды вместо тех, что не разобрал, и не приводи примеров - лучше признать, что не "
    "видно, чем назвать похожее. "
    "Затем одной-двумя фразами опиши, какая форма/раздел открыт и что на экране происходит "
    "(что выделено или активно). Без рассуждений, только факты с экрана. Отвечай по-русски."
)


class LocalBackendError(RuntimeError):
    """Ошибка локального бэкенда (сервер 150 или ffmpeg).

    status/elapsed нужны, чтобы отличить выгруженную из памяти модель от настоящей поломки:
    текст ошибки для этого не годится (LM Studio отдаёт generic-страницу), а время - годится.
    """

    def __init__(self, message, status=None, elapsed=None):
        super().__init__(message)
        self.status = status      # HTTP-код, если ошибка пришла от сервера
        self.elapsed = elapsed    # сколько секунд заняла неудачная попытка


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
        t0 = time.time()
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": "Bearer lm-studio", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:400]
            last = LocalBackendError(f"HTTP {e.code} от 150 [{label}]: {body}",
                                     status=e.code, elapsed=time.time() - t0)
            if e.code != 429 and 400 <= e.code < 500:
                raise last  # плохой запрос/модель - ретрай не поможет
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = LocalBackendError(f"Сеть/таймаут к 150 [{label}]: {type(e).__name__}: {e}",
                                     elapsed=time.time() - t0)
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    raise last or LocalBackendError(f"150 недоступен [{label}]")


UNLOADED_MAX_SECONDS = _env_float("LOCAL_UNLOADED_MAX_SECONDS", 1.0)


def looks_unloaded(err):
    """Похоже ли, что модель просто выгружена из памяти, а не сломалась.

    Отличаем по ВРЕМЕНИ, а не по тексту: на запрос к выгруженной модели LM Studio отвечает generic
    ошибкой без внятного содержания, зато почти мгновенно, тогда как настоящая генерация занимает
    секунды. Нужно, чтобы выгрузка по TTL посреди прогона не засчитывалась как сбой сервера.
    """
    status = getattr(err, "status", None)
    elapsed = getattr(err, "elapsed", None)
    return bool(status and status >= 500 and elapsed is not None
                and elapsed < UNLOADED_MAX_SECONDS)


def looks_context_overflow(err):
    """Похоже ли, что запрос не влез в контекст, а не сервер сломался.

    Это НЕ повод бросать кадр: слоты LM Studio делят одно окно, поэтому виновата параллельность,
    а сам запрос корректен. Лечится снижением параллельности и повтором. Принимает и исключение,
    и уже сохранённый текст ошибки - в статус-файл попадает строка.
    """
    text = str(err or "").lower()
    status = getattr(err, "status", None)
    if not (status == 400 or "http 400" in text):
        return False
    return any(k in text for k in ("context", "exceed", "too long", "too large", "token",
                                   "контекст"))


def ensure_loaded(model=None, base=None, timeout=600):
    """Убедиться, что модель в памяти: прогреть и проверить по каталогу. True если готова."""
    model = model or LOCAL_VLM_MODEL
    if get_loaded_info(model, base=base)["loaded"]:
        return True
    warmup_model(model, base=base, timeout=timeout)
    return get_loaded_info(model, base=base)["loaded"]


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


def _api_root(base=None):
    """Корень сервера без суффикса /v1: нативные эндпоинты LM Studio живут от корня."""
    root = (base or LOCAL_150_BASE).rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root


def _get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer lm-studio"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _model_matches(entry, model):
    """Совпадает ли запись каталога с запрошенным именем модели (с учётом варианта квантизации)."""
    if model in (entry.get("key"), entry.get("id"), entry.get("selected_variant")):
        return True
    return model in (entry.get("variants") or [])


def get_loaded_info(model=None, base=None):
    """Что сервер знает о модели ПРЯМО СЕЙЧАС: загружена ли и с какими параметрами.

    Возвращает dict(loaded, context, parallel, reasoning); context и parallel заполняются ТОЛЬКО
    для загруженной модели. Паспортный max_context_length сознательно не подставляется: у
    выгруженной модели он на порядок больше рабочего (262144 против фактических 32000), и
    посчитанный от него бюджет переполняет контекст на первом же параллельном кадре.
    """
    model = model or LOCAL_VLM_MODEL
    root = _api_root(base)
    info = {"loaded": False, "context": None, "parallel": None, "reasoning": None}

    try:  # /api/v1 точнее: отдаёт конфиг конкретного загруженного инстанса
        for m in _get_json(root + "/api/v1/models").get("models", []):
            if not _model_matches(m, model):
                continue
            caps = (m.get("capabilities") or {}).get("reasoning") or {}
            info["reasoning"] = caps.get("allowed_options") or None
            inst = m.get("loaded_instances") or []
            if inst:
                cfg = inst[0].get("config") or {}
                info.update(loaded=True, context=cfg.get("context_length"),
                            parallel=cfg.get("parallel"))
            return info
    except Exception:
        pass

    try:  # сборки LM Studio без /api/v1: состояние приходит отдельным полем state
        for m in _get_json(root + "/api/v0/models").get("data", []):
            if not _model_matches(m, model):
                continue
            if m.get("state") == "loaded":
                info.update(loaded=True, context=m.get("loaded_context_length"))
            return info
    except Exception:
        pass
    return info


def get_loaded_context(model=None, base=None):
    """Рабочий контекст ЗАГРУЖЕННОЙ модели. None если она выгружена или сервер не отвечает."""
    c = get_loaded_info(model, base=base).get("context")
    return int(c) if c else None


def warmup_model(model=None, base=None, timeout=180):
    """JIT-прогрев: крошечный запрос, чтобы LM Studio загрузил модель (с сохранённым в её конфиге
    контекстом) ДО расчёта бюджета. Иначе на холодном старте (модель выгружена по TTL)
    get_loaded_context вернёт None -> бюджет уйдёт в fallback -> parallel=1, хотя модель грузится
    на 32768. Возвращает True при ответе."""
    model = model or LOCAL_VLM_MODEL
    root = (base or LOCAL_150_BASE).rstrip("/")
    body = {"model": model, "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1, "temperature": 0}
    req = urllib.request.Request(
        root + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except Exception as e:
        print(f"[warmup] прогрев {model} не удался: {e}", file=sys.stderr)
        return False


def fit_parallel(context, reserve, max_tokens, parallel_cap):
    """Сколько кадров слать одновременно. Слоты LM Studio делят ОДНО окно (unified KV cache),
    поэтому действует parallel*(reserve + max_tokens) <= context."""
    per_req = max(1, reserve) + max(1, max_tokens)   # max(1) - защита от порченого env
    return max(1, min(parallel_cap, context // per_req))


def plan_vlm_budget(model=None, base=None, max_tokens=None, parallel_cap=None):
    """Согласовать вывод и параллельность под контекст ЗАГРУЖЕННОЙ VLM на 150.

    Возвращает dict(context, parallel, max_tokens, reserve, cap, source, measured). Резерв на этой
    стадии - оценка из конфига; фактический меряется на первом кадре (see replan_with_measured).
    """
    max_tokens = max_tokens or VLM_MAX_TOKENS
    parallel_cap = parallel_cap or VLM_PARALLEL
    info = get_loaded_info(model, base=base)
    if not info["loaded"]:   # выгружена по TTL - прогреть и перемерить, иначе бюджет уйдёт в fallback
        warmup_model(model, base=base)
        info = get_loaded_info(model, base=base)
    ctx, source = info.get("context"), "api"
    if not ctx:
        ctx, source = VLM_FALLBACK_CONTEXT, "fallback"
    if info.get("parallel"):   # сервер знает свой реальный потолок слотов - он главнее догадки из env
        parallel_cap = min(parallel_cap, int(info["parallel"]))
    reserve = VLM_PROMPT_RESERVE
    if ctx < reserve + max_tokens:   # контекст не вмещает даже ОДИН запрос: ужимаем вывод,
        max_tokens = max(256, ctx - reserve)   # чтобы печатаемый бюджет не врал
        print(f"[warn] контекст VLM {ctx} мал для резерва {reserve}+вывода: "
              f"ужал max_tokens до {max_tokens}", file=sys.stderr)
    return {"context": ctx, "parallel": fit_parallel(ctx, reserve, max_tokens, parallel_cap),
            "max_tokens": max_tokens, "reserve": reserve, "cap": parallel_cap,
            "source": source, "measured": False}


def replan_with_measured(budget, prompt_tokens, headroom=1.15):
    """Пересчитать бюджет под ИЗМЕРЕННЫЙ на первом кадре размер промпта.

    prompt_tokens кадра практически постоянен (зависит от разрешения, а не от содержимого экрана),
    поэтому одного замера достаточно на весь прогон. Константа из конфига - оценка сверху и обычно
    завышена вдвое, а завышенный резерв режет параллельность на ровном месте. Запас headroom - на
    разброс тайлинга между кадрами. Возвращает НОВЫЙ dict, исходный не меняет.
    """
    if not prompt_tokens or prompt_tokens <= 0:
        return budget
    out = dict(budget)
    out["reserve"] = int(prompt_tokens * headroom)
    out["measured"] = True
    out["parallel"] = fit_parallel(out["context"], out["reserve"], out["max_tokens"], out["cap"])
    return out


def _extract_text(resp, allow_reasoning=True):
    """Текст ответа OpenAI-совместимого эндпоинта.

    allow_reasoning=False обязателен для задач со СТРОГИМ форматом (JSON спикеров): думающая модель
    может отдать пустой content, положив весь вывод в reasoning_content. Подстановка размышлений
    вместо ответа превращает явный отказ в тихо неверный результат - для строгих задач это ошибка.
    """
    ch = (resp.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    content = (msg.get("content") or "").strip()
    if not content and allow_reasoning:
        content = (msg.get("reasoning_content") or "").strip()
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
    # Зрение остаётся на OpenAI-совместимом эндпоинте: нативный /api/v1/chat принимает только
    # текстовый input, картинку туда не передать.
    resp = _post_chat(model, messages, base=base, max_tokens=max_tokens,
                      label=f"vlm:{Path(image_path).name}")
    # allow_reasoning=False: описание экрана - строгая задача. Размышления вместо распознанного
    # текста выглядят как валидный ответ и молча уезжают в лог, поэтому лучше явный сбой кадра.
    text, finish, usage = _extract_text(resp, allow_reasoning=False)
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


def _post_native_chat(model, input_text, base=None, reasoning="off", max_output_tokens=4000,
                      temperature=0.2, timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES, label=""):
    """POST /api/v1/chat - нативный эндпоинт LM Studio, ретраи как у _post_chat.

    Нужен ради параметра `reasoning`: на /v1/chat/completions он молча игнорируется (проверено на
    150: off и on дают идентичный ответ), а chat_template_kwargs.enable_thinking для qwen3.x мёртв.
    Размышления стоят 45-кратного времени и корневую ошибку привязки имён не лечат - по умолчанию off.
    """
    url = _api_root(base) + "/api/v1/chat"
    payload = {"model": model, "input": input_text, "reasoning": reasoning,
               "max_output_tokens": max_output_tokens, "temperature": temperature}
    data = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": "Bearer lm-studio", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:400]
            last = LocalBackendError(f"HTTP {e.code} от 150 [{label}]: {body}",
                                     status=e.code, elapsed=time.time() - t0)
            if e.code != 429 and 400 <= e.code < 500:
                raise last  # плохой запрос/модель - ретрай не поможет
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = LocalBackendError(f"Сеть/таймаут к 150 [{label}]: {type(e).__name__}: {e}",
                                     elapsed=time.time() - t0)
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    raise last or LocalBackendError(f"150 недоступен [{label}]")


def _extract_native(resp, allow_reasoning=False):
    """Текст из ответа /api/v1/chat: output[] содержит элементы type=message и/или type=reasoning.

    При reasoning=on и упоре в потолок токенов ответ состоит ТОЛЬКО из размышлений, без единого
    message - вернуть их вместо ответа нельзя по той же причине, что и в _extract_text.
    """
    out = resp.get("output") or []
    text = "\n".join((o.get("content") or "") for o in out if o.get("type") == "message").strip()
    if not text and allow_reasoning:
        text = "\n".join((o.get("content") or "") for o in out
                         if o.get("type") == "reasoning").strip()
    return text, resp.get("stats", {}) or {}


def llm_summary_pass(data_text, instruction, model=None, base=None, max_tokens=4000,
                     reasoning="off"):
    """Один СВОБОДНЫЙ текстовый проход на 150 (порядок как в build_summary: данные, затем инструкция)."""
    model = model or LOCAL_SUMMARY_MODEL
    combined = f"{data_text}\n\n---\n\n{instruction}"
    resp = _post_native_chat(model, combined, base=base, reasoning=reasoning,
                             max_output_tokens=max_tokens, label=f"text:{model}")
    out, stats = _extract_native(resp)
    if not out:
        raise LocalBackendError(
            f"Пустой ответ text-модели {model} (вывод {stats.get('total_output_tokens')} ток., "
            f"из них размышления {stats.get('reasoning_output_tokens')})")
    produced = stats.get("total_output_tokens") or 0
    if produced >= max_tokens:   # упёрлись в потолок - хвост почти наверняка обрезан
        print(f"[warn] {model}: вывод достиг потолка {max_tokens} токенов - возможен обрыв хвоста",
              file=sys.stderr)
    return out


def llm_json_pass(data_text, instruction, schema, model=None, base=None, max_tokens=2000):
    """Строгий JSON-проход: формат гарантирует СЕРВЕР (response_format=json_schema), а не послушание
    модели. Живёт на /v1/chat/completions - нативный /api/v1/chat схемы вывода не принимает.

    Пустой ответ и невалидный JSON - громкая ошибка: тихо неверный маппинг спикеров дороже отказа.
    """
    model = model or LOCAL_SPEAKER_MODEL
    combined = f"{data_text}\n\n---\n\n{instruction}"
    extra = {"response_format": {"type": "json_schema", "json_schema": {
        "name": "result", "strict": True, "schema": schema}}}
    resp = _post_chat(model, [{"role": "user", "content": combined}], base=base,
                      max_tokens=max_tokens, temperature=0, extra_body=extra, label=f"json:{model}")
    text, finish, _ = _extract_text(resp, allow_reasoning=False)
    if not text:
        raise LocalBackendError(f"Пустой ответ модели {model} на строгий JSON (finish={finish})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LocalBackendError(f"Модель {model} вернула невалидный JSON ({e}): {text[:300]}")


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
