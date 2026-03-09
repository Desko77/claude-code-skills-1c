# skd-validate v1.0 — Validate 1C DCS structure (Python port)
# Source: https://github.com/Desko77/claude-code-skills-1c
import argparse
import os
import sys

from lxml import etree

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── arg parsing ──────────────────────────────────────────────

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("-TemplatePath", required=True)
parser.add_argument("-MaxErrors", type=int, default=20)
parser.add_argument("-OutFile", default="")
args = parser.parse_args()

template_path = args.TemplatePath
max_errors = args.MaxErrors
out_file = args.OutFile

# ── resolve path ─────────────────────────────────────────────

if not template_path.endswith(".xml"):
    candidate = os.path.join(template_path, "Ext", "Template.xml")
    if os.path.exists(candidate):
        template_path = candidate

if not os.path.exists(template_path):
    print(f"File not found: {template_path}", file=sys.stderr)
    sys.exit(1)

resolved_path = os.path.abspath(template_path)
file_name = os.path.basename(resolved_path)

# ── output infrastructure ────────────────────────────────────

errors = 0
warnings = 0
stopped = False
output_lines = []


def out_line(msg):
    output_lines.append(msg)


def report_ok(msg):
    out_line(f"[OK]    {msg}")


def report_error(msg):
    global errors, stopped
    errors += 1
    out_line(f"[ERROR] {msg}")
    if errors >= max_errors:
        stopped = True


def report_warn(msg):
    global warnings
    warnings += 1
    out_line(f"[WARN]  {msg}")


def finalize():
    out_line("")
    out_line(f"=== Result: {errors} errors, {warnings} warnings ===")
    result = "\n".join(output_lines)
    print(result)
    if out_file:
        with open(out_file, "w", encoding="utf-8-sig") as f:
            f.write(result)
        print(f"Written to: {out_file}")


out_line(f"=== Validation: {file_name} ===")
out_line("")

# ── 1. Parse XML ─────────────────────────────────────────────

NS = {
    "s": "http://v8.1c.ru/8.1/data-composition-system/schema",
    "dcscom": "http://v8.1c.ru/8.1/data-composition-system/common",
    "dcscor": "http://v8.1c.ru/8.1/data-composition-system/core",
    "dcsset": "http://v8.1c.ru/8.1/data-composition-system/settings",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "v8ui": "http://v8.1c.ru/8.1/data/ui",
    "xs": "http://www.w3.org/2001/XMLSchema",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "dcsat": "http://v8.1c.ru/8.1/data-composition-system/area-template",
}

XSI_TYPE = f"{{{NS['xsi']}}}type"

tree = None
try:
    parser_xml = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(resolved_path, parser_xml)
    report_ok("XML parsed successfully")
except Exception as e:
    report_error(f"XML parse failed: {e}")
    result = "\n".join(output_lines)
    print(result)
    if out_file:
        with open(out_file, "w", encoding="utf-8-sig") as f:
            f.write(result)
    sys.exit(1)

root = tree.getroot()


def local_name(node):
    return etree.QName(node.tag).localname


def find(parent, xpath):
    """XPath find with namespaces, returns first match or None."""
    r = parent.xpath(xpath, namespaces=NS)
    return r[0] if r else None


def find_all(parent, xpath):
    """XPath findall with namespaces."""
    return parent.xpath(xpath, namespaces=NS)


def text_of(node):
    """Return stripped text or empty string."""
    if node is None:
        return ""
    return (node.text or "").strip()


def inner_text(node):
    """Return text (non-stripped) or empty string."""
    if node is None:
        return ""
    return node.text or ""

# ── 3. Root element checks ───────────────────────────────────

if local_name(root) != "DataCompositionSchema":
    report_error(f"Root element is '{local_name(root)}', expected 'DataCompositionSchema'")
else:
    report_ok("Root element: DataCompositionSchema")

expected_ns = "http://v8.1c.ru/8.1/data-composition-system/schema"
root_ns = etree.QName(root.tag).namespace or ""
if root_ns != expected_ns:
    report_error(f"Default namespace is '{root_ns}', expected '{expected_ns}'")
else:
    report_ok("Default namespace correct")

if stopped:
    finalize()
    sys.exit(1)

# ── 4. Collect inventories ───────────────────────────────────

# DataSources
data_source_nodes = find_all(root, "s:dataSource")
data_source_names = {}
for dsn in data_source_nodes:
    name = find(dsn, "s:name")
    if name is not None:
        data_source_names[inner_text(name)] = True

# DataSets (recursive for unions)
data_set_nodes = find_all(root, "s:dataSet")
data_set_names = {}
all_field_paths = {}  # dataPath -> dataSet name


def collect_data_set_fields(ds_node, ds_name):
    fields = find_all(ds_node, "s:field")
    local_paths = {}
    for f in fields:
        dp = find(f, "s:dataPath")
        if dp is not None:
            path = inner_text(dp)
            local_paths[path] = True
            all_field_paths[path] = ds_name
    # Union items
    items = find_all(ds_node, "s:item")
    for item in items:
        item_name = find(item, "s:name")
        if item_name is not None:
            collect_data_set_fields(item, inner_text(item_name))
    return local_paths


data_set_field_map = {}
for ds in data_set_nodes:
    name_node = find(ds, "s:name")
    if name_node is not None:
        ds_name = inner_text(name_node)
        data_set_names[ds_name] = True
        data_set_field_map[ds_name] = collect_data_set_fields(ds, ds_name)

# CalculatedFields
calc_field_nodes = find_all(root, "s:calculatedField")
calc_field_paths = {}
for cf in calc_field_nodes:
    dp = find(cf, "s:dataPath")
    if dp is not None:
        calc_field_paths[inner_text(dp)] = True

# TotalFields
total_field_nodes = find_all(root, "s:totalField")

# Parameters
param_nodes = find_all(root, "s:parameter")
param_names = {}
for p in param_nodes:
    name_node = find(p, "s:name")
    if name_node is not None:
        param_names[inner_text(name_node)] = True

# Templates
template_nodes = find_all(root, "s:template")
template_names = {}
for t in template_nodes:
    name_node = find(t, "s:name")
    if name_node is not None:
        template_names[inner_text(name_node)] = True

# GroupTemplates
group_template_nodes = find_all(root, "s:groupTemplate")

# SettingsVariants
variant_nodes = find_all(root, "s:settingsVariant")

# Known fields = dataset fields + calculated fields
known_fields = {}
for key in all_field_paths:
    known_fields[key] = True
for key in calc_field_paths:
    known_fields[key] = True

# ── 5. DataSource checks ─────────────────────────────────────

if len(data_source_nodes) == 0:
    report_warn("No dataSource elements found (settings-only DCS?)")
else:
    ds_names_seen = {}
    ds_ok = True
    for dsn in data_source_nodes:
        name = find(dsn, "s:name")
        typ = find(dsn, "s:dataSourceType")
        if name is None or not inner_text(name):
            report_error("DataSource has empty name")
            ds_ok = False
        elif inner_text(name) in ds_names_seen:
            report_error(f"Duplicate dataSource name: {inner_text(name)}")
            ds_ok = False
        else:
            ds_names_seen[inner_text(name)] = True
        if typ is not None:
            tv = inner_text(typ)
            if tv not in ("Local", "External"):
                report_warn(f"DataSource '{inner_text(name)}' has unusual type: {tv}")
    if ds_ok:
        report_ok(f"{len(data_source_nodes)} dataSource(s) found, names unique")

if stopped:
    finalize()
    sys.exit(1)

# ── 6. DataSet checks ────────────────────────────────────────

valid_ds_types = ("DataSetQuery", "DataSetObject", "DataSetUnion")

if len(data_set_nodes) == 0:
    report_warn("No dataSet elements found (settings-only DCS?)")
else:
    ds_names_seen = {}
    ds_ok = True
    for ds in data_set_nodes:
        xsi_type = ds.get(XSI_TYPE, "")
        name_node = find(ds, "s:name")
        ds_name = inner_text(name_node) if name_node is not None else "(unnamed)"

        if name_node is None or not inner_text(name_node):
            report_error("DataSet has empty name")
            ds_ok = False
        elif ds_name in ds_names_seen:
            report_error(f"Duplicate dataSet name: {ds_name}")
            ds_ok = False
        else:
            ds_names_seen[ds_name] = True

        if not xsi_type:
            report_error(f"DataSet '{ds_name}' missing xsi:type")
            ds_ok = False
        elif xsi_type not in valid_ds_types:
            report_warn(f"DataSet '{ds_name}' has unusual xsi:type: {xsi_type}")

        # Check dataSource reference
        if xsi_type != "DataSetUnion":
            src_node = find(ds, "s:dataSource")
            if src_node is not None and inner_text(src_node):
                if inner_text(src_node) not in data_source_names:
                    report_error(f"DataSet '{ds_name}' references unknown dataSource: {inner_text(src_node)}")
                    ds_ok = False

        # Check query not empty for Query type
        if xsi_type == "DataSetQuery":
            query_node = find(ds, "s:query")
            if query_node is None or not text_of(query_node):
                report_warn(f"DataSet '{ds_name}' (Query) has empty query")

        # Check objectName for Object type
        if xsi_type == "DataSetObject":
            obj_node = find(ds, "s:objectName")
            if obj_node is None or not text_of(obj_node):
                report_error(f"DataSet '{ds_name}' (Object) has empty objectName")
                ds_ok = False

    if ds_ok:
        report_ok(f"{len(data_set_nodes)} dataSet(s) found, names unique")

if stopped:
    finalize()
    sys.exit(1)

# ── 7. Field checks ──────────────────────────────────────────


def check_data_set_fields(ds_node, ds_name):
    global stopped
    fields = find_all(ds_node, "s:field")
    if len(fields) == 0:
        return

    paths_seen = {}
    field_ok = True

    for f in fields:
        dp = find(f, "s:dataPath")
        fn = find(f, "s:field")

        if dp is None or not inner_text(dp):
            report_error(f"DataSet '{ds_name}': field has empty dataPath")
            field_ok = False
            continue

        path = inner_text(dp)
        if path in paths_seen:
            report_warn(f"DataSet '{ds_name}': duplicate dataPath '{path}'")
        else:
            paths_seen[path] = True

        if fn is None or not inner_text(fn):
            report_warn(f"DataSet '{ds_name}': field '{path}' has empty <field> element")

    if field_ok:
        report_ok(f'DataSet "{ds_name}": {len(fields)} fields, dataPath unique')

    # Check union items recursively
    items = find_all(ds_node, "s:item")
    for item in items:
        item_name = find(item, "s:name")
        i_name = inner_text(item_name) if item_name is not None else "(unnamed item)"
        check_data_set_fields(item, i_name)


for ds in data_set_nodes:
    name_node = find(ds, "s:name")
    ds_name = inner_text(name_node) if name_node is not None else "(unnamed)"
    check_data_set_fields(ds, ds_name)

if stopped:
    finalize()
    sys.exit(1)

# ── 8. DataSetLink checks ────────────────────────────────────

link_nodes = find_all(root, "s:dataSetLink")
if len(link_nodes) > 0:
    link_ok = True
    for link in link_nodes:
        src = find(link, "s:sourceDataSet")
        dst = find(link, "s:destinationDataSet")
        src_expr = find(link, "s:sourceExpression")
        dst_expr = find(link, "s:destinationExpression")

        if src is not None and inner_text(src) and inner_text(src) not in data_set_names:
            report_error(f"DataSetLink: sourceDataSet '{inner_text(src)}' not found")
            link_ok = False
        if dst is not None and inner_text(dst) and inner_text(dst) not in data_set_names:
            report_error(f"DataSetLink: destinationDataSet '{inner_text(dst)}' not found")
            link_ok = False
        if src_expr is None or not text_of(src_expr):
            report_error("DataSetLink: empty sourceExpression")
            link_ok = False
        if dst_expr is None or not text_of(dst_expr):
            report_error("DataSetLink: empty destinationExpression")
            link_ok = False
    if link_ok:
        report_ok(f"{len(link_nodes)} dataSetLink(s): references valid")

if stopped:
    finalize()
    sys.exit(1)

# ── 9. CalculatedField checks ────────────────────────────────

if len(calc_field_nodes) > 0:
    cf_ok = True
    cf_seen = {}
    for cf in calc_field_nodes:
        dp = find(cf, "s:dataPath")
        expr = find(cf, "s:expression")

        if dp is None or not inner_text(dp):
            report_error("CalculatedField has empty dataPath")
            cf_ok = False
            continue

        path = inner_text(dp)
        if path in cf_seen:
            report_error(f"Duplicate calculatedField dataPath: {path}")
            cf_ok = False
        else:
            cf_seen[path] = True

        if expr is None or not text_of(expr):
            report_error(f"CalculatedField '{path}' has empty expression")
            cf_ok = False

        # Warn if collides with a dataset field
        if path in all_field_paths:
            report_warn(f"CalculatedField '{path}' shadows dataSet field in '{all_field_paths[path]}'")

    if cf_ok:
        report_ok(f"{len(calc_field_nodes)} calculatedField(s): dataPath and expression valid")

if stopped:
    finalize()
    sys.exit(1)

# ── 10. TotalField checks ────────────────────────────────────

if len(total_field_nodes) > 0:
    tf_ok = True
    for tf in total_field_nodes:
        dp = find(tf, "s:dataPath")
        expr = find(tf, "s:expression")

        if dp is None or not inner_text(dp):
            report_error("TotalField has empty dataPath")
            tf_ok = False
            continue

        if expr is None or not text_of(expr):
            report_error(f"TotalField '{inner_text(dp)}' has empty expression")
            tf_ok = False

    if tf_ok:
        report_ok(f"{len(total_field_nodes)} totalField(s): dataPath and expression present")

if stopped:
    finalize()
    sys.exit(1)

# ── 11. Parameter checks ─────────────────────────────────────

if len(param_nodes) > 0:
    param_ok = True
    param_seen = {}
    for p in param_nodes:
        name_node = find(p, "s:name")
        if name_node is None or not inner_text(name_node):
            report_error("Parameter has empty name")
            param_ok = False
            continue
        p_name = inner_text(name_node)
        if p_name in param_seen:
            report_error(f"Duplicate parameter name: {p_name}")
            param_ok = False
        else:
            param_seen[p_name] = True
    if param_ok:
        report_ok(f"{len(param_nodes)} parameter(s): names unique")

if stopped:
    finalize()
    sys.exit(1)

# ── 12. Template checks ──────────────────────────────────────

if len(template_nodes) > 0:
    tpl_ok = True
    tpl_seen = {}
    for t in template_nodes:
        name_node = find(t, "s:name")
        if name_node is None or not inner_text(name_node):
            report_error("Template has empty name")
            tpl_ok = False
            continue
        t_name = inner_text(name_node)
        if t_name in tpl_seen:
            report_error(f"Duplicate template name: {t_name}")
            tpl_ok = False
        else:
            tpl_seen[t_name] = True
    if tpl_ok:
        report_ok(f"{len(template_nodes)} template(s): names unique")

# ── 13. GroupTemplate checks ─────────────────────────────────

if len(group_template_nodes) > 0:
    gt_ok = True
    valid_tpl_types = ("Header", "Footer", "Overall", "OverallHeader", "OverallFooter")
    for gt in group_template_nodes:
        tpl_ref = find(gt, "s:template")
        tpl_type = find(gt, "s:templateType")

        if tpl_ref is not None and inner_text(tpl_ref) and inner_text(tpl_ref) not in template_names:
            report_error(f"GroupTemplate references unknown template: {inner_text(tpl_ref)}")
            gt_ok = False
        if tpl_type is not None and inner_text(tpl_type) not in valid_tpl_types:
            report_warn(f"GroupTemplate has unusual templateType: {inner_text(tpl_type)}")
    if gt_ok:
        report_ok(f"{len(group_template_nodes)} groupTemplate(s): references valid")

if stopped:
    finalize()
    sys.exit(1)

# ── 14. Settings helper functions ─────────────────────────────

valid_comparison_types = (
    "Equal", "NotEqual", "Greater", "GreaterOrEqual", "Less", "LessOrEqual",
    "InList", "NotInList", "InHierarchy", "InListByHierarchy",
    "Contains", "NotContains", "BeginsWith", "NotBeginsWith",
    "Filled", "NotFilled",
)

valid_structure_types = (
    "dcsset:StructureItemGroup",
    "dcsset:StructureItemTable",
    "dcsset:StructureItemChart",
    "dcsset:StructureItemNestedObject",
)


def check_filter_items(parent_node, variant_name):
    global stopped
    filter_items = find_all(parent_node, "dcsset:filter/dcsset:item")
    for fi in filter_items:
        if stopped:
            return
        xsi_type = fi.get(XSI_TYPE, "")
        if xsi_type == "dcsset:FilterItemComparison":
            comp_type = find(fi, "dcsset:comparisonType")
            if comp_type is not None and inner_text(comp_type) not in valid_comparison_types:
                report_error(f"Variant '{variant_name}' filter: invalid comparisonType '{inner_text(comp_type)}'")
        elif xsi_type == "dcsset:FilterItemGroup":
            group_type = find(fi, "dcsset:groupType")
            if group_type is not None:
                valid_group_types = ("AndGroup", "OrGroup", "NotGroup")
                if inner_text(group_type) not in valid_group_types:
                    report_warn(f"Variant '{variant_name}' filter group: unusual groupType '{inner_text(group_type)}'")
            # Recurse into nested items
            nested_items = find_all(fi, "dcsset:item")
            for ni in nested_items:
                ni_type = ni.get(XSI_TYPE, "")
                if ni_type == "dcsset:FilterItemComparison":
                    comp_type = find(ni, "dcsset:comparisonType")
                    if comp_type is not None and inner_text(comp_type) not in valid_comparison_types:
                        report_error(f"Variant '{variant_name}' filter: invalid comparisonType '{inner_text(comp_type)}'")


def check_structure_item(item_node, variant_name):
    global stopped
    if stopped:
        return

    xsi_type = item_node.get(XSI_TYPE, "")
    if not xsi_type:
        report_error(f"Variant '{variant_name}': structure item missing xsi:type")
        return
    if xsi_type not in valid_structure_types:
        report_warn(f"Variant '{variant_name}': unusual structure item type '{xsi_type}'")

    # Recurse into nested items (groups can contain groups)
    nested_items = find_all(item_node, "dcsset:item")
    for ni in nested_items:
        check_structure_item(ni, variant_name)

    # Check column/row in tables
    if xsi_type == "dcsset:StructureItemTable":
        columns = find_all(item_node, "dcsset:column")
        rows = find_all(item_node, "dcsset:row")
        if len(columns) == 0:
            report_warn(f"Variant '{variant_name}': table has no columns")
        if len(rows) == 0:
            report_warn(f"Variant '{variant_name}': table has no rows")


def check_settings(settings_node, variant_name):
    global stopped
    if stopped:
        return

    # Selection
    sel_items = find_all(settings_node, "dcsset:selection/dcsset:item")
    for si in sel_items:
        xsi_type = si.get(XSI_TYPE, "")
        if xsi_type == "dcsset:SelectedItemField":
            field = find(si, "dcsset:field")
            if field is not None and inner_text(field) and inner_text(field) != "SystemFields.Number":
                base_path = inner_text(field).split(".")[0]
                if inner_text(field) not in known_fields and base_path not in known_fields:
                    pass  # Soft check — autoFillFields may add fields not listed explicitly

    # Filter
    check_filter_items(settings_node, variant_name)

    # Order
    order_items = find_all(settings_node, "dcsset:order/dcsset:item")
    for oi in order_items:
        xsi_type = oi.get(XSI_TYPE, "")
        if xsi_type == "dcsset:OrderItemField":
            order_type = find(oi, "dcsset:orderType")
            if order_type is not None and inner_text(order_type) not in ("Asc", "Desc"):
                report_warn(f"Variant '{variant_name}' order: invalid orderType '{inner_text(order_type)}'")

    # Structure items
    struct_items = find_all(settings_node, "dcsset:item")
    for si in struct_items:
        check_structure_item(si, variant_name)


# ── 15. SettingsVariant checks ────────────────────────────────

if len(variant_nodes) == 0:
    report_warn("No settingsVariant elements found")
else:
    v_ok = True
    v_idx = 0
    for v in variant_nodes:
        v_idx += 1
        v_name = find(v, "dcsset:name")
        if v_name is None or not inner_text(v_name):
            report_error(f"SettingsVariant #{v_idx} has empty name")
            v_ok = False

        settings = find(v, "dcsset:settings")
        if settings is None:
            report_error(f"SettingsVariant '{inner_text(v_name) if v_name is not None else ''}' has no settings element")
            v_ok = False
            continue

        # Check settings internals
        check_settings(settings, inner_text(v_name) if v_name is not None else "")

    if v_ok:
        report_ok(f"{len(variant_nodes)} settingsVariant(s) found")

# ── Final output ──────────────────────────────────────────────

finalize()

if errors > 0:
    sys.exit(1)
sys.exit(0)
