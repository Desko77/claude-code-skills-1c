Запусти Яндекс Браузер с удалённой отладкой (Chrome DevTools Protocol) для отладки веб-приложений.

Выполни следующие шаги:

1. Закрой все процессы Яндекс Браузера:
   ```
   taskkill //F //IM browser.exe
   ```

2. Подожди 3 секунды, затем запусти браузер с отладкой (в фоне):
   ```
   "%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe" --remote-debugging-port=9222
   ```

3. Подожди 10 секунд и проверь доступность CDP:
   ```
   curl -s http://localhost:9222/json/version
   ```

4. Если CDP доступен — выведи статус "CDP работает" и WebSocket URL.
   Если не доступен — повтори проверку ещё 2 раза с интервалом 5 секунд.

5. Напомни пользователю добавить Chrome DevTools MCP через команду `/mcp` если ещё не добавлен:
   - Тип: stdio
   - Команда: `npx chrome-devtools-mcp@latest --port=9222`
