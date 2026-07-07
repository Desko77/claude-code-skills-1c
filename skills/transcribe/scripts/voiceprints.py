"""voiceprints.py - голосовая база (enrollment) + идентификация кластеров по ГОЛОСУ.

Единая база с провенансом: {имя: {prints: [вектор,...], projects: [...], meetings: [...]}}.
Отпечаток кластера считает diarize_sherpa (--emit-voiceprints, eres2net-эмбеддинги). Здесь -
хранение, матчинг (косинус) и enrollment (ручной + авто). Голоса - чувствительные данные:
хранить ЛОКАЛЬНО, папку voiceprints/ не коммитить.

Слой «по голосу» (абсолютная идентификация, узнаёт даже неназванных, помнит между встречами) -
это БОЛЬШЕ, чем делает Gemini (тот вяжет имена только в контексте одной записи).

CLI:
    python voiceprints.py list [--db PATH]
    python voiceprints.py enroll --prints voiceprints.json --map SPEAKER_00=Имя1,SPEAKER_01=Имя2 \
           --project МойПроект --meeting "Встреча 2026-01-01" [--db PATH]
    python voiceprints.py match --prints voiceprints.json [--db PATH] [--threshold 0.5]
"""
import argparse
import json
from pathlib import Path

import numpy as np

DEFAULT_DB = Path.home() / ".claude" / "skills" / "transcribe" / "voiceprints" / "db.json"
MATCH_THRESHOLD = 0.7  # косинус. Откалибровано на реальных записях: различимые голоса дают >0.8 между
#   встречами, похожие (близкий тембр) ~0.5 (размыто). 0.7 = высокая точность: голос называет только
#   уверенно различимых, похожих/неоднозначных отдаём text-binding'у (слои дополняют друг друга).


def load_db(path=None):
    path = Path(path or DEFAULT_DB)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_db(db, path=None):
    path = Path(path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def _cos(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def is_plausible_name(name):
    """Похоже на реальное имя, а не на мусор/инициалы - гард для энролла и матчинга.
    Мусор: короче 3 символов ИЛИ одни заглавные буквы длиной <=3 (инициалы). 'Иванов' - да, 'КС' - нет."""
    n = (name or "").strip()
    if len(n) < 3:
        return False
    letters = [c for c in n if c.isalpha()]
    if letters and len(letters) <= 3 and all(c.isupper() for c in letters):
        return False
    return True


def identify(cluster_prints, db, threshold=MATCH_THRESHOLD, project=None):
    """Сопоставить отпечатки кластеров {SPEAKER_XX: vec} с базой -> {SPEAKER_XX: (имя, близость)}.

    Только уверенные (близость >= threshold). Жадно по убыванию близости, одно имя не вешаем на две
    метки и одну метку не на два имени. Мусорные имена (КС, инициалы) в матче НЕ участвуют - чтобы
    кривая запись не выиграла матч и не подменила корректное имя.
    project: если задан, матчим только против записей ТОГО ЖЕ проекта (записи без проекта считаем
    глобальными и матчим всегда); записи ЧУЖОГО проекта исключаем - защита от кросс-проектных совпадений."""
    cand = []  # (score, spk, name)
    for spk, vec in cluster_prints.items():
        for name, entry in db.items():
            if not is_plausible_name(name):   # мусорную запись (КС) не матчим
                continue
            if project and entry.get("projects") and project not in entry["projects"]:
                continue   # запись другого проекта - не матчим (провенанс из --project)
            best = max((_cos(vec, p) for p in entry.get("prints", [])), default=0.0)
            if best >= threshold:
                cand.append((best, spk, name))
    cand.sort(reverse=True)
    used_spk, used_name, result = set(), set(), {}
    for score, spk, name in cand:
        if spk in used_spk or name in used_name:
            continue
        result[spk] = (name, round(score, 3))
        used_spk.add(spk)
        used_name.add(name)
    return result


def enroll(db, name, vec, project=None, meeting=None, max_prints=6):
    """Добавить отпечаток голоса под именем (с провенансом). До max_prints отпечатков на имя
    (разные микрофоны/каналы). Возвращает db (мутирует)."""
    entry = db.setdefault(name, {"prints": [], "projects": [], "meetings": []})
    entry["prints"].append([round(float(x), 6) for x in vec])
    entry["prints"] = entry["prints"][-max_prints:]
    for key, val in (("projects", project), ("meetings", meeting)):
        if val and val not in entry[key]:
            entry[key].append(val)
    return db


# ---------------- CLI ----------------

def _main():
    ap = argparse.ArgumentParser(description="Голосовая база спикеров")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--db", default=None)

    p_list = sub.add_parser("list", help="Показать базу")

    p_enr = sub.add_parser("enroll", help="Занести отпечатки кластеров под именами")
    p_enr.add_argument("--prints", required=True, help="voiceprints.json от diarize_sherpa")
    p_enr.add_argument("--map", required=True, help="SPEAKER_00=Имя,SPEAKER_01=Имя2")
    p_enr.add_argument("--project", default=None)
    p_enr.add_argument("--meeting", default=None)

    p_match = sub.add_parser("match", help="Сопоставить отпечатки с базой")
    p_match.add_argument("--prints", required=True)
    p_match.add_argument("--threshold", type=float, default=MATCH_THRESHOLD)

    args = ap.parse_args()
    db = load_db(args.db)

    if args.cmd == "list":
        if not db:
            print("База пуста.")
        for name, e in db.items():
            print(f"  {name}: {len(e.get('prints', []))} отпечатк(ов); проекты={e.get('projects')}; "
                  f"встречи={e.get('meetings')}")
        return

    prints = json.loads(Path(args.prints).read_text(encoding="utf-8"))

    if args.cmd == "enroll":
        mp = dict(kv.split("=", 1) for kv in args.map.split(","))
        for spk, name in mp.items():
            if spk in prints:
                enroll(db, name.strip(), prints[spk], args.project, args.meeting)
                print(f"  занесён {spk} -> {name.strip()}")
            else:
                print(f"  [!] {spk} нет в отпечатках", flush=True)
        save_db(db, args.db)
        print("База сохранена.")
    elif args.cmd == "match":
        res = identify(prints, db, args.threshold)
        for spk, (name, score) in res.items():
            print(f"  {spk} -> {name} (близость {score})")
        unmatched = [s for s in prints if s not in res]
        if unmatched:
            print(f"  не опознаны: {unmatched}")


if __name__ == "__main__":
    _main()
