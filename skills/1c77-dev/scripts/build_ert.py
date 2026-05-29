#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка (компиляция) .ert / 1Cv7.MD из исходников через GComp (7.7).

Вызывает gcomp.exe напрямую через subprocess - Python на Windows передаёт Unicode-аргументы
корректно, кириллица в путях не теряется (в отличие от Bash, где gcomp молча выходит с EXIT 0
и ничего не собирает).

Делает бэкап целевого файла (gcomp перезаписывает молча) и проверяет, что результат реально
изменился (timestamp/размер). Если не изменился - сигнализирует об ошибке: значит аргументы
не дошли до gcomp.

Примеры:
  python build_ert.py --out ВыгрузкаИзТис77.ert --src ./PUBID_NNNN-ВыгрузкаИзТис77
  python build_ert.py --out report.ert --src ./report_src --truncate-mms
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

DEFAULT_GCOMP_CANDIDATES = [
    r"C:\Program Files\GComp\Release\gcomp.exe",
    r"C:\Tools\gcomp\gcomp.exe",
    r"C:\1Cv77\BIN\gcomp.exe",
]


def find_gcomp(explicit):
    if explicit:
        return explicit
    env = os.environ.get("GCOMP_EXE")
    if env and Path(env).exists():
        return env
    for c in DEFAULT_GCOMP_CANDIDATES:
        if Path(c).exists() and (Path(c).parent / "GComp.dll").exists():
            return c
    return None


def run_gcomp(gcomp, args):
    cmd = [gcomp] + args
    print("RUN:", " ".join(f'"{a}"' if " " in a else a for a in cmd), file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True)
    for stream in (proc.stdout, proc.stderr):
        if stream:
            try:
                print(stream.decode("cp866"))
            except Exception:
                print(stream.decode("cp1251", errors="replace"))
    return proc.returncode


def stat_of(path):
    if Path(path).exists():
        st = Path(path).stat()
        return (st.st_size, st.st_mtime)
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="целевой .ert (или 1cv7.md)")
    p.add_argument("--src", required=True, help="каталог исходников (-DD)")
    p.add_argument("--meta-data", action="store_true", help="собираем файл конфигурации 1cv7.md")
    p.add_argument("--external-report", action="store_true", help="явно указать .ert")
    p.add_argument("--truncate-mms", action="store_true", help="заменить Main MetaData Stream на пустой")
    p.add_argument("--no-backup", action="store_true", help="не делать бэкап целевого файла")
    p.add_argument("--gcomp", help="путь к gcomp.exe (иначе автопоиск рабочего)")
    p.add_argument("--extra", nargs=argparse.REMAINDER, help="доп. флаги GComp как есть")
    a = p.parse_args()

    out = Path(a.out).resolve()
    src = Path(a.src).resolve()
    if not src.is_dir():
        sys.exit(f"Каталог исходников не найден: {src}")

    gcomp = find_gcomp(a.gcomp)
    if not gcomp:
        sys.exit("Рабочий gcomp.exe не найден. Укажи --gcomp <путь к Release\\gcomp.exe>.")

    before = stat_of(out)
    if before and not a.no_backup:
        bak = f"{out}.bak_{date.today().strftime('%Y%m%d')}"
        shutil.copy2(out, bak)
        print(f"Бэкап: {bak}", file=sys.stderr)

    args = ["-c", "-F", str(out), "-DD", str(src)]
    if a.meta_data:
        args.append("--meta-data")
    if a.external_report:
        args.append("--external-report")
    if a.truncate_mms:
        args.append("--truncate-mms")
    if a.extra:
        args += a.extra

    rc = run_gcomp(gcomp, args)
    print(f"EXIT={rc}", file=sys.stderr)
    if rc != 0:
        sys.exit(rc)

    time.sleep(0.2)
    after = stat_of(out)
    if after is None:
        sys.exit("ОШИБКА: целевой файл не создан.")
    if before is not None and after == before:
        sys.exit("ОШИБКА: файл не изменился (size/mtime те же). Аргументы не дошли до GComp - проверь пути.")
    print(f"OK: {out.name} -> {after[0]} байт, mtime обновлён.", file=sys.stderr)


if __name__ == "__main__":
    main()
