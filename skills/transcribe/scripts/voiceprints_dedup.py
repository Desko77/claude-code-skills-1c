"""voiceprints_dedup.py - разбор и слияние дублей в голосовой базе.

Зачем. Авто-пополнение заносит имя так, как его назвала модель, поэтому один человек со временем
растекается по нескольким записям: Дмитрий / Дима / Дим / Дмитрий Иванов. Вред конкретный -
отпечатки одного голоса размазаны по записям (в каждой не больше max_prints), а правило "одно имя
не вешаем на две метки" тут не срабатывает, потому что имена РАЗНЫЕ. Живой пример: на интервью
07.08.2026 один и тот же интервьюер опознался и как "Дмитрий" (0.908), и как "Дмитрий Иванов"
(0.745) на двух метках - то есть в протоколе он вышел бы двумя участниками.

ГЛАВНОЕ ОГРАНИЧЕНИЕ, замерено на этой самой базе 07.08.2026 (команда `verify`):

    отпечатки НЕ различают людей при сверке записей между собой.

    свои пары   средний косинус 0.413 (минимум 0.117)
    чужие пары  средний косинус 0.358 (МАКСИМУМ 0.972)
    44.7% чужих пар выглядят не хуже медианы своих; нормировка по когорте (AS-norm) не помогает

Даже внутри ОДНОЙ записи отпечатки с разных встреч расходятся: у самой полной записи (6 отпечатков,
9 встреч) минимум 0.150. Опознание на живой встрече работает не абсолютным порогом, а тем, что
берется лучший кандидат, и держится на запасе в 0.01-0.10 - то есть на грани.

Поэтому сливать по ГОЛОСУ здесь нельзя: это склеит разных людей. Слияние идет по ИМЕНИ (Дима, Дим
-> Дмитрий; Стас -> Станислав), а близость голоса печатается лишь как справка. Решение в любом
случае за человеком: "Алексей" и "Алексей Петров" на реальной встрече оказались РАЗНЫМИ людьми,
а "Станислав" и "Стас" - одним, и по голосу это неразличимо.

    python voiceprints_dedup.py verify [--db PATH]              # разделяющая способность базы
    python voiceprints_dedup.py report [--db PATH] [--plan plan.json]
    python voiceprints_dedup.py apply --plan plan.json [--db PATH] [--dry-run]

report печатает разбор и, если задан --plan, пишет ЗАГОТОВКУ: в merges попадают только слияния по
имени, все остальное - в review, руками. apply делает резервную копию базы рядом (db.json.bak-<N>)
до записи: база накапливается месяцами и восстановлению не подлежит.
"""
import argparse
import json
import shutil
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voiceprints as vp  # noqa: E402
import speaker_validator as sv  # noqa: E402

# Порог "это один и тот же голос". Взят равным боевому порогу опознания: если база при таком
# значении назвала бы обе записи одним человеком, значит и хранить их порознь смысла нет.
SAME_VOICE = vp.MATCH_THRESHOLD
# Ниже этого голоса заведомо разные - пару даже не показываем, чтобы не топить отчет в шуме.
CLEARLY_DIFFERENT = 0.45


def pair_similarity(entry_a, entry_b):
    """Близость двух записей базы: МАКСИМУМ по всем парам отпечатков.

    Максимум, а не среднее: отпечатки одного человека сняты с разных встреч, микрофонов и каналов,
    и часть из них закономерно далека друг от друга. Одно уверенное совпадение доказывает, что это
    один голос, а десяток слабых этого не опровергает.
    """
    best = 0.0
    for pa in entry_a.get("prints", []):
        for pb in entry_b.get("prints", []):
            best = max(best, vp._cos(pa, pb))
    return best


def _looks_like_placeholder(name):
    """Заглушка вместо имени: Коллега1, Участник2, Спикер3 - в базе им не место."""
    low = name.lower().rstrip("0123456789 ")
    return low in {"коллега", "участник", "спикер", "докладчик", "гость", "модератор"}


def analyze(db):
    """Сгруппировать записи по личному имени. Голос идет справкой, решения на нем не строятся.

    Группа - это записи с одинаковым личным именем (Дмитрий, Дима, Дим, Дмитрий Иванов). Внутри
    группы разделяем два случая: голая форма имени (Дима) почти наверняка тот же человек, что и
    полная (Дмитрий), а запись С ФАМИЛИЕЙ - отдельный человек, пока человек не скажет иначе.
    """
    names = sorted(db)
    groups = {}
    for name in names:
        groups.setdefault(sv.first_name_key(name), []).append(name)

    dupes = []
    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        bare = [n for n in members if len(n.split()) == 1]
        full = [n for n in members if len(n.split()) > 1]
        pairs = [{"a": a, "b": b, "score": round(pair_similarity(db[a], db[b]), 3)}
                 for a, b in combinations(members, 2)]
        dupes.append({"key": key, "members": members, "bare": bare, "full": full,
                      "pairs": sorted(pairs, key=lambda p: -p["score"])})

    return {
        "groups": dupes,
        "placeholders": [n for n in names if _looks_like_placeholder(n)],
        "implausible": [n for n in names if not vp.is_plausible_name(n)],
        "no_prints": [n for n in names if not db[n].get("prints")],
    }


def discriminative_power(db):
    """Насколько отпечатки вообще различают людей: своя пара против чужой.

    Метрика честная только при условии, что имена в базе расставлены верно. База пополнялась
    автоматически по текстовому слою, который до 07.08.2026 систематически ошибался, поэтому часть
    "своих" пар может на деле быть чужими - и тогда цифры занижены. Отличить одно от другого без
    ручной разметки нельзя, но вывод для практики один и тот же: сливать по голосу нельзя.
    """
    import numpy as np

    vecs, owner = [], []
    for name, entry in db.items():
        for print_ in entry.get("prints", []):
            vecs.append(print_)
            owner.append(name)
    if len(vecs) < 4:
        return None
    matrix = np.asarray(vecs, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8
    sim = matrix @ matrix.T
    n = len(owner)
    same = np.array([[owner[i] == owner[j] for j in range(n)] for i in range(n)])
    iu = np.triu_indices(n, 1)
    own, alien = sim[iu][same[iu]], sim[iu][~same[iu]]
    if not len(own) or not len(alien):
        return None
    median_own = float(np.median(own))
    return {"prints": n, "own_mean": float(own.mean()), "own_min": float(own.min()),
            "alien_mean": float(alien.mean()), "alien_max": float(alien.max()),
            "alien_above_own_median": float((alien >= median_own).mean())}


def _merge_target(names):
    """Какое имя оставить при слиянии: самое информативное - с фамилией, затем самое длинное.
    Выбор все равно можно переопределить в плане вручную."""
    with_surname = [n for n in names if len(n.split()) > 1]
    pool = with_surname or list(names)
    return max(pool, key=lambda n: (len(n.split()), len(n)))


def build_draft_plan(report):
    """Заготовка плана. В merges идет только СЛИЯНИЕ ФОРМ ОДНОГО ИМЕНИ: Дима и Дим в Дмитрия,
    Стас в Станислава. Записи с фамилией остаются отдельными и уезжают в review - разные люди с
    одинаковым личным именем встречаются постоянно, и по голосу их здесь не различить."""
    drop = set(report["placeholders"] + report["no_prints"])
    merges, review = [], []
    for group in report["groups"]:
        # Записи из drop в слияния не тянем: иначе сливаем то, что через шаг удаляем.
        bare = [n for n in group["bare"] if n not in drop]
        full = [n for n in group["full"] if n not in drop]
        if len(bare) > 1:
            target = _merge_target(bare)
            merges.append({"into": target, "from": sorted(n for n in bare if n != target),
                           "why": "разные формы одного имени"})
        if full:
            review.append({"members": group["members"], "pairs": group["pairs"][:3],
                           "why": "есть записи с фамилией - это может быть ДРУГОЙ человек с тем же "
                                  "именем; по голосу не проверить, решать по памяти о встречах"})
    return {"merges": merges, "drop": sorted(drop), "review": review}


def apply_plan(db, plan, max_prints=6):
    """Применить план к базе. Возвращает (новая база, список строк отчета)."""
    log = []
    for merge in plan.get("merges", []):
        target, sources = merge.get("into"), merge.get("from", [])
        if target not in db:
            log.append(f"пропуск: целевой записи '{target}' в базе нет")
            continue
        entry = db[target]
        for src in sources:
            if src == target or src not in db:
                log.append(f"пропуск: записи '{src}' в базе нет")
                continue
            other = db.pop(src)
            entry["prints"].extend(other.get("prints", []))
            for key in ("projects", "meetings"):
                for val in other.get(key, []):
                    if val not in entry.setdefault(key, []):
                        entry[key].append(val)
            log.append(f"слито '{src}' -> '{target}'")
        # Отпечатков держим не больше max_prints - как и при обычном enroll; оставляем ПОСЛЕДНИЕ,
        # они сняты на свежих встречах и ближе к тому, как человек звучит сейчас.
        if len(entry["prints"]) > max_prints:
            log.append(f"'{target}': отпечатков {len(entry['prints'])} -> оставляю {max_prints}")
            entry["prints"] = entry["prints"][-max_prints:]

    for name in plan.get("drop", []):
        if db.pop(name, None) is not None:
            log.append(f"удалено '{name}'")
    return db, log


def _backup(path):
    path = Path(path)
    for i in range(1, 100):
        candidate = path.with_suffix(path.suffix + f".bak-{i}")
        if not candidate.exists():
            shutil.copy2(path, candidate)
            return candidate
    raise RuntimeError("не нашлось свободного имени для резервной копии")


def cmd_verify(args):
    db = vp.load_db(args.db)
    stats = discriminative_power(db)
    if not stats:
        print("Слишком мало отпечатков для оценки.")
        return
    print(f"Отпечатков: {stats['prints']}")
    print(f"  свои пары:  средний {stats['own_mean']:.3f}, минимум {stats['own_min']:.3f}")
    print(f"  чужие пары: средний {stats['alien_mean']:.3f}, МАКСИМУМ {stats['alien_max']:.3f}")
    print(f"  чужих пар не хуже медианы своих: {stats['alien_above_own_median']*100:.1f}%")
    if stats["alien_above_own_median"] > 0.2:
        print("\nВЫВОД: отпечатки НЕ различают людей при сверке записей между собой. Сливать по "
              "голосу нельзя - склеит разных. Опознание на встрече держится на выборе лучшего "
              "кандидата, а не на пороге, и потому ненадежно вне однородной серии записей.")


def cmd_report(args):
    db = vp.load_db(args.db)
    if not db:
        print("База пуста.")
        return
    report = analyze(db)
    print(f"Записей в базе: {len(db)}, отпечатков: "
          f"{sum(len(e.get('prints', [])) for e in db.values())}\n")

    print("ГРУППЫ ПО ЛИЧНОМУ ИМЕНИ (близость голоса - справка, решение по ней НЕ принимается):")
    for group in report["groups"]:
        print(f"\n  {group['key']}: {', '.join(group['members'])}")
        if len(group["bare"]) > 1:
            print(f"    -> слить формы одного имени: {', '.join(group['bare'])}")
        for name in group["full"]:
            print(f"    -> {name}: с фамилией, оставляю отдельно (может быть другой человек)")
        for pair in group["pairs"][:3]:
            print(f"       голос {pair['score']:.3f}  {pair['a']} <-> {pair['b']}")
    if not report["groups"]:
        print("  дублей по имени нет")

    junk = sorted(set(report["placeholders"] + report["implausible"] + report["no_prints"]))
    if junk:
        print(f"\nМУСОРНЫЕ ЗАПИСИ (заглушки, инициалы, пустые): {', '.join(junk)}")

    if args.plan:
        plan = build_draft_plan(report)
        Path(args.plan).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nЗаготовка плана записана: {args.plan}")
        print("  merges - слияние разных форм одного имени, можно применять;")
        print("  review - записи с фамилией, решать по памяти о встречах;")
        print("  drop   - заглушки и записи без отпечатков.")


def cmd_apply(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    db = vp.load_db(args.db)
    before = len(db)
    db, log = apply_plan(db, plan)
    for line in log:
        print("  " + line)
    print(f"\nЗаписей было {before}, стало {len(db)}")
    if args.dry_run:
        print("Пробный прогон (--dry-run): база НЕ изменена.")
        return
    path = Path(args.db or vp.DEFAULT_DB)
    if path.exists():
        print(f"Резервная копия: {_backup(path).name}")
    vp.save_db(db, args.db)
    print("База сохранена.")


def main():
    ap = argparse.ArgumentParser(description="Разбор и слияние дублей в голосовой базе")
    ap.add_argument("--db", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ver = sub.add_parser("verify", help="Насколько отпечатки вообще различают людей")
    p_ver.set_defaults(func=cmd_verify)

    p_rep = sub.add_parser("report", help="Показать дубли и подготовить план")
    p_rep.add_argument("--plan", default=None, help="Куда записать заготовку плана (JSON)")
    p_rep.set_defaults(func=cmd_report)

    p_app = sub.add_parser("apply", help="Применить план слияния")
    p_app.add_argument("--plan", required=True)
    p_app.add_argument("--dry-run", action="store_true")
    p_app.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
