#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Профиль правки: класс объема, архетипы, среда и обязательные проверки.

Считается поверх канонического множества изменений (tools/changeset.py,
compute_changeset) по спецификации skills/1c-code-review/references/profile-map.md.
Строки объема - git diff --numstat относительно base (файл множества без записи
numstat считается целиком), архетипы - по путям множества и тексту diff (добавленные
строки и контекст). Событие scope пишется в каталог следа общим модулем
tools/quality_events.py.

Использование:
  python tools/change_profile.py --repo <каталог> --base <коммит> [--session <id>]
      [--vendor-copy "<обоснование>"] [--json] [--no-write]

Без --json печатается таблица для человека: класс, driver, архетипы, среды,
обязательные проверки. Коды выхода: 0 расчет выполнен, 2 отказ (каталог не найден,
не репозиторий, git недоступен, base не разрешается, недопустимая сессия).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import unicodedata
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

CODE_SUFFIXES = (".bsl", ".os")
METADATA_SUFFIXES = (".mdo", ".form", ".dcs")
RIGHTS_SUFFIXES = ("rights.xml", ".rights")
EDT_PROJECT_MARKER = "com._1c.g5.v8.dt"

# Порядок архетипов в профиле - канонический список каталога дефектов.
ARCHETYPE_ORDER = ("транзакция", "блокировка", "права", "запрос", "модуль формы",
                   "событие объекта", "новый общий модуль", "перехват в расширении",
                   "изменение метаданных", "любой BSL")

# Текстовые маркеры архетипов: поиск подстрок с учетом регистра в добавленных
# строках и контексте diff (устойчивые написания).
TEXT_MARKERS = {
    "транзакция": ("НачатьТранзакцию",),
    "блокировка": ("БлокировкаДанных", "Заблокировать"),
    "права": ("УстановитьПривилегированныйРежим", "ПравоДоступа"),
    "запрос": ("Новый Запрос", "ВЫБРАТЬ"),
    "событие объекта": ("ОбработкаПроведения", "ПередЗаписью", "ПриЗаписи",
                        "ОбработкаУдаленияПроведения"),
    "перехват в расширении": ("&Вместо", "&Перед", "&После", "&ИзменениеИКонтроль"),
}


def _run_git(args: list[str], cwd: Path) -> bytes:
    """Выполнить git и вернуть stdout; отказ - ChangesetError с диагностикой git."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)
    except OSError as exc:
        raise changeset.ChangesetError(f"git недоступен: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise changeset.ChangesetError(
            f"git {' '.join(args)} завершился с кодом {proc.returncode}: {detail}")
    return proc.stdout


def _numstat(top: Path, base: str) -> dict[str, int]:
    """Суммы добавленных и удаленных строк по путям из git diff --numstat -z.

    Ключи - новые пути NFC (как в каноническом множестве). Формат -z: поля записи
    разделены NUL, отображаемый синтаксис переименований не разбирается. Обычная
    запись - одно поле <добавлено><TAB><удалено><TAB><путь>; переименование - три
    поля: числа (третий элемент после табуляции пуст), прежний путь, новый путь.
    Бинарные файлы дают прочерк и считаются нулем.
    """
    raw = _run_git(["-c", "core.quotepath=false", "diff", "--numstat", "-z", "-M",
                    "--no-color", "--no-ext-diff", "--no-textconv", base], top)
    result: dict[str, int] = {}
    tokens = raw.split(b"\0")
    i = 0
    while i < len(tokens) and tokens[i]:
        fields = tokens[i].decode("utf-8", errors="replace").split("\t")
        i += 1
        if len(fields) < 3:
            continue
        added, deleted, tail = fields[0], fields[1], "\t".join(fields[2:])
        added_n = 0 if added == "-" else int(added)
        deleted_n = 0 if deleted == "-" else int(deleted)
        if tail:
            path = tail
        elif i + 1 < len(tokens) and tokens[i] and tokens[i + 1]:
            path = tokens[i + 1].decode("utf-8", errors="replace")  # новый путь
            i += 2
        else:
            continue
        result[unicodedata.normalize("NFC", path)] = added_n + deleted_n
    return result


def _diff_texts(top: Path, base: str, wanted: set[str]) -> dict[str, list[str]]:
    """Добавленные и контекстные строки diff по путям множества: один вызов git diff.

    Ключи - новые пути записей (строка +++ b/<путь>), значения - списки строк
    (добавленные и контекстные, префикс +/пробел снят). Файлы вне wanted и удаления
    (+++ /dev/null) пропускаются; пути NFC-нормализуются.
    """
    raw = _run_git(["-c", "core.quotepath=false", "diff", "-M", "-U3",
                    "--no-color", "--no-ext-diff", "--no-textconv", base], top)
    texts: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        if line.startswith("+++ b/"):
            candidate = unicodedata.normalize("NFC", line[6:])
            current = candidate if candidate in wanted else None
        elif current is None:
            continue
        elif line.startswith("+"):
            texts.setdefault(current, []).append(line[1:])
        elif line.startswith(" "):
            texts.setdefault(current, []).append(line[1:])
    return texts


def _count_lines(data: bytes) -> int:
    """Число строк файла: переводы строк плюс неполная последняя строка."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _is_code_file(path: str) -> bool:
    """Файл кода: суффикс .bsl или .os."""
    return path.lower().endswith(CODE_SUFFIXES)


def _is_rights_path(path: str) -> bool:
    """Путь прав: Rights.xml, *.rights или сегмент Roles."""
    lowered = path.lower()
    return lowered.endswith(RIGHTS_SUFFIXES) or "Roles" in Path(path).parts


def _is_metadata_file(path: str, top: Path) -> bool:
    """Файл метаданных: суффиксы EDT, пути прав либо XML выгрузки Конфигуратора.

    XML считается метаданными, когда в корне репозитория лежит Configuration.xml -
    признак выгрузки Конфигуратора (rules/edt-source-format.md).
    """
    if path.lower().endswith(METADATA_SUFFIXES):
        return True
    if _is_rights_path(path):
        return True
    return path.lower().endswith(".xml") and (top / "Configuration.xml").is_file()


def _is_form_module(path: str) -> bool:
    """Модуль формы: Forms/<имя>/Module.bsl, Form.form либо Ext/Form/Module.bsl."""
    return (path.endswith("Form.form")
            or path.endswith("Ext/Form/Module.bsl")
            or ("Forms" in Path(path).parts and path.endswith("Module.bsl")))


def _file_env(top: Path, path: str, cache: dict[Path, bool]) -> str:
    """Среда файла: edt при предке с .project, содержащим маркер проекта 1C:EDT.

    Предки обходятся от ближайшего каталога файла до корня репозитория включительно;
    решение по каталогу кешируется (дерево опрашивается один раз).
    """
    parts = Path(path).parts
    for depth in range(len(parts), -1, -1):
        ancestor = top.joinpath(*parts[:depth])
        if ancestor in cache:
            if cache[ancestor]:
                return "edt"
            continue
        project = ancestor / ".project"
        is_edt = project.is_file() and EDT_PROJECT_MARKER in project.read_text(
            encoding="utf-8", errors="replace")
        cache[ancestor] = is_edt
        if is_edt:
            return "edt"
    return "configurator"


def required_checks(archetypes: set[str], envs: set[str], volume_class: str) -> list[str]:
    """Обязательный состав проверок по таблице profile-map.md.

    Идентификаторы фиксированы: <проверка>@<среда>, среда any - проверка не зависит
    от среды. Состав пересчитывается после окончательного класса, поэтому понижение
    класса убирает cross_review и adversarial_audit.
    """
    required: set[str] = set()
    has_edt = "edt" in envs
    has_cfg = "configurator" in envs
    if "любой BSL" in archetypes:
        if has_edt:
            required |= {"code_review@edt", "ask_1c_ai@edt"}
        if has_cfg:
            required |= {"syntaxcheck@configurator", "bsl_validate@configurator"}
    if "запрос" in archetypes:
        if has_edt:
            required.add("validate_query@edt")
        if has_cfg:
            required.add("query_validate@configurator")
    if "изменение метаданных" in archetypes:
        if has_edt:
            required |= {"validate_for_export@edt", "get_project_errors@edt"}
        if has_cfg:
            required.add("meta_validate@configurator")
    if "права" in archetypes:
        if has_edt:
            required.add("security_audit@edt")
        if has_cfg:
            required.add("role_validate@configurator")
    if archetypes & {"транзакция", "блокировка", "событие объекта"}:
        required.add("catalog_read:TXN@any")
    if "перехват в расширении" in archetypes:
        required.add("catalog_read:EXT@any")
        if has_edt:
            required.add("validate_for_export@edt")
    if "модуль формы" in archetypes:
        required |= {"catalog_read:CLIENT@any", "catalog_read:FORM@any"}
    if volume_class in ("C2", "C3"):
        required.add("cross_review@any")
    if volume_class == "C3":
        required.add("adversarial_audit@any")
    return sorted(required)


def compute_profile(repo_dir: Path | str, base: str = "HEAD",
                    vendor_copy: str | None = None) -> dict:
    """Профиль правки по спецификации profile-map.md поверх канонического множества.

    Возвращает поля профиля с base и diffHash: volume (class, bslLines, bslFiles),
    files, archetypes, env, driver, required, analyzerConfig, vendorCopy. Множество
    считает compute_changeset (tools/changeset.py), здесь оно только читается.
    """
    cs = changeset.compute_changeset(repo_dir, base)
    top = quality_events.repo_top(repo_dir)
    files = cs["files"]
    numstat = _numstat(top, base)
    wanted = {record["path"] for record in files if record["status"] != "deleted"}
    diff_texts = _diff_texts(top, base, wanted) if wanted else {}

    bsl_lines = 0
    bsl_files = 0
    archetypes: set[str] = set()
    envs: set[str] = set()
    env_cache: dict[Path, bool] = {}
    metadata_files: list[str] = []
    new_metadata: list[str] = []

    for record in files:
        path = record["path"]
        is_code = _is_code_file(path)
        is_meta = _is_metadata_file(path, top)
        if is_code:
            bsl_files += 1
            archetypes.add("любой BSL")
            lines = None
            if (record["status"] in ("modified", "added") and (top / path).is_file()
                    and (path not in numstat or path not in diff_texts)):
                # Арбитраж git rm --cached (numstat дает удаление, текст diff -
                # +++ /dev/null) либо записи numstat нет (неотслеживаемый): объем
                # и маркеры архетипов считаются по рабочему файлу целиком.
                data = (top / path).read_bytes()
                bsl_lines += _count_lines(data)
                lines = data.decode("utf-8", errors="replace").split("\n")
            elif path in numstat:
                bsl_lines += numstat[path]
                lines = diff_texts.get(path)
            if lines:
                text = "\n".join(lines)
                for archetype, markers in TEXT_MARKERS.items():
                    if any(marker in text for marker in markers):
                        archetypes.add(archetype)
        if is_meta:
            archetypes.add("изменение метаданных")
            metadata_files.append(path)
            if record["status"] == "added":
                new_metadata.append(path)
        if _is_rights_path(path):
            archetypes.add("права")
        if _is_form_module(path):
            archetypes.add("модуль формы")
        if record["status"] == "added" and "CommonModules" in Path(path).parts:
            archetypes.add("новый общий модуль")
        if path.lower().endswith(".dcs"):
            archetypes.add("запрос")
        if is_code or is_meta:
            envs.add(_file_env(top, path, env_cache))

    if not metadata_files and bsl_files == 0:
        volume_class, driver = "C0", "нет файлов кода и метаданных"
    elif new_metadata:
        volume_class = "C3"
        driver = f"архетип: новый объект метаданных: {new_metadata[0]}"
    elif bsl_lines > 300:
        volume_class, driver = "C3", f"объем: {bsl_lines} строк BSL"
    elif metadata_files:
        volume_class, driver = "C2", "архетип: изменение метаданных"
    elif bsl_lines > 30:
        volume_class, driver = "C2", f"объем: {bsl_lines} строк BSL"
    elif bsl_files > 2:
        volume_class, driver = "C2", f"объем: {bsl_files} файлов BSL"
    else:
        volume_class = "C1"
        driver = f"объем: {bsl_lines} строк BSL в {bsl_files} файлах"
    if vendor_copy and volume_class in ("C2", "C3"):
        volume_class, driver = "C1", "явное указание: калька типового"

    return {
        "base": cs["base"],
        "diffHash": cs["diffHash"],
        "volume": {"class": volume_class, "bslLines": bsl_lines, "bslFiles": bsl_files},
        "files": [record["path"] for record in files],
        "archetypes": [name for name in ARCHETYPE_ORDER if name in archetypes],
        "env": sorted(envs),
        "driver": driver,
        "required": required_checks(archetypes, envs, volume_class),
        "analyzerConfig": "project-config",
        "vendorCopy": vendor_copy,
    }


def render_table(profile: dict) -> str:
    """Таблица профиля для человека: класс, driver, архетипы, среды, проверки."""
    volume = profile["volume"]
    lines = [f"base: {profile['base']}",
             f"diffHash: {profile['diffHash']}",
             f"класс: {volume['class']} ({profile['driver']})",
             f"строк BSL: {volume['bslLines']} в {volume['bslFiles']} файлах",
             f"архетипы: {', '.join(profile['archetypes']) or '-'}",
             f"среда: {', '.join(profile['env']) or '-'}",
             "обязательные проверки:"]
    lines += [f"  {check}" for check in profile["required"]] or ["  -"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI: расчет профиля, запись scope и вывод JSON либо таблицы."""
    parser = argparse.ArgumentParser(
        description="Профиль правки: класс объема, архетипы, среда, обязательные проверки.")
    parser.add_argument("--repo", type=Path, default=Path("."), metavar="КАТАЛОГ",
                        help="каталог репозитория (по умолчанию текущий)")
    parser.add_argument("--base", default="HEAD", metavar="КОММИТ",
                        help="базовый коммит (по умолчанию HEAD)")
    parser.add_argument("--session", metavar="ИД",
                        help="идентификатор сессии: пишет событие scope в каталог следа")
    parser.add_argument("--vendor-copy", metavar="ОБОСНОВАНИЕ",
                        help="калька типового кода: понижает класс до C1 (условия - profile-map.md)")
    parser.add_argument("--json", action="store_true",
                        help="вывод JSON вместо таблицы")
    parser.add_argument("--no-write", action="store_true",
                        help="не писать событие scope")
    args = parser.parse_args(argv)
    try:
        profile = compute_profile(args.repo, args.base, args.vendor_copy)
        if args.session and not args.no_write:
            event = {"type": "scope", "at": quality_events.now_iso(),
                     "session": args.session, "diffHash": profile["diffHash"],
                     "producer": "profile", "volume": profile["volume"],
                     "files": profile["files"], "archetypes": profile["archetypes"],
                     "env": profile["env"], "driver": profile["driver"],
                     "required": profile["required"],
                     "analyzerConfig": profile["analyzerConfig"],
                     "vendorCopy": profile["vendorCopy"]}
            wrote = quality_events.write_event(args.repo, args.session, event)
            # stderr: stdout занят JSON либо таблицей, дополнительная строка ломает разбор.
            print(f"scope записан: {wrote}", file=sys.stderr)
    except (changeset.ChangesetError, quality_events.EventsError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_table(profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
