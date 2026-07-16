#!/usr/bin/env python3
# support-state v1.0 - Read and switch 1C configuration support state in XML dump
# Source: https://github.com/Desko77/claude-code-skills-1c

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

BOM = b"\xef\xbb\xbf"
F1_BY_STATE = {"editable": "1", "off-support": "2", "locked": "0"}
STATE_BY_F1 = {
    "0": "locked (на замке, правка запрещена)",
    "1": "editable (редактируется с сохранением поддержки)",
    "2": "off-support (снят с поддержки)",
}
VENDOR_HEADER_RE = re.compile(
    r'([0-9a-f-]{36}),\d+,([0-9a-f-]{36}),"((?:[^"]|"")*)","((?:[^"]|"")*)","((?:[^"]|"")*)",(\d+)'
)


def root_uuid(xml_path):
    """uuid первого дочернего элемента корня XML-файла объекта."""
    if not os.path.isfile(xml_path):
        return None
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return None
    for child in tree.getroot():
        u = child.get("uuid")
        if u:
            return u
    return None


def resolve_target(target_path):
    """Возвращает (elem_uuid, cfg_dir, bin_path, is_extension, rp)."""
    if not os.path.exists(target_path):
        print(f"Error: path not found: {target_path}", file=sys.stderr)
        sys.exit(1)
    rp = os.path.abspath(target_path)
    elem_uuid = root_uuid(rp) if os.path.isfile(rp) else None
    cfg_dir = None
    bin_path = None
    d = rp if os.path.isdir(rp) else os.path.dirname(rp)
    for _ in range(12):
        if elem_uuid is None:
            # -Path мог указывать на каталог объекта: рядом лежит одноименный <Имя>.xml
            elem_uuid = root_uuid(d + ".xml")
        if cfg_dir is None:
            cand_bin = os.path.join(d, "Ext", "ParentConfigurations.bin")
            cfg_xml = os.path.join(d, "Configuration.xml")
            if os.path.isfile(cand_bin) or os.path.isfile(cfg_xml):
                cfg_dir = d
                bin_path = cand_bin
        if elem_uuid and cfg_dir:
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if cfg_dir is None:
        print(f"Error: configuration root (Configuration.xml) not found above: {rp}", file=sys.stderr)
        sys.exit(1)
    if elem_uuid is None:
        elem_uuid = root_uuid(os.path.join(cfg_dir, "Configuration.xml"))
    is_extension = False
    cfg_xml_path = os.path.join(cfg_dir, "Configuration.xml")
    if os.path.isfile(cfg_xml_path):
        try:
            with open(cfg_xml_path, "r", encoding="utf-8-sig", errors="replace") as f:
                is_extension = "ConfigurationExtensionPurpose" in f.read()
        except OSError:
            pass
    return elem_uuid, cfg_dir, bin_path, is_extension, rp


def read_bin(bin_path):
    """Текст .bin без BOM или None, если поддержка снята полностью (файл-огрызок)."""
    with open(bin_path, "rb") as f:
        raw = f.read()
    if len(raw) <= 32:
        return None
    if raw.startswith(BOM):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def save_bin(bin_path, text):
    with open(bin_path, "wb") as f:
        f.write(BOM + text.encode("utf-8"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Read and switch 1C configuration support state in XML dump",
        allow_abbrev=False,
    )
    parser.add_argument("-Path", required=True)
    parser.add_argument("-Get", action="store_true")
    parser.add_argument("-Set", choices=["editable", "off-support", "locked"], default="")
    parser.add_argument("-Capability", choices=["on", "off"], default="")
    args = parser.parse_args()

    chosen = (1 if args.Get else 0) + (1 if args.Set else 0) + (1 if args.Capability else 0)
    if chosen == 0:
        args.Get = True
    elif chosen > 1:
        print("Error: specify only one of -Get, -Set, -Capability", file=sys.stderr)
        sys.exit(1)

    elem_uuid, cfg_dir, bin_path, is_extension, rp = resolve_target(args.Path)

    if is_extension:
        print("Это расширение конфигурации - состояние поддержки не применимо.")
        sys.exit(0)
    if not os.path.isfile(bin_path):
        print("Конфигурация не на поддержке (нет Ext/ParentConfigurations.bin) - переключать нечего.")
        sys.exit(0)

    text = read_bin(bin_path)
    if text is None:
        print("Поддержка снята полностью (пустой ParentConfigurations.bin).")
        sys.exit(0)

    m = re.match(r"^\{6,(\d+),(\d+),", text)
    if not m:
        print("Error: неизвестный формат ParentConfigurations.bin", file=sys.stderr)
        sys.exit(1)
    g, k = m.group(1), m.group(2)

    if args.Get:
        if g == "1":
            print("Возможность изменения конфигурации: ВЫКЛЮЧЕНА (вся конфигурация read-only)")
        else:
            print("Возможность изменения конфигурации: включена")
        print(f"Конфигураций поставщика на поддержке: {k}")
        for i, mm in enumerate(VENDOR_HEADER_RE.finditer(text), 1):
            ver = mm.group(3).replace('""', '"')
            vendor = mm.group(4).replace('""', '"')
            name = mm.group(5).replace('""', '"')
            print(f"  {i}. {name} ({vendor}), версия {ver}, записей: {mm.group(6)}")
        if elem_uuid:
            u = re.escape(elem_uuid.lower())
            found = re.findall(r"(?<![0-9a-f-])([0-2]),0," + u, text)
            if found:
                eff = min(found)
                note = f" (по вхождениям: {','.join(found)})" if len(set(found)) > 1 else ""
                print(f"Объект {elem_uuid}: вхождений {len(found)}, правило: {STATE_BY_F1[eff]}{note}")
            else:
                print(f"Объект {elem_uuid}: не найден в поддержке (свое добавление)")
        sys.exit(0)

    if args.Capability:
        target = "0" if args.Capability == "on" else "1"
        if g == target:
            print("Уже в целевом состоянии - изменения не требуются.")
            sys.exit(0)
        text = re.sub(r"^(\{6,)\d+(,)", r"\g<1>" + target + r"\g<2>", text)
        # заголовок каждого блока поставщика: guidA,X,guidVendor - X следует за G
        text = re.sub(r"([0-9a-f-]{36}),\d+,([0-9a-f-]{36})", r"\1," + target + r",\2", text)
        text = re.sub(r"(?<![0-9a-f-])[0-2],0,([0-9a-f-]{36})", target + r",0,\1", text)
        save_bin(bin_path, text)
        if args.Capability == "on":
            print("Возможность изменения конфигурации ВКЛЮЧЕНА. Все объекты поставщика - на замке.")
            print("Дальше включай правку точечно: -Set editable по нужным объектам.")
        else:
            print("Возможность изменения конфигурации ВЫКЛЮЧЕНА. Вся конфигурация read-only, пообъектные правила сброшены.")
        sys.exit(0)

    # -Set
    if g == "1":
        print("Возможность изменения конфигурации выключена - пообъектное переключение недоступно.", file=sys.stderr)
        print(f'Сначала: -Path "{args.Path}" -Capability on', file=sys.stderr)
        sys.exit(1)
    if not elem_uuid:
        print(f"Error: не удалось определить объект по пути: {rp}", file=sys.stderr)
        sys.exit(1)
    u_low = elem_uuid.lower()
    u = re.escape(u_low)
    vals = re.findall(r"(?<![0-9a-f-])([0-2]),0," + u, text)
    n = len(vals)
    if n == 0:
        print("Объект не найден в поддержке (свое добавление) - переключать нечего.")
        sys.exit(0)
    new_f1 = F1_BY_STATE[args.Set]
    if set(vals) == {new_f1}:
        print("Объект уже в целевом состоянии - изменения не требуются.")
        sys.exit(0)
    text = re.sub(r"(?<![0-9a-f-])[0-2],0," + u, new_f1 + ",0," + u_low, text)
    save_bin(bin_path, text)
    print(f"Объект {elem_uuid} -> {STATE_BY_F1[new_f1]}")
    print(f"Изменено записей: {n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
