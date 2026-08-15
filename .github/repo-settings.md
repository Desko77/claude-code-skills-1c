# Настройки репозитория

Темы и описание живут в настройках GitHub, а не в файлах: их нет в `git clone`, они не переносятся
при форке и пропадают, если репозиторий пересоздать. Здесь они записаны, чтобы восстановить их одной
командой, а не вспоминать по памяти.

Файл ничего не применяет сам. Правишь настройки на GitHub - поправь и здесь.

## Описание

```
112 скилов и 35 правил для Claude Code: агент собирает исходники 1С (метаданные, формы, расширения, роли, СКД, обработки) из компактного JSON и разбирает обратно. Базовые операции - без Конфигуратора.
```

Описание на русском намеренно: аудитория русскоязычная, README тоже. GitHub индексирует описание и
README, поиск с квалификаторами `in:description` и `in:readme` находит репозиторий по русским
запросам. Темы закрывают англоязычный канал и тематические страницы.

## Темы

```
1c 1c-development 1c-edt 1c-enterprise ai-agent anthropic bsl claude claude-code claude-skills code-generation developer-tools llm mcp onec
```

Кириллица в темах невозможна: GitHub отвечает `HTTP 422 - must start with a lowercase letter or
number, consist of 50 characters or less, and can include hyphens`.

## Восстановить

```bash
gh repo edit Desko77/claude-code-skills-1c \
  --description "112 скилов и 35 правил для Claude Code: агент собирает исходники 1С (метаданные, формы, расширения, роли, СКД, обработки) из компактного JSON и разбирает обратно. Базовые операции - без Конфигуратора."

gh repo edit Desko77/claude-code-skills-1c \
  --add-topic 1c --add-topic 1c-development --add-topic 1c-edt --add-topic 1c-enterprise \
  --add-topic ai-agent --add-topic anthropic --add-topic bsl --add-topic claude \
  --add-topic claude-code --add-topic claude-skills --add-topic code-generation \
  --add-topic developer-tools --add-topic llm --add-topic mcp --add-topic onec
```

Проверить, что применилось:

```bash
gh repo view Desko77/claude-code-skills-1c --json description,repositoryTopics
```

## Прочее, что задано на стороне GitHub

| Настройка | Значение |
|-----------|----------|
| Основная ветка | `main` |
| Лицензия | MIT (файл `LICENSE` в репозитории) |
| Сайт (homepage) | не задан |
| Релизы | теги `vX.Y.Z`, заметки собираются `tools/release_notes.py` из `CHANGELOG.md` |
