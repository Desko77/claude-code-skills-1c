---
name: v8unpack-cf
description: "Распаковка и сборка бинарных файлов 1С (CF/CFE/EPF) через Python-утилиту v8unpack. Используй когда нужно распаковать конфигурацию, расширение или обработку в исходники, или собрать обратно."
argument-hint: "<-E|-B> <source> <destination> [--temp path] [--descent ver] [--auto_include]"
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

# v8unpack-cf — распаковка и сборка бинарных файлов 1С

Утилита `saby v8unpack` (Python) распаковывает CF/CFE/EPF файлы 1С в человекочитаемые исходники (JSON + BSL) с деревом метаданных — **без платформы 1С**.

Установка: `pip install v8unpack` (или dev-install из репозитория).

## Команды

### Распаковка (-E)

```bash
python -m v8unpack -E "<файл.cf>" "<папка_исходников>" --temp "<папка_temp>"
```

| Параметр | Описание |
|----------|----------|
| `<файл.cf>` | Путь к CF, CFE или EPF файлу |
| `<папка_исходников>` | Куда распаковать (создаётся автоматически) |
| `--temp <путь>` | Папка для промежуточных данных (не удаляется — для отладки) |
| `--processes N` | Количество потоков (по умолчанию cpu_count - 2) |
| `--descent XYYZZZ` | Режим версионирования расширений (суффикс версии конфигурации) |
| `--auto_include` | Динамическое оглавление из папки, а не из заголовка |
| `--prefix STR` | Префикс имён метаданных 1-го уровня |

### Сборка (-B)

```bash
python -m v8unpack -B "<папка_исходников>" "<файл.cf>"
```

| Параметр | Описание |
|----------|----------|
| `<папка_исходников>` | Папка с распакованными исходниками |
| `<файл.cf>` | Путь к выходному CF/CFE/EPF файлу |
| `--index <path>` | JSON-файл оглавления (маппинг файлов по папкам) |
| `--version XYYZZ` | Версия режима совместимости (для расширений), напр. `80306` = 8.3.6 |
| `--descent XYYZZZ` | Суффикс версии конфигурации |

### Индексация (-I)

```bash
python -m v8unpack -I "<папка_исходников>" --index index.json --core core
```

Генерирует/обновляет `index.json` — файл оглавления для раскладки исходников по подпапкам.

### Пакетные операции (-EA, -BA, -IA)

```bash
python -m v8unpack -EA products.json              # распаковать все продукты
python -m v8unpack -BA products.json              # собрать все продукты
python -m v8unpack -BA products.json --index KEY  # собрать конкретный продукт
```

Файл `products.json` описывает несколько продуктов с индивидуальными параметрами сборки.

## Python API

```python
import v8unpack

v8unpack.extract('d:/sample.cf', 'd:/src')
v8unpack.extract('d:/sample.cf', 'd:/src', temp_dir='d:/temp',
                 options={'descent': 4100200, 'auto_include': True})

v8unpack.build('d:/src', 'd:/repacked.cf')
v8unpack.build('d:/src', 'd:/repacked.cf', index='index.json',
               options={'descent': 4100200, 'version': '80306'})
```

## Примеры использования

### Распаковать конфигурацию

```bash
python -m v8unpack -E "<project>/1Cv8.cf" "<project>/src" --temp "<project>/temp"
```

### Собрать обратно

```bash
python -m v8unpack -B "<project>/src" "<project>/1Cv8_new.cf"
```

### Распаковать внешнюю обработку

```bash
python -m v8unpack -E "МояОбработка.epf" "src_epf"
```

### Распаковать расширение

```bash
python -m v8unpack -E "МоёРасширение.cfe" "src_cfe" --descent 3000112
```

### Собрать расширение

```bash
python -m v8unpack -B "src_cfe" "bin/ext.cfe" --index cmd/index.json --descent 3000112 --version 80316
```

## Совместимость версий

Версия утилиты записывается в `Configuration.json` (`"v8unpack": "1.2.6"`). При сборке проверяется совпадение major.minor. Если версии не совпадают:
1. Собрать старой версией
2. Обновить утилиту
3. Распаковать новой версией
4. Закоммитить

## Промежуточные стадии (--temp)

| Стадия | Описание |
|--------|----------|
| `decode_stage_0/` | Извлечение из контейнера 1С |
| `decode_stage_1/` | Декомпрессия (zlib), скобкофайлы |
| `decode_stage_3/` | Разбор метаданных → дерево |
| Папка назначения | Организация кода (include, элементы форм) |

## Ограничения

- Свойства объектов и разметка форм хранятся в `header` / `raw` как сырые массивы
- Файлы > 1 МБ (макеты, HTML) хранятся как `.bin` без декодирования
- Зашифрованные модули сохраняются в бинарном виде
- При `--auto_include` вложенные объекты сортируются по алфавиту
