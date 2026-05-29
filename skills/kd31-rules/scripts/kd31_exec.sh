#!/usr/bin/env bash
# execute_code к toolkit КД 3.1 из BSL-файла.
# Использование: kd31_exec.sh script.bsl [out.json]
# Серверный контекст: НЕ использовать Возврат, результат через переменную Результат.
# Порт через переменную окружения KD31_PORT (по умолчанию 6011).
# Если указан out.json - ответ сохраняется туда (читать через Read для корректной
# кириллицы), иначе печатается в stdout.
set -euo pipefail
PORT="${KD31_PORT:-6011}"
BSL="${1:?Укажите путь к BSL-файлу первым аргументом}"
OUT="${2:-}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
if command -v jq >/dev/null 2>&1; then
  jq -Rs '{code: .}' "$BSL" > "$TMP"
else
  python -c "import json,io,sys; print(json.dumps({'code': io.open(sys.argv[1], encoding='utf-8').read()}))" "$BSL" > "$TMP"
fi
if [ -n "$OUT" ]; then
  curl -s --max-time 60 -X POST "http://localhost:${PORT}/api/execute_code" \
    -H "Content-Type: application/json; charset=utf-8" --data-binary @"$TMP" > "$OUT"
  echo "saved -> $OUT (читать через Read для корректной кириллицы)"
else
  curl -s --max-time 60 -X POST "http://localhost:${PORT}/api/execute_code" \
    -H "Content-Type: application/json; charset=utf-8" --data-binary @"$TMP"
  echo ""
fi
