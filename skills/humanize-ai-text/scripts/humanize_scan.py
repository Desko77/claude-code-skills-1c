#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ищет в тексте объективные маркеры AI-генерации и чинит механические.

Разделение простое: то, что заменяется одним правилом без понимания смысла, делает скрипт;
то, где нужно решение, остается модели. Скрипт не переписывает текст и не трогает стиль.

Блоки кода, огражденные тройными кавычками, и inline-код исключены из поиска целиком: внутри них
и стрелка, и тире - часть синтаксиса, а не признак генерации.

Проверка технического регистра включена по умолчанию: бытовая метафора вместо действия и предмета
в техническом тексте - дефект. В письме и ответе она нормальна, поэтому проверка сама выключается,
когда видит приветствие или подпись.

Режимы:
    python humanize_scan.py файл.md                  отчет, файл не меняется
    python humanize_scan.py файл.md --fix            применить механические замены на месте
    python humanize_scan.py *.md --quiet             только итоговая строка на файл
    python humanize_scan.py файл.md --no-technical   без проверки технического регистра
    python humanize_scan.py письмо.md --technical    проверять регистр и в письме
"""
import argparse
import re
import sys
from pathlib import Path

# Замены, однозначные без разбора смысла. Все прочее скрипт только показывает.
MECHANICAL = [
    ('ё', 'е', 'буква е с диакритикой'),
    ('Ё', 'Е', 'буква Е с диакритикой'),
    ('—', '-', 'длинное тире'),
    ('–', '-', 'короткое тире'),
    ('«', '"', 'кавычка-елочка открывающая'),
    ('»', '"', 'кавычка-елочка закрывающая'),
    ('…', '...', 'символ многоточия'),
]

# Стрелка мехническими средствами не чинится: на ее месте нужно слово по смыслу
# ("становится", "дает", "ведет к"), а его выбирает человек или модель.
ARROW_RE = re.compile(r'(?<![<>=!-])(->|=>|→)(?!>)')

EMOJI_MARKER_RE = re.compile(
    r'^\s*(?:[-*+]\s*)?[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]')

STOP_PHRASES_RU = [
    'в современном мире', 'в наше время', 'в эпоху цифровизации',
    'давайте погрузимся', 'давайте разберемся', 'давайте разберёмся',
    'рассмотрим подробнее', 'стоит отметить, что', 'важно понимать, что',
    'нельзя не упомянуть', 'не секрет, что', 'как известно',
    'в заключение', 'подводя итог', 'таким образом, мы видим',
    'ключевой момент здесь', 'важный нюанс заключается в том',
    'открывает новые возможности', 'революционизирует',
    'надеюсь, это было полезно', 'надеюсь, это поможет',
    'дайте знать, если', 'не стесняйтесь обращаться',
    'в мире, где', 'по сути говоря', 'если разобраться',
    'что действительно важно', 'на самом деле вопрос в том',
]

STOP_PHRASES_EN = [
    "let's dive into", "it's worth noting", "in today's fast-paced world",
    'furthermore', 'moreover', 'in conclusion', 'i hope this helps',
    'feel free to ask', "it's important to note", 'game-changer',
    'revolutionary', 'cutting-edge', 'delve into',
    'navigate the complexities of', 'in the realm of', 'at its core',
]

FENCE_RE = re.compile(r'^\s*```')
INLINE_CODE_RE = re.compile(r'`[^`\n]*`')
HEADING_RE = re.compile(r'^\s{0,3}#{2,3}\s')
WORD_RE = re.compile(r'\w+', re.UNICODE)

# --- технический регистр ---------------------------------------------------------------------
# Бытовая метафора вместо действия и предмета. В техническом тексте такая фраза не только неточна:
# по ней нельзя назвать ни метод, ни поле, ни код ошибки, ни измеренную величину.
#
# Список намеренно узкий и точный. Оценочные слова ("просто", "легко", "удобно") сюда НЕ входят:
# они слишком часто законны, а решение по ним принимает модель по проверочному вопросу из SKILL.md.
# Целые слова и обороты: ищутся по границе слова, иначе "копит" находится в "накопитель".
REGISTER_WORDS = [
    'кладет', 'кладёт', 'забирает', 'копит', 'копят',
    'внутренняя кухня', 'ядро библиотеки', 'узнают друг о друге',
    'под капотом', 'на лету', 'магия', 'магию', 'магией',
    'умеет', 'умеют', 'дружит с', 'из коробки',
    'тянет из', 'тащит', 'съедает', 'жрет', 'жрёт',
    'грабли', 'подводные камни', 'зоопарк',
    'серебряная пуля', 'изобретать велосипед', 'своего велосипеда', 'вслепую',
    'under the hood', 'out of the box', 'the heart of', 'knows how to',
    'tops up', 'grabs', 'piles up', 'learn about each other', 'seamless', 'magic',
]
# Основы: слово продолжается любым окончанием, но начинаться должно именно с них.
REGISTER_STEMS = [
    'досып', 'схлопыв', 'скармлив', 'подсовыв', 'выкидыв',
    'проглот', 'разрулив', 'костыл', 'ловушк',
]
REGISTER_RE = re.compile(
    '|'.join([r'\b(?:%s)\b' % '|'.join(re.escape(w) for w in REGISTER_WORDS)] +
             [r'\b(?:%s)\w*' % '|'.join(re.escape(s) for s in REGISTER_STEMS)]),
    re.I | re.UNICODE)

# Эпистолярный жанр: письмо, ответ, обращение. Там разговорный оборот - норма, а не дефект,
# поэтому проверка регистра сама себя выключает.
#
# Приветствие ищется целым словом И в короткой строке: без этого "Приветственный экран" в заголовке
# технической статьи выключал проверку для всего документа.
GREETING_MAX_LEN = 60
SALUTATION_RE = re.compile(
    r'^\s*(здравствуйте|здравствуй|добрый день|добрый вечер|доброе утро|привет|приветствую|'
    r'уважаемый|уважаемая|уважаемые|дорогой|дорогая|дорогие|коллеги|'
    r'dear|hi|hello|good morning|good afternoon)\b', re.I)
SIGNOFF_RE = re.compile(
    r'^\s*(с уважением|всего доброго|до встречи|обнимаю|спасибо за внимание|'
    r'best regards|sincerely|kind regards|cheers|yours)\b', re.I)


def strip_code(text):
    """Возвращает текст, где содержимое блоков кода и inline-кода заменено пробелами.

    Длина строк и их количество сохраняются, поэтому номера строк остаются верными.
    """
    out = []
    in_fence = False
    for line in text.split('\n'):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(' ' * len(line))
            continue
        if in_fence:
            out.append(' ' * len(line))
            continue
        out.append(INLINE_CODE_RE.sub(lambda m: ' ' * len(m.group(0)), line))
    return '\n'.join(out)


def looks_epistolary(prose_lines):
    """Похож ли текст на письмо или ответ: приветствие в начале, подпись в конце.

    Смотрим края, а не весь текст: в середине технической статьи слово "уважаемый" может
    оказаться в цитате, и это еще не делает документ письмом.
    """
    head = [l for l in prose_lines[:12] if l.strip()]
    tail = [l for l in prose_lines[-12:] if l.strip()]
    short = lambda l: len(l.strip()) <= GREETING_MAX_LEN
    if any(SALUTATION_RE.match(l) and short(l) for l in head):
        return True
    return any(SIGNOFF_RE.match(l) and short(l) for l in tail)


def scan(text, technical=True, force_technical=False):
    """Список находок: (категория, номер строки, описание)."""
    prose = strip_code(text)
    prose_lines = prose.split('\n')
    found = []

    # Пропуск по жанру - это пояснение, а не находка: письмо с разговорным оборотом исправно.
    note = None
    check_register = technical
    if check_register and not force_technical and looks_epistolary(prose_lines):
        check_register = False
        note = ('похоже на письмо или ответ, проверка технического регистра пропущена; '
                'включить принудительно - ключ --technical')

    for line_no, line in enumerate(prose_lines, 1):
        for ch, _repl, name in MECHANICAL:
            count = line.count(ch)
            if count:
                found.append(('механическое', line_no,
                              '%s: %d' % (name, count)))
        arrows = ARROW_RE.findall(line)
        if arrows:
            found.append(('стрелка', line_no,
                          'текстовая стрелка: %d, нужно слово по смыслу' % len(arrows)))
        if EMOJI_MARKER_RE.match(line):
            found.append(('эмодзи', line_no, 'эмодзи-маркер в начале строки'))
        low = line.lower()
        for phrase in STOP_PHRASES_RU + STOP_PHRASES_EN:
            if phrase in low:
                found.append(('стоп-фраза', line_no, '"%s"' % phrase))
        if check_register:
            for m in REGISTER_RE.finditer(line):
                found.append(('регистр', line_no,
                              '"%s" - бытовой оборот, нужен технический термин' % m.group(0)))

    headings = sum(1 for line in prose_lines if HEADING_RE.match(line))
    words = len(WORD_RE.findall(prose))
    if headings and words:
        per = words / headings
        if per < 200:
            found.append(('структура', 0,
                          'заголовков H2/H3: %d на %d слов, один на %d - гуще порога 1 на 200'
                          % (headings, words, int(per))))

    in_code = sum(text.count(ch) for ch, _r, _n in MECHANICAL) - \
        sum(prose.count(ch) for ch, _r, _n in MECHANICAL)
    return found, in_code, note


def apply_fix(text):
    """Механические замены. Блоки кода и inline-код не трогаются."""
    lines = text.split('\n')
    in_fence = False
    changed = 0
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        pieces = []
        pos = 0
        for m in INLINE_CODE_RE.finditer(line):
            pieces.append((line[pos:m.start()], True))
            pieces.append((m.group(0), False))
            pos = m.end()
        pieces.append((line[pos:], True))
        rebuilt = []
        for piece, editable in pieces:
            if editable:
                for ch, repl, _name in MECHANICAL:
                    if ch in piece:
                        changed += piece.count(ch)
                        piece = piece.replace(ch, repl)
            rebuilt.append(piece)
        lines[i] = ''.join(rebuilt)
    return '\n'.join(lines), changed


def main():
    parser = argparse.ArgumentParser(
        description='Поиск объективных маркеров AI-генерации; механические чинятся сразу')
    parser.add_argument('files', nargs='+')
    parser.add_argument('--fix', action='store_true',
                        help='применить механические замены на месте')
    parser.add_argument('--quiet', action='store_true',
                        help='только итоговая строка на файл')
    parser.add_argument('--no-technical', dest='technical', action='store_false',
                        help='не проверять технический регистр (по умолчанию проверяется)')
    parser.add_argument('--technical', dest='force_technical', action='store_true',
                        help='проверять технический регистр даже в письме или ответе')
    parser.set_defaults(technical=True, force_technical=False)
    args = parser.parse_args()

    total = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            sys.stderr.write('Файл не найден: %s\n' % name)
            return 1
        raw = path.read_text(encoding='utf-8-sig', newline='')
        eol = '\r\n' if '\r\n' in raw else '\n'
        text = raw.replace('\r\n', '\n')

        if args.fix:
            fixed, changed = apply_fix(text)
            if changed:
                path.write_text(fixed.replace('\n', eol), encoding='utf-8', newline='')
            text = fixed
            print('%s: механических замен %d' % (path.name, changed))

        found, in_code, note = scan(text, technical=args.technical,
                                    force_technical=args.force_technical)
        total += len(found)
        if args.quiet:
            print('%s: находок %d' % (path.name, len(found)))
            continue

        print('=== %s ===' % path)
        if note:
            print('  (%s)' % note)
        if not found:
            print('Объективных маркеров не найдено.')
        else:
            for category, line_no, text_of in found:
                where = 'строка %d' % line_no if line_no else 'весь файл'
                print('  [%s] %s: %s' % (category, where, text_of))
        if in_code:
            print('  (в блоках кода символов из списка: %d, не трогаю)' % in_code)
        print('  ИТОГО находок: %d' % len(found))

    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
