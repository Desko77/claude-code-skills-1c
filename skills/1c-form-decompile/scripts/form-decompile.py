#!/usr/bin/env python3
# form-decompile v1.0 - Decompile 1C managed form (Form.xml) to JSON DSL draft
# Source: https://github.com/Desko77/claude-code-skills-1c
# Structural mirror of form-decompile.ps1 (canonical implementation).

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# XML tag -> DSL type key (form-dsl-spec.md, section 4.3)
ELEMENT_MAP = {
    "UsualGroup": "group",
    "InputField": "input",
    "CheckBoxField": "check",
    "LabelDecoration": "label",
    "LabelField": "labelField",
    "Table": "table",
    "Pages": "pages",
    "Page": "page",
    "Button": "button",
    "PictureDecoration": "picture",
    "PictureField": "picField",
    "CalendarField": "calendar",
    "CommandBar": "cmdBar",
    "Popup": "popup",
}

# Reverse of form-compile PROP_MAP; fallback is first-char lowercase
PROP_REVERSE = {
    "AutoTitle": "autoTitle",
    "WindowOpeningMode": "windowOpeningMode",
    "CommandBarLocation": "commandBarLocation",
    "SaveDataInSettings": "saveDataInSettings",
    "AutoSaveDataInSettings": "autoSaveDataInSettings",
    "AutoTime": "autoTime",
    "UsePostingMode": "usePostingMode",
    "RepostOnWrite": "repostOnWrite",
    "AutoURL": "autoURL",
    "AutoFillCheck": "autoFillCheck",
    "Customizable": "customizable",
    "EnterKeyBehavior": "enterKeyBehavior",
    "VerticalScroll": "verticalScroll",
    "ScalingMode": "scalingMode",
    "UseForFoldersAndItems": "useForFoldersAndItems",
    "ReportResult": "reportResult",
    "DetailsData": "detailsData",
    "ReportFormType": "reportFormType",
    "AutoShowState": "autoShowState",
    "Width": "width",
    "Height": "height",
    "Group": "group",
}

FORM_STRUCTURAL_TAGS = {
    "Title", "CommandSet", "AutoCommandBar", "Events", "ChildItems",
    "Attributes", "Parameters", "Commands", "CommandInterface",
    "ConditionalAppearance", "MobileDeviceCommandBarContent",
}

GROUP_ORIENTATION_REVERSE = {
    "Horizontal": "horizontal",
    "Vertical": "vertical",
    "AlwaysHorizontal": "alwaysHorizontal",
    "AlwaysVertical": "alwaysVertical",
}

GROUP_REPRESENTATION_REVERSE = {
    "None": "none",
    "NormalSeparation": "normal",
    "WeakSeparation": "weak",
    "StrongSeparation": "strong",
}

TITLE_LOCATION_REVERSE = {
    "None": "none", "Left": "left", "Right": "right", "Top": "top", "Bottom": "bottom",
}

BUTTON_TYPE_REVERSE = {
    "UsualButton": "usual", "Hyperlink": "hyperlink", "CommandBarButton": "commandBar",
}

PLATFORM_TYPE_REVERSE = {
    "v8:ValueTable": "ValueTable",
    "v8:ValueTree": "ValueTree",
    "v8:ValueListType": "ValueList",
    "v8:TypeDescription": "TypeDescription",
    "v8:Universal": "Universal",
    "v8:FixedArray": "FixedArray",
    "v8:FixedStructure": "FixedStructure",
    "v8:UUID": "UUID",
    "v8ui:FormattedString": "FormattedString",
    "v8ui:Picture": "Picture",
    "v8ui:Color": "Color",
    "v8ui:Font": "Font",
    "dcsset:DataCompositionSettings": "DataCompositionSettings",
    "dcssch:DataCompositionSchema": "DataCompositionSchema",
    "dcscor:DataCompositionComparisonType": "DataCompositionComparisonType",
}

# Same table as in form-compile: auto handler = element name + suffix
EVENT_SUFFIX_MAP = {
    "OnChange": "ПриИзменении",
    "StartChoice": "НачалоВыбора",
    "ChoiceProcessing": "ОбработкаВыбора",
    "AutoComplete": "АвтоПодбор",
    "Clearing": "Очистка",
    "Opening": "Открытие",
    "Click": "Нажатие",
    "OnActivateRow": "ПриАктивизацииСтроки",
    "BeforeAddRow": "ПередНачаломДобавления",
    "BeforeDeleteRow": "ПередУдалением",
    "BeforeRowChange": "ПередНачаломИзменения",
    "OnStartEdit": "ПриНачалеРедактирования",
    "OnEndEdit": "ПриОкончанииРедактирования",
    "Selection": "ВыборСтроки",
    "OnCurrentPageChange": "ПриСменеСтраницы",
    "TextEditEnd": "ОкончаниеВводаТекста",
    "URLProcessing": "ОбработкаНавигационнойСсылки",
    "DragStart": "НачалоПеретаскивания",
    "Drag": "Перетаскивание",
    "DragCheck": "ПроверкаПеретаскивания",
    "Drop": "Помещение",
    "AfterDeleteRow": "ПослеУдаления",
}

TODO_COUNT = 0


def lname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def note(todos, msg):
    global TODO_COUNT
    TODO_COUNT += 1
    todos.append(msg)
    print("[TODO] " + msg, file=sys.stderr)


def is_empty_node(node):
    if len(node) > 0:
        return False
    return not (node.text or "").strip()


def as_bool(text):
    return (text or "").strip() == "true"


def sniff_scalar(text):
    t = (text or "").strip()
    if t == "true":
        return True
    if t == "false":
        return False
    if re.match(r"^-?\d+$", t):
        return int(t)
    return t


def node_text(node):
    return (node.text or "").strip()


def ml_text(node, todos, owner):
    ru_val = None
    first_val = None
    items = 0
    for item in node:
        if lname(item.tag) != "item":
            continue
        lang = None
        content = None
        for sub in item:
            sn = lname(sub.tag)
            if sn == "lang":
                lang = (sub.text or "").strip()
            elif sn == "content":
                content = sub.text or ""
        if content is None:
            continue
        items += 1
        if first_val is None:
            first_val = content
        if lang == "ru" and ru_val is None:
            ru_val = content
    if items > 1:
        note(todos, owner + ": мультиязычный текст, взят один язык (ru или первый)")
    best = ru_val if ru_val is not None else first_val
    if best is not None:
        return best
    t = (node.text or "").strip()
    return t if t else None


def base_type_token(raw):
    if raw == "xs:string":
        return "string"
    if raw == "xs:decimal":
        return "decimal"
    if raw == "xs:boolean":
        return "boolean"
    if raw == "xs:dateTime":
        return "dateTime"
    if raw.startswith("cfg:"):
        return raw[4:]
    if raw in PLATFORM_TYPE_REVERSE:
        return PLATFORM_TYPE_REVERSE[raw]
    return raw


def decompile_type(type_node, todos, owner):
    parts = []
    for ch in type_node:
        ln = lname(ch.tag)
        if ln == "Type":
            parts.append(base_type_token(node_text(ch)))
        elif ln == "StringQualifiers":
            length = "0"
            allowed = ""
            for q in ch:
                qn = lname(q.tag)
                if qn == "Length":
                    length = node_text(q)
                elif qn == "AllowedLength":
                    allowed = node_text(q)
            if parts and parts[-1] == "string" and length not in ("", "0"):
                parts[-1] = "string(" + length + ")"
            if allowed == "Fixed":
                note(todos, owner + ": AllowedLength=Fixed не выражается в DSL")
        elif ln == "NumberQualifiers":
            digits = "0"
            fraction = "0"
            sign = ""
            for q in ch:
                qn = lname(q.tag)
                if qn == "Digits":
                    digits = node_text(q)
                elif qn == "FractionDigits":
                    fraction = node_text(q)
                elif qn == "AllowedSign":
                    sign = node_text(q)
            if parts and parts[-1] == "decimal":
                suffix = ",nonneg" if sign == "Nonnegative" else ""
                parts[-1] = "decimal(" + digits + "," + fraction + suffix + ")"
        elif ln == "DateQualifiers":
            fractions = ""
            for q in ch:
                if lname(q.tag) == "DateFractions":
                    fractions = node_text(q)
            df_map = {"Date": "date", "Time": "time", "DateTime": "dateTime"}
            if parts and parts[-1] == "dateTime" and fractions in df_map:
                parts[-1] = df_map[fractions]
        elif ln in ("TypeSet", "TypeId"):
            note(todos, owner + ": <v8:" + ln + "> (" + node_text(ch) + ") не выражается в DSL")
        else:
            note(todos, owner + ": узел типа " + ln + " не разобран")
    fixed = []
    for p in parts:
        if p == "decimal":
            fixed.append("decimal(0,0)")
        elif p:
            fixed.append(p)
    return " | ".join(fixed)


def picture_ref(node, todos, owner):
    ref = None
    for ch in node:
        ln = lname(ch.tag)
        if ln == "Ref":
            ref = node_text(ch)
        elif ln == "LoadTransparent":
            pass
        else:
            note(todos, owner + ": картинка задана не ссылкой xr:Ref (" + ln + ")")
    return ref


def read_element_events(node, el_name, el):
    on = []
    handlers = OrderedDict()
    for ev in node:
        if lname(ev.tag) != "Event":
            continue
        ev_name = ev.get("name", "")
        handler = (ev.text or "").strip()
        if not ev_name or not handler:
            continue
        on.append(ev_name)
        suffix = EVENT_SUFFIX_MAP.get(ev_name)
        auto = el_name + suffix if suffix else el_name + ev_name
        if handler != auto:
            handlers[ev_name] = handler
    if on:
        el["on"] = on
    if handlers:
        el["handlers"] = handlers


def handle_common_child(ch, ln, el, name, todos):
    """Returns True if the child was consumed by a common rule."""
    if ln == "Title":
        t = ml_text(ch, todos, "Элемент '" + name + "'")
        if t is not None:
            el["title"] = t
        return True
    if ln == "Visible":
        if node_text(ch) == "false":
            el["hidden"] = True
        return True
    if ln == "Enabled":
        if node_text(ch) == "false":
            el["disabled"] = True
        return True
    if ln == "ReadOnly":
        if node_text(ch) == "true":
            el["readOnly"] = True
        return True
    if ln == "UserVisible":
        for sub in ch:
            sn = lname(sub.tag)
            if sn == "Common":
                if node_text(sub) == "false":
                    el["userVisible"] = False
            else:
                note(todos, "Элемент '" + name + "': UserVisible по ролям не поддержан DSL")
        return True
    if ln == "Events":
        read_element_events(ch, name, el)
        return True
    if ln in ("ContextMenu", "ExtendedTooltip", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"):
        if not is_empty_node(ch):
            note(todos, "Элемент '" + name + "': служебный элемент " + ln + " с содержимым не перенесен (генерируется заново)")
        return True
    return False


def unknown_child(ch, ln, name, todos):
    if len(ch) == 0:
        val = node_text(ch)
        note(todos, "Элемент '" + name + "': свойство " + ln + "=" + val + " не поддержано DSL")
    else:
        note(todos, "Элемент '" + name + "': узел " + ln + " не поддержан DSL")


def parse_child_items(node, container_key, el):
    items = []
    for sub in node:
        parsed = parse_element(sub)
        if parsed is not None:
            items.append(parsed)
    el[container_key] = items


def check_extra_attrs(node, name, todos):
    for attr_name in node.attrib:
        an = lname(attr_name)
        if an in ("name", "id"):
            continue
        note(todos, "Элемент '" + name + "': XML-атрибут " + an + "=" + node.attrib[attr_name] + " не поддержан DSL")


def parse_element(node):
    tag = lname(node.tag)
    name = node.get("name", "")
    todos = []

    if tag not in ELEMENT_MAP:
        note(todos, "Элемент " + tag + " '" + name + "' не поддержан DSL 1c-form-compile - создать вручную")
        placeholder = OrderedDict()
        placeholder["name"] = name
        placeholder["_todo"] = todos
        return placeholder

    key = ELEMENT_MAP[tag]
    el = OrderedDict()

    if key == "group":
        orientation = ""
        collapsible = False
        for ch in node:
            ln = lname(ch.tag)
            if ln == "Group":
                orientation = GROUP_ORIENTATION_REVERSE.get(node_text(ch), node_text(ch))
            elif ln == "Behavior" and node_text(ch) == "Collapsible":
                collapsible = True
        if collapsible:
            orientation = "collapsible"
        elif not orientation:
            orientation = "vertical"
        el["group"] = orientation
        el["name"] = name
    else:
        el[key] = name

    check_extra_attrs(node, name, todos)

    for ch in node:
        ln = lname(ch.tag)

        if key == "group" and ln in ("Group", "Behavior"):
            continue
        if handle_common_child(ch, ln, el, name, todos):
            continue

        if key == "group":
            if ln == "Representation":
                el["representation"] = GROUP_REPRESENTATION_REVERSE.get(node_text(ch), node_text(ch))
            elif ln == "ShowTitle":
                el["showTitle"] = as_bool(node_text(ch))
            elif ln == "United":
                el["united"] = as_bool(node_text(ch))
            elif ln == "ChildItems":
                parse_child_items(ch, "children", el)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "input":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            elif ln == "TitleLocation":
                el["titleLocation"] = TITLE_LOCATION_REVERSE.get(node_text(ch), node_text(ch))
            elif ln == "MultiLine":
                el["multiLine"] = as_bool(node_text(ch))
            elif ln == "PasswordMode":
                el["passwordMode"] = as_bool(node_text(ch))
            elif ln == "ChoiceButton":
                el["choiceButton"] = as_bool(node_text(ch))
            elif ln == "ClearButton":
                el["clearButton"] = as_bool(node_text(ch))
            elif ln == "SpinButton":
                el["spinButton"] = as_bool(node_text(ch))
            elif ln == "DropListButton":
                el["dropListButton"] = as_bool(node_text(ch))
            elif ln == "AutoMarkIncomplete":
                el["markIncomplete"] = as_bool(node_text(ch))
            elif ln == "SkipOnInput":
                el["skipOnInput"] = as_bool(node_text(ch))
            elif ln == "AutoMaxWidth":
                el["autoMaxWidth"] = as_bool(node_text(ch))
            elif ln == "AutoMaxHeight":
                el["autoMaxHeight"] = as_bool(node_text(ch))
            elif ln == "Width":
                el["width"] = sniff_scalar(node_text(ch))
            elif ln == "Height":
                el["height"] = sniff_scalar(node_text(ch))
            elif ln == "HorizontalStretch":
                el["horizontalStretch"] = as_bool(node_text(ch))
            elif ln == "VerticalStretch":
                el["verticalStretch"] = as_bool(node_text(ch))
            elif ln == "InputHint":
                t = ml_text(ch, todos, "Элемент '" + name + "'")
                if t is not None:
                    el["inputHint"] = t
            elif ln == "EditMode":
                el["editMode"] = node_text(ch)
            elif ln == "Wrap":
                el["wrap"] = as_bool(node_text(ch))
            elif ln == "ChooseType":
                el["chooseType"] = as_bool(node_text(ch))
            elif ln == "TextEdit":
                el["textEdit"] = as_bool(node_text(ch))
            elif ln == "TypeDomainEnabled":
                el["typeDomainEnabled"] = as_bool(node_text(ch))
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "check":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            elif ln == "TitleLocation":
                el["titleLocation"] = node_text(ch)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "label":
            if ln == "Hyperlink":
                el["hyperlink"] = as_bool(node_text(ch))
            elif ln == "AutoMaxWidth":
                el["autoMaxWidth"] = as_bool(node_text(ch))
            elif ln == "AutoMaxHeight":
                el["autoMaxHeight"] = as_bool(node_text(ch))
            elif ln == "Width":
                el["width"] = sniff_scalar(node_text(ch))
            elif ln == "Height":
                el["height"] = sniff_scalar(node_text(ch))
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "labelField":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            elif ln == "Hyperlink":
                el["hyperlink"] = as_bool(node_text(ch))
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "table":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            elif ln == "Representation":
                el["representation"] = node_text(ch)
            elif ln == "ChangeRowSet":
                el["changeRowSet"] = as_bool(node_text(ch))
            elif ln == "ChangeRowOrder":
                el["changeRowOrder"] = as_bool(node_text(ch))
            elif ln == "HeightInTableRows":
                el["height"] = sniff_scalar(node_text(ch))
            elif ln == "Header":
                el["header"] = as_bool(node_text(ch))
            elif ln == "Footer":
                el["footer"] = as_bool(node_text(ch))
            elif ln == "CommandBarLocation":
                el["commandBarLocation"] = node_text(ch)
            elif ln == "SearchStringLocation":
                el["searchStringLocation"] = node_text(ch)
            elif ln == "TitleLocation":
                el["titleLocation"] = node_text(ch)
            elif ln == "ChoiceMode":
                el["choiceMode"] = as_bool(node_text(ch))
            elif ln == "InitialTreeView":
                el["initialTreeView"] = node_text(ch)
            elif ln == "EnableStartDrag":
                el["enableStartDrag"] = as_bool(node_text(ch))
            elif ln == "EnableDrag":
                el["enableDrag"] = as_bool(node_text(ch))
            elif ln == "RowPictureDataPath":
                el["rowPictureDataPath"] = node_text(ch)
            elif ln == "AutoCommandBar":
                for sub in ch:
                    sn = lname(sub.tag)
                    if sn == "Autofill":
                        el["tableAutofill"] = as_bool(node_text(sub))
                    else:
                        note(todos, "Элемент '" + name + "': содержимое AutoCommandBar (" + sn + ") не поддержано DSL")
            elif ln == "ChildItems":
                parse_child_items(ch, "columns", el)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "pages":
            if ln == "PagesRepresentation":
                el["pagesRepresentation"] = node_text(ch)
            elif ln == "ChildItems":
                parse_child_items(ch, "children", el)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "page":
            if ln == "Group":
                el["group"] = GROUP_ORIENTATION_REVERSE.get(node_text(ch), node_text(ch))
            elif ln == "ChildItems":
                parse_child_items(ch, "children", el)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "button":
            if ln == "Type":
                el["type"] = BUTTON_TYPE_REVERSE.get(node_text(ch), node_text(ch))
            elif ln == "CommandName":
                cn = node_text(ch)
                m = re.match(r"^Form\.Command\.(.+)$", cn)
                m_std = re.match(r"^Form\.StandardCommand\.(.+)$", cn)
                m_item = re.match(r"^Form\.Item\.(.+)\.StandardCommand\.(.+)$", cn)
                if m_item:
                    el["stdCommand"] = m_item.group(1) + "." + m_item.group(2)
                elif m_std:
                    el["stdCommand"] = m_std.group(1)
                elif m:
                    el["command"] = m.group(1)
                else:
                    note(todos, "Элемент '" + name + "': CommandName '" + cn + "' не распознан")
            elif ln == "DefaultButton":
                el["defaultButton"] = as_bool(node_text(ch))
            elif ln == "Picture":
                ref = picture_ref(ch, todos, "Элемент '" + name + "'")
                if ref:
                    el["picture"] = ref
            elif ln == "Representation":
                el["representation"] = node_text(ch)
            elif ln == "LocationInCommandBar":
                el["locationInCommandBar"] = node_text(ch)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "picture":
            if ln == "Picture":
                ref = picture_ref(ch, todos, "Элемент '" + name + "'")
                if ref:
                    el["src"] = ref
            elif ln == "Hyperlink":
                el["hyperlink"] = as_bool(node_text(ch))
            elif ln == "Width":
                el["width"] = sniff_scalar(node_text(ch))
            elif ln == "Height":
                el["height"] = sniff_scalar(node_text(ch))
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "picField":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            elif ln == "Width":
                el["width"] = sniff_scalar(node_text(ch))
            elif ln == "Height":
                el["height"] = sniff_scalar(node_text(ch))
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "calendar":
            if ln == "DataPath":
                el["path"] = node_text(ch)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "cmdBar":
            if ln == "Autofill":
                el["autofill"] = as_bool(node_text(ch))
            elif ln == "ChildItems":
                parse_child_items(ch, "children", el)
            else:
                unknown_child(ch, ln, name, todos)
        elif key == "popup":
            if ln == "Picture":
                ref = picture_ref(ch, todos, "Элемент '" + name + "'")
                if ref:
                    el["picture"] = ref
            elif ln == "Representation":
                el["representation"] = node_text(ch)
            elif ln == "ChildItems":
                parse_child_items(ch, "children", el)
            else:
                unknown_child(ch, ln, name, todos)
        else:
            unknown_child(ch, ln, name, todos)

    if todos:
        el["_todo"] = todos
    return el


def parse_attribute(node):
    name = node.get("name", "")
    todos = []
    check_extra_attrs(node, name, todos)
    title = None
    type_str = None
    main = False
    saved_data = False
    fill_checking = None
    columns = None
    settings = None

    for ch in node:
        ln = lname(ch.tag)
        if ln == "Title":
            title = ml_text(ch, todos, "Реквизит '" + name + "'")
        elif ln == "Type":
            type_str = decompile_type(ch, todos, "Реквизит '" + name + "'")
        elif ln == "MainAttribute":
            main = as_bool(node_text(ch))
        elif ln == "SavedData":
            saved_data = as_bool(node_text(ch))
        elif ln == "FillChecking":
            fill_checking = node_text(ch)
        elif ln == "Columns":
            columns = []
            for col in ch:
                if lname(col.tag) != "Column":
                    note(todos, "Реквизит '" + name + "': узел Columns/" + lname(col.tag) + " не разобран")
                    continue
                c = OrderedDict()
                c["name"] = col.get("name", "")
                for cc in col:
                    cn = lname(cc.tag)
                    if cn == "Title":
                        t = ml_text(cc, todos, "Колонка '" + c["name"] + "'")
                        if t is not None:
                            c["title"] = t
                    elif cn == "Type":
                        ct = decompile_type(cc, todos, "Колонка '" + c["name"] + "'")
                        if ct:
                            c["type"] = ct
                    else:
                        note(todos, "Колонка '" + c["name"] + "': узел " + cn + " не поддержан DSL")
                columns.append(c)
        elif ln == "Settings":
            xsi_type = ch.get("{" + XSI_NS + "}type", "")
            if xsi_type.endswith("DynamicList"):
                settings = OrderedDict()
                for sc in ch:
                    sn = lname(sc.tag)
                    if sn == "MainTable":
                        settings["mainTable"] = node_text(sc)
                    elif sn == "DynamicDataRead":
                        settings["dynamicDataRead"] = as_bool(node_text(sc))
                    elif sn == "ManualQuery":
                        if as_bool(node_text(sc)):
                            settings["manualQuery"] = True
                    elif sn == "Query":
                        note(todos, "Реквизит '" + name + "': текст запроса динамического списка не поддержан DSL: " + (sc.text or "").strip())
                    else:
                        note(todos, "Реквизит '" + name + "': Settings/" + sn + " не поддержан DSL")
            else:
                note(todos, "Реквизит '" + name + "': Settings xsi:type='" + xsi_type + "' не поддержан DSL")
        else:
            note(todos, "Реквизит '" + name + "': узел " + ln + " не поддержан DSL")

    a = OrderedDict()
    a["name"] = name
    if type_str:
        a["type"] = type_str
    if main:
        a["main"] = True
    if title is not None:
        a["title"] = title
    if saved_data:
        a["savedData"] = True
    if fill_checking:
        a["fillChecking"] = fill_checking
    if columns is not None:
        a["columns"] = columns
    if settings is not None:
        a["settings"] = settings
    if todos:
        a["_todo"] = todos
    return a


def parse_parameter(node):
    name = node.get("name", "")
    todos = []
    check_extra_attrs(node, name, todos)
    p = OrderedDict()
    p["name"] = name
    for ch in node:
        ln = lname(ch.tag)
        if ln == "Type":
            t = decompile_type(ch, todos, "Параметр '" + name + "'")
            if t:
                p["type"] = t
        elif ln == "KeyParameter":
            if as_bool(node_text(ch)):
                p["key"] = True
        else:
            note(todos, "Параметр '" + name + "': узел " + ln + " не поддержан DSL")
    if todos:
        p["_todo"] = todos
    return p


def parse_command(node):
    name = node.get("name", "")
    todos = []
    check_extra_attrs(node, name, todos)
    action = None
    title = None
    shortcut = None
    picture = None
    representation = None

    for ch in node:
        ln = lname(ch.tag)
        if ln == "Action":
            action = node_text(ch)
        elif ln == "Title":
            title = ml_text(ch, todos, "Команда '" + name + "'")
        elif ln == "Shortcut":
            shortcut = node_text(ch)
        elif ln == "Picture":
            picture = picture_ref(ch, todos, "Команда '" + name + "'")
        elif ln == "Representation":
            representation = node_text(ch)
        else:
            note(todos, "Команда '" + name + "': узел " + ln + " не поддержан DSL")

    c = OrderedDict()
    c["name"] = name
    if action:
        c["action"] = action
    if title is not None:
        c["title"] = title
    if shortcut:
        c["shortcut"] = shortcut
    if picture:
        c["picture"] = picture
    if representation:
        c["representation"] = representation
    if todos:
        c["_todo"] = todos
    return c


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Decompile 1C managed form (Form.xml) to JSON DSL draft", allow_abbrev=False)
    parser.add_argument("-InputFile", required=True, help="Path to Form.xml")
    parser.add_argument("-OutputFile", default=None, help="Output JSON path (default: <name>.form.json next to input)")
    args = parser.parse_args()

    input_path = args.InputFile
    if not os.path.isfile(input_path):
        print("File not found: " + input_path, file=sys.stderr)
        sys.exit(1)
    input_abs = os.path.abspath(input_path)

    output_path = args.OutputFile
    if not output_path:
        base = os.path.splitext(os.path.basename(input_abs))[0]
        output_path = os.path.join(os.path.dirname(input_abs), base + ".form.json")

    try:
        tree = ET.parse(input_abs)
    except ET.ParseError as e:
        print("XML parse error: " + str(e), file=sys.stderr)
        sys.exit(1)
    root = tree.getroot()

    if lname(root.tag) != "Form":
        print("Корневой элемент <" + lname(root.tag) + "> не <Form> - это не файл управляемой формы (выгрузка Конфигуратора)", file=sys.stderr)
        sys.exit(1)

    root_todos = []
    title = None
    properties = OrderedDict()
    excluded_commands = []
    events = OrderedDict()
    elements = []
    attributes = []
    parameters = []
    commands = []

    for ch in root:
        ln = lname(ch.tag)
        if ln == "Title":
            title = ml_text(ch, root_todos, "Форма")
        elif ln == "CommandSet":
            for sub in ch:
                sn = lname(sub.tag)
                if sn == "ExcludedCommand":
                    excluded_commands.append(node_text(sub))
                else:
                    note(root_todos, "Форма: CommandSet/" + sn + " не поддержан DSL")
        elif ln == "AutoCommandBar":
            for sub in ch:
                if lname(sub.tag) == "ChildItems" and not is_empty_node(sub):
                    note(root_todos, "Форма: командная панель формы содержит элементы - не поддержано DSL")
        elif ln == "Events":
            for ev in ch:
                if lname(ev.tag) != "Event":
                    continue
                ev_name = ev.get("name", "")
                handler = (ev.text or "").strip()
                if ev_name and handler:
                    events[ev_name] = handler
        elif ln == "ChildItems":
            for sub in ch:
                parsed = parse_element(sub)
                if parsed is not None:
                    elements.append(parsed)
        elif ln == "Attributes":
            for sub in ch:
                sn = lname(sub.tag)
                if sn == "Attribute":
                    attributes.append(parse_attribute(sub))
                elif sn == "ConditionalAppearance":
                    if not is_empty_node(sub):
                        note(root_todos, "Форма: условное оформление (ConditionalAppearance) не поддержано DSL")
                else:
                    note(root_todos, "Форма: Attributes/" + sn + " не разобран")
        elif ln == "Parameters":
            for sub in ch:
                if lname(sub.tag) == "Parameter":
                    parameters.append(parse_parameter(sub))
        elif ln == "Commands":
            for sub in ch:
                if lname(sub.tag) == "Command":
                    commands.append(parse_command(sub))
        elif ln == "CommandInterface":
            if not is_empty_node(ch):
                note(root_todos, "Форма: командный интерфейс (CommandInterface) не поддержан DSL")
        elif ln == "ConditionalAppearance":
            if not is_empty_node(ch):
                note(root_todos, "Форма: условное оформление (ConditionalAppearance) не поддержано DSL")
        elif ln == "MobileDeviceCommandBarContent":
            if not is_empty_node(ch):
                note(root_todos, "Форма: MobileDeviceCommandBarContent не поддержан DSL")
        elif ln in FORM_STRUCTURAL_TAGS:
            pass
        else:
            if len(ch) == 0:
                prop_key = PROP_REVERSE.get(ln, ln[0].lower() + ln[1:] if ln else ln)
                properties[prop_key] = sniff_scalar(node_text(ch))
            else:
                note(root_todos, "Форма: сложное свойство " + ln + " не поддержано DSL")

    result = OrderedDict()
    if root_todos:
        result["_todo"] = root_todos
    if title is not None:
        result["title"] = title
    if properties:
        result["properties"] = properties
    if excluded_commands:
        result["excludedCommands"] = excluded_commands
    if events:
        result["events"] = events
    if elements:
        result["elements"] = elements
    if attributes:
        result["attributes"] = attributes
    if parameters:
        result["parameters"] = parameters
    if commands:
        result["commands"] = commands

    json_str = json.dumps(result, ensure_ascii=False, indent=2)

    out_abs = output_path if os.path.isabs(output_path) else os.path.join(os.getcwd(), output_path)
    out_dir = os.path.dirname(out_abs)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(out_abs, "w", encoding="utf-8", newline="") as fh:
        fh.write(json_str + "\n")

    print("[OK] Decompiled: " + output_path)
    print("     Elements: " + str(len(elements)) + ", Attributes: " + str(len(attributes)) + ", Commands: " + str(len(commands)) + ", Parameters: " + str(len(parameters)), file=sys.stderr)
    if TODO_COUNT > 0:
        print("     TODO: " + str(TODO_COUNT) + " - черновик требует ручной доработки (ключи _todo)", file=sys.stderr)


if __name__ == "__main__":
    main()
