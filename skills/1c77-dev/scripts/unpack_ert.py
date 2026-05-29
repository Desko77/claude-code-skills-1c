#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разбор (декомпиляция) .ert / 1Cv7.MD в текстовые исходники через GComp (7.7).

Вызывает gcomp.exe напрямую через subprocess: Python на Windows передаёт Unicode-аргументы
корректно (CreateProcessW), поэтому кириллица в путях не бьётся - в отличие от запуска из Bash.

По умолчанию ищет рабочий GComp в стандартных местах (с GComp.dll рядом). "Голый" gcomp.exe
из каталогов проекта не годится - падает с STATUS_DLL_NOT_FOUND.

Примеры:
  python unpack_ert.py ВыгрузкаИзТис77.ert --dest ./src_unpacked
  python unpack_ert.py 1Cv7.MD --meta-data --dest ./conf_src
"""
import argparse
import os
import subprocess
import sys
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
        if Path(c).exists():
            # рядом должна быть GComp.dll, иначе exe не запустится
            if (Path(c).parent / "GComp.dll").exists():
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", help="исходный .ert или 1Cv7.MD")
    p.add_argument("--dest", help="каталог назначения (-DD). Без него GComp создаёт SRC\\<имя>")
    p.add_argument("--meta-data", action="store_true", help="работаем с файлом конфигурации 1cv7.md")
    p.add_argument("--external-report", action="store_true", help="явно указать .ert")
    p.add_argument("--gcomp", help="путь к gcomp.exe (иначе автопоиск рабочего)")
    p.add_argument("--extra", nargs=argparse.REMAINDER, help="доп. флаги GComp как есть")
    a = p.parse_args()

    src = Path(a.file).resolve()
    if not src.exists():
        sys.exit(f"Файл не найден: {src}")

    gcomp = find_gcomp(a.gcomp)
    if not gcomp:
        sys.exit("Рабочий gcomp.exe не найден. Укажи --gcomp <путь к Release\\gcomp.exe>.")

    args = ["-d", "-F", str(src)]
    if a.dest:
        Path(a.dest).mkdir(parents=True, exist_ok=True)
        args += ["-DD", str(Path(a.dest).resolve())]
    if a.meta_data:
        args.append("--meta-data")
    if a.external_report:
        args.append("--external-report")
    if a.extra:
        args += a.extra

    rc = run_gcomp(gcomp, args)
    print(f"EXIT={rc}", file=sys.stderr)
    if rc != 0:
        sys.exit(rc)
    print("Разбор завершён.", file=sys.stderr)


if __name__ == "__main__":
    main()
