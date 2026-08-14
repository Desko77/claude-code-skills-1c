# -*- coding: utf-8 -*-
"""Пример: несколько однотипных документов из данных, в оформлении образца.

Схема, которая себя оправдала на серии документов: данные отдельно, сборка отдельно.
Тогда правка формулировки делается в одном месте и все документы остаются одинаковыми.

Запуск:  python build-example.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from docx_builder import SampleDoc

PROFILE = "profile.json"
OUT_DIR = "."

# ---------------------------------------------------------------- данные

COMMON_INTRO = [
    "Документ описывает порядок проверки и состав контролируемых данных.",
    "Документ предназначен для специалистов, выполняющих проверку.",
]

DOCS = [
    {
        "file": "Отчет по направлению А.docx",
        "title": "Проверка по направлению А",
        "rows": [["Показатель 1", "Значение 1", "Примечание"],
                 ["Показатель 2", "Значение 2", ""]],
        "steps": [("Открытие формы", "Открыть форму обработки.", "Форма открыта."),
                  ("Заполнение", "Заполнить период и организацию.", "Данные введены.")],
    },
    {
        "file": "Отчет по направлению Б.docx",
        "title": "Проверка по направлению Б",
        "rows": [["Показатель 3", "Значение 3", ""]],
        "steps": [("Открытие формы", "Открыть форму обработки.", "Форма открыта.")],
    },
]

# ---------------------------------------------------------------- сборка


def build(spec):
    d = SampleDoc(PROFILE)
    d.footer_for_all("Отчет «%s»" % spec["title"])

    # титул: линейка, блок подписей, название
    d.rule_table(cols=3)
    d.plain_table([["СОГЛАСОВАНО", "УТВЕРЖДАЮ"],
                   ["Должность, организация", "Должность, организация"],
                   ["______________ Фамилия И. О.", "______________ Фамилия И. О."]],
                  bold_first_row=True)
    d.empty(3)
    d.title_block([("Отчет", 22, True), (spec["title"], 22, False)])

    # служебные разделы без номеров
    d.section("portrait")
    d.heading("Версии документа", 1, numbered=False)
    d.table(["Номер версии", "Содержание изменения", "Ответственный", "Дата"],
            [["1", "Первая версия документа", "", ""]],
            widths=[2.7, 7.0, 3.0, 3.8], style=None, head_size=9,
            body_style_key="table_body_alt", borders=8, repeat=False)
    d.heading("Оглавление", 1, numbered=False)
    d.toc()

    # нумерованные разделы
    d.heading("Введение", 1)
    for line in COMMON_INTRO:
        d.body(line)

    d.heading("Контролируемые данные", 1)
    d.table(["№ п/п", "Показатель", "Значение", "Примечания"],
            [[str(i + 1)] + list(r) for i, r in enumerate(spec["rows"])])

    # альбомная секция под широкую таблицу
    d.section("landscape")
    d.heading("Порядок проверки", 1)
    d.callout("ПОСЛЕДОВАТЕЛЬНОСТЬ ДЕЙСТВИЙ")
    d.table(["№ шага", "Название шага", "Описание действия", "Ожидаемый результат"],
            [[str(i + 1)] + list(s) for i, s in enumerate(spec["steps"])])

    out = os.path.join(OUT_DIR, spec["file"])
    d.save(out, author="Имя Ф.", title=spec["title"])
    for w in d.warnings:
        print("  ВНИМАНИЕ: %s" % w)
    return out


if __name__ == "__main__":
    for spec in DOCS:
        print("OK  %s" % build(spec))
    print("Дальше: verify_result.py по каждому файлу, с --update-fields и --png.")
