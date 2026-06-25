#!/bin/bash
# Интерактивный ввод ключей. Запуск: bash configure.sh
cd "$(dirname "$0")"
echo "Введи ключи (после каждого — Enter):"
read -p "  api_id (число): " A
read -p "  api_hash: " B
read -p "  Anthropic API key: " C
cat > .env <<EOF
TG_API_ID=$A
TG_API_HASH=$B
TG_SESSION=
SHEET_ID=1SS6Sl2L4LHQXGaWx6sE8Hh9M_fLfImufCwK8d5VLQVA
GOOGLE_CREDENTIALS_FILE=
ANTHROPIC_API_KEY=$C
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
EOF
echo "✅ .env создан. Дальше: python3 login.py"
