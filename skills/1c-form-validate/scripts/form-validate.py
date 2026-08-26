#!/usr/bin/env python3
# form-validate v1.4 — Validate 1C managed form
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import json
import os
import re
import sys
from lxml import etree

# Проверенный диапазон версий формата. Эталон - лестница версий в docs/1c-configuration-spec.md
# (§7.1); согласованность границ стережет tests/skills/check-format-versions.mjs. Сравнение
# числовое, поэтому промежуточная версия ведет себя предсказуемо.
FORMAT_VERIFIED_MIN = "2.17"
FORMAT_VERIFIED_MAX = "2.21"


def _format_version_rank(version):
    m = re.match(r'^(\d+)\.(\d+)$', version or '')
    return int(m.group(1)) * 100 + int(m.group(2)) if m else 0


def opaque_path(segment):
    """Путь, который платформа записала не именем реквизита формы, по реквизитам не проверяется."""
    if not segment:
        return True
    if re.match(r'^\d+$', segment):
        return True
    if re.match(r'^[\d/]+:[0-9a-fA-F-]+$', segment):
        return True
    if segment.startswith('~'):
        return True
    return segment == 'Items'


def format_version_known(version):
    rank = _format_version_rank(version)
    if rank == 0:
        return False
    return _format_version_rank(FORMAT_VERIFIED_MIN) <= rank <= _format_version_rank(FORMAT_VERIFIED_MAX)



F_NS = "http://v8.1c.ru/8.3/xcf/logform"
V8_NS = "http://v8.1c.ru/8.1/data/core"

XR_NS = "http://v8.1c.ru/8.3/xcf/readable"

NSMAP = {"f": F_NS, "v8": V8_NS, "xr": XR_NS}

KNOWN_INVALID_TYPES = {
    'FormDataStructure', 'FormDataCollection', 'FormDataTree',
    'FormDataTreeItem', 'FormDataCollectionItem',
    'FormGroup', 'FormField', 'FormButton', 'FormDecoration', 'FormTable',
}

VALID_CLOSED_TYPES = {
    'xs:boolean', 'xs:string', 'xs:decimal', 'xs:dateTime', 'xs:binary',
    'v8:FillChecking', 'v8:Null', 'v8:StandardPeriod', 'v8:StandardBeginningDate', 'v8:Type',
    'v8:TypeDescription', 'v8:UUID', 'v8:ValueListType', 'v8:ValueTable', 'v8:ValueTree',
    'v8:Universal', 'v8:FixedArray', 'v8:FixedStructure',
    'v8ui:Color', 'v8ui:Font', 'v8ui:FormattedString', 'v8ui:HorizontalAlign',
    'v8ui:Picture', 'v8ui:SizeChangeMode', 'v8ui:VerticalAlign',
    'dcsset:DataCompositionComparisonType', 'dcsset:DataCompositionFieldPlacement',
    'dcsset:Filter', 'dcsset:SettingsComposer', 'dcsset:DataCompositionSettings',
    'dcssch:DataCompositionSchema',
    'dcscor:DataCompositionComparisonType', 'dcscor:DataCompositionGroupType',
    'dcscor:DataCompositionPeriodAdditionType', 'dcscor:DataCompositionSortDirection', 'dcscor:Field',
    'ent:AccountType', 'ent:AccumulationRecordType', 'ent:AccountingRecordType',
}

VALID_CFG_PREFIXES = {
    'AccountingRegisterRecordSet', 'AccumulationRegisterRecordSet',
    'BusinessProcessObject', 'BusinessProcessRef',
    'CatalogObject', 'CatalogRef',
    'ChartOfAccountsObject', 'ChartOfAccountsRef',
    'ChartOfCalculationTypesObject', 'ChartOfCalculationTypesRef',
    'ChartOfCharacteristicTypesObject', 'ChartOfCharacteristicTypesRef',
    'ConstantsSet', 'DataProcessorObject', 'DocumentObject', 'DocumentRef',
    'DynamicList', 'EnumRef', 'ExchangePlanObject', 'ExchangePlanRef',
    'ExternalDataProcessorObject', 'ExternalReportObject',
    'InformationRegisterRecordManager', 'InformationRegisterRecordSet',
    'ReportObject', 'TaskObject', 'TaskRef',
}


def localname(el):
    return etree.QName(el.tag).localname


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate 1C managed form", allow_abbrev=False)
    parser.add_argument("-FormPath", required=True)
    parser.add_argument("-Detailed", action="store_true")
    parser.add_argument("-MaxErrors", type=int, default=30)
    parser.add_argument("-IndexPath", default="")
    args = parser.parse_args()

    form_path = args.FormPath
    detailed = args.Detailed
    max_errors = args.MaxErrors
    index_path = args.IndexPath

    if not os.path.isabs(form_path):
        form_path = os.path.join(os.getcwd(), form_path)

    # A: Directory → Ext/Form.xml
    if os.path.isdir(form_path):
        form_path = os.path.join(form_path, 'Ext', 'Form.xml')
    # B1: Missing Ext/ (e.g. Forms/Форма/Form.xml → Forms/Форма/Ext/Form.xml)
    if not os.path.exists(form_path):
        fn = os.path.basename(form_path)
        if fn == 'Form.xml':
            c = os.path.join(os.path.dirname(form_path), 'Ext', fn)
            if os.path.exists(c):
                form_path = c
    # B2: Descriptor (Forms/Форма.xml → Forms/Форма/Ext/Form.xml)
    if not os.path.exists(form_path) and form_path.endswith('.xml'):
        stem = os.path.splitext(os.path.basename(form_path))[0]
        parent = os.path.dirname(form_path)
        c = os.path.join(parent, stem, 'Ext', 'Form.xml')
        if os.path.exists(c):
            form_path = c

    if not os.path.isfile(form_path):
        print(f"File not found: {form_path}", file=sys.stderr)
        sys.exit(1)

    # --- Load XML ---
    try:
        xml_parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(form_path, xml_parser)
    except Exception as e:
        print(f"[ERROR] XML parse error: {e}")
        print()
        print("---")
        print("Errors: 1, Warnings: 0")
        sys.exit(1)

    root = tree.getroot()

    # Detect context: config vs EPF/ERF
    is_config_context = False
    walk_dir = os.path.dirname(os.path.abspath(form_path))
    for _ in range(15):
        parent = os.path.dirname(walk_dir)
        if parent == walk_dir:
            break
        # Описание внешней обработки лежит рядом с ее каталогом и встречается раньше, чем
        # Configuration.xml. Без этой проверки автономная обработка, распакованная внутрь
        # каталога конфигурации, принималась за объект конфигурации.
        owner_xml = os.path.join(parent, os.path.basename(walk_dir) + '.xml')
        if os.path.isfile(owner_xml):
            with open(owner_xml, 'r', encoding='utf-8-sig', errors='replace') as fh:
                head = fh.read(2000)
            if re.search(r'<(ExternalDataProcessor|ExternalReport)\s', head):
                break
        if os.path.isfile(os.path.join(walk_dir, 'Configuration.xml')):
            is_config_context = True
            break
        walk_dir = parent

    errors = 0
    warnings = 0
    ok_count = 0
    stopped = False
    output_lines = []

    def report_ok(msg):
        nonlocal ok_count
        ok_count += 1
        if detailed:
            output_lines.append(f"[OK]    {msg}")

    def report_error(msg):
        nonlocal errors, stopped
        errors += 1
        output_lines.append(f"[ERROR] {msg}")
        if errors >= max_errors:
            stopped = True

    def report_warn(msg):
        nonlocal warnings
        warnings += 1
        output_lines.append(f"[WARN]  {msg}")

    # --- Form name from path ---
    form_name = os.path.splitext(os.path.basename(form_path))[0]
    parent_dir = os.path.dirname(form_path)
    if parent_dir:
        ext_dir = os.path.basename(parent_dir)
        if ext_dir == "Ext":
            form_dir = os.path.dirname(parent_dir)
            if form_dir:
                form_name = os.path.basename(form_dir)

    output_lines.append(f"=== Validation: Form.{form_name} ===")
    output_lines.append("")

    # Early BaseForm detection
    has_base_form = root.find(f"{{{F_NS}}}BaseForm") is not None

    # --- Check 1: Root element and version ---
    if localname(root) != "Form":
        report_error(f"Root element is '{localname(root)}', expected 'Form'")
    else:
        version = root.get("version", "")
        if format_version_known(version):
            report_ok(f"Root element: Form version={version}")
        elif version:
            # Версия вне проверенного диапазона - это непокрытие проверками, а не дефект файла;
            # сторона отклонения важна: ниже диапазона формат старый, выше - еще не замерен.
            rank = _format_version_rank(version)
            if rank == 0:
                report_warn(f"Form version='{version}' is malformed (expected a number like 2.21)")
            elif rank < _format_version_rank(FORMAT_VERIFIED_MIN):
                report_warn(f"Format version '{version}' is below the tested range "
                            f"{FORMAT_VERIFIED_MIN}-{FORMAT_VERIFIED_MAX}")
            else:
                report_warn(f"Format version '{version}' is above the tested range "
                            f"{FORMAT_VERIFIED_MIN}-{FORMAT_VERIFIED_MAX}")
        else:
            report_warn("Form version attribute missing")

    # --- Check 2: AutoCommandBar ---
    if not stopped:
        acb = root.find(f"{{{F_NS}}}AutoCommandBar")
        if acb is not None:
            acb_name = acb.get("name", "")
            acb_id = acb.get("id", "")
            if acb_id == "-1":
                report_ok(f"AutoCommandBar: name='{acb_name}', id={acb_id}")
            else:
                report_error(f"AutoCommandBar id='{acb_id}', expected '-1'")
        else:
            report_error("AutoCommandBar element missing")

    # --- Collect all elements with IDs ---
    element_ids = {}  # id -> name
    all_elements = []  # list of dicts {Name, Tag, Id, ParentName, Node}

    def collect_elements(node, parent_name):
        nonlocal stopped
        for child in node:
            if not isinstance(child.tag, str):
                continue

            name = child.get("name", "")
            eid = child.get("id", "")

            if name and eid:
                tag = localname(child)

                all_elements.append({
                    "Name": name,
                    "Tag": tag,
                    "Id": eid,
                    "ParentName": parent_name,
                    "Node": child,
                })

                if eid != "-1":
                    if eid in element_ids:
                        report_error(f"Duplicate element id={eid}: '{name}' and '{element_ids[eid]}'")
                    else:
                        element_ids[eid] = name

                child_items = child.find(f"{{{F_NS}}}ChildItems")
                if child_items is not None:
                    collect_elements(child_items, name)

    child_items_root = root.find(f"{{{F_NS}}}ChildItems")
    if child_items_root is not None:
        collect_elements(child_items_root, "(root)")

    acb = root.find(f"{{{F_NS}}}AutoCommandBar")
    if acb is not None:
        acb_children = acb.find(f"{{{F_NS}}}ChildItems")
        if acb_children is not None:
            collect_elements(acb_children, "\u0424\u043e\u0440\u043c\u0430\u041a\u043e\u043c\u0430\u043d\u0434\u043d\u0430\u044f\u041f\u0430\u043d\u0435\u043b\u044c")

    # Два элемента с одним именем платформа принимает, но второй из кода недостижим.
    name_counts = {}
    for el in all_elements:
        if not el["Name"]:
            continue
        name_counts.setdefault(el["Name"].lower(), []).append(el["Name"])
    for names in name_counts.values():
        if len(names) > 1:
            report_error(f"Duplicate element name: '{names[0]}' ({len(names)} elements)")
    if all(len(v) == 1 for v in name_counts.values()):
        report_ok(f"Unique element names: {len(all_elements)} elements")

    # --- Check 3: Unique element IDs ---
    if not stopped:
        # Duplicates already reported during collection
        dup_count = 0
        id_counts = {}
        for el in all_elements:
            eid = el["Id"]
            if eid == "-1":
                continue
            id_counts[eid] = id_counts.get(eid, 0) + 1
        dup_count = sum(1 for v in id_counts.values() if v > 1)
        if dup_count == 0:
            report_ok(f"Unique element IDs: {len(element_ids)} elements")

    # --- Collect attributes (separate ID pool) ---
    attr_map = {}   # name -> node
    attr_ids = {}   # id -> name

    attr_nodes_parent = root.find(f"{{{F_NS}}}Attributes")
    attr_nodes = []
    if attr_nodes_parent is not None:
        attr_nodes = attr_nodes_parent.findall(f"{{{F_NS}}}Attribute")

    for attr in attr_nodes:
        attr_name = attr.get("name", "")
        attr_id = attr.get("id", "")
        if attr_name:
            attr_map[attr_name] = attr
        if attr_id:
            if attr_id in attr_ids:
                report_error(f"Duplicate attribute id={attr_id}: '{attr_name}' and '{attr_ids[attr_id]}'")
            else:
                attr_ids[attr_id] = attr_name

        # Column IDs uniqueness within parent
        col_ids = {}
        columns = attr.find(f"{{{F_NS}}}Columns")
        if columns is not None:
            for col in columns.findall(f"{{{F_NS}}}Column"):
                col_id = col.get("id", "")
                col_name = col.get("name", "")
                if col_id:
                    if col_id in col_ids:
                        report_error(f"Duplicate column id={col_id} in '{attr_name}': '{col_name}' and '{col_ids[col_id]}'")
                    else:
                        col_ids[col_id] = col_name

    if not stopped:
        if attr_ids:
            report_ok(f"Unique attribute IDs: {len(attr_ids)} entries")

    # --- Collect commands (separate ID pool) ---
    cmd_map = {}   # name -> node
    cmd_ids = {}   # id -> name

    cmd_nodes_parent = root.find(f"{{{F_NS}}}Commands")
    cmd_nodes = []
    if cmd_nodes_parent is not None:
        cmd_nodes = cmd_nodes_parent.findall(f"{{{F_NS}}}Command")

    for cmd in cmd_nodes:
        cmd_name = cmd.get("name", "")
        cmd_id = cmd.get("id", "")
        if cmd_name:
            cmd_map[cmd_name] = cmd
        if cmd_id:
            if cmd_id in cmd_ids:
                report_error(f"Duplicate command id={cmd_id}: '{cmd_name}' and '{cmd_ids[cmd_id]}'")
            else:
                cmd_ids[cmd_id] = cmd_name

    if not stopped:
        if cmd_ids:
            report_ok(f"Unique command IDs: {len(cmd_ids)} entries")

    # --- Check 4: Companion elements ---
    companion_rules = {
        "InputField": ["ContextMenu", "ExtendedTooltip"],
        "CheckBoxField": ["ContextMenu", "ExtendedTooltip"],
        "LabelDecoration": ["ContextMenu", "ExtendedTooltip"],
        "LabelField": ["ContextMenu", "ExtendedTooltip"],
        "PictureDecoration": ["ContextMenu", "ExtendedTooltip"],
        "PictureField": ["ContextMenu", "ExtendedTooltip"],
        "CalendarField": ["ContextMenu", "ExtendedTooltip"],
        "UsualGroup": ["ExtendedTooltip"],
        "Pages": ["ExtendedTooltip"],
        "Page": ["ExtendedTooltip"],
        "Button": ["ExtendedTooltip"],
        "Table": ["ContextMenu", "AutoCommandBar", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"],
    }

    if not stopped:
        companion_errors = 0
        companion_checked = 0

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag not in companion_rules:
                continue

            required = companion_rules[tag]
            companion_checked += 1

            for comp_tag in required:
                comp_node = node.find(f"{{{F_NS}}}{comp_tag}")
                if comp_node is None:
                    report_error(f"[{tag}] '{el_name}': missing companion <{comp_tag}>")
                    companion_errors += 1

        if companion_errors == 0 and companion_checked > 0:
            report_ok(f"Companion elements: {companion_checked} elements checked")

    # --- Check 5: DataPath -> Attribute references ---
    if not stopped:
        path_errors = 0
        path_checked = 0
        path_base_skipped = 0

        skip_tags = {"ContextMenu", "ExtendedTooltip", "AutoCommandBar", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"}

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag in skip_tags:
                continue

            if has_base_form and el["Id"]:
                try:
                    if int(el["Id"]) < 1000000:
                        path_base_skipped += 1
                        continue
                except (ValueError, TypeError):
                    pass

            for bind_tag in ("MultipleValueDataPath", "MultipleValuePresentDataPath"):
                bind_node = node.find(f"{{{F_NS}}}{bind_tag}")
                if bind_node is None:
                    continue
                bind_path = (bind_node.text or "").strip()
                if not bind_path:
                    continue
                bind_root = re.sub(r'\[\d+\]', '', bind_path).split(".")[0]
                if not opaque_path(bind_root) and bind_root not in attr_map:
                    report_error(f"[{tag}] '{el_name}': {bind_tag}='{bind_path}' "
                                 f"— attribute '{bind_root}' not found")
                    path_errors += 1

            dp_node = node.find(f"{{{F_NS}}}DataPath")
            if dp_node is None:
                continue

            data_path = (dp_node.text or "").strip()
            if not data_path:
                continue

            path_checked += 1

            clean_path = re.sub(r'\[\d+\]', '', data_path)
            segments = clean_path.split(".")
            root_attr = segments[0]

            if not opaque_path(root_attr) and root_attr not in attr_map:
                report_error(f"[{tag}] '{el_name}': DataPath='{data_path}' \u2014 attribute '{root_attr}' not found")
                path_errors += 1

        path_msg = ""
        if path_checked > 0:
            path_msg = f"{path_checked} paths checked"
        if path_base_skipped > 0:
            skip_note = f"{path_base_skipped} base skipped"
            path_msg = f"{path_msg}, {skip_note}" if path_msg else skip_note
        if path_errors == 0 and path_msg:
            report_ok(f"DataPath references: {path_msg}")

    # --- Check 5a: Пути ссылок параметров выбора ---
    # В заимствованной форме собственные реквизиты объявляет само расширение. Путь вида
    # Объект.X платформа свяжет только при объявленном основном реквизите.
    if not stopped:
        link_errors = 0
        link_checked = 0
        child_items_node = root.find(f"{{{F_NS}}}ChildItems")
        if child_items_node is not None:
            for link_path in child_items_node.iter(f"{{{XR_NS}}}DataPath"):
                value = (link_path.text or "").strip()
                if not value:
                    continue
                link_root = re.sub(r'\[\d+\]', '', value).split(".")[0]
                if opaque_path(link_root):
                    continue
                link_checked += 1
                if link_root not in attr_map:
                    report_error(f"Choice parameter link: DataPath='{value}' "
                                 f"— attribute '{link_root}' not found")
                    link_errors += 1
        if link_errors == 0 and link_checked > 0:
            report_ok(f"Choice parameter links: {link_checked} paths checked")

    # --- Check 6: Button command references ---
    if not stopped:
        cmd_errors = 0
        cmd_checked = 0

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag != "Button":
                continue

            cmd_node = node.find(f"{{{F_NS}}}CommandName")
            if cmd_node is None:
                continue

            cmd_ref = (cmd_node.text or "").strip()
            if not cmd_ref:
                continue

            m = re.match(r'^Form\.Command\.(.+)$', cmd_ref)
            if m:
                cmd_name_ref = m.group(1)
                cmd_checked += 1
                if cmd_name_ref not in cmd_map:
                    report_error(f"[Button] '{el_name}': CommandName='{cmd_ref}' \u2014 command '{cmd_name_ref}' not found in Commands")
                    cmd_errors += 1

        if cmd_errors == 0 and cmd_checked > 0:
            report_ok(f"Command references: {cmd_checked} buttons checked")

    # --- Check 7: Events have handler names ---
    if not stopped:
        event_errors = 0
        event_checked = 0

        # Form-level events
        form_events = root.find(f"{{{F_NS}}}Events")
        if form_events is not None:
            for evt in form_events.findall(f"{{{F_NS}}}Event"):
                evt_name = evt.get("name", "")
                handler = (evt.text or "").strip()
                event_checked += 1
                if not handler:
                    report_error(f"Form event '{evt_name}': empty handler name")
                    event_errors += 1

        # Element-level events
        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            events_node = node.find(f"{{{F_NS}}}Events")
            if events_node is None:
                continue

            for evt in events_node.findall(f"{{{F_NS}}}Event"):
                evt_name = evt.get("name", "")
                handler = (evt.text or "").strip()
                event_checked += 1
                if not handler:
                    report_error(f"[{tag}] '{el_name}' event '{evt_name}': empty handler name")
                    event_errors += 1

        if event_errors == 0 and event_checked > 0:
            report_ok(f"Event handlers: {event_checked} events checked")

    # --- Check 8: Command actions ---
    if not stopped:
        action_errors = 0
        action_missing = 0
        action_checked = 0

        for cmd in cmd_nodes:
            if stopped:
                break
            cmd_name = cmd.get("name", "")
            action_node = cmd.find(f"{{{F_NS}}}Action")
            action_checked += 1
            if action_node is None or not (action_node.text or "").strip():
                report_warn(f"Command '{cmd_name}': no Action declared "
                            f"(handler may be assigned at runtime)")
                action_missing += 1

        if action_errors == 0 and action_missing == 0 and action_checked > 0:
            report_ok(f"Command actions: {action_checked} commands checked")

    # --- Check 9: MainAttribute count ---
    if not stopped:
        main_count = 0
        for attr in attr_nodes:
            main_node = attr.find(f"{{{F_NS}}}MainAttribute")
            if main_node is not None and (main_node.text or "") == "true":
                main_count += 1

        if main_count <= 1:
            main_info = "1 main attribute" if main_count == 1 else "no main attribute"
            report_ok(f"MainAttribute: {main_info}")
        else:
            report_error(f"Multiple MainAttribute=true ({main_count} found, expected 0 or 1)")

    # --- Check 10: Title must be multilingual XML ---
    if not stopped:
        title_node = root.find(f"{{{F_NS}}}Title")
        if title_node is not None:
            v8_items = title_node.findall(f"{{{V8_NS}}}item")
            if len(v8_items) == 0 and (title_node.text or "").strip():
                report_error(f"Form Title is plain text ('{(title_node.text or '').strip()}') \u2014 must be multilingual XML (<v8:item>). Use top-level 'title' key in form-compile DSL.")
            else:
                report_ok("Title: multilingual XML")

    # --- Check 11: Extension-specific validations ---
    base_form_node = root.find(f"{{{F_NS}}}BaseForm")
    is_extension = base_form_node is not None

    if not stopped and is_extension:
        # 11a. BaseForm version
        bf_version = base_form_node.get("version", "")
        if bf_version:
            report_ok(f"BaseForm: version={bf_version}")
        else:
            report_warn("BaseForm: version attribute missing")

        # 11b. callType values validation
        valid_call_types = {"Before", "After", "Override"}
        ct_errors = 0
        ct_checked = 0

        form_events_node = root.find(f"{{{F_NS}}}Events")
        if form_events_node is not None:
            for evt in form_events_node.findall(f"{{{F_NS}}}Event"):
                ct = evt.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"Form event '{evt.get('name', '')}': invalid callType='{ct}' (expected: Before, After, Override)")
                        ct_errors += 1

        for el in all_elements:
            if stopped:
                break
            events_node = el["Node"].find(f"{{{F_NS}}}Events")
            if events_node is None:
                continue
            for evt in events_node.findall(f"{{{F_NS}}}Event"):
                ct = evt.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"[{el['Tag']}] '{el['Name']}' event '{evt.get('name', '')}': invalid callType='{ct}'")
                        ct_errors += 1

        for cmd in cmd_nodes:
            if stopped:
                break
            cmd_name = cmd.get("name", "")
            for action in cmd.findall(f"{{{F_NS}}}Action"):
                ct = action.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"Command '{cmd_name}' Action: invalid callType='{ct}'")
                        ct_errors += 1

        if not stopped and ct_errors == 0 and ct_checked > 0:
            report_ok(f"callType values: {ct_checked} checked")

        # 11c. Extension ID ranges
        base_attr_names = set()
        base_cmd_names = set()

        bf_attrs = base_form_node.find(f"{{{F_NS}}}Attributes")
        if bf_attrs is not None:
            for b_attr in bf_attrs.findall(f"{{{F_NS}}}Attribute"):
                ba_name = b_attr.get("name", "")
                if ba_name:
                    base_attr_names.add(ba_name)

        bf_cmds = base_form_node.find(f"{{{F_NS}}}Commands")
        if bf_cmds is not None:
            for b_cmd in bf_cmds.findall(f"{{{F_NS}}}Command"):
                bc_name = b_cmd.get("name", "")
                if bc_name:
                    base_cmd_names.add(bc_name)

        id_warn_count = 0
        for attr in attr_nodes:
            a_name = attr.get("name", "")
            a_id = attr.get("id", "")
            if a_name and a_name not in base_attr_names and a_id:
                try:
                    int_id = int(a_id)
                    if int_id < 1000000:
                        report_warn(f"Attribute '{a_name}' (id={a_id}): extension-added attribute has id < 1000000")
                        id_warn_count += 1
                except (ValueError, TypeError):
                    pass

        for cmd in cmd_nodes:
            c_name = cmd.get("name", "")
            c_id = cmd.get("id", "")
            if c_name and c_name not in base_cmd_names and c_id:
                try:
                    int_id = int(c_id)
                    if int_id < 1000000:
                        report_warn(f"Command '{c_name}' (id={c_id}): extension-added command has id < 1000000")
                        id_warn_count += 1
                except (ValueError, TypeError):
                    pass

        if not stopped and id_warn_count == 0:
            ext_attr_count = sum(1 for a in attr_nodes if a.get("name", "") not in base_attr_names)
            ext_cmd_count = sum(1 for c in cmd_nodes if c.get("name", "") not in base_cmd_names)
            if (ext_attr_count + ext_cmd_count) > 0:
                report_ok(f"Extension ID ranges: {ext_attr_count} attr(s), {ext_cmd_count} cmd(s) \u2014 all >= 1000000")

    # Check callType without BaseForm
    if not stopped and not is_extension:
        call_type_without_base = False
        fe_node = root.find(f"{{{F_NS}}}Events")
        if fe_node is not None:
            for evt in fe_node.findall(f"{{{F_NS}}}Event"):
                if evt.get("callType"):
                    call_type_without_base = True
                    break
        if not call_type_without_base:
            for cmd in cmd_nodes:
                for action in cmd.findall(f"{{{F_NS}}}Action"):
                    if action.get("callType"):
                        call_type_without_base = True
                        break
                if call_type_without_base:
                    break
        if call_type_without_base:
            report_warn("callType attributes found but no BaseForm \u2014 possible incorrect structure")

    # --- Check 12: Type validation ---
    if not stopped:
        type_nodes = root.xpath('//v8:Type', namespaces={'v8': V8_NS})
        type_error_count = 0
        type_warn_count = 0
        type_count = len(type_nodes)

        for tn in type_nodes:
            if stopped:
                break
            tv = (tn.text or "").strip()
            if not tv:
                continue

            used_prefix = re.match(r'^([A-Za-z][\w.-]*):', tv)
            if used_prefix and used_prefix.group(1) not in (root.nsmap or {}):
                report_error(f"12. Type '{tv}': prefix '{used_prefix.group(1)}:' "
                             f"is not declared in the form header")
                type_error_count += 1
            elif tv in KNOWN_INVALID_TYPES:
                report_error(f'12. Type "{tv}": invalid runtime/UI type (not valid in XDTO schema)')
                type_error_count += 1
            elif tv in VALID_CLOSED_TYPES:
                pass  # OK
            elif tv.startswith("cfg:"):
                suffix = tv[4:]  # after "cfg:"
                prefix = suffix.split(".")[0]
                if prefix in VALID_CFG_PREFIXES or suffix == "DynamicList":
                    # ExternalDataProcessorObject/ExternalReportObject valid only in EPF/ERF context
                    if is_config_context and prefix in ('ExternalDataProcessorObject', 'ExternalReportObject'):
                        report_error(f'12. Type "{tv}": External* type in configuration context (use DataProcessorObject/ReportObject instead)')
                        type_invalid += 1
                else:
                    report_warn(f'12. Type "{tv}": unrecognized cfg prefix')
                    type_warn_count += 1
            elif ":" in tv:
                pass  # unknown namespace, pass through
            else:
                report_warn(f'12. Type "{tv}": bare type without namespace prefix')
                type_warn_count += 1

        if type_error_count == 0 and type_warn_count == 0:
            if type_count > 0:
                report_ok(f'12. Types: {type_count} values, all valid')
            else:
                report_ok('12. Types: no type values to check')

    # --- Check 13: DataPath resolves against the owner object ---
    # Проверка 5 убеждается, что корень пути - реквизит формы. Дальше путь не разбирался вовсе:
    # Объект.ИНН при отсутствующем ИНН у справочника проходил молча. Здесь берется тип реквизита
    # формы (cfg:CatalogObject.Контрагенты), по нему в индексе находится объект и сверяются
    # остальные части пути.
    if not stopped:
        index_objects = None
        index_is_extension = False
        if index_path:
            try:
                with open(index_path, "r", encoding="utf-8") as fh:
                    index_data = json.load(fh)
                if index_data.get("format") != 1:
                    report_warn("13. Index format %s is not supported, owner check skipped"
                                % index_data.get("format"))
                else:
                    index_objects = index_data.get("objects") or {}
                    index_is_extension = index_data.get("kind") == "extension"
            except Exception as exc:
                report_warn("13. Index could not be read (%s), owner check skipped" % exc)

        if index_objects is None:
            pass  # Индекса не дали - проверка не выполняется, и это нормальный режим работы.
        else:
            kinds = sorted(index_objects.keys())
            kind_names = set()
            for key in kinds:
                kind_names.add(key.split(".", 1)[0])

            def resolve_owner(type_value):
                """cfg:CatalogObject.Контрагенты -> ключ объекта в индексе."""
                v = type_value.strip()
                colon = v.find(":")
                if colon >= 0:
                    v = v[colon + 1:]
                dot = v.find(".")
                if dot <= 0:
                    return None
                prefix, name = v[:dot], v[dot + 1:]
                # Самое длинное совпадение: DocumentJournalList должен дать DocumentJournal,
                # а не Document.
                best = None
                for kind in kind_names:
                    if prefix.startswith(kind) and (best is None or len(kind) > len(best)):
                        best = kind
                if best is None:
                    return None
                key = best + "." + name
                return key if key in index_objects else None

            owner_of = {}
            for attr_name, attr_node in attr_map.items():
                type_holder = attr_node.find(f"{{{F_NS}}}Type")
                if type_holder is None:
                    continue
                type_values = [(tn.text or "").strip() for tn in type_holder.findall(f"{{{V8_NS}}}Type")]
                type_values = [tv for tv in type_values if tv]
                # Составной тип разрешать некуда: путь может вести в любой из них.
                if len(type_values) != 1:
                    continue
                owner = resolve_owner(type_values[0])
                if owner:
                    owner_of[attr_name] = owner

            path_skip_tags = {"ContextMenu", "ExtendedTooltip", "AutoCommandBar",
                              "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"}
            owner_checked = 0
            owner_bad = 0
            owner_skipped_no_std = 0
            reported_paths = set()

            for el in all_elements:
                if stopped:
                    break
                if el["Tag"] in path_skip_tags:
                    continue
                node = el["Node"]
                dp_node = node.find(f"{{{F_NS}}}DataPath")
                if dp_node is None:
                    continue
                data_path = (dp_node.text or "").strip()
                if not data_path or data_path in reported_paths:
                    continue
                segments = re.sub(r'\[\d+\]', '', data_path).split(".")
                if len(segments) < 2:
                    continue
                owner_key = owner_of.get(segments[0])
                if owner_key is None:
                    continue
                obj = index_objects[owner_key]
                # Объект без блока StandardAttributes проверять нельзя: любой Объект.Code
                # был бы объявлен несуществующим. Такие пропускаем целиком.
                std_attrs = obj.get("standardAttributes")
                if not std_attrs:
                    owner_skipped_no_std += 1
                    continue

                tabular = obj.get("tabularSections") or {}
                std_tabular = obj.get("standardTabularSections") or {}
                own_fields = set(obj.get("attributes") or {})
                own_fields |= set(std_attrs)
                own_fields |= set(obj.get("dimensions") or {})
                own_fields |= set(obj.get("resources") or {})
                own_fields |= set(obj.get("addressingAttributes") or {})
                own_fields |= set(obj.get("accountingFlags") or {})
                own_fields |= set(tabular)
                own_fields |= set(std_tabular)

                owner_checked += 1
                reported_paths.add(data_path)
                second = segments[1]
                if second not in own_fields:
                    owner_bad += 1
                    if index_is_extension:
                        report_warn("13. DataPath='%s': у %s нет '%s' в этой выгрузке - "
                                    "ожидается в основной конфигурации" % (data_path, owner_key, second))
                    else:
                        report_warn("13. DataPath='%s': у %s нет реквизита или табличной части '%s'"
                                    % (data_path, owner_key, second))
                    continue
                if len(segments) < 3:
                    continue
                third = segments[2]
                if second in tabular:
                    ts = tabular[second]
                    ts_fields = set(ts.get("attributes") or {}) | set(ts.get("standardAttributes") or [])
                elif second in std_tabular:
                    ts_fields = set(std_tabular[second] or [])
                    # Признаки учета по субконто живут в стандартной ТЧ плана счетов.
                    if second == "ExtDimensionTypes":
                        ts_fields |= set(obj.get("extDimensionAccountingFlags") or {})
                else:
                    continue
                if third not in ts_fields:
                    owner_bad += 1
                    if index_is_extension:
                        report_warn("13. DataPath='%s': у табличной части '%s' нет '%s' в этой "
                                    "выгрузке - ожидается в основной конфигурации"
                                    % (data_path, second, third))
                    else:
                        report_warn("13. DataPath='%s': у табличной части '%s' нет реквизита '%s'"
                                    % (data_path, second, third))

            if owner_bad == 0:
                note = "%d paths resolved against owner objects" % owner_checked
                if owner_skipped_no_std:
                    note += ", %d skipped (owner has no StandardAttributes)" % owner_skipped_no_std
                if owner_checked or owner_skipped_no_std:
                    report_ok("13. Owner object: " + note)
                else:
                    report_ok("13. Owner object: no paths bound to configuration objects")

    # --- Finalize ---
    checks = ok_count + errors + warnings
    if errors == 0 and warnings == 0 and not detailed:
        result = f"=== Validation OK: Form.{form_name} ({checks} checks) ==="
    else:
        output_lines.append("")
        output_lines.append(f"=== Result: {errors} errors, {warnings} warnings ({checks} checks) ===")
        result = "\n".join(output_lines)

    print(result)

    if errors > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
