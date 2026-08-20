#!/usr/bin/env python3
# bsl-validate v1.0 - Check BSL module calls against a configuration index
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Reads BSL modules and the index built by 1c-config-index, then reports calls to common-module
methods that do not exist or are not exported. This is NOT a BSL compiler: types, syntax and
overload resolution are out of reach without the platform."""
import sys, os, argparse, json, re

IDENT = r'[A-Za-z_А-Яа-яЁё][A-Za-z0-9_А-Яа-яЁё]*'
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description='Check BSL module calls against a configuration index', allow_abbrev=False)
    parser.add_argument('-ModulePath', dest='ModulePath', required=True)
    parser.add_argument('-IndexPath', dest='IndexPath', required=True)
    parser.add_argument('-UnknownCalls', action='store_true')
    parser.add_argument('-Detailed', action='store_true')
    parser.add_argument('-MaxErrors', dest='MaxErrors', type=int, default=30)
    args = parser.parse_args()

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
