# Экранирование текста для XML. Тело совпадает с role-compile: семейство общее.
def esc_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# Операции правки. Неизвестное имя - отказ.
KNOWN_OPS = {
    'add-rights', 'set-rights', 'remove-rights', 'deny-rights',
    'set-rls', 'remove-rls',
    'add-template', 'set-template', 'remove-template',
    'modify-property',
}

# Признаки роли, которые лежат в Rights.xml, а не в файле метаданных.
FLAG_PROPS = {
    'setForNewObjects',
    'setForAttributesByDefault',
    'independentRightsOfChildObjects',
}

PROP_MAP = {
    'synonym': 'synonym',
    'comment': 'comment',
    'setfornewobjects': 'setForNewObjects',
    'setforattributesbydefault': 'setForAttributesByDefault',
    'independentrightsofchildobjects': 'independentRightsOfChildObjects',
    'синоним': 'synonym',
    'комментарий': 'comment',
}


def die(message):
    """Отказ до записи: сообщение в stderr и код 1."""
    print(f'Ошибка: {message}', file=sys.stderr)
    sys.exit(1)


def flush_errors():
    """Печатает накопленные ошибки ввода и завершает процесс, если они есть."""
    if not INPUT_ERRORS:
        return
    for message in INPUT_ERRORS:
        print(f'Ошибка: {message}', file=sys.stderr)
    sys.exit(1)


def fold_op(item):
    """Ключи операции без учета регистра. Вложенный словарь прав не трогает."""
    if not isinstance(item, dict):
        return None
    out = {}
    for key, value in item.items():
        out[key.lower() if isinstance(key, str) else key] = value
    return out


def load_operations(path):
    """Читает JSON правки: массив, одна операция или объект с полем operations."""
    if not os.path.isfile(path):
        die(f'файл описания не найден: {path}')
    with open(path, 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        folded = fold_op(data)
        if 'operations' in folded:
            data = folded['operations']
        else:
            data = [folded]
    if not isinstance(data, list):
        add_input_error('описание правки: ожидался объект или массив операций')
        return []
    ops = []
    for item in data:
        folded = fold_op(item)
        if folded is None:
            add_input_error('операция: ожидался объект')
            continue
        ops.append(folded)
    return ops


def op_name(op):
    """Каноническое имя операции."""
    raw = op.get('operation') or op.get('op') or ''
    return str(raw).strip().lower()


def op_object_name(op):
    """Имя объекта метаданных в каноническом написании."""
    raw = op.get('object') or ''
    if not raw and op_name(op) not in ('add-template', 'set-template', 'remove-template', 'modify-property'):
        raw = op.get('name') or ''
    raw = str(raw).strip() if raw else ''
    return translate_object_name(raw) if raw else ''


def op_rights_spec(op):
    """Спецификация прав: поле rights, иначе value у операций над правами."""
    if 'rights' in op and op['rights'] is not None:
        return op['rights']
    if op_name(op) in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights'):
        if 'value' in op and op['value'] is not None:
            return op['value']
    return None


def op_right_name(op):
    """Имя одного права для операций RLS."""
    raw = op.get('right') or ''
    if not raw and isinstance(op.get('rights'), str):
        raw = op['rights']
    raw = str(raw).strip() if raw else ''
    return translate_right_name(raw) if raw else ''


def op_template_name(op):
    """Имя шаблона ограничения."""
    raw = op.get('template') or op.get('name') or ''
    return str(raw).strip()


def op_condition(op):
    """Текст условия RLS или шаблона. None - поле не задано."""
    if 'condition' in op and op['condition'] is not None:
        return str(op['condition'])
    if op_name(op) in ('set-rls', 'add-template', 'set-template') and 'value' in op and op['value'] is not None:
        return str(op['value'])
    return None


def op_property(op):
    """Имя свойства роли и новое значение. Неизвестное имя дает (None, value)."""
    prop = op.get('property') or ''
    value = op.get('value') if 'value' in op else None
    if not prop and isinstance(value, str) and '=' in value:
        prop, value = value.split('=', 1)
    if not prop:
        prop = op.get('name') or ''
    key = PROP_MAP.get(str(prop).strip().lower()) if prop else None
    return key, prop, value


def truthy(value):
    """Истина для значения права: bool, число и строки true/1/yes."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ('true', '1', 'yes')


def xml_bool(value):
    """true или false для признака роли. None - значение не разобрано."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    text = str(value).strip().lower()
    if text in ('true', '1'):
        return 'true'
    if text in ('false', '0'):
        return 'false'
    return None


def right_pairs(spec):
    """Пары (имя права, 'true'|'false') из строки, списка или словаря."""
    if isinstance(spec, str):
        parts = [part.strip() for part in spec.split(',') if part.strip()]
        return [(translate_right_name(part), 'true') for part in parts]
    if isinstance(spec, list):
        pairs = []
        for part in spec:
            text = str(part).strip()
            if text:
                pairs.append((translate_right_name(text), 'true'))
        return pairs
    if isinstance(spec, dict):
        pairs = []
        for key, value in spec.items():
            pairs.append((translate_right_name(str(key)), 'true' if truthy(value) else 'false'))
        return pairs
    add_input_error('права: ожидалась строка, список или словарь')
    return []


def validate_ops(ops):
    """Проверяет операции до чтения роли. Ошибки копятся в INPUT_ERRORS."""
    if not ops:
        add_input_error('нет операций')
        return
    seen = set()
    for op in ops:
        name = op_name(op)
        if name not in KNOWN_OPS:
            add_input_error(f"неизвестная операция '{name}'")
            continue
        needs_object = name in (
            'add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls',
        )
        obj = op_object_name(op) if needs_object else ''
        if needs_object and not obj:
            add_input_error(f'{name}: не задан объект')
            continue
        check_type = name in ('add-rights', 'set-rights', 'deny-rights', 'set-rls')
        if check_type and obj not in seen:
            test_object_type_known(obj)
            test_nested_kind(obj)
            seen.add(obj)
        if name in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights'):
            spec = op_rights_spec(op)
            if spec is None or spec == '' or spec == [] or spec == {}:
                if name != 'set-rights' or spec is None:
                    add_input_error(f'{name}: не заданы права')
                elif spec is None:
                    add_input_error(f'{name}: не заданы права')
                continue
            if name == 'set-rights' and spec in ('', [], {}):
                continue
            pairs = right_pairs(spec)
            if name != 'remove-rights':
                for right_name, _value in pairs:
                    validate_right_name(obj, right_name)
            if name in ('add-rights', 'deny-rights', 'remove-rights') and not pairs:
                add_input_error(f'{name}: не заданы права')
        elif name == 'set-rls':
            right_name = op_right_name(op)
            if not right_name:
                add_input_error('set-rls: не задано право')
            else:
                validate_right_name(obj, right_name)
            if op_condition(op) is None:
                add_input_error('set-rls: не задано условие')
        elif name == 'remove-rls':
            if not op_right_name(op):
                add_input_error('remove-rls: не задано право')
        elif name in ('add-template', 'set-template'):
            if not op_template_name(op):
                add_input_error(f'{name}: не задано имя шаблона')
            if op_condition(op) is None:
                add_input_error(f'{name}: не задано условие')
        elif name == 'remove-template':
            if not op_template_name(op):
                add_input_error('remove-template: не задано имя шаблона')
        elif name == 'modify-property':
            key, raw, value = op_property(op)
            if not key:
                add_input_error(f"неизвестное свойство '{raw}'")
            elif value is None:
                add_input_error(f'{key}: не задано значение')
            elif key in FLAG_PROPS and xml_bool(value) is None:
                add_input_error(f'{key}: ожидалось true или false')


def read_text(path):
    """Текст файла, признак BOM и признак CRLF. Переводы строк внутри - LF."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    body = raw[3:] if bom else raw
    text = body.decode('utf-8')
    crlf = '\r\n' in text
    return text.replace('\r\n', '\n'), bom, crlf


def write_text(path, text, bom, crlf):
    """Пишет текст в исходной кодировке файла: UTF-8, BOM и концы строк как были."""
    if crlf:
        text = text.replace('\n', '\r\n')
    data = text.encode('utf-8')
    if bom:
        data = b'\xef\xbb\xbf' + data
    with open(path, 'wb') as handle:
        handle.write(data)


def resolve_role_paths(path):
    """Пара путей: файл метаданных роли и Ext/Rights.xml."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        if os.path.basename(path).lower() == 'ext':
            return resolve_role_paths(os.path.join(path, 'Rights.xml'))
        name = os.path.basename(path)
        meta = os.path.join(os.path.dirname(path), name + '.xml')
        rights = os.path.join(path, 'Ext', 'Rights.xml')
        return meta, rights
    if os.path.basename(path).lower() == 'rights.xml':
        role_dir = os.path.dirname(os.path.dirname(path))
        name = os.path.basename(role_dir)
        meta = os.path.join(os.path.dirname(role_dir), name + '.xml')
        return meta, path
    name = os.path.splitext(os.path.basename(path))[0]
    meta = path if path.lower().endswith('.xml') else path + '.xml'
    rights = os.path.join(os.path.dirname(meta), name, 'Ext', 'Rights.xml')
    return meta, rights


def indent_unit(text):
    """Единица отступа файла: пробелы или таб перед первым вложенным тегом."""
    match = re.search(r'\n([ \t]+)<(?:object|setForNewObjects|restrictionTemplate)>', text)
    return match.group(1) if match else '\t'


def find_objects(text):
    """Блоки object: имя, права и границы в тексте с переводами LF."""
    found = []
    for match in re.finditer(r'[ \t]*<object>.*?</object>', text, re.DOTALL):
        block = match.group(0)
        name_match = re.search(r'<name>(.*?)</name>', block, re.DOTALL)
        rights = []
        for right_match in re.finditer(
            r'<right>\s*<name>(.*?)</name>\s*<value>(.*?)</value>(.*?)</right>',
            block,
            re.DOTALL,
        ):
            condition = None
            cond_match = re.search(r'<condition>(.*?)</condition>', right_match.group(3), re.DOTALL)
            if cond_match:
                condition = html.unescape(cond_match.group(1))
            rights.append({
                'Name': html.unescape(right_match.group(1).strip()),
                'Value': right_match.group(2).strip(),
                'Condition': condition,
            })
        found.append({
            'start': match.start(),
            'end': match.end(),
            'name': html.unescape(name_match.group(1).strip()) if name_match else '',
            'rights': rights,
        })
    return found


def render_object(name, rights, unit):
    """Блок object в оформлении выгрузки: таб или тот же отступ, что у файла."""
    lines = [f'{unit}<object>', f'{unit * 2}<name>{esc_xml(name)}</name>']
    for right in rights:
        lines.append(f'{unit * 2}<right>')
        lines.append(f'{unit * 3}<name>{esc_xml(right["Name"])}</name>')
        lines.append(f'{unit * 3}<value>{right["Value"]}</value>')
        if right.get('Condition'):
            lines.append(f'{unit * 3}<restrictionByCondition>')
            lines.append(f'{unit * 4}<condition>{esc_xml(right["Condition"])}</condition>')
            lines.append(f'{unit * 3}</restrictionByCondition>')
        lines.append(f'{unit * 2}</right>')
    lines.append(f'{unit}</object>')
    return '\n'.join(lines)


def close_object(obj_name, rights):
    """Замыкание включенных прав объекта и канонический порядок."""
    mapping = {}
    order = []
    for right in rights:
        if right['Name'] not in mapping:
            order.append(right['Name'])
        mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
    return finish_rights(obj_name, mapping, order)


def splice_span(text, start, end, block):
    """Подменяет отрезок текста. block None удаляет отрезок вместе с переводом перед ним."""
    if block is None:
        if start > 0 and text[start - 1] == '\n':
            start -= 1
        return text[:start] + text[end:]
    return text[:start] + block + text[end:]


def insert_before_close(text, block, tag):
    """Вставляет блок перед первым тегом tag либо перед закрытием Rights."""
    match = re.search(r'\n[ \t]*<' + tag + r'>', text)
    if match is None and tag != '/Rights':
        match = re.search(r'\n[ \t]*</Rights>', text)
    if match is None:
        die('Rights.xml: нет закрывающего тега Rights')
    return text[:match.start()] + '\n' + block + text[match.start():]


def apply_rights_op(text, op):
    """Одна операция над правами или RLS. Чужие объекты не переписываются."""
    name = op_name(op)
    obj_name = op_object_name(op)
    unit = indent_unit(text)
    objects = find_objects(text)
    index = next((i for i, obj in enumerate(objects) if obj['name'] == obj_name), None)
    current = list(objects[index]['rights']) if index is not None else []

    if name == 'remove-rights':
        if index is None:
            return text
        drop = {pair[0] for pair in right_pairs(op_rights_spec(op))}
        kept = [right for right in current if right['Name'] not in drop]
        new_rights = close_object(obj_name, kept)
        for removed in drop:
            if any(right['Name'] == removed and right['Value'] == 'true' for right in new_rights):
                print(
                    f"WARNING: {obj_name}: право '{removed}' снято, но замыкание снова включает его",
                    file=sys.stderr,
                )
        block = render_object(obj_name, new_rights, unit) if new_rights else None
        return splice_span(text, objects[index]['start'], objects[index]['end'], block)

    if name == 'remove-rls':
        if index is None:
            return text
        right_name = op_right_name(op)
        changed = False
        new_rights = []
        for right in current:
            item = dict(right)
            if item['Name'] == right_name and item.get('Condition'):
                item['Condition'] = None
                changed = True
            new_rights.append(item)
        if not changed:
            return text
        block = render_object(obj_name, new_rights, unit)
        return splice_span(text, objects[index]['start'], objects[index]['end'], block)

    if name == 'set-rights':
        pairs = right_pairs(op_rights_spec(op))
        old = {right['Name']: right for right in current}
        mapping = {}
        order = []
        for right_name, value in pairs:
            if right_name not in mapping:
                order.append(right_name)
                cond = old[right_name]['Condition'] if right_name in old else None
                mapping[right_name] = {'Value': value, 'Condition': cond}
        new_rights = finish_rights(obj_name, mapping, order)
    elif name == 'set-rls':
        mapping = {}
        order = []
        for right in current:
            order.append(right['Name'])
            mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
        right_name = op_right_name(op)
        condition = op_condition(op)
        if right_name in mapping:
            mapping[right_name]['Value'] = 'true'
            mapping[right_name]['Condition'] = condition
        else:
            order.append(right_name)
            mapping[right_name] = {'Value': 'true', 'Condition': condition}
        new_rights = finish_rights(obj_name, mapping, order)
    else:
        pairs = right_pairs(op_rights_spec(op))
        mapping = {}
        order = []
        for right in current:
            order.append(right['Name'])
            mapping[right['Name']] = {'Value': right['Value'], 'Condition': right.get('Condition')}
        for right_name, value in pairs:
            if right_name in mapping:
                mapping[right_name]['Value'] = value
            else:
                order.append(right_name)
                mapping[right_name] = {'Value': value, 'Condition': None}
        new_rights = finish_rights(obj_name, mapping, order)

    block = render_object(obj_name, new_rights, unit) if new_rights else None
    if index is None:
        if block is None:
            return text
        if objects:
            end = objects[-1]['end']
            return text[:end] + '\n' + block + text[end:]
        return insert_before_close(text, block, 'restrictionTemplate')
    return splice_span(text, objects[index]['start'], objects[index]['end'], block)


def find_templates(text):
    """Шаблоны ограничения: имя, условие и границы блока."""
    found = []
    pattern = re.compile(
        r'[ \t]*<restrictionTemplate>\s*<name>(.*?)</name>\s*<condition>(.*?)</condition>\s*</restrictionTemplate>',
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        found.append({
            'start': match.start(),
            'end': match.end(),
            'name': html.unescape(match.group(1).strip()),
            'condition': html.unescape(match.group(2)),
        })
    return found


def render_template(name, condition, unit):
    """Блок restrictionTemplate в оформлении выгрузки."""
    return '\n'.join([
        f'{unit}<restrictionTemplate>',
        f'{unit * 2}<name>{esc_xml(name)}</name>',
        f'{unit * 2}<condition>{esc_xml(condition)}</condition>',
        f'{unit}</restrictionTemplate>',
    ])


def apply_template_op(text, op):
    """Добавление, замена или снятие шаблона. Совпадающий add ничего не меняет."""
    name = op_name(op)
    template = op_template_name(op)
    unit = indent_unit(text)
    found = find_templates(text)
    index = next((i for i, item in enumerate(found) if item['name'] == template), None)
    if name == 'remove-template':
        if index is None:
            return text
        return splice_span(text, found[index]['start'], found[index]['end'], None)
    condition = op_condition(op)
    if index is not None and found[index]['condition'] == condition:
        return text
    if name == 'add-template' and index is not None:
        add_input_error(f"шаблон '{template}' уже есть, для замены используйте set-template")
        return text
    block = render_template(template, condition, unit)
    if index is None:
        return insert_before_close(text, block, '/Rights')
    return splice_span(text, found[index]['start'], found[index]['end'], block)


def replace_synonym(text, value):
    """Меняет русский синоним, не трогая uuid и остальные языки."""
    pattern = re.compile(
        r'(<Synonym\b[^>]*>.*?<v8:lang>\s*ru\s*</v8:lang>\s*<v8:content>)(.*?)(</v8:content>)',
        re.DOTALL,
    )
    if not pattern.search(text):
        return None
    return pattern.sub(lambda match: match.group(1) + esc_xml(str(value)) + match.group(3), text, count=1)


def replace_comment(text, value):
    """Меняет комментарий роли. Пустая строка записывается пустым тегом."""
    escaped = esc_xml(str(value))
    if re.search(r'<Comment\s*/>', text):
        if escaped == '':
            return text
        return re.sub(r'<Comment\s*/>', f'<Comment>{escaped}</Comment>', text, count=1)
    if re.search(r'<Comment\b[^>]*>.*?</Comment>', text, re.DOTALL):
        if escaped == '':
            return re.sub(r'<Comment\b[^>]*>.*?</Comment>', '<Comment/>', text, count=1, flags=re.DOTALL)
        return re.sub(
            r'(<Comment\b[^>]*>)(.*?)(</Comment>)',
            lambda match: match.group(1) + escaped + match.group(3),
            text,
            count=1,
            flags=re.DOTALL,
        )
    return None


def replace_flag(text, tag, value):
    """Меняет текст признака роли в Rights.xml."""
    pattern = re.compile(rf'(<{tag}>)(\s*)(true|false)(\s*)(</{tag}>)')
    if not pattern.search(text):
        return None
    return pattern.sub(rf'\g<1>\g<2>{value}\g<4>\g<5>', text, count=1)


def apply_property_op(rights, meta, op):
    """Меняет синоним, комментарий или признак. Возвращает пару текстов."""
    key, _raw, value = op_property(op)
    if key in ('synonym', 'comment'):
        if key == 'synonym':
            updated = replace_synonym(meta, value)
        else:
            updated = replace_comment(meta, '' if value is None else value)
        if updated is None:
            add_input_error(f'{key}: в файле роли нет этого свойства')
            return rights, meta
        return rights, updated
    updated = replace_flag(rights, key, xml_bool(value))
    if updated is None:
        add_input_error(f'{key}: в Rights.xml нет этого признака')
        return rights, meta
    return updated, meta


def apply_ops(rights, meta, ops):
    """Применяет операции по порядку. При ошибке тексты не считаются годными к записи."""
    for op in ops:
        name = op_name(op)
        if name in ('add-rights', 'set-rights', 'remove-rights', 'deny-rights', 'set-rls', 'remove-rls'):
            rights = apply_rights_op(rights, op)
        elif name in ('add-template', 'set-template', 'remove-template'):
            rights = apply_template_op(rights, op)
        elif name == 'modify-property':
            rights, meta = apply_property_op(rights, meta, op)
        if INPUT_ERRORS:
            break
    return rights, meta


def role_validate_script():
    """Путь к role-validate.py соседнего навыка."""
    base = os.path.dirname(os.path.abspath(__file__))
    for folder in ('1c-role-validate', 'role-validate'):
        candidate = os.path.normpath(os.path.join(base, '..', '..', folder, 'scripts', 'role-validate.py'))
        if os.path.isfile(candidate):
            return candidate
    return ''


def role_label(meta_text, meta_path):
    """Имя роли из метаданных, иначе из имени файла."""
    match = re.search(r'<Name>(.*?)</Name>', meta_text)
    if match:
        return match.group(1).strip()
    return os.path.splitext(os.path.basename(meta_path))[0]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Точечная правка существующей роли 1С', allow_abbrev=False)
    parser.add_argument('-RolePath', required=True)
    parser.add_argument('-DefinitionFile', default=None)
    parser.add_argument('-Operation', default=None)
    parser.add_argument('-Object', default=None)
    parser.add_argument('-Rights', default=None)
    parser.add_argument('-Right', default=None)
    parser.add_argument('-Template', default=None)
    parser.add_argument('-Condition', default=None)
    parser.add_argument('-Property', default=None)
    parser.add_argument('-Value', default=None)
    parser.add_argument('-NoValidate', action='store_true')
    args = parser.parse_args()

    if args.DefinitionFile and args.Operation:
        die('-DefinitionFile и -Operation вместе не задают')
    if not args.DefinitionFile and not args.Operation:
        die('укажите -DefinitionFile или -Operation')

    if args.DefinitionFile:
        ops = load_operations(args.DefinitionFile)
    else:
        ops = [fold_op({
            'operation': args.Operation,
            'object': args.Object,
            'rights': args.Rights,
            'right': args.Right,
            'template': args.Template,
            'condition': args.Condition,
            'property': args.Property,
            'value': args.Value,
        })]
    validate_ops(ops)
    flush_errors()

    meta_path, rights_path = resolve_role_paths(args.RolePath)
    if not os.path.isfile(meta_path):
        die(f'файл роли не найден: {meta_path}')
    if not os.path.isfile(rights_path):
        die(f'файл прав не найден: {rights_path}')
    assert_edit_allowed(meta_path, 'editable')

    rights, rights_bom, rights_crlf = read_text(rights_path)
    meta, meta_bom, meta_crlf = read_text(meta_path)
    new_rights, new_meta = apply_ops(rights, meta, ops)
    flush_errors()

    if new_rights != rights:
        write_text(rights_path, new_rights, rights_bom, rights_crlf)
    if new_meta != meta:
        write_text(meta_path, new_meta, meta_bom, meta_crlf)

    label = role_label(new_meta, meta_path)
    print(f'role-edit: {label}, операций {len(ops)}')

    if not args.NoValidate:
        script = role_validate_script()
        if script:
            print('--- role-validate ---')
            subprocess.run([sys.executable, script, '-RightsPath', rights_path])
