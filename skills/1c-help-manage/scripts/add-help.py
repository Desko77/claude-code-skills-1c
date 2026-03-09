#!/usr/bin/env python3
# add-help v1.0 — Add built-in help to 1C object
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import os
import sys

from lxml import etree

NSMAP = {"md": "http://v8.1c.ru/8.3/MDClasses"}


def save_xml_with_bom(tree, path):
    """Save XML tree to file with UTF-8 BOM."""
    xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    xml_bytes = xml_bytes.replace(b"encoding='UTF-8'", b'encoding="UTF-8"')
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(xml_bytes)


def write_text_with_bom(path, text):
    """Write text to file with UTF-8 BOM."""
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Add built-in help to 1C object", allow_abbrev=False)
    parser.add_argument("-ObjectName", "-ProcessorName", required=True)
    parser.add_argument("-Lang", default="ru")
    parser.add_argument("-SrcDir", default="src")
    args = parser.parse_args()

    object_name = args.ObjectName
    lang = args.Lang
    src_dir = args.SrcDir

    # --- Checks ---

    processor_dir = os.path.join(src_dir, object_name)
    ext_dir = os.path.join(processor_dir, "Ext")

    if not os.path.isdir(ext_dir):
        print(f"Каталог обработки не найден: {ext_dir}. Сначала выполните epf-init.", file=sys.stderr)
        sys.exit(1)

    help_xml_path = os.path.join(ext_dir, "Help.xml")
    if os.path.exists(help_xml_path):
        print(f"Справка уже существует: {help_xml_path}", file=sys.stderr)
        sys.exit(1)

    # --- 1. Help.xml ---

    help_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Help xmlns="http://v8.1c.ru/8.3/xcf/extrnprops"'
        ' xmlns:xs="http://www.w3.org/2001/XMLSchema"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' version="2.17">\n'
        f'\t<Page>{lang}</Page>\n'
        '</Help>'
    )

    write_text_with_bom(help_xml_path, help_xml)

    # --- 2. Help/<lang>.html ---

    help_dir = os.path.join(ext_dir, "Help")
    os.makedirs(help_dir, exist_ok=True)

    help_html_path = os.path.join(help_dir, f"{lang}.html")

    help_html = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">\n'
        '<html>\n'
        '<head>\n'
        '    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
        '    <link rel="stylesheet" type="text/css" href="v8help://service_book/service_style"/>\n'
        '</head>\n'
        '<body>\n'
        f'    <h1>{object_name}</h1>\n'
        '    <p>Описание обработки.</p>\n'
        '</body>\n'
        '</html>'
    )

    write_text_with_bom(help_html_path, help_html)

    # --- 3. Check IncludeHelpInContents in form metadata ---

    forms_dir = os.path.join(processor_dir, "Forms")
    if os.path.isdir(forms_dir):
        for entry in os.listdir(forms_dir):
            if not entry.endswith(".xml"):
                continue
            form_meta_full = os.path.join(forms_dir, entry)
            if not os.path.isfile(form_meta_full):
                continue

            parser_xml = etree.XMLParser(remove_blank_text=False)
            form_tree = etree.parse(form_meta_full, parser_xml)
            form_root = form_tree.getroot()

            include_help = form_root.find(".//md:IncludeHelpInContents", NSMAP)
            if include_help is not None:
                continue

            # Add after <FormType>
            form_type = form_root.find(".//md:FormType", NSMAP)
            if form_type is None:
                continue

            parent = form_type.getparent()
            ns = "http://v8.1c.ru/8.3/MDClasses"
            new_elem = etree.SubElement(parent, f"{{{ns}}}IncludeHelpInContents")
            new_elem.text = "false"
            # Remove SubElement's auto-placement (it appends to end) and insert after FormType
            parent.remove(new_elem)

            # Find index of FormType in parent
            form_type_idx = list(parent).index(form_type)

            # Insert after FormType
            parent.insert(form_type_idx + 1, new_elem)

            # Whitespace handling: copy FormType's tail as new_elem's tail,
            # and set FormType's tail to include newline + indent
            new_elem.tail = form_type.tail
            form_type.tail = "\n\t\t\t"

            save_xml_with_bom(form_tree, form_meta_full)

            print(f"     IncludeHelpInContents добавлен: {entry}")

    print(f"[OK] Создана справка: {object_name}")
    print(f"     Метаданные: {help_xml_path}")
    print(f"     Страница:   {help_html_path}")


if __name__ == "__main__":
    main()
