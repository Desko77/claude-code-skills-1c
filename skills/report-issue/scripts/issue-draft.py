#!/usr/bin/env python3
"""Проверка черновика issue на приватные данные и ссылка на создание issue на GitHub.

Черновик - заголовок и файл с текстом (markdown). Находки печатаются в stderr с номером
строки, код выхода 1, ссылка не выдается. Без находок в stdout - ссылка
https://github.com/<репозиторий>/issues/new с заполненными title, body и labels, код 0.
Ошибка вызова - код 2.
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

URL_LIMIT = 8000
ALLOWED_HOSTS = ("github.com", "t.me", "its.1c.ru", "v8.1c.ru", "1c.ru", "docs.anthropic.com",
                 "cursor.com", "localhost", "127.0.0.1")
ALLOWED_IPS = ("127.0.0.1", "0.0.0.0")

PATTERNS = [
    ("путь", re.compile(r"(?<![\w/])[A-Za-z]:[\\/][^\s\"'`|*?]*")),
    ("сетевой путь", re.compile(r"(?<![\w\\/])\\\\[\w.$-]+\\[^\s\"'`|]*")),
    ("домашний каталог", re.compile(r"(?<![\w.])/(?:home|Users)/[\w.-]+")),
    ("IP-адрес", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
    ("адрес почты", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("секрет", re.compile(r"(?i)\b(?:password|passwd|pwd|token|secret|api[_-]?key|пароль)\s*[:=]\s*\S+")),
    ("токен", re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_]{16,}|\bBearer\s+[A-Za-z0-9._-]{16,}")),
    ("строка соединения", re.compile(r"(?i)\b(?:Srvr|Ref|Usr|Pwd)\s*=\s*\"?[^;\"\s]+")),
    ("UUID", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("ссылка", re.compile(r"https?://[^\s)>\]\"'`]+")),
]


def allowed(kind, text):
    """Обобщенные значения, которые находкой не считаются."""
    if kind == "путь":
        normalized = text.replace("\\", "/").lower()
        return normalized.startswith("c:/projects/") or normalized == "c:/projects" or "<" in text
    if kind == "IP-адрес":
        return text in ALLOWED_IPS
    if kind == "UUID":
        return set(text.replace("-", "")) <= {"0"}
    if kind == "ссылка":
        host = (urlsplit(text).hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)
    return False


def find_private_data(title, body):
    """Находки черновика: (место, вид, значение) в порядке строк и позиций."""
    findings = []
    lines = [("заголовок", title)] + [(f"строка {n}", line) for n, line in enumerate(body.split("\n"), 1)]
    for place, line in lines:
        hits = []
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0).rstrip(".,;:")
                if not allowed(kind, value):
                    hits.append((match.start(), kind, value))
        covered = []
        for start, kind, value in sorted(hits):
            end = start + len(value)
            if any(s <= start and end <= e for s, e in covered):
                continue
            covered.append((start, end))
            findings.append((place, kind, value))
    return findings


def build_url(repo, title, body, labels):
    """Ссылка на новую issue; тело не входит, если ссылка длиннее предела GitHub."""
    base = f"https://github.com/{repo}/issues/new?title={quote(title, safe='')}"
    tail = f"&labels={quote(','.join(labels), safe='')}" if labels else ""
    full = base + f"&body={quote(body, safe='')}" + tail
    if len(full) <= URL_LIMIT:
        return full, True
    return base + tail, False


def main():
    """Разбор доводов, проверка черновика, вывод находок либо ссылки; возвращает код выхода."""
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(description="Проверка черновика issue и ссылка на создание")
    parser.add_argument("-Repo", required=True)
    parser.add_argument("-Title", required=True)
    parser.add_argument("-BodyFile", required=True)
    parser.add_argument("-Labels", default="")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.Repo):
        print(f"Неверный репозиторий: {args.Repo} (нужно владелец/имя)", file=sys.stderr)
        return 2
    title = args.Title.strip()
    if not title:
        print("Пустой заголовок", file=sys.stderr)
        return 2
    path = Path(args.BodyFile)
    try:
        body = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"Файл текста не читается: {args.BodyFile} ({exc.strerror})", file=sys.stderr)
        return 2
    body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    labels = [label.strip() for label in args.Labels.split(",") if label.strip()]

    findings = find_private_data(title, body)
    if findings:
        print(f"Находок: {len(findings)}", file=sys.stderr)
        for place, kind, value in findings:
            print(f"  {place}: {kind} - {value}", file=sys.stderr)
        print("Черновик не отправлять: замените находки обобщенными значениями и повторите проверку.",
              file=sys.stderr)
        return 1

    url, with_body = build_url(args.Repo, title, body, labels)
    print("Проверка на приватные данные: находок нет.")
    if not with_body:
        print(f"Текст длиннее, чем принимает ссылка GitHub ({URL_LIMIT} символов): в ссылке только "
              "заголовок и метки, текст вставьте вручную либо создайте issue через "
              "gh issue create --body-file.")
    print("Ссылка для создания issue:")
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
