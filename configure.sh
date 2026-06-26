#!/bin/bash
# Интерактивный ввод ключей. Запуск: bash configure.sh
cd "$(dirname "$0")"
echo "Введи ключи (после каждого — Enter). Пустые можно пропустить:"
read -p "  api_id (число): " A
read -p "  api_hash: " B
read -p "  Anthropic API key: " C
read -p "  Адрес скрипта таблицы (SHEET_WEBHOOK_URL, можно позже): " D
read -p "  Токен таблицы (SHEET_TOKEN, можно позже): " E
cat > .env <<EOF
TG_API_ID=$A
TG_API_HASH=$B
TG_SESSION=
SHEET_WEBHOOK_URL=$D
SHEET_TOKEN=$E
ANTHROPIC_API_KEY=$C
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
EOF
echo "✅ .env создан. Дальше: python3 login.py"
