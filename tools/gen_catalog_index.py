#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор индекса, сводной детекторов и каталожных секций правил из карточек дефектов.

Читает карточки skills/1c-code-review/references/catalog/<ИДЕНТИФИКАТОР>.md, проверяет
обязательные поля и пишет:

- catalog/INDEX.md - таблица идентификатор, важность, группа, архетипы, детекторы, триггер;
- skills/1c-code-review/references/detectors.md - сводная матрица детекторов и строка покрытия
  (детекторы bsl_validate вне реестра реализованных правил
  skills/1c-bsl-validate/scripts/catalog-rules.json помечаются planned, в покрытие не входят);
- секции между маркерами catalog:begin / catalog:end в rules/anti_patterns.md (таблица
  триггеров с колонкой псевдонима) и rules/code-review-checklist.md (таблица по группам).

Вне маркеров файлы правил не меняются. Одинаковый вход дает одинаковый выход: сортировка
по идентификатору, генерация одной строкой на строку таблицы.

Раздел "Детекторы" карточки - таблица "Среда | Детектор | Уровень" из словаря спецификации
(docs/1c-defect-catalog-spec.md, раздел "Детекторы"); при "чтение" в среде EDT обязательна
строка "Обоснование чтения: ...". Генератор сверяет детектор со словарем, уровень -
со словарем, идентификатор правила lint - с идентификатором карточки.

Режим --check ничего не пишет и выходит с кодом 1, если сгенерированное отличается от
файлов на диске.

Запуск:  python tools/gen_catalog_index.py [--check]
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "skills" / "1c-code-review" / "references" / "catalog"
INDEX = CATALOG / "INDEX.md"
DETECTORS_MD = ROOT / "skills" / "1c-code-review" / "references" / "detectors.md"
LINT_REGISTRY = ROOT / "skills" / "1c-bsl-validate" / "scripts" / "catalog-rules.json"
RULE_TARGETS = {
    ROOT / "rules" / "anti_patterns.md": "anti",
    ROOT / "rules" / "code-review-checklist.md": "checklist",
}

BEGIN = "<!-- catalog:begin -->"
END = "<!-- catalog:end -->"

# Словарь детекторов спецификации: среда -> детектор -> уровень.
# "code_review:*" и "bsl_validate:*" - семейства с параметром (код диагностики,
# идентификатор карточки).
DETECTOR_DICT = {
    "EDT": {
        "code_review:*": "static",
        "get_project_errors": "semantic",
        "validate_query": "semantic",
        "validate_for_export": "semantic",
        "security_audit": "semantic",
        "detect_query_anti_patterns": "static",
        "ask_1c_ai": "llm",
        "чтение": "read",
    },
    "Конфигуратор": {
        "syntaxcheck": "static",
        "bsl_validate:*": "static",
        "query_validate": "static",
        "meta_validate": "static",
        "role_validate": "static",
        "form_validate": "static",
        "чтение": "read",
    },
}
DETERMINISTIC_LEVELS = {"semantic", "static"}


SECTIONS = [
    "Идентификатор и группа",
    "Важность",
    "Триггер",
    "Почему дефект",
    "Законная форма",
    "Как чинить",
    "Детекторы",
    "Архетипы правки",
    "Фикстура",
    "Источник",
]
SEVERITIES = {"Critical", "Major", "Minor"}
GROUPS = {
    "MODEL", "PERF", "QUERY", "TXN", "FORM",
    "CLIENT", "SEC", "EXT", "META", "PROC",
}
FIXTURE_TYPES = {"bsl-pair", "project-tree", "diff", "evidence"}
ARCHETYPES = {
    "транзакция", "блокировка", "права", "запрос", "модуль формы",
    "событие объекта", "новый общий модуль", "перехват в расширении",
    "изменение метаданных", "любой BSL",
}


class CardError(Exception):
    """Нарушение формата карточки или структуры каталога."""


def parse_card(path):
    """Разобрать карточку в словарь полей. Все разделы обязательны и строго по порядку."""
    text = path.read_text(encoding="utf-8")
    heading = re.match(r"^# ([A-Z]+-\d{2})\. (.+)$", text.split("\n", 1)[0])
    if not heading:
        raise CardError("%s: заголовок не вида '# <ИД>. <Заголовок>'" % path.name)
    card_id, title = heading.group(1), heading.group(2)
    if card_id != path.stem:
        raise CardError("%s: идентификатор %s не совпадает с именем файла" % (path.name, card_id))

    chunks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    order = []
    fields = {}
    for chunk in chunks:
        name, _, body = chunk.partition("\n")
        name = name.strip()
        order.append(name)
        fields[name] = body.strip()
    if order != SECTIONS:
        raise CardError(
            "%s: разделы %s не совпадают с требуемым порядком %s"
            % (path.name, order, SECTIONS))

    severity = fields["Важность"].strip()
    if severity not in SEVERITIES:
        raise CardError("%s: важность %s вне шкалы %s" % (path.name, severity, sorted(SEVERITIES)))

    group = card_id.split("-", 1)[0]
    if group not in GROUPS:
        raise CardError("%s: группа %s не входит в список групп" % (path.name, group))

    ident_lines = fields["Идентификатор и группа"].split("\n")
    if not any(line.strip() == "Идентификатор: `%s`" % card_id for line in ident_lines):
        raise CardError("%s: в разделе Идентификатор и группа нет строки Идентификатор" % path.name)
    alias = ""
    for line in ident_lines:
        if line.startswith("Псевдоним:"):
            alias = line.partition(":")[2].strip()

    legal = fields["Законная форма"]
    if not legal or "```" not in legal:
        raise CardError("%s: законная форма пуста или без блока кода" % path.name)

    archetypes = [a.strip() for a in fields["Архетипы правки"].split(",") if a.strip()]
    unknown = [a for a in archetypes if a not in ARCHETYPES]
    if unknown:
        raise CardError("%s: неизвестные архетипы %s" % (path.name, unknown))

    fixture_type = ""
    fixture_match = re.search(r"^Тип: `([a-z-]+)`", fields["Фикстура"], flags=re.MULTILINE)
    if fixture_match:
        fixture_type = fixture_match.group(1)
    if fixture_type not in FIXTURE_TYPES:
        raise CardError("%s: тип фикстуры %s вне списка %s"
                        % (path.name, fixture_type, sorted(FIXTURE_TYPES)))

    trigger = fields["Триггер"].split("\n")[0].strip()

    detectors, justification = parse_detectors(card_id, fields["Детекторы"])

    return {
        "id": card_id,
        "title": title,
        "group": group,
        "alias": alias,
        "severity": severity,
        "trigger": trigger,
        "archetypes": archetypes,
        "detectors": detectors,
        "justification": justification,
        "fixture_type": fixture_type,
    }


def detector_level(env, detector):
    """Уровень детектора по словарю; семейства с параметром задаются как префикс:*."""
    table = DETECTOR_DICT.get(env)
    if table is None:
        return None
    if detector in table:
        return table[detector]
    family, sep, param = detector.partition(":")
    if sep and family + ":*" in table:
        return table[family + ":*"], param
    return None


def parse_detectors(card_id, body):
    """Разобрать таблицу "Среда | Детектор | Уровень" и обоснование чтения."""
    detectors = []
    justification = ""
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Обоснование чтения:"):
            justification = stripped.partition(":")[2].strip()
            continue
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 3 or not cells[0] or set(cells[0]) <= {"-", " "}:
            continue  # пустая строка, разделитель или строка с другим числом колонок
        if cells == ["Среда", "Детектор", "Уровень"]:
            continue  # заголовок таблицы
        env, detector, level = cells
        resolved = detector_level(env, detector)
        if resolved is None:
            raise CardError("%s: детектор %s в среде %s вне словаря" % (card_id, detector, env))
        expected, param = resolved if isinstance(resolved, tuple) else (resolved, "")
        if level != expected:
            raise CardError("%s: уровень %s у детектора %s не совпадает со словарем (%s)"
                            % (card_id, level, detector, expected))
        if detector.startswith("bsl_validate:") and param != card_id:
            raise CardError("%s: правило lint %s не совпадает с идентификатором карточки"
                            % (card_id, detector))
        detectors.append((env, detector, level))
    if not detectors:
        raise CardError("%s: таблица детекторов пуста" % card_id)
    envs = [d[0] for d in detectors]
    if "EDT" not in envs or "Конфигуратор" not in envs:
        raise CardError("%s: в матрице нет обеих сред" % card_id)
    has_edt_read = any(e == "EDT" and d == "чтение" for e, d, _ in detectors)
    if has_edt_read and not justification:
        raise CardError("%s: чтение в среде EDT без строки 'Обоснование чтения:'" % card_id)
    return detectors, justification


def load_cards():
    cards = [parse_card(p) for p in sorted(CATALOG.glob("*.md")) if p.stem != "INDEX"]
    if not cards:
        raise CardError("в %s нет карточек" % CATALOG)
    seen = set()
    for card in cards:
        if card["id"] in seen:
            raise CardError("повтор идентификатора %s" % card["id"])
        seen.add(card["id"])
    return sorted(cards, key=lambda c: c["id"])


def load_lint_registry(cards):
    """Реестр реализованных правил lint скила 1c-bsl-validate.

    Файл skills/1c-bsl-validate/scripts/catalog-rules.json - массив объектов с полями
    id, title, kind (regex | query-regex | structure) и данными правила (pattern+scope
    либо check). Идентификатор обязан называть карточку с детектором bsl_validate:<ИД>:
    запись без карточки или без детектора - ошибка каталога. Детектор bsl_validate:<ИД>
    детерминирован только при наличии <ИД> в реестре; вне реестра в сводной матрице
    он помечается planned и в покрытие не входит.
    """
    if not LINT_REGISTRY.exists():
        raise CardError("нет реестра lint-правил: %s" % LINT_REGISTRY.relative_to(ROOT))
    try:
        rules = json.loads(LINT_REGISTRY.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CardError("реестр lint-правил не разбирается как JSON: %s" % exc)
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        raise CardError("реестр lint-правил - не массив объектов")
    ids = []
    for rule in rules:
        rid = rule.get("id")
        kind = rule.get("kind")
        if not isinstance(rid, str) or not rid:
            raise CardError("реестр lint-правил: запись без id")
        if kind not in ("regex", "query-regex", "structure"):
            raise CardError("реестр lint-правил: %s с kind %s вне словаря" % (rid, kind))
        if kind == "structure" and not rule.get("check"):
            raise CardError("реестр lint-правил: %s без check" % rid)
        if kind in ("regex", "query-regex") and not rule.get("pattern"):
            raise CardError("реестр lint-правил: %s без pattern" % rid)
        ids.append(rid)
    if len(set(ids)) != len(ids):
        raise CardError("реестр lint-правил: повтор идентификатора")
    lint_ids = {c["id"] for c in cards
                if any(d.startswith("bsl_validate:") for _e, d, _l in c["detectors"])}
    unknown = [r for r in ids if r not in lint_ids]
    if unknown:
        raise CardError("реестр lint-правил: %s без карточки с детектором bsl_validate" % unknown)
    return set(ids), lint_ids


def is_deterministic(detector, level, lint_registry):
    """Детерминирован ли детектор: уровень из словаря, lint-правило - только из реестра.

    lint_registry=None снимает ограничение реестра: все bsl_validate считаются
    детерминированными (подсчет "с учетом планируемых lint-правил").
    """
    if level not in DETERMINISTIC_LEVELS:
        return False
    if detector.startswith("bsl_validate:"):
        return lint_registry is None or detector.partition(":")[2] in lint_registry
    return True


def short_detectors(card):
    """Краткая форма колонки INDEX: детекторы по средам через запятую."""
    parts = []
    for env in ("EDT", "Конфигуратор"):
        names = [d for e, d, _lvl in card["detectors"] if e == env]
        parts.append("%s: %s" % (env, ", ".join(names)))
    return "; ".join(parts)


def coverage(cards, lint_registry):
    """Покрытие детерминированными детекторами.

    Возвращает (critical_ok, critical, det_now, det_planned). det_now - карточки
    с детерминированным детектором сейчас: lint-правило учитывается только из реестра
    реализованных. det_planned - то же с учетом всех bsl_validate как планируемых
    lint-правил.
    """
    def deterministic_in(card, env=None, registry=frozenset()):
        return any(is_deterministic(d, lvl, registry) and (env is None or e == env)
                   for e, d, lvl in card["detectors"])

    critical = [c for c in cards if c["severity"] == "Critical"]
    critical_ok = [c for c in critical
                   if deterministic_in(c, "EDT") or c["justification"]]
    det_now = [c for c in cards if deterministic_in(c, registry=lint_registry)]
    det_planned = [c for c in cards if deterministic_in(c, registry=None)]
    return critical_ok, critical, det_now, det_planned


def render_index(cards):
    lines = [
        "# Индекс каталога дефектов",
        "",
        "Генерируется `tools/gen_catalog_index.py` по карточкам каталога; правится только",
        "через карточки. Колонка Триггер - формулировка одной строкой; полные триггер,",
        "законная форма и способ чинить - в карточке с идентичным именем. Сводная матрица",
        "детекторов с уровнями доказательности - references/detectors.md.",
        "",
        "| Идентификатор | Важность | Группа | Архетипы | Детекторы | Триггер |",
        "|---------------|----------|--------|----------|-----------|---------|",
    ]
    for c in cards:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            c["id"], c["severity"], c["group"],
            ", ".join(c["archetypes"]), short_detectors(c), c["trigger"]))
    lines.append("")
    return "\n".join(lines)


def lint_cards(cards):
    """Карточки с детектором bsl_validate - задания для lint-режима скила 1c-bsl-validate."""
    return [c for c in cards
            if any(d.startswith("bsl_validate:") for _e, d, _l in c["detectors"])]


def render_detectors(cards, lint_registry):
    critical_ok, critical, det_now, det_planned = coverage(cards, lint_registry)
    lines = [
        "# Сводная матрица детекторов",
        "",
        "Генерируется `tools/gen_catalog_index.py` по разделу Детекторы карточек каталога;",
        "правится только через карточки. Уровни доказательности и словарь детекторов -",
        "docs/1c-defect-catalog-spec.md, раздел Детекторы. Колонка lint - карточки с детектором",
        "`bsl_validate:<ИД>`: задание для lint-режима скила `1c-bsl-validate`; `planned` -",
        "правило вне реестра реализованных правил, в покрытие не входит. Обоснование чтения",
        "приведено в самой карточке.",
        "",
        "| Карточка | Важность | EDT | Конфигуратор | lint |",
        "|----------|----------|-----|--------------|------|",
    ]
    for c in cards:
        edt = ", ".join("%s (%s)" % (d, lvl) for e, d, lvl in c["detectors"] if e == "EDT")
        conf_parts = []
        for e, d, lvl in c["detectors"]:
            if e != "Конфигуратор":
                continue
            planned = (d.startswith("bsl_validate:")
                       and d.partition(":")[2] not in lint_registry)
            conf_parts.append("%s (%s%s)" % (d, lvl, ", planned" if planned else ""))
        lint = ""
        for _e, d, _l in c["detectors"]:
            if d.startswith("bsl_validate:"):
                lint = ("lint" if d.partition(":")[2] in lint_registry else "planned")
        lines.append("| %s | %s | %s | %s | %s |" % (
            c["id"], c["severity"], edt, ", ".join(conf_parts), lint))
    lines.append("")
    lines.append("Покрытие: Critical с детерминированным детектором в EDT либо с обоснованием"
                 " чтения - %d из %d; с детерминированным детектором хотя бы в одной среде -"
                 " %d из %d (%d%%), с учетом планируемых lint-правил - %d из %d (%d%%)."
                 " Реестр реализованных правил lint - %d из %d карточек"
                 " (`skills/1c-bsl-validate/scripts/catalog-rules.json`)."
                 % (len(critical_ok), len(critical), len(det_now), len(cards),
                    round(100.0 * len(det_now) / len(cards)),
                    len(det_planned), len(cards),
                    round(100.0 * len(det_planned) / len(cards)),
                    len(lint_registry), len(lint_cards(cards))))
    lines.append("")
    return "\n".join(lines)


def render_anti(cards):
    lines = [
        "## Каталог дефектов",
        "",
        "Секция генерируется `tools/gen_catalog_index.py` по карточкам каталога скила",
        "`1c-code-review`; между маркерами не правится. Колонка Псевдоним сохраняет прежнюю",
        "нумерацию пунктов этого файла: ссылки вида п.N читаются по ней. Подробности - в",
        "карточке каталога с тем же идентификатором.",
        "",
        "| Идентификатор | Псевдоним | Важность | Триггер |",
        "|---------------|-----------|----------|---------|",
    ]
    for c in cards:
        alias = c["alias"] if c["alias"] else ""
        lines.append("| %s | %s | %s | %s |" % (c["id"], alias, c["severity"], c["trigger"]))
    lines.append("")
    return "\n".join(lines)


def render_checklist(cards):
    lines = [
        "## Каталог дефектов",
        "",
        "Секция генерируется `tools/gen_catalog_index.py` по карточкам каталога скила",
        "`1c-code-review`; между маркерами не правится. Перевод важности карточек в действия",
        "ревью - `skills/1c-code-review/references/severity.md`.",
        "",
        "| Группа | Идентификатор | Важность | Триггер |",
        "|--------|---------------|----------|---------|",
    ]
    for c in cards:
        lines.append("| %s | %s | %s | %s |" % (c["group"], c["id"], c["severity"], c["trigger"]))
    lines.append("")
    return "\n".join(lines)


RENDERERS = {"anti": render_anti, "checklist": render_checklist}


def replace_section(text, rendered):
    """Заменить содержимое между маркерами, остальной текст не трогать."""
    begin = text.find(BEGIN)
    end = text.find(END)
    if begin == -1 or end == -1 or end < begin:
        raise CardError("маркеры catalog:begin/end не найдены или перепутаны местами")
    head = text[:begin + len(BEGIN)]
    tail = text[end:]
    return head + "\n\n" + rendered + "\n" + tail


def normalize(text):
    return text.replace("\r\n", "\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Генератор индекса каталога дефектов")
    parser.add_argument("--check", action="store_true",
                        help="без записи: выход 1, если файлы отличаются от генерации")
    args = parser.parse_args()

    try:
        cards = load_cards()
        lint_registry, _lint_ids = load_lint_registry(cards)
        outputs = [(INDEX, render_index(cards)),
                   (DETECTORS_MD, render_detectors(cards, lint_registry))]
        for path, kind in RULE_TARGETS.items():
            if not path.exists():
                raise CardError("нет файла правила: %s" % path)
            text = normalize(path.read_text(encoding="utf-8"))
            outputs.append((path, replace_section(text, RENDERERS[kind](cards))))
    except CardError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    stale = []
    for path, content in outputs:
        if args.check:
            disk = normalize(path.read_text(encoding="utf-8")) if path.exists() else ""
            if disk != content:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.write_text(content, encoding="utf-8", newline="\n")

    if args.check:
        if stale:
            print("ОТЛИЧАЕТСЯ ОТ ГЕНЕРАЦИИ:")
            for name in stale:
                print("  %s" % name)
            print("Выполни: python tools/gen_catalog_index.py")
            return 1
        print("OK - индекс, сводная детекторов и каталожные секции совпадают с карточками"
              " (%d шт.)." % len(cards))
        return 0
    print("Записано: %s, %s и секции в %d правилах (%d карточек)."
          % (INDEX.relative_to(ROOT), DETECTORS_MD.relative_to(ROOT),
             len(RULE_TARGETS), len(cards)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
