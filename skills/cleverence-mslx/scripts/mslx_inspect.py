#!/usr/bin/env python3
"""
mslx_inspect.py - dump and validate a Cleverence Mobile SMARTS .mslx file.

.mslx are single-line XML graphs of Actions (DocumentType) or a single Operation.
Reading them by eye is hard; this tool gives a structured view (actions are indented by
their `indent` attribute, so the Panel nesting is visible at a glance) and catches the
mistakes that actually break the algorithm on the TSD:
  - dangling transitions (a direction points at an action that does not exist)
  - unbalanced QuestionAction button arrays (Buttons / ButtonTexts / ButtonDirections)
  - malformed XML
  - flat structure: logically subordinate actions left at indent=0 (renders wrong in
    the Panel; the indented dump makes this obvious)

Usage:
    python mslx_inspect.py <file.mslx>            # dump + validate (default)
    python mslx_inspect.py <file.mslx> --dump     # only structured dump
    python mslx_inspect.py <file.mslx> --validate # only validation, exit 1 on problems
    python mslx_inspect.py <file.mslx> --names     # just list action names

Set PYTHONIOENCODING=utf-8 on Windows to avoid console encoding errors with Cyrillic.
"""
import sys
import xml.etree.ElementTree as ET

# Directions that are resolved by the platform, not by an action name.
BUILTINS = {
    "", "back", "return", "abort", "exit", "next", "home", "cancel",
    "break", "process zero", "continue", "undo",
}

# Attributes on actions that hold a transition target (an action name or builtin).
DIRECTION_ATTRS = (
    "nextDirection", "yesDirection", "noDirection", "abortDirection",
    "timeoutDirection", "errorDirection", "onAsyncDirection",
    "quantityErrorDirection",
)

ACTION_SUFFIX = "Action"


def local(tag):
    return tag.split("}")[-1]


# Elements whose tag ends with "Action" but which are NOT graph nodes.
NOT_NODES = {"KeyToAction"}


def is_action(el):
    t = local(el.tag)
    return t.endswith(ACTION_SUFFIX) and t not in NOT_NODES


def collect_action_names(root):
    """Names that a transition may legally point to (case-insensitive set)."""
    names = set()
    for el in root.iter():
        if is_action(el):
            n = el.get("name")
            if n:
                names.add(n)
    return names


def gather_references(root):
    """Yield (source_action, attr_or_kind, target) for every transition target."""
    for el in root.iter():
        t = local(el.tag)
        src = el.get("name") or "(unnamed %s)" % t
        if is_action(el):
            for attr in DIRECTION_ATTRS:
                v = el.get(attr)
                if v is not None:
                    yield (src, attr, v)
        if t == "KeyToAction":
            v = el.get("action")
            if v:
                yield ("(KeyJumps)", "KeyToAction.action", v)
        # ButtonDirections live as <String> children of a ButtonDirections element
        if t == "ButtonDirections":
            for child in el:
                yield (src, "ButtonDirections", child.text or "")


def resolve_ok(target, names_lower):
    return target.lower() in names_lower or target.lower() in {b.lower() for b in BUILTINS}


def dump(root):
    print("ROOT <%s> name=%r" % (local(root.tag), root.get("name")))
    interesting = {
        "name", "operationName", "nextDirection", "yesDirection", "noDirection",
        "abortDirection", "expression", "fieldName", "text", "message",
        "sessionVariable",
    }
    for el in root.iter():
        if not is_action(el):
            continue
        t = local(el.tag)
        attrs = {local(k): v for k, v in el.attrib.items()}
        shown = {k: attrs[k] for k in attrs if k in interesting}
        # Trim long expressions/messages for readability.
        for k in ("expression", "message", "text"):
            if k in shown and len(shown[k]) > 90:
                shown[k] = shown[k][:90] + "..."
        # In/Out mapping for OperationAction.
        io = {}
        for grp in ("InKeys", "InValues", "OutKeys", "OutValues"):
            vals = [c.text for e in el for c in e if local(e.tag) == grp]
            if vals:
                io[grp] = vals
        # indent = visual nesting depth in the Panel algorithm tree. Subordinate actions
        # must sit deeper than their parent (indent > parent); a flat indent=0 on logically
        # nested actions renders the structure wrong in the Panel. We indent the dump by it
        # so a flat/broken structure is visible at a glance.
        try:
            depth = int(attrs.get("indent", "0") or "0")
        except ValueError:
            depth = 0
        line = "  %s[%s]" % ("  " * depth, t)
        for k in ("name", "operationName", "fieldName"):
            if shown.get(k):
                line += " %s=%r" % (k, shown[k])
        for k in ("nextDirection", "yesDirection", "noDirection", "abortDirection"):
            if shown.get(k):
                line += " %s=%r" % (k, shown[k])
        for k in ("expression", "message", "text", "sessionVariable"):
            if shown.get(k):
                line += " %s=%r" % (k, shown[k])
        if depth:
            line += " indent=%d" % depth
        if io:
            line += " " + " ".join("%s=%s" % (k, v) for k, v in io.items())
        print(line)


def validate(root):
    problems = []
    names = collect_action_names(root)
    names_lower = {n.lower() for n in names}

    # 1. dangling transitions
    for src, kind, target in gather_references(root):
        if not resolve_ok(target, names_lower):
            problems.append("DANGLING: %s.%s -> %r (no such action)" % (src, kind, target))

    # 2. QuestionAction button-array balance
    for el in root.iter():
        if local(el.tag) != "QuestionAction":
            continue
        arrays = {}
        for child in el:
            tag = local(child.tag)
            if tag in ("Buttons", "ButtonTexts", "ButtonDirections"):
                arrays[tag] = len(list(child))
        if arrays and len(set(arrays.values())) > 1:
            problems.append(
                "BUTTON IMBALANCE in QuestionAction %r: %s"
                % (el.get("name"), arrays)
            )
    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        sys.exit(2)
    path = args[0]

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        print("XML PARSE ERROR: %s" % e)
        sys.exit(1)
    root = tree.getroot()

    if "--names" in flags:
        for n in sorted(n for n in collect_action_names(root) if n):
            print(n)
        return

    do_dump = "--validate" not in flags or "--dump" in flags
    do_validate = "--dump" not in flags or "--validate" in flags

    if do_dump:
        dump(root)
    if do_validate:
        problems = validate(root)
        print("\n=== VALIDATION ===")
        if not problems:
            print("OK: XML valid, all transitions resolve, button arrays balanced.")
        else:
            for p in problems:
                print("  " + p)
            sys.exit(1)


if __name__ == "__main__":
    main()
