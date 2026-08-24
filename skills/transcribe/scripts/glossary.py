"""glossary.py - словарь терминов: подсказка распознавателю речи + правка ослышек.

Зачем. Whisper уверенно ослышивается на англицизмах и жаргоне предметной области, и молча:
DAX -> "ДАКС", JSON -> "G-Splone", PROD -> "Прот", гашение -> "базаты". Ни один последующий слой
это не чинит - текстовая модель принимает ослышку за факт и тащит ее в связный лог и в саммари.

Два рычага, оба нужны:
  1. hotwords - список правильных написаний уходит в промпт КАЖДОГО окна распознавания
     (faster-whisper подмешивает их в prompt при каждом вызове get_prompt, в отличие от
     initial_prompt, который влияет в основном на первое окно). Профилактика: модель чаще
     выбирает знакомую форму. Гарантии нет - слово может не влезть в лимит промпта.
  2. fix() - лечение по факту: замена конкретных ослышек на правильную форму. Работает уже по
     готовому тексту, поэтому чинит и то, что hotwords не спасли.

Формат файла (по умолчанию `<скил>/glossary.txt`, кодировка UTF-8):

    # строка комментария
    DAX = ДАКС, дакс, дэкс     # слева правильное написание, справа ослышки через запятую
    JSON = джейсон, G-Splone
    чек-лист                   # строка без "=" - только подсказка распознавателю, замен нет

Ослышки перечисляются ТЕМИ формами, какими они реально вышли из распознавателя (падеж, число).
Морфологии здесь нет и не планируется: угадывать словоформы опаснее, чем пропустить одну.

Модуль намеренно на голой стандартной библиотеке: он импортируется и из venv распознавателя, где
из стороннего стоит только faster-whisper.
"""
import os
import re
import sys
from pathlib import Path

# Файл по умолчанию лежит в корне скила, рядом со SKILL.md: правит его человек, а не агент.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "glossary.txt"

# Ослышки короче этого не заменяем: на 1-2 символах любая замена начинает попадать в середину
# посторонних слов, а выигрыш нулевой.
MIN_FORM_LEN = 3

# Потолок строки hotwords. Распознаватель все равно режет промпт по своему лимиту (~223 токена),
# но обрезать осмысленно - по границе термина - лучше, чем отдать ему обрубок последнего слова.
HOTWORDS_MAX_CHARS = 400


class Glossary:
    """Термины и их ослышки. Пустой глоссарий безопасен: hotwords пуст, fix() возвращает текст как есть."""

    def __init__(self, terms=None, source=None, warnings=None):
        self.terms = list(terms or [])          # [(правильное написание, [ослышки])]
        self.source = source                    # откуда загружен - для сообщения в лог
        self.warnings = list(warnings or [])
        self._pattern, self._by_form = _compile(self.terms)

    def __bool__(self):
        return bool(self.terms)

    def __len__(self):
        return len(self.terms)

    @property
    def fixable(self):
        """Сколько терминов реально умеют чиниться заменой (у остальных только hotwords)."""
        return sum(1 for _canon, forms in self.terms if forms)

    def hotwords(self, max_chars=HOTWORDS_MAX_CHARS):
        """Строка правильных написаний для faster-whisper hotwords. Обрезается по границе термина."""
        out, total = [], 0
        for canon, _forms in self.terms:
            add = len(canon) + (2 if out else 0)
            if total + add > max_chars:
                break
            out.append(canon)
            total += add
        return ", ".join(out)

    def fix(self, text):
        """Заменить ослышки на правильные написания. Возвращает (текст, {правильное: сколько раз}).

        Один проход комбинированным регэкспом, а не цепочка re.sub: уже подставленный термин не
        может быть перезаписан следующим правилом (та же защита от каскада, что в apply_names).
        """
        if not text or self._pattern is None:
            return text, {}
        stats = {}

        def _sub(m):
            canon = self._by_form[_key(m.group(0))]
            stats[canon] = stats.get(canon, 0) + 1
            return _match_case(m.group(0), canon)

        return self._pattern.sub(_sub, text), stats

    def fix_segments(self, segments, field="text"):
        """Починить ослышки в списке словарей (сегменты/реплики) на месте. Возвращает общую статистику."""
        total = {}
        for seg in segments or ():
            fixed, stats = self.fix(seg.get(field) or "")
            if stats:
                seg[field] = fixed
                for canon, n in stats.items():
                    total[canon] = total.get(canon, 0) + n
        return total


def _key(form):
    """Ключ сопоставления: регистр и внутренние пробелы не считаются."""
    return re.sub(r"\s+", " ", form.strip().lower())


def _match_case(original, canon):
    """Сохранить заглавную букву начала предложения, если правильное написание строчное."""
    if original[:1].isupper() and canon[:1].islower():
        return canon[:1].upper() + canon[1:]
    return canon


def _compile(terms):
    """Собрать один регэксп по всем ослышкам. Длинные формы первыми - иначе короткая съест префикс."""
    by_form = {}
    for canon, forms in terms:
        for form in forms:
            by_form.setdefault(_key(form), canon)
    if not by_form:
        return None, {}
    parts = []
    for form in sorted(by_form, key=len, reverse=True):
        # Пробелы внутри формы - любой пробельный разрыв: распознаватель ставит их непредсказуемо.
        parts.append(r"\s+".join(re.escape(tok) for tok in form.split()))
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)
    return pattern, by_form


def parse(text):
    """Разобрать содержимое файла глоссария. Возвращает (термины, предупреждения)."""
    terms, warnings, seen = [], [], {}
    for num, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        canon, _sep, rest = line.partition("=")
        canon = canon.strip()
        if not canon:
            warnings.append(f"строка {num}: пустое правильное написание - пропущена")
            continue
        forms = []
        for form in rest.split(","):
            form = form.strip()
            if not form:
                continue
            if len(form) < MIN_FORM_LEN:
                warnings.append(f"строка {num}: ослышка {form!r} короче {MIN_FORM_LEN} символов - пропущена")
                continue
            if _key(form) == _key(canon):
                continue   # форма совпала с правильным написанием - заменять нечего
            if _key(form) in seen:
                # Регистр в сопоставлении не участвует, поэтому "ДАКС" и "дакс" - одна и та же
                # ослышка: это не конфликт, а просто повтор. Предупреждаем только когда одну форму
                # растащили по РАЗНЫМ терминам - там правда неоднозначность.
                if seen[_key(form)] != canon:
                    warnings.append(f"строка {num}: ослышка {form!r} уже закреплена за "
                                    f"{seen[_key(form)]!r} - пропущена")
                continue
            seen[_key(form)] = canon
            forms.append(form)
        terms.append((canon, forms))
    return terms, warnings


def load(path=None, enabled=True):
    """Загрузить глоссарий. Приоритет: аргумент -> env TRANSCRIBE_GLOSSARY -> файл по умолчанию.

    enabled=False (ключ --no-glossary) отдает пустой глоссарий: он безвреден на всех стадиях,
    поэтому вызывающему не нужно ветвиться на None.
    Отсутствие файла - не ошибка: глоссарий необязателен.
    """
    if not enabled:
        return Glossary(source=None)
    chosen = path or os.environ.get("TRANSCRIBE_GLOSSARY") or DEFAULT_PATH
    p = Path(chosen)
    if not p.exists():
        warn = [f"файл глоссария не найден: {p}"] if path else []
        return Glossary(source=None, warnings=warn)
    try:
        terms, warnings = parse(p.read_text(encoding="utf-8"))
    except OSError as e:
        return Glossary(source=None, warnings=[f"глоссарий не прочитан ({e}): {p}"])
    return Glossary(terms, source=str(p), warnings=warnings)


def describe(gl):
    """Однострочный отчет о загруженном глоссарии - для лога прогона."""
    if not gl:
        return "глоссарий: не задан"
    return (f"глоссарий: {len(gl)} терминов ({gl.fixable} с правилами замены) из {gl.source}")


def main(argv=None):
    """Проверка глоссария вручную: показать разбор и прогнать замены по строке или файлу."""
    # Вывод содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    argv = list(sys.argv[1:] if argv is None else argv)
    text_arg, path = None, None
    while argv:
        a = argv.pop(0)
        if a == "--glossary":
            path = argv.pop(0) if argv else None
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            text_arg = a
    gl = load(path)
    print(describe(gl))
    for w in gl.warnings:
        print(f"  предупреждение: {w}")
    for canon, forms in gl.terms:
        print(f"  {canon}" + (f" <- {', '.join(forms)}" if forms else "  (только подсказка)"))
    print(f"\nhotwords: {gl.hotwords()!r}")
    if text_arg:
        src = Path(text_arg)
        text = src.read_text(encoding="utf-8") if src.exists() else text_arg
        fixed, stats = gl.fix(text)
        print(f"\nзамен: {stats if stats else 'нет'}")
        print(fixed if len(fixed) < 4000 else fixed[:4000] + "...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
