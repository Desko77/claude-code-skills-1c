#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Поиск по справочнику API БСП.

Справочник больше мегабайта и в контекст целиком не грузится - он спрашивается по месту.

  bsp-api.py find <текст>            поиск по имени метода, модулю, подсистеме, механизму
  bsp-api.py show <Модуль.Метод>     полная карточка метода
  bsp-api.py show <Метод>            все методы с таким именем, в каких модулях
  bsp-api.py module <Модуль>         состав модуля
  bsp-api.py modules [<текст>]       перечень модулей
  bsp-api.py subsystem <текст>       модули и механизмы подсистемы
  bsp-api.py overrides <текст>       переопределяемые обработчики
  bsp-api.py check <Модуль.Метод>    существует ли такой вызов; код возврата 1, если нет

Отборы: --av S|T|F|E|C (контекст), --sub <подсистема>, --version <версия>, --limit N.
"""
import argparse
import io
import json
import os
import re
import sys

AV_LONG = {'S': 'Сервер', 'C': 'Вызов сервера', 'T': 'Тонкий клиент',
           'F': 'Толстый клиент', 'E': 'Внешнее соединение'}
SRC_LONG = {
    'L': 'модуль назван в документации',
    'P': 'модуль из примера вызова, подтвержден реализацией',
    'PA': 'модуль из примера вызова плюс контексты выполнения',
    'A': 'модуль выбран по контекстам выполнения',
    'AP': 'контексты выполнения плюс пример вызова',
    'O': 'модуль объекта или менеджера',
    'OS': 'модуль объекта, выбран по подсистеме',
    'P?': 'модуль назван в примере, но в дистрибутиве этой версии такого метода нет',
    '?': 'модуль не определен однозначно',
}
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'bsp-api.jsonl')


def read_reference(path):
    if not os.path.exists(path):
        raise SystemExit('справочник не найден: %s\nсобрать: scripts/bsp-build.py --help' % path)
    with io.open(path, encoding='utf-8') as fh:
        header = json.loads(fh.readline())
        return header, [json.loads(line) for line in fh if line.strip()]


def av_text(code):
    return ', '.join(AV_LONG.get(c, c) for c in code) or 'не указана'


def matches(rec, words):
    """Совпадение по ВСЕМ словам запроса, а не по непрерывной подстроке.

    Запрос обычно описывает задачу ("реквизит объекта", "фоновое задание"), а слова из него
    в записи разнесены по имени, механизму и формулировке назначения. Поиск подстроки целиком
    такие запросы просто не находит.
    """
    hay = ' '.join(filter(None, [rec['n'], rec['m'], rec.get('sub'),
                                 rec.get('grp'), rec.get('o'), rec.get('sig')])).lower()
    return all(w in hay for w in words)


def keep(rec, args):
    if args.av and not all(c in rec.get('av', '') for c in args.av.upper()):
        return False
    if args.sub and args.sub.lower() not in (rec.get('sub') or '').lower():
        return False
    if args.version and args.version not in rec.get('v', []):
        return False
    return True


def line_of(rec):
    star = '' if rec['src'] in ('L', 'P', 'PA', 'O') else ' [?]'
    ver = ' [!]' if rec.get('was') else ''
    purpose = ('  - ' + rec['o']) if rec.get('o') else ''
    return '%s.%s%s%s   %s%s' % (rec['m'], rec['n'], star, ver, rec.get('av', ''), purpose)


def card(rec, header):
    out = []
    out.append('%s.%s' % (rec['m'], rec['n']))
    if rec.get('o'):
        out.append('  %s' % rec['o'])
    out.append('  %s' % rec['sig'])
    out.append('  контексты: %s' % av_text(rec.get('av', '')))
    if rec.get('p'):
        out.append('  параметры:')
        for p in rec['p']:
            bits = [p['n']]
            if p.get('t'):
                bits.append(p['t'])
            if p.get('d'):
                bits.append('по умолчанию ' + p['d'])
            if p.get('byval'):
                bits.append('Знач')
            out.append('    %s' % ' - '.join(bits))
    if rec.get('ret'):
        out.append('  возвращает: %s' % rec['ret'])
    out.append('  подсистема: %s%s' % (rec['sub'],
                                       ', механизм ' + rec['grp'] if rec.get('grp') else ''))
    out.append('  раздел: %s' % ('переопределяемый обработчик' if rec['sec'] == 'П'
                                 else 'программный интерфейс'))
    out.append('  версии: %s' % ', '.join(rec.get('v', [])))
    for ver, delta in (rec.get('was') or {}).items():
        bits = []
        if delta.get('sig'):
            bits.append('сигнатура была: %s' % delta['sig'])
        if delta.get('k'):
            bits.append('была %s' % ('функцией' if delta['k'] == 'Ф' else 'процедурой'))
        if delta.get('ret'):
            bits.append('возвращала %s' % delta['ret'])
        if delta.get('av'):
            bits.append('контексты были: %s' % av_text(delta['av']))
        if delta.get('sub'):
            bits.append('подсистема была: %s' % delta['sub'])
        out.append('  ВНИМАНИЕ, в %s иначе - %s' % (ver, '; '.join(bits)))
    mod = header['modules'].get(rec['m'])
    if mod:
        extra = ', повторное использование %s' % mod['reuse'] if mod.get('reuse') else ''
        out.append('  модуль: %s, методов %d%s' % (mod['kind'], mod.get('total', 0), extra))
        if mod.get('o'):
            out.append('  назначение модуля: %s' % mod['o'])
    out.append('  источник: %s' % SRC_LONG.get(rec['src'], rec['src']))
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['find', 'show', 'module', 'modules', 'subsystem',
                                        'overrides', 'check', 'stats'])
    ap.add_argument('query', nargs='?', default='')
    ap.add_argument('--db', default=DB)
    ap.add_argument('--av', help='отбор по контексту: S сервер, T тонкий, F толстый, E внешнее, C вызов сервера')
    ap.add_argument('--sub', help='отбор по подсистеме')
    ap.add_argument('--version', help='отбор по версии БСП')
    ap.add_argument('--limit', type=int, default=40)
    args = ap.parse_args()

    header, recs = read_reference(args.db)
    q = args.query.strip()
    ql = q.lower()

    if args.command == 'stats':
        print('версии: %s' % ', '.join(header['versions']))
        print('модулей: %d, методов: %d' % (len(header['modules']), len(recs)))
        subs = {}
        for r in recs:
            subs[r['sub']] = subs.get(r['sub'], 0) + 1
        for k in sorted(subs, key=lambda x: -subs[x])[:20]:
            print('   %5d  %s' % (subs[k], k))
        return 0

    if args.command == 'check':
        if '.' not in q:
            raise SystemExit('check ждет Модуль.Метод')
        mod, name = q.rsplit('.', 1)
        hit = [r for r in recs if r['m'].lower() == mod.lower() and r['n'].lower() == name.lower()]
        # Отбор по версии обязан действовать и здесь. Иначе на проекте с БСП 3.1.11 проверка
        # подтвердит метод, появившийся только в 3.2.1, - то есть сделает ровно обратное тому,
        # ради чего ее зовут.
        if hit and args.version:
            wrong = [r for r in hit if args.version not in r.get('v', [])]
            hit = [r for r in hit if args.version in r.get('v', [])]
            if not hit and wrong:
                print('%s - в версии %s НЕ СУЩЕСТВУЕТ; есть в: %s'
                      % (q, args.version,
                         ', '.join(sorted(set(v for r in wrong for v in r.get('v', []))))))
                return 1
        if hit:
            print('%s.%s - есть, %s' % (hit[0]['m'], hit[0]['n'], hit[0]['sig']))
            return 0
        same = [r for r in recs if r['n'].lower() == name.lower()]
        print('%s - НЕ НАЙДЕН в справочнике БСП' % q)
        if same:
            print('метод с таким именем есть в: %s' % ', '.join(sorted({r['m'] for r in same})))
        near = [r for r in recs if r['m'].lower() == mod.lower()]
        if near and not same:
            print('модуль есть, метода нет. Похожие имена в модуле: %s'
                  % ', '.join(sorted(r['n'] for r in near
                                     if name.lower()[:5] in r['n'].lower())[:8]))
        elif not near:
            mods = sorted(m for m in header['modules'] if mod.lower()[:6] in m.lower())
            if mods:
                print('модуля нет. Похожие: %s' % ', '.join(mods[:8]))
        return 1

    if args.command == 'modules':
        rows = [(m, v) for m, v in header['modules'].items() if not q or ql in m.lower()]
        rows.sort(key=lambda x: -x[1].get('total', 0))
        for m, v in rows[:args.limit]:
            print('%-52s %-4s методов %4d' % (m, v.get('av', ''), v.get('total', 0)))
            if v.get('o'):
                print('    %s' % v['o'])
        print('-- всего %d' % len(rows))
        return 0

    if args.command == 'module':
        rows = [r for r in recs if r['m'].lower() == ql]
        if not rows:
            # Частичное совпадение с НЕСКОЛЬКИМИ модулями склеивать нельзя: состав окажется
            # сборным, а шапка - от одного из них, и клиент-серверные методы припишутся клиенту.
            near = sorted({r['m'] for r in recs if ql in r['m'].lower()})
            if len(near) > 1:
                print('уточните модуль, подходит %d: %s' % (len(near), ', '.join(near[:12])))
                return 1
            rows = [r for r in recs if ql in r['m'].lower()]
        if not rows:
            print('модуль не найден: %s' % q)
            return 1
        rows = [r for r in rows if keep(r, args)]
        if not rows:
            print('модуль есть, но под отбор ничего не подходит')
            return 1
        info = header['modules'].get(rows[0]['m'], {})
        print('%s - %s, контексты: %s' % (rows[0]['m'], info.get('kind', ''),
                                          av_text(info.get('av', ''))))
        if info.get('o'):
            print('   %s' % info['o'])
        for r in sorted(rows, key=lambda x: x['n'])[:args.limit]:
            print('   %s %s' % ('Ф' if r['k'] == 'Ф' else 'П', r['sig']))
        print('-- методов %d' % len(rows))
        return 0

    if args.command == 'subsystem':
        rows = [r for r in recs if (r.get('sub') or '').lower() == ql]
        if not rows:
            # "Обмен данными" подходит и к "Обмен данными в модели сервиса": склеив их, получим
            # чужие модули и счетчик от двух подсистем под именем одной.
            near = sorted({r['sub'] for r in recs if ql in (r.get('sub') or '').lower()})
            if len(near) > 1:
                print('уточните подсистему, подходит %d: %s' % (len(near), '; '.join(near)))
                return 1
            rows = [r for r in recs if ql in (r.get('sub') or '').lower()]
        if not rows:
            print('подсистема не найдена: %s' % q)
            return 1
        rows = [r for r in rows if keep(r, args)]
        if not rows:
            print('подсистема есть, но под отбор ничего не подходит')
            return 1
        mods, groups = {}, {}
        for r in rows:
            mods[r['m']] = mods.get(r['m'], 0) + 1
            if r.get('grp'):
                groups[r['grp']] = groups.get(r['grp'], 0) + 1
        print('подсистема: %s, методов %d' % (rows[0]['sub'], len(rows)))
        print('модули:')
        for m in sorted(mods, key=lambda x: -mods[x])[:args.limit]:
            print('   %-50s %4d' % (m, mods[m]))
            o = header['modules'].get(m, {}).get('o')
            if o:
                print('       %s' % o)
        if groups:
            print('механизмы:')
            for g in sorted(groups, key=lambda x: -groups[x])[:args.limit]:
                print('   %-50s %4d' % (g, groups[g]))
        return 0

    if args.command == 'overrides':
        rows = [r for r in recs if r['sec'] == 'П'
                and (not q or matches(r, [w for w in ql.split() if w]))]
        rows = [r for r in rows if keep(r, args)]
        for r in sorted(rows, key=lambda x: (x['m'], x['n']))[:args.limit]:
            print(line_of(r))
        print('-- всего %d' % len(rows))
        return 0

    if args.command == 'show':
        if '.' in q:
            mod, name = q.rsplit('.', 1)
            rows = [r for r in recs if r['m'].lower() == mod.lower() and r['n'].lower() == name.lower()]
        else:
            rows = [r for r in recs if r['n'].lower() == ql]
        rows = [r for r in rows if keep(r, args)]
        if not rows:
            print('не найдено: %s' % q)
            return 1
        print('\n\n'.join(card(r, header) for r in rows[:args.limit]))
        return 0

    words = [w for w in ql.split() if w]
    if not words:
        raise SystemExit('find ждет текст запроса')
    rows = [r for r in recs if matches(r, words) and keep(r, args)]
    # Сперва то, где запрос попал в само имя метода: имена в БСП говорящие, и точное попадание
    # почти всегда и есть искомое.
    rows.sort(key=lambda r: (0 if all(w in r['n'].lower() for w in words) else 1,
                             len(r['n']), r['m'], r['n']))
    for r in rows[:args.limit]:
        print(line_of(r))
    if len(rows) > args.limit:
        print('-- показано %d из %d, уточните запрос или поднимите --limit' % (args.limit, len(rows)))
    else:
        print('-- всего %d' % len(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
