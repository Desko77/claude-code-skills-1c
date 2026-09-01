"""speaker_validator.py - программная проверка привязки имен к меткам спикеров.

Зачем отдельный слой. Все проверенные языковые модели (qwen2.5-32b, qwen3-vl-30b и qwen3.6, в том
числе с включенными размышлениями) систематически вешают имя на того, кто его ПРОИЗНОСИТ, хотя
произносящий как раз обращается к другому. На эталонной встрече три модели дали три разных ответа,
совпав ровно на одной метке из шести; правило "названный - тот, кто отвечает" в промпте есть, и все
модели его игнорируют. Поэтому проверка вынесена в код. Независимое измерение (NTT + CMU, arXiv
2606.17542) говорит о том же: на определении адресата обычный классификатор обходит все языковые
модели, а переход на модель побольше результат ухудшает.

Что проверяется:
  1. Звательная позиция ("Марина, логика та же", "Да, Леш?") - имя принадлежит НЕ говорящему.
  2. Адресат - тот, кто отвечает в соседних репликах.
  3. Третье лицо (косвенный падеж, имя с фамилией, "как Алексей просил") кандидатом не считается.
  4. Усеченные и уменьшительные формы сводятся к полной (Леш, Леша -> Алексей).
  5. Одно имя не висит на двух метках; роли и заглушки ("Модератор", "неизвестно") именами не считаются.

Модуль работает на ГОТОВОМ транскрипте с метками и ни к каким моделям не обращается.
Запуск отдельно (разбор одной встречи и отчет по уликам):
    python speaker_validator.py "<файл - со спикерами.md>" [--names SPEAKER_01=Алексей,...]
"""
import re
import sys
import json
import unicodedata
from collections import defaultdict

# Строчная и заглавная "е с диерезисом" - в исходнике кодами, чтобы файл оставался без нее в тексте.
# Whisper ставит ее непоследовательно ("Леша"/"Лёша", "Артем"/"Артём"), поэтому при сравнении
# всегда сводим к обычной "е", а таблицу форм ниже держим только в варианте без диерезиса.
_YO_LOWER = "ё"

# Полная форма -> известные уменьшительные и усеченные (звательные) варианты.
# Список покрывает распространенные русские имена; незнакомое имя все равно будет распознано как
# кандидат по звательной позиции, просто без сведения форм друг к другу.
_NAME_FORMS = {
    "Александр": ["Саша", "Саня", "Шура", "Алекс", "Сашка"],
    "Александра": ["Саша", "Сашенька", "Шура"],
    "Алексей": ["Леша", "Леха", "Алекс", "Лешка"],
    "Анастасия": ["Настя", "Ася", "Настена"],
    "Анатолий": ["Толя", "Толик"],
    "Андрей": ["Андрюша", "Дюша", "Андрюха"],
    "Анна": ["Аня", "Анюта", "Нюра"],
    "Антон": ["Антоша", "Тоша"],
    "Артем": ["Тема", "Артемка"],
    "Артур": [],
    "Борис": ["Боря"],
    "Вадим": ["Вадик"],
    "Валентина": ["Валя"],
    "Валерий": ["Валера"],
    "Василий": ["Вася"],
    "Вера": ["Верочка"],
    "Виктор": ["Витя"],
    "Виктория": ["Вика"],
    "Виталий": ["Виталик"],
    "Владимир": ["Вова", "Володя", "Вован"],
    "Владислав": ["Влад", "Слава"],
    "Вячеслав": ["Слава"],
    "Галина": ["Галя"],
    "Геннадий": ["Гена"],
    "Георгий": ["Гоша", "Жора"],
    "Григорий": ["Гриша"],
    "Даниил": ["Даня", "Данил"],
    "Дарья": ["Даша", "Дашенька"],
    "Денис": ["Дениска"],
    "Дмитрий": ["Дима", "Митя", "Димон", "Димка"],
    "Евгений": ["Женя", "Жека"],
    "Евгения": ["Женя"],
    "Егор": ["Егорка"],
    "Екатерина": ["Катя", "Катюша"],
    "Елена": ["Лена", "Аленка", "Ленка"],
    "Елизавета": ["Лиза"],
    "Иван": ["Ваня", "Ванька"],
    "Игорь": ["Игорек"],
    "Илья": ["Илюша"],
    "Ирина": ["Ира", "Иришка"],
    "Кирилл": ["Кир"],
    "Константин": ["Костя"],
    "Ксения": ["Ксюша", "Ксю"],
    "Лариса": ["Лара"],
    "Леонид": ["Леня"],
    "Лидия": ["Лида"],
    "Любовь": ["Люба"],
    "Людмила": ["Люда", "Мила"],
    "Максим": ["Макс"],
    "Марина": ["Мариша"],
    "Мария": ["Маша", "Машенька"],
    "Михаил": ["Миша", "Мишка"],
    "Надежда": ["Надя"],
    "Наталья": ["Наташа", "Ната"],
    "Наталия": ["Наташа"],
    "Никита": ["Никитка"],
    "Николай": ["Коля", "Колян"],
    "Олег": ["Олежа"],
    "Ольга": ["Оля", "Оленька"],
    "Павел": ["Паша", "Пашка"],
    "Петр": ["Петя"],
    "Роман": ["Рома", "Ромка"],
    "Руслан": [],
    "Светлана": ["Света", "Светик"],
    "Сергей": ["Сережа", "Серега", "Серый"],
    "Станислав": ["Стас"],
    "Степан": ["Степа"],
    "Тамара": ["Тома"],
    "Татьяна": ["Таня", "Танюша"],
    "Федор": ["Федя"],
    "Юлия": ["Юля"],
    "Юрий": ["Юра"],
    "Яков": ["Яша"],
    "Ярослав": ["Слава", "Ярик"],
}

# Не имена: роли, заглушки и отказы, которые модели регулярно подставляют вместо имени.
_NOT_NAMES = {
    "модератор", "ведущий", "ведущая", "участник", "участница", "докладчик", "спикер",
    "неизвестно", "неизвестный", "нет", "нет данных", "не определено", "не определен",
    "аноним", "гость", "заказчик", "исполнитель", "клиент", "разработчик", "аналитик",
    "коллега", "коллеги", "все", "никто", "unknown", "n/a", "none", "null",
}

_WORD_RE = re.compile(r"[А-Яа-яA-Za-zЁё-]+")

# Реплика приходит в двух видах, и оба надо понимать:
#   **[SPEAKER_05, 05:23]** текст   - файл "<имя> - со спикерами.md";
#   [05:23] SPEAKER_05: текст       - внутренний формат пайплайна, который и попадает в проверку.
# Поддержка только первого молча отключала всю проверку на реальном прогоне.
_SEGMENT_RES = (
    re.compile(r"\*\*\[(?:([^,\]]+),\s*)?(\d{1,3}(?::\d{2})+)\]\*\*\s*(.*)"),
    re.compile(r"\[(\d{1,3}(?::\d{2})+)\]\s*([^:]{1,40}?):\s*(.*)"),
)

# Слова, после которых стоящее следом имя почти всегда идет в третьем лице, а не в обращении:
# "как Алексей просил", "что Марина говорила".
_THIRD_PERSON_MARKERS = {
    "как", "что", "чтобы", "если", "когда", "пока", "раз", "потому", "поскольку",
    "ведь", "мол", "будто", "словно", "вон", "вот",
}

# Частые слова, В ТОЧНОСТИ совпадающие с усеченными формами имен из таблицы выше: "о ТОМ, что"
# против Тома -> Том, "у ВАС" против Вася -> Вас, "с ТЕМ же" против Тема -> Тем. Без этого фильтра
# обычная речь превращается в поток ложных обращений. Список намеренно короткий: сюда попадают
# только проверенные коллизии, а не все частотные слова языка.
_COMMON_WORDS = {"том", "вас", "тем", "мил", "ром", "слав", "лар", "нат"}


def _norm(word):
    """Сравнительная форма слова: нижний регистр, е вместо е-с-диерезисом, без концевых дефисов."""
    w = unicodedata.normalize("NFC", word).strip("-")
    return w.lower().replace(_YO_LOWER, "е")


def _build_index():
    """Индекс "форма имени -> полное имя". Кроме полных и уменьшительных форм включает усеченную
    звательную (Леша -> Леш, Марина -> Марин) - в живой речи она встречается чаще полной.

    Формы, которые делят между собой РАЗНЫЕ имена (Саша - и Александр, и Александра; Женя - и
    Евгений, и Евгения), к полному имени НЕ сводятся: молчаливый выбор мужского варианта навязал бы
    женщине мужское имя и вдобавок поссорился бы с проверкой рода. Такая форма остается сама собой,
    а род у нее считается неизвестным.
    """
    index, ambiguous = {}, set()

    def add(form, canonical):
        key = _norm(form)
        if len(key) < 3 or key in _COMMON_WORDS:
            return
        if key in index and index[key] != canonical:
            ambiguous.add(key)
        else:
            index.setdefault(key, canonical)

    for canonical, shorts in _NAME_FORMS.items():
        for f in [canonical] + list(shorts):
            add(f, canonical)
            if _norm(f)[-1:] in ("а", "я"):   # усеченное обращение: Леша -> Леш, Марина -> Марин
                add(f[:-1], canonical)

    for key in ambiguous:   # именем остается, но собственным - без сведения к чужому полному
        index[key] = key.capitalize()
    return index, ambiguous


_FORM_INDEX, _AMBIGUOUS_FORMS = _build_index()


def first_name_key(name):
    """Полная форма ТОЛЬКО личного имени, без фамилии - по ней сверяются обращения и род."""
    words = _WORD_RE.findall(name or "")
    if not words:
        return None
    return _FORM_INDEX.get(_norm(words[0])) or words[0].capitalize()


def canonical_name(name):
    """Свести имя к полной форме (Леш, Леша -> Алексей), СОХРАНИВ фамилию, если она названа.

    Отбрасывать фамилию нельзя: на встрече с двумя Алексеями "Алексей Иванов" и "Алексей Петров"
    схлопнулись бы в одно имя, и правило "одно имя - одной метке" выкинуло бы живого участника.
    """
    words = _WORD_RE.findall(name or "")
    if not words:
        return None
    canon = first_name_key(name)
    rest = " ".join(w.capitalize() for w in words[1:3])   # фамилия и отчество, если названы
    return f"{canon} {rest}".strip() if rest else canon


def is_name_like(name):
    """Похоже ли на настоящее имя человека: не роль, не заглушка, не аббревиатура."""
    if not name:
        return False
    words = _WORD_RE.findall(name)
    if not words:
        return False
    if _norm(name) in _NOT_NAMES or _norm(words[0]) in _NOT_NAMES:
        return False
    first = words[0]
    if len(first) < 3:
        return False
    if first.isupper() and len(first) <= 4:   # КС, ТСД и прочие аббревиатуры
        return False
    return bool(re.match(r"^[А-Яа-яЁё][а-яё-]+$", first))


# ---------------- Разбор транскрипта ----------------

def parse_segments(text):
    """Транскрипт со спикерами -> [dict(idx, sec, label, text)] в порядке следования."""
    segments = []
    for line in text.splitlines():
        line = line.strip()
        md = _SEGMENT_RES[0].match(line)
        plain = None if md else _SEGMENT_RES[1].match(line)
        if md:
            label, tstr, body = md.group(1), md.group(2), md.group(3).strip()
        elif plain:
            tstr, label, body = plain.group(1), plain.group(2), plain.group(3).strip()
        else:
            continue
        if not label or not body:
            continue
        # Метка спикера - это "SPEAKER_05", "Участник 2" или имя: длинных фраз там не бывает.
        # Без этой отсечки строка вида "[05:23] длинный текст: с двоеточием" дала бы мусорную метку.
        if label.count(" ") > 2:
            continue
        sec = 0
        for part in tstr.split(":"):
            try:
                sec = sec * 60 + int(part)
            except ValueError:
                sec = 0
        segments.append({"idx": len(segments), "sec": sec, "label": label.strip(), "text": body})
    return segments


def _tokens_with_pos(text):
    """[(слово, начало, конец)] по тексту реплики."""
    return [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def _classify(text, tokens, i, extra_index):
    """Как употреблено имя в позиции i: 'vocative' (обращение), 'third' (третье лицо) или None.

    Обращение в русском надежно опознается пунктуацией: имя стоит в именительной или усеченной
    форме и отбито запятой либо границей предложения. Третье лицо - косвенный падеж
    ("Алексея Иванова запросить"), имя с фамилией ("Дима Петров") или имя после союза ("как
    Алексей просил").
    """
    word, start, end = tokens[i]
    key = _norm(word)
    known_form = key in _FORM_INDEX or key in extra_index

    before = text[:start].rstrip()
    after = text[end:].lstrip()
    prev_word = _norm(tokens[i - 1][0]) if i else ""

    # Имя с фамилией: следом ВПЛОТНУЮ (без знаков препинания между) идет слово с заглавной буквы.
    # Проверка на разделитель обязательна: иначе заглавная буква следующего ПРЕДЛОЖЕНИЯ выдает
    # обращение за фамилию - на "Да, Леш? Да." это съедало главную улику встречи.
    if i + 1 < len(tokens):
        next_word, next_start = tokens[i + 1][0], tokens[i + 1][1]
        gap = text[end:next_start]
        if (next_word[:1].isupper() and not re.search(r"[^\s]", gap)
                and _norm(next_word) not in _FORM_INDEX):
            return "third"

    if not known_form:
        # Форма не из словаря именительных: почти наверняка косвенный падеж того же имени.
        return "third"

    if prev_word in _THIRD_PERSON_MARKERS:
        return "third"

    starts_clause = (not before) or before.endswith((",", ".", "!", "?", ":", ";", "-"))
    ends_clause = (not after) or after[:1] in (",", ".", "!", "?", ";", ":")
    if starts_clause and ends_clause:
        return "vocative"
    return "third"


def _stem(name):
    """Основа имени для сопоставления косвенных падежей (Алексей -> алексе)."""
    key = _norm(name)
    return key[:-1] if key[-1:] in ("й", "ь", "а", "я") else key


# Падежные окончания имен. По ним косвенная форма отличается от постороннего слова с тем же началом:
# без этой проверки "максимально" опознается как Максим, а "вернули" - как Вера.
_CASE_ENDINGS = ("а", "у", "е", "и", "ы", "я", "ю", "ой", "ей", "ом", "ем", "ою", "ью", "ым")
_MIN_STEM = 4   # основы короче (Вера -> вер) дают слишком много ложных совпадений


def _oblique_of(key, stems):
    """Полное имя, если key - косвенная форма известного имени, иначе None.
    Длинные основы проверяются первыми: совпадение по более специфичной основе точнее."""
    for stem in sorted(stems, key=len, reverse=True):
        if len(stem) < _MIN_STEM or key == stem or not key.startswith(stem):
            continue
        if key[len(stem):] in _CASE_ENDINGS:
            return stems[stem]
    return None


def collect_name_events(segments, known_names=()):
    """Найти все употребления имен. Возвращает [dict(seg, label, name, kind, form)].

    known_names - имена, уже предложенные другими слоями (модель, голосовая база): по ним ловятся
    и косвенные формы, даже если само имя в словаре отсутствует.
    """
    extra_index = {}
    stems = {}
    for n in known_names:
        canon = canonical_name(n)
        if not canon:
            continue
        extra_index[_norm(canon)] = canon
        stems[_stem(canon)] = canon
    for canon in _NAME_FORMS:
        stems.setdefault(_stem(canon), canon)

    events = []
    for seg in segments:
        tokens = _tokens_with_pos(seg["text"])
        for i, (word, _s, _e) in enumerate(tokens):
            key = _norm(word)
            canon = _FORM_INDEX.get(key) or extra_index.get(key)
            if not canon:   # не именительная форма - проверяем, не косвенный ли это падеж имени
                canon = _oblique_of(key, stems)
                if not canon:
                    continue
            kind = _classify(seg["text"], tokens, i, extra_index)
            events.append({"seg": seg["idx"], "label": seg["label"], "name": canon,
                           "kind": kind, "form": word, "sec": seg["sec"]})
    return events


# ---------------- Род говорящего ----------------

# Мужские имена, оканчивающиеся на -а/-я: общее правило "на -а/-я значит женское" их не берет.
_MALE_EXCEPTIONS = {"Никита", "Илья", "Данила", "Кузьма", "Фома", "Савва", "Лука", "Гаврила"}

# "я" и его формы, после которых глагол прошедшего времени указывает на род ГОВОРЯЩЕГО.
_FIRST_PERSON = {"я"}
_MIN_VERB_LEN = 3       # короче не бывает даже "был"/"дал"/"шел"

# Служебные слова, которые в русском вклиниваются между "я" и глаголом ("я же все равно былА").
# Все ОСТАЛЬНОЕ обрывает поиск: иначе окончание случайного существительного принимается за глагол
# и "я этот стол вижу" делает говорящего мужчиной, а "я вижу, что школа закрыта" - женщиной.
_GENDER_SKIP = {
    "же", "бы", "уж", "уже", "еще", "тоже", "все", "всё", "вот", "не", "ни", "там", "тут",
    "сейчас", "тогда", "вчера", "сразу", "равно", "лично", "просто", "точно", "давно",
    "потом", "как", "то", "так", "ведь", "видимо", "кстати", "вообще", "именно", "тут",
}


def name_gender(canonical):
    """Род имени: 'f', 'm' или None, если по имени род не определить (Саша, Женя, Слава)."""
    if not canonical:
        return None
    key = _norm(canonical)
    if key in _AMBIGUOUS_FORMS:
        return None
    if canonical in _MALE_EXCEPTIONS:
        return "m"
    return "f" if key[-1:] in ("а", "я") else "m"


def detect_gender(segments, min_margin=2):
    """Род говорящего за каждой меткой по форме глагола: "я сделалА" против "я сделаЛ".

    Считаем улики, а не первое попадание: диаризация регулярно склеивает короткий обмен репликами
    ("Да? Да. Я же была близко") в один сегмент, и тогда маркер принадлежит собеседнику. Отсюда два
    режима: если противоречий нет (все улики одного рода), хватает одной - на реальной встрече
    единственное "была" у метки верно опознало женщину, что подтвердила голосовая база. Если улики
    спорят, нужен перевес min_margin, иначе род не определяем вовсе.
    """
    counts = defaultdict(lambda: {"m": 0, "f": 0})
    for seg in segments:
        words = [_norm(w) for w in _WORD_RE.findall(seg["text"])]
        for i, w in enumerate(words):
            if w not in _FIRST_PERSON:
                continue
            for nxt in words[i + 1:]:
                if nxt in _GENDER_SKIP:
                    continue
                # Первое же ЗНАЧИМОЕ слово решает: либо это глагол прошедшего времени, либо улики
                # нет вовсе. "лись" сюда не входит - это множественное число, а не женский род.
                if nxt == "сама" or (len(nxt) >= _MIN_VERB_LEN
                                     and (nxt.endswith("лась") or nxt.endswith("ла"))):
                    counts[seg["label"]]["f"] += 1
                elif nxt == "сам" or (len(nxt) >= _MIN_VERB_LEN
                                      and (nxt.endswith("лся") or nxt.endswith("л"))):
                    counts[seg["label"]]["m"] += 1
                break
    out = {}
    for label, c in counts.items():
        if c["f"] and not c["m"]:
            out[label] = "f"
        elif c["m"] and not c["f"]:
            out[label] = "m"
        elif c["f"] - c["m"] >= min_margin:
            out[label] = "f"
        elif c["m"] - c["f"] >= min_margin:
            out[label] = "m"
    return out


# ---------------- Вывод имен по уликам ----------------

# Вес адресата по расстоянию: сильнее всего - тот, кто ответил сразу после обращения.
_NEXT_WEIGHTS = (1.0, 0.4)
_PREV_WEIGHT = 0.4


def infer_from_events(segments, events):
    """Свести улики в оценки. Возвращает (scores, banned):

    scores[label][name] - насколько улики поддерживают "метка label это name";
    banned[label] - множество имен, которые эта метка произносила в звательной позиции,
    то есть заведомо ЧУЖИЕ для нее.
    """
    scores = defaultdict(lambda: defaultdict(float))
    banned = defaultdict(set)
    by_idx = {s["idx"]: s for s in segments}

    for ev in events:
        if ev["kind"] != "vocative":
            continue
        speaker, name, idx = ev["label"], ev["name"], ev["seg"]
        banned[speaker].add(name)

        seen = []
        for j in range(idx + 1, min(idx + 6, len(segments))):   # кто отвечает после обращения
            lbl = by_idx[j]["label"]
            if lbl == speaker or lbl in seen:
                continue
            seen.append(lbl)
            if len(seen) >= len(_NEXT_WEIGHTS):
                break
        for k, lbl in enumerate(seen):
            scores[lbl][name] += _NEXT_WEIGHTS[k]

        for j in range(idx - 1, max(idx - 3, -1), -1):   # или тот, с кем говорящий уже говорил
            lbl = by_idx[j]["label"]
            if lbl != speaker:
                scores[lbl][name] += _PREV_WEIGHT
                break

    for label in list(scores):   # свое же имя в обращении - улика против, а не за
        for name in list(scores[label]):
            if name in banned[label]:
                del scores[label][name]
    return scores, banned


# Вес голого предложения модели, ничем не подтвержденного в речи. Меньше веса одной прямой улики:
# иначе модель занимает имя за случайной меткой, и метка с настоящим обращением остается ни с чем -
# ровно так qwen3-vl отдавала "Алексей" метке, к которой по имени не обращались ни разу.
_MODEL_PRIOR = 0.5


def _assign_global(combined, banned, locked, proposed, min_new):
    """Раздать имена меткам: одно имя - одной метке, одна метка - одно имя.

    Раздача общая для всех пар, откуда бы пара ни взялась, поэтому сильная улика из речи бьет
    слабое предложение модели. locked (подтвержденное голосом) занимает места до раздачи и не
    пересматривается: голос надежнее текста и узнает человека между встречами. Пары из proposed
    проходят без порога min_new - его проверяют только имена, которые мы назначаем сами.
    Возвращает (результат, список вытесненных предложений).
    """
    result = dict(locked)
    taken = set(result.values())
    pairs = sorted(((sc, lbl, nm) for lbl, d in combined.items() for nm, sc in d.items()),
                   key=lambda x: (-x[0], x[1], x[2]))
    dropped = []
    for score, label, name in pairs:
        # Занятость - по ПОЛНОМУ имени: "Алексей Иванов" и "Алексей Петров" разные люди, и оба
        # должны получить метку. Запреты же проверяются по личному имени - обращения в речи звучат
        # без фамилии. На эталонной встрече двое Алексеев реально есть, так что это не гипотеза.
        if (label in result or name in taken or first_name_key(name) in banned[label]):
            if proposed.get(label) == name:
                dropped.append((label, name))
            continue
        if score < min_new and proposed.get(label) != name:
            continue
        result[label] = name
        taken.add(name)
    return result, dropped


# ---------------- Точка входа ----------------

def validate(name_map, transcript_text, voice_confirmed=(), min_score=1.2, require_spoken=True):
    """Проверить и исправить привязку имен к меткам.

    name_map          - что предложили предыдущие слои (модель и/или голосовая база);
    transcript_text   - транскрипт с метками спикеров;
    voice_confirmed   - метки, чье имя подтверждено голосом: их не пересматриваем, голос надежнее
                        текстовых улик (он же узнает человека между встречами);
    require_spoken    - снимать имена, которые в записи не звучали ни разу. Это защита от чистой
                        выдумки модели: порог min_score к ее предложениям не применяется, так что
                        без этой проверки имя без единой улики проходит насквозь. Выключать имеет
                        смысл только в отладке;
    min_score         - порог, ниже которого улик недостаточно, чтобы НАЗНАЧИТЬ имя самим. 1.2 - это
                        больше одного ответа на обращение (вес 1.0), то есть нужны либо два
                        независимых обращения, либо обращение плюс подтверждение. Смысл порога -
                        не пускать в протокол имя, за которым стоит одна слабая улика: пустая
                        метка честнее неверного имени. На эталонной встрече подъем порога с 0.8
                        до 1.2 убрал больше половины ошибок, не потеряв ни одного верного имени.

    Возвращает (исправленный map, список строк отчета - что и почему изменено).
    """
    report = []
    segments = parse_segments(transcript_text)
    if not segments:
        return dict(name_map or {}), ["валидатор: в транскрипте нет размеченных реплик - пропускаю"]

    proposed = {}
    for label, raw in (name_map or {}).items():
        if not is_name_like(raw):
            report.append(f"снято {label} -> {raw!r}: это роль или заглушка, а не имя")
            continue
        canon = canonical_name(raw)
        if canon != raw:
            report.append(f"нормализовано {label}: {raw} -> {canon}")
        proposed[label] = canon

    events = collect_name_events(segments, known_names=proposed.values())
    scores, banned = infer_from_events(segments, events)

    # Имена, которые в записи ВООБЩЕ звучали - в любой позиции и в любом падеже (collect_name_events
    # ловит и косвенные формы предложенных имен). Все остальное модель взяла из головы: на встрече,
    # где никого не назвали, она уверенно выдает правдоподобный набор ("Роман", "Станислав"), и до
    # этой проверки такие имена проходили насквозь - порог min_score к предложениям модели не
    # применяется по замыслу, а других улик у них нет. Пустая метка честнее выдуманного имени.
    spoken = {e["name"] for e in events}

    genders = detect_gender(segments)
    names_in_play = {e["name"] for e in events} | set(proposed.values())
    wrong_gender = defaultdict(set)
    for label, g in genders.items():
        for name in names_in_play:
            ng = name_gender(first_name_key(name))
            if ng is not None and ng != g:   # None - род по имени неизвестен, запрещать не за что
                wrong_gender[label].add(name)
                banned[label].add(first_name_key(name))

    locked, survived = {}, {}
    for label, name in proposed.items():
        if label in voice_confirmed:   # голос надежнее текстовых улик - не пересматриваем
            locked[label] = name
            continue
        if require_spoken and first_name_key(name) not in spoken and name not in spoken:
            report.append(f"снято {label} -> {name}: имя ни разу не звучит в записи "
                          f"(модель его придумала)")
            continue
        if name in wrong_gender[label]:
            told = "женском" if genders[label] == "f" else "мужском"
            report.append(f"снято {label} -> {name}: по форме глаголов метка говорит о себе "
                          f"в {told} роде")
            continue
        if first_name_key(name) in banned[label]:
            where = next((e for e in events
                          if e["label"] == label and e["name"] == first_name_key(name)
                          and e["kind"] == "vocative"), None)
            at = (f" (обращается к нему на {where['sec'] // 60:02d}:{where['sec'] % 60:02d})"
                  if where else "")
            report.append(f"снято {label} -> {name}: метка сама произносит это имя в обращении{at}")
            continue
        survived[label] = name

    combined = defaultdict(dict)
    for label, per_name in scores.items():
        for name, sc in per_name.items():
            if name not in banned[label]:
                combined[label][name] = sc
    for label, name in survived.items():
        combined[label][name] = combined[label].get(name, 0.0) + _MODEL_PRIOR

    final, dropped = _assign_global(combined, banned, locked, survived, min_score)
    for label, name in dropped:
        winner = next((l for l, n in final.items() if n == name), None)
        if winner:
            report.append(f"снято {label} -> {name}: за {winner} улик больше "
                          f"({combined[winner].get(name, 0.0):.1f} против "
                          f"{combined[label].get(name, 0.0):.1f})")
        else:
            report.append(f"снято {label} -> {name}: имя не подтверждено речью")
    for label, name in sorted(final.items()):
        if label not in locked and survived.get(label) != name:
            report.append(f"добавлено {label} -> {name}: к метке обращаются по имени, "
                          f"улик {scores[label].get(name, 0.0):.1f}")
    return final, report


def evidence_report(transcript_text, known_names=()):
    """Человекочитаемая сводка улик - для разбора спорных случаев и отладки."""
    segments = parse_segments(transcript_text)
    events = collect_name_events(segments, known_names=known_names)
    scores, banned = infer_from_events(segments, events)
    lines = ["Обращения по имени (звательная позиция):"]
    for ev in events:
        if ev["kind"] != "vocative":
            continue
        lines.append(f"  {ev['sec'] // 60:02d}:{ev['sec'] % 60:02d}  {ev['label']} произносит "
                     f"'{ev['form']}' -> {ev['name']}")
    lines.append("Упоминания в третьем лице (кандидатами не считаются):")
    for ev in events:
        if ev["kind"] == "third":
            lines.append(f"  {ev['sec'] // 60:02d}:{ev['sec'] % 60:02d}  {ev['label']}: "
                         f"'{ev['form']}' -> {ev['name']}")
    genders = detect_gender(segments)
    if genders:
        lines.append("Род по форме глаголов:")
        for label in sorted(genders):
            lines.append(f"  {label}: {'женский' if genders[label] == 'f' else 'мужской'}")
    lines.append("Оценки:")
    for label in sorted(scores):
        inner = ", ".join(f"{n}={s:.1f}" for n, s in sorted(scores[label].items(),
                                                            key=lambda x: -x[1]))
        lines.append(f"  {label}: {inner or '-'}   заведомо чужие: "
                     f"{', '.join(sorted(banned[label])) or '-'}")
    return "\n".join(lines)


def main():
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    # Запрос справки не должен читаться как имя файла: без этого любой ключ превращался
    # в путь и давал отказ вместо подсказки.
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "/?"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) > 1 else 1)
    path = sys.argv[1]
    preset = {}
    for arg in sys.argv[2:]:
        if arg.startswith("--names"):
            body = arg.split("=", 1)[1] if "=" in arg else ""
            for pair in body.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    preset[k.strip()] = v.strip()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    print(evidence_report(text, known_names=preset.values()))
    print()
    final, report = validate(preset, text)
    print("Итог:", json.dumps(final, ensure_ascii=False))
    for line in report:
        print("  -", line)


if __name__ == "__main__":
    main()
