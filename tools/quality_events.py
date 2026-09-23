#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общий модуль событий следа проверок: запись, чтение, отбор прогона.

Каталог событий - <база>/<ключ>/<session>/events/ вне репозитория
(спецификация - skills/1c-code-review/references/evidence-format.md). База -
QUALITY_STATE_DIR, если переменная не пустая, иначе
<домашний каталог>/.claude/state/quality. Событие - один неизменяемый JSON-файл
с именем <время>-<номер>-<источник>-<id>.json; запись идет через временный файл
и переименование. Поврежденный JSON при чтении не поднимает исключение: файл
возвращается записью type=corrupt с именем и текстом ошибки.

Пишут события: tools/change_profile.py (scope, producer profile), tools/evidence.py
(skipped, not_verified, probe; producer cli) и хуки (applied, failed, release,
baseline, armed; producer hook) - хуки этим модулем не реализуются, для него они
только записи каталога.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Идентификатор сессии: буква-цифра-подчеркивание-точка-дефис, без разделителей пути.
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DRIVE_ROOT = re.compile(r"[A-Za-z]:/")


class EventsError(Exception):
    """Отказ каталога событий: недопустимый идентификатор сессии, git недоступен."""


def now_iso() -> str:
    """Текущее время в ISO 8601 с зоной и миллисекундами (поле at события)."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def claude_home() -> str:
    """Домашний каталог: на win32 первым USERPROFILE, иначе HOME, затем Path.home."""
    if sys.platform == "win32":
        return os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
    return os.environ.get("HOME") or os.environ.get("USERPROFILE") or str(Path.home())


def state_base() -> Path:
    """База следа: QUALITY_STATE_DIR, если переменная не пустая, иначе домашний каталог."""
    env = os.environ.get("QUALITY_STATE_DIR", "")
    if env:
        return Path(env)
    return Path(claude_home()) / ".claude" / "state" / "quality"


def normalize_top(path: str, platform: str) -> str:
    """Нормализация корня репозитория. platform - win32, linux или darwin."""
    text = str(path).replace("\\", "/")
    while len(text) > 1 and text.endswith("/") and _DRIVE_ROOT.fullmatch(text) is None:
        text = text[:-1]
    if platform == "win32":
        text = text.lower()
    return text


def repo_key(normalized: str) -> str:
    """Ключ репозитория: сегмент пути и 12 hex sha256 нормализованной строки."""
    segment = str(normalized).rsplit("/", 1)[-1]
    segment = re.sub(r"[^A-Za-z0-9._-]", "_", segment)
    segment = re.sub(r"_+", "_", segment)
    segment = segment.strip("_.-")[:32].rstrip("_.-")
    if not segment:
        segment = "repo"
    digest = hashlib.sha256(str(normalized).encode("utf-8")).hexdigest()[:12]
    return f"{segment}-{digest}"


def _canonical_top(top: str) -> str:
    """Канонический путь. Отказ realpath - путь без изменений."""
    try:
        return os.path.realpath(top)
    except OSError:
        return top


def state_root(top: Path | str) -> Path:
    """Корень следа репозитория: <база>/<ключ>."""
    canonical = _canonical_top(os.fspath(top))
    return state_base() / repo_key(normalize_top(canonical, sys.platform))


def repo_top(repo_dir: Path | str) -> Path:
    """Корень git-репозитория по git rev-parse --show-toplevel.

    Каталог следа один на репозиторий независимо от того, каким подкаталогом задан --repo.
    """
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              cwd=str(repo_dir), capture_output=True)
    except OSError as exc:
        raise EventsError(f"git недоступен: {exc}") from exc
    if proc.returncode != 0:
        raise EventsError(f"каталог не является git-репозиторием: {repo_dir}")
    return Path(proc.stdout.decode("utf-8", errors="replace").strip())


def validate_session(session: str) -> None:
    """Проверить идентификатор сессии; недопустимый - EventsError."""
    if not SESSION_RE.match(session or ""):
        raise EventsError(f"недопустимый идентификатор сессии: {session!r}")


def session_dir(repo_dir: Path | str, session: str) -> Path:
    """Каталог сессии: <база>/<ключ>/<session>."""
    validate_session(session)
    return state_root(repo_top(repo_dir)) / session


def events_dir(repo_dir: Path | str, session: str) -> Path:
    """Каталог событий сессии вне репозитория."""
    return session_dir(repo_dir, session) / "events"


def _acquire_seq(session_dir: Path, time_part: str) -> int:
    """Занять номер последовательности отметки времени созданием lock-файла.

    Номер упорядочивает события одной миллисекунды по записи, а не по producer.
    Файл <время>-<номер>.lock в каталоге сессии создается открытием с
    O_CREAT|O_EXCL: занятый номер поднимает FileExistsError, перебор идет со
    следующего. Lock-файлы остаются в каталоге как занятые номера. Node-писатель
    событий повторяет ту же схему (evidence-format.md).
    """
    seq = 0
    while True:
        try:
            fd = os.open(str(session_dir / f"{time_part}-{seq:06d}.lock"),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            seq += 1
            continue
        os.close(fd)
        return seq


def _filename(event: dict, session_dir: Path) -> str:
    """Имя файла события: время, номер последовательности, producer и случайный id.

    Время формата YYYY-MM-DDTHHMMSS-<мс> самолексикографично; номер - 6 цифр
    монотонной последовательности отметки времени, поэтому сортировка имен
    совпадает с порядком записи и в пределах одной миллисекунды. Поле at обязано
    быть ISO 8601; иначе EventsError.
    """
    try:
        stamp = datetime.fromisoformat(event["at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventsError("событие без поля at или с не-ISO временем") from exc
    producer = event.get("producer", "cli")
    if not re.fullmatch(r"[a-z]+", str(producer)):
        raise EventsError(f"недопустимый producer: {producer!r}")
    time_part = f"{stamp:%Y-%m-%dT%H%M%S}-{stamp.microsecond // 1000:03d}"
    seq = _acquire_seq(session_dir, time_part)
    return f"{time_part}-{seq:06d}-{producer}-{uuid.uuid4().hex[:6]}.json"


def write_event(repo_dir: Path | str, session: str, event: dict) -> Path:
    """Записать событие атомарно и вернуть путь файла.

    Тело - UTF-8 JSON с сортировкой ключей, отступом 2 и завершающим переводом
    строки. Временный файл пишется в каталог событий и переименовывается; занятое
    имя перегенерируется (id случайный, коллизия маловероятна, но проверяется).
    """
    target_dir = events_dir(repo_dir, session)
    session_dir = target_dir.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    final = target_dir / _filename(event, session_dir)
    while final.exists():
        final = target_dir / _filename(event, session_dir)
    tmp = target_dir / f".tmp-{uuid.uuid4().hex}"
    tmp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(tmp, final)
    return final


def read_events(repo_dir: Path | str, session: str) -> list[dict]:
    """Прочитать события сессии в порядке имен; поврежденные - записью type=corrupt.

    Каждое событие дополняется служебным ключом _file (имя файла): по нему ссылаются
    пропуски (ref) и строится диагностика. Отсутствующий каталог - пустой список.
    """
    directory = events_dir(repo_dir, session)
    if not directory.is_dir():
        return []
    events: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            events.append({"type": "corrupt", "file": path.name, "error": str(exc)})
            continue
        if not isinstance(data, dict):
            events.append({"type": "corrupt", "file": path.name,
                           "error": "корень JSON не объект"})
            continue
        data["_file"] = path.name
        events.append(data)
    return events


def select_run(events: list[dict], diff_hash: str) -> dict | None:
    """Отобрать прогон: последнее scope с diffHash и события с тем же хешем после него.

    Возвращает {"scope": событие, "events": [события после него с тем же diffHash]}
    либо None, когда scope с таким хешем в каталоге нет. Порядок берется по позициям
    в списке (он же порядок имен файлов).
    """
    run = None
    for index, event in enumerate(events):
        if event.get("type") == "scope" and event.get("diffHash") == diff_hash:
            run = {"scope": event,
                   "events": [e for e in events[index + 1:]
                              if e.get("diffHash") == diff_hash]}
    return run
