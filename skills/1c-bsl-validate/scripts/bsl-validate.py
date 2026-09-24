#!/usr/bin/env python3
# bsl-validate v1.0 - Check BSL module calls against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Reads BSL modules and the index built by 1c-config-index, then reports calls to common-module
methods that do not exist or are not exported. This is NOT a BSL compiler: types, syntax and
overload resolution are out of reach without the platform."""
import sys, os, argparse, json, re, hashlib, bisect

IDENT = r'[A-Za-z_А-я\u0401\u0451][A-Za-z0-9_А-я\u0401\u0451]*'
CALL_RE = re.compile(r'\b(' + IDENT + r')\s*\.\s*(' + IDENT + r')\s*\(')
VAR_RE = re.compile(r'^[ \t]*(?:Перем|Var)[ \t]+(.+?);',
                    re.IGNORECASE | re.MULTILINE | re.DOTALL)
METHOD_RE = re.compile(r'^[ \t]*(?:(?:Асинх|Async)[ \t]+)?'
                       r'(?:Процедура|Функция|Procedure|Function)[ \t]+' + IDENT + r'[ \t]*\(',
                       re.IGNORECASE | re.MULTILINE)
# Присваивание бывает не только с начала строки: "Если Истина Тогда М = Новый Массив;".
ASSIGN_RE = re.compile(r'(?:^|;|\bТогда\b|\bThen\b|\bЦикл\b|\bDo\b)[ \t]*('
                       + IDENT + r')[ \t]*=[^=]', re.IGNORECASE | re.MULTILINE)
FOREACH_RE = re.compile(r'\b(?:Для[ \t]+Каждого|For[ \t]+Each)[ \t]+(' + IDENT + r')\b', re.IGNORECASE)
FOR_RE = re.compile(r'\b(?:Для|For)[ \t]+(' + IDENT + r')[ \t]*=', re.IGNORECASE)

# Глобальные коллекции и объекты платформы, к которым обращаются через точку. Список заведомо
# НЕПОЛНЫЙ - платформа их сотни. Поэтому проверка неизвестных имен и включается флагом: без него
# отсутствие имени в этом списке ни на что не влияет.
KNOWN_GLOBAL_ROOTS = {
    'Справочники', 'Catalogs', 'Документы', 'Documents', 'Перечисления', 'Enums',
    'РегистрыСведений', 'InformationRegisters', 'РегистрыНакопления', 'AccumulationRegisters',
    'РегистрыБухгалтерии', 'AccountingRegisters', 'РегистрыРасчета', 'CalculationRegisters',
    'ПланыСчетов', 'ChartsOfAccounts', 'ПланыВидовХарактеристик', 'ChartsOfCharacteristicTypes',
    'ПланыВидовРасчета', 'ChartsOfCalculationTypes', 'ПланыОбмена', 'ExchangePlans',
    'БизнесПроцессы', 'BusinessProcesses', 'Задачи', 'Tasks', 'Отчеты', 'Reports',
    'Обработки', 'DataProcessors', 'Константы', 'Constants',
    'ЖурналыДокументов', 'DocumentJournals', 'Последовательности', 'Sequences',
    'КритерииОтбора', 'FilterCriteria', 'ХранилищаНастроек', 'SettingsStorages',
    'WSСсылки', 'WSReferences', 'WebСервисы', 'WebServices', 'HTTPСервисы', 'HTTPServices',
    'ОбщиеМодули', 'CommonModules', 'ПараметрыСеанса', 'SessionParameters',
    'РегламентныеЗадания', 'ScheduledJobs', 'ОпределяемыеТипы', 'DefinedTypes',
    'ФункциональныеОпции', 'ВнешниеИсточникиДанных', 'ExternalDataSources',
    'Метаданные', 'Metadata', 'ЭтотОбъект', 'ThisObject',
    'БиблиотекаКартинок', 'PictureLib', 'БиблиотекаМакетов', 'ЦветаСтиля', 'StyleColors',
    'ШрифтыСтиля', 'StyleFonts', 'РамкиСтиля', 'StyleBorders',
    'ФабрикаXDTO', 'XDTOFactory', 'СериализаторXDTO', 'XDTOSerializer',
    'ПолнотекстовыйПоиск', 'FullTextSearch',
    'ВнешниеОбработки', 'ExternalDataProcessors', 'ВнешниеОтчеты', 'ExternalReports',
    'ПользователиИнформационнойБазы', 'InfoBaseUsers',
    'ХранилищеСистемныхНастроек', 'SystemSettingsStorage',
    'ХранилищеОбщихНастроек', 'CommonSettingsStorage',
    'ИсторияДанных', 'DataHistory', 'ФункциональныеОпции', 'FunctionalOptions',
    'КриптоМенеджер', 'ОбменДаннымиСервер', 'ДокументыHTTP',
    'ХранилищеВариантовОтчетов', 'ReportsVariantsStorage',
    'ХранилищеНастроекДанныхФорм', 'FormDataSettingsStorage',
    'ХранилищеПользовательскихНастроекДинамическихСписков', 'DynamicListsUserSettingsStorage',
}

# Литерал ИЛИ комментарий: что началось раньше, то и поглощает второе. Закрывающая кавычка
# необязательна - незакрытый литерал гасит остаток файла.
BSL_NOISE_RE = re.compile(r'"(?:[^"]|"")*"?|//[^\n]*')


def strip_bsl_noise(text):
    """Комментарии и строковые литералы гасятся ЗА ОДИН проход, с сохранением длины.

    Гасить их нужно: тексты запросов внутри строк полны точек, и без этого каждая вторая строка
    запроса стала бы вызовом. Но по очереди нельзя - неверно в обе стороны. Литералы первыми:
    нечетная кавычка в комментарии открывает мнимый литерал и съедает следом идущий код вместе
    с вызовами. Комментарии первыми: "TCP://" в литерале обрубит строку. Кто из двух начался
    раньше, решает чередование в самом образце: движок идет слева направо, и внутри уже
    начавшегося литерала двойной слеш ему не виден.

    Длина сохраняется, переводы строк внутри литерала тоже: проверка корня вызова смотрит на
    символ ПЕРЕД совпадением, а литерал в BSL занимает несколько строк.
    """
    def blank(m):
        s = m.group(0)
        if s[0] == '/':
            return ' ' * len(s)
        closed = len(s) >= 2 and s[-1] == '"'
        inner = s[1:-1] if closed else s[1:]
        body = ' ' * len(inner) if '\n' not in inner \
            else ''.join('\n' if c == '\n' else ' ' for c in inner)
        return '"' + body + ('"' if closed else '')
    return BSL_NOISE_RE.sub(blank, text)


def collect_local_names(text):
    """Имена, объявленные в самом модуле: переменные, параметры методов, цели присваивания,
    переменные циклов. Косвенный вызов через переменную не должен давать ложной ошибки."""
    names = set()
    for m in VAR_RE.finditer(text):
        for part in m.group(1).split(','):
            part = part.strip().split()
            if part:
                names.add(part[-1] if part[0].lower() in ('экспорт', 'export') else part[0])
    for m in METHOD_RE.finditer(text):
        i = m.end()
        depth = 1
        start = i
        while i < len(text) and depth > 0:
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
            i += 1
        params = text[start:i - 1]
        for part in params.split(','):
            part = part.split('=')[0].strip()
            words = part.split()
            if words:
                names.add(words[-1])
    for rx in (ASSIGN_RE, FOREACH_RE, FOR_RE):
        for m in rx.finditer(text):
            names.add(m.group(1))
    return names


# --- Режим -Catalog: lint по каталогу дефектов ---
#
# Правила лежат в реестре scripts/catalog-rules.json рядом со скриптом: массив объектов
# id/title/kind. kind = regex (паттерн по строкам модуля; scope code - с погашенными
# литералами и комментариями, raw - по исходным строкам), query-regex (паттерн по строкам
# запросных литералов) и structure (многошаговая проверка по имени check). Идентификатор
# правила равен идентификатору карточки каталога skills/1c-code-review/references/catalog;
# пара фикстур tests/catalog/<ИД> задает ожидаемые строки - их сверяет гард
# tests/skills/check-lint-catalog.mjs на обоих портах. Все правила текстовые: типов,
# вызовов и семантики платформы здесь нет, находка - предупреждение, а не приговор.

CATALOG_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'catalog-rules.json')

# Обработчики событий, внутри которых платформа уже держит транзакцию (карточка TXN-06).
TXN_EVENT_HANDLERS = ('ПередЗаписью', 'ПриЗаписи', 'ОбработкаПроведения')
# Имена вызовов с побочными эффектами, которым не место внутри транзакции (карточка
# TXN-10): диалоги с пользователем, сетевые обращения, работа с файлами. Сопоставление
# по целому идентификатору вызова: подстрока давала ложные находки на
# ПолучитьИмяВременногоФайла и ВводНаОсновании.
TXN_SLOW_CALL_NAMES = frozenset((
    'вопрос', 'предупреждение', 'открытьзначение', 'сообщить', 'уведомить',
    'отправитьзапроснаружу', 'копироватьфайл', 'переместитьфайл', 'удалитьфайл',
    'найтифайлы',
))
# Слова обоснования законной блокировки без отбора: комментарий над вызовом (карточка TXN-08).
TXN08_COMMENT_MARKERS = ('отбор', 'пересчет', 'все записи')

CATALOG_RE = {
    'try': re.compile(r'\bПопытка\b', re.IGNORECASE),
    'except': re.compile(r'\bИсключение\b', re.IGNORECASE),
    'endtry': re.compile(r'\bКонецПопытки\b', re.IGNORECASE),
    'raise': re.compile(r'\bВызватьИсключение\b', re.IGNORECASE),
    'begin_txn': re.compile(r'\bНачатьТранзакцию\s*\(', re.IGNORECASE),
    'commit_txn': re.compile(r'\bЗафиксироватьТранзакцию\s*\(', re.IGNORECASE),
    'rollback_txn': re.compile(r'\bОтменитьТранзакцию\s*\(', re.IGNORECASE),
    'endproc': re.compile(r'\bКонецПроцедуры\b|\bКонецФункции\b', re.IGNORECASE),
    'event_proc': re.compile(r'\b(?:Процедура|Функция)\s+(?:'
                             + '|'.join(TXN_EVENT_HANDLERS) + r')\s*\(', re.IGNORECASE),
    'lock_new': re.compile(r'\b(\w+)\s*=\s*Новый\s+БлокировкаДанных\b', re.IGNORECASE),
    'lock_add': re.compile(r'\b(\w+)\s*\.\s*Добавить\s*\(\s*"[^"]*"\s*\)', re.IGNORECASE),
    'write_posting': re.compile(r'Записать\s*\([^)]*РежимЗаписиДокумента\s*\.\s*Проведение',
                                re.IGNORECASE),
    'const_read': re.compile(r'\bКонстанты\s*\.\s*\w+\s*\.\s*Получить\s*\(', re.IGNORECASE),
    'loop_open': re.compile(r'\bДля\s+Каждого\b|\bПока\b|\bДля\s+\w+\s*=', re.IGNORECASE),
    'loop_close': re.compile(r'\bКонецЦикла\b', re.IGNORECASE),
    'if_open': re.compile(r'\bЕсли\b', re.IGNORECASE),
    'elseif': re.compile(r'\bИначеЕсли\b', re.IGNORECASE),
    'else': re.compile(r'\bИначе\b', re.IGNORECASE),
    'endif': re.compile(r'\bКонецЕсли\b', re.IGNORECASE),
    'call': re.compile(r'\b(\w+)\s*\(', re.IGNORECASE),
}


def collect_query_literals(text):
    """Запросные литералы файла: (содержимое, номер строки начала) без кавычек-обертки.

    Литералом запроса считается строковый литерал со словом ВЫБРАТЬ: тексты запросов в
    модулях начинаются с него. Многострочный литерал занимает те же строки, что и в файле,
    поэтому k-я строка литерала лежит в строке start + k.
    """
    out = []
    for m in BSL_NOISE_RE.finditer(text):
        s = m.group(0)
        if not s or s[0] != '"':
            continue
        closed = len(s) >= 2 and s[-1] == '"'
        inner = s[1:-1] if closed else s[1:]
        if re.search(r'\bВЫБРАТЬ\b', inner, re.IGNORECASE):
            start_line = text.count('\n', 0, m.start()) + 1
            out.append((inner, start_line))
    return out


def _rstripped(lines):
    return [ln.rstrip('\r') for ln in lines]


def check_txn01(q):
    """TXN-01: НачатьТранзакцию() внутри Попытка - репорт на строке вызова."""
    out, stack = [], []
    for i, ln in enumerate(q, 1):
        s = ln.strip()
        if CATALOG_RE['try'].search(s):
            stack.append('try')
        if CATALOG_RE['except'].search(s) and stack and stack[-1] == 'try':
            stack[-1] = 'except'
        if CATALOG_RE['begin_txn'].search(s) and stack and stack[-1] == 'try':
            out.append(i)
        if CATALOG_RE['endtry'].search(s) and stack:
            stack.pop()
    return out


def _try_sections(q):
    """Секции Попытка..(Исключение|КонецПопытки): пары (первая строка, строка конца)."""
    sections = []
    n = len(q)
    for i, ln in enumerate(q):
        if not CATALOG_RE['try'].search(ln):
            continue
        end = n
        for j in range(i + 1, n):
            s = q[j].strip()
            if CATALOG_RE['except'].search(s) or CATALOG_RE['endtry'].search(s):
                end = j
                break
        sections.append((i, end))
    return sections


def _except_sections(q):
    """Секции Исключение..КонецПопытки: пары (строка Исключение, строка за концом)."""
    sections = []
    n = len(q)
    for i, ln in enumerate(q):
        if not CATALOG_RE['except'].search(ln) or CATALOG_RE['raise'].search(ln):
            continue
        end = n
        for j in range(i + 1, n):
            if CATALOG_RE['endtry'].search(q[j]):
                end = j
                break
        sections.append((i, end))
    return sections


def _first_meaningful(q, lo, hi):
    for k in range(lo, hi):
        if q[k].strip():
            return k
    return None


def check_txn02(q):
    """TXN-02: операторы между НачатьТранзакцию() и Попытка - репорт на первом из них."""
    out = []
    n = len(q)
    for i, ln in enumerate(q):
        if not CATALOG_RE['begin_txn'].search(ln):
            continue
        hit = None
        for j in range(i + 1, n):
            s = q[j].strip()
            if CATALOG_RE['endproc'].search(s):
                break
            if CATALOG_RE['try'].search(s):
                hit = j
                break
        if hit is None:
            continue
        k = _first_meaningful(q, i + 1, hit)
        if k is not None:
            out.append(k + 1)
    return out


def check_txn03(q):
    """TXN-03: операторы после ЗафиксироватьТранзакцию() в Попытка - репорт на первом."""
    out = []
    for i, end in _try_sections(q):
        for j in range(i + 1, end):
            if CATALOG_RE['commit_txn'].search(q[j]):
                k = _first_meaningful(q, j + 1, end)
                if k is not None:
                    out.append(k + 1)
                break
    return out


def check_txn04(q):
    """TXN-04: операторы в Исключении до ОтменитьТранзакцию() - репорт на первом."""
    out = []
    for i, end in _except_sections(q):
        body = '\n'.join(q[i:end])
        if not CATALOG_RE['rollback_txn'].search(body):
            continue
        k = _first_meaningful(q, i + 1, end)
        if k is not None and not CATALOG_RE['rollback_txn'].search(q[k]):
            out.append(k + 1)
    return out


def check_txn05(q):
    """TXN-05: Исключение с ОтменитьТранзакцию, но без ВызватьИсключение - репорт на Исключение."""
    out = []
    for i, end in _except_sections(q):
        body = '\n'.join(q[i:end])
        if CATALOG_RE['rollback_txn'].search(body) and not CATALOG_RE['raise'].search(body):
            out.append(i + 1)
    return out


def check_txn06(q):
    """TXN-06: НачатьТранзакцию() в ПередЗаписью/ПриЗаписи/ОбработкаПроведения."""
    out = []
    n = len(q)
    i = 0
    while i < n:
        if not CATALOG_RE['event_proc'].search(q[i]):
            i += 1
            continue
        j = i + 1
        while j < n and not CATALOG_RE['endproc'].search(q[j]):
            if CATALOG_RE['begin_txn'].search(q[j]):
                out.append(j + 1)
            j += 1
        i = j
    return out


def check_txn08(raw, q):
    """TXN-08: Добавить("таблица") без отбора у БлокировкаДанных, без обоснования.

    Законные формы карточки: блокировка всей таблицы с поясняющим комментарием в двух
    строках над вызовом и отбор по измерениям - УстановитьЗначение у элемента в
    следующих строках. Комментарий ищется по исходным строкам, остальное - по погашенным.
    """
    lockvars = set()
    for ln in q:
        m = CATALOG_RE['lock_new'].search(ln)
        if m:
            lockvars.add(m.group(1).lower())
    if not lockvars:
        return []
    setval_re = re.compile(r'\.\s*УстановитьЗначение\s*\(', re.IGNORECASE)
    out = []
    for i, ln in enumerate(q):
        m = CATALOG_RE['lock_add'].search(ln)
        if not m or m.group(1).lower() not in lockvars:
            continue
        suppressed = False
        for k in (i - 1, i - 2):
            if k < 0:
                continue
            src = raw[k].lower()
            if '//' in src and any(mk in src for mk in TXN08_COMMENT_MARKERS):
                suppressed = True
                break
        if not suppressed:
            for k in range(i + 1, min(i + 4, len(q))):
                if setval_re.search(q[k]):
                    suppressed = True
                    break
        if not suppressed:
            out.append(i + 1)
    return out


def check_txn10(q):
    """TXN-10: диалоги, сеть и файлы между НачатьТранзакцию() и фиксацией/отменой.

    Вызов сопоставляется со списком имен целиком (TXN_SLOW_CALL_NAMES), не подстрокой.
    """
    out = []
    n = len(q)
    i = 0
    while i < n:
        if not CATALOG_RE['begin_txn'].search(q[i]):
            i += 1
            continue
        j = i + 1
        while j < n and not (CATALOG_RE['commit_txn'].search(q[j])
                             or CATALOG_RE['rollback_txn'].search(q[j])):
            for m in CATALOG_RE['call'].finditer(q[j]):
                if m.group(1).lower() in TXN_SLOW_CALL_NAMES:
                    out.append(j + 1)
                    break
            j += 1
        i = j
    return out


def check_txn11(q):
    """TXN-11: явная транзакция вокруг Записать(РежимЗаписиДокумента.Проведение)."""
    out = []
    n = len(q)
    i = 0
    while i < n:
        if not CATALOG_RE['begin_txn'].search(q[i]):
            i += 1
            continue
        j = i + 1
        posting = False
        while j < n and not (CATALOG_RE['commit_txn'].search(q[j])
                             or CATALOG_RE['rollback_txn'].search(q[j])):
            if CATALOG_RE['write_posting'].search(q[j]):
                posting = True
            j += 1
        if posting:
            out.append(i + 1)
        i = j if j > i else i + 1
    return out


def check_perf05(q):
    """PERF-05: чтение Константы.<Имя>.Получить() внутри цикла."""
    out = []
    depth = 0
    for i, ln in enumerate(q, 1):
        for _m in CATALOG_RE['loop_open'].finditer(ln):
            depth += 1
        if depth > 0 and CATALOG_RE['const_read'].search(ln):
            out.append(i)
        for _m in CATALOG_RE['loop_close'].finditer(ln):
            depth = max(0, depth - 1)
    return out


def check_model14(q):
    """MODEL-14: Если-ИначеЕсли из трех и более ветвей без Иначе - репорт на КонецЕсли."""
    out, stack = [], []
    for i, ln in enumerate(q, 1):
        if CATALOG_RE['if_open'].search(ln):
            stack.append([0, False])
        if CATALOG_RE['elseif'].search(ln) and stack:
            stack[-1][0] += 1
        if CATALOG_RE['else'].search(ln) and stack:
            stack[-1][1] = True
        if CATALOG_RE['endif'].search(ln) and stack:
            elseifs, has_else = stack.pop()
            if elseifs >= 2 and not has_else:
                out.append(i)
    return out


def _query_packs(inner, start):
    """Пакеты запроса по ';': список сегментов [(номер строки, текст)]."""
    packs, cur = [], []
    for k, ln in enumerate(inner.split('\n')):
        cur.append((start + k, ln.rstrip('\r')))
        if ';' in ln:
            packs.append(cur)
            cur = []
    if cur:
        packs.append(cur)
    return packs


def check_query18(literals):
    """QUERY-18: ПЕРВЫЕ без УПОРЯДОЧИТЬ ПО в пакете - репорт на строках ПЕРВЫЕ."""
    out = []
    for inner, start in literals:
        for pack in _query_packs(inner, start):
            text = '\n'.join(t for _n, t in pack)
            if not re.search(r'\bПЕРВЫЕ\b', text, re.IGNORECASE):
                continue
            if re.search(r'\bУПОРЯДОЧИТЬ\b', text, re.IGNORECASE):
                continue
            for n, t in pack:
                if re.search(r'\bПЕРВЫЕ\b', t, re.IGNORECASE):
                    out.append(n)
    return out


def check_query08(literals):
    """QUERY-08: ИЛИ по полям таблицы внутри секции ГДЕ."""
    section_re = re.compile(
        r'\b(?:УПОРЯДОЧИТЬ|СГРУППИРОВАТЬ|ИМЕЮЩИЕ|ОБЪЕДИНИТЬ|ИТОГИ)\b|;', re.IGNORECASE)
    where_re = re.compile(r'(?:^|\|)\s*ГДЕ\b', re.IGNORECASE)
    or_re = re.compile(r'(?:^|\|)\s*ИЛИ\s+\w+\.', re.IGNORECASE)
    out = []
    for inner, start in literals:
        in_where = False
        for k, ln in enumerate(inner.split('\n')):
            ln = ln.rstrip('\r')
            if where_re.search(ln):
                in_where = True
                continue
            if not in_where:
                continue
            if section_re.search(ln):
                in_where = False
                continue
            if or_re.search(ln):
                out.append(start + k)
    return out


def check_query13(raw, literals):
    """QUERY-13: Колонки.Добавить("Имя") без типа у переменной-параметра запроса.

    Колонка ловится только когда ее имя фигурирует в тексте запроса модуля: нестроковые
    колонки без типа соединение не ломают, и чистый признак - сама колонка в запросе.
    """
    param_vars = set()
    for ln in raw:
        m = re.search(r'УстановитьПараметр\s*\(\s*"[^"]*"\s*,\s*(\w+)', ln, re.IGNORECASE)
        if m:
            param_vars.add(m.group(1).lower())
    if not param_vars:
        return []
    words = set()
    for inner, _start in literals:
        for w in re.findall(r'\w+', inner):
            words.add(w.lower())
    add_re = re.compile(r'\b(\w+)\s*\.\s*Колонки\s*\.\s*Добавить\s*\(\s*"([^"]+)"\s*\)',
                        re.IGNORECASE)
    out = []
    for i, ln in enumerate(raw):
        for m in add_re.finditer(ln):
            if m.group(1).lower() in param_vars and m.group(2).lower() in words:
                out.append(i + 1)
                break
    return out


def _pos_line_fn(inner, start):
    """Функция смещение -> номер строки файла для позиций внутри литерала."""
    line_starts = [0]
    for k, ch in enumerate(inner):
        if ch == '\n':
            line_starts.append(k + 1)

    def pos_line(p):
        return start + bisect.bisect_right(line_starts, p) - 1

    return pos_line


def _correlated_subqueries(inner):
    """Подзапросы (ВЫБРАТЬ...) со ссылкой на псевдоним внешнего запроса.

    Возвращает пары (позиция открытия, позиции внешних ссылок внутри). Псевдонимы
    внешнего запроса - КАК <Имя> вне скобок подзапроса; ссылка - <псевдоним>. внутри.
    Некоррелированный подзапрос (законная форма QUERY-01) пары не дает.
    """
    aliases = [(m.group(1).lower(), m.start())
               for m in re.finditer(r'\bКАК\s+(\w+)', inner, re.IGNORECASE)]
    out = []
    # Подзапрос открывается скобкой, за которой до ВЫБРАТЬ возможны переводы строк и
    # линии продолжения | - многострочный подзапрос в литерале запроса.
    for m in re.finditer(r'\(\s*(?:\|\s*)*ВЫБРАТЬ', inner, re.IGNORECASE):
        open_pos = m.start()
        depth, close_pos = 0, len(inner)
        for p in range(open_pos, len(inner)):
            if inner[p] == '(':
                depth += 1
            elif inner[p] == ')':
                depth -= 1
                if depth == 0:
                    close_pos = p
                    break
        outer = {a for a, s in aliases if not open_pos <= s < close_pos}
        if not outer:
            continue
        used = [open_pos + 1 + um.start()
                for um in re.finditer(r'\b(\w+)\s*\.', inner[open_pos + 1:close_pos])
                if um.group(1).lower() in outer]
        if used:
            out.append((open_pos, used))
    return out


def _top_level_keyword_pos(inner, word):
    """Позиция первого вхождения слова вне скобок либо None."""
    for m in re.finditer(r'\b' + word + r'\b', inner, re.IGNORECASE):
        before = inner[:m.start()]
        if before.count('(') == before.count(')'):
            return m.start()
    return None


def check_query01(literals):
    """QUERY-01: коррелированный подзапрос в списке полей - репорт на открытии и ссылках.

    Место - секция полей: открытие подзапроса до первого ИЗ верхнего уровня. В ГДЕ
    коррелированный подзапрос - карточка QUERY-14, здесь он не репортится.
    """
    out = []
    for inner, start in literals:
        pos_line = _pos_line_fn(inner, start)
        iz = _top_level_keyword_pos(inner, 'ИЗ')
        for open_pos, used in _correlated_subqueries(inner):
            if iz is not None and open_pos > iz:
                continue
            out.append(pos_line(open_pos))
            out.extend(pos_line(p) for p in used)
    return sorted(set(out))


def check_query14(literals):
    """QUERY-14: подзапрос в скобках использует псевдоним внешнего запроса.

    Репорт на строке открытия подзапроса и на строках внешних ссылок внутри него.
    """
    out = []
    for inner, start in literals:
        pos_line = _pos_line_fn(inner, start)
        for open_pos, used in _correlated_subqueries(inner):
            out.append(pos_line(open_pos))
            out.extend(pos_line(p) for p in used)
    return sorted(set(out))


def check_query15(literals):
    """QUERY-15: ВТ помещена без ИНДЕКСИРОВАТЬ ПО и соединяется в следующем пакете."""
    out = []
    for inner, start in literals:
        packs = _query_packs(inner, start)
        if len(packs) < 2:
            continue
        for pi, pack in enumerate(packs):
            text = '\n'.join(t for _n, t in pack)
            m = re.search(r'\bПОМЕСТИТЬ\s+(\w+)', text, re.IGNORECASE)
            if not m or re.search(r'\bИНДЕКСИРОВАТЬ\b', text, re.IGNORECASE):
                continue
            vt = m.group(1)
            rest = '\n'.join(t for p2 in packs[pi + 1:] for _n, t in p2)
            if re.search(r'\bСОЕДИНЕНИЕ\s+' + re.escape(vt) + r'\b', rest, re.IGNORECASE):
                for n, t in pack:
                    if re.search(r'\bПОМЕСТИТЬ\b', t, re.IGNORECASE):
                        out.append(n)
                        break
    return out


def check_sec01(text):
    """SEC-01: значение конкатенацией в литерал текста запроса вместо параметра.

    Литералы запроса многострочны, поэтому признак ищется по файлу целиком: литерал
    с ключевым словом запроса закрывается кавычкой, за которой сразу идет + и идентификатор.
    Репорт на строке закрытия литерала.
    """
    kw = re.compile(r'\b(?:ВЫБРАТЬ|ГДЕ|ИЗ|ПОДОБНО|СОЕДИНЕНИЕ|УПОРЯДОЧИТЬ|СГРУППИРОВАТЬ'
                    r'|ПОМЕСТИТЬ)\b', re.IGNORECASE)
    concat = re.compile(r'^[ \t]*\+[ \t]*\w')
    out = []
    for m in BSL_NOISE_RE.finditer(text):
        s = m.group(0)
        if not s or s[0] != '"' or len(s) < 2 or s[-1] != '"':
            continue
        if not kw.search(s[1:-1]):
            continue
        if concat.match(text[m.end():m.end() + 60]):
            out.append(text.count('\n', 0, m.end()) + 1)
    return out


def check_model18(q):
    """MODEL-18: пустой блок Исключение - репорт на строке Исключения."""
    out = []
    for i, end in _except_sections(q):
        if all(not ln.strip() for ln in q[i + 1:end]):
            out.append(i + 1)
    return out


def check_model22(q):
    """MODEL-22: удаление элемента коллекции внутри обхода этой же коллекции.

    Репорт на строке вызова Удалить. Обход ищется до первого КонецЦикла после
    заголовка: вложенные циклы с теми же именами редки, ложных находок нет.
    """
    out = []
    text = '\n'.join(q)
    head = re.compile(r'\bДля\s+Каждого\s+(\w+)\s+Из\s+(\w+)\b', re.IGNORECASE)
    close = re.compile(r'\bКонецЦикла\b', re.IGNORECASE)
    for m in head.finditer(text):
        item, coll = m.group(1), m.group(2)
        line_no = text.count('\n', 0, m.start()) + 1
        rest = text[m.end():]
        em = close.search(rest)
        scope_text = rest[:em.start()] if em else rest
        del_re = re.compile(r'\b' + re.escape(coll) + r'\s*\.\s*Удалить\s*\(\s*'
                            + re.escape(item) + r'\s*\)', re.IGNORECASE)
        dm = del_re.search(scope_text)
        if dm:
            out.append(line_no + scope_text.count('\n', 0, dm.start()))
    return out


STRUCTURE_CHECKS = {
    'model-14': check_model14,
    'model-18': check_model18,
    'model-22': check_model22,
    'perf-05': check_perf05,
    'query-01': check_query01,
    'query-08': check_query08,
    'query-13': check_query13,
    'query-14': check_query14,
    'query-15': check_query15,
    'query-18': check_query18,
    'sec-01': check_sec01,
    'txn-01': check_txn01,
    'txn-02': check_txn02,
    'txn-03': check_txn03,
    'txn-04': check_txn04,
    'txn-05': check_txn05,
    'txn-06': check_txn06,
    'txn-08': check_txn08,
    'txn-10': check_txn10,
    'txn-11': check_txn11,
}


def load_catalog_rules():
    """Реестр правил lint: массив объектов id/title/kind (+pattern+scope либо check)."""
    try:
        with open(CATALOG_RULES_PATH, 'r', encoding='utf-8-sig') as fh:
            rules = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write('Catalog rules registry not readable: %s (%s)\n'
                         % (CATALOG_RULES_PATH, exc))
        return None
    if not isinstance(rules, list) or not rules:
        sys.stderr.write('Catalog rules registry must be a non-empty array\n')
        return None
    seen = set()
    for rule in rules:
        rid = rule.get('id')
        kind = rule.get('kind')
        if not isinstance(rid, str) or not rid:
            sys.stderr.write('Catalog rule without id: %s\n' % json.dumps(rule, ensure_ascii=False))
            return None
        if rid in seen:
            sys.stderr.write('Catalog rule %s listed twice\n' % rid)
            return None
        seen.add(rid)
        if kind == 'structure':
            if rule.get('check') not in STRUCTURE_CHECKS:
                sys.stderr.write('Catalog rule %s: unknown check %s\n' % (rid, rule.get('check')))
                return None
        elif kind in ('regex', 'query-regex'):
            pattern = rule.get('pattern')
            if not isinstance(pattern, str):
                sys.stderr.write('Catalog rule %s: regex rule without pattern\n' % rid)
                return None
            try:
                re.compile(pattern)
            except re.error as exc:
                sys.stderr.write('Catalog rule %s: pattern not compiled (%s)\n' % (rid, exc))
                return None
            if kind == 'regex' and rule.get('scope') not in ('code', 'raw'):
                sys.stderr.write('Catalog rule %s: scope must be code or raw\n' % rid)
                return None
        else:
            sys.stderr.write('Catalog rule %s: unknown kind %s\n' % (rid, kind))
            return None
    return rules


def run_catalog_rules(raw, rule_ids, rules_by_id):
    """Прогон правил по одному модулю. Возвращает {(id, line)}."""
    quiet = strip_bsl_noise(raw)
    q = _rstripped(quiet.split('\n'))
    src = _rstripped(raw.split('\n'))
    literals = collect_query_literals(raw)
    findings = set()
    for rid in rule_ids:
        rule = rules_by_id[rid]
        kind = rule['kind']
        if kind == 'regex':
            rx = re.compile(rule['pattern'])
            lines = src if rule.get('scope') == 'raw' else q
            for i, ln in enumerate(lines):
                if ln and rx.search(ln):
                    findings.add((rid, i + 1))
        elif kind == 'query-regex':
            # Матч по тексту литерала целиком: скобка и ВЫБРАТЬ на разных строках
            # построчному поиску не видны. Номер строки - по смещению совпадения.
            rx = re.compile(rule['pattern'])
            for inner, start in literals:
                for m in rx.finditer(inner):
                    findings.add((rid, start + inner.count('\n', 0, m.start())))
        else:
            fn = STRUCTURE_CHECKS[rule['check']]
            # сигнатуры проверок различаются набором контекста; передаем по имени
            names = fn.__code__.co_varnames[:fn.__code__.co_argcount]
            ctx = {'q': q, 'raw': src, 'literals': literals, 'text': raw}
            for line in fn(*[ctx.get(n) for n in names]):
                findings.add((rid, line))
    return findings


def catalog_main(args):
    """Режим -Catalog: lint модулей по реестру каталога дефектов. Коды 0/1/2."""
    rules = load_catalog_rules()
    if rules is None:
        return 2
    rules_by_id = {r['id']: r for r in rules}
    rule_ids = list(rules_by_id)
    if args.RuleId:
        if args.RuleId not in rules_by_id:
            sys.stderr.write("Rule '%s' is not in the catalog registry\n" % args.RuleId)
            return 2
        rule_ids = [args.RuleId]

    module_path = args.ModulePath
    if not os.path.isabs(module_path):
        module_path = os.path.join(os.getcwd(), module_path)
    root = module_path
    if os.path.isdir(module_path):
        modules = []
        for dirpath, _dirs, files in os.walk(module_path):
            for f in sorted(files):
                if f.lower().endswith('.bsl'):
                    modules.append(os.path.join(dirpath, f))
        modules.sort()
        def rel_label(p):
            return os.path.relpath(p, root).replace('\\', '/')
    elif os.path.isfile(module_path):
        modules = [module_path]
        def rel_label(_p):
            return os.path.basename(module_path)
    else:
        sys.stderr.write('Module path not found: ' + module_path + '\n')
        return 2

    findings = []
    for path in modules:
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
                raw = fh.read()
        except OSError as exc:
            sys.stderr.write('%s: not readable (%s)\n' % (path, exc))
            return 2
        label = rel_label(path)
        src_lines = _rstripped(raw.split('\n'))
        for rid, line in run_catalog_rules(raw, rule_ids, rules_by_id):
            fragment = src_lines[line - 1].strip()[:100] if line <= len(src_lines) else ''
            findings.append({'id': rid, 'file': label, 'line': line, 'match': fragment})

    # Порядок находок един в обоих портах: файл, строка, идентификатор.
    findings.sort(key=lambda f: (f['file'], f['line'], f['id']))

    sha = hashlib.sha256()
    for path in modules:
        sha.update(rel_label(path).encode('utf-8'))
        sha.update(b'\0')
        with open(path, 'rb') as fh:
            sha.update(fh.read())
        sha.update(b'\0')
    payload = {
        'check': 'bsl_validate@configurator',
        'ids': sorted({f['id'] for f in findings}),
        'inputHash': sha.hexdigest(),
        'status': 'findings' if findings else 'pass',
        'findings': findings,
    }
    # Компактные разделители: строка EVIDENCE и -Json обязаны совпадать у портов байт в байт.
    compact = {'ensure_ascii': False, 'separators': (',', ':')}
    if args.Json:
        sys.stdout.write(json.dumps(payload, **compact) + '\n')
        return 1 if findings else 0

    lines = ['=== BSL catalog lint: %d module(s), %d rule(s) ===' % (len(modules), len(rule_ids)),
             '']
    for f in findings:
        lines.append('[%s] %s:%d  %s' % (f['id'], f['file'], f['line'], f['match']))
    lines.append('')
    lines.append('=== Result: %d finding(s) ===' % len(findings))
    lines.append('EVIDENCE ' + json.dumps(payload, **compact))
    sys.stdout.write('\n'.join(lines) + '\n')
    return 1 if findings else 0


def main():
    # newline="" отключает трансляцию \n в \r\n: вывод портов сверяется гардом байт в байт.
    sys.stdout.reconfigure(encoding="utf-8", newline="")
    sys.stderr.reconfigure(encoding="utf-8", newline="")
    parser = argparse.ArgumentParser(
        description='Check BSL module calls against a configuration index', allow_abbrev=False)
    parser.add_argument('-ModulePath', dest='ModulePath', required=True)
    parser.add_argument('-IndexPath', dest='IndexPath', required=False)
    parser.add_argument('-UnknownCalls', action='store_true')
    parser.add_argument('-Detailed', action='store_true')
    parser.add_argument('-MaxErrors', dest='MaxErrors', type=int, default=30)
    parser.add_argument('-Catalog', action='store_true',
                        help='lint по реестру каталога дефектов вместо индекса')
    parser.add_argument('-RuleId', dest='RuleId',
                        help='в режиме -Catalog выполнить только правило карточки с этим ИД')
    parser.add_argument('-Json', action='store_true',
                        help='в режиме -Catalog печатать только JSON со строкой результата')
    args = parser.parse_args()

    if args.RuleId and not args.Catalog:
        sys.stderr.write('-RuleId имеет смысл только вместе с -Catalog\n')
        return 2
    if args.Catalog:
        return catalog_main(args)

    if not args.IndexPath:
        sys.stderr.write('the following arguments are required: -IndexPath '
                         '(или режим -Catalog, где индекс не нужен)\n')
        return 2

    module_path = args.ModulePath
    if not os.path.isabs(module_path):
        module_path = os.path.join(os.getcwd(), module_path)
    if os.path.isdir(module_path):
        modules = []
        for root, _dirs, files in os.walk(module_path):
            for f in sorted(files):
                if f.lower().endswith('.bsl'):
                    modules.append(os.path.join(root, f))
        modules.sort()
    elif os.path.isfile(module_path):
        modules = [module_path]
    else:
        sys.stderr.write('Module path not found: ' + module_path + '\n')
        return 1

    index_path = args.IndexPath
    if not os.path.isabs(index_path):
        index_path = os.path.join(os.getcwd(), index_path)
    if not os.path.isfile(index_path):
        sys.stderr.write('Index file not found: ' + index_path + '\n')
        return 1
    with open(index_path, 'r', encoding='utf-8') as fh:
        index_data = json.load(fh)
    if index_data.get('format') != 1:
        sys.stderr.write('Index format %s is not supported\n' % index_data.get('format'))
        return 1

    common_modules = index_data.get('commonModules') or {}
    lenient = index_data.get('kind') == 'extension'

    common_modules_lower = dict((k.lower(), v) for k, v in common_modules.items())
    known_globals_lower = set(g.lower() for g in KNOWN_GLOBAL_ROOTS)
    missing_modules_reported = set()

    warnings = []
    checked_calls = 0
    checked_modules = 0

    def add_bsl_warn(msg):
        if len(warnings) < args.MaxErrors:
            warnings.append(msg)

    for path in modules:
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
                raw = fh.read()
        except Exception as exc:
            add_bsl_warn('%s: не прочитан (%s)' % (os.path.basename(path), exc))
            continue
        checked_modules += 1
        text = strip_bsl_noise(raw)
        label = os.path.basename(os.path.dirname(os.path.dirname(path))) or os.path.basename(path)
        # Общий модуль - единственное место, где список имен ЗАМКНУТ: контекста формы или объекта
        # у него нет, поэтому неизвестное имя действительно подозрительно.
        # Разделитель приводится к одному виду: путь могли передать и через прямой слеш.
        norm_path = path.replace('\\', '/')
        is_common = '/CommonModules/' in norm_path
        # Локальные имена нужны ВСЕГДА, а не только под флагом: параметр или переменная могут
        # называться как общий модуль, и тогда вызов идет через нее, а не через модуль.
        locals_here = collect_local_names(text)
        locals_lower = set(n.lower() for n in locals_here)

        for m in CALL_RE.finditer(text):
            # Цепочка Справочники.Номенклатура.СоздатьЭлемент() дала бы ложный корень
            # "Номенклатура": образец ловит ЛЮБЫЕ два звена. Корнем считается только звено,
            # перед которым нет точки.
            back = text[:m.start()].rstrip()
            if back.endswith('.'):
                continue
            root, method = m.group(1), m.group(2)
            # BSL регистронезависим: общиеФункции.заполнено() - тот же вызов.
            root_lower = root.lower()
            if root_lower in locals_lower:
                continue
            module_info = common_modules_lower.get(root_lower)
            if module_info is not None:
                checked_calls += 1
                exported = set(n.lower() for n in (module_info.get('exported') or []))
                if method.lower() in exported:
                    continue
                if module_info.get('moduleMissing'):
                    if root_lower not in missing_modules_reported:
                        missing_modules_reported.add(root_lower)
                        add_bsl_warn("%s: у общего модуля '%s' нет файла модуля, вызовы к нему "
                                     "не проверялись" % (label, root))
                    continue
                if lenient:
                    add_bsl_warn("%s: '%s.%s' - в этой выгрузке метод не экспортный и его нет "
                                 "в модуле; возможно, он в основной конфигурации"
                                 % (label, root, method))
                else:
                    add_bsl_warn("%s: '%s.%s' - метод не экспортный или его нет в модуле"
                                 % (label, root, method))
                continue
            if not args.UnknownCalls or not is_common:
                continue
            if root_lower in known_globals_lower:
                continue
            checked_calls += 1
            if lenient:
                add_bsl_warn("%s: имя '%s' не объявлено в модуле и не является общим модулем этой "
                             "выгрузки - возможно, оно в основной конфигурации" % (label, root))
            else:
                add_bsl_warn("%s: имя '%s' не объявлено в модуле и не является общим модулем"
                             % (label, root))

    lines = ['=== BSL check: %d module(s) ===' % checked_modules, '']
    for w in warnings:
        lines.append('[WARN]  ' + w)
    if args.Detailed or not warnings:
        lines.append('[OK]    Общих модулей в индексе: %d' % len(common_modules))
        lines.append('[OK]    Вызовов проверено: %d' % checked_calls)
    lines.append('')
    lines.append('=== Result: %d warnings ===' % len(warnings))
    sys.stdout.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
