#!/usr/bin/env bash
# Headless-исполнитель MiniMax M3. usage: mm.sh "<задача>" [минут_таймаут]
set -u
TASK="$1"; LIMIT="${2:-30}"
ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic" \
ANTHROPIC_AUTH_TOKEN="$(cat /root/.minimax_key)" \
ANTHROPIC_MODEL="MiniMax-M3" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
timeout "${LIMIT}m" /root/.local/bin/claude -p "$TASK" \
  --permission-mode acceptEdits \
  --max-turns 60 \
  --output-format json
echo "EXIT:$?"
