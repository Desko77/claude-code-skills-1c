#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проставляет признак устаревания в готовый справочник API БСП.

Зачем отдельный шаг. Признак устаревания нужен структурным: искать слово
"устаревший" в тексте назначения нельзя, потому что устаревший метод
упоминается и в описаниях ДРУГИХ методов - предупреждение сработало бы ложно.
А полная пересборка справочника через `bsp-build.py` требует двух лицензионных
источников (скрап документации и дистрибутив библиотеки), которых в репозитории
нет и которые нужны редко.

Поэтому список устаревших вызовов ведется вручную в разделе `deprecated` файла
`references/purposes.json`, а этот скрипт переносит его в готовый
`references/bsp-api.jsonl` полем `dep` со значением замены. Скрипт идемпотентен:
повторный прогон по тому же списку ничего не меняет.

Использование:
  python tools/stamp_deprecated.py                 применить и переписать справочник
  python tools/stamp_deprecated.py --check         только проверить, ничего не писать

Коды возврата: 0 справочник согласован со списком, 1 расхождение при --check,
2 ошибка запуска.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

REPO_ROOT = Path(__file__).resolve().parent.parent
REFS = REPO_ROOT / "skills" / "1c-bsp-api" / "references"
PURPOSES = REFS / "purposes.json"
INDEX = REFS / "bsp-api.jsonl"


def load_deprecated(path: Path = PURPOSES) -> dict[str, str]:
    """Прочитать раздел deprecated: вызов -> чем заменять.

    Пустой словарь, если раздела нет: это не ошибка, а состояние набора,
    в котором устаревших вызовов пока не отмечено.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("не читается %s: %s" % (path, exc))
    section = payload.get("deprecated", {})
    if not isinstance(section, dict):
        raise SystemExit("раздел deprecated в %s должен быть объектом" % path)
    return {str(k): str(v) for k, v in section.items()}


def stamp(index_path: Path, deprecated: dict[str, str], write: bool) -> tuple[int, list[str]]:
    """Проставить поле dep по списку и вернуть (сколько записей затронуто, расхождения).

    Расхождением считается имя из списка, которого в справочнике нет: это либо
    опечатка, либо метод, убранный в новой версии библиотеки. Такое имя нельзя
    оставлять молча - оно означает, что список разошелся со справочником.
    """
    wanted = {k.lower(): v for k, v in deprecated.items()}
    seen: set[str] = set()
    lines: list[str] = []
    touched = 0

    with index_path.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            record = json.loads(raw)
            module, name = record.get("m"), record.get("n")
            if module and name:
                key = ("%s.%s" % (module, name)).lower()
                replacement = wanted.get(key)
                if replacement:
                    seen.add(key)
                    if record.get("dep") != replacement:
                        record["dep"] = replacement
                        touched += 1
                elif "dep" in record:
                    # Вызов убрали из списка - снимаем и признак, иначе справочник
                    # будет предупреждать о том, что списком уже не считается устаревшим.
                    record.pop("dep")
                    touched += 1
            lines.append(json.dumps(record, ensure_ascii=False))

    missing = sorted(k for k in wanted if k not in seen)
    if write and touched:
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return touched, missing


def main() -> int:
    """Точка входа: применить список устаревших к справочнику либо проверить согласованность."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="только проверить согласованность, не писать файл")
    parser.add_argument("--purposes", default=str(PURPOSES))
    parser.add_argument("--index", default=str(INDEX))
    args = parser.parse_args()

    index_path = Path(args.index)
    if not index_path.is_file():
        print("нет справочника: %s" % index_path, file=sys.stderr)
        return 2

    deprecated = load_deprecated(Path(args.purposes))
    touched, missing = stamp(index_path, deprecated, write=not args.check)

    print("устаревших в списке: %d" % len(deprecated))
    for name in missing:
        print("  РАСХОЖДЕНИЕ: %s есть в списке, но нет в справочнике" % name, file=sys.stderr)

    if args.check:
        if touched or missing:
            print("справочник не согласован со списком: записей к правке %d, расхождений %d"
                  % (touched, len(missing)), file=sys.stderr)
            return 1
        print("справочник согласован со списком")
        return 0

    print("записей обновлено: %d" % touched)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
