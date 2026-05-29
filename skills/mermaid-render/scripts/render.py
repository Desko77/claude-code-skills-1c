"""Рендер mermaid-диаграмм в PNG/SVG/PDF через локальный mmdc (mermaid-cli).

Поддержка:
- .mmd / .mermaid - один входной файл с диаграммой
- .md - извлекает все блоки ```mermaid и рендерит каждый отдельным файлом

Под капотом - mermaid-cli (npm i -g @mermaid-js/mermaid-cli), без MCP и Docker.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path

VALID_THEMES = {"default", "forest", "dark", "neutral"}
VALID_FORMATS = {"png", "svg", "pdf"}
MD_EXTS = {".md", ".markdown"}
MMD_EXTS = {".mmd", ".mermaid"}


def resolve_mmdc() -> str:
    """Найти исполняемый mmdc (.cmd на Windows, .js обёртку на Unix)."""
    for cand in ("mmdc.cmd", "mmdc"):
        path = shutil.which(cand)
        if path:
            return path
    sys.stderr.write(
        "ERROR: mmdc не найден в PATH.\n"
        "Установите: npm install -g @mermaid-js/mermaid-cli\n"
    )
    sys.exit(2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Рендер mermaid-диаграмм в PNG/SVG/PDF через mmdc.",
    )
    p.add_argument("input", help="Путь к .mmd / .mermaid / .md файлу")
    p.add_argument("-o", "--output",
                   help="Путь к выходному файлу. Если не указан - рядом с входом.")
    p.add_argument("-t", "--theme", default="default", choices=sorted(VALID_THEMES),
                   help="Тема диаграммы (default)")
    p.add_argument("-b", "--bg", default="white",
                   help="Цвет фона: white, transparent, '#F0F0F0' (default: white)")
    p.add_argument("-f", "--format", default="png", choices=sorted(VALID_FORMATS),
                   help="Формат вывода (default: png)")
    p.add_argument("-w", "--width", type=int, default=None,
                   help="Ширина в пикселях (mmdc default: 800)")
    p.add_argument("-H", "--height", type=int, default=None,
                   help="Высота в пикселях (mmdc default: 600)")
    p.add_argument("-s", "--scale", type=int, default=2,
                   help="Puppeteer scale factor (default: 2 для retina)")
    p.add_argument("--quiet", action="store_true", default=True,
                   help="Подавить логи mmdc (default: вкл)")
    p.add_argument("--verbose", action="store_true",
                   help="Показать вывод mmdc (отменяет --quiet)")
    return p.parse_args()


def determine_output(input_path: Path, output: str | None, fmt: str) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    return input_path.with_suffix(f".{fmt}")


def list_outputs(output: Path, is_markdown: bool) -> list[Path]:
    """mmdc для .md создаёт <stem>-1.<ext>, <stem>-2.<ext> и т.д."""
    if not is_markdown:
        return [output] if output.exists() else []
    pattern = f"{output.with_suffix('').name}-*{output.suffix}"
    matches = sorted(output.parent.glob(pattern))
    return matches if matches else ([output] if output.exists() else [])


def main() -> int:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        sys.stderr.write(f"ERROR: входной файл не найден - {input_path}\n")
        return 2

    ext = input_path.suffix.lower()
    is_markdown = ext in MD_EXTS
    is_mermaid = ext in MMD_EXTS
    if not (is_markdown or is_mermaid):
        sys.stderr.write(
            f"ERROR: неподдерживаемое расширение '{ext}'. "
            f"Ожидается .mmd, .mermaid, .md\n"
        )
        return 2

    output_path = determine_output(input_path, args.output, args.format)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mmdc = resolve_mmdc()
    cmd = [
        mmdc,
        "-i", str(input_path),
        "-o", str(output_path),
        "-t", args.theme,
        "-b", args.bg,
        "-e", args.format,
        "-s", str(args.scale),
    ]
    if args.width:
        cmd += ["-w", str(args.width)]
    if args.height:
        cmd += ["-H", str(args.height)]
    if args.quiet and not args.verbose:
        cmd.append("--quiet")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        sys.stderr.write(f"ERROR: не удалось запустить mmdc - {e}\n")
        return 2

    if result.returncode != 0:
        sys.stderr.write("ERROR: mmdc вернул ненулевой код\n")
        if result.stdout:
            sys.stderr.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode

    if args.verbose and result.stdout:
        sys.stdout.write(result.stdout)

    outputs = list_outputs(output_path, is_markdown)
    if not outputs:
        sys.stderr.write(
            "WARN: mmdc отработал успешно, но выходных файлов не обнаружено. "
            "Возможно в .md нет блоков ```mermaid.\n"
        )
        return 1

    print(f"Готово: создано файлов - {len(outputs)}")
    for p in outputs:
        size_kb = p.stat().st_size / 1024
        print(f"  {p}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
