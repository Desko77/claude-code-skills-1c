#!/usr/bin/env bash
# execute_query к toolkit КД 3.1.
# Использование: kd31_query.sh "ВЫБРАТЬ ... ИЗ Справочник.Конвертации" [out.json]
# Порт через переменную окружения KD31_PORT (по умолчанию 6011).
# Кириллица передаётся payload-файлом (jq, fallback python). Если указан out.json -
# ответ сохраняется туда (читать через Read: терминал портит кириллицу), иначе stdout.
set -euo pipefail
PORT="${KD31_PORT:-6011}"
Q="${1:?Укажите текст запроса первым аргументом}"
OUT="${2:-}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
if command -v jq >/dev/null 2>&1; then
  printf '%s' "$Q" | jq -Rs '{query: .}' > "$TMP"
else
  python -c "import json,sys; print(json.dumps({'query': sys.argv[1]}))" "$Q" > "$TMP"
fi
if [ -n "$OUT" ]; then
  curl -s --max-time 30 -X POST "http://localhost:${PORT}/api/execute_query" \
    -H "Content-Type: application/json; charset=utf-8" --data-binary @"$TMP" > "$OUT"
  echo "saved -> $OUT (читать через Read для корректной кириллицы)"
else
  curl -s --max-time 30 -X POST "http://localhost:${PORT}/api/execute_query" \
    -H "Content-Type: application/json; charset=utf-8" --data-binary @"$TMP"
  echo ""
fi
