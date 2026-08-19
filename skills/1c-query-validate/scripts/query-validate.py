#!/usr/bin/env python3
# query-validate v1.0 - Check 1C query text against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Reads a query text and the index built by 1c-config-index, then reports table and field names
that do not exist in the configuration. This is NOT platform query validation: types, joins and
execution plan are out of reach without the platform."""
import sys, os, argparse, json, re

# Имя таблицы в запросе -> тип метаданных. Оба языка запроса: конфигурация может быть написана
# и по-русски, и по-английски, а проверять надо обе.
QUERY_TABLE_PREFIX_MAP = {
    'Справочник': 'Catalog', 'Catalog': 'Catalog',
    'Документ': 'Document', 'Document': 'Document',
    'Перечисление': 'Enum', 'Enum': 'Enum',
    'РегистрСведений': 'InformationRegister', 'InformationRegister': 'InformationRegister',
    'РегистрНакопления': 'AccumulationRegister', 'AccumulationRegister': 'AccumulationRegister',
    'РегистрБухгалтерии': 'AccountingRegister', 'AccountingRegister': 'AccountingRegister',
    'РегистрРасчета': 'CalculationRegister', 'CalculationRegister': 'CalculationRegister',
    'ПланСчетов': 'ChartOfAccounts', 'ChartOfAccounts': 'ChartOfAccounts',
    'ПланВидовХарактеристик': 'ChartOfCharacteristicTypes',
    'ChartOfCharacteristicTypes': 'ChartOfCharacteristicTypes',
    'ПланВидовРасчета': 'ChartOfCalculationTypes', 'ChartOfCalculationTypes': 'ChartOfCalculationTypes',
    'ПланОбмена': 'ExchangePlan', 'ExchangePlan': 'ExchangePlan',
    'БизнесПроцесс': 'BusinessProcess', 'BusinessProcess': 'BusinessProcess',
    'Задача': 'Task', 'Task': 'Task',
    'Константа': 'Constant', 'Constant': 'Constant',
    'ЖурналДокументов': 'DocumentJournal', 'DocumentJournal': 'DocumentJournal',
    'Последовательность': 'Sequence', 'Sequence': 'Sequence',
    'КритерийОтбора': 'FilterCriterion', 'FilterCriterion': 'FilterCriterion',
}

# Виртуальные таблицы по виду регистра. Список закрытый: имя вне его - повод предупредить,
# потому что платформа такую таблицу не найдет.
VIRTUAL_TABLES = {
    'AccumulationRegister': {
        'Остатки', 'Balance', 'Обороты', 'Turnovers',
        'ОстаткиИОбороты', 'BalanceAndTurnovers',
    },
    'InformationRegister': {'СрезПоследних', 'SliceLast', 'СрезПервых', 'SliceFirst'},
    'AccountingRegister': {
        'Остатки', 'Balance', 'Обороты', 'Turnovers',
        'ОстаткиИОбороты', 'BalanceAndTurnovers',
        'ДвиженияССубконто', 'RecordsWithExtDimensions',
        'ОборотыДтКт', 'DrCrTurnovers',
    },
    'CalculationRegister': {
        'ДанныеГрафика', 'ScheduleData', 'БазаПоВидуРасчета', 'BaseCalculationType',
        'ФактическийПериодДействия', 'ActualActionPeriod', 'Перерасчет', 'Recalc',
    },
}

# Стандартные поля таблиц в тексте запроса. Внутренние имена английские, в запросе пишут русские -
# принимаются оба. Набор ОБЩИЙ, не по видам объектов: неверная привязка поля к виду дала бы
# ложное срабатывание, а лишнее имя в наборе - всего лишь пропуск.
STANDARD_QUERY_FIELDS = {
    'Ссылка', 'Ref', 'Код', 'Code', 'Наименование', 'Description',
    'ПометкаУдаления', 'DeletionMark', 'ЭтоГруппа', 'IsFolder', 'Родитель', 'Parent',
    'Владелец', 'Owner', 'Предопределенный', 'Predefined',
    'ИмяПредопределенныхДанных', 'PredefinedDataName',
    'Проведен', 'Posted', 'Дата', 'Date', 'Номер', 'Number',
    'Период', 'Period', 'Регистратор', 'Recorder', 'НомерСтроки', 'LineNumber',
    'Активность', 'Active', 'ВидДвижения', 'RecordType',
    'Счет', 'Account', 'Порядок', 'Order', 'Вид', 'Type', 'Забалансовый', 'OffBalance',
    'ТипЗначения', 'ValueType', 'ЭтотУзел', 'ThisNode',
    'НомерОтправленного', 'SentNo', 'НомерПринятого', 'ReceivedNo',
    'Стартован', 'Started', 'Завершен', 'Completed', 'ВедущаяЗадача', 'HeadTask',
    'Выполнена', 'Executed', 'ТочкаМаршрута', 'RoutePoint', 'БизнесПроцесс', 'BusinessProcess',
    'ПериодРегистрации', 'RegistrationPeriod', 'ВидРасчета', 'CalculationType',
    'Сторно', 'ReversingEntry',
    'ПериодДействия', 'ActionPeriod', 'ПериодДействияНачало', 'BegOfActionPeriod',
    'ПериодДействияКонец', 'EndOfActionPeriod',
    'БазовыйПериодНачало', 'BegOfBasePeriod', 'БазовыйПериодКонец', 'EndOfBasePeriod',
    'ПериодДействияБазовый', 'ActionPeriodIsBasic',
    'МоментВремени', 'PointInTime', 'Представление', 'Presentation',
    'ВерсияДанных', 'DataVersion', 'Значение', 'Value',
}

IDENT = r'[A-Za-z_А-Яа-яЁё][A-Za-z0-9_А-Яа-яЁё]*'
TABLE_RE = re.compile(r'\b(' + IDENT + r')\.(' + IDENT + r')(?:\.(' + IDENT + r'))?')
FROM_RE = re.compile(
    r'\b(?:ИЗ|FROM|СОЕДИНЕНИЕ|JOIN)\s+(' + IDENT + r')\.(' + IDENT + r')(?:\.(' + IDENT + r'))?'
    r'\s*(?:\([^()]*\))?(?:\s*(?:КАК|AS)\s+(' + IDENT + r'))?',
    re.IGNORECASE)
FIELD_RE = re.compile(r'\b(' + IDENT + r')\.(' + IDENT + r')\b')


def strip_noise(text):
    """Строковые литералы и комментарии выкидываются: внутри них Справочник.Чего-Нибудь - просто
    текст, а не имя таблицы."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    text = re.sub(r'"(?:[^"]|"")*"', ' ', text)
    return text


def virtual_table_fields(kind, vt_name, obj):
    """Поля виртуальной таблицы выводятся из ресурсов по суффиксам. Незнакомая таблица дает None -
    поля такого псевдонима не проверяются вовсе.

    У регистров бухгалтерии и расчета суффиксного правила НЕТ: там СуммаОстатокДт, СуммаОборотКт,
    развернутые остатки, корреспонденции. Выводить их этим способом нельзя - будут ложные
    срабатывания на существующие поля, поэтому такие таблицы объявляются непрозрачными."""
    if kind in ('AccountingRegister', 'CalculationRegister'):
        return None
    dims = list((obj.get('dimensions') or {}).keys())
    res = list((obj.get('resources') or {}).keys())
    attrs = list((obj.get('attributes') or {}).keys())
    name = vt_name
    fields = set(dims)
    if name in ('Остатки', 'Balance'):
        fields |= {r + 'Остаток' for r in res} | {r + 'Balance' for r in res}
    elif name in ('Обороты', 'Turnovers'):
        fields |= {r + 'Оборот' for r in res} | {r + 'Приход' for r in res} | {r + 'Расход' for r in res}
        fields |= {r + 'Turnover' for r in res} | {r + 'Receipt' for r in res} | {r + 'Expense' for r in res}
    elif name in ('ОстаткиИОбороты', 'BalanceAndTurnovers'):
        for r in res:
            fields |= {r + 'НачальныйОстаток', r + 'КонечныйОстаток', r + 'Приход', r + 'Расход', r + 'Оборот'}
            fields |= {r + 'OpeningBalance', r + 'ClosingBalance', r + 'Receipt', r + 'Expense', r + 'Turnover'}
    elif name in ('СрезПоследних', 'SliceLast', 'СрезПервых', 'SliceFirst'):
        fields |= set(res) | set(attrs)
    else:
        return None
    return fields


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description='Check 1C query text against a configuration index', allow_abbrev=False)
    parser.add_argument('-QueryPath', dest='QueryPath', default='')
    parser.add_argument('-Query', dest='Query', default='')
    parser.add_argument('-IndexPath', dest='IndexPath', required=True)
    parser.add_argument('-Detailed', action='store_true')
    parser.add_argument('-MaxErrors', dest='MaxErrors', type=int, default=30)
    args = parser.parse_args()

    if not args.QueryPath and not args.Query:
        sys.stderr.write('Either -QueryPath or -Query is required\n')
        return 1

    if args.QueryPath:
        query_path = args.QueryPath
        if not os.path.isabs(query_path):
            query_path = os.path.join(os.getcwd(), query_path)
        if not os.path.isfile(query_path):
            sys.stderr.write('Query file not found: ' + query_path + '\n')
            return 1
        with open(query_path, 'r', encoding='utf-8-sig', newline='') as fh:
            query_text = fh.read()
        source_label = os.path.basename(query_path)
    else:
        query_text = args.Query
        source_label = '(inline)'

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

    objects = index_data.get('objects') or {}
    lenient = index_data.get('kind') == 'extension'

    lines = ['=== Query check: %s ===' % source_label, '']
    warnings = []
    ok_notes = []

    def add_query_warn(msg):
        if len(warnings) < args.MaxErrors:
            warnings.append(msg)

    clean = strip_noise(query_text)

    # --- Таблицы в позиции ИЗ / СОЕДИНЕНИЕ: разбираются полностью, вместе с третьей частью ---
    aliases = {}
    alias_names = set()      # ВСЕ псевдонимы, даже неразрешенные
    table_spans = []         # куски текста, уже разобранные как имя таблицы
    seen_missing = set()
    for m in FROM_RE.finditer(clean):
        prefix, name, third, alias = m.group(1), m.group(2), m.group(3), m.group(4)
        if alias:
            alias_names.add(alias)
        kind = QUERY_TABLE_PREFIX_MAP.get(prefix)
        if kind is None:
            continue
        # Позиция самого имени таблицы: сюда не должен лезть проход по полям, иначе
        # "ИЗ Документ.Накладная КАК Документ" прочтется как поле Накладная у псевдонима Документ.
        name_start = clean.find(prefix, m.start())
        table_spans.append((name_start, m.end(1 if third is None else 3)))
        key = kind + '.' + name
        obj = objects.get(key)
        if obj is None:
            if key not in seen_missing:
                seen_missing.add(key)
                if lenient:
                    add_query_warn("Таблицы '%s.%s' нет в этой выгрузке - ожидается в основной "
                                   "конфигурации" % (prefix, name))
                else:
                    add_query_warn("Таблицы '%s.%s' нет в конфигурации" % (prefix, name))
            continue
        if third is None:
            fields = set((obj.get('attributes') or {}).keys())
            fields |= set(obj.get('standardAttributes') or [])
            fields |= set((obj.get('dimensions') or {}).keys())
            fields |= set((obj.get('resources') or {}).keys())
            fields |= set((obj.get('addressingAttributes') or {}).keys())
            fields |= set((obj.get('accountingFlags') or {}).keys())
            fields |= set((obj.get('tabularSections') or {}).keys())
            fields |= set((obj.get('standardTabularSections') or {}).keys())
            if alias:
                aliases[alias] = ('object', key, fields)
        elif kind in VIRTUAL_TABLES:
            if third not in VIRTUAL_TABLES[kind]:
                add_query_warn("Виртуальной таблицы '%s' нет у %s" % (third, key))
                continue
            vt_fields = virtual_table_fields(kind, third, obj)
            if vt_fields is None:
                if alias:
                    aliases[alias] = ('opaque', key + '.' + third, None)
            else:
                if alias:
                    aliases[alias] = ('virtual', key + '.' + third, vt_fields)
        else:
            ts = (obj.get('tabularSections') or {}).get(third)
            if ts is not None:
                fields = set((ts.get('attributes') or {}).keys())
                fields |= set(ts.get('standardAttributes') or [])
                if alias:
                    aliases[alias] = ('tabular', key + '.' + third, fields)
                continue
            std_ts = (obj.get('standardTabularSections') or {}).get(third)
            if std_ts is not None:
                fields = set(std_ts or [])
                fields |= set((obj.get('extDimensionAccountingFlags') or {}).keys())
                if alias:
                    aliases[alias] = ('tabular', key + '.' + third, fields)
                continue
            add_query_warn("У %s нет табличной части '%s'" % (key, third))

    # --- Все двухчастные имена метаданных где угодно: объект обязан существовать ---
    checked_objects = 0
    seen_objects = set()
    for m in TABLE_RE.finditer(clean):
        prefix, name = m.group(1), m.group(2)
        # Псевдоним запроса может называться как тип метаданных: "ИЗ Документ.Накладная КАК
        # Документ". Тогда Документ.Дата - это ПОЛЕ, а не таблица, и трогать его тут нельзя.
        if prefix in alias_names:
            continue
        kind = QUERY_TABLE_PREFIX_MAP.get(prefix)
        if kind is None:
            continue
        key = kind + '.' + name
        if key in seen_objects or key in seen_missing:
            continue
        seen_objects.add(key)
        checked_objects += 1
        if key not in objects:
            if lenient:
                add_query_warn("Таблицы '%s.%s' нет в этой выгрузке - ожидается в основной конфигурации"
                     % (prefix, name))
            else:
                add_query_warn("Таблицы '%s.%s' нет в конфигурации" % (prefix, name))

    # --- Поля по псевдонимам ---
    checked_fields = 0
    seen_fields = set()
    for m in FIELD_RE.finditer(clean):
        alias, field = m.group(1), m.group(2)
        binding = aliases.get(alias)
        if binding is None:
            continue
        if any(s <= m.start() < e for s, e in table_spans):
            continue
        kind_of_binding, table_label, fields = binding
        if fields is None:
            continue
        pair = (alias, field)
        if pair in seen_fields:
            continue
        seen_fields.add(pair)
        checked_fields += 1
        if field in fields or field in STANDARD_QUERY_FIELDS:
            continue
        if lenient:
            add_query_warn("У таблицы %s нет поля '%s' в этой выгрузке - ожидается в основной конфигурации"
                 % (table_label, field))
        else:
            add_query_warn("У таблицы %s нет поля '%s'" % (table_label, field))

    ok_notes.append('Таблиц проверено: %d' % checked_objects)
    ok_notes.append('Псевдонимов связано: %d' % len(aliases))
    ok_notes.append('Полей проверено: %d' % checked_fields)

    for w in warnings:
        lines.append('[WARN]  ' + w)
    if args.Detailed or not warnings:
        for n in ok_notes:
            lines.append('[OK]    ' + n)
    lines.append('')
    lines.append('=== Result: %d warnings ===' % len(warnings))
    sys.stdout.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
