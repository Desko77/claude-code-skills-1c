---
name: 1c-platform-docs
description: "1C platform API documentation tools via bsl-platform-help MCP server — search, info, members, constructors. Supports keyword, semantic (embeddings), and hybrid search. Use when checking built-in functions, types, methods, or properties of the 1C platform."
---

# 1C Platform Documentation — bsl-platform-help

MCP-сервер **bsl-platform-help** предоставляет доступ к документации API платформы 1С:Предприятие.
Поддерживает keyword, semantic (эмбеддинги) и hybrid (RRF merge + reranker) поиск.

## When to Use

- Проверка существования встроенных процедур/функций/методов/свойств
- Поиск методов и типов по описанию на естественном языке
- Получение сигнатуры и параметров метода
- Просмотр всех членов типа (методы + свойства)
- Получение конструкторов типа
- Проверка версии платформы

## Tools

### `search` — Поиск по документации (основной)
Замена `docsearch`. Поддерживает 3 режима поиска.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `query` | да | Запрос (рус/англ, CamelCase, natural language) |
| `mode` | нет | `keyword` / `semantic` / `hybrid` (default: hybrid) |
| `type` | нет | Фильтр: `method`, `property`, `type` |
| `limit` | нет | Максимум результатов (1-50, default 10) |

Примеры:
- `search("ТекущаяДата")` — точный keyword
- `search("как записать файл на диск", mode="semantic")` — семантический
- `search("HTTP запрос POST", mode="hybrid")` — hybrid

### `info` — Детальная информация
Получить полное описание элемента API: сигнатура, параметры, возвращаемое значение, описание.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `name` | да | Точное имя (рус/англ): `НайтиПоСсылке`, `FindByRef` |
| `type` | да | `method`, `property`, `type` |

### `get_member` — Метод/свойство типа
Информация о конкретном члене конкретного типа.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `type_name` | да | Имя типа: `ТаблицаЗначений`, `ValueTable` |
| `member_name` | да | Имя члена: `Добавить`, `Add` |

### `get_members` — Все члены типа
Полный список методов и свойств типа.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `type_name` | да | Имя типа |

### `get_constructors` — Конструкторы типа
Сигнатуры конструкторов для создания экземпляров типа.

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `type_name` | да | Имя типа |

### `get_platform_info` — Версия платформы
Текущая версия, путь к HBK, список доступных версий. Без параметров.

## Typical Workflows

### Проверка встроенной функции
1. `search("ТекущаяДата")` — найти
2. `info(name="ТекущаяДата", type="method")` — получить детали

### Изучение типа
1. `get_members("ТаблицаЗначений")` — все методы и свойства
2. `get_member("ТаблицаЗначений", "Добавить")` — детали конкретного метода
3. `get_constructors("ТаблицаЗначений")` — как создать

### Поиск по описанию
1. `search("записать данные в XML файл", mode="semantic")` — семантический поиск
