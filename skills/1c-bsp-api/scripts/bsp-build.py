#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Сборка справочника API БСП: документация ИТС плюс реальная реализация библиотеки.

Документация знает, ЧТО делает метод, но не знает, в каком общем модуле он лежит: крошки
статьи называют механизм, а не модуль. Реализация знает модули и сигнатуры, но не знает, какая
часть кода вынесена в публичный интерфейс. Справочник получается на стыке.

Вход:
  --docs   <версия>=<каталог скрапа ИТС>   можно указать несколько раз
  --lib    <каталог, куда v8unpack развернул 1Cv8.cf>
  --out    <файл .jsonl>

Скрап и дистрибутив библиотеки лицензионные и в репозиторий не кладутся. На выходе - только
факты: имена, сигнатуры, типы, контексты выполнения, принадлежность подсистеме и версиям.

Распаковать дистрибутив:  python -m v8unpack -E 1Cv8.cf <каталог> --temp <каталог-temp>
"""
import argparse
import collections
import io
import json
import os
import re
import sys

IDENT = r'[A-Za-z_А-яЁё][A-Za-z0-9_А-яЁё]*'

# --- разбор страниц документации ------------------------------------------------------------
SEC_RE = re.compile(r'^(Синтаксис|Параметры|Возвращаемое значение|Пример вызова|Пример реализации|'
                    r'Доступность|Расположение)\s*\n+```\n(.*?)```', re.S | re.M)
SIGN_RE = re.compile(r'^\s*(?:(Асинх|Async)\s+)?(Процедура|Функция|Procedure|Function)\s+('
                     + IDENT + r')\s*\(', re.S)
LOC_RE = re.compile(r'^[ \t]*Общий модуль\s+(' + IDENT + r')', re.M)
PARAM_TYPE_RE = re.compile(r'\s{0,6}(' + IDENT + r')\s+-\s+([^-\n]{1,60}?)\s*(?:-|$)')

# --- разбор кода ----------------------------------------------------------------------------
# Литерал ИЛИ комментарий: что началось раньше, то и поглощает второе. Закрывающая кавычка
# необязательна - незакрытый литерал гасит остаток файла.
NOISE_RE = re.compile(r'"(?:[^"]|"")*"?|//[^\n]*')
SIG_RE = re.compile(r'^[ \t]*(?:(Асинх|Async)[ \t]+)?(Процедура|Функция|Procedure|Function)[ \t]+('
                    + IDENT + r')[ \t]*\(', re.IGNORECASE | re.MULTILINE)
TAIL_RE = re.compile(r'^\s*(Экспорт|Export)\b', re.IGNORECASE)

# Позиции флагов в CommonModule.json (v8unpack), расшифрованы сверкой с XML-выгрузкой на 425
# модулях с полным совпадением. Шестая позиция - не флаг, а ReturnValuesReuse.
FLAG_POS = {0: 'ClientOrdinaryApplication', 1: 'Server', 2: 'ExternalConnection', 3: 'Privileged',
            4: 'Global', 5: 'ClientManagedApplication', 7: 'ServerCall'}
REUSE = {'0': None, '1': 'НаВремяВызова', '2': 'НаВремяСеанса'}

AV_SHORT = {'Сервер': 'S', 'Вызов сервера': 'C', 'Тонкий клиент': 'T',
            'Толстый клиент': 'F', 'Внешнее соединение': 'E'}
# Источник имени модуля. Показывает, насколько запись факт, а не вывод: L - документация назвала
# модуль сама; P - префикс из примера, подтвержденный реализацией; A - выбор по контекстам
# выполнения; O - модуль объекта или менеджера; P? - имя названо документацией, но в дистрибутиве
# этой версии такого метода нет (объект выведен из поставки либо документация отстала).
SRC_CODE = {'Расположение': 'L', 'префикс подтвержден реализацией': 'P',
            'префикс плюс доступность': 'PA', 'доступность': 'A',
            'доступность плюс префикс': 'AP', 'модуль объекта или менеджера': 'O',
            'модуль объекта, выбран по подсистеме': 'OS',
            'префикс без подтверждения': 'P?'}

KIND_RU = {
    'Catalog': 'Справочник', 'Document': 'Документ', 'DataProcessor': 'Обработка',
    'Report': 'Отчет', 'InformationRegister': 'РегистрСведений',
    'AccumulationRegister': 'РегистрНакопления', 'BusinessProcess': 'БизнесПроцесс',
    'ChartOfCharacteristicType': 'ПланВидовХарактеристик', 'Task': 'Задача',
    'ExchangePlan': 'ПланОбмена', 'Constant': 'Константа', 'DocumentJournal': 'ЖурналДокументов',
    'WebService': 'WebСервис', 'HTTPService': 'HTTPСервис', 'FilterCriterion': 'КритерийОтбора',
    'SettingsStorage': 'ХранилищеНастроек', 'CalculationRegister': 'РегистрРасчета',
    'AccountingRegister': 'РегистрБухгалтерии',
}

# Префиксы из примеров вызова, которые общими модулями не являются.
NOT_A_MODULE_RE = re.compile(r'(Объект|Ссылка|Менеджер|Форма|Набор|Запись)$')

# Менеджер объектов метаданных в примерах: Обработки.Имя, Отчеты.Имя и так далее.
MANAGER_RU = {'Обработки': 'Обработка', 'Отчеты': 'Отчет', 'Справочники': 'Справочник',
              'Документы': 'Документ', 'РегистрыСведений': 'РегистрСведений',
              'РегистрыНакопления': 'РегистрНакопления', 'ПланыОбмена': 'ПланОбмена',
              'БизнесПроцессы': 'БизнесПроцесс', 'Задачи': 'Задача',
              'ЖурналыДокументов': 'ЖурналДокументов', 'Константы': 'Константа'}
# Пример вида "ОбработкаОбъект = Обработки.Имя.Создать();" - дальше метод зовут через переменную,
# и без этой связки настоящее имя обработки теряется.
CREATE_RE = re.compile(r'(' + IDENT + r')\s*=\s*(' + '|'.join(MANAGER_RU) +
                       r')\.(' + IDENT + r')\s*\.\s*(?:Создать\w*)\s*\(')
MANAGER_CALL_RE = re.compile(r'(' + '|'.join(MANAGER_RU) + r')\.(' + IDENT + r')\s*\.\s*%s\b')


def blank_noise(text):
    """Гасит строковые литералы и комментарии за один проход, сохраняя длину и переводы строк."""
    def blank(m):
        s = m.group(0)
        if s[0] == '/':
            return ' ' * len(s)
        closed = len(s) >= 2 and s[-1] == '"'
        inner = s[1:-1] if closed else s[1:]
        body = ' ' * len(inner) if '\n' not in inner \
            else ''.join('\n' if c == '\n' else ' ' for c in inner)
        return '"' + body + ('"' if closed else '')
    return NOISE_RE.sub(blank, text)


def exported_methods(text):
    """Экспортные методы модуля: имя, вид, сигнатура одной строкой."""
    src = blank_noise(text)
    out = []
    for m in SIG_RE.finditer(src):
        i, depth = m.end() - 1, 0
        while i < len(src):
            if src[i] == '(':
                depth += 1
            elif src[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            continue
        if not TAIL_RE.match(src[i + 1:i + 240].lstrip('\r\n \t')):
            continue
        out.append({'name': m.group(3), 'kind': m.group(2), 'async': bool(m.group(1)),
                    'signature': ' '.join(text[m.start():i + 1].split())})
    return out


def read_module_text(path):
    if not os.path.exists(path):
        return ''
    return io.open(path, encoding='utf-8-sig', errors='replace', newline='').read()


# --- сторона реализации ---------------------------------------------------------------------
def parse_impl(root):
    """Контейнеры кода библиотеки: общие модули плюс модули объектов и менеджеров.

    Формы не берутся: их методы программным интерфейсом библиотеки не являются.
    """
    containers = {}
    base = os.path.join(root, 'CommonModule')
    if not os.path.isdir(base):
        raise SystemExit('в каталоге %s нет папки CommonModule - это не распакованный .cf' % root)

    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        jp = os.path.join(d, 'CommonModule.json')
        if not os.path.isdir(d) or not os.path.exists(jp):
            continue
        meta = json.load(io.open(jp, encoding='utf-8'))
        flags, reuse = {}, None
        try:
            tail = meta['header'][0][1][2:10]
            if len(tail) >= 8 and all(isinstance(v, str) for v in tail):
                flags = {n: tail[p] == '1' for p, n in FLAG_POS.items()}
                reuse = REUSE.get(tail[6])
        except (KeyError, IndexError, TypeError):
            pass
        av = []
        for flag, label in (('Server', 'Сервер'), ('ServerCall', 'Вызов сервера'),
                            ('ClientManagedApplication', 'Тонкий клиент'),
                            ('ClientOrdinaryApplication', 'Толстый клиент'),
                            ('ExternalConnection', 'Внешнее соединение')):
            if flags.get(flag):
                av.append(label)
        containers[name] = {'kind': 'ОбщийМодуль', 'availability': av, 'reuse': reuse,
                            'privileged': bool(flags.get('Privileged')),
                            'methods': exported_methods(read_module_text(
                                os.path.join(d, 'CommonModule.obj.bsl')))}

    for kind in sorted(os.listdir(root)):
        kd = os.path.join(root, kind)
        if kind == 'CommonModule' or not os.path.isdir(kd):
            continue
        ru = KIND_RU.get(kind, kind)
        for obj in sorted(os.listdir(kd)):
            od = os.path.join(kd, obj)
            if not os.path.isdir(od):
                continue
            for suffix, label in ((kind + '.obj.bsl', 'модуль объекта'),
                                  (kind + '.mgr.bsl', 'модуль менеджера')):
                ms = exported_methods(read_module_text(os.path.join(od, suffix)))
                if not ms:
                    continue
                containers['%s.%s (%s)' % (ru, obj, label)] = {
                    'kind': ru, 'availability': [], 'reuse': None, 'privileged': False,
                    'methods': ms}
    return containers


# --- сторона документации -------------------------------------------------------------------
def split_params(sig):
    """Параметры из сигнатуры: имя, передача по значению, значение по умолчанию."""
    i = sig.find('(')
    if i < 0:
        return []
    depth, j = 0, i
    while j < len(sig):
        if sig[j] == '(':
            depth += 1
        elif sig[j] == ')':
            depth -= 1
            if depth == 0:
                break
        j += 1
    # Запятая разделяет параметры только вне скобок И вне строкового литерала: у части методов
    # значение по умолчанию - это сама запятая, например Разделитель = ",".
    parts, depth, cur, in_str = [], 0, '', False
    for ch in sig[i + 1:j]:
        if in_str:
            cur += ch
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur += ch
            continue
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    out = []
    for p in parts:
        p = ' '.join(p.split())
        if not p:
            continue
        byval = bool(re.match(r'(Знач|Val)\s+', p, re.I))
        rest = re.sub(r'^(Знач|Val)\s+', '', p, flags=re.I)
        name, _, dflt = rest.partition('=')
        out.append({'name': name.strip(), 'byval': byval,
                    'default': dflt.strip() or None})
    return out


def parse_docs(root):
    """Страницы главы 4 - программного интерфейса."""
    meta = json.load(io.open(os.path.join(root, '_meta.json'), encoding='utf-8'))
    out = []
    for x in meta:
        b = x['breadcrumb']
        if len(b) < 4 or not b[1].startswith('Глава 4'):
            continue
        p = os.path.join(root, 'markdown', x['filename_base'] + '.md')
        if not os.path.exists(p):
            continue
        body = io.open(p, encoding='utf-8').read()
        body = body.split('---', 2)[2] if body.startswith('---') else body
        secs = {m.group(1): m.group(2).strip('\n') for m in SEC_RE.finditer(body)}
        if 'Синтаксис' not in secs:
            continue
        ms = SIGN_RE.match(secs['Синтаксис'].strip())
        if not ms:
            continue
        name = ms.group(3)

        module, source, cands = None, None, []
        if 'Расположение' in secs:
            ml = LOC_RE.search(secs['Расположение'])
            if ml:
                module, source = ml.group(1), 'Расположение'
        if module is None:
            # Метод могут звать прямо через менеджер: Обработки.Имя.Метод().
            mc = MANAGER_CALL_RE.pattern % re.escape(name)
            for mm in re.finditer(mc, body):
                cands.append('%s.%s (модуль менеджера)' % (MANAGER_RU[mm.group(1)], mm.group(2)))
            # Либо через переменную, которой присвоили Обработки.Имя.Создать().
            created = {mm.group(1): '%s.%s (модуль объекта)' % (MANAGER_RU[mm.group(2)], mm.group(3))
                       for mm in CREATE_RE.finditer(body)}
            pref = collections.Counter(
                mm.group(1) for mm in
                re.finditer(r'(' + IDENT + r')\.' + re.escape(name) + r'\b', body))
            for p in pref:
                if p in created:
                    cands.append(created[p])
                elif not NOT_A_MODULE_RE.search(p):
                    cands.append(p)
            cands = sorted(set(cands))

        types = {}
        for line in (secs.get('Параметры') or '').split('\n'):
            m = PARAM_TYPE_RE.match(line)
            if m:
                types.setdefault(m.group(1), m.group(2).strip())
        params = split_params(' '.join(secs['Синтаксис'].split()))
        for pr in params:
            pr['type'] = types.get(pr['name'])

        out.append({
            'name': name,
            'async': bool(ms.group(1)),
            'kind': ms.group(2),
            'subsystem': b[2],
            'section': b[3],
            'group': b[4] if len(b) > 5 else None,
            'module': module,
            'module_source': source,
            'candidates': cands,
            'availability': [s.strip() for s in secs.get('Доступность', '').split(',') if s.strip()],
            'signature': ' '.join(secs['Синтаксис'].split()),
            'params': params,
            'returns': secs.get('Возвращаемое значение'),
        })
    return out


# --- сшивка ---------------------------------------------------------------------------------
def public_only(cands, section):
    """Отсев кандидатов, которые публичным интерфейсом быть не могут.

    Оба правила проверены сплошь: ни один документированный метод не лежит в служебном модуле,
    а раздел Переопределение ложится ровно в переопределяемые модули и никуда больше.
    """
    out = [c for c in cands if 'Служебн' not in c]
    if section == 'Переопределение':
        pick = [c for c in out if 'Переопределяем' in c]
    else:
        pick = [c for c in out if 'Переопределяем' not in c]
    return pick or out or list(cands)


def resolve_module(doc, impl, by_name):
    """Модуль метода. Возвращает (модуль, источник) - источник показывает, насколько это факт."""
    owners = by_name.get(doc['name'].lower(), [])
    common = public_only([c for c in owners if impl[c]['kind'] == 'ОбщийМодуль'], doc['section'])
    other = sorted(set(c for c in owners if impl[c]['kind'] != 'ОбщийМодуль'))
    av = set(doc['availability'])

    if doc['module_source'] == 'Расположение':
        m = doc['module']
        return (m, 'Расположение') if m in impl else (m, 'Расположение (в реализации нет)')

    fixed = []
    for c in doc['candidates']:
        if c in impl:
            fixed.append(c)
        elif c.startswith('Модуль') and c[6:] in impl:
            fixed.append(c[6:])          # идиома ОбщегоНазначения.ОбщийМодуль("Имя")

    confirmed = sorted(set(c for c in fixed if c in common))
    if len(confirmed) == 1:
        return confirmed[0], 'префикс подтвержден реализацией'
    if len(confirmed) > 1:
        byav = [c for c in confirmed if set(impl[c]['availability']) == av]
        if len(byav) == 1:
            return byav[0], 'префикс плюс доступность'

    if common:
        byav = [c for c in sorted(set(common)) if set(impl[c]['availability']) == av]
        if len(byav) == 1:
            return byav[0], 'доступность'
        if len(byav) > 1:
            inter = [c for c in byav if c in fixed]
            if len(inter) == 1:
                return inter[0], 'доступность плюс префикс'
            return None, 'несколько общих модулей с одной доступностью'
        return None, 'доступность не совпала ни с одним общим модулем'

    if other:
        if len(other) == 1:
            return other[0], 'модуль объекта или менеджера'
        sub = re.sub(r'[^A-Za-zА-яЁё]', '', doc['subsystem']).lower()[:10]
        near = [c for c in other if sub and sub in re.sub(r'[^A-Za-zА-яЁё]', '', c).lower()]
        if len(near) == 1:
            return near[0], 'модуль объекта, выбран по подсистеме'
        return None, 'метод есть в %d модулях объектов' % len(other)

    if len(set(fixed)) == 1:
        return sorted(set(fixed))[0], 'префикс без подтверждения'
    # Последняя попытка: документация называет владельца, а в этой сборке библиотеки его нет.
    # Так бывает у обработок обмена, выведенных из поставки: имя из примера достоверно, а
    # проверить его нечем. Отдаем с явной пометкой, а не молчим.
    raw = sorted(set(c for c in doc['candidates'] if not NOT_A_MODULE_RE.search(c)))
    if len(raw) == 1:
        return raw[0], 'префикс без подтверждения'
    return None, 'метода нет в реализации'


def version_deltas(by_ver, versions, base_rec):
    """Чем метод отличался в прежних версиях от того, что записано как основное.

    Записывать только последнюю версию нельзя: между 3.1.11 и 3.2.1 у части методов изменилась
    сигнатура, причем ломающе - процедура стала функцией, параметр вставлен НЕ в конец. Код,
    написанный по новой сигнатуре, на старой версии передаст аргументы не туда.
    """
    if len(by_ver) < 2:
        return None
    newest = [v for v in versions if v in by_ver][-1]
    out = {}
    for ver in versions:
        if ver not in by_ver or ver == newest:
            continue
        d = by_ver[ver]
        delta = {}
        if d['signature'] != base_rec['sig']:
            delta['sig'] = d['signature']
        av = ''.join(AV_SHORT.get(a, '?') for a in d['availability'])
        if av != base_rec['av']:
            delta['av'] = av
        # Отличие по возврату записывается только когда ОБА типа названы. Отсутствие секции в
        # старой документации - это ее неполнота, а не смена контракта, и в отличия не идет.
        rt = return_type(d.get('returns'))
        if rt and base_rec.get('ret') and rt != base_rec['ret']:
            delta['ret'] = rt
        kind = 'Ф' if d['kind'].lower().startswith(('функ', 'func')) else 'П'
        if kind != base_rec['k']:
            delta['k'] = kind
        if d['subsystem'] != base_rec['sub']:
            delta['sub'] = d['subsystem']
        if delta:
            out[ver] = delta
    return out or None


def return_type(raw):
    """Тип возвращаемого значения - первое слово секции."""
    if not raw:
        return None
    m = re.match(r'\s*см\.\s*(' + IDENT + r'(?:\.' + IDENT + r')*)', raw.strip(), re.I)
    if m:
        return 'см. ' + m.group(1)
    m = re.match(r'\s*(' + IDENT + r'(?:\.' + IDENT + r')*)', raw.strip())
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--docs', action='append', required=True, metavar='ВЕРСИЯ=КАТАЛОГ',
                    help='скрап документации ИТС; можно указать несколько раз')
    ap.add_argument('--lib', action='append', required=True, metavar='[ВЕРСИЯ=]КАТАЛОГ',
                    help='каталог, куда v8unpack развернул 1Cv8.cf. С префиксом версии '
                         'привязывается к своей документации; без префикса берется для всех')
    ap.add_argument('--out', required=True, metavar='ФАЙЛ.jsonl')
    ap.add_argument('--map', metavar='ФАЙЛ.md',
                    help='заодно переписать карту подсистем')
    ap.add_argument('--purposes', metavar='ФАЙЛ.json',
                    help='свои однострочные формулировки назначения: "Модуль.Метод": "текст"')
    args = ap.parse_args()

    # Каждая версия документации сшивается со СВОЕЙ библиотекой. Иначе методы, убранные в новой
    # версии, объявляются несуществующими, а добавленные - неподтвержденными.
    libs, default_lib = {}, None
    for spec in args.lib:
        ver, sep, path = spec.partition('=')
        if not sep:
            ver, path = None, spec
        impl = parse_impl(path)
        index = collections.defaultdict(list)
        for cid, c in impl.items():
            for m in c['methods']:
                index[m['name'].lower()].append(cid)
        sys.stderr.write('реализация %s: контейнеров %d, экспортных методов %d\n'
                         % (ver or 'общая', len(impl), sum(len(c['methods']) for c in impl.values())))
        if ver:
            libs[ver] = (impl, index)
        else:
            default_lib = (impl, index)
    # Библиотеку без префикса версии подставляем любой документации. Молча подставлять вместо нее
    # "самую свежую из указанных" нельзя: опечатка в версии тогда сведет документацию с чужой
    # реализацией и выдаст неверные модули и контексты - ровно то, ради чего версии и разводились.

    # Формулировки назначения - единственная часть справочника, написанная нами, а не выведенная
    # из источников. Два раздела: чем занят модуль и что делает метод.
    purposes, mod_purposes = {}, {}
    if args.purposes and os.path.exists(args.purposes):
        p = json.load(io.open(args.purposes, encoding='utf-8'))
        if isinstance(p, dict) and ('methods' in p or 'modules' in p):
            purposes = p.get('methods') or {}
            mod_purposes = p.get('modules') or {}
        else:
            purposes = p
        sys.stderr.write('формулировки назначения: модулей %d, методов %d\n'
                         % (len(mod_purposes), len(purposes)))

    merged, seen, versions, per_version = {}, collections.defaultdict(set), [], {}
    stat = collections.Counter()
    for spec in args.docs:
        if '=' not in spec:
            raise SystemExit('--docs ждет ВЕРСИЯ=КАТАЛОГ, получено: %s' % spec)
        ver, path = spec.split('=', 1)
        versions.append(ver)
        pair = libs.get(ver, default_lib)
        if pair is None:
            raise SystemExit('для документации %s не указана библиотека: добавьте --lib "%s=<каталог>" '
                             'либо --lib <каталог> без версии. Известны: %s'
                             % (ver, ver, ', '.join(sorted(libs)) or 'ни одной'))
        impl, by_name = pair
        pages = parse_docs(path)
        for d in pages:
            module, source = resolve_module(d, impl, by_name)
            d['module'], d['module_source'] = module, source
            stat[source] += 1
            stat['всего'] += 1
            key = (module or '?', d['name'])
            seen[key].add(ver)
            merged[key] = d
            per_version.setdefault(key, {})[ver] = d
        sys.stderr.write('документация %s: методов %d\n' % (ver, len(pages)))

    resolved = sum(v for k, v in stat.items() if k in SRC_CODE)
    sys.stderr.write('сшивка: модуль определен у %d из %d (%.1f%%)\n'
                     % (resolved, stat['всего'], 100.0 * resolved / max(1, stat['всего'])))
    for k, v in stat.most_common():
        if k != 'всего' and k not in SRC_CODE:
            sys.stderr.write('   не разрешено - %s: %d\n' % (k, v))

    used = sorted({k[0] for k in merged})
    header = {'_': 'справочник API БСП', 'versions': versions, 'modules': {}}
    # Свойства модуля берутся из самой поздней библиотеки, где он есть: модуль мог быть убран,
    # и тогда о нем знает только более ранняя.
    lookup = [libs[v][0] for v in reversed(versions) if v in libs]
    if default_lib is not None:
        lookup.append(default_lib[0])
    for cid in used:
        c = next((L[cid] for L in lookup if cid in L), None)
        header['modules'][cid] = {
            'kind': c['kind'] if c else '?',
            'av': ''.join(AV_SHORT.get(a, '?') for a in c['availability']) if c else '',
            'reuse': c['reuse'] if c else None,
            'total': len(c['methods']) if c else 0,
        }
        if mod_purposes.get(cid):
            header['modules'][cid]['o'] = mod_purposes[cid]
    unknown = sorted(set(mod_purposes) - set(header['modules']))
    if unknown:
        sys.stderr.write('в формулировках есть модули, которых нет в справочнике: %s\n'
                         % ', '.join(unknown[:5]))
    unknown_m = sorted(set(purposes) - {'%s.%s' % k for k in merged})
    if unknown_m:
        sys.stderr.write('в формулировках есть методы, которых нет в справочнике: %d, например %s\n'
                         % (len(unknown_m), ', '.join(unknown_m[:3])))

    with io.open(args.out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(header, ensure_ascii=False, sort_keys=False) + '\n')
        for (mod, name), d in sorted(merged.items()):
            rec = {'m': mod, 'n': name,
                   'k': 'Ф' if d['kind'].lower().startswith(('функ', 'func')) else 'П',
                   'sig': d['signature'],
                   'av': ''.join(AV_SHORT.get(a, '?') for a in d['availability']),
                   'sub': d['subsystem'],
                   'sec': 'П' if d['section'] == 'Переопределение' else 'И',
                   'src': SRC_CODE.get(d['module_source'], '?'),
                   'v': sorted(seen[(mod, name)])}
            if d['async']:
                rec['async'] = True
            if d['group']:
                rec['grp'] = d['group']
            params = []
            for p in d['params']:
                q = {'n': p['name']}
                if p.get('type'):
                    q['t'] = p['type']
                if p.get('default'):
                    q['d'] = p['default']
                if p.get('byval'):
                    q['byval'] = True
                params.append(q)
            if params:
                rec['p'] = params
            rt = return_type(d.get('returns'))
            if rt:
                rec['ret'] = rt
            pur = purposes.get(mod + '.' + name)
            if pur:
                rec['o'] = pur
            was = version_deltas(per_version.get((mod, name), {}), versions, rec)
            if was:
                rec['was'] = was
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=False) + '\n')

    sys.stderr.write('записано: %s, методов %d, %.2f МБ\n'
                     % (args.out, len(merged), os.path.getsize(args.out) / 1048576.0))

    if args.map:
        write_subsystem_map(args.map, merged, versions)
        sys.stderr.write('записано: %s\n' % args.map)


def write_subsystem_map(path, merged, versions):
    """Карта подсистем: какие модули в каждой и где ее точки расширения.

    Имя подсистемы в документации и имя модуля в коде совпадают далеко не всегда, а без карты
    приходится угадывать: механизм печати живет в УправлениеПечатью, а не в Печать.
    """
    by_sub = collections.defaultdict(lambda: collections.defaultdict(int))
    for (mod, name), d in merged.items():
        by_sub[d['subsystem']][mod] += 1

    lines = ['# Карта подсистем БСП', '',
             'Собрано генератором из версий: %s. Правка вручную бессмысленна - файл '
             'перезаписывается при пересборке справочника.' % ', '.join(versions), '',
             'Имя подсистемы в документации и имя модуля в коде совпадают не всегда: механизм '
             'печати живет в `УправлениеПечатью`, свойства - в `УправлениеСвойствами`, а базовая '
             'функциональность - в `ОбщегоНазначения`. Поэтому модуль ищется по этой таблице, а не '
             'по названию подсистемы.', '',
             'Цифра в скобках - сколько методов подсистемы объявлено в этом модуле.', '',
             '| Подсистема | Программный интерфейс | Точки расширения |', '|---|---|---|']
    for sub in sorted(by_sub, key=lambda s: (-sum(by_sub[s].values()), s)):
        mods = by_sub[sub]
        api = [m for m in mods if 'Переопределяем' not in m and m != '?']
        ext = [m for m in mods if 'Переопределяем' in m]
        api.sort(key=lambda m: (-mods[m], m))
        ext.sort(key=lambda m: (-mods[m], m))
        lines.append('| %s | %s | %s |' % (sub, map_cell(api, mods), map_cell(ext, mods)))
    lines.append('')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines))


def map_cell(mods, counts, top=10):
    """Ячейка карты. В крупных подсистемах модулей десятки, и целиком они превращают строку
    таблицы в простыню. Перечисляются те, где методов больше; остальные считаются, а полный
    состав дает scripts/bsp-api.py subsystem."""
    if not mods:
        return '-'
    head = ', '.join('`%s` (%d)' % (m, counts[m]) for m in mods[:top])
    rest = len(mods) - top
    return head + (', и еще %d' % rest if rest > 0 else '')


if __name__ == '__main__':
    main()
