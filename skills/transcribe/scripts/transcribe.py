"""
Транскрибация аудио и видео через Gemini API.

Два режима:
- Generic (по умолчанию): verbatim-транскрипция речи с таймкодами
- Analyze-UI (--analyze-ui, только видео): саммари + детальный лог + скриншоты + транскрипция

Установка:
    pip install google-genai python-dotenv

Использование:
    python transcribe.py "запись.mp3"
    python transcribe.py "встреча.mp4" --analyze-ui
    python transcribe.py "подкаст.wav" --with-summary --output-dir "./результат"

API-ключ: переменная окружения GEMINI_API_KEY или файл .env
(ищет в ~/.claude/skills/transcribe/.env, ~/.claude/skills/video-transcribe/.env, затем в cwd).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

# Загрузка .env: приоритет transcribe > video-transcribe > cwd
_home = Path.home()
for _env_path in [
    _home / ".claude" / "skills" / "transcribe" / ".env",
    _home / ".claude" / "skills" / "video-transcribe" / ".env",
]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
load_dotenv()  # cwd/.env как fallback

import httpx
from google import genai
from google.genai import errors, types

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# === Модели Gemini и авто-fallback при перегрузке ===

# Стартовая модель по умолчанию: ПИН на конкретную версию gemini-2.5-flash (не плавающий алиас).
# Плавающий gemini-flash-latest дрейфовал в gemini-3.5-flash (видео-вход 5x, выход 3.6x дороже) -
# это дало 96% счета за Gemini в июне 2026. Явная версия не дрейфует.
DEFAULT_MODEL = "gemini-2.5-flash"

# Цепочка перебора при 503/429 - ТОЛЬКО дешевые модели 2.5. Сознательно НЕ уходим в дорогие
# gemini-3.5-flash / *-pro / плавающие *-latest (в 4-5x дороже, именно на них утекал счет).
# Если оба варианта перегружены - лучше отказ, чем молчаливая переплата в 5x. Обе видео-capable,
# output 65536 / input 1M. Переопределяется через --model / --fallback-models / env.
DEFAULT_FALLBACK_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

# HTTP-коды, при которых переходим к следующей модели (SDK уже отретраил - модель устойчиво лежит).
RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
# Модель недоступна для ключа (напр. preview не у всех) - тоже к следующей, но без ожидания.
MODEL_UNAVAILABLE_CODES = {404}

# === Промпты: Generic ===

PROMPT_TRANSCRIBE = """Транскрибируй всю речь из этой записи дословно.

Требования:
1. Таймкоды [MM:SS] каждые 30-60 секунд или при смене спикера
2. Идентификация спикеров (Спикер 1, Спикер 2, или по имени если названо)
3. Значимые неречевые звуки в скобках: [смех], [пауза], [шум]
4. Сохраняй оригинальный язык записи
5. Дословная транскрипция, не пересказ

Отвечай на языке записи. Формат - Markdown с таймкодами."""

# Проход 1 саммари: экстрактор всех фактов из текста транскрипции (контроль полноты).
PROMPT_TASKS_EXTRACT = """Перед тобой полная дословная транскрипция рабочей встречи. Извлеки из нее АБСОЛЮТНО ВСЕ конкретные пункты, ничего не обобщая и не пропуская.

Пройди транскрипцию последовательно от начала до конца и выпиши:

## Задачи и поручения
Каждую задачу, поручение, договоренность что-то сделать - отдельным пунктом. Даже если упомянуто вскользь, одной фразой, между делом. Для каждой: что сделать, кто ответственный (если назван), срок (если назван), таймкод [MM:SS].

## Решения
Каждое принятое решение - отдельным пунктом, с таймкодом.

## Открытые вопросы
Каждый незакрытый вопрос, разногласие, "надо уточнить" - отдельным пунктом, с таймкодом.

## Важные детали
Прочие значимые факты: цифры, условия, названия систем и документов, сроки, которые прозвучали и могут понадобиться.

Правила:
- Полнота важнее краткости. Лучше включить лишнее, чем упустить.
- НЕ объединяй несколько пунктов в один. Каждое поручение - отдельной строкой.
- Сохраняй конкретику дословно: имена, цифры, названия, сроки.
- Только то, что реально прозвучало в транскрипции. Ничего не выдумывай.

Отвечай на языке транскрипции."""


# Проход 2 саммари: протокол из текста транскрипции + извлеченных фактов (гарантия полноты).
PROMPT_SUMMARY_FROM_TEXT = """Перед тобой полная транскрипция рабочей встречи и предварительно извлеченный из нее список фактов (задачи, решения, открытые вопросы, детали). Составь по ним структурированный протокол встречи.

КЛЮЧЕВОЕ ТРЕБОВАНИЕ: протокол обязан включить ВСЕ пункты из списка фактов - ни одна задача, решение или открытый вопрос не должны потеряться. Список фактов - это контроль полноты; транскрипция - источник контекста, формулировок и связей.

Формат протокола (строго соблюдай структуру и заголовки):

---

## Цель встречи
Один абзац - зачем собрались, что хотели обсудить/решить.

## Участники
Список участников с именами и ролями (если определяются).

## Ключевые темы и фокус обсуждения
Нумерованный список основных тем. Каждая тема - заголовок и 1-2 предложения пояснения.

## Решения
Нумерованный список всех принятых решений. Каждое - отдельным пунктом, подробно, с таймкодом.

## Открытые вопросы
Нумерованный список всех нерешенных вопросов. Для каждого - почему отложено или что нужно для решения, с таймкодом.

## Задачи
Группируй по ответственному. Для каждого человека - нумерованный список задач.
Формат:
### Имя (Роль)
1. Описание задачи. Срок: дата или "не определен". Таймкод [MM:SS]
2. ...
Задачи без явного ответственного - в группу "### Без ответственного".

---

Отвечай на языке транскрипции. По делу, но с достаточной детализацией, чтобы человек не присутствовавший на встрече понял контекст. Перепроверь себя: каждый факт из списка должен найти место в протоколе."""

# === Промпты: Analyze-UI (анализ интерфейсов) ===
# Саммари в analyze-ui строится из текста транскрипции через build_summary
# (полнее по задачам/решениям, чем разбор видео), отдельного UI-промпта саммари нет.

PROMPT_UI_DETAILED = """Ты анализируешь видеозапись рабочей встречи, на которой демонстрируются бизнес-процессы
и интерфейсы программ (1С и другие).

Сделай МАКСИМАЛЬНО ДЕТАЛЬНЫЙ пошаговый анализ видео. Не обобщай - описывай каждое действие.

## Требования к детализации:

### 1. Пошаговый хронологический лог (основная часть)
Для каждого значимого момента (каждые 10-30 секунд или при смене экрана/действия):
- **[MM:SS]** Что именно происходит на экране
- Какое окно/форма открыта (полное название из заголовка)
- Какие поля видны и какие значения в них заполнены (читай весь текст с экрана)
- Какие кнопки нажимаются, какие пункты меню выбираются
- Куда переходит пользователь (навигационный путь)
- Что говорят участники в этот момент (если слышно речь - перескажи суть)

### 2. Распознанные данные
- Все названия справочников, документов, регистров, отчетов которые видны
- Все значения полей которые можно прочитать с экрана (наименования, числа, даты)
- Структура меню и навигации которая видна
- Названия колонок таблиц, значения в ячейках

### 3. Речь участников
- Кто говорит и что именно обсуждается (пересказ близко к тексту, не обобщение)
- Вопросы, ответы, решения, замечания - каждое отдельно с таймкодом
- Если кто-то что-то объясняет - передай суть объяснения подробно

### 4. Итоги
- Общая тема встречи
- Список всех показанных интерфейсов/форм
- Принятые решения и открытые вопросы
- Участники и их роли

Отвечай на русском языке. Будь максимально подробным - лучше написать слишком много, чем упустить детали.
Таймкоды в формате MM:SS."""

PROMPT_SCREENSHOTS = """Проанализируй видео и определи ключевые моменты, для которых нужно сделать скриншоты.

Выбери моменты где:
- Показан новый интерфейс/форма/документ (первое появление)
- Виден важный результат (отчет, таблица с данными)
- Демонстрируется ключевое действие (заполнение формы, настройка)

Верни ТОЛЬКО JSON-массив объектов, без markdown-форматирования, без ```json блоков:
[
  {"time": "MM:SS", "description": "Краткое описание что на скриншоте"}
]

Выбери 5-15 ключевых моментов, равномерно распределенных по видео."""

PROMPT_UI_ALLINONE = """Перед тобой ФРАГМЕНТ (несколько минут) видеозаписи рабочей встречи, где демонстрируются 1С и другие интерфейсы. Разбери ВЕСЬ фрагмент за один проход и верни РОВНО три раздела. Каждый раздел начинается с точной строки-разделителя на ОТДЕЛЬНОЙ строке - пиши разделители буквально, как указано.

Таймкоды - ОТ НАЧАЛА этого фрагмента (фрагмент начинается с 00:00). Покрой ВСЮ длительность: таймкоды примерно каждые 15-30 секунд от 00:00 и до самого конца фрагмента, НЕ останавливайся раньше. ВСЁ строго на русском языке, включая описания скриншотов.

=====ТРАНСКРИПЦИЯ=====
Полная дословная транскрипция речи, ничего не пропуская. Каждая реплика отдельной строкой строго в формате: [MM:SS] Имя: текст. Имена бери из обращений и представлений участников; если имя определить нельзя - пиши "Участник 1", "Участник 2" и т.д. стабильно за одним и тем же голосом.

=====ДЕТАЛЬНЫЙ=====
Пошаговый хронологический лог. КАЖДАЯ запись ОБЯЗАТЕЛЬНО начинается с таймкода [MM:SS]. Для каждого момента: какое окно/форма открыты (полное название из заголовка); какие поля и значения видны - читай ВЕСЬ текст с экрана ДОСЛОВНО (названия справочников, документов, регистров, отчётов, числа, даты, названия колонок и значения ячеек); какие действия выполняются; что при этом обсуждают участники (близко к тексту). Пиши связным текстом-нарративом. Цифры и названия - строго дословно.

=====СКРИНШОТЫ=====
ТОЛЬКО JSON-массив 2-4 ключевых моментов этого фрагмента (новая форма/интерфейс, важный результат-таблица, ключевое действие), без markdown и без тройных кавычек:
[{"time": "MM:SS", "description": "что на скриншоте, по-русски"}]

Все таймкоды строго в формате MM:SS от начала фрагмента."""


# === Утилиты ===

def upload_file(client, path):
    """Загрузка файла в Gemini File API с workaround для кириллических имен."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"media{path.suffix}"
        shutil.copy2(path, tmp_path)
        media_file = client.files.upload(file=str(tmp_path))
    return media_file


def wait_for_processing(client, media_file):
    """Ожидание обработки файла."""
    while media_file.state.name == "PROCESSING":
        print("  Обработка файла...")
        time.sleep(5)
        media_file = client.files.get(name=media_file.name)
    if media_file.state.name == "FAILED":
        print(f"Ошибка обработки файла: {media_file.state}")
        sys.exit(1)
    return media_file


def get_media_duration(path):
    """Получение длительности медиафайла в секундах через ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"  Предупреждение: не удалось определить длительность ({e}). Разбивка длинных файлов отключена.")
        return 0


UI_CHUNK_SEC = int(os.environ.get("UI_CHUNK_SEC", "300"))  # analyze-ui: длина видео-чанка (сек). Короткий
#   чанк = один мультимодальный проход держит таймлайн; на полном видео один проход коллапсирует таймкоды.
UI_MAX_PARALLEL = int(os.environ.get("UI_MAX_PARALLEL", "6"))  # analyze-ui: сколько чанков обрабатывать
#   одновременно (загрузка+генерация). Gemini держит конкурентность; при 429/503 - перебор моделей invoker.


def split_media(path, max_duration=3600):
    """Разбивка медиафайла на части если превышает max_duration (сек)."""
    duration = get_media_duration(path)
    if duration <= max_duration:
        return [path], [0]

    parts = []
    offsets = []
    num_parts = int(duration // max_duration) + 1
    part_duration = int(duration // num_parts) + 1
    tmp_dir = tempfile.mkdtemp()

    print(f"  Файл {duration/60:.0f} мин > {max_duration/60:.0f} мин лимита, разбиваю на {num_parts} частей...")

    for i in range(num_parts):
        start = i * part_duration
        out_path = Path(tmp_dir) / f"part_{i+1}{path.suffix}"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-i", str(path),
             "-t", str(part_duration), "-c", "copy", str(out_path)],
            capture_output=True, timeout=120,
        )
        if out_path.exists():
            parts.append(out_path)
            offsets.append(start)
            end = min(start + part_duration, int(duration))
            print(f"  Часть {i+1}: {start//60}:{start%60:02d} - {end//60}:{end%60:02d}")

    return parts, offsets


def offset_timestamps_in_text(text, offset_seconds):
    """Сдвиг таймкодов [MM:SS] в тексте на offset_seconds."""
    if offset_seconds == 0:
        return text

    def replace_ts(match):
        mm, ss = int(match.group(1)), int(match.group(2))
        total = mm * 60 + ss + offset_seconds
        new_mm, new_ss = divmod(total, 60)
        return f"[{new_mm:02d}:{new_ss:02d}]"

    return re.sub(r"\[(\d{1,2}):(\d{2})\]", replace_ts, text)


def extract_screenshots(video_path, timestamps, output_dir):
    """Извлечение скриншотов через ffmpeg по таймкодам."""
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    extracted = []
    for i, item in enumerate(timestamps, 1):
        ts = item["time"]
        desc = item["description"]
        out_file = screenshots_dir / f"{i:02d}_{ts.replace(':', '-')}.png"

        parts = ts.split(":")
        seconds = int(parts[0]) * 60 + int(parts[1])

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(seconds),
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(out_file),
                ],
                capture_output=True,
                timeout=30,
            )
            if out_file.exists():
                extracted.append({"file": out_file.name, "time": ts, "description": desc})
                print(f"  [{ts}] {out_file.name} - {desc}")
        except Exception as e:
            print(f"  [{ts}] Ошибка: {e}")

    return extracted


def insert_screenshots_into_text(text, extracted):
    """Вставка ссылок на скриншоты в детальный анализ рядом с соответствующими таймкодами."""
    if not extracted:
        return text

    for s in reversed(extracted):
        ts = s["time"]
        img_md = f"\n\n![{s['description']}](screenshots/{s['file']})\n"

        pattern = re.compile(
            r"^(.*?" + re.escape(ts) + r".*?)$",
            re.MULTILINE,
        )
        match = pattern.search(text)
        if match:
            insert_pos = match.end()
            text = text[:insert_pos] + img_md + text[insert_pos:]
        else:
            text += f"\n\n**[{ts}]** {s['description']}{img_md}"

    return text


def offset_screenshot_times(timestamps, offset_seconds):
    """Сдвиг таймкодов скриншотов на offset_seconds."""
    if offset_seconds == 0:
        return timestamps
    result = []
    for item in timestamps:
        parts = item["time"].split(":")
        total = int(parts[0]) * 60 + int(parts[1]) + offset_seconds
        mm, ss = divmod(total, 60)
        result.append({"time": f"{mm:02d}:{ss:02d}", "description": item["description"]})
    return result


def is_video(path):
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_audio(path):
    return path.suffix.lower() in AUDIO_EXTENSIONS


# === Генерация через Gemini с авто-fallback по моделям ===

class GeminiClient:
    """Обертка над genai.Client с авто-перебором моделей при перегрузке (503/429).

    Ретрай одной модели делает SDK (http_options.retry_options). Этот класс при устойчивом
    отказе модели переключается на следующую из цепочки и запоминает рабочую для следующих вызовов.
    """

    def __init__(self, api_key, models):
        # SDK сам ретраит каждую модель (по умолчанию retry_options=None - ретраев нет).
        # attempts=2 на КАЖДУЮ модель; коды ретрая - дефолтные SDK (408/429/500/502/503/504).
        retry = types.HttpRetryOptions(attempts=2)
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=retry),
        )
        self.models = models
        self._idx = 0  # индекс текущей рабочей модели

    def generate(self, media_file, prompt):
        """Генерация по медиафайлу (видео/аудио) с перебором моделей. Возвращает текст."""
        return self._generate([media_file, prompt])

    def generate_text(self, text, prompt):
        """Генерация по текстовому контенту (напр. саммари из транскрипции). Возвращает текст."""
        # Порядок как в generate: данные, затем инструкция.
        return self._generate([text, prompt])

    def _generate(self, contents):
        """Перебор моделей при перегрузке (503/429) для произвольного contents. Возвращает текст."""
        n = len(self.models)
        tried = []
        last_err = None
        for offset in range(n):
            i = (self._idx + offset) % n
            model = self.models[i]
            tried.append(model)
            next_model = self.models[(self._idx + offset + 1) % n] if offset < n - 1 else None
            tail = f"пробую {next_model}" if next_model else "модели исчерпаны"
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                )
                if not response.text:
                    # Пустой ответ - фильтр безопасности/контент, а не нагрузка.
                    # Модели не перебираем: пробрасываем наружу.
                    finish = (
                        getattr(response.candidates[0], "finish_reason", "unknown")
                        if response.candidates else "no candidates"
                    )
                    raise RuntimeError(
                        f"Gemini ({model}) вернул пустой ответ (возможно, сработал фильтр "
                        f"безопасности). finish_reason: {finish}"
                    )
                self._idx = i  # запомнить рабочую модель для следующих вызовов
                if offset > 0:
                    print(f"  [OK] Сгенерировано моделью {model}")
                return response.text
            except errors.APIError as e:
                if e.code in RETRYABLE_CODES or e.code in MODEL_UNAVAILABLE_CODES:
                    last_err = e
                    print(f"  [!] Модель {model} недоступна (код {e.code}), {tail}")
                    continue
                raise  # fatal (400/401/403/...) - смена модели не поможет
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
                print(f"  [!] Сетевая ошибка на {model} ({type(e).__name__}), {tail}")
                continue
        raise RuntimeError(
            f"Все модели Gemini недоступны (перегрузка/недоступность). "
            f"Испробованы: {', '.join(tried)}. Последняя ошибка: {last_err}"
        )


def transcribe_generic(invoker, media_file, time_offset=0):
    """Generic-транскрипция: verbatim речь с таймкодами."""
    text = invoker.generate(media_file, PROMPT_TRANSCRIBE)
    return offset_timestamps_in_text(text, time_offset)


def build_summary(invoker, transcript_text):
    """Саммари из текста транскрипции в два прохода: экстрактор фактов -> протокол.

    Источник - текст транскрипции, а не видео: полнее по речи (все задачи/решения,
    в т.ч. сказанные вскользь) и один проход на всю встречу убирает фрагментацию по
    частям. Проход 1 извлекает все факты, проход 2 оформляет протокол, гарантированно
    включив их. Прежнее саммари из видео в один проход теряло часть задач.
    """
    print("    [саммари 1/2] Извлечение всех задач/решений из транскрипции...")
    facts = _safe_call(
        "извлечение фактов",
        lambda: invoker.generate_text(transcript_text, PROMPT_TASKS_EXTRACT),
    )
    print("    [саммари 2/2] Сборка протокола с контролем полноты...")
    combined = (
        f"ТРАНСКРИПЦИЯ:\n\n{transcript_text}\n\n"
        f"---\n\nПРЕДВАРИТЕЛЬНО ИЗВЛЕЧЕННЫЕ ФАКТЫ:\n\n{facts}"
    )
    return _safe_call(
        "протокол",
        lambda: invoker.generate_text(combined, PROMPT_SUMMARY_FROM_TEXT),
    )


def _safe_call(label, fn):
    """Выполнить вызов Gemini, не роняя весь прогон. При ожидаемом отказе вернуть маркер.

    Ловим только ожидаемые отказы Gemini: fatal API-код, исчерпанный пул моделей,
    пустой ответ фильтра, сеть. Программные ошибки (AttributeError/TypeError) НЕ
    маскируем - пусть падают, иначе баг кода спрячется за маркером. Прежде один
    упавший вызов из нескольких терял весь прогон analyze-ui.
    """
    try:
        return fn()
    except (errors.APIError, httpx.TimeoutException, httpx.TransportError, RuntimeError) as e:
        print(f"    [!] {label}: шаг пропущен ({e})", file=sys.stderr)
        return f"\n> **[!] {label}: шаг не выполнен.** Причина: {e}\n"


def _safe_generate(invoker, media_file, prompt, label):
    """invoker.generate (по видео/файлу), не роняющий прогон analyze-ui."""
    return _safe_call(label, lambda: invoker.generate(media_file, prompt))


def _append(file_path, text):
    """Дописать текст в файл результата (инкрементальное сохранение по частям)."""
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(text)


def _split_allinone(resp):
    """Разбить единый ответ Gemini на (транскрипт, детальный, screenshots_json).

    Разделители =====ТРАНСКРИПЦИЯ/ДЕТАЛЬНЫЙ/СКРИНШОТЫ=====. Если разметка не сработала
    (напр. маркер ошибки _safe_generate) - весь ответ уходит в детальный, остальное пусто.
    """
    parts = re.split(r"=====\s*(ТРАНСКРИПЦИЯ|ДЕТАЛЬНЫЙ|СКРИНШОТЫ)\s*=====", resp)
    d = {}
    for i in range(1, len(parts) - 1, 2):
        d[parts[i]] = parts[i + 1].strip()
    transcript = d.get("ТРАНСКРИПЦИЯ", "")
    detailed = d.get("ДЕТАЛЬНЫЙ", "")
    shots = d.get("СКРИНШОТЫ", "")
    if not detailed and not transcript:
        detailed = resp.strip()
    return transcript, detailed, shots


def _parse_shots(shots_json, time_offset):
    """Разобрать JSON-массив скриншотов и сдвинуть их таймкоды на time_offset. [] при ошибке."""
    if not shots_json:
        return []
    try:
        text = re.sub(r"^```json\s*", "", shots_json.strip())
        text = re.sub(r"\s*```$", "", text)
        return offset_screenshot_times(json.loads(text), time_offset)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"    Не удалось распарсить таймкоды скриншотов: {e}")
        return []


def analyze_ui_single(invoker, media_file, video_path, output_dir, part_label="", time_offset=0):
    """Analyze-UI: ОДИН мультимодальный проход по чанку (транскрипт + детальный + скриншоты).

    Вызывается по-чанково (~5 мин) из _process_analyze_ui. На КОРОТКОМ чанке один проход
    держит таймлайн (проверено де-риском); на полном 25-мин видео один проход коллапсирует
    таймкоды. time_offset сдвигает чанк-локальные таймкоды в глобальные. Саммари строится
    глобально из полной транскрипции в _process_analyze_ui.
    """
    suffix = f" (фрагмент {part_label})" if part_label else ""
    print(f"  [проход]{suffix} транскрипт + детальный + скриншоты...")
    resp = _safe_generate(invoker, media_file, PROMPT_UI_ALLINONE, f"проход{suffix}")
    transcript_text, detailed_text, shots_json = _split_allinone(resp)

    detailed_text = offset_timestamps_in_text(detailed_text, time_offset)
    transcript_text = offset_timestamps_in_text(transcript_text, time_offset)

    timestamps = _parse_shots(shots_json, time_offset)
    if timestamps:
        print(f"    Извлекаю {len(timestamps)} скриншотов...")
        extracted = extract_screenshots(video_path, timestamps, output_dir)
        detailed_text = insert_screenshots_into_text(detailed_text, extracted)

    return detailed_text, transcript_text


# === Основная логика ===

def process_file(path, output_dir, mode, with_summary, output_format, models):
    """Обработка одного файла."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("API-ключ не найден. Варианты:")
        print("  1. Файл ~/.claude/skills/transcribe/.env с GEMINI_API_KEY=...")
        print("  2. Файл ~/.claude/skills/video-transcribe/.env с GEMINI_API_KEY=...")
        print("  3. Файл .env в текущей директории")
        print("  4. Переменная окружения: set GEMINI_API_KEY=ваш_ключ")
        sys.exit(1)

    size_mb = path.stat().st_size / (1024 * 1024)
    media_type = "видео" if is_video(path) else "аудио"
    print(f"Файл: {path.name} ({size_mb:.1f} MB, {media_type})")
    if len(models) > 1:
        print(f"Модель: {models[0]} (fallback при перегрузке: {', '.join(models[1:])})")
    else:
        print(f"Модель: {models[0]} (без fallback)")

    output_dir.mkdir(parents=True, exist_ok=True)
    invoker = GeminiClient(api_key, models)

    # Разбивка: analyze-ui режем на короткие чанки (один проход/чанк держит таймлайн),
    # остальные режимы - только очень длинные файлы.
    if mode == "analyze-ui" and is_video(path):
        parts, offsets = split_media(path, max_duration=UI_CHUNK_SEC)
    else:
        parts, offsets = split_media(path)

    if mode == "analyze-ui":
        _process_analyze_ui(invoker, path, parts, offsets, output_dir)
    else:
        _process_generic(invoker, path, parts, offsets, output_dir, with_summary, output_format)

    # Очистка временных файлов
    for part_path in parts:
        if part_path != path:
            part_path.unlink(missing_ok=True)
            try:
                part_path.parent.rmdir()
            except OSError:
                pass

    print(f"\n{'=' * 60}")
    print(f"Готово! Результаты в: {output_dir}")
    print(f"{'=' * 60}")


def _process_generic(invoker, path, parts, offsets, output_dir, with_summary, output_format):
    """Generic-режим: транскрипция (+ опц. саммари из полной транскрипции).

    Саммари (при --with-summary) строится из полного текста транскрипции через
    build_summary - полнее по задачам/решениям, чем разбор видео в один проход.
    """
    transcript_chunks = []
    if len(parts) == 1:
        media_file = None
        try:
            print("Загрузка файла в Gemini...")
            media_file = upload_file(invoker.client, path)
            print(f"Загружено: {media_file.name}")
            media_file = wait_for_processing(invoker.client, media_file)

            print("\n  Генерация транскрипции...")
            transcript_chunks.append(transcribe_generic(invoker, media_file))
        finally:
            if media_file is not None:
                _cleanup_file(invoker.client, media_file)
    else:
        for i, (part_path, offset) in enumerate(zip(parts, offsets), 1):
            print(f"\n{'='*40} Часть {i}/{len(parts)} {'='*40}")
            media_file = None
            try:
                print("Загрузка части в Gemini...")
                media_file = upload_file(invoker.client, part_path)
                print(f"Загружено: {media_file.name}")
                media_file = wait_for_processing(invoker.client, media_file)

                print("  Генерация транскрипции...")
                t_text = transcribe_generic(invoker, media_file, offset)
                transcript_chunks.append(f"## Часть {i} (с {offset//60}:{offset%60:02d})\n\n{t_text}")
            except (Exception, SystemExit) as e:
                # Сбой одной части не должен терять транскрипцию остальных (симметрично analyze-ui).
                print(f"  [!] Часть {i} не обработана ({e}), перехожу к следующей", file=sys.stderr)
                transcript_chunks.append(
                    f"## Часть {i} (с {offset//60}:{offset%60:02d})\n\n"
                    f"> **[!] Часть {i}: не обработана.** Причина: {e}\n"
                )
            finally:
                if media_file is not None:
                    _cleanup_file(invoker.client, media_file)

    transcript_text = "\n\n---\n\n".join(transcript_chunks)

    summary_text = None
    if with_summary:
        print("\n  Генерация саммари из полной транскрипции...")
        summary_text = build_summary(invoker, transcript_text)

    # Сохранение
    ext = ".txt" if output_format == "txt" else ".md"
    transcript_path = output_dir / f"{path.stem} - транскрипция{ext}"
    transcript_path.write_text(transcript_text, encoding="utf-8")
    print(f"\nСохранено: {transcript_path.name}")

    if summary_text:
        summary_path = output_dir / f"{path.stem} - саммари{ext}"
        summary_path.write_text(summary_text, encoding="utf-8")
        print(f"Сохранено: {summary_path.name}")


def _process_analyze_ui(invoker, path, parts, offsets, output_dir):
    """Analyze-UI: видео нарезано на чанки (~UI_CHUNK_SEC сек), каждый чанк - ОДИН
    мультимодальный проход (транскрипт+детальный+скриншоты), чанки идут ПАРАЛЛЕЛЬНО.

    Один проход по КОРОТКОМУ чанку держит таймлайн (на полном видео один проход
    коллапсирует таймкоды); чанки независимы, поэтому параллель не влияет на содержание,
    результаты сшиваются строго по порядку. Сбой одного чанка оставляет маркер, но не
    теряет остальные. Саммари строится в конце из ПОЛНОЙ транскрипции через build_summary
    (полнее по задачам/решениям и без фрагментации).
    """
    multipart = len(parts) > 1
    summary_path = output_dir / f"{path.stem} - саммари.md"
    detailed_path = output_dir / f"{path.stem} - детальный.md"
    transcript_path = output_dir / f"{path.stem} - транскрипция.md"

    # Чистый старт: перезапуск перезаписывает результат прошлого прогона
    for p in (summary_path, detailed_path, transcript_path):
        p.write_text("", encoding="utf-8")

    def _process_chunk(i, part_path, offset):
        """Обработать один чанк: загрузка -> один проход -> (детальный, транскрипт). Вернуть (i, d, t, ok).

        Полностью НЕЗАВИСИМ от других чанков - потому параллелится без влияния на содержание.
        """
        media_file = None
        try:
            media_file = upload_file(invoker.client, part_path)
            media_file = wait_for_processing(invoker.client, media_file)
            d_text, t_text = analyze_ui_single(
                invoker, media_file, path, output_dir,
                part_label=f"{i}/{len(parts)}" if multipart else "",
                time_offset=offset,
            )
            print(f"  [готов] фрагмент {i}/{len(parts)}", flush=True)
            return i, d_text, t_text, True
        except (Exception, SystemExit) as e:
            # Сбой одного фрагмента не роняет остальные. SystemExit ловим намеренно:
            # wait_for_processing зовет sys.exit(1) при FAILED-обработке файла Gemini.
            print(f"  [!] Фрагмент {i} не обработан ({e})", file=sys.stderr, flush=True)
            marker = (f"\n> **[!] Фрагмент {i} (с {offset//60}:{offset%60:02d}): не обработан.** "
                      f"Причина: {e}\n")
            return i, marker, marker, False
        finally:
            if media_file is not None:
                _cleanup_file(invoker.client, media_file)

    # Параллельная обработка чанков (загрузка+генерация одновременно; Gemini держит
    # конкурентность, 429/503 гасит перебор моделей invoker). Каждый чанк независим,
    # поэтому параллель НЕ меняет содержание - результаты сшиваются строго по порядку.
    workers = min(len(parts), UI_MAX_PARALLEL)
    if multipart:
        print(f"\nОбработка {len(parts)} фрагментов параллельно (до {workers} одновременно)...")
    else:
        print("Загрузка видео в Gemini...")
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_process_chunk, i, pp, off)
                for i, (pp, off) in enumerate(zip(parts, offsets), 1)]
        for fut in as_completed(futs):
            i, d_text, t_text, ok = fut.result()
            results[i] = (d_text, t_text)

    # Сшивка строго по порядку фрагментов (таймкоды уже глобальные -> лог сплошным потоком)
    transcript_chunks = []
    for i in range(1, len(parts) + 1):
        d_text, t_text = results[i]
        sep = "\n\n" if i > 1 else ""
        _append(detailed_path, f"{sep}{d_text}")
        _append(transcript_path, f"{sep}{t_text}")
        transcript_chunks.append(t_text)

    # Единое саммари из полной транскрипции (полнота задач + без фрагментации по частям)
    print("\n  Генерация саммари из полной транскрипции...")
    full_transcript = "\n\n".join(transcript_chunks)
    summary_text = build_summary(invoker, full_transcript)
    summary_path.write_text(summary_text, encoding="utf-8")

    print(f"\nСохранено: {summary_path.name}")
    print(f"Сохранено: {detailed_path.name}")
    print(f"Сохранено: {transcript_path.name}")


def _cleanup_file(client, media_file):
    """Удаление загруженного файла из Gemini."""
    try:
        client.files.delete(name=media_file.name)
    except Exception as e:
        print(f"  Предупреждение: не удалось удалить файл из Gemini ({media_file.name}): {e}")


# === CLI ===

def build_model_chain(cli_model=None, cli_fallback=None, no_fallback=False):
    """Сборка цепочки моделей. Приоритет: CLI > env > дефолт. Стартовая первой, дедупликация."""
    start = cli_model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    if no_fallback:
        return [start]

    chain_src = cli_fallback or os.environ.get("GEMINI_FALLBACK_MODELS")
    if chain_src:
        models = [m.strip() for m in chain_src.split(",") if m.strip()]
    else:
        models = list(DEFAULT_FALLBACK_CHAIN)

    # стартовая первой + остальные, дедупликация с сохранением порядка
    seen = set()
    result = []
    for m in [start] + models:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Транскрибация аудио и видео через Gemini API"
    )
    parser.add_argument("file", help="Путь к аудио/видеофайлу")
    parser.add_argument(
        "--output-dir", "-o",
        help="Каталог для результатов (по умолчанию: рядом с файлом в Транскрипция/<имя>/)",
    )
    parser.add_argument(
        "--analyze-ui",
        action="store_true",
        help="Режим анализа интерфейсов (только видео): саммари + детальный лог + скриншоты + транскрипция",
    )
    parser.add_argument(
        "--with-summary",
        action="store_true",
        help="Добавить саммари (для generic-режима)",
    )
    parser.add_argument(
        "--format",
        choices=["md", "txt"],
        default="md",
        help="Формат вывода (по умолчанию: md)",
    )
    parser.add_argument(
        "--model",
        help=f"Стартовая модель Gemini (по умолчанию: {DEFAULT_MODEL} или env GEMINI_MODEL)",
    )
    parser.add_argument(
        "--fallback-models",
        help="Цепочка fallback через запятую (переопределяет дефолтную; иначе env GEMINI_FALLBACK_MODELS)",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Отключить перебор моделей: использовать только стартовую (контроль стоимости/отладка)",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Файл не найден: {args.file}")
        sys.exit(1)

    if path.suffix.lower() not in ALL_EXTENSIONS:
        print(f"Неподдерживаемый формат: {path.suffix}")
        print(f"Видео: {', '.join(sorted(VIDEO_EXTENSIONS))}")
        print(f"Аудио: {', '.join(sorted(AUDIO_EXTENSIONS))}")
        sys.exit(1)

    # Определение режима
    mode = "generic"
    if args.analyze_ui:
        if is_audio(path):
            print("Предупреждение: --analyze-ui доступен только для видео. Переключаюсь на generic + саммари.",
                  file=sys.stderr)
            args.with_summary = True
        else:
            mode = "analyze-ui"

    # Определение output_dir
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = path.parent / "Транскрипция" / path.stem

    models = build_model_chain(args.model, args.fallback_models, args.no_fallback)
    process_file(path, output_dir, mode, args.with_summary, args.format, models)


if __name__ == "__main__":
    main()
