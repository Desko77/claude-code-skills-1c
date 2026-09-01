#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Строит реестр тем прикладного слоя БСП по документации и сверяет покрытие.

Реестр отвечает на два вопроса: какие темы вообще есть и все ли они разобраны.
Он же служит счетчиком: работа закончена, когда у каждой строки стоит отметка.

Источник тем - глава 3 документации БСП ("Настройка и использование подсистем
при разработке конфигурации"). Именно она описывает применение, а не состав
библиотеки (глава 1), внедрение (глава 2) или программный интерфейс (глава 4,
он уже сведен в справочник `1c-bsp-api`).

Тема берется из хлебных крошек файла: третий уровень крошки - название раздела
главы 3. Разделять три разных понятия обязательно, иначе реестр смешивает
несравнимое:

  - РАЗДЕЛ ДОКУМЕНТАЦИИ - то, что дает эта глава;
  - ПОДСИСТЕМА МЕТАДАННЫХ - то, что видно в конфигурации;
  - МЕХАНИЗМ - то, вокруг чего пишется сценарий.

Связь между ними не один к одному: длительные операции это механизм внутри
базовой функциональности, а не отдельная подсистема.

Обратная сверка обязательна. Счет "N из N" по собственному реестру доказывает
лишь, что заполнены строки, которые сам и завел. Поэтому каждый файл главы 3
обеих версий сопоставляется с темой, а файлы без темы выводятся отдельно.

Использование:
  python tools/build_bsp_registry.py \
      --docs "3.1.11=<путь к markdown-скрапу>" --docs "3.2.1=<путь>" \
      --prototype <путь к references прообраза> \
      --out <путь к реестру.md>

Скрап документации лицензионный, в репозиторий не входит и передается путем.

Коды возврата: 0 реестр построен, 2 ошибка запуска.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

RE_CRUMB = re.compile(r'^- "(.*)"\s*$')
RE_CHAPTER3 = re.compile(r"^Глава\s+3\.", re.IGNORECASE)

# Шкала приоритета из плана. 1 - механизм нужен почти в любой доработке,
# 2 - в проектах определенного профиля, 3 - узкие и служебные механизмы.
# Ключ - точное название раздела главы 3; неназванное получает 2 по умолчанию,
# потому что молча ронять тему в конец очереди нельзя.
PRIORITY = {
    1: (
        "Базовая функциональность", "Пользователи", "Управление доступом",
        "Обновление версии ИБ", "Обновление конфигурации",
        "Печать", "Работа с файлами", "Регламентные задания",
        "Варианты отчетов", "Даты запрета изменения",
        "Запрет редактирования реквизитов объектов", "Свойства",
        "Подключаемые команды", "Дополнительные отчеты и обработки",
        "Версионирование объектов", "Префиксация объектов",
    ),
    3: (
        "Резервное копирование ИБ", "Центр мониторинга", "Оценка производительности",
        "Контроль работы пользователей", "Завершение работы пользователей",
        "Профили безопасности", "Анкетирование", "Обсуждения",
        "Управление итогами и агрегатами", "Полнотекстовый поиск", "Работа в модели сервиса",
    ),
}


def crumbs(path: Path) -> list[str]:
    """Прочитать хлебные крошки из frontmatter файла документации.

    Читается только заголовок файла: полный текст для реестра не нужен, а
    файлов тысячи.
    """
    out: list[str] = []
    inside = False
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("breadcrumb:"):
                inside = True
                continue
            if inside:
                m = RE_CRUMB.match(line)
                if m:
                    out.append(m.group(1))
                else:
                    break
    return out


def collect(docs_dir: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Собрать темы главы 3: название раздела -> файлы, плюс файлы без темы.

    Файлом без темы считается тот, у кого крошка обрывается на самой главе:
    у него нет раздела, к которому его отнести. Такие файлы выводятся в отчет,
    а не пропадают: обратная сверка на них и держится.
    """
    topics: dict[str, list[str]] = {}
    orphans: list[str] = []
    for name in sorted(os.listdir(docs_dir)):
        if not name.endswith(".md"):
            continue
        chain = crumbs(docs_dir / name)
        if not any(RE_CHAPTER3.match(c) for c in chain):
            continue
        if len(chain) >= 3:
            topics.setdefault(chain[2], []).append(name)
        else:
            orphans.append(name)
    return topics, orphans


def slug(title: str) -> str:
    """Канонический идентификатор темы: устойчивый ключ, не зависящий от версии.

    Название раздела между версиями меняется (перенос слова, уточнение), а
    идентификатор должен остаться прежним, иначе тема задвоится в реестре.
    """
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
        "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y",
        "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    out = []
    for ch in title.lower():
        if ch in table:
            out.append(table[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    text = re.sub(r"-+", "-", "".join(out)).strip("-")
    return text[:48]


def priority_of(title: str) -> int:
    """Приоритет темы по шкале плана; неназванное получает 2."""
    for level, names in PRIORITY.items():
        if title in names:
            return level
    return 2


def prototype_map(path: Path | None) -> dict[str, str]:
    """Карта покрытия прообраза: имя файла -> его заголовок.

    Из прообраза берется ТОЛЬКО перечень имен и первый заголовок каждого файла:
    имена английские, и без заголовка сопоставить их с русскими разделами
    документации нечем. Текст оттуда не читается и не пересказывается -
    справочники пишутся по документации и исходникам библиотеки.
    """
    out: dict[str, str] = {}
    if path is None or not path.is_dir():
        return out
    for p in sorted(path.glob("*.md")):
        title = ""
        with io.open(p, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        out[p.stem] = title
    return out


def words(text: str) -> set[str]:
    """Значимые слова названия для сопоставления тем разных источников."""
    return {w for w in re.split(r"[^А-Яа-яЁёA-Za-z]+", text.lower())
            if len(w) > 4}


def match_prototype(title: str, proto: dict[str, str]) -> str:
    """Найти файл прообраза, покрывающий эту тему, по пересечению слов заголовка.

    Сопоставление по словам, а не по имени файла: имена у прообраза английские,
    а заголовки русские. Пересечения в одно значимое слово достаточно - карта
    покрытия нужна как подсказка "тема где-то разобрана", а не как точный ключ.
    """
    mine = words(title)
    if not mine:
        return ""
    best, best_score = "", 0
    for stem, proto_title in proto.items():
        score = len(mine & words(proto_title))
        if score > best_score:
            best, best_score = stem, score
    return best if best_score else ""


def main() -> int:
    """Точка входа: собрать реестр по версиям и записать его файлом."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--docs", action="append", required=True,
                        metavar="ВЕРСИЯ=ПУТЬ",
                        help="каталог markdown-скрапа документации, по одному на версию")
    parser.add_argument("--prototype", default=None,
                        help="каталог references прообраза (только перечень имен)")
    parser.add_argument("--out", required=True, help="куда записать реестр")
    args = parser.parse_args()

    versions: dict[str, tuple[dict[str, list[str]], list[str]]] = {}
    for item in args.docs:
        version, _, path = item.partition("=")
        if not path:
            print("--docs ждет ВЕРСИЯ=ПУТЬ, получено: %s" % item, file=sys.stderr)
            return 2
        docs_dir = Path(path)
        if not docs_dir.is_dir():
            print("нет каталога документации: %s" % docs_dir, file=sys.stderr)
            return 2
        versions[version] = collect(docs_dir)

    proto = prototype_map(Path(args.prototype) if args.prototype else None)

    all_titles: dict[str, dict] = {}
    for version, (topics, _orphans) in versions.items():
        for title, files in topics.items():
            row = all_titles.setdefault(slug(title), {"title": title, "files": {}})
            row["files"][version] = len(files)
            # Название могло измениться между версиями - оставляем более позднее.
            row["title"] = title

    lines: list[str] = []
    lines.append("# Реестр тем прикладного слоя БСП")
    lines.append("")
    lines.append("Построен `tools/build_bsp_registry.py` по главе 3 документации.")
    lines.append("Отметка: `-` не начата, `в работе`, `готово`, `вне набора: причина`.")
    lines.append("")
    header = ["идентификатор", "тема"] + ["файлов " + v for v in versions] + \
             ["приоритет", "прообраз", "отметка"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))

    matched: set[str] = set()
    for key in sorted(all_titles, key=lambda k: (priority_of(all_titles[k]["title"]),
                                                 all_titles[k]["title"])):
        row = all_titles[key]
        counts = [str(row["files"].get(v, 0)) for v in versions]
        proto_hit = match_prototype(row["title"], proto)
        matched.add(proto_hit)
        lines.append("| `%s` | %s | %s | %d | %s | - |"
                     % (key, row["title"], " | ".join(counts),
                        priority_of(row["title"]),
                        ("`%s`" % proto_hit) if proto_hit else ""))

    lines.append("")
    lines.append("## Обратная сверка")
    lines.append("")
    total_files = 0
    for version, (topics, orphans) in versions.items():
        files_in_topics = sum(len(f) for f in topics.values())
        total_files += files_in_topics + len(orphans)
        lines.append("- **%s**: разделов %d, файлов в разделах %d, без раздела %d"
                     % (version, len(topics), files_in_topics, len(orphans)))
        for name in orphans:
            lines.append("  - без раздела: `%s`" % name)
    lines.append("")
    lines.append("Тем всего: **%d**. Файлов главы 3 учтено: **%d**." % (len(all_titles), total_files))

    known_titles = {row["title"] for row in all_titles.values()}
    unknown_priority = sorted(name for names in PRIORITY.values() for name in names
                              if name not in known_titles)
    if unknown_priority:
        lines.append("")
        lines.append("**Имена в шкале приоритета, которых нет среди тем** (приоритет назначен "
                     "в пустоту): "
                     + ", ".join("`%s`" % n for n in unknown_priority))

    only_proto = sorted(p for p in proto if p not in matched)
    if only_proto:
        lines.append("")
        lines.append("Есть у прообраза, не сопоставлено с темой (разобрать явно): "
                     + ", ".join("`%s`" % p for p in only_proto))

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("реестр записан: %s" % args.out)
    print("тем: %d, файлов учтено: %d" % (len(all_titles), total_files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
