# 1c-agent-kit — автономный доступ AI-агента к живой базе 1С

Переносимый набор скриптов: агент **читает и пишет** живую базу 1С — и **данные**, и **код** —
headless и самостоятельно. Все параметры — в одном файле `.dev.env`.

## Что внутри

| Файл | Назначение |
|------|-----------|
| `_env.ps1` | Загрузчик `.dev.env` + хелперы (подключается сам). |
| `start-mcp.ps1` | Поднять MCP Toolkit HTTP-сервер (headless, автостарт). |
| `run-bsl.ps1` | Выполнить любой BSL: чтение и **запись** (обход фильтра через Base64). |
| `code-channel.ps1` | Канал кода: `-Action backup\|dump\|apply`. |
| `.dev.env.template` | Шаблон параметров — скопируй в `.dev.env` и заполни. |

## Установка на новой машине

1. Установить платформу 1С нужной версии.
2. Скачать `MCP_Toolkit.epf` (x64/x86) из https://github.com/ROCTUP/1c-mcp-toolkit (папка `build/`).
3. Скопировать этот каталог. `cp .dev.env.template .dev.env` и заполнить пути/логин/порт.
4. `curl` — в Windows 10+ уже есть.

## Использование

```powershell
# 1. Поднять сервер данных
.\start-mcp.ps1

# 2. ЧТЕНИЕ данных
curl -s -X POST http://localhost:6003/api/execute_query -H "Content-Type: application/json" -d '{"query":"ВЫБРАТЬ ПЕРВЫЕ 5 Наименование ИЗ Справочник.Контрагенты"}'

# 3. ЗАПИСЬ данных / выполнение BSL
.\run-bsl.ps1 -Code 'Об = Справочники.Склады.СоздатьЭлемент(); Об.Наименование = "Тест"; Об.Записать(); Результат = Строка(Об.Ссылка);'
.\run-bsl.ps1 -File .\my_script.bsl

# 4. КОД: правка конфигурации
.\code-channel.ps1 -Action backup     # бэкап .cf (один раз)
.\code-channel.ps1 -Action dump        # свежие XML-исходники в SRC_DIR\cf
#   ... правишь .bsl/.mdo в SRC_DIR\cf ...
Stop-Process -Name 1cv8c -Force        # закрыть toolkit + ВСЕ прочие сеансы (монополия!)
.\code-channel.ps1 -Action apply       # LoadConfigFromFiles + UpdateDBCfg
.\start-mcp.ps1                        # поднять сервер, проверить
```

## Как это работает (метод)

- **Headless-запуск toolkit:** параметр `/C "startup;mode=embedded;port=N"` поднимает встроенный
  HTTP-сервер без кликов в форме.
- **Запись данных:** toolkit блокирует `Записать/Удалить/…`, и фильтр не отключается headless.
  `run-bsl.ps1` кодирует BSL в Base64 и исполняет через
  `Выполнить(ПолучитьСтрокуИзДвоичныхДанных(Base64Значение(...)))` — опасные слова спрятаны.
- **Канал кода:** `DumpConfigToFiles` → правка → `LoadConfigFromFiles` + `UpdateDBCfg`.

## Файловая vs серверная база

- Файловая: `INFOBASE_KIND=File`, `INFOBASE_PATH=...`.
- Серверная: `INFOBASE_KIND=Server`, `INFOBASE_SERVER=сервер\база`. Монополия для `apply` =
  выгнать сеансы через администрирование кластера (`rac`/консоль), а не просто закрыть окна.

## Важные оговорки

- **Base64-обход = полный доступ** (запись/удаление/привилегии). Только dev/test с разрешения владельца. НЕ на проде.
- **`apply` (UpdateDBCfg) требует монополии** — все сеансы закрыты.
- **Перед правкой кода — свежий `dump`**, иначе полная загрузка откатит правки, сделанные в БД мимо `SRC_DIR\cf`.
- toolkit-сервер иногда сам закрывается — перезапусти `start-mcp.ps1` (проверка: `curl http://localhost:6003/health`).
- Логи Designer — в CP1251.
