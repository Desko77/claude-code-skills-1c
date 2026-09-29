#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Каталог событий следа проверок: add, check, render.

Спецификация следа - skills/1c-code-review/references/evidence-format.md, профиль
правки - skills/1c-code-review/references/profile-map.md. Подкоманда add записывает
события skipped, not_verified и probe; записи applied и release пишет только хук -
попытка набрать их через CLI завершается кодом 2. Проверку закрывает выполненное
событие applied либо действующее снятие от человека (release с подтверждением в
журнале сессии): skipped, probe down и not_verified - заявки на пропуск, вердикт они
не закрывают. Подкоманда check дает строгий вердикт прогона (scope с текущим diffHash
плюс события с тем же хешем), render печатает markdown-отчет по тому же прогону.

Использование:
  python tools/evidence.py add --repo <каталог> --session <id> [--base <коммит>] --type ...
  python tools/evidence.py check [--strict] --repo <каталог> --session <id> [--base <коммит>]
      [--transcript <журнал сессии>]
  python tools/evidence.py render --repo <каталог> --session <id> [--base <коммит>]
      [--transcript <журнал сессии>]

Коды выхода check: 0 clean, 1 with_gaps, 3 blocked, 2 ошибка вызова.
Коды выхода add и render: 0 выполнено, 2 ошибка вызова.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
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

# Предел длины сообщения журнала, считающегося промптом человека: текст блока гейта
# и сводка сжатия контекста длиннее, ответ хука помечен служебным (isMeta).
USER_MESSAGE_LIMIT = 400

REQUEST_KINDS = ("skipped", "probe down", "not_verified")


def _parse_moment(value) -> datetime | None:
    """Разобрать момент ISO 8601 с зоной; без зоны или не ISO - None."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _one_line(text, limit: int = 160) -> str:
    """Текст заявки одной строкой: пробелы сжаты, длинный хвост отрезан."""
    flat = " ".join(str(text or "").split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "..."
    return flat


def _command_tail(scope: str, check: str | None) -> str:
    """Хвост команды снятия: gate либо check с идентификатором проверки.

    Хвост закрыт запретом на продолжение слова: команда release gate не должна
    подтверждать снятие проверки, названной gate-something.
    """
    if scope == "gate":
        return "gate(?![\\w.@:-])"
    return f"check[ \\t]+{re.escape(str(check))}(?![\\w.@:-])"


def _command_re(scope: str, check: str | None, anchored: bool) -> re.Pattern:
    """Образец команды снятия в сообщении журнала: сырой текст промпта либо обертка.

    Обертка - запись слэш-команды: <command-message>quality</command-message> и
    <command-name>/quality</command-name>, доводы в <command-args>. anchored -
    команда должна начинать сообщение (с учетом обертки).
    """
    tail = _command_tail(scope, check)
    body = (rf"(?:/quality[ \t]+release[ \t]+{tail}"
            rf"|<command-args>[ \t]*release[ \t]+{tail})")
    if not anchored:
        return re.compile(rf"(?<![\w./-]){body}")
    return re.compile(rf"^(?:<command-message>[^<]*</command-message>[ \t\r\n]*"
                      rf"(?:<command-name>/quality</command-name>[ \t\r\n]*)?)?{body}")


def _message_text(content) -> str | None:
    """Текст сообщения журнала: строка либо части text; только результат инструмента - None."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(parts) if parts else None


def read_user_messages(path) -> list[tuple[str, bool]] | None:
    """Сообщения пользователя из журнала сессии: пары (текст, служебное).

    Журнал - JSONL: записи type user. Результаты инструментов (записи с полем
    toolUseResult и части tool_result) и записи без текста пропускаются. Файл не
    читается - None: подтверждений снятия нет.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    messages: list[tuple[str, bool]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "user":
            continue
        if entry.get("toolUseResult"):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        text = _message_text(content)
        if text is None:
            continue
        messages.append((text, bool(entry.get("isMeta"))))
    return messages


def confirmed_by_user(messages, scope: str, check: str | None) -> bool:
    """Есть ли в журнале сообщение пользователя с командой снятия этой области.

    Команда в начале сообщения - подтверждение при любой длине и пометке.
    Команда в середине - только в коротком сообщении без пометки служебного:
    так не засчитываются ни текст блока гейта, ни ответ хука, ни сводка сжатия.
    """
    if not messages or scope not in ("gate", "check"):
        return False
    loose = _command_re(scope, check, anchored=False)
    strict = _command_re(scope, check, anchored=True)
    for text, meta in messages:
        if not loose.search(text):
            continue
        if strict.search(text):
            return True
        if not meta and len(text) <= USER_MESSAGE_LIMIT:
            return True
    return False


def release_command(check: str, reason: str) -> str | None:
    """Готовая команда снятия проверки для человека; без проверки - None."""
    if not check:
        return None
    return f"/quality release check {check} {_one_line(reason) or 'причина не названа'}"


def _skip_request(check: str | None, kind: str, reason) -> dict:
    """Заявка на пропуск: проверка, вид и причина одной строкой.

    Проверка пустая у заявок, не привязанных к обязательной проверке (not_verified,
    probe down без проверок того же источника): снятием такую заявку не подтвердить.
    """
    return {"check": check or "", "kind": kind, "detail": _one_line(reason)}


def evaluate(repo_dir: Path | str, session: str, base: str = "HEAD",
             transcript=None) -> dict:
    """Строгий вердикт прогона: clean, with_gaps либо blocked с причинами.

    Прогон - последнее scope с текущим diffHash и события с тем же хешем после первого
    такого scope (quality_events.select_run). Проверку закрывает выполненное событие applied либо
    действующее снятие от человека: release с текущим diffHash, не истекшим сроком и
    командой в журнале сессии (transcript). skipped, probe down и not_verified - заявки
    на пропуск, проверку они не закрывают и возвращаются ключом skipRequests. Журнал не
    задан или не читается - подтверждений снятия нет. Возвращает словарь: verdict,
    reasons (блокирующие), gaps (проверки, закрытые снятием), checks (проверка -> способ
    закрытия), required, probes, notVerified, skipRequests, scope, diffHash, session.
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

    # Снятия сканируются по всему каталогу сессии. Действующее снятие - текущий
    # diffHash, не истекший expiresAt и команда снятия в журнале сессии: снятие
    # записывает хук по промпту человека, и без подтверждения в журнале запись
    # снятием не считается. Снятия с чужим хешем и просроченные относятся к прежним
    # множествам изменений: на вердикт не влияют и в причинах не называются.
    released_checks: set[str] = set()
    gate_released = False
    messages = None
    unconfirmed: set[str] = set()
    for event in events:
        if event.get("type") != "release":
            continue
        if event.get("diffHash") != current:
            continue
        expires = _parse_moment(event.get("expiresAt"))
        if expires is None or expires <= datetime.now().astimezone():
            continue
        scope = event.get("scope")
        check = event.get("check") if scope == "check" else None
        if scope not in ("gate", "check") or (scope == "check" and not check):
            continue
        if messages is None:
            messages = read_user_messages(transcript) if transcript else None
        if not confirmed_by_user(messages, scope, check):
            unconfirmed.add("gate" if scope == "gate" else f"проверки {check}")
            continue
        if scope == "gate":
            gate_released = True
        else:
            released_checks.add(check)
    if run is None and not gate_released:
        reasons.append("нет scope с текущим diffHash: прогон устарел или не создан")

    applied_ok: dict[str, dict] = {}
    applied_critical: dict[str, dict] = {}
    skip_requests: list[dict] = []
    not_verified: list[dict] = []
    probes_ok: set[str] = set()
    probes_down: dict[str, dict] = {}
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
            # Пропуск от модели - заявка на пропуск: проверку закрывает applied либо
            # снятие от человека, поэтому заявка идет в skipRequests, а не в закрытия.
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
                    # Причина заявки - отказ инструмента из ссылки: заявка уходит
                    # человеку текстом, а не именем файла события.
                    skip_requests.append(_skip_request(
                        check, "tool_unavailable",
                        event.get("reason") or target.get("error") or f"ссылка: {ref}"))
            elif skip_class == "not_applicable":
                if not event.get("reason"):
                    reasons.append(f"пропуск без причины: {check} ({event.get('_file')})")
                else:
                    skip_requests.append(_skip_request(check, "not_applicable",
                                                       event.get("reason")))
            else:
                reasons.append(f"пропуск без класса: {check} ({event.get('_file')})")
        elif etype == "probe":
            if event.get("source") not in PROBE_SOURCES:
                continue
            if event.get("status") == "ok":
                probes_ok.add(event["source"])
            elif event.get("status") == "down":
                probes_down[event["source"]] = event
        elif etype == "not_verified":
            not_verified.append(event)

    required = run["scope"].get("required", []) if run else []
    checks: dict[str, dict] = {}
    gaps: list[str] = []
    if run is None and gate_released:
        # Снятие гейта человеком закрывает ход и без прогона: обязательный состав
        # неизвестен, вердикт - с пробелами, а не блокировка.
        gaps.append("gate")
    for check in required:
        # Неснятый applied с critical проверяется первым: позднее applied без critical
        # и заявка на пропуск ту же проверку не закрывают (evidence-format.md).
        if check in applied_critical:
            if check in released_checks or gate_released:
                checks[check] = {"closedBy": "release", "critical": True}
                gaps.append(check)
            else:
                reasons.append(f"applied с critical без снятия: {check}")
        elif check in applied_ok:
            checks[check] = {"closedBy": "applied", "event": applied_ok[check]}
        elif check in released_checks or gate_released:
            checks[check] = {"closedBy": "release", "critical": False}
            gaps.append(check)
        else:
            kinds = sorted({r["kind"] for r in skip_requests if r["check"] == check})
            if kinds:
                reasons.append(f"проверка не закрыта, есть только заявка на пропуск "
                               f"({', '.join(kinds)}): {check}")
            else:
                reasons.append(f"обязательная проверка без события: {check}")

    # Заявка по недоступному источнику: probe down не закрывает проверку, а называет
    # повод ее не выполнять. Заявка раскрывается по обязательным проверкам того же
    # источника, оставшимся без applied и без снятия; когда таких нет - идет без
    # проверки (подтверждать снятием нечего).
    for source in sorted(probes_down):
        open_checks = [check for check in required
                       if CHECK_SOURCES.get(check.split("@")[0]) == source
                       and check not in checks]
        detail = probes_down[source].get("detail") or f"источник {source} недоступен"
        if open_checks:
            skip_requests.extend(_skip_request(check, "probe down", detail)
                                 for check in open_checks)
        else:
            skip_requests.append(_skip_request("", "probe down", detail))
    for event in not_verified:
        skip_requests.append(_skip_request(
            "", "not_verified",
            f"{event.get('dimension', '-')}: {event.get('reason', '-')}"))

    needed_sources = set()
    for info in checks.values():
        if info["closedBy"] == "applied":
            source = CHECK_SOURCES.get(info["event"]["check"].split("@")[0])
            if source:
                needed_sources.add(source)
    for source in sorted(needed_sources - probes_ok):
        reasons.append(f"нет probe ok по источнику: {source}")

    # Неподтвержденное снятие само ход не блокирует: оно поясняет, почему проверка,
    # которую оно должно было закрыть, осталась открытой.
    if reasons:
        for what in sorted(unconfirmed):
            reasons.append(f"снятие {what}: не найдено подтверждение пользователя "
                           f"в журнале сессии")
    verdict = "blocked" if reasons else ("with_gaps" if gaps else "clean")
    return {"verdict": verdict, "reasons": reasons, "gaps": gaps, "checks": checks,
            "required": required, "probes": sorted(probes_ok),
            "notVerified": not_verified, "skipRequests": skip_requests,
            "scope": run["scope"] if run else None,
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
    """Markdown-отчет прогона: вердикт, проверенное, снятия, заявки, не проверенное."""
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
                  "| Проверка | Чем закрыта |", "|---|---|"])
    for check in result["gaps"]:
        lines.append(f"| {check} | release: снятие человеком |")
    if not result["gaps"]:
        lines.append("| - | - |")

    # Заявки на пропуск: проверку они не закрывают, подтверждает снятие человек.
    lines.extend(["", "## Заявки на пропуск",
                  "| Проверка | Вид | Причина | Подтверждение человеком |",
                  "|---|---|---|---|"])
    if result["skipRequests"]:
        for request in result["skipRequests"]:
            command = release_command(request["check"], request["detail"]) or "-"
            lines.append(f"| {request['check'] or '-'} | {request['kind']} | "
                         f"{request['detail'] or '-'} | {command} |")
    else:
        lines.append("| - | - | - | - |")

    lines.extend(["", "## Не проверено",
                  "| Проверка | Причина |", "|---|---|"])
    requests_by_check = {r["check"]: r for r in result["skipRequests"] if r["check"]}
    rows = []
    for check in [c for c in result["required"] if c not in result["checks"]]:
        request = requests_by_check.get(check)
        if request:
            rows.append(f"| {check} | заявка на пропуск ({request['kind']}): "
                        f"{request['detail'] or '-'} |")
        else:
            rows.append(f"| {check} | нет события |")
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
        result = evaluate(args.repo, args.session, args.base, args.transcript)
    except (changeset.ChangesetError, quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    print(f"вердикт: {VERDICT_TITLES[result['verdict']]}")
    print(f"diffHash: {result['diffHash']}")
    for reason in result["reasons"]:
        print(f"блокирует: {reason}")
    for gap in result["gaps"]:
        print(f"пробел: {gap}")
    # Заявки на пропуск и готовая команда снятия: подтвердить пропуск может только
    # человек, поэтому строка команды идет вместе с заявкой.
    for request in result["skipRequests"]:
        print(f"заявка на пропуск: {request['check'] or '-'} [{request['kind']}] "
              f"{request['detail'] or '-'}")
        command = release_command(request["check"], request["detail"])
        if command:
            print(f"подтверждение человеком: {command}")
    return {"clean": 0, "with_gaps": 1, "blocked": 3}[result["verdict"]]


def cmd_render(args: argparse.Namespace) -> int:
    """Подкоманда render: markdown-отчет прогона; код 0 при любом вердикте."""
    try:
        result = evaluate(args.repo, args.session, args.base, args.transcript)
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
        sp.add_argument("--base", default=None, metavar="КОММИТ",
                        help="базовый коммит (по умолчанию HEAD отметки сессии, иначе HEAD)")

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
    check_parser.add_argument("--transcript", default=None, metavar="ЖУРНАЛ",
                              help="журнал сессии для подтверждения снятий человеком")
    check_parser.set_defaults(func=cmd_check)

    render_parser = sub.add_parser("render", help="markdown-отчет прогона")
    common(render_parser)
    render_parser.add_argument("--transcript", default=None, metavar="ЖУРНАЛ",
                               help="журнал сессии для подтверждения снятий человеком")
    render_parser.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    # База diffHash без явного --base - HEAD отметки сессии: единая база с хуками
    # и гейтом завершения хода (tools/quality_events.py, resolve_base).
    try:
        args.base = quality_events.resolve_base(args.repo, args.session, args.base)
    except (quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
