#!/usr/bin/env bash
# Headless-исполнитель MiniMax M3. usage: mm.sh "<задача>" [минут_таймаут]
set -u
set -o pipefail
TASK="$1"; LIMIT="${2:-30}"
LOG="/root/polymarket-bot/logs/mm_executor.log"
ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic" \
ANTHROPIC_AUTH_TOKEN="$(cat /root/.minimax_key)" \
ANTHROPIC_MODEL="MiniMax-M3" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
timeout "${LIMIT}m" /root/.local/bin/claude -p "$TASK" \
  --permission-mode acceptEdits \
  --allowedTools "Bash" \
  --max-turns 60 \
  --output-format stream-json \
  --verbose \
  | python3 /root/polymarket-bot/scripts/mm_log_filter.py \
  | tee -a "$LOG"
echo "EXIT:${PIPESTATUS[0]}"
