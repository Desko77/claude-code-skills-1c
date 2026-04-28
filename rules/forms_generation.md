---
paths:
  - "**/Forms/**/*.xml"
  - "**/Forms/**"
---

# Генерация и модификация форм 1С

MCP-сервер: **1c-forms-mcp** (http://localhost:8011/mcp).

## Форматы

- `"logform"` — формат Конфигуратора (`<Form xmlns="...xcf/logform">`). По умолчанию.
- `"edt"` — формат EDT (`<form:Form xmlns:form="...dt/form">`). Для EDT-проектов.
- `"managed"` — упрощённый формат (`<ManagedForm>`).

Для EDT-проектов использовать `format="edt"`. Файл формы в EDT — `Form.form` (не Form.xml).

## Генерация новой формы

1. **get_form_prompt**(format?) — загрузить базу знаний (обязательно перед первой генерацией в сессии). `format="edt"` для EDT-проектов
2. **search_form_examples** — найти похожий пример формы как образец
3. **generate_form_template** (типовая форма) или **generate_form** (произвольная спецификация)
4. **validate_form** — проверить результат

### С EDT (расширенный workflow)

1. **get_form_prompt**(format="edt") — загрузить EDT-базу знаний
2. **edt_status**(edt_url?) — проверить доступность EDT
3. **get_object_metadata**(object_type, object_name, edt_url?) — получить реквизиты объекта из проекта
4. **generate_form_from_metadata**(object_type, object_name, ..., edt_url?) — автогенерация (самый быстрый способ)
5. **validate_form_edt**(xml_content, form_fqn?, edt_url?) — валидация с проверками EDT

Все EDT-тулзы принимают опциональный `edt_url` (напр. `"http://localhost:9999/sse"`). Если не указан — берётся из настроек сервера.

## Модификация существующей формы

- **get_form_info** — быстрый обзор структуры формы
- **get_form_schema** — справочник допустимых тегов и свойств элементов
- **search_form_examples** — найти примеры аналогичных элементов
- **get_form_prompt** — полная база знаний (если вышеуказанных недостаточно)

## Конвертация

- **convert_form** — конвертация между форматами (`target_format`: `"logform"`, `"edt"`, `"managed"`)

## Полный список тулзов сервера (18)

| Тулза | Категория | Назначение |
|-------|-----------|-----------|
| `validate_form` | Валидация | Проверка Form.xml |
| `get_form_info` | Анализ | Быстрый обзор структуры формы |
| `get_form_schema` | Схема | Допустимые теги и свойства |
| `get_form_prompt` | Схема | Полная база знаний по формам (format: logform/edt) |
| `get_xcore_model_info` | Схема | Модель XCore |
| `generate_form` | Генерация | Генерация по произвольной спецификации |
| `generate_form_template` | Генерация | Генерация типовой формы |
| `list_form_templates` | Генерация | Список доступных шаблонов |
| `convert_form` | Конвертация | Между форматами logform/edt/managed |
| `search_form_examples` | Поиск | Поиск примеров форм |
| `index_forms` | Поиск | Индексация форм проекта |
| `get_form_example` | Поиск | Получить конкретный пример |
| `edt_status` | EDT | Проверка доступности EDT (edt_url?) |
| `get_object_metadata` | EDT | Реквизиты объекта из проекта (edt_url?) |
| `validate_form_edt` | EDT | Валидация с проверками EDT (edt_url?) |
| `form_screenshot` | EDT | Скриншот формы (edt_url?) |
| `generate_form_from_metadata` | EDT | Автогенерация из метаданных (edt_url?) |
| `get_server_info` | Info | Информация о сервере |
