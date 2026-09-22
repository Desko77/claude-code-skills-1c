#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Каталог событий следа проверок: add, check, render.

Спецификация следа - skills/1c-code-review/references/evidence-format.md, профиль
правки - skills/1c-code-review/references/profile-map.md. Подкоманда add записывает
события skipped, not_verified и probe; записи applied и release пишет только хук -
попытка набрать их через CLI завершается кодом 2. Подкоманда check дает строгий
вердикт прогона (scope с текущим diffHash плюс события с тем же хешем), render
печатаает markdown-отчет по тому же прогону.

Использование:
  python tools/evidence.py add --repo <каталог> --session <id> [--base <коммит>] --type ...
  python tools/evidence.py check [--strict] --repo <каталог> --session <id> [--base <коммит>]
  python tools/evidence.py render --repo <каталог> --session <id> [--base <коммит>]

Коды выхода check: 0 clean, 1 with_gaps, 3 blocked, 2 ошибка вызова.
Коды выхода add и render: 0 выполнено, 2 ошибка вызова.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8", newline="\n")
        except (ValueError, OSError):
            pass

_TOOLS_DIR = Path(__file__).resolve().parent


def _load_tool(name: str):
    """Импортировать модуль tools/ по пути файла: tools/ не пакет."""
    spec = importlib.util.spec_from_file_location(name, _TOOLS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changeset = _load_tool("changeset")
quality_events = _load_tool("quality_events")

# Типы, которые CLI не записывает: их пишет только хук (evidence-format.md).
HOOK_ONLY_TYPES = ("applied", "release")
PROBE_SOURCES = ("ai-edt", "naparnik", "script")

# Источник проверки для требования probe ok: среда детектора (evidence-format.md).
CHECK_SOURCES = {
    "code_review": "ai-edt",
    "validate_query": "ai-edt",
    "validate_for_export": "ai-edt",
    "get_project_errors": "ai-edt",
    "security_audit": "ai-edt",
    "ask_1c_ai": "naparnik",
    "syntaxcheck": "script",
    "bsl_validate": "script",
    "query_validate": "script",
    "meta_validate": "script",
    "role_validate": "script",
}

VERDICT_TITLES = {"clean": "чисто", "with_gaps": "с пробелами", "blocked": "заблокировано"}


def _parse_moment(value) -> datetime | None:
    """Разобрать момент ISO 8601 с зоной; без зоны или не ISO - None."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def evaluate(repo_dir: Path | str, session: str, base: str = "HEAD") -> dict:
    """Строгий вердикт прогона: clean, with_gaps либо blocked с причинами.

    Прогон - последнее scope с текущим diffHash и события с тем же хешем после него
    (quality_events.select_run). Возвращает словарь: verdict, reasons (блокирующие),
    gaps (проверки, закрытые пропуском или снятием), checks (проверка -> способ
    закрытия), required, probes, notVerified, scope, diffHash, session.
    """
    cs = changeset.compute_changeset(repo_dir, base)
    current = cs["diffHash"]
    events = quality_events.read_events(repo_dir, session)
    reasons: list[str] = []
    for event in events:
        if event.get("type") == "corrupt":
            reasons.append(f"поврежденный файл события: {event.get('file')}: "
                           f"{event.get('error')}")
    run = quality_events.select_run(events, current)
    if run is None:
        reasons.append("нет scope с текущим diffHash: прогон устарел или не создан")

    # Снятия сканируются по всему каталогу сессии: чужой diffHash и просроченность -
    # невалидный прогон независимо от отбора прогона.
    released_checks: set[str] = set()
    gate_released = False
    for event in events:
        if event.get("type") != "release":
            continue
        if event.get("diffHash") != current:
            reasons.append(f"release с чужим diffHash: {event.get('_file')}")
            continue
        expires = _parse_moment(event.get("expiresAt"))
        if expires is None or expires <= datetime.now().astimezone():
            reasons.append(f"просроченное release: {event.get('_file')}")
            continue
        if event.get("scope") == "gate":
            gate_released = True
        elif event.get("scope") == "check" and event.get("check"):
            released_checks.add(event["check"])

    applied_ok: dict[str, dict] = {}
    applied_critical: dict[str, dict] = {}
    skipped_ok: dict[str, dict] = {}
    not_verified: list[dict] = []
    probes_ok: set[str] = set()
    run_events = run["events"] if run else []

    for event in run_events:
        etype = event.get("type")
        if etype == "applied":
            check = event.get("check")
            if not check:
                reasons.append(f"applied без check: {event.get('_file')}")
                continue
            if not event.get("toolUseId"):
                reasons.append(f"applied без toolUseId: {check} ({event.get('_file')})")
                continue
            outcome = event.get("outcome")
            status = outcome.get("status") if isinstance(outcome, dict) else None
            if status not in ("pass", "findings", "error"):
                reasons.append(f"applied без итога: {check} ({event.get('_file')})")
                continue
            if status == "error":
                continue  # выполнено с отказом: проверку не закрывает
            critical = outcome.get("critical") or 0
            if status == "pass" or critical == 0:
                applied_ok[check] = event
            else:
                applied_critical[check] = event
        elif etype == "skipped":
            check = event.get("check")
            skip_class = event.get("class")
            if not check:
                reasons.append(f"skipped без check: {event.get('_file')}")
            elif skip_class == "tool_unavailable":
                ref = event.get("ref")
                target = next((e for e in run_events if e.get("_file") == ref), None)
                ref_ok = (target is not None and target.get("type") == "failed") or (
                    target is not None and target.get("type") == "probe"
                    and target.get("status") == "down")
                if not ref_ok:
                    reasons.append(f"пропуск без ссылки на failed или probe down: "
                                   f"{check} ({event.get('_file')})")
                else:
                    skipped_ok[check] = event
            elif skip_class == "not_applicable":
                if not event.get("reason"):
                    reasons.append(f"пропуск без причины: {check} ({event.get('_file')})")
                else:
                    skipped_ok[check] = event
            else:
                reasons.append(f"пропуск без класса: {check} ({event.get('_file')})")
        elif etype == "probe":
            if event.get("status") == "ok" and event.get("source") in PROBE_SOURCES:
                probes_ok.add(event["source"])
        elif etype == "not_verified":
            not_verified.append(event)

    required = run["scope"].get("required", []) if run else []
    checks: dict[str, dict] = {}
    gaps: list[str] = []
    for check in required:
        # Неснятый applied с critical проверяется первым: пропуск или позднее
        # applied без critical ту же проверку не закрывают (evidence-format.md).
        if check in applied_critical:
            if check in released_checks or gate_released:
                checks[check] = {"closedBy": "release", "critical": True}
                gaps.append(check)
            else:
                reasons.append(f"applied с critical без снятия: {check}")
        elif check in applied_ok:
            checks[check] = {"closedBy": "applied", "event": applied_ok[check]}
        elif check in skipped_ok:
            checks[check] = {"closedBy": "skipped", "event": skipped_ok[check]}
            gaps.append(check)
        elif check in released_checks or gate_released:
            checks[check] = {"closedBy": "release", "critical": False}
            gaps.append(check)
        else:
            reasons.append(f"обязательная проверка без события: {check}")

    needed_sources = set()
    for info in checks.values():
        if info["closedBy"] == "applied":
            source = CHECK_SOURCES.get(info["event"]["check"].split("@")[0])
            if source:
                needed_sources.add(source)
    for source in sorted(needed_sources - probes_ok):
        reasons.append(f"нет probe ok по источнику: {source}")

    verdict = "blocked" if reasons else ("with_gaps" if gaps else "clean")
    return {"verdict": verdict, "reasons": reasons, "gaps": gaps, "checks": checks,
            "required": required, "probes": sorted(probes_ok),
            "notVerified": not_verified, "scope": run["scope"] if run else None,
            "diffHash": current, "session": session}


def _outcome_detail(event: dict) -> str:
    """Итог applied-события одной строкой: статус и числа находок."""
    outcome = event.get("outcome") or {}
    status = outcome.get("status", "-")
    if status != "findings":
        return str(status)
    return (f"findings (critical {outcome.get('critical', 0)}, "
            f"major {outcome.get('major', 0)}, minor {outcome.get('minor', 0)})")


def render_report(result: dict) -> str:
    """Markdown-отчет прогона: вердикт, три таблицы, пробелы с классами."""
    lines = ["# След проверок", "",
             f"Сессия: {result['session']}",
             f"diffHash: {result['diffHash']}",
             f"Вердикт: {result['verdict']}", ""]
    if result["reasons"]:
        lines.append("## Блокирующие причины")
        lines.extend(f"- {reason}" for reason in result["reasons"])
        lines.append("")

    lines.extend(["## Проверено", "| Проверка | Итог | Источник |", "|---|---|---|"])
    verified = 0
    for check, info in result["checks"].items():
        if info["closedBy"] != "applied":
            continue
        source = CHECK_SOURCES.get(check.split("@")[0])
        if source and source in result["probes"]:
            source_note = f"{source}, probe ok"
        else:
            source_note = source or "-"
        lines.append(f"| {check} | {_outcome_detail(info['event'])} | {source_note} |")
        verified += 1
    if not verified:
        lines.append("| - | - | - |")

    lines.extend(["", "## С пробелами",
                  "| Проверка | Чем закрыта | Класс или причина |", "|---|---|---|"])
    listed = 0
    for check in result["gaps"]:
        info = result["checks"].get(check, {})
        if info.get("closedBy") == "skipped":
            event = info.get("event", {})
            why = event.get("reason") or f"ref: {event.get('ref')}"
            lines.append(f"| {check} | skipped | {event.get('class')}: {why} |")
        else:
            lines.append(f"| {check} | release | снятие человеком |")
        listed += 1
    if not listed:
        lines.append("| - | - | - |")

    lines.extend(["", "## Не проверено",
                  "| Проверка или измерение | Причина |", "|---|---|"])
    missing = [check for check in result["required"] if check not in result["checks"]]
    rows = [f"| {check} | нет события |" for check in missing]
    rows.extend(f"| {event.get('dimension', '-')} (not_verified) | "
                f"{event.get('reason', '-')}" for event in result["notVerified"])
    lines.extend(rows or ["| - | - |"])
    return "\n".join(lines)


def cmd_add(args: argparse.Namespace) -> int:
    """Подкоманда add: записать skipped, not_verified либо probe; applied и release - отказ."""
    if args.type in HOOK_ONLY_TYPES:
        print(f"отказ: тип {args.type} через CLI не записывается, его пишет только хук",
              file=sys.stderr)
        return 2
    event = {"type": args.type, "session": args.session, "producer": "cli"}
    if args.type == "skipped":
        if not args.check:
            print("ошибка: skipped требует --check", file=sys.stderr)
            return 2
        if args.skip_class == "tool_unavailable":
            if not args.ref:
                print("ошибка: tool_unavailable требует --ref (событие failed или probe down)",
                      file=sys.stderr)
                return 2
        elif args.skip_class == "not_applicable":
            if not args.reason:
                print("ошибка: not_applicable требует --reason", file=sys.stderr)
                return 2
        else:
            print("ошибка: класс пропуска - tool_unavailable либо not_applicable",
                  file=sys.stderr)
            return 2
        event.update({"check": args.check, "class": args.skip_class})
        if args.ref:
            event["ref"] = args.ref
        if args.reason:
            event["reason"] = args.reason
    elif args.type == "not_verified":
        if not args.dimension or not args.reason:
            print("ошибка: not_verified требует --dimension и --reason", file=sys.stderr)
            return 2
        event.update({"dimension": args.dimension, "reason": args.reason})
    else:  # probe
        if args.source not in PROBE_SOURCES:
            print(f"ошибка: источник probe - один из {', '.join(PROBE_SOURCES)}",
                  file=sys.stderr)
            return 2
        if args.status not in ("ok", "down"):
            print("ошибка: статус probe - ok либо down", file=sys.stderr)
            return 2
        event.update({"source": args.source, "status": args.status})
        if args.detail:
            event["detail"] = args.detail
    try:
        cs = changeset.compute_changeset(args.repo, args.base)
        event.update({"at": quality_events.now_iso(), "diffHash": cs["diffHash"]})
        path = quality_events.write_event(args.repo, args.session, event)
    except (changeset.ChangesetError, quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Подкоманда check: строгий вердикт; коды 0/1/3, ошибка вызова - 2."""
    try:
        result = evaluate(args.repo, args.session, args.base)
    except (changeset.ChangesetError, quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    print(f"вердикт: {VERDICT_TITLES[result['verdict']]}")
    print(f"diffHash: {result['diffHash']}")
    for reason in result["reasons"]:
        print(f"блокирует: {reason}")
    for gap in result["gaps"]:
        print(f"пробел: {gap}")
    return {"clean": 0, "with_gaps": 1, "blocked": 3}[result["verdict"]]


def cmd_render(args: argparse.Namespace) -> int:
    """Подкоманда render: markdown-отчет прогона; код 0 при любом вердикте."""
    try:
        result = evaluate(args.repo, args.session, args.base)
    except (changeset.ChangesetError, quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    print(render_report(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI с подкомандами add, check, render."""
    parser = argparse.ArgumentParser(
        description="Каталог событий следа проверок: add, строгая проверка check, отчет render.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        """Общие доводы подкоманд: репозиторий, сессия, базовый коммит."""
        sp.add_argument("--repo", type=Path, default=Path("."), metavar="КАТАЛОГ",
                        help="каталог репозитория (по умолчанию текущий)")
        sp.add_argument("--session", required=True, metavar="ИД",
                        help="идентификатор сессии следа")
        sp.add_argument("--base", default="HEAD", metavar="КОММИТ",
                        help="базовый коммит (по умолчанию HEAD)")

    add_parser = sub.add_parser("add", help="записать событие skipped, not_verified, probe")
    common(add_parser)
    add_parser.add_argument("--type", required=True,
                            choices=["skipped", "not_verified", "probe",
                                     "applied", "release"],
                            help="тип события (applied и release пишет только хук)")
    add_parser.add_argument("--check", help="идентификатор проверки (skipped)")
    add_parser.add_argument("--class", dest="skip_class",
                            choices=["tool_unavailable", "not_applicable"],
                            help="класс пропуска (skipped)")
    add_parser.add_argument("--ref", help="файл события failed или probe down (tool_unavailable)")
    add_parser.add_argument("--reason", help="причина (not_applicable, not_verified)")
    add_parser.add_argument("--dimension", help="измерение (not_verified)")
    add_parser.add_argument("--source", help="источник: ai-edt, naparnik, script (probe)")
    add_parser.add_argument("--status", help="статус: ok либо down (probe)")
    add_parser.add_argument("--detail", help="пояснение (probe)")
    add_parser.set_defaults(func=cmd_add)

    check_parser = sub.add_parser("check", help="строгий вердикт прогона")
    common(check_parser)
    check_parser.add_argument("--strict", action="store_true",
                              help="принят для явности: check всегда строгий")
    check_parser.set_defaults(func=cmd_check)

    render_parser = sub.add_parser("render", help="markdown-отчет прогона")
    common(render_parser)
    render_parser.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
