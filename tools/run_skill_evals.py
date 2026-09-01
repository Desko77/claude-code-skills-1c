#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Поведенческий прогон скилов: один и тот же вопрос агенту без скила и со скилом.

Снапшот-тесты в tests/skills проверяют СКРИПТЫ навыка детерминированно. Этот
раннер проверяет другое: меняет ли скил поведение агента. Каждый кейс идет
двумя фазами.

  RED    агент отвечает без скила: базовая линия, что модель знает сама
  GREEN  скил разложен в рабочий каталог как project-scoped: что добавил скил

Замеряется по каждой фазе:

  - активация: прочитал ли агент SKILL.md либо файл из references (видно
    в JSONL-трейсе агента, а не по словам в ответе);
  - ожидаемые совпадения expect и запрещенные forbid по тексту ответа;
  - вызовы БСП в блоках BSL сверяются с офлайн-справочником
    skills/1c-bsp-api/references/bsp-api.jsonl: выдуманный модуль или метод,
    вызов служебного модуля, вызов переопределяемого обработчика;
  - расход токенов.

Скил считается полезным, когда GREEN проходит пороги, а RED их не достигает.
Совпадение RED и GREEN означает, что скил не дал агенту ничего нового.

Агент - Codex CLI: он идет без интерактива, пишет машинный трейс и не тратит
подписку Claude. Ответы оцениваются по тексту, поэтому проверяется наученное
поведение, а не конкретная модель.

Использование:
  python tools/run_skill_evals.py --skill 1c-bsp-api
  python tools/run_skill_evals.py --skill 1c-bsp-api --case check-before-call
  python tools/run_skill_evals.py --skill 1c-bsp-api --runs 3 --jobs 4
  python tools/run_skill_evals.py --skill 1c-bsp-api --phase green
  python tools/run_skill_evals.py --list
  python tools/run_skill_evals.py --skill 1c-bsp-api --dry-run
  python tools/run_skill_evals.py --skill 1c-bsp-api --json report.json

Формат кейсов - skills/<навык>/evals/evals.json. Прозаические expectations из
старого формата раннером не проверяются: они остаются описанием для человека,
а машинные проверки задаются полями expect / forbid. Кейс без единой машинной
проверки прогоняется и помечается no-checks, чтобы было видно, какие скилы еще
не переведены на исполняемый формат.

Коды возврата: 0 пороги достигнуты, 1 не достигнуты, 2 ошибка запуска.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if callable(_reconf):
        try:
            _reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
BSP_INDEX = SKILLS_DIR / "1c-bsp-api" / "references" / "bsp-api.jsonl"
DEFAULT_TIMEOUT = 600
DEFAULT_JOBS = 4
# Порог похожести имени на настоящий модуль БСП. Замерено на живом прогоне:
# выдумки дают 0.80-0.88, чужие и платформенные имена 0.33-0.57.
LOOKALIKE = 0.72


class EvalError(RuntimeError):
    """Ошибка подготовки или запуска прогона: нечего или нечем прогонять."""


# --------------------------------------------------------------------------
# Кейсы
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """Один поведенческий кейс скила.

    Поля:
      ident       идентификатор кейса в пределах скила
      prompt      задача, которую получает агент
      expect      регулярные выражения, которые ДОЛЖНЫ найтись в ответе
      forbid      регулярные выражения, которых в ответе быть НЕ должно
      should_activate  ожидается ли обращение агента к файлам скила
      checks_bsl  разбирать ли блоки BSL и сверять вызовы со справочником БСП
      note        прозаическое описание из старого формата, для человека
    """

    ident: str
    prompt: str
    expect: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    should_activate: bool = True
    checks_bsl: bool = False
    note: str = ""

    @property
    def has_machine_checks(self) -> bool:
        """Есть ли у кейса хоть одна проверка, которую раннер может выполнить."""
        return bool(self.expect or self.forbid or self.checks_bsl)


def load_cases(skill: str) -> tuple[Path, list[Case]]:
    """Прочитать кейсы скила из skills/<навык>/evals/evals.json.

    Понимает и старый формат (evals с прозаическими expectations), и новый
    (те же записи плюс expect / forbid / checks_bsl). Идентификатор берется
    из поля id: строковое используется как есть, числовое дополняется до
    читаемого вида по порядковому номеру.

    Возвращает путь к файлу и список кейсов. Бросает EvalError, если файла
    нет либо он не разбирается.
    """
    path = SKILLS_DIR / skill / "evals" / "evals.json"
    if not path.is_file():
        raise EvalError(f"нет файла кейсов: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"не читается {path}: {exc}") from exc

    raw_cases = payload.get("evals")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalError(f"в {path} нет непустого массива evals")

    cases: list[Case] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise EvalError(f"кейс #{index} в {path} не объект")
        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise EvalError(f"кейс #{index} в {path} без prompt")
        ident = raw.get("id")
        ident = str(ident) if isinstance(ident, str) and ident.strip() else f"case-{index}"
        if ident in seen:
            raise EvalError(f"повтор идентификатора кейса {ident} в {path}")
        seen.add(ident)
        expect = _patterns(raw, "expect", ident)
        forbid = _patterns(raw, "forbid", ident)
        cases.append(
            Case(
                ident=ident,
                prompt=prompt.strip(),
                expect=expect,
                forbid=forbid,
                should_activate=bool(raw.get("should_activate", True)),
                checks_bsl=bool(raw.get("checks_bsl", False)),
                note=str(raw.get("expected_output", "")),
            )
        )
    return path, cases


def _patterns(raw: dict, key: str, ident: str) -> tuple[str, ...]:
    """Достать список регулярных выражений и сразу проверить их компиляцию.

    Битый шаблон должен падать на загрузке кейсов, а не посреди прогона,
    когда агент уже отработал и результат некуда девать.
    """
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise EvalError(f"кейс {ident}: поле {key} должно быть массивом")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise EvalError(f"кейс {ident}: пустое значение в {key}")
        try:
            re.compile(item, re.I | re.S)
        except re.error as exc:
            raise EvalError(f"кейс {ident}: битое регулярное выражение {item!r}: {exc}") from exc
        out.append(item)
    return tuple(out)


# --------------------------------------------------------------------------
# Справочник БСП
# --------------------------------------------------------------------------


@dataclass
class BspIndex:
    """Офлайн-справочник БСП для сверки вызовов, найденных в ответе агента.

    В отличие от сверки по выгрузке конфигурации, справочник не требует от
    прогона ни базы, ни исходников: имена, модули и регионы уже собраны.
    """

    methods: dict[str, set[str]] = field(default_factory=dict)
    modules: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path = BSP_INDEX) -> "BspIndex | None":
        """Загрузить справочник. Возвращает None, если файла нет.

        Отсутствие справочника не ошибка прогона: сверка вызовов просто
        не выполняется, и это отражается в отчете.
        """
        if not path.is_file():
            return None
        index = cls()
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                module = record.get("m")
                name = record.get("n")
                if not module or not name or module == "?":
                    continue
                index.modules.add(module)
                index.methods.setdefault(module, set()).add(name)
        return index if index.modules else None

    def verdict(self, module: str, method: str) -> str | None:
        """Оценить вызов Модуль.Метод. Возвращает текст претензии либо None.

        Претензии трех видов: вызов служебного или переопределяемого модуля,
        выдуманный модуль, выдуманный метод.

        Служебные модули проверяются ДО поиска в справочнике: справочник несет
        только программный интерфейс, служебных модулей в нем нет вовсе, и без
        этой проверки такой вызов объявлялся бы выдуманным.

        Имя, которого в справочнике нет, само по себе НЕ претензия: это может
        быть модуль самого проекта, заглушка примера или платформенный тип.
        Выдумкой считается только имя, похожее на настоящее имя БСП, - именно
        так галлюцинация и выглядит. Порог отделяет ФайловаяСистемаКлиентСервер
        (0.88 к ФайловаяСистемаКлиент) от МойСерверныйМодуль (0.49) и
        ТаблицаЗначений (0.52).
        """
        if "Служебный" in module:
            return f"вызов служебного модуля {module}.{method}"
        if module.endswith("Переопределяемый"):
            return f"вызов переопределяемого обработчика {module}.{method}"
        if module not in self.modules:
            near = difflib.get_close_matches(module, self.modules, n=1, cutoff=LOOKALIKE)
            if near:
                return f"выдуман модуль {module}, похож на {near[0]}"
            return None
        if method not in self.methods.get(module, set()):
            return f"выдуман метод {module}.{method}"
        return None


BSL_BLOCK = re.compile(r"```(?:bsl|1c|bsl-?\w*)?\s*\n(.*?)```", re.S | re.I)
CALL = re.compile(r"\b([А-ЯЁ][А-Яа-яЁё0-9]{3,})\.([А-ЯЁ][А-Яа-яЁё0-9]{2,})\s*\(")

# Имена, объявленные в самом блоке: присваивание, Перем, переменная цикла.
# Вызов на такой переменной - метод платформенного объекта, а не общего модуля.
LOCAL_NAME = re.compile(
    r"^\s*([А-ЯЁ][А-Яа-яЁё0-9]*)\s*=(?!=)"
    r"|^\s*Перем\s+([А-ЯЁ][А-Яа-яЁё0-9]*)"
    r"|Для\s+Каждого\s+([А-ЯЁ][А-Яа-яЁё0-9]*)\s+Из",
    re.I | re.M,
)

# Менеджеры объектов конфигурации: обращение к прикладным данным, не к БСП.
MANAGERS = (
    "Справочники", "Документы", "РегистрыСведений", "РегистрыНакопления",
    "РегистрыБухгалтерии", "РегистрыРасчета", "Перечисления", "Обработки",
    "Отчеты", "ПланыВидовХарактеристик", "ПланыСчетов", "ПланыОбмена",
    "БизнесПроцессы", "Задачи", "Константы", "Метаданные",
)


def bsp_findings(response: str, index: BspIndex | None) -> list[str]:
    """Собрать претензии к вызовам БСП во всех блоках BSL ответа.

    Разбираются только fenced-блоки: имя модуля, упомянутое в прозе, чаще
    всего обсуждается, а не вызывается.

    Из разбора исключаются локальные переменные блока и менеджеры объектов.
    Без этого вызов метода на переменной читался бы как обращение к общему
    модулю: поймано на живом прогоне, где ДвоичныеДанные.Размер() на локальной
    переменной был объявлен выдуманным модулем БСП.

    Дубли схлопываются, чтобы один и тот же вызов не считался несколько раз.
    """
    if index is None:
        return []
    findings: list[str] = []
    for block in BSL_BLOCK.findall(response):
        locals_here = {name for group in LOCAL_NAME.findall(block) for name in group if name}
        for module, method in CALL.findall(block):
            if module in locals_here or module in MANAGERS:
                continue
            verdict = index.verdict(module, method)
            if verdict and verdict not in findings:
                findings.append(verdict)
    return findings


# --------------------------------------------------------------------------
# Запуск агента
# --------------------------------------------------------------------------


def resolve_codex(explicit: str | None) -> str:
    """Найти исполняемый Codex CLI.

    Предпочитается ПАКЕТНЫЙ codex.exe, рядом с которым лежит windows sandbox
    helper: установленный в PATH codex на Windows идет без него и падает на
    песочнице. Тот же резолвер используется в скиле codex-review.
    """
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(explicit)
        if not found:
            raise EvalError(f"не найден Codex: {explicit}")
        return found

    releases = sorted(
        (Path.home() / ".codex" / "packages" / "standalone" / "releases").glob("*/bin/codex.exe"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for candidate in releases:
        helper = candidate.parent.parent / "codex-resources" / "codex-windows-sandbox-setup.exe"
        if helper.is_file():
            return str(candidate)
    found = shutil.which("codex")
    if found:
        return found
    raise EvalError("Codex CLI не найден, нужен codex login и установленный CLI")


def conflicting_installs(skill: str, staged: Path) -> list[Path]:
    """Найти установленные копии того же скила, которые протекут в фазу RED.

    Если скил уже стоит глобально, агент прочитает его и в RED тоже, и вся
    разница между фазами исчезнет. Такой прогон бессмысленен, поэтому копии
    ищутся заранее и прогон останавливается.

    Ищутся только каталоги, которые читает Codex. Каталог ~/.claude/skills
    сюда НЕ входит: его читает Claude Code, а не агент прогона, и своя
    установка скила там - нормальное рабочее состояние, а не конфликт.
    """
    found: list[Path] = []
    homes = [Path.home() / ".agents" / "skills"]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        homes.append(Path(codex_home) / "skills")
    for root in homes:
        candidate = root / skill / "SKILL.md"
        if candidate.is_file() and candidate.resolve() != (staged / "SKILL.md").resolve():
            found.append(candidate.resolve())
    return sorted(set(found))


@contextlib.contextmanager
def staged_skill(source: Path, target: Path) -> Iterator[None]:
    """Разложить скил в рабочий каталог на время фазы GREEN и убрать после.

    Существующий каталог не перетирается: это чужие файлы, и молча заменять
    их прогоном тестов нельзя. Пустые родительские каталоги подчищаются,
    чтобы прогон не оставлял следов в рабочем дереве.
    """
    if target.exists():
        raise EvalError(f"каталог уже занят, не перетираю: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    try:
        yield
    finally:
        shutil.rmtree(target, ignore_errors=True)
        for folder in (target.parent, target.parent.parent):
            with contextlib.suppress(OSError):
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()


def codex_command(codex: str, prompt: str, workdir: Path, model: str | None) -> list[str]:
    """Собрать вызов Codex для одного кейса.

    Прогон изолируется от пользовательских настроек: иначе личные правила и
    установленные скилы попадут в фазу RED и сотрут разницу между фазами.
    На Windows после отключения пользовательского конфига у Codex не остается
    backend песочницы, и он отвергает даже чтение, поэтому backend задается
    явно.
    """
    command = [
        codex,
        "exec",
        "--json",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
    ]
    if os.name == "nt":
        command.extend(["-c", 'windows.sandbox="unelevated"'])
    command.extend(["-C", str(workdir)])
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def parse_events(stdout: str) -> list[dict]:
    """Выбрать JSONL-события агента из потока вывода, мусорные строки пропустить."""
    events: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def final_answer(events: Iterable[dict]) -> str:
    """Собрать текст ответа агента из событий трейса.

    Сообщения лежат вложенно: item.completed несет item с type agent_message
    и полем text. Возвращается ТОЛЬКО этот текст, без остального трейса.

    Откат на сырой поток недопустим: трейс содержит вывод прочитанных агентом
    файлов, включая сам SKILL.md, и проверка forbid тогда срабатывает на
    примерах из документации скила, а не на ответе. Пустая строка честнее:
    она провалит кейс как отсутствие ответа, а не как мнимое нарушение.
    """
    texts: list[str] = []
    for event in events:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        elif event.get("type") == "agent_message":
            text = event.get("text") or event.get("message")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return "\n\n".join(texts)


def trace_error(events: Iterable[dict]) -> str | None:
    """Найти в трейсе отказ агента: не ответ по существу, а сбой самого прогона.

    Codex сообщает такие случаи событием type=error и при этом успевает выдать
    начало трейса (thread.started, turn.started). Проверка "код возврата не ноль
    И событий нет" этого не ловит, и фаза, где не отработал ни один вызов,
    отчитывалась как честно проваленные проверки.

    Поймано на исчерпании лимита подписки: фаза показала 0 из 5 и ноль ошибок,
    хотя ни одного ответа не было.
    """
    for event in events:
        if event.get("type") == "error":
            message = event.get("message") or event.get("error") or "отказ агента"
            return str(message)[:300]
    return None


def activation_evidence(events: Iterable[dict], skill: str) -> list[str]:
    """Найти в трейсе следы фактического обращения агента к файлам скила.

    Проверяется путь в событиях, а не слова в ответе: агент может назвать
    скил, не открыв его, и наоборот. Ложная активация в RED означала бы,
    что изоляция фазы не работает.
    """
    marks: list[str] = []
    needles = (f"skills/{skill}/", f"skills\\{skill}\\")
    for event in events:
        blob = json.dumps(event, ensure_ascii=False)
        for needle in needles:
            if needle in blob or needle.replace("/", "\\\\") in blob:
                snippet = needle.strip("/\\")
                if snippet not in marks:
                    marks.append(snippet)
    return marks


def token_usage(events: Iterable[dict]) -> int:
    """Сложить потраченные токены по событиям трейса, 0 если агент их не сообщил.

    Считается вход плюс выход по каждому завершенному ходу. Кэшированный вход
    в сумму НЕ входит отдельным слагаемым: агент сообщает его как часть
    input_tokens, и повторный учет удвоил бы длинные прогоны.
    """
    total = 0
    for event in events:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        explicit = usage.get("total_tokens")
        if isinstance(explicit, int):
            total += explicit
            continue
        for key in ("input_tokens", "output_tokens", "reasoning_output_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                total += value
    return total


# --------------------------------------------------------------------------
# Оценка
# --------------------------------------------------------------------------


def score(case: Case, response: str, marks: list[str], index: BspIndex | None) -> dict:
    """Оценить один ответ агента и вернуть запись результата.

    Кейс проходит, когда найдены все expect, не найдено ни одного forbid и
    сверка вызовов БСП не дала претензий. Кейс без машинных проверок не
    объявляется пройденным: он помечается no-checks, потому что раннеру
    нечего было проверить.
    """
    missing = [p for p in case.expect if not re.search(p, response, re.I | re.S)]
    hit = [p for p in case.forbid if re.search(p, response, re.I | re.S)]
    findings = bsp_findings(response, index) if case.checks_bsl else []
    checked = case.has_machine_checks
    passed = checked and not missing and not hit and not findings
    return {
        "case": case.ident,
        "checked": checked,
        "passed": passed,
        "activated": bool(marks),
        "activation": marks,
        "missing_expect": missing,
        "hit_forbid": hit,
        "bsp_findings": findings,
        "response_chars": len(response),
    }


def run_case(
    codex: str,
    case: Case,
    workdir: Path,
    skill: str,
    model: str | None,
    timeout: int,
    index: BspIndex | None,
    artifacts: Path | None,
    phase: str,
    attempt: int = 1,
) -> dict:
    """Прогнать один кейс в одной фазе и вернуть оцененный результат.

    Падение самого запуска не смешивается с провалом проверок: у записи
    появляется поле error, и такой кейс считается инфраструктурной ошибкой,
    а не отрицательным ответом агента.
    """
    command = codex_command(codex, case.prompt, workdir, model)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"case": case.ident, "checked": False, "passed": False, "error": "таймаут"}
    except OSError as exc:
        return {"case": case.ident, "checked": False, "passed": False, "error": str(exc)}

    events = parse_events(completed.stdout)
    response = final_answer(events)
    marks = activation_evidence(events, skill)
    record = score(case, response, marks, index)
    record["tokens"] = token_usage(events)

    # Активация решает, о чем вообще говорит результат фазы.
    # В GREEN кейс, помеченный should_activate, но прошедший мимо файлов скила,
    # ничего про скил не доказывает: агент ответил из своих знаний, и засчитывать
    # это скилу нельзя.
    if phase == "green" and case.should_activate and not marks:
        record["passed"] = False
        record["no_activation"] = True
    # В RED активация означает, что изоляция фазы протекла: скил все-таки виден,
    # и разница между фазами перестает что-либо значить. Это сбой прогона.
    if phase == "red" and marks:
        record["error"] = "изоляция протекла: в фазе RED агент читал файлы скила"
        record["passed"] = False
        record["checked"] = False

    # Сбой прогона отделяется от проваленной проверки: у первого чинят среду,
    # у второй скил или кейс. Смешивать их - значит гнаться за призраком.
    failure = trace_error(events)
    if failure is None and not response.strip():
        failure = "агент не вернул ответа"
    if failure is None and completed.returncode != 0 and not events:
        failure = f"код возврата {completed.returncode}: {completed.stderr.strip()[:200]}"
    if failure is not None:
        record["error"] = failure
        record["passed"] = False
        record["checked"] = False

    if artifacts:
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / f"{phase}-{case.ident}.md").write_text(response, encoding="utf-8", newline="\n")
    return record


def merge_runs(records: list[dict]) -> dict:
    """Свести повторы одного кейса в одну запись по большинству.

    Ответ модели дрейфует между запусками, поэтому один прогон отличает удачу
    от наученного поведения плохо. Кейс считается пройденным, когда прошло
    БОЛЬШИНСТВО повторов; то же для активации. Токены усредняются.

    Записи со сбоем прогона в голосовании не участвуют: неотработавший вызов
    это не отрицательный ответ. Если не отработал ни один повтор, возвращается
    первая запись со своей ошибкой.
    """
    good = [r for r in records if not r.get("error")]
    if not good:
        return records[0]
    total = len(good)
    merged = dict(good[0])
    merged["runs"] = total
    merged["runs_requested"] = len(records)
    # Сбойный повтор нельзя терять молча: критерий прогона требует НИ ОДНОГО сбоя, а
    # запись, где остался хотя бы один успешный повтор, показывала errors = 0 и
    # проходила сравнение фаз как полная.
    failed = [r for r in records if r.get("error")]
    if failed:
        merged["runs_failed"] = len(failed)
        merged["runs_failed_reason"] = failed[0].get("error")
    merged["passed"] = sum(1 for r in good if r.get("passed")) * 2 > total
    merged["activated"] = sum(1 for r in good if r.get("activated")) * 2 > total
    merged["tokens"] = sum(int(r.get("tokens") or 0) for r in good) // total
    if total > 1:
        merged["passed_runs"] = f"{sum(1 for r in good if r.get('passed'))}/{total}"
    for key in ("missing_expect", "hit_forbid", "bsp_findings"):
        seen: list[str] = []
        for record in good:
            for item in record.get(key) or []:
                if item not in seen:
                    seen.append(item)
        merged[key] = seen
    return merged


def run_phase(
    phase: str,
    codex: str,
    cases: list[Case],
    workdir: Path,
    skill: str,
    model: str | None,
    timeout: int,
    jobs: int,
    index: BspIndex | None,
    artifacts: Path | None,
    runs: int = 1,
) -> list[dict]:
    """Прогнать все кейсы одной фазы, при jobs > 1 параллельно.

    Кейсы независимы друг от друга, поэтому распараллеливаются без общего
    состояния. Порядок результата приводится к порядку кейсов, чтобы отчет
    не прыгал между прогонами.

    При runs > 1 каждый кейс идет несколько раз, и повторы сводятся по
    большинству через merge_runs.
    """
    repeats = max(1, runs)
    results: dict[str, list[dict]] = {c.ident: [] for c in cases}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(
                run_case, codex, case, workdir, skill, model, timeout, index,
                artifacts, phase, attempt,
            ): case.ident
            for case in cases
            for attempt in range(1, repeats + 1)
        }
        for future in concurrent.futures.as_completed(futures):
            ident = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 - падение одного кейса не рушит прогон
                record = {"case": ident, "checked": False, "passed": False, "error": repr(exc)}
            results[ident].append(record)
            status = "ok" if record.get("passed") else "--"
            suffix = f" ({len(results[ident])}/{repeats})" if repeats > 1 else ""
            print(f"  [{phase}] {status} {ident}{suffix}", flush=True)
    return [merge_runs(results[c.ident]) for c in cases if results[c.ident]]


# --------------------------------------------------------------------------
# Отчет
# --------------------------------------------------------------------------


def summarize(records: list[dict]) -> dict:
    """Свести записи фазы в счета: сколько прошло, активировалось, дало претензии."""
    checked = [r for r in records if r.get("checked")]
    return {
        "cases": len(records),
        "checked": len(checked),
        "passed": sum(1 for r in checked if r.get("passed")),
        "activated": sum(1 for r in records if r.get("activated")),
        "bsp_findings": sum(len(r.get("bsp_findings") or []) for r in records),
        "errors": sum(1 for r in records if r.get("error")),
        # Кейс, где упал хотя бы один повтор, тоже неполный: критерий требует
        # ни одного сбоя, а не большинства удачных попыток.
        "partial": sum(1 for r in records if r.get("runs_failed")),
        "tokens": sum(int(r.get("tokens") or 0) for r in records),
    }


def print_report(skill: str, report: dict) -> None:
    """Напечатать сводку прогона: строка на фазу плюс разбор непрошедших кейсов."""
    print()
    print(f"Скил: {skill}")
    header = f"{'фаза':<7}{'прошло':>10}{'активация':>12}{'претензии БСП':>16}{'ошибки':>9}{'токены':>10}"
    print(header)
    print("-" * len(header))
    for phase in ("red", "green"):
        stats = report.get(phase, {}).get("summary")
        if not stats:
            continue
        passed = f"{stats['passed']}/{stats['checked']}"
        print(
            f"{phase:<7}{passed:>10}{stats['activated']:>12}"
            f"{stats['bsp_findings']:>16}{stats['errors']:>9}{stats['tokens']:>10}"
        )

    for phase in ("red", "green"):
        failures = [
            r
            for r in report.get(phase, {}).get("cases", [])
            if r.get("checked") and not r.get("passed")
        ]
        if not failures:
            continue
        print(f"\nНе прошли в фазе {phase}:")
        for record in failures:
            reasons: list[str] = []
            if record.get("missing_expect"):
                reasons.append("нет ожидаемого: " + ", ".join(record["missing_expect"]))
            if record.get("hit_forbid"):
                reasons.append("найдено запрещенное: " + ", ".join(record["hit_forbid"]))
            if record.get("bsp_findings"):
                reasons.append("; ".join(record["bsp_findings"]))
            if record.get("no_activation"):
                reasons.append("агент не открыл файлы скила: результат не про скил")
            if record.get("error"):
                reasons.append(record["error"])
            if record.get("passed_runs"):
                reasons.append(f"повторов пройдено {record['passed_runs']}")
            if record.get("runs_failed"):
                reasons.append(
                    f"повторов упало {record['runs_failed']} из "
                    f"{record.get('runs_requested', '?')}: {record.get('runs_failed_reason')}"
                )
            print(f"  {record['case']}: {' | '.join(reasons) or 'без деталей'}")

    for phase in ("red", "green"):
        broken = [r for r in report.get(phase, {}).get("cases", []) if r.get("error")]
        if not broken:
            continue
        print(f"\nНе отработали в фазе {phase} ({len(broken)}) - это сбой прогона, а не скила:")
        for record in broken:
            print(f"  {record['case']}: {record['error']}")
        if len(broken) == len(report[phase]["cases"]):
            print(f"  Фаза {phase} не дала НИ ОДНОГО ответа: ее числа читать нельзя.")

    unchecked = [
        r["case"]
        for r in report.get("green", {}).get("cases", [])
        if not r.get("checked") and not r.get("error")
    ]
    if unchecked:
        print(f"\nБез машинных проверок ({len(unchecked)}): {', '.join(unchecked)}")
        print("  Добавь в кейс поля expect / forbid / checks_bsl, иначе прогон ничего не доказывает.")


def list_skills() -> int:
    """Показать скилы с файлом кейсов и признак, переведены ли они на исполняемый формат."""
    rows: list[tuple[str, int, int]] = []
    for path in sorted(SKILLS_DIR.glob("*/evals/evals.json")):
        skill = path.parent.parent.name
        try:
            _, cases = load_cases(skill)
        except EvalError:
            continue
        rows.append((skill, len(cases), sum(1 for c in cases if c.has_machine_checks)))
    ready = sum(1 for _, _, machine in rows if machine)
    print(f"{'скил':<32}{'кейсов':>8}{'машинных':>10}")
    print("-" * 50)
    for skill, total, machine in rows:
        print(f"{skill:<32}{total:>8}{machine:>10}")
    print("-" * 50)
    print(f"Скилов с кейсами: {len(rows)}, из них с машинными проверками: {ready}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Собрать разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Поведенческий прогон скила: без скила и со скилом",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skill", help="имя скила из skills/")
    parser.add_argument("--case", action="append", default=[], help="прогнать только эти кейсы")
    parser.add_argument(
        "--phase", choices=("red", "green", "both"), default="both", help="какие фазы гонять"
    )
    parser.add_argument("--runs", type=int, default=1, help="повторов на кейс, большинство решает")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="параллельных запусков агента")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="секунд на один запуск")
    parser.add_argument("--model", help="переопределить модель агента")
    parser.add_argument("--codex", help="путь к Codex CLI, по умолчанию ищется пакетный")
    parser.add_argument("--workdir", help="рабочий каталог агента, по умолчанию временный в репо")
    parser.add_argument("--artifacts", help="куда сложить ответы агента")
    parser.add_argument("--json", dest="json_out", help="записать отчет в файл")
    parser.add_argument("--list", action="store_true", help="показать скилы с кейсами и выйти")
    parser.add_argument("--dry-run", action="store_true", help="проверить кейсы и выйти без запуска")
    return parser


def main() -> int:
    """Точка входа: разобрать аргументы, прогнать фазы, напечатать отчет.

    Возвращает 0 при достигнутых порогах, 1 при непройденных кейсах,
    2 при ошибке подготовки прогона.
    """
    args = build_parser().parse_args()

    if args.list:
        return list_skills()
    if not args.skill:
        print("Укажи --skill или --list", file=sys.stderr)
        return 2

    try:
        cases_path, cases = load_cases(args.skill)
    except EvalError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2

    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.ident in wanted]
        if not cases:
            print(f"ОШИБКА: кейсы не найдены: {', '.join(sorted(wanted))}", file=sys.stderr)
            return 2

    machine = [c for c in cases if c.has_machine_checks]
    print(f"Кейсов: {len(cases)}, с машинными проверками: {len(machine)}  ({cases_path})")

    if args.dry_run:
        for case in cases:
            flags = []
            if case.expect:
                flags.append(f"expect {len(case.expect)}")
            if case.forbid:
                flags.append(f"forbid {len(case.forbid)}")
            if case.checks_bsl:
                flags.append("checks_bsl")
            print(f"  {case.ident}: {', '.join(flags) or 'без машинных проверок'}")
        if not machine:
            print("\nНи одного машинного условия: прогон подтвердит только факт ответа агента.")
        return 0

    skill_dir = SKILLS_DIR / args.skill
    if not (skill_dir / "SKILL.md").is_file():
        print(f"ОШИБКА: нет {skill_dir / 'SKILL.md'}", file=sys.stderr)
        return 2

    try:
        codex = resolve_codex(args.codex)
    except EvalError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2

    workdir = Path(args.workdir).resolve() if args.workdir else REPO_ROOT / ".tmp" / "skill-evals"
    workdir.mkdir(parents=True, exist_ok=True)
    staged = workdir / ".agents" / "skills" / args.skill

    conflicts = conflicting_installs(args.skill, staged)
    if conflicts:
        print("ОШИБКА: скил уже установлен и протечет в фазу RED:", file=sys.stderr)
        for path in conflicts:
            print(f"  {path}", file=sys.stderr)
        print("  Убери установленную копию либо гоняй только --phase green.", file=sys.stderr)
        if args.phase != "green":
            return 2

    index = BspIndex.load()
    artifacts = Path(args.artifacts).resolve() if args.artifacts else None
    print(f"Агент: {codex}")
    print(f"Справочник БСП: {'загружен' if index else 'НЕ найден, сверка вызовов пропущена'}")

    report: dict = {"skill": args.skill, "runs": args.runs, "model": args.model}
    phases = ("red", "green") if args.phase == "both" else (args.phase,)

    for phase in phases:
        print(f"\nФаза {phase}:")
        context = (
            staged_skill(skill_dir, staged) if phase == "green" else contextlib.nullcontext()
        )
        try:
            with context:
                records = run_phase(
                    phase, codex, cases, workdir, args.skill, args.model,
                    args.timeout, args.jobs, index, artifacts, args.runs,
                )
        except EvalError as exc:
            print(f"ОШИБКА: {exc}", file=sys.stderr)
            return 2
        report[phase] = {"cases": records, "summary": summarize(records)}

    print_report(args.skill, report)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        print(f"\nОтчет: {args.json_out}")

    green = report.get("green", {}).get("summary")
    if green and green["errors"] == green["cases"]:
        print("\nПрогон не состоялся: ни один вызов агента не отработал.", file=sys.stderr)
        return 2
    red = report.get("red", {}).get("summary")
    if green and green["checked"]:
        # Частично сбойная фаза неполна с ОБЕИХ сторон: критерий требует ни одного сбоя.
        # Проверка partial только для RED оставляла дыру - GREEN с одним упавшим повтором
        # из трех показывала errors = 0 и объявлялась пройденной.
        ok = (
            green["passed"] == green["checked"]
            and not green["errors"]
            and not green.get("partial")
        )
        if green.get("partial") and green["passed"] == green["checked"]:
            print(
                f"\nВ фазе GREEN кейсов с упавшими повторами: {green['partial']}. "
                "Прогон неполный, результат не засчитан.",
                file=sys.stderr,
            )
        # Сравнение фаз имеет смысл, только когда RED отработала целиком. Сбойная RED
        # дает мало пройденных кейсов, и сравнение "RED прошел меньше" выполнялось бы
        # само собой, пропуская скил, который ничего не добавил.
        if ok and red is not None:
            if red["errors"] or red.get("partial") or red["checked"] < green["checked"]:
                print(
                    f"\nФаза RED отработала не полностью: проверено {red['checked']} из "
                    f"{green['checked']}, сбоев {red['errors']}, кейсов с упавшими "
                    f"повторами {red.get('partial', 0)}. Сравнить фазы нельзя, "
                    "прогнать RED заново.",
                    file=sys.stderr,
                )
                return 2
            if red["passed"] >= green["passed"]:
                print(
                    f"\nRED прошел {red['passed']} из {red['checked']}, GREEN "
                    f"{green['passed']} из {green['checked']}: кейсы не различают скил.",
                    file=sys.stderr,
                )
                return 1
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        sys.exit(2)
