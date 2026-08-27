#!/usr/bin/env python3
# skd-decompile v1.0 - Decompile 1C DCS XML (DataCompositionSchema) to JSON DSL draft
# Source: https://github.com/Desko77/claude-code-skills-1c
# Mirror of skd-decompile.ps1 (same algorithm, independent implementation).
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

URI_CFG = 'http://v8.1c.ru/8.1/data/enterprise/current-config'
URI_STYLE = 'http://v8.1c.ru/8.1/data/ui/style'
URI_WEB = 'http://v8.1c.ru/8.1/data/ui/colors/web'
URI_WIN = 'http://v8.1c.ru/8.1/data/ui/colors/windows'
XSI_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'
XSI_NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'

COMPARISON_OPS = {
    'Equal': '=', 'NotEqual': '<>', 'Greater': '>', 'GreaterOrEqual': '>=',
    'Less': '<', 'LessOrEqual': '<=', 'InList': 'in', 'NotInList': 'notIn',
    'InHierarchy': 'inHierarchy', 'InListByHierarchy': 'inListByHierarchy',
    'Contains': 'contains', 'NotContains': 'notContains',
    'BeginsWith': 'beginsWith', 'NotBeginsWith': 'notBeginsWith',
    'Filled': 'filled', 'NotFilled': 'notFilled',
}

AGG_FUNCS = {
    'Сумма', 'Количество',
    'Минимум', 'Максимум',
    'Среднее',
    'Sum', 'Count', 'Min', 'Max', 'Avg', 'Minimum', 'Maximum', 'Average',
}

DEFAULT_SOURCE_NAME = 'ИсточникДанных1'
NAME_BEGIN = 'НачалоПериода'
NAME_END = 'КонецПериода'
EXPR_BEGIN_SUFFIX = '.ДатаНачала'
EXPR_END_SUFFIX = '.ДатаОкончания'
VARIANT_MAIN = 'Основной'
ZERO_DATE = '0001-01-01T00:00:00'

SIMPLE_NAME = re.compile(r'^[^\s:@#\[\]=]+$')

warnings_list = []
ns_prefixes = {}
dropped_setting_ids = 0


def local(tag):
    return tag.split('}')[-1] if isinstance(tag, str) else ''


def kids(elem, name):
    if elem is None:
        return []
    return [c for c in elem if local(c.tag) == name]


def kid(elem, name):
    if elem is None:
        return None
    for c in elem:
        if local(c.tag) == name:
            return c
    return None


def text_of(elem):
    if elem is None or elem.text is None:
        return ''
    return elem.text


def xsi_local(elem):
    if elem is None:
        return ''
    t = elem.get(XSI_TYPE) or ''
    return t.split(':')[-1]


def add_todo(node, msg):
    node.setdefault('_todo', []).append(msg)
    warnings_list.append(msg)


def ml_text(elem, todo_node):
    items = kids(elem, 'item')
    if not items:
        return text_of(elem)
    langs = {}
    for it in items:
        langs[text_of(kid(it, 'lang')).strip()] = text_of(kid(it, 'content'))
    if len(langs) > 1 and todo_node is not None:
        add_todo(todo_node, 'многоязычный текст: сохранен только ru')
    if 'ru' in langs:
        return langs['ru']
    for v in langs.values():
        return v
    return ''


def resolve_qname_uri(qtext):
    if ':' in qtext:
        pfx = qtext.split(':', 1)[0]
        return ns_prefixes.get(pfx, ''), qtext.split(':', 1)[1]
    return '', qtext


def normalize_color(raw):
    raw = (raw or '').strip()
    if ':' in raw:
        pfx, loc = raw.split(':', 1)
        uri = ns_prefixes.get(pfx, '')
        if uri == URI_STYLE or pfx == 'style':
            return 'style:' + loc
        if uri == URI_WEB or pfx == 'web':
            return 'web:' + loc
        if uri == URI_WIN or pfx == 'win':
            return 'win:' + loc
    return raw


def type_shorthand(vt_elem, node):
    types = kids(vt_elem, 'Type')
    if kids(vt_elem, 'TypeSet'):
        add_todo(node, 'valueType: TypeSet не поддержан нашим DSL')
    if not types:
        return None
    if len(types) > 1:
        names = ', '.join((text_of(t) or '').strip() for t in types)
        add_todo(node, 'составной тип не поддержан: ' + names)
        return None
    raw = (text_of(types[0]) or '').strip()
    uri, loc = resolve_qname_uri(raw)
    if uri == URI_CFG:
        return loc
    if loc == 'StandardPeriod':
        return 'StandardPeriod'
    if loc == 'ValueStorage':
        add_todo(node, 'тип ValueStorage не поддержан нашим DSL')
        return None
    if loc == 'boolean':
        return 'boolean'
    if loc == 'string':
        q = kid(vt_elem, 'StringQualifiers')
        if q is None:
            return 'string'
        length = text_of(kid(q, 'Length')).strip() or '0'
        allowed = text_of(kid(q, 'AllowedLength')).strip()
        if allowed and allowed != 'Variable':
            add_todo(node, 'StringQualifiers AllowedLength=' + allowed + ' не поддержан (принят Variable)')
        return 'string' if length == '0' else 'string(' + length + ')'
    if loc == 'decimal':
        q = kid(vt_elem, 'NumberQualifiers')
        if q is None:
            return raw
        digits = text_of(kid(q, 'Digits')).strip() or '0'
        frac = text_of(kid(q, 'FractionDigits')).strip() or '0'
        sign = text_of(kid(q, 'AllowedSign')).strip()
        if sign == 'Nonnegative':
            return 'decimal(' + digits + ',' + frac + ',nonneg)'
        return 'decimal(' + digits + ',' + frac + ')'
    if loc == 'dateTime':
        q = kid(vt_elem, 'DateQualifiers')
        frac = text_of(kid(q, 'DateFractions')).strip() if q is not None else 'DateTime'
        if frac == 'Date':
            return 'date'
        if frac in ('DateTime', ''):
            return 'dateTime'
        add_todo(node, 'DateQualifiers DateFractions=' + frac + ' не поддержан')
        return 'dateTime'
    return raw


def restriction_tokens(el):
    toks = []
    if el is None:
        return toks
    m = {'field': 'noField', 'condition': 'noFilter', 'group': 'noGroup', 'order': 'noOrder'}
    for c in el:
        n = local(c.tag)
        if n in m and text_of(c).strip() == 'true':
            toks.append(m[n])
    return toks


def decode_setting_value(v_el, todo_node, pname):
    if v_el is None:
        return ''
    xt = xsi_local(v_el)
    if xt == 'LocalStringType':
        return ml_text(v_el, todo_node)
    if xt == 'Color':
        return normalize_color(text_of(v_el))
    if xt in ('Font', 'Line'):
        add_todo(todo_node, 'оформление "' + pname + '": тип значения ' + xt + ' не поддержан нашим DSL')
        return text_of(v_el).strip()
    return text_of(v_el)


def build_appearance_map(app_el, todo_node):
    result = {}
    for it in kids(app_el, 'item'):
        p = text_of(kid(it, 'parameter')).strip()
        if not p:
            continue
        val = decode_setting_value(kid(it, 'value'), todo_node, p)
        use_el = kid(it, 'use')
        if use_el is not None and text_of(use_el).strip() == 'false':
            result[p] = {'value': val, 'use': False}
        else:
            result[p] = val
    return result


# === Fields ===

def build_field(fel):
    xt = xsi_local(fel)
    node = {}
    if xt == 'DataSetFieldFolder':
        node['dataPath'] = text_of(kid(fel, 'dataPath'))
        add_todo(node, 'папка полей (DataSetFieldFolder) не поддержана нашим DSL')
        return node
    if xt not in ('DataSetFieldField', ''):
        add_todo(node, 'неподдержанный тип поля: ' + xt)
        return node

    data_path = text_of(kid(fel, 'dataPath'))
    field = text_of(kid(fel, 'field'))
    title = ''
    t_el = kid(fel, 'title')
    if t_el is not None:
        title = ml_text(t_el, node)

    roles = []
    role_extra = {}
    r_el = kid(fel, 'role')
    if r_el is not None:
        period_num = ''
        period_type = ''
        for rc in r_el:
            rl = local(rc.tag)
            rv = text_of(rc).strip()
            if rl in ('dimension', 'account', 'balance') and rv == 'true':
                roles.append(rl)
            elif rl == 'periodNumber':
                period_num = rv
            elif rl == 'periodType':
                period_type = rv
            elif rl in ('accountTypeExpression', 'balanceGroup'):
                role_extra[rl] = rv
            else:
                add_todo(node, 'элемент роли не поддержан: ' + rl)
        if period_num == '1' and period_type == 'Main':
            roles.append('period')
        elif period_num or period_type:
            add_todo(node, 'роль периода не свернута: periodNumber=' + period_num + ', periodType=' + period_type)

    restrict = restriction_tokens(kid(fel, 'useRestriction'))
    attr_restrict = restriction_tokens(kid(fel, 'attributeUseRestriction'))
    vt_el = kid(fel, 'valueType')
    type_str = type_shorthand(vt_el, node) if vt_el is not None else None
    app_el = kid(fel, 'appearance')
    appearance = build_appearance_map(app_el, node) if app_el is not None else None
    pres_expr = text_of(kid(fel, 'presentationExpression'))

    handled = {'dataPath', 'field', 'title', 'role', 'useRestriction',
               'attributeUseRestriction', 'valueType', 'appearance', 'presentationExpression'}
    for c in fel:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент поля не поддержан: ' + ln)

    can_short = (
        bool(SIMPLE_NAME.match(data_path or '')) and
        (not field or field == data_path) and
        not title and not role_extra and not attr_restrict and
        not appearance and not pres_expr and '_todo' not in node and
        (type_str is None or bool(SIMPLE_NAME.match(type_str)))
    )
    if can_short:
        s = data_path
        if type_str:
            s += ': ' + type_str
        for r in roles:
            s += ' @' + r
        for t in restrict:
            s += ' #' + t
        return s

    obj = {'dataPath': data_path}
    if field and field != data_path:
        obj['field'] = field
    if title:
        obj['title'] = title
    if type_str:
        obj['type'] = type_str
    if roles or role_extra:
        if len(roles) == 1 and not role_extra:
            obj['role'] = roles[0]
        else:
            ro = {}
            for r in roles:
                ro[r] = True
            for k, v in role_extra.items():
                ro[k] = v
            obj['role'] = ro
    if restrict:
        obj['restrict'] = restrict
    if attr_restrict:
        obj['attrRestrict'] = attr_restrict
    if appearance:
        obj['appearance'] = appearance
    if pres_expr:
        obj['presentationExpression'] = pres_expr
    if '_todo' in node:
        obj['_todo'] = node['_todo']
    return obj


# === DataSets ===

def build_data_set(el, default_source):
    node = {'name': text_of(kid(el, 'name'))}
    xt = xsi_local(el)
    src = text_of(kid(el, 'dataSource'))
    if xt == 'DataSetQuery':
        if src and src != default_source:
            node['source'] = src
        query_text = text_of(kid(el, 'query'))
        if '\n' in query_text:
            safe_name = safe_query_file_name(str(node['name']))
            external_queries[safe_name] = query_text
            node['query'] = '@' + query_file_prefix[0] + '-' + safe_name + '.sql'
        else:
            node['query'] = query_text
        aff = kid(el, 'autoFillFields')
        if aff is not None and text_of(aff).strip() == 'false':
            node['autoFillFields'] = False
    elif xt == 'DataSetObject':
        if src and src != default_source:
            node['source'] = src
        node['objectName'] = text_of(kid(el, 'objectName'))
    elif xt == 'DataSetUnion':
        items = []
        for sub in kids(el, 'item') + kids(el, 'dataSet'):
            items.append(build_data_set(sub, default_source))
        node['items'] = items
    else:
        add_todo(node, 'неподдержанный тип набора данных: ' + (xt or '(нет xsi:type)'))
    handled = {'name', 'dataSource', 'field'}
    if xt == 'DataSetQuery':
        handled |= {'query', 'autoFillFields'}
    elif xt == 'DataSetObject':
        handled.add('objectName')
    elif xt == 'DataSetUnion':
        handled |= {'item', 'dataSet'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент набора данных не поддержан: ' + ln)
    fields = [build_field(f) for f in kids(el, 'field')]
    if fields:
        node['fields'] = fields
    return node


# === DataSetLinks ===

def build_link(el):
    node = {
        'source': text_of(kid(el, 'sourceDataSet')),
        'dest': text_of(kid(el, 'destinationDataSet')),
        'sourceExpr': text_of(kid(el, 'sourceExpression')),
        'destExpr': text_of(kid(el, 'destinationExpression')),
    }
    p = kid(el, 'parameter')
    if p is not None and text_of(p):
        node['parameter'] = text_of(p)
    handled = {'sourceDataSet', 'destinationDataSet', 'sourceExpression',
               'destinationExpression', 'parameter'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент связи наборов не поддержан: ' + ln)
    return node


# === CalculatedFields ===

def build_calc(el):
    node = {}
    dp = text_of(kid(el, 'dataPath'))
    expr = text_of(kid(el, 'expression'))
    title = ''
    t_el = kid(el, 'title')
    if t_el is not None:
        title = ml_text(t_el, node)
    vt_el = kid(el, 'valueType')
    type_str = type_shorthand(vt_el, node) if vt_el is not None else None
    restrict = restriction_tokens(kid(el, 'useRestriction'))
    app_el = kid(el, 'appearance')
    appearance = build_appearance_map(app_el, node) if app_el is not None else None

    handled = {'dataPath', 'expression', 'title', 'valueType', 'useRestriction', 'appearance'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент вычисляемого поля не поддержан: ' + ln)

    restrict_pat = re.compile(r'#(noField|noFilter|noCondition|noGroup|noOrder)\b')
    can_short = (
        '_todo' not in node and not appearance and
        bool(SIMPLE_NAME.match(dp or '')) and
        expr and '\n' not in expr and not restrict_pat.search(expr) and
        (not title or not re.search(r'[\]=#@]', title)) and
        (type_str is None or bool(SIMPLE_NAME.match(type_str)))
    )
    if can_short:
        s = dp
        if title:
            s += ' [' + title + ']'
        if type_str:
            s += ': ' + type_str
        s += ' = ' + expr
        for t in restrict:
            s += ' #' + t
        return s

    obj = {'dataPath': dp, 'expression': expr}
    if title:
        obj['title'] = title
    if type_str:
        obj['type'] = type_str
    if restrict:
        obj['restrict'] = restrict
    if appearance:
        obj['appearance'] = appearance
    if '_todo' in node:
        obj['_todo'] = node['_todo']
    return obj


# === TotalFields ===

def build_total(el):
    node = {}
    dp = text_of(kid(el, 'dataPath'))
    expr = text_of(kid(el, 'expression'))
    groups = [text_of(g) for g in kids(el, 'group')]
    handled = {'dataPath', 'expression', 'group'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент итогового поля не поддержан: ' + ln)

    if ('_todo' not in node and not groups and expr and '\n' not in expr
            and SIMPLE_NAME.match(dp or '') and expr not in AGG_FUNCS):
        m = re.match(r'^(\w+)\((.+)\)$', expr)
        if m and m.group(1) in AGG_FUNCS and m.group(2) == dp:
            return dp + ': ' + m.group(1)
        return dp + ': ' + expr

    obj = {'dataPath': dp, 'expression': expr}
    if groups:
        obj['group'] = groups[0] if len(groups) == 1 else groups
    if '_todo' in node:
        obj['_todo'] = node['_todo']
    return obj


# === Parameters ===

def build_parameter(el):
    node = {'name': text_of(kid(el, 'name'))}
    t_el = kid(el, 'title')
    if t_el is not None:
        title = ml_text(t_el, node)
        if title:
            node['title'] = title
    vt_el = kid(el, 'valueType')
    if vt_el is not None:
        ts = type_shorthand(vt_el, node)
        if ts:
            node['type'] = ts
    v_el = kid(el, 'value')
    if v_el is not None and (v_el.get(XSI_NIL) or '') != 'true':
        vxt = xsi_local(v_el)
        if vxt == 'StandardPeriod':
            node['value'] = text_of(kid(v_el, 'variant')).strip()
            sd = text_of(kid(v_el, 'startDate')).strip()
            ed = text_of(kid(v_el, 'endDate')).strip()
            if (sd and sd != ZERO_DATE) or (ed and ed != ZERO_DATE):
                add_todo(node, 'нестандартные даты StandardPeriod потеряны: ' + sd + ' / ' + ed)
        elif vxt == 'boolean':
            node['value'] = text_of(v_el).strip()
        else:
            node['value'] = text_of(v_el)
    if text_of(kid(el, 'useRestriction')).strip() == 'true':
        node['useRestriction'] = True
    expr = text_of(kid(el, 'expression'))
    if expr:
        node['expression'] = expr
    if text_of(kid(el, 'availableAsField')).strip() == 'false':
        node['availableAsField'] = False
    if text_of(kid(el, 'valueListAllowed')).strip() == 'true':
        node['valueListAllowed'] = True
    if text_of(kid(el, 'denyIncompleteValues')).strip() == 'true':
        node['denyIncompleteValues'] = True
    use = text_of(kid(el, 'use')).strip()
    if use:
        node['use'] = use
    avs = kids(el, 'availableValue')
    if avs:
        av_list = []
        for av in avs:
            av_obj = {'value': text_of(kid(av, 'value'))}
            p_el = kid(av, 'presentation')
            if p_el is not None:
                pres = ml_text(p_el, node)
                if pres:
                    av_obj['presentation'] = pres
            av_list.append(av_obj)
        node['availableValues'] = av_list

    handled = {'name', 'title', 'valueType', 'value', 'useRestriction', 'expression',
               'availableAsField', 'valueListAllowed', 'denyIncompleteValues', 'use',
               'availableValue'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент параметра не поддержан: ' + ln)
    return node


def collapse_auto_dates(params):
    companion_keys = {'name', 'title', 'type', 'value', 'useRestriction',
                      'availableAsField', 'expression'}
    by_name = {}
    for p in params:
        if p.get('name') not in by_name:
            by_name[p['name']] = p
    drop = []
    for p in params:
        if p.get('type') != 'StandardPeriod' or '_todo' in p:
            continue
        b = by_name.get(NAME_BEGIN)
        e = by_name.get(NAME_END)
        if b is None or e is None or b is p or e is p:
            continue
        expected_b = '&' + p['name'] + EXPR_BEGIN_SUFFIX
        expected_e = '&' + p['name'] + EXPR_END_SUFFIX
        if (b.get('expression') == expected_b and e.get('expression') == expected_e
                and not (set(b.keys()) - companion_keys)
                and not (set(e.keys()) - companion_keys)):
            p['autoDates'] = True
            drop.append(id(b))
            drop.append(id(e))
            if p.get('use') == 'Always':
                del p['use']
            if p.get('denyIncompleteValues') is True:
                del p['denyIncompleteValues']
            break
    return [p for p in params if id(p) not in drop]


def param_to_shorthand(p):
    if p.get('useRestriction') is True and p.get('availableAsField') is False:
        p = dict(p)
        del p['useRestriction']
        del p['availableAsField']
        p['hidden'] = True
    allowed = {'name', 'title', 'type', 'value', 'autoDates', 'valueListAllowed', 'hidden'}
    if set(p.keys()) - allowed:
        return p
    name = p.get('name', '')
    type_str = p.get('type', '')
    title = p.get('title', '')
    value = p.get('value')
    if not SIMPLE_NAME.match(name or ''):
        return p
    if not type_str or not SIMPLE_NAME.match(type_str):
        return p
    if title and re.search(r'[\]@#=:]', title):
        return p
    if value is not None:
        v_str = str(value)
        if isinstance(value, bool):
            v_str = 'true' if value else 'false'
        if re.search(r'[@\[\]]', v_str) or '\n' in v_str or v_str.strip() != v_str or not v_str:
            return p
    else:
        v_str = None
    s = name
    if title:
        s += ' [' + title + ']'
    s += ': ' + type_str
    if v_str is not None:
        s += ' = ' + v_str
    if p.get('autoDates'):
        s += ' @autoDates'
    if p.get('valueListAllowed'):
        s += ' @valueList'
    if p.get('hidden'):
        s += ' @hidden'
    return s


# === Selection / Filter / Order ===

def build_selection(sel_el, todo_node):
    items = []
    for it in kids(sel_el, 'item'):
        xt = xsi_local(it)
        if xt == 'SelectedItemAuto':
            if text_of(kid(it, 'use')).strip() == 'false':
                add_todo(todo_node, 'выборка: SelectedItemAuto с use=false не поддержан')
            items.append('Auto')
        elif xt == 'SelectedItemField':
            fld = text_of(kid(it, 'field'))
            if text_of(kid(it, 'use')).strip() == 'false':
                add_todo(todo_node, 'выборка: use=false у поля "' + fld + '" не поддержано')
            t_el = kid(it, 'lwsTitle')
            if t_el is not None:
                items.append({'field': fld, 'title': ml_text(t_el, todo_node)})
            else:
                items.append(fld)
        elif xt == 'SelectedItemFolder':
            t_el = kid(it, 'lwsTitle')
            folder = {'folder': ml_text(t_el, todo_node) if t_el is not None else ''}
            sub_items = []
            for sub in kids(it, 'item'):
                sxt = xsi_local(sub)
                if sxt == 'SelectedItemField':
                    sub_items.append(text_of(kid(sub, 'field')))
                else:
                    add_todo(folder, 'элемент папки выборки не поддержан: ' + sxt)
            folder['items'] = sub_items
            placement = text_of(kid(it, 'placement')).strip()
            if placement and placement != 'Auto':
                add_todo(folder, 'размещение папки выборки не поддержано: ' + placement)
            items.append(folder)
        else:
            stub = {}
            add_todo(stub, 'элемент выборки не поддержан: ' + xt)
            items.append(stub)
    return items


def detect_value_type(v_str):
    if v_str in ('true', 'false'):
        return 'xs:boolean'
    if re.match(r'^\d{4}-\d{2}-\d{2}T', v_str):
        return 'xs:dateTime'
    if re.match(r'^\d+(\.\d+)?$', v_str):
        return 'xs:decimal'
    if re.match(r'^(Перечисление|Справочник|ПланСчетов|Документ|ПланВидовХарактеристик|ПланВидовРасчета)\.', v_str):
        return 'dcscor:DesignTimeValue'
    return 'xs:string'


def build_filter_item(it, todo_node):
    xt = xsi_local(it)
    if xt == 'FilterItemGroup':
        gt = text_of(kid(it, 'groupType')).strip()
        gmap = {'AndGroup': 'And', 'OrGroup': 'Or', 'NotGroup': 'Not'}
        node = {'group': gmap.get(gt, 'And')}
        if gt and gt not in gmap:
            add_todo(node, 'тип группы отбора не распознан: ' + gt)
        if text_of(kid(it, 'use')).strip() == 'false':
            add_todo(node, 'группа отбора: use=false не поддержано нашим DSL')
        sub_items = []
        for sub in kids(it, 'item'):
            sub_items.append(build_filter_item(sub, node))
        node['items'] = sub_items
        for extra in ('viewMode', 'userSettingID', 'userSettingPresentation'):
            if kid(it, extra) is not None:
                add_todo(node, 'группа отбора: ' + extra + ' не поддержан нашим DSL')
        return node
    if xt != 'FilterItemComparison':
        stub = {}
        add_todo(stub, 'элемент отбора не поддержан: ' + xt)
        return stub

    node = {}
    left_el = kid(it, 'left')
    field = text_of(left_el)
    if left_el is not None and xsi_local(left_el) not in ('Field', ''):
        add_todo(node, 'левая часть отбора не поддержана: ' + xsi_local(left_el))
    comp = text_of(kid(it, 'comparisonType')).strip()
    op = COMPARISON_OPS.get(comp, comp)
    use_off = text_of(kid(it, 'use')).strip() == 'false'

    value = None
    value_type = None
    r_el = kid(it, 'right')
    if r_el is not None and (r_el.get(XSI_NIL) or '') != 'true':
        rxt = xsi_local(r_el)
        if rxt == 'boolean':
            value = text_of(r_el).strip() == 'true'
            value_type = 'xs:boolean'
        elif rxt in ('decimal', 'dateTime', 'string'):
            value = text_of(r_el)
            value_type = 'xs:' + rxt
        elif rxt == 'DesignTimeValue':
            value = text_of(r_el)
            value_type = 'dcscor:DesignTimeValue'
        elif rxt == '':
            value = text_of(r_el)
            value_type = 'xs:string'
        else:
            value = text_of(r_el)
            value_type = rxt
            add_todo(node, 'тип значения отбора не поддержан: ' + rxt)

    presentation = ''
    p_el = kid(it, 'presentation')
    if p_el is not None:
        presentation = ml_text(p_el, node)
    view_mode = text_of(kid(it, 'viewMode')).strip()
    setting_id = text_of(kid(it, 'userSettingID')).strip()
    usp = ''
    usp_el = kid(it, 'userSettingPresentation')
    if usp_el is not None:
        usp = ml_text(usp_el, node)

    v_str = None
    if value is not None:
        v_str = ('true' if value else 'false') if isinstance(value, bool) else str(value)
    can_short = (
        '_todo' not in node and not presentation and not usp and
        comp in COMPARISON_OPS and bool(SIMPLE_NAME.match(field or '')) and
        (v_str is None or (v_str and '\n' not in v_str and '@' not in v_str
                           and v_str != '_' and v_str.strip() == v_str
                           and detect_value_type(v_str) == value_type))
    )
    if can_short:
        s = field + ' ' + op
        if v_str is not None:
            s += ' ' + v_str
        elif op in ('=', '<>', '>', '>=', '<', '<='):
            s += ' _'
        if use_off:
            s += ' @off'
        if setting_id:
            s += ' @user'
        if view_mode == 'QuickAccess':
            s += ' @quickAccess'
        elif view_mode == 'Normal':
            s += ' @normal'
        elif view_mode == 'Inaccessible':
            s += ' @inaccessible'
        elif view_mode:
            return _filter_object(node, field, op, value, value_type, use_off,
                                  presentation, view_mode, setting_id, usp)
        return s
    return _filter_object(node, field, op, value, value_type, use_off,
                          presentation, view_mode, setting_id, usp)


def _filter_object(node, field, op, value, value_type, use_off,
                   presentation, view_mode, setting_id, usp):
    obj = {'field': field, 'op': op}
    if value is not None:
        obj['value'] = value
        if value_type:
            obj['valueType'] = value_type
    if use_off:
        obj['use'] = False
    if presentation:
        obj['presentation'] = presentation
    if view_mode:
        obj['viewMode'] = view_mode
    if setting_id:
        obj['userSettingID'] = setting_id
    if usp:
        obj['userSettingPresentation'] = usp
    if '_todo' in node:
        obj['_todo'] = node['_todo']
    return obj


def build_filter(f_el, todo_node):
    return [build_filter_item(it, todo_node) for it in kids(f_el, 'item')]


def build_order(ord_el, todo_node):
    items = []
    for it in kids(ord_el, 'item'):
        xt = xsi_local(it)
        if xt == 'OrderItemAuto':
            items.append('Auto')
        elif xt == 'OrderItemField':
            f = text_of(kid(it, 'field'))
            d = text_of(kid(it, 'orderType')).strip()
            if not SIMPLE_NAME.match(f or ''):
                stub = {}
                add_todo(stub, 'поле сортировки не выражается shorthand-строкой: "' + f + '"')
                items.append(stub)
            elif d == 'Desc':
                items.append(f + ' desc')
            else:
                items.append(f)
        else:
            stub = {}
            add_todo(stub, 'элемент сортировки не поддержан: ' + xt)
            items.append(stub)
    return items


# === ConditionalAppearance / OutputParameters / DataParameters ===

def build_conditional_appearance(ca_el, todo_node):
    out = []
    for it in kids(ca_el, 'item'):
        node = {}
        sel_el = kid(it, 'selection')
        if sel_el is not None:
            flds = [text_of(kid(x, 'field')) for x in kids(sel_el, 'item')]
            flds = [f for f in flds if f]
            if flds:
                node['selection'] = flds
        f_el = kid(it, 'filter')
        if f_el is not None:
            flt = build_filter(f_el, node)
            if flt:
                node['filter'] = flt
        app_el = kid(it, 'appearance')
        if app_el is not None:
            app = build_appearance_map(app_el, node)
            if app:
                node['appearance'] = app
        p_el = kid(it, 'presentation')
        if p_el is not None:
            pres = ml_text(p_el, node)
            if pres:
                node['presentation'] = pres
        vm = text_of(kid(it, 'viewMode')).strip()
        if vm:
            node['viewMode'] = vm
        uid = text_of(kid(it, 'userSettingID')).strip()
        if uid:
            node['userSettingID'] = uid
        if text_of(kid(it, 'use')).strip() == 'false':
            add_todo(node, 'условное оформление: use=false не поддержано нашим DSL')
        scope_el = kid(it, 'scope')
        if scope_el is not None and (text_of(scope_el).strip() or len(list(scope_el))):
            add_todo(node, 'область применения (scope) не поддержана нашим DSL')
        usp_el = kid(it, 'userSettingPresentation')
        if usp_el is not None:
            add_todo(node, 'условное оформление: userSettingPresentation не поддержан')
        out.append(node)
    return out


def build_output_params(op_el, todo_node):
    result = {}
    for it in kids(op_el, 'item'):
        p = text_of(kid(it, 'parameter')).strip()
        if not p:
            continue
        val = decode_setting_value(kid(it, 'value'), todo_node, p)
        if text_of(kid(it, 'use')).strip() == 'false':
            add_todo(todo_node, 'параметр вывода "' + p + '": use=false не поддержан, значение сохранено как активное')
        result[p] = val
    return result


PERIOD_VARIANTS = {
    'Custom', 'Today', 'ThisWeek', 'ThisTenDays', 'ThisMonth', 'ThisQuarter',
    'ThisHalfYear', 'ThisYear', 'FromBeginningOfThisWeek', 'FromBeginningOfThisTenDays',
    'FromBeginningOfThisMonth', 'FromBeginningOfThisQuarter', 'FromBeginningOfThisHalfYear',
    'FromBeginningOfThisYear', 'LastWeek', 'LastTenDays', 'LastMonth', 'LastQuarter',
    'LastHalfYear', 'LastYear', 'NextDay', 'NextWeek', 'NextTenDays', 'NextMonth',
    'NextQuarter', 'NextHalfYear', 'NextYear', 'TillEndOfThisWeek', 'TillEndOfThisTenDays',
    'TillEndOfThisMonth', 'TillEndOfThisQuarter', 'TillEndOfThisHalfYear', 'TillEndOfThisYear',
}


def build_data_parameters(dp_el, todo_node):
    items = []
    for it in kids(dp_el, 'item'):
        node = {'parameter': text_of(kid(it, 'parameter'))}
        use_off = text_of(kid(it, 'use')).strip() == 'false'
        variant = None
        v_el = kid(it, 'value')
        if v_el is not None:
            if (v_el.get(XSI_NIL) or '') == 'true':
                node['nilValue'] = True
            else:
                vxt = xsi_local(v_el)
                if vxt == 'StandardPeriod':
                    variant = text_of(kid(v_el, 'variant')).strip()
                    node['value'] = {'variant': variant}
                    sd = text_of(kid(v_el, 'startDate')).strip()
                    ed = text_of(kid(v_el, 'endDate')).strip()
                    if (sd and sd != ZERO_DATE) or (ed and ed != ZERO_DATE):
                        add_todo(node, 'нестандартные даты StandardPeriod потеряны: ' + sd + ' / ' + ed)
                elif vxt == 'boolean':
                    node['value'] = text_of(v_el).strip() == 'true'
                else:
                    node['value'] = text_of(v_el)
                    if vxt == 'decimal':
                        node['valueType'] = 'decimal'
        if use_off:
            node['use'] = False
        vm = text_of(kid(it, 'viewMode')).strip()
        if vm:
            node['viewMode'] = vm
        uid = text_of(kid(it, 'userSettingID')).strip()
        if uid:
            node['userSettingID'] = uid
        usp_el = kid(it, 'userSettingPresentation')
        usp = ml_text(usp_el, node) if usp_el is not None else ''
        if usp:
            node['userSettingPresentation'] = usp

        v = node.get('value')
        v_str = None
        if isinstance(v, dict):
            v_str = variant
        elif isinstance(v, bool):
            v_str = 'true' if v else 'false'
        elif v is not None:
            v_str = str(v)
            if v_str in PERIOD_VARIANTS:
                v_str = None
        can_short = (
            '_todo' not in node and not usp and 'nilValue' not in node
            and 'valueType' not in node and vm in ('', 'QuickAccess', 'Normal')
            and bool(SIMPLE_NAME.match(node['parameter'] or ''))
            and (v is None or (v_str is not None and '@' not in v_str
                               and '\n' not in v_str and v_str.strip() == v_str and v_str))
        )
        if can_short:
            s = node['parameter']
            if v_str is not None:
                s += ' = ' + v_str
            if use_off:
                s += ' @off'
            if uid:
                s += ' @user'
            if vm == 'QuickAccess':
                s += ' @quickAccess'
            elif vm == 'Normal':
                s += ' @normal'
            items.append(s)
        else:
            items.append(node)
    return items


# === Structure ===

def build_group_items(gi_el, todo_node):
    fields = []
    for it in kids(gi_el, 'item'):
        xt = xsi_local(it)
        if xt == 'GroupItemField':
            f = text_of(kid(it, 'field'))
            gt = text_of(kid(it, 'groupType')).strip() or 'Items'
            pat = text_of(kid(it, 'periodAdditionType')).strip() or 'None'
            pab = text_of(kid(it, 'periodAdditionBegin')).strip()
            pae = text_of(kid(it, 'periodAdditionEnd')).strip()
            if gt == 'Items' and pat == 'None':
                fields.append(f)
            else:
                obj = {'field': f}
                if gt != 'Items':
                    obj['groupType'] = gt
                if pat != 'None':
                    obj['periodAdditionType'] = pat
                fields.append(obj)
            if (pab and pab != ZERO_DATE) or (pae and pae != ZERO_DATE):
                add_todo(todo_node, 'границы добавления периода у "' + f + '" потеряны')
        elif xt == 'GroupItemAuto':
            stub = {}
            add_todo(stub, 'группировка Авто (GroupItemAuto) не поддержана нашим DSL')
            fields.append(stub)
        else:
            stub = {}
            add_todo(stub, 'элемент группировки не поддержан: ' + xt)
            fields.append(stub)
    return fields


STRUCTURE_EXTRA_TODO = {'userSettingPresentation', 'itemsViewMode', 'columnsViewMode',
                        'rowsViewMode', 'pointsViewMode', 'seriesViewMode'}


def apply_structure_extras(el, node, handled):
    global dropped_setting_ids
    for c in el:
        ln = local(c.tag)
        if ln in handled:
            continue
        if ln == 'userSettingID':
            dropped_setting_ids += 1
        elif ln == 'viewMode':
            if text_of(c).strip() != 'Normal':
                add_todo(node, 'элемент структуры: viewMode=' + text_of(c).strip() + ' не поддержан')
        elif ln == 'use':
            if text_of(c).strip() == 'false':
                add_todo(node, 'элемент структуры: use=false не поддержан нашим DSL')
        elif ln in STRUCTURE_EXTRA_TODO:
            add_todo(node, 'элемент структуры: ' + ln + ' не поддержан нашим DSL')
        else:
            add_todo(node, 'элемент структуры не поддержан: ' + ln)


def build_structure_content(el, node, with_children):
    n_el = kid(el, 'name')
    if n_el is not None and text_of(n_el):
        node['name'] = text_of(n_el)
    gi_el = kid(el, 'groupItems')
    if gi_el is not None:
        node['groupBy'] = build_group_items(gi_el, node)
    ord_el = kid(el, 'order')
    if ord_el is not None:
        o = build_order(ord_el, node)
        if o and o != ['Auto']:
            node['order'] = o
    sel_el = kid(el, 'selection')
    if sel_el is not None:
        s = build_selection(sel_el, node)
        if s and s != ['Auto']:
            node['selection'] = s
    f_el = kid(el, 'filter')
    if f_el is not None:
        flt = build_filter(f_el, node)
        if flt:
            node['filter'] = flt
    ca_el = kid(el, 'conditionalAppearance')
    if ca_el is not None:
        ca = build_conditional_appearance(ca_el, node)
        if ca:
            node['conditionalAppearance'] = ca
    op_el = kid(el, 'outputParameters')
    if op_el is not None:
        op = build_output_params(op_el, node)
        if op:
            node['outputParameters'] = op
    handled = {'name', 'groupItems', 'order', 'selection', 'filter',
               'conditionalAppearance', 'outputParameters'}
    if with_children:
        children = [build_structure_item(c) for c in kids(el, 'item')]
        if children:
            node['children'] = children
        handled.add('item')
    apply_structure_extras(el, node, handled)


def build_structure_item(el):
    xt = xsi_local(el)
    if xt in ('', 'StructureItemGroup'):
        node = {}
        build_structure_content(el, node, True)
        return node
    if xt == 'StructureItemTable':
        node = {'type': 'table'}
        n_el = kid(el, 'name')
        if n_el is not None and text_of(n_el):
            node['name'] = text_of(n_el)
        rows = []
        for r in kids(el, 'row'):
            axis = {}
            build_structure_content(r, axis, False)
            rows.append(axis)
        cols = []
        for c in kids(el, 'column'):
            axis = {}
            build_structure_content(c, axis, False)
            if 'name' in axis:
                add_todo(axis, 'имя колонки таблицы не поддержано компилятором')
            cols.append(axis)
        if rows:
            node['rows'] = rows
        if cols:
            node['columns'] = cols
        handled = {'name', 'row', 'column'}
        for extra in ('selection', 'filter', 'conditionalAppearance', 'outputParameters'):
            if kid(el, extra) is not None:
                add_todo(node, 'таблица структуры: ' + extra + ' на уровне таблицы не поддержан')
                handled.add(extra)
        apply_structure_extras(el, node, handled)
        return node
    if xt == 'StructureItemChart':
        node = {'type': 'chart'}
        n_el = kid(el, 'name')
        if n_el is not None and text_of(n_el):
            node['name'] = text_of(n_el)
        points = kids(el, 'point')
        if points:
            axis = {}
            build_structure_content(points[0], axis, False)
            node['points'] = axis
            if len(points) > 1:
                add_todo(node, 'несколько точек диаграммы: сохранена только первая')
        series = kids(el, 'series')
        if series:
            axis = {}
            build_structure_content(series[0], axis, False)
            node['series'] = axis
            if len(series) > 1:
                add_todo(node, 'несколько серий диаграммы: сохранена только первая')
        sel_el = kid(el, 'selection')
        if sel_el is not None:
            s = build_selection(sel_el, node)
            if s:
                node['selection'] = s
        op_el = kid(el, 'outputParameters')
        if op_el is not None:
            op = build_output_params(op_el, node)
            if op:
                node['outputParameters'] = op
        handled = {'name', 'point', 'series', 'selection', 'outputParameters'}
        apply_structure_extras(el, node, handled)
        return node
    stub = {}
    add_todo(stub, 'элемент структуры не поддержан: ' + xt)
    return stub


def try_structure_shorthand(items):
    segments = []
    current = items
    while True:
        if len(current) != 1 or not isinstance(current[0], dict):
            return None
        node = current[0]
        if set(node.keys()) - {'groupBy', 'children'}:
            return None
        gb = node.get('groupBy')
        children = node.get('children')
        if not gb:
            if children:
                return None
            segments.append('details')
            break
        if len(gb) != 1 or not isinstance(gb[0], str) or not SIMPLE_NAME.match(gb[0]):
            return None
        segments.append(gb[0])
        if not children:
            break
        current = children
    if not segments:
        return None
    return ' > '.join(segments)


# === Settings variants ===

def build_settings(s_el):
    s = {}
    sel_el = kid(s_el, 'selection')
    if sel_el is not None:
        sel = build_selection(sel_el, s)
        if sel:
            s['selection'] = sel
    f_el = kid(s_el, 'filter')
    if f_el is not None:
        flt = build_filter(f_el, s)
        if flt:
            s['filter'] = flt
    ord_el = kid(s_el, 'order')
    if ord_el is not None:
        o = build_order(ord_el, s)
        if o:
            s['order'] = o
    ca_el = kid(s_el, 'conditionalAppearance')
    if ca_el is not None:
        ca = build_conditional_appearance(ca_el, s)
        if ca:
            s['conditionalAppearance'] = ca
    op_el = kid(s_el, 'outputParameters')
    if op_el is not None:
        op = build_output_params(op_el, s)
        if op:
            s['outputParameters'] = op
    dp_el = kid(s_el, 'dataParameters')
    if dp_el is not None:
        dp = build_data_parameters(dp_el, s)
        if dp:
            s['dataParameters'] = dp
    struct_items = [build_structure_item(c) for c in kids(s_el, 'item')]
    if struct_items:
        short = try_structure_shorthand(struct_items)
        s['structure'] = short if short else struct_items
    handled = {'selection', 'filter', 'order', 'conditionalAppearance',
               'outputParameters', 'dataParameters', 'item'}
    for c in s_el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(s, 'настройка варианта не поддержана: ' + ln)
    return s


def build_variant(v_el):
    node = {'name': text_of(kid(v_el, 'name'))}
    p_el = kid(v_el, 'presentation')
    pres = ml_text(p_el, node) if p_el is not None else ''
    if pres and pres != node['name']:
        node['presentation'] = pres
    s_el = kid(v_el, 'settings')
    if s_el is not None:
        node['settings'] = build_settings(s_el)
    handled = {'name', 'presentation', 'settings'}
    for c in v_el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент варианта настроек не поддержан: ' + ln)
    return node


def is_default_variant(v):
    if v.get('name') != VARIANT_MAIN or 'presentation' in v or '_todo' in v:
        return False
    s = v.get('settings')
    if s is None:
        return True
    if set(s.keys()) - {'structure'}:
        return False
    st = s.get('structure')
    return st is None or st == 'details'


# === Templates ===

def parse_num(s):
    try:
        f = float(s)
    except ValueError:
        return 0
    return int(f) if f == int(f) else f


def build_template_cell(cell_el, tpl_node):
    info = {'width': 0, 'minHeight': 0, 'dd': '', 'probe': None, 'content': None}
    v_merge = False
    h_merge = False
    app_el = kid(cell_el, 'appearance')
    if app_el is not None:
        probe = {}
        for it in kids(app_el, 'item'):
            p = text_of(kid(it, 'parameter')).strip()
            v_el = kid(it, 'value')
            v_txt = text_of(v_el).strip() if v_el is not None else ''
            if p == 'ОбъединятьПоВертикали' and v_txt == 'true':
                v_merge = True
            elif p == 'ОбъединятьПоГоризонтали' and v_txt == 'true':
                h_merge = True
            elif p == 'МинимальнаяШирина':
                info['width'] = parse_num(v_txt)
            elif p == 'МинимальнаяВысота':
                info['minHeight'] = parse_num(v_txt)
            elif p == 'Расшифровка':
                info['dd'] = v_txt
            elif p == 'ЦветФона':
                probe['bgColor'] = normalize_color(v_txt)
            elif p == 'ЦветТекста':
                probe['textColor'] = normalize_color(v_txt)
            elif p == 'ЦветГраницы':
                probe['borderColor'] = normalize_color(v_txt)
            elif p == 'СтильГраницы':
                probe['borders'] = True
            elif p == 'ГоризонтальноеПоложение':
                probe['hAlign'] = v_txt
            elif p == 'ВертикальноеПоложение':
                probe['vAlign'] = v_txt
            elif p == 'Размещение':
                probe['wrap'] = (v_txt == 'Wrap')
            elif p == 'Шрифт' and v_el is not None:
                probe['font'] = v_el.get('faceName') or ''
                probe['fontSize'] = parse_num(v_el.get('height') or '0')
                probe['bold'] = (v_el.get('bold') == 'true')
                probe['italic'] = (v_el.get('italic') == 'true')
        info['probe'] = probe
    content = None
    item_el = kid(cell_el, 'item')
    if item_el is not None:
        ixt = xsi_local(item_el)
        if ixt == 'Field':
            v_el = kid(item_el, 'value')
            vxt = xsi_local(v_el)
            if vxt == 'Parameter':
                content = '{' + text_of(v_el).strip() + '}'
            elif vxt == 'LocalStringType':
                content = ml_text(v_el, tpl_node)
            else:
                content = text_of(v_el)
        elif 'Picture' in ixt:
            add_todo(tpl_node, 'ячейка макета с картинкой (' + ixt + ') не поддержана')
        else:
            add_todo(tpl_node, 'элемент ячейки макета не поддержан: ' + ixt)
    if content is None:
        if v_merge:
            content = '|'
        elif h_merge:
            content = '>'
    elif content == '|':
        content = '\\|'
    elif content == '>':
        content = '\\>'
    info['content'] = content
    return info


# Оформление ячейки читается целиком и сверяется с пресетами: встроенными и пользовательскими
# из skd-styles.json. Так распознается и свой стиль, а не только четыре штатных.
AREA_STYLE_PRESETS = {
    'data': {
        'font': 'Arial', 'fontSize': 10, 'bold': False, 'italic': False,
        'hAlign': None, 'vAlign': None, 'wrap': False,
        'bgColor': 'style:ReportGroup1BackColor', 'textColor': None,
        'borderColor': 'style:ReportLineColor', 'borders': True,
    },
    'header': {
        'font': 'Arial', 'fontSize': 10, 'bold': False, 'italic': False,
        'hAlign': 'Center', 'vAlign': None, 'wrap': True,
        'bgColor': 'style:ReportHeaderBackColor', 'textColor': None,
        'borderColor': 'style:ReportLineColor', 'borders': True,
    },
    'subheader': {
        'font': 'Arial', 'fontSize': 10, 'bold': False, 'italic': False,
        'hAlign': 'Center', 'vAlign': None, 'wrap': True,
        'bgColor': None, 'textColor': None,
        'borderColor': 'style:ReportLineColor', 'borders': True,
    },
    'total': {
        'font': 'Arial', 'fontSize': 10, 'bold': False, 'italic': False,
        'hAlign': None, 'vAlign': None, 'wrap': False,
        'bgColor': None, 'textColor': None,
        'borderColor': 'style:ReportLineColor', 'borders': True,
    },
    'none': {
        'font': None, 'fontSize': None, 'bold': False, 'italic': False,
        'hAlign': None, 'vAlign': None, 'wrap': False,
        'bgColor': None, 'textColor': None,
        'borderColor': None, 'borders': False,
    },
}

STYLE_KEYS = ('font', 'fontSize', 'bold', 'italic', 'hAlign', 'vAlign', 'wrap',
              'bgColor', 'textColor', 'borderColor', 'borders')

USER_STYLE_PRESETS = {}


def load_user_style_presets(base_dir):
    """Пользовательские пресеты берутся оттуда же, откуда их берет сборка: каталог макета,
    текущий каталог, затем подъем по дереву к presets/skills/skd."""
    candidates = [os.path.join(base_dir, 'skd-styles.json'),
                  os.path.join(os.getcwd(), 'skd-styles.json')]
    scan_dir = base_dir
    while scan_dir:
        candidates.append(os.path.join(scan_dir, 'presets', 'skills', 'skd', 'skd-styles.json'))
        parent_dir = os.path.dirname(scan_dir)
        if parent_dir == scan_dir:
            break
        scan_dir = parent_dir
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, encoding='utf-8-sig') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            for name, overrides in data.items():
                if not isinstance(overrides, dict):
                    continue
                base = dict(AREA_STYLE_PRESETS.get(name, AREA_STYLE_PRESETS['data']))
                base.update(overrides)
                USER_STYLE_PRESETS[name] = base
        return


def style_signature(props):
    out = {}
    for k in STYLE_KEYS:
        v = props.get(k)
        if k in ('bold', 'italic', 'wrap', 'borders'):
            out[k] = bool(v)
        elif k == 'fontSize':
            out[k] = None if v is None else parse_num(str(v))
        else:
            out[k] = v if v else None
    return tuple(out[k] for k in STYLE_KEYS)


def detect_template_style(probe):
    want = style_signature(probe)
    for name, preset in list(AREA_STYLE_PRESETS.items()) + list(USER_STYLE_PRESETS.items()):
        if style_signature(preset) == want:
            return name
    return None


def build_template(el):
    node = {'name': text_of(kid(el, 'name'))}
    if kid(el, 'templateCondition') is not None:
        add_todo(node, 'условие выбора макета (templateCondition) не поддержано нашим DSL')
    inner = kid(el, 'template')
    rows = []
    widths = []
    min_height = 0
    first_probe = None
    cell_probes = []
    cell_dd = {}
    if inner is not None:
        for row_el in kids(inner, 'item'):
            rxt = xsi_local(row_el)
            if rxt != 'TableRow':
                add_todo(node, 'элемент области макета не поддержан: ' + rxt)
                continue
            row = []
            row_probes = []
            c_i = 0
            for cell_el in kids(row_el, 'tableCell'):
                info = build_template_cell(cell_el, node)
                row.append(info['content'])
                row_probes.append(info['probe'])
                if len(rows) == 0:
                    widths.append(info['width'])
                    if c_i == 0:
                        min_height = info['minHeight']
                if first_probe is None and info['probe'] is not None:
                    first_probe = info['probe']
                content = info['content']
                if info['dd'] and isinstance(content, str) and content.startswith('{') and content.endswith('}'):
                    cell_dd[content[1:-1]] = info['dd']
                c_i += 1
            rows.append(row)
            cell_probes.append(row_probes)
    else:
        add_todo(node, 'макет без области AreaTemplate - строки не декомпилированы')
    style = None
    if first_probe is not None:
        style = detect_template_style(first_probe)
        if style is None:
            add_todo(node, 'оформление ячеек не распознано - подбери style вручную (header/data/subheader/total или skd-styles.json)')
    # Ячейка со своим оформлением записывается объектом: макетный стиль ей не подходит.
    if style:
        for r_i, row_probes in enumerate(cell_probes):
            for c_i, probe in enumerate(row_probes):
                if probe is None or c_i >= len(rows[r_i]):
                    continue
                cell_style = detect_template_style(probe)
                if cell_style is None or cell_style == style:
                    continue
                rows[r_i][c_i] = {'value': rows[r_i][c_i], 'style': cell_style}
    if style:
        node['style'] = style
    if any(w for w in widths):
        # Ширина колонки записывается строкой: так ее задает и читает наш DSL.
        node['widths'] = [str(w) for w in widths]
    if min_height:
        node['minHeight'] = min_height
    node['rows'] = rows

    params = []
    details = []
    for p_el in kids(el, 'parameter'):
        pxt = xsi_local(p_el)
        if pxt == 'ExpressionAreaTemplateParameter':
            params.append({'name': text_of(kid(p_el, 'name')),
                           'expression': text_of(kid(p_el, 'expression'))})
        elif pxt == 'DetailsAreaTemplateParameter':
            fe = kid(p_el, 'fieldExpression')
            details.append({
                'name': text_of(kid(p_el, 'name')),
                'field': text_of(kid(fe, 'field')) if fe is not None else '',
                'expr': text_of(kid(fe, 'expression')) if fe is not None else '',
                'action': text_of(kid(p_el, 'mainAction')).strip(),
            })
        else:
            add_todo(node, 'параметр макета не поддержан: ' + pxt)
    by_name = {}
    for p in params:
        by_name[p['name']] = p
    for d in details:
        target = None
        m = re.match(r'^Расшифровка_(.+)$', d['name'])
        if (m and d['field'] == 'ИмяРесурса' and d['action'] == 'DrillDown'
                and d['expr'] == '"' + m.group(1) + '"'):
            for pname, ref in cell_dd.items():
                if ref == d['name'] and pname in by_name:
                    target = by_name[pname]
                    break
            if target is not None:
                target['drilldown'] = m.group(1)
                continue
        add_todo(node, 'параметр расшифровки макета не свернут: ' + d['name'])
    if params:
        node['parameters'] = params

    handled = {'name', 'template', 'parameter', 'templateCondition'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент макета не поддержан: ' + ln)
    return node


def build_group_template(el, ttype_override):
    node = {}
    gn = kid(el, 'groupName')
    gf = kid(el, 'groupField')
    if gn is not None and text_of(gn):
        node['groupName'] = text_of(gn)
    elif gf is not None:
        node['groupField'] = text_of(gf)
    xml_ttype = text_of(kid(el, 'templateType')).strip()
    node['templateType'] = ttype_override if ttype_override else (xml_ttype or 'Header')
    node['template'] = text_of(kid(el, 'template'))
    handled = {'groupName', 'groupField', 'templateType', 'template'}
    for c in el:
        ln = local(c.tag)
        if ln not in handled:
            add_todo(node, 'элемент привязки макета не поддержан: ' + ln)
    return node


# === Main ===

def safe_query_file_name(name):
    """Имя набора приходит из чужого файла и идет в имя файла запроса.

    Разделители пути и недопустимые символы в нем сделали бы запись мимо каталога назначения.
    """
    safe = re.sub(r'[^\w-]', '_', name, flags=re.UNICODE).strip('._')
    if not safe:
        safe = 'query'
    safe = safe[:64]
    candidate = safe
    suffix = 2
    while candidate in external_queries:
        candidate = f'{safe}_{suffix}'
        suffix += 1
    return candidate


# --- Черновой JSON (общий блок, версия 2) ---
# Ширина строки, после которой контейнер разворачивается по элементу на строку.
DRAFT_JSON_WIDTH = 400


def to_inline_json(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        if not value:
            return '{}'
        parts = [json.dumps(str(k), ensure_ascii=False) + ': ' + to_inline_json(v)
                 for k, v in value.items()]
        return '{ ' + ', '.join(parts) + ' }'
    if isinstance(value, (list, tuple)):
        if not value:
            return '[]'
        return '[' + ', '.join(to_inline_json(v) for v in value) + ']'
    return json.dumps(str(value), ensure_ascii=False)


def to_draft_json(value, indent=''):
    """Описание пишется в том виде, в каком его удобно править руками: контейнер идет
    одной строкой, пока в нее помещается, и разворачивается, когда перестает."""
    rendered = to_inline_json(value)
    if (len(indent) + len(rendered) <= DRAFT_JSON_WIDTH
            or not isinstance(value, (dict, list, tuple)) or not value):
        return rendered
    inner = indent + '  '
    if isinstance(value, dict):
        parts = [inner + json.dumps(str(k), ensure_ascii=False) + ': ' + to_draft_json(v, inner)
                 for k, v in value.items()]
        return '{\n' + ',\n'.join(parts) + '\n' + indent + '}'
    parts = [inner + to_draft_json(v, inner) for v in value]
    return '[\n' + ',\n'.join(parts) + '\n' + indent + ']'
# --- Конец общего блока чернового JSON ---


external_queries = {}
query_file_prefix = ['']


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description='Decompile 1C DCS XML (DataCompositionSchema) to JSON DSL draft',
        allow_abbrev=False)
    # Имена параметров общие для семейства навыков по схемам компоновки и макетам;
    # прежние приняты как синонимы: по ним написаны вызовы в чужих сценариях.
    parser.add_argument('-TemplatePath', type=str, default=None)
    parser.add_argument('-OutputPath', type=str, default=None)
    parser.add_argument('-InputFile', type=str, default=None)
    parser.add_argument('-OutputFile', type=str, default=None)
    args = parser.parse_args()

    template_path = args.TemplatePath or args.InputFile
    if not template_path:
        print('Параметр -TemplatePath обязателен', file=sys.stderr)
        sys.exit(1)

    in_path = os.path.abspath(template_path)
    if not os.path.isfile(in_path):
        print('Файл не найден: ' + in_path, file=sys.stderr)
        sys.exit(1)

    load_user_style_presets(os.path.dirname(in_path))

    root = None
    try:
        for event, obj in ET.iterparse(in_path, events=('start-ns', 'start')):
            if event == 'start-ns':
                pfx, uri = obj
                if pfx not in ns_prefixes:
                    ns_prefixes[pfx] = uri
            elif root is None:
                root = obj
    except ET.ParseError as e:
        print('Ошибка разбора XML: ' + str(e), file=sys.stderr)
        sys.exit(1)

    if root is None or local(root.tag) != 'DataCompositionSchema':
        found = local(root.tag) if root is not None else '(пусто)'
        print('Корневой элемент не DataCompositionSchema: ' + found, file=sys.stderr)
        sys.exit(1)

    out_path = args.OutputPath or args.OutputFile
    if not out_path:
        base = os.path.splitext(in_path)[0]
        out_path = base + '.skd.json'
    out_path = os.path.abspath(out_path)
    # Имя внешнего файла запроса берется от имени описания: рядом с ним он и лежит.
    query_file_prefix[0] = os.path.splitext(os.path.basename(out_path))[0]

    root_todos = []

    def root_todo(msg):
        root_todos.append(msg)
        warnings_list.append(msg)

    result = {}

    sources = []
    for ds in kids(root, 'dataSource'):
        sources.append({
            'name': text_of(kid(ds, 'name')),
            'type': text_of(kid(ds, 'dataSourceType')).strip() or 'Local',
        })
    default_source = sources[0]['name'] if sources else DEFAULT_SOURCE_NAME
    is_default_sources = (len(sources) <= 1 and default_source == DEFAULT_SOURCE_NAME
                          and (not sources or sources[0]['type'] == 'Local'))
    if not is_default_sources:
        result['dataSources'] = sources

    data_sets = [build_data_set(ds, default_source) for ds in kids(root, 'dataSet')]
    if not data_sets:
        root_todo('в схеме нет ни одного dataSet - /skd-compile требует минимум один набор данных')
    result['dataSets'] = data_sets

    links = [build_link(l) for l in kids(root, 'dataSetLink')]
    if links:
        result['dataSetLinks'] = links
    calc = [build_calc(c) for c in kids(root, 'calculatedField')]
    if calc:
        result['calculatedFields'] = calc
    totals = [build_total(t) for t in kids(root, 'totalField')]
    if totals:
        result['totalFields'] = totals

    raw_params = [build_parameter(p) for p in kids(root, 'parameter')]
    raw_params = collapse_auto_dates(raw_params)
    params = [param_to_shorthand(p) for p in raw_params]
    if params:
        result['parameters'] = params

    templates = [build_template(t) for t in kids(root, 'template')]
    if templates:
        result['templates'] = templates

    for ft in kids(root, 'fieldTemplate'):
        fld = text_of(kid(ft, 'field'))
        root_todo('привязка макета к полю (fieldTemplate "' + fld + '") не поддержана нашим DSL')

    group_templates = []
    for gt in kids(root, 'groupHeaderTemplate'):
        group_templates.append(build_group_template(gt, 'GroupHeader'))
    for gt in kids(root, 'groupTemplate'):
        group_templates.append(build_group_template(gt, None))
    if group_templates:
        result['groupTemplates'] = group_templates

    variants = [build_variant(v) for v in kids(root, 'settingsVariant')]
    if variants and not (len(variants) == 1 and is_default_variant(variants[0])):
        result['settingsVariants'] = variants

    known_root = {'dataSource', 'dataSet', 'dataSetLink', 'calculatedField', 'totalField',
                  'parameter', 'template', 'fieldTemplate', 'groupHeaderTemplate',
                  'groupTemplate', 'settingsVariant'}
    seen_unknown = set()
    for c in root:
        ln = local(c.tag)
        if ln not in known_root and ln not in seen_unknown:
            seen_unknown.add(ln)
            root_todo('элемент схемы не поддержан: ' + ln)

    if dropped_setting_ids:
        root_todo('userSettingID у ' + str(dropped_setting_ids)
                  + ' элементов структуры отброшены (наш DSL их не выражает)')

    if root_todos:
        final = {'_todo': root_todos}
        final.update(result)
        result = final

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(to_draft_json(result))

    for query_name, query_text in external_queries.items():
        query_path = os.path.join(out_dir, query_file_prefix[0] + '-' + query_name + '.sql')
        with open(query_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(query_text)

    for w in warnings_list:
        print('TODO: ' + w, file=sys.stderr)

    print('OK  ' + out_path)
    print('    DataSets: %d  Links: %d  Calculated: %d  Totals: %d  Params: %d  Templates: %d  GroupTemplates: %d  Variants: %d  Todos: %d' % (
        len(data_sets), len(links), len(calc), len(totals), len(params),
        len(templates), len(group_templates), len(variants), len(warnings_list)))
    sys.exit(0)


if __name__ == '__main__':
    main()
