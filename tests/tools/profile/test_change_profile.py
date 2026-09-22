#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты профиля правки: tools/change_profile.py.

Каждый сценарий строит временный git-репозиторий и сверяет compute_profile со
спецификацией skills/1c-code-review/references/profile-map.md: класс объема,
архетипы (по путям и тексту diff), среду, обязательные проверки и понижение
"калька типового". CLI-тесты проверяют запись события scope и коды выхода.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "tools" / "change_profile.py"
EVIDENCE_CLI = REPO_ROOT / "tools" / "evidence.py"

TXN_MODULE = """Процедура ВыполнитьОбмен()
	НачатьТранзакцию();
	Данные = ПодготовитьДанные();
	ЗафиксироватьТранзакцию();
КонецПроцедуры
"""


def load_module():
    """Модуль tools/change_profile.py, импортированный по пути: вызов функций без CLI."""
    spec = importlib.util.spec_from_file_location("change_profile_py", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_changeset():
    """Модуль tools/changeset.py по пути: текущий diffHash для сверки события scope."""
    spec = importlib.util.spec_from_file_location("changeset_profile_test",
                                                  REPO_ROOT / "tools" / "changeset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    """Выполнить git в репозитории; отказ команды - ошибка теста с выводом git."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr.decode('utf-8', errors='replace')}"


def make_repo(tmp: Path) -> Path:
    """Создать временный git-репозиторий с настройками, не зависящими от машины."""
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "core.quotepath", "false")
    # Каталог следа исключен из git: запись события не должна менять diffHash.
    (repo / ".gitignore").write_text(".claude/.state/\n", encoding="utf-8")
    return repo


def write_file(repo: Path, rel: str, text: str) -> None:
    """Записать файл текстом как есть (UTF-8, LF - концы строк значимы для numstat)."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def commit_all(repo: Path, message: str = "изменение") -> None:
    """Закоммитить все изменения репозитория (хуки и подпись выключены)."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, "--no-gpg-sign", "--no-verify")


def run_cli(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    """Запустить CLI change_profile.py с --repo и дополнительными доводами."""
    return subprocess.run([sys.executable, "-X", "utf8", str(TOOL),
                           "--repo", str(repo), "--base", "HEAD", *extra],
                          capture_output=True)


class ComputeProfileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.profile_mod = load_module()

    def compute(self, repo: Path, vendor_copy=None):
        """Профиль репозитория относительно HEAD (модульный вызов, без CLI)."""
        return self.profile_mod.compute_profile(repo, "HEAD", vendor_copy)

    def test_transaction_edit_c1(self):
        """Правка внутри транзакции: архетипы транзакция и любой BSL, класс C1."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Обмен/Module.bsl", TXN_MODULE)
        commit_all(repo)
        edited = TXN_MODULE.replace("\tДанные = ПодготовитьДанные();",
                                    "\tДанные = ПодготовитьДанные();\n\tЗаписано = Истина;")
        write_file(repo, "src/CommonModules/Обмен/Module.bsl", edited)
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C1")
        self.assertIn("транзакция", profile["archetypes"])
        self.assertIn("любой BSL", profile["archetypes"])
        self.assertEqual(profile["env"], ["configurator"])
        self.assertIn("bsl_validate@configurator", profile["required"])
        self.assertIn("syntaxcheck@configurator", profile["required"])
        self.assertIn("catalog_read:TXN@any", profile["required"])
        self.assertNotIn("cross_review@any", profile["required"])

    def test_new_query(self):
        """Новый запрос в модуле: архетип запрос, проверка query_validate по среде."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Загрузка/Module.bsl",
                   "Процедура ЗагрузитьДанные()\n\tДанные = ПрочитатьФайл();\nКонецПроцедуры\n")
        commit_all(repo)
        write_file(repo, "src/CommonModules/Загрузка/Module.bsl",
                   "Процедура ЗагрузитьДанные()\n"
                   "\tДанные = ПрочитатьФайл();\n"
                   "\tЗапрос = Новый Запрос;\n"
                   "\tЗапрос.Текст = \"ВЫБРАТЬ Спр.Ссылка ИЗ Справочник.Контрагенты КАК Спр\";\n"
                   "КонецПроцедуры\n")
        profile = self.compute(repo)
        self.assertIn("запрос", profile["archetypes"])
        self.assertIn("любой BSL", profile["archetypes"])
        self.assertIn("query_validate@configurator", profile["required"])
        self.assertNotIn("validate_query@edt", profile["required"])

    def test_form_module_edit(self):
        """Правка модуля формы: архетип модуль формы, чтение групп CLIENT и FORM."""
        repo = make_repo(self.tmp)
        path = "src/Catalogs/Товары/Forms/ФормаСписка/Module.bsl"
        write_file(repo, path, "&НаКлиенте\nПроцедура ПриОткрытии()\nКонецПроцедуры\n")
        commit_all(repo)
        write_file(repo, path,
                   "&НаКлиенте\nПроцедура ПриОткрытии()\n\tУстановитьЗаголовок();\nКонецПроцедуры\n")
        profile = self.compute(repo)
        self.assertIn("модуль формы", profile["archetypes"])
        self.assertIn("любой BSL", profile["archetypes"])
        self.assertIn("catalog_read:CLIENT@any", profile["required"])
        self.assertIn("catalog_read:FORM@any", profile["required"])

    def test_new_common_module_c3(self):
        """Добавленный общий модуль с .mdo: новый объект метаданных поднимает класс до C3."""
        repo = make_repo(self.tmp)
        write_file(repo, "base.txt", "база\n")
        commit_all(repo)
        write_file(repo, "src/CommonModules/НовыйМодуль/Module.bsl",
                   "Процедура Сделать() Экспорт\nКонецПроцедуры\n")
        write_file(repo, "src/CommonModules/НовыйМодуль/НовыйМодуль.mdo",
                   "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<mdo:CommonModule/>\n")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C3")
        for archetype in ("новый общий модуль", "изменение метаданных", "любой BSL"):
            self.assertIn(archetype, profile["archetypes"])
        self.assertTrue(profile["driver"].startswith("архетип: новый объект метаданных"))
        self.assertIn("meta_validate@configurator", profile["required"])
        self.assertIn("cross_review@any", profile["required"])
        self.assertIn("adversarial_audit@any", profile["required"])
        # Неотслеживаемый модуль без numstat считается целиком: 2 строки.
        self.assertEqual(profile["volume"]["bslLines"], 2)

    def test_docs_only_c0(self):
        """Правка только документации: C0, архетипов нет, обязательных проверок нет."""
        repo = make_repo(self.tmp)
        write_file(repo, "README.md", "текст\n")
        commit_all(repo)
        write_file(repo, "README.md", "текст изменен\n")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C0")
        self.assertEqual(profile["archetypes"], [])
        self.assertEqual(profile["env"], [])
        self.assertEqual(profile["required"], [])
        self.assertEqual(profile["driver"], "нет файлов кода и метаданных")

    def test_metadata_edit_c2(self):
        """Правка существующего .mdo без новых объектов: C2 по архетипу метаданных."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/Catalogs/Товары/Товары.mdo",
                   "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<mdo:Catalog/>\n")
        commit_all(repo)
        write_file(repo, "src/Catalogs/Товары/Товары.mdo",
                   "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<mdo:Catalog><synonym>Товары</synonym></mdo:Catalog>\n")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C2")
        self.assertEqual(profile["driver"], "архетип: изменение метаданных")
        self.assertIn("изменение метаданных", profile["archetypes"])
        self.assertNotIn("любой BSL", profile["archetypes"])
        self.assertIn("meta_validate@configurator", profile["required"])
        self.assertIn("cross_review@any", profile["required"])

    def test_c2_by_lines(self):
        """35 добавленных строк BSL: C2, обязательное кросс-ревью, без adversarial_audit."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Расчет/Module.bsl", "Процедура Рассчитать()\nКонецПроцедуры\n")
        commit_all(repo)
        body = "".join(f"\tСтрока{num} = {num};\n" for num in range(1, 36))
        write_file(repo, "src/CommonModules/Расчет/Module.bsl",
                   "Процедура Рассчитать()\n" + body + "КонецПроцедуры\n")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C2")
        self.assertTrue(profile["driver"].startswith("объем: 35 строк BSL"))
        self.assertIn("cross_review@any", profile["required"])
        self.assertNotIn("adversarial_audit@any", profile["required"])

    def test_c3_by_lines(self):
        """301 добавленная строка BSL: C3 с adversarial_audit."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Расчет/Module.bsl", "Процедура Рассчитать()\nКонецПроцедуры\n")
        commit_all(repo)
        body = "".join(f"\tСтрока{num} = {num};\n" for num in range(1, 302))
        write_file(repo, "src/CommonModules/Расчет/Module.bsl",
                   "Процедура Рассчитать()\n" + body + "КонецПроцедуры\n")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["class"], "C3")
        self.assertIn("adversarial_audit@any", profile["required"])

    def test_vendor_copy_downgrade(self):
        """Довод --vendor-copy понижает C2 до C1; обоснование попадает в профиль."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Расчет/Module.bsl", "Процедура Рассчитать()\nКонецПроцедуры\n")
        commit_all(repo)
        body = "".join(f"\tСтрока{num} = {num};\n" for num in range(1, 36))
        write_file(repo, "src/CommonModules/Расчет/Module.bsl",
                   "Процедура Рассчитать()\n" + body + "КонецПроцедуры\n")
        before = self.compute(repo)
        self.assertEqual(before["volume"]["class"], "C2")
        after = self.compute(repo, vendor_copy="перенос модуля БСП 3.1.11, дословная копия")
        self.assertEqual(after["volume"]["class"], "C1")
        self.assertEqual(after["driver"], "явное указание: калька типового")
        self.assertEqual(after["vendorCopy"], "перенос модуля БСП 3.1.11, дословная копия")
        self.assertNotIn("cross_review@any", after["required"])

    def test_env_edt_by_project(self):
        """Среда edt: у файла есть предок с .project, содержащим маркер проекта 1C:EDT."""
        repo = make_repo(self.tmp)
        write_file(repo, ".project",
                   "<?xml version=\"1.0\"?>\n<projectDescription><natures>"
                   "<nature>com._1c.g5.v8.dt.core.v8.nature</nature>"
                   "</natures></projectDescription>\n")
        write_file(repo, "src/CommonModules/Обмен/Module.bsl", TXN_MODULE)
        commit_all(repo)
        write_file(repo, "src/CommonModules/Обмен/Module.bsl",
                   TXN_MODULE.replace("\tДанные = ПодготовитьДанные();", "\tДанные = 1;"))
        profile = self.compute(repo)
        self.assertEqual(profile["env"], ["edt"])
        self.assertIn("code_review@edt", profile["required"])
        self.assertIn("ask_1c_ai@edt", profile["required"])
        self.assertNotIn("syntaxcheck@configurator", profile["required"])

    def test_env_mixed(self):
        """Файл в дереве EDT и файл вне его: обе среды, проверки обеих складываются."""
        repo = make_repo(self.tmp)
        write_file(repo, "vendor/.project",
                   "<projectDescription><natures>"
                   "<nature>com._1c.g5.v8.dt.core.v8.nature</nature>"
                   "</natures></projectDescription>\n")
        write_file(repo, "vendor/src/CommonModules/Обмен/Module.bsl", TXN_MODULE)
        write_file(repo, "dump/Catalogs/Контрагенты/Ext/ObjectModule.bsl",
                   "Процедура ОбработкаЗаполнения()\nКонецПроцедуры\n")
        commit_all(repo)
        write_file(repo, "vendor/src/CommonModules/Обмен/Module.bsl",
                   TXN_MODULE.replace("\tДанные = ПодготовитьДанные();", "\tДанные = 1;"))
        write_file(repo, "dump/Catalogs/Контрагенты/Ext/ObjectModule.bsl",
                   "Процедура ОбработкаЗаполнения()\n\tНаименование = 1;\nКонецПроцедуры\n")
        profile = self.compute(repo)
        self.assertEqual(profile["env"], ["configurator", "edt"])
        self.assertIn("code_review@edt", profile["required"])
        self.assertIn("syntaxcheck@configurator", profile["required"])

    def test_rights_archetype(self):
        """Правка ролей: архетипы права и изменение метаданных, проверка role_validate."""
        repo = make_repo(self.tmp)
        write_file(repo, "Roles/Менеджер/Rights.rights", "<rights/>\n")
        commit_all(repo)
        write_file(repo, "Roles/Менеджер/Rights.rights",
                   "<rights><objectRights/></rights>\n")
        profile = self.compute(repo)
        self.assertIn("права", profile["archetypes"])
        self.assertIn("изменение метаданных", profile["archetypes"])
        self.assertIn("role_validate@configurator", profile["required"])
        self.assertEqual(profile["volume"]["class"], "C2")

    def test_rename_unrelated_names_zero_lines(self):
        """Переименование без правок между несвязанными именами: 0 строк, класс C1.

        numstat -z дает переименование тремя полями (числа, прежний путь, новый):
        отображаемый синтаксис со стрелкой не разбирается, запись читается по новому
        пути с нулевым объемом.
        """
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Обмен/Module.bsl", TXN_MODULE)
        commit_all(repo)
        (repo / "vendor").mkdir()
        git(repo, "mv", "src/CommonModules/Обмен/Module.bsl",
            "vendor/ПереименованныйМодуль.bsl")
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["bslLines"], 0)
        self.assertEqual(profile["volume"]["bslFiles"], 1)
        self.assertEqual(profile["volume"]["class"], "C1")
        self.assertIn("любой BSL", profile["archetypes"])

    def test_braces_in_filename(self):
        """Имя файла со скобками: разбор numstat не трогает скобки, объем по numstat."""
        repo = make_repo(self.tmp)
        braces = "src/{Каталог}/Module.bsl"
        reverse = "src/модуль}имя{1.bsl"
        write_file(repo, braces, "Процедура Раз()\nКонецПроцедуры\n")
        write_file(repo, reverse, "Процедура Еще()\nКонецПроцедуры\n")
        commit_all(repo)
        write_file(repo, braces, "Процедура Раз()\n\tНоваяСтрока = 1;\nКонецПроцедуры\n")
        write_file(repo, reverse, "Процедура Еще()\n\tДругаяСтрока = 2;\nКонецПроцедуры\n")
        profile = self.compute(repo)
        # По одному изменению в каждом файле: добавленная и удаленная строки.
        self.assertEqual(profile["volume"]["bslLines"], 2)
        self.assertEqual(profile["volume"]["bslFiles"], 2)

    def test_rm_cached_working_file(self):
        """git rm --cached с измененным рабочим файлом: объем и маркеры по файлу.

        Канонический статус - modified (арбитраж), но numstat дает удаление, а текст
        diff - +++ /dev/null: объем считается по рабочему файлу целиком и маркер
        Новый Запрос берется из рабочего файла.
        """
        repo = make_repo(self.tmp)
        path = "src/CommonModules/Загрузка/Module.bsl"
        write_file(repo, path,
                   "Процедура ЗагрузитьДанные()\n\tДанные = ПрочитатьФайл();\nКонецПроцедуры\n")
        commit_all(repo)
        write_file(repo, path,
                   "Процедура ЗагрузитьДанные()\n"
                   "\tДанные = ПрочитатьФайл();\n"
                   "\tЗапрос = Новый Запрос;\n"
                   "КонецПроцедуры\n")
        git(repo, "rm", "-q", "--cached", "--", path)
        profile = self.compute(repo)
        self.assertEqual(profile["volume"]["bslLines"], 4)
        self.assertIn("запрос", profile["archetypes"])
        self.assertIn("любой BSL", profile["archetypes"])
        self.assertEqual(profile["volume"]["class"], "C1")


class ChangeProfileCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def scenario_repo(self) -> Path:
        """Репозиторий с правкой внутри транзакции (C1, конфигуратор)."""
        repo = make_repo(self.tmp)
        write_file(repo, "src/CommonModules/Обмен/Module.bsl", TXN_MODULE)
        commit_all(repo)
        write_file(repo, "src/CommonModules/Обмен/Module.bsl",
                   TXN_MODULE.replace("\tДанные = ПодготовитьДанные();", "\tДанные = 2;"))
        return repo

    def test_json_output(self):
        """--json печатает профиль целиком; ключи соответствуют спецификации."""
        repo = self.scenario_repo()
        proc = run_cli(repo, "--json", "--no-write")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        data = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(data["volume"]["class"], "C1")
        for key in ("base", "diffHash", "volume", "files", "archetypes", "env",
                    "driver", "required", "analyzerConfig", "vendorCopy"):
            self.assertIn(key, data)
        self.assertEqual(data["analyzerConfig"], "project-config")

    def test_table_output(self):
        """Без --json печатается таблица с классом и списком проверок."""
        repo = self.scenario_repo()
        proc = run_cli(repo, "--no-write")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        text = proc.stdout.decode("utf-8")
        self.assertIn("класс: C1", text)
        self.assertIn("обязательные проверки:", text)
        self.assertIn("bsl_validate@configurator", text)

    def test_scope_write_and_stable_hash(self):
        """--session пишет событие scope; запись не меняет diffHash прогона."""
        repo = self.scenario_repo()
        proc = run_cli(repo, "--json", "--session", "sess-1")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        events_dir = repo / ".claude" / ".state" / "quality" / "sess-1" / "events"
        files = sorted(events_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        event = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(event["type"], "scope")
        self.assertEqual(event["session"], "sess-1")
        self.assertEqual(event["producer"], "profile")
        current = load_changeset().compute_changeset(repo, "HEAD")["diffHash"]
        self.assertEqual(event["diffHash"], current)
        self.assertNotIn("code_review@edt", event["required"])  # среда configurator
        self.assertIn("syntaxcheck@configurator", event["required"])
        check = subprocess.run([sys.executable, "-X", "utf8", str(EVIDENCE_CLI),
                                "check", "--strict", "--repo", str(repo),
                                "--session", "sess-1"], capture_output=True)
        # Только записанный scope без прогонов проверок: scope виден (не "нет scope"),
        # но обязательные проверки без событий - заблокировано, код 3.
        self.assertEqual(check.returncode, 3, check.stdout.decode("utf-8", errors="replace"))
        self.assertNotIn("нет scope", check.stdout.decode("utf-8"))

    def test_no_write(self):
        """--no-write не создает каталог следа при заданной сессии."""
        repo = self.scenario_repo()
        proc = run_cli(repo, "--json", "--session", "sess-1", "--no-write")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        self.assertFalse((repo / ".claude").exists())

    def test_bad_base_exit_2(self):
        """Неразрешаемый base - код 2, диагностика в stderr без traceback."""
        repo = self.scenario_repo()
        proc = subprocess.run([sys.executable, "-X", "utf8", str(TOOL),
                               "--repo", str(repo), "--base", "no-such-commit",
                               "--json", "--no-write"], capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ошибка:", proc.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
