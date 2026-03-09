#!/usr/bin/env python3
# cf-edit v1.0 — Edit 1C configuration root (Configuration.xml)
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import json
import os
import subprocess
import sys
from html import escape as html_escape
from lxml import etree

MD_NS = "http://v8.1c.ru/8.3/MDClasses"
XR_NS = "http://v8.1c.ru/8.3/xcf/readable"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
V8_NS = "http://v8.1c.ru/8.1/data/core"
XS_NS = "http://www.w3.org/2001/XMLSchema"

# Canonical type order for ChildObjects (44 types)
TYPE_ORDER = [
    "Language", "Subsystem", "StyleItem", "Style",
    "CommonPicture", "SessionParameter", "Role", "CommonTemplate",
    "FilterCriterion", "CommonModule", "CommonAttribute", "ExchangePlan",
    "XDTOPackage", "WebService", "HTTPService", "WSReference",
    "EventSubscription", "ScheduledJob", "SettingsStorage", "FunctionalOption",
    "FunctionalOptionsParameter", "DefinedType", "CommonCommand", "CommandGroup",
    "Constant", "CommonForm", "Catalog", "Document",
    "DocumentNumerator", "Sequence", "DocumentJournal", "Enum",
    "Report", "DataProcessor", "InformationRegister", "AccumulationRegister",
    "ChartOfCharacteristicTypes", "ChartOfAccounts", "AccountingRegister",
    "ChartOfCalculationTypes", "CalculationRegister",
    "BusinessProcess", "Task", "IntegrationService",
]

ML_PROPS = ["Synonym", "BriefInformation", "DetailedInformation", "Copyright", "VendorInformationAddress", "ConfigurationInformationAddress"]
SCALAR_PROPS = ["Name", "Version", "Vendor", "Comment", "NamePrefix", "UpdateCatalogAddress"]
REF_PROPS = ["DefaultLanguage"]


def localname(el):
    return etree.QName(el.tag).localname


def info(msg):
    print(f"[INFO] {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def get_child_indent(container):
    if container.text and "\n" in container.text:
        after_nl = container.text.rsplit("\n", 1)[-1]
        if after_nl and not after_nl.strip():
            return after_nl
    for child in container:
        if child.tail and "\n" in child.tail:
            after_nl = child.tail.rsplit("\n", 1)[-1]
            if after_nl and not after_nl.strip():
                return after_nl
    depth = 0
    current = container
    while current is not None:
        depth += 1
        current = current.getparent()
    return "\t" * depth


def insert_before_closing(container, new_el, child_indent):
    children = list(container)
    if len(children) == 0:
        parent_indent = child_indent[:-1] if len(child_indent) > 0 else ""
        container.text = "\r\n" + child_indent
        new_el.tail = "\r\n" + parent_indent
        container.append(new_el)
    else:
        last = children[-1]
        new_el.tail = last.tail
        last.tail = "\r\n" + child_indent
        container.append(new_el)


def insert_before_ref(container, new_el, ref_el, child_indent):
    """Insert new_el before ref_el inside container."""
    idx = list(container).index(ref_el)
    prev = ref_el.getprevious()
    if prev is not None:
        new_el.tail = prev.tail
        prev.tail = "\r\n" + child_indent
    else:
        new_el.tail = container.text
        container.text = "\r\n" + child_indent
    container.insert(idx, new_el)


def remove_with_indent(el):
    parent = el.getparent()
    prev = el.getprevious()
    if prev is not None:
        if el.tail:
            prev.tail = el.tail
    else:
        if el.tail:
            parent.text = el.tail
    parent.remove(el)


def expand_self_closing(container, parent_indent):
    if len(container) == 0 and not (container.text and container.text.strip()):
        container.text = "\r\n" + parent_indent


def import_fragment(xml_string):
    wrapper = (
        f'<_W xmlns="{MD_NS}" xmlns:xsi="{XSI_NS}" xmlns:v8="{V8_NS}" '
        f'xmlns:xr="{XR_NS}" xmlns:xs="{XS_NS}">{xml_string}</_W>'
    )
    frag = etree.fromstring(wrapper.encode("utf-8"))
    return list(frag)


def parse_batch_value(val):
    items = []
    for part in val.split(";;"):
        trimmed = part.strip()
        if trimmed:
            items.append(trimmed)
    return items


def save_xml_bom(tree, path):
    xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    xml_bytes = xml_bytes.replace(b"encoding='UTF-8'", b'encoding="UTF-8"')
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(xml_bytes)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Edit 1C configuration root (Configuration.xml)", allow_abbrev=False)
    parser.add_argument("-ConfigPath", required=True)
    parser.add_argument("-DefinitionFile", default=None)
    parser.add_argument("-Operation", default=None, choices=["modify-property", "add-childObject", "remove-childObject", "add-defaultRole", "remove-defaultRole", "set-defaultRoles"])
    parser.add_argument("-Value", default=None)
    parser.add_argument("-NoValidate", action="store_true")
    args = parser.parse_args()

    if args.DefinitionFile and args.Operation:
        print("Cannot use both -DefinitionFile and -Operation", file=sys.stderr)
        sys.exit(1)
    if not args.DefinitionFile and not args.Operation:
        print("Either -DefinitionFile or -Operation is required", file=sys.stderr)
        sys.exit(1)

    config_path = args.ConfigPath
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if os.path.isdir(config_path):
        candidate = os.path.join(config_path, "Configuration.xml")
        if os.path.isfile(candidate):
            config_path = candidate
        else:
            print("No Configuration.xml in directory", file=sys.stderr)
            sys.exit(1)
    if not os.path.isfile(config_path):
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    resolved_path = os.path.abspath(config_path)

    xml_parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(resolved_path, xml_parser)
    xml_root = tree.getroot()

    add_count = 0
    remove_count = 0
    modify_count = 0

    cfg_el = None
    for child in xml_root:
        if isinstance(child.tag, str) and localname(child) == "Configuration":
            cfg_el = child
            break
    if cfg_el is None:
        print("No <Configuration> element found", file=sys.stderr)
        sys.exit(1)

    props_el = None
    child_objs_el = None
    for child in cfg_el:
        if not isinstance(child.tag, str):
            continue
        if localname(child) == "Properties":
            props_el = child
        if localname(child) == "ChildObjects":
            child_objs_el = child

    obj_name = ""
    if props_el is not None:
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "Name":
                obj_name = (child.text or "").strip()
                break
    info(f"Configuration: {obj_name}")

    # --- Operations ---
    def do_modify_property(batch_val):
        nonlocal modify_count
        items = parse_batch_value(batch_val)
        for item in items:
            eq_idx = item.find("=")
            if eq_idx < 1:
                print(f"Invalid property format '{item}', expected 'Key=Value'", file=sys.stderr)
                sys.exit(1)
            prop_name = item[:eq_idx].strip()
            prop_value = item[eq_idx + 1:].strip()

            prop_el = None
            for child in props_el:
                if isinstance(child.tag, str) and localname(child) == prop_name:
                    prop_el = child
                    break
            if prop_el is None:
                print(f"Property '{prop_name}' not found in Properties", file=sys.stderr)
                sys.exit(1)

            if prop_name in ML_PROPS:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                if not prop_value:
                    prop_el.text = None
                else:
                    indent = get_child_indent(props_el)
                    item_el = etree.SubElement(prop_el, f"{{{V8_NS}}}item")
                    lang_el = etree.SubElement(item_el, f"{{{V8_NS}}}lang")
                    lang_el.text = "ru"
                    content_el = etree.SubElement(item_el, f"{{{V8_NS}}}content")
                    content_el.text = prop_value
                    prop_el.text = "\r\n" + indent + "\t"
                    item_el.text = "\r\n" + indent + "\t\t"
                    lang_el.tail = "\r\n" + indent + "\t\t"
                    content_el.tail = "\r\n" + indent + "\t"
                    item_el.tail = "\r\n" + indent
            elif prop_name in SCALAR_PROPS or prop_name in REF_PROPS:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                if not prop_value:
                    prop_el.text = None
                else:
                    prop_el.text = prop_value
            else:
                for ch in list(prop_el):
                    prop_el.remove(ch)
                prop_el.text = prop_value

            modify_count += 1
            info(f'Set {prop_name} = "{prop_value}"')

    def do_add_child_object(batch_val):
        nonlocal add_count
        if child_objs_el is None:
            print("No <ChildObjects> element found", file=sys.stderr)
            sys.exit(1)

        items = parse_batch_value(batch_val)
        cfg_indent = get_child_indent(cfg_el)
        if len(child_objs_el) == 0 and not (child_objs_el.text and child_objs_el.text.strip()):
            expand_self_closing(child_objs_el, cfg_indent)
        child_indent = get_child_indent(child_objs_el)

        for item in items:
            dot_idx = item.find(".")
            if dot_idx < 1:
                print(f"Invalid format '{item}', expected 'Type.Name'", file=sys.stderr)
                sys.exit(1)
            type_name = item[:dot_idx]
            obj_name_val = item[dot_idx + 1:]

            if type_name not in TYPE_ORDER:
                print(f"Unknown type '{type_name}'", file=sys.stderr)
                sys.exit(1)
            type_idx = TYPE_ORDER.index(type_name)

            # Dedup
            exists = False
            for child in child_objs_el:
                if isinstance(child.tag, str) and localname(child) == type_name and (child.text or "") == obj_name_val:
                    exists = True
                    break
            if exists:
                warn(f"Already exists: {type_name}.{obj_name_val}")
                continue

            # Find insertion point
            insert_before = None
            for child in child_objs_el:
                if not isinstance(child.tag, str):
                    continue
                child_type_name = localname(child)
                if child_type_name not in TYPE_ORDER:
                    continue
                child_type_idx = TYPE_ORDER.index(child_type_name)

                if child_type_name == type_name:
                    if (child.text or "") > obj_name_val and insert_before is None:
                        insert_before = child
                elif child_type_idx > type_idx and insert_before is None:
                    insert_before = child

            new_el = etree.Element(f"{{{MD_NS}}}{type_name}")
            new_el.text = obj_name_val

            if insert_before is not None:
                insert_before_ref(child_objs_el, new_el, insert_before, child_indent)
            else:
                insert_before_closing(child_objs_el, new_el, child_indent)

            add_count += 1
            info(f"Added: {type_name}.{obj_name_val}")

    def do_remove_child_object(batch_val):
        nonlocal remove_count
        if child_objs_el is None:
            print("No <ChildObjects> element found", file=sys.stderr)
            sys.exit(1)

        items = parse_batch_value(batch_val)
        for item in items:
            dot_idx = item.find(".")
            if dot_idx < 1:
                print(f"Invalid format '{item}', expected 'Type.Name'", file=sys.stderr)
                sys.exit(1)
            type_name = item[:dot_idx]
            obj_name_val = item[dot_idx + 1:]

            found = False
            for child in list(child_objs_el):
                if isinstance(child.tag, str) and localname(child) == type_name and (child.text or "") == obj_name_val:
                    remove_with_indent(child)
                    remove_count += 1
                    info(f"Removed: {type_name}.{obj_name_val}")
                    found = True
                    break
            if not found:
                warn(f"Not found: {type_name}.{obj_name_val}")

    def do_add_default_role(batch_val):
        nonlocal add_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found in Properties", file=sys.stderr)
            sys.exit(1)

        props_indent = get_child_indent(props_el)
        if len(roles_el) == 0 and not (roles_el.text and roles_el.text.strip()):
            expand_self_closing(roles_el, props_indent)
        role_indent = get_child_indent(roles_el)

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            exists = False
            for child in roles_el:
                if isinstance(child.tag, str) and (child.text or "").strip() == role_name:
                    exists = True
                    break
            if exists:
                warn(f"DefaultRole already exists: {role_name}")
                continue

            frag_xml = f'<xr:Item xsi:type="xr:MDObjectRef">{role_name}</xr:Item>'
            nodes = import_fragment(frag_xml)
            if nodes:
                insert_before_closing(roles_el, nodes[0], role_indent)
                add_count += 1
                info(f"Added DefaultRole: {role_name}")

    def do_remove_default_role(batch_val):
        nonlocal remove_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found", file=sys.stderr)
            sys.exit(1)

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            found = False
            for child in list(roles_el):
                if isinstance(child.tag, str) and (child.text or "").strip() == role_name:
                    remove_with_indent(child)
                    remove_count += 1
                    info(f"Removed DefaultRole: {role_name}")
                    found = True
                    break
            if not found:
                warn(f"DefaultRole not found: {role_name}")

    def do_set_default_roles(batch_val):
        nonlocal modify_count
        items = parse_batch_value(batch_val)

        roles_el = None
        for child in props_el:
            if isinstance(child.tag, str) and localname(child) == "DefaultRoles":
                roles_el = child
                break
        if roles_el is None:
            print("No <DefaultRoles> element found", file=sys.stderr)
            sys.exit(1)

        # Clear all existing children
        for ch in list(roles_el):
            roles_el.remove(ch)
        roles_el.text = None

        if not items:
            modify_count += 1
            info("Cleared DefaultRoles")
            return

        props_indent = get_child_indent(props_el)
        role_indent = props_indent + "\t"

        roles_el.text = "\r\n" + props_indent

        for item in items:
            role_name = item
            if not role_name.startswith("Role."):
                role_name = f"Role.{role_name}"

            frag_xml = f'<xr:Item xsi:type="xr:MDObjectRef">{role_name}</xr:Item>'
            nodes = import_fragment(frag_xml)
            if nodes:
                insert_before_closing(roles_el, nodes[0], role_indent)

        modify_count += 1
        info(f"Set DefaultRoles: {len(items)} roles")

    # --- Execute operations ---
    operations = []
    if args.DefinitionFile:
        def_file = args.DefinitionFile
        if not os.path.isabs(def_file):
            def_file = os.path.join(os.getcwd(), def_file)
        with open(def_file, "r", encoding="utf-8-sig") as fh:
            ops = json.loads(fh.read())
        if isinstance(ops, list):
            operations = ops
        else:
            operations = [ops]
    else:
        operations = [{"operation": args.Operation, "value": args.Value or ""}]

    for op in operations:
        op_name = op.get("operation", args.Operation or "")
        op_value = op.get("value", args.Value or "")

        if op_name == "modify-property":
            do_modify_property(op_value)
        elif op_name == "add-childObject":
            do_add_child_object(op_value)
        elif op_name == "remove-childObject":
            do_remove_child_object(op_value)
        elif op_name == "add-defaultRole":
            do_add_default_role(op_value)
        elif op_name == "remove-defaultRole":
            do_remove_default_role(op_value)
        elif op_name == "set-defaultRoles":
            do_set_default_roles(op_value)
        else:
            print(f"Unknown operation: {op_name}", file=sys.stderr)
            sys.exit(1)

    # --- Save ---
    save_xml_bom(tree, resolved_path)
    info(f"Saved: {resolved_path}")

    # --- Auto-validate ---
    if not args.NoValidate:
        validate_script = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "cf-validate", "scripts", "cf-validate.py"))
        if os.path.isfile(validate_script):
            print()
            print("--- Running cf-validate ---")
            subprocess.run([sys.executable, validate_script, "-ConfigPath", resolved_path])

    # --- Summary ---
    print()
    print("=== cf-edit summary ===")
    print(f"  Configuration: {obj_name}")
    print(f"  Added:         {add_count}")
    print(f"  Removed:       {remove_count}")
    print(f"  Modified:      {modify_count}")
    sys.exit(0)


if __name__ == "__main__":
    main()
