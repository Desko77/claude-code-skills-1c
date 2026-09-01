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

Жанр определяет, какие категории проверяются. Жанрозависимых категорий две, и
каждый жанр глушит ровно одну:

    reference  README, правило, SKILL.md, справочник, CHANGELOG - НЕ проверяется
               структура: плотные заголовки в справочнике уместны по существу
    prose      отчет, статья, пост - проверяется все (по умолчанию)
    letter     письмо, ответ - НЕ проверяется регистр: разговорный оборот там норма

Жанр берется из ключа --genre, иначе определяется сам: сначала по пути и имени
файла (reference), затем по содержимому (letter), иначе prose. Порядок важен:
README с приветствием это справочник, а не письмо.

Маскирование адресное. Область снимает НЕ все категории, а названные:

    блок кода и inline-код   не проверяется ничего
    frontmatter              проверяется только механическое
    таблица                  не проверяется стрелка (там это обозначение)
    цитата                   не проверяется регистр
    слово в кавычках         не проверяется регистр: слово упоминается, не употребляется
    адрес ссылки             не проверяются регистр и стоп-фраза; текст ссылки проверяется

Механическое не маскируется нигде, кроме кода: запрещенный символ остается
запрещенным и в таблице, и во frontmatter - EDT рубит его одинаково.

Режимы:
    python humanize_scan.py файл.md                  отчет, файл не меняется
    python humanize_scan.py файл.md --fix            применить механические замены на месте
    python humanize_scan.py *.md --quiet             только итоговая строка на файл
    python humanize_scan.py файл.md --genre reference   задать жанр явно
    python humanize_scan.py файл.md --json           машиночитаемый отчет
    python humanize_scan.py файл.md --no-technical   без проверки технического регистра
    python humanize_scan.py письмо.md --technical    проверять регистр и в письме

Коды возврата: 0 чисто, 1 есть находки, 2 хотя бы один файл нечитаем.
Реестр категорий - scripts/categories.json, единственный источник истины.
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

# Замены, однозначные без разбора смысла. Все прочее скрипт только показывает.
# Символы задаются кодами: в исходнике этого набора они запрещены, а подстановка
# самого символа сделала бы шаблон поиска дефисом и находкой стала бы любая строка.
MECHANICAL = [
    (chr(0x451), chr(0x435), 'буква е с диакритикой'),
    (chr(0x401), chr(0x415), 'буква Е с диакритикой'),
    (chr(0x2014), '-', 'длинное тире'),
    (chr(0x2013), '-', 'короткое тире'),
    (chr(0xab), chr(34), 'кавычка-елочка открывающая'),
    (chr(0xbb), chr(34), 'кавычка-елочка закрывающая'),
    (chr(0x2026), '...', 'символ многоточия'),
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


# Строка-разделитель таблицы: только черты, дефисы, двоеточия выравнивания и
# пробелы, и хотя бы один дефис. Именно она делает набор строк таблицей.
TABLE_SEP_RE = re.compile(r'^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$')
TABLE_ROW_RE = re.compile(r'\|')
QUOTE_RE = re.compile(r'^\s*>')
FRONTMATTER_RE = re.compile(r'^\s*---\s*$')
LIST_ITEM_RE = re.compile(r'^\s*(?:[-*+]|\d+\.)\s')
# Адрес ссылки: inline, ссылка на определение и автоссылка.
LINK_TARGET_RE = re.compile(r'\]\(([^)\s]+)[^)]*\)|^\s*\[[^\]]+\]:\s*(\S+)|<((?:https?|mailto):[^>]+)>')
# Максимум строк, в которых ищется закрытие frontmatter. Без предела незакрытый
# разделитель скрыл бы документ целиком.
FRONTMATTER_MAX = 40


def mark_areas(lines):
    """Разметить строки областями: какие категории в строке НЕ проверяются.

    Возвращает список множеств по числу строк. Пустое множество - обычная проза,
    проверяется все.

    Маскирование адресное, а не сплошное: таблица снимает только стрелку
    (там это обозначение соответствия, а не проза), цитата снимает только
    регистр (там цитируют чужие слова). Механическое не снимается НИГДЕ -
    запрещенный символ остается запрещенным и в таблице, и во frontmatter.
    """
    areas = [set() for _ in lines]

    # frontmatter: блок между первой строкой из трех дефисов и следующей такой же.
    if lines and FRONTMATTER_RE.match(lines[0]):
        end = None
        for i in range(1, min(len(lines), FRONTMATTER_MAX)):
            if FRONTMATTER_RE.match(lines[i]):
                end = i
                break
        if end is not None:
            for i in range(0, end + 1):
                areas[i] |= {'стрелка', 'эмодзи', 'стоп-фраза', 'регистр'}

    # Таблица: строки вокруг разделителя, содержащие черту.
    for i, line in enumerate(lines):
        if not TABLE_SEP_RE.match(line) or '|' not in line:
            continue
        areas[i].add('стрелка')
        for j in range(i - 1, -1, -1):
            if not TABLE_ROW_RE.search(lines[j]):
                break
            areas[j].add('стрелка')
        for j in range(i + 1, len(lines)):
            if not TABLE_ROW_RE.search(lines[j]):
                break
            areas[j].add('стрелка')

    for i, line in enumerate(lines):
        if QUOTE_RE.match(line):
            areas[i].add('регистр')

    return areas


def mask_link_targets(line):
    """Заменить адреса ссылок пробелами, сохранив длину строки и видимый текст.

    Текст ссылки читается как проза, и запрещенное слово в нем такой же дефект.
    А адрес вида /game-changer или https://example.test/magic дал бы ложную
    находку регистра или стоп-фразы, хотя менять его нельзя.
    """
    def blank(m):
        return ' ' * len(m.group(0))
    return LINK_TARGET_RE.sub(
        lambda m: m.group(0)[:m.group(0).find('(') + 1] + ' ' * (len(m.group(0)) - m.group(0).find('(') - 2) + ')'
        if '](' in m.group(0) else blank(m), line)


def quoted_example(line, pos, end):
    """Взято ли само слово в позиции pos..end в кавычки или бэктики.

    Слово в кавычках УПОМИНАЕТСЯ, а не употребляется: правило, объясняющее
    запрет, приводит запрещенное слово, и штрафовать его собственным правилом
    неверно. Именно так не проходили `text-formatting.md` и SKILL.md самого
    хуманизатора.

    Проверяется обрамление САМОГО слова, а не наличие кавычек где-то в строке:
    широкое условие сняло бы регистр с любой строки, где есть хоть одна
    кавычка. Замерено по rules/: из 30 срабатываний 14 обрамлены кавычками и
    все они упоминания, 16 не обрамлены и все они настоящий долг текстов -
    заголовки вида "Подводные камни" и оборот "известные грабли".
    """
    left = line[pos - 1] if pos > 0 else ''
    right = line[end] if end < len(line) else ''
    pairs = {'"': '"', '«': '»', '`': '`', "'": "'"}
    return pairs.get(left) == right and left != ''


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


def describe_fixes(before, after):
    """Перечислить примененные механические замены построчно.

    Нужен для машиночитаемого отчета: без перечня замен режим --fix молча меняет
    файл, и по отчету нельзя понять, что именно исправлено.
    """
    out = []
    for i, (was, became) in enumerate(zip(before.split('\n'), after.split('\n')), 1):
        if was == became:
            continue
        for ch, repl, name in MECHANICAL:
            n = was.count(ch) - became.count(ch)
            if n > 0:
                out.append({'line': i, 'category': 'механическое',
                            'was': name, 'became': repl, 'count': n})
    return out


def muted_report(genre, technical, force_technical):
    """Какие категории заглушены для этого прогона и по какой причине.

    Одного признака "пропущено по жанру" мало: reference глушит структуру,
    letter регистр, а ключи регистра перебивают жанр. Читателю отчета нужна
    причина, а не факт.
    """
    out = [{'category': c, 'reason': 'genre:' + genre}
           for c in sorted(GENRE_MUTES.get(genre, set()))]
    if not technical and not force_technical:
        out.append({'category': 'регистр', 'reason': 'flag:--no-technical'})
    return out


def detect_genre(path, text):
    """Определить жанр файла. Порядок классификаторов задан и не меняется.

    reference идет РАНЬШЕ letter: README с приветствием это справочник, а не
    письмо, и регистр в нем проверять надо. Обратный порядок выключил бы
    проверку у половины документации набора.
    """
    if path:
        p = str(path).replace('\\', '/').lower()
        segments = set(p.split('/'))
        name = p.rsplit('/', 1)[-1]
        if segments & {'rules', 'skills', 'tools', 'docs'}:
            return 'reference'
        if name.startswith('readme') or name.startswith('changelog'):
            return 'reference'
    if looks_epistolary(strip_code(text).split('\n')):
        return 'letter'
    return 'prose'


# Какие категории ГЛУШИТ жанр. Каждый жанр глушит ровно одну: замерено по
# репозиторию, жанрозависимых категорий всего две, и полный жанровый слой при
# них не обоснован.
GENRE_MUTES = {
    'reference': {'структура'},
    'prose': set(),
    'letter': {'регистр'},
}


def scan(text, technical=True, force_technical=False, genre='prose'):
    """Список находок: (категория, номер строки, описание).

    Маскирование адресное: область снимает НЕ все категории, а названные.
    Сплошное исключение таблиц и цитат скрыло бы и запрещенный символ, который
    остается запрещенным где угодно - EDT рубит его и в таблице, и во
    frontmatter.
    """
    prose = strip_code(text)
    prose_lines = prose.split('\n')
    areas = mark_areas(prose_lines)
    muted = GENRE_MUTES.get(genre, set())
    found = []

    # Пропуск по жанру - это пояснение, а не находка: письмо с разговорным оборотом исправно.
    # Формулировка пояснения про письмо сохранена дословно: на нее опирается
    # существующий кейс, а обещание обратной совместимости запрещает править
    # кейс под новое поведение.
    note = None
    check_register = technical
    if check_register and not force_technical and 'регистр' in muted:
        check_register = False
        if genre == 'letter':
            note = ('похоже на письмо или ответ, проверка технического регистра пропущена; '
                    'включить принудительно - ключ --technical')
        else:
            note = ('регистр не проверяется: жанр %s; включить принудительно - '
                    'ключ --technical' % genre)
    if force_technical:
        check_register = True

    for line_no, line in enumerate(prose_lines, 1):
        area = areas[line_no - 1]
        for ch, _repl, name in MECHANICAL:
            count = line.count(ch)
            if count:
                found.append(('механическое', line_no,
                              '%s: %d' % (name, count)))
        if 'стрелка' not in area:
            arrows = ARROW_RE.findall(line)
            if arrows:
                found.append(('стрелка', line_no,
                              'текстовая стрелка: %d, нужно слово по смыслу' % len(arrows)))
        if 'эмодзи' not in area and EMOJI_MARKER_RE.match(line):
            found.append(('эмодзи', line_no, 'эмодзи-маркер в начале строки'))
        low = line.lower()
        if 'стоп-фраза' not in area:
            for phrase in STOP_PHRASES_RU + STOP_PHRASES_EN:
                if phrase in low:
                    found.append(('стоп-фраза', line_no, '"%s"' % phrase))
        if check_register and 'регистр' not in area:
            for m in REGISTER_RE.finditer(mask_link_targets(line)):
                if quoted_example(line, m.start(), m.end()):
                    continue
                found.append(('регистр', line_no,
                              '"%s" - бытовой оборот, нужен технический термин' % m.group(0)))

    if 'структура' not in muted:
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
    # Отчет содержит кириллицу. Без явного переключения печать падает с UnicodeEncodeError
    # везде, где консоль не в UTF-8: сборочный агент, чужая локаль.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
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
    parser.add_argument('--genre', choices=('reference', 'prose', 'letter'), default=None,
                        help='жанр текста; по умолчанию определяется по пути и содержимому')
    parser.add_argument('--json', dest='as_json', action='store_true',
                        help='машиночитаемый отчет; stdout содержит только JSON')
    parser.set_defaults(technical=True, force_technical=False)
    args = parser.parse_args()

    total = 0
    unreadable = 0
    report = []
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            # Обработка остальных файлов продолжается: остановка на первом плохом
            # прятала бы результат по всем следующим.
            unreadable += 1
            if args.as_json:
                report.append({'path': name, 'error': 'файл не найден'})
            else:
                sys.stderr.write('Файл не найден: %s\n' % name)
            continue
        # Чтение и запись идут через io.open, а не через методы Path: параметр newline
        # у них появился только в python 3.13, а без него перевод строки нормализуется
        # при чтении, и файл с CRLF сохранялся бы с LF.
        with io.open(str(path), encoding='utf-8-sig', newline='') as fh:
            raw = fh.read()
        eol = '\r\n' if '\r\n' in raw else '\n'
        text = raw.replace('\r\n', '\n')

        fixes = []
        if args.fix:
            before = text
            fixed, changed = apply_fix(text)
            if changed:
                with io.open(str(path), 'w', encoding='utf-8', newline='') as fh:
                    fh.write(fixed.replace('\n', eol))
                fixes = describe_fixes(before, fixed)
            text = fixed
            if not args.as_json:
                print('%s: механических замен %d' % (path.name, changed))

        genre = args.genre or detect_genre(path, text)
        found, in_code, note = scan(text, technical=args.technical,
                                    force_technical=args.force_technical, genre=genre)
        total += len(found)

        if args.as_json:
            report.append({
                'path': name,
                'genre': genre,
                'muted': muted_report(genre, args.technical, args.force_technical),
                'findings': [{'category': c, 'line': ln, 'message': d}
                             for c, ln, d in found],
                'fixes': fixes,
            })
            continue

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

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    # Приоритет кода возврата: нечитаемый файл важнее находок, находки важнее
    # чистого результата.
    if unreadable:
        return 2
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
