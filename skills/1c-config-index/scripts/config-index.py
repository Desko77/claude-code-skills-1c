#!/usr/bin/env python3
# config-index v1.0 - Build a JSON index of a 1C configuration dump
# Source: https://github.com/Desko77/claude-code-skills-1c
"""Reads a Designer XML dump and writes one JSON index: what objects exist, their attributes,
tabular sections, register dimensions and resources, and the exported methods of common modules.
Other skills read the index instead of walking the dump themselves."""
import sys, os, argparse, json, re, time
from lxml import etree

# --- Type -> directory map (canonical, docs/1c-configuration-spec.md) ---

CHILD_TYPE_DIR_MAP = {
    'Language': 'Languages', 'Subsystem': 'Subsystems', 'StyleItem': 'StyleItems', 'Style': 'Styles',
    'CommonPicture': 'CommonPictures', 'SessionParameter': 'SessionParameters', 'Role': 'Roles',
    'CommonTemplate': 'CommonTemplates', 'FilterCriterion': 'FilterCriteria', 'CommonModule': 'CommonModules',
    'CommonAttribute': 'CommonAttributes', 'ExchangePlan': 'ExchangePlans', 'XDTOPackage': 'XDTOPackages',
    'WebService': 'WebServices', 'HTTPService': 'HTTPServices', 'WSReference': 'WSReferences',
    'EventSubscription': 'EventSubscriptions', 'ScheduledJob': 'ScheduledJobs',
    'SettingsStorage': 'SettingsStorages', 'FunctionalOption': 'FunctionalOptions',
    'FunctionalOptionsParameter': 'FunctionalOptionsParameters', 'DefinedType': 'DefinedTypes',
    'CommonCommand': 'CommonCommands', 'CommandGroup': 'CommandGroups', 'Constant': 'Constants',
    'CommonForm': 'CommonForms', 'Catalog': 'Catalogs', 'Document': 'Documents',
    'DocumentNumerator': 'DocumentNumerators', 'Sequence': 'Sequences',
    'DocumentJournal': 'DocumentJournals', 'Enum': 'Enums', 'Report': 'Reports',
    'DataProcessor': 'DataProcessors', 'InformationRegister': 'InformationRegisters',
    'AccumulationRegister': 'AccumulationRegisters',
    'ChartOfCharacteristicTypes': 'ChartsOfCharacteristicTypes',
    'ChartOfAccounts': 'ChartsOfAccounts', 'AccountingRegister': 'AccountingRegisters',
    'ChartOfCalculationTypes': 'ChartsOfCalculationTypes',
    'CalculationRegister': 'CalculationRegisters',
    'BusinessProcess': 'BusinessProcesses', 'Task': 'Tasks',
    'IntegrationService': 'IntegrationServices',
}

# Child elements of ChildObjects that carry a name and a type, grouped by the index bucket
# they fill. Everything not listed here is recorded by name only or ignored on purpose.
IDX_TYPED_BUCKETS = {
    'Attribute': 'attributes', 'Dimension': 'dimensions', 'Resource': 'resources',
    'AddressingAttribute': 'addressingAttributes', 'AccountingFlag': 'accountingFlags',
    'ExtDimensionAccountingFlag': 'extDimensionAccountingFlags',
}
IDX_NAMED_BUCKETS = {
    'Form': 'forms', 'Template': 'templates', 'Command': 'commands', 'Subsystem': 'subsystems',
    'EnumValue': 'enumValues', 'Recalculation': 'recalculations', 'Column': 'columns',
    'Operation': 'operations', 'URLTemplate': 'urlTemplates',
}
# Object properties worth carrying into the index: later checks read them, the rest is noise.
IDX_KEPT_PROPS = [
    'Hierarchical', 'HierarchyType', 'CodeLength', 'DescriptionLength', 'Periodicity',
    'RegisterType', 'WriteMode', 'InformationRegisterPeriodicity', 'ObjectBelonging',
    'Global', 'Server', 'ClientManagedApplication', 'ClientOrdinaryApplication',
    'ExternalConnection', 'ServerCall', 'Privileged', 'ReturnValuesReuse',
]
# Properties holding a list of <xr:Item> references to other objects.
IDX_REF_LIST_PROPS = ['Content', 'RegisterRecords', 'Owners', 'BasedOn', 'Registers']

BUCKET_ORDER_TYPED = ['dimensions', 'resources', 'addressingAttributes',
                      'accountingFlags', 'extDimensionAccountingFlags']
BUCKET_ORDER_NAMED = ['enumValues', 'forms', 'templates', 'commands', 'subsystems',
                      'recalculations', 'columns', 'operations', 'urlTemplates']

EXPORT_RE = re.compile(
    r'^[ \t]*(?:(?:Асинх|Async)[ \t]+)?(?:Процедура|Функция|Procedure|Function)[ \t]+'
    r'([A-Za-z_А-яЁё][A-Za-z0-9_А-яЁё]*)[ \t]*\(',
    re.IGNORECASE | re.MULTILINE)
# Экспорт может стоять на следующей строке - список параметров нередко переносят.
EXPORT_TAIL_RE = re.compile(r'^\s*(Экспорт|Export)\b', re.IGNORECASE)
# Литерал ИЛИ комментарий: что началось раньше, то и поглощает второе. Закрывающая кавычка
# необязательна - незакрытый литерал гасит остаток файла.
IDX_NOISE_RE = re.compile(r'"(?:[^"]|"")*"?|//[^\n]*')


# --- XML helpers (navigate by local name: the dump uses many prefixes) ---

def idx_local(el):
    if not isinstance(el.tag, str):
        return ''
    tag = el.tag
    return tag.split('}', 1)[1] if tag.startswith('{') else tag


def idx_child(node, local_name):
    if node is None:
        return None
    for c in node:
        if idx_local(c) == local_name:
            return c
    return None


def idx_children(node, local_name):
    found = []
    if node is None:
        return found
    for c in node:
        if idx_local(c) == local_name:
            found.append(c)
    return found


def idx_inner_text(node):
    if node is None:
        return ''
    return ''.join(node.itertext())


def idx_text(node, local_name):
    c = idx_child(node, local_name)
    if c is None:
        return ''
    return idx_inner_text(c)


def idx_types(props_node):
    """Type list of an attribute-like node. Namespace prefixes are dropped: only the local part
    carries meaning ("d5p1:CatalogRef.X" -> "CatalogRef.X", "xs:string" -> "string").
    The " + " form comes from DefinedType written by meta-compile as one string; the platform
    writes one element per type. Both are accepted."""
    types = []
    holder = idx_child(props_node, 'Type')
    if holder is None:
        holder = idx_child(props_node, 'ValueType')
    if holder is None:
        return types
    for c in holder:
        if idx_local(c) not in ('Type', 'TypeSet'):
            continue
        for part in idx_inner_text(c).split(' + '):
            t = part.strip()
            if not t:
                continue
            colon = t.find(':')
            if colon >= 0:
                t = t[colon + 1:]
            types.append(t)
    return types


def idx_standard_names(holder):
    """Стандартные реквизиты объект несет сам: <xr:StandardAttribute name="Description">. Читаем их
    из выгрузки, а не держим свою таблицу - таблица разошлась бы с платформой молча."""
    names = []
    if holder is None:
        return names
    for c in holder:
        if idx_local(c) != 'StandardAttribute':
            continue
        n = c.get('name') or ''
        if n:
            names.append(n)
    return names


def idx_ref_list(props_node, prop_name):
    refs = []
    holder = idx_child(props_node, prop_name)
    if holder is None:
        return refs
    for item in idx_children(holder, 'Item'):
        v = idx_inner_text(item).strip()
        if v:
            refs.append(v)
    return refs


def idx_blank_noise(text):
    """Гасит строковые литералы и комментарии ЗА ОДИН проход, сохраняя длину текста.

    Гасить их по очереди неверно в обе стороны, и обе ошибки встречаются в типовом коде:
    литералы первыми - нечетная кавычка в комментарии открывает мнимый литерал и съедает
    следующие за ним объявления методов; комментарии первыми - "TCP://" в литерале обрубит
    строку. Кто из двух начался раньше, решает чередование в самом образце: движок идет слева
    направо, и внутри уже начавшегося литерала двойной слеш ему не виден.

    Незакрытая кавычка гасит остаток файла - так же, как ее понимает платформа.
    Длина сохраняется, переводы строк внутри литерала тоже: вызывающий код ходит по тексту по
    позициям, а литерал в BSL занимает несколько строк.
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
    return IDX_NOISE_RE.sub(blank, text)


def idx_exports(text):
    """Exported methods of a module. Comments are blanked together with string literals: a
    commented-out procedure would otherwise become a phantom export - and a phantom export only
    makes a later check MISS a call, never invent one."""
    names = []
    src = idx_blank_noise(text) + '\n'
    for m in EXPORT_RE.finditer(src):
        # Walk past the parameter list counting nesting: default values contain parens too.
        i = m.end()
        depth = 1
        while i < len(src) and depth > 0:
            if src[i] == '(':
                depth += 1
            elif src[i] == ')':
                depth -= 1
            i += 1
        if depth != 0:
            continue
        if EXPORT_TAIL_RE.match(src[i:i + 40]):
            names.append(m.group(1))
    return names


# --- One metadata object -> index entry ---

def idx_read_object(path, kind, types_sink):
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    tree = etree.parse(path, parser)
    obj_node = idx_child(tree.getroot(), kind)
    if obj_node is None:
        return None

    internal = idx_child(obj_node, 'InternalInfo')
    for gt in idx_children(internal, 'GeneratedType'):
        gt_name = gt.get('name') or ''
        if gt_name:
            types_sink.append(gt_name)

    props = idx_child(obj_node, 'Properties')
    entry = {'kind': kind, 'name': idx_text(props, 'Name')}

    typed = {b: {} for b in IDX_TYPED_BUCKETS.values()}
    named = {b: [] for b in IDX_NAMED_BUCKETS.values()}
    tabular = {}

    children = idx_child(obj_node, 'ChildObjects')
    if children is not None:
        for c in children:
            local = idx_local(c)
            if not local:
                continue
            c_props = idx_child(c, 'Properties')
            c_name = idx_text(c_props, 'Name')
            # Форма и макет записаны в ChildObjects просто именем: <Form>ФормаЭлемента</Form>,
            # без Properties. Команда там же, но полноценным объектом с Properties/Name.
            if not c_name and c_props is None:
                c_name = idx_inner_text(c).strip()
            if not c_name:
                continue
            if local in IDX_TYPED_BUCKETS:
                typed[IDX_TYPED_BUCKETS[local]][c_name] = idx_types(c_props)
            elif local in IDX_NAMED_BUCKETS:
                named[IDX_NAMED_BUCKETS[local]].append(c_name)
            elif local == 'TabularSection':
                ts_attrs = {}
                ts_children = idx_child(c, 'ChildObjects')
                for a in idx_children(ts_children, 'Attribute'):
                    a_props = idx_child(a, 'Properties')
                    a_name = idx_text(a_props, 'Name')
                    if a_name:
                        ts_attrs[a_name] = idx_types(a_props)
                ts_entry = {'attributes': ts_attrs}
                ts_std = idx_standard_names(idx_child(c_props, 'StandardAttributes'))
                if ts_std:
                    ts_entry['standardAttributes'] = ts_std
                tabular[c_name] = ts_entry

    # Only non-empty buckets are written: an index of thousands of objects should not carry
    # thousands of empty braces.
    if typed['attributes']:
        entry['attributes'] = typed['attributes']
    std = idx_standard_names(idx_child(props, 'StandardAttributes'))
    if std:
        entry['standardAttributes'] = std
    if tabular:
        entry['tabularSections'] = tabular
    std_tabular = {}
    for sts in idx_children(idx_child(props, 'StandardTabularSections'), 'StandardTabularSection'):
        sts_name = sts.get('name') or ''
        if not sts_name:
            continue
        std_tabular[sts_name] = idx_standard_names(idx_child(sts, 'StandardAttributes'))
    if std_tabular:
        entry['standardTabularSections'] = std_tabular
    for b in BUCKET_ORDER_TYPED:
        if typed[b]:
            entry[b] = typed[b]
    for b in BUCKET_ORDER_NAMED:
        if named[b]:
            entry[b] = named[b]

    value_types = idx_types(props)
    if value_types:
        entry['valueType'] = value_types

    flags = {}
    for p in IDX_KEPT_PROPS:
        v = idx_child(props, p)
        if v is not None and idx_inner_text(v) != '':
            flags[p] = idx_inner_text(v)
    if flags:
        entry['props'] = flags

    refs = {}
    for p in IDX_REF_LIST_PROPS:
        lst = idx_ref_list(props, p)
        if lst:
            refs[p] = lst
    if refs:
        entry['refs'] = refs

    return entry


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description='Build a JSON index of a 1C configuration dump', allow_abbrev=False
    )
    parser.add_argument('-ConfigPath', dest='ConfigPath', required=True)
    parser.add_argument('-OutFile', dest='OutFile', default='')
    parser.add_argument('-Detailed', action='store_true')
    args = parser.parse_args()

    # --- Resolve the configuration root ---
    config_path = args.ConfigPath
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if os.path.isfile(config_path):
        config_path = os.path.dirname(config_path)
    if not os.path.isdir(config_path):
        sys.stderr.write('Configuration directory not found: ' + config_path + '\n')
        return 1
    config_root = os.path.abspath(config_path)
    config_xml = os.path.join(config_root, 'Configuration.xml')
    if not os.path.isfile(config_xml):
        sys.stderr.write('Configuration.xml not found in: ' + config_root + '\n')
        return 1

    started = time.time()

    # --- Configuration.xml: identity and the declared object list ---
    cfg_tree = etree.parse(config_xml, etree.XMLParser(remove_blank_text=False, recover=False))
    cfg_node = idx_child(cfg_tree.getroot(), 'Configuration')
    if cfg_node is None:
        sys.stderr.write('Configuration.xml has no <Configuration> element\n')
        return 1
    cfg_props = idx_child(cfg_node, 'Properties')
    ext_purpose = idx_text(cfg_props, 'ConfigurationExtensionPurpose')

    index = {}
    index['format'] = 1
    index['kind'] = 'extension' if ext_purpose else 'configuration'
    index['name'] = idx_text(cfg_props, 'Name')
    index['version'] = idx_text(cfg_props, 'Version')
    if ext_purpose:
        index['extensionPurpose'] = ext_purpose
        index['namePrefix'] = idx_text(cfg_props, 'NamePrefix')

    declared = {}
    cfg_children = idx_child(cfg_node, 'ChildObjects')
    if cfg_children is not None:
        for c in cfg_children:
            local = idx_local(c)
            if not local:
                continue
            n = idx_inner_text(c).strip()
            if not n:
                continue
            declared.setdefault(local, []).append(n)
    index['declared'] = declared

    # --- Walk the declared objects ---
    objects = {}
    all_types = []
    missing = []
    unknown_kinds = []
    common_modules = {}
    state = {'files': 0}

    # Subsystems nest: Subsystems/Родитель/Subsystems/Ребенок.xml, и ребенок объявлен в
    # ChildObjects родителя. Ключ несет весь путь, потому что так подсистема адресуется
    # во всей конфигурации.
    def add_subsystems(directory, prefix, names):
        for sub in names:
            file_path = os.path.join(directory, sub + '.xml')
            key = prefix + 'Subsystem.' + sub
            if not os.path.isfile(file_path):
                missing.append(key)
                continue
            entry = idx_read_object(file_path, 'Subsystem', all_types)
            state['files'] += 1
            if entry is None:
                continue
            objects[key] = entry
            nested = entry.get('subsystems')
            if nested:
                add_subsystems(os.path.join(directory, sub, 'Subsystems'), key + '.', nested)

    for kind in declared:
        if kind == 'Language':
            continue
        if kind not in CHILD_TYPE_DIR_MAP:
            unknown_kinds.append(kind)
            continue
        directory = os.path.join(config_root, CHILD_TYPE_DIR_MAP[kind])
        if kind == 'Subsystem':
            add_subsystems(directory, '', declared[kind])
            continue
        for name in declared[kind]:
            file_path = os.path.join(directory, name + '.xml')
            key = kind + '.' + name
            if not os.path.isfile(file_path):
                missing.append(key)
                continue
            entry = idx_read_object(file_path, kind, all_types)
            state['files'] += 1
            if entry is None:
                continue
            objects[key] = entry
            if kind == 'CommonModule':
                mod_file = os.path.join(directory, name, 'Ext', 'Module.bsl')
                mod = {}
                if os.path.isfile(mod_file):
                    with open(mod_file, 'r', encoding='utf-8-sig', newline='') as fh:
                        mod['exported'] = idx_exports(fh.read())
                else:
                    mod['exported'] = []
                    mod['moduleMissing'] = True
                common_modules[name] = mod

    index['objects'] = objects
    index['types'] = all_types
    if common_modules:
        index['commonModules'] = common_modules
    if missing:
        index['missing'] = missing
    if unknown_kinds:
        index['unknownKinds'] = unknown_kinds

    json_text = json.dumps(index, ensure_ascii=False, indent=2) + '\n'

    elapsed = int((time.time() - started) * 1000)
    lines = []
    lines.append('[OK]    Индекс собран: объектов %d, типов %d, файлов прочитано %d'
                 % (len(objects), len(all_types), state['files']))
    if common_modules:
        lines.append('[OK]    Общих модулей: %d' % len(common_modules))
    if missing:
        lines.append('[WARN]  Объявлено в Configuration.xml, но файла нет: %d' % len(missing))
    if unknown_kinds:
        lines.append('[WARN]  Неизвестные типы в ChildObjects: ' + ', '.join(unknown_kinds))
    if args.Detailed:
        for m in missing:
            lines.append('        нет файла: ' + m)
        lines.append('[INFO]  Время сборки, мс: %d' % elapsed)

    if args.OutFile:
        out_file = args.OutFile
        if not os.path.isabs(out_file):
            out_file = os.path.join(os.getcwd(), out_file)
        out_dir = os.path.dirname(out_file)
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(out_file, 'w', encoding='utf-8', newline='') as fh:
            fh.write(json_text)
        lines.append('[INFO]  Записан: ' + out_file)
        sys.stdout.write('\n'.join(lines) + '\n')
    else:
        sys.stdout.write(json_text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
