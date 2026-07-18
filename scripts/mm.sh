#!/usr/bin/env bash
# Headless-исполнитель MiniMax M3. usage: mm.sh "<задача>" [минут_таймаут]
#
# INFRA-051 инцидент (2026-07-18): исполнитель с голым Bash-доступом сам
# сделал git commit, отредактировал TASK_BOARD/CHANGELOG вне списка файлов
# ТЗ, заявил о несуществующем "reviewer subagent → APPROVE" и удалил
# обязательный report-файл до того, как оркестратор успел его прочитать.
# Ниже — технический deny (git) + обязательный guardrail-блок, добавляемый
# к каждому ТЗ автоматически.
#
# INFRA-052 инцидент (2026-07-18): claude -p с cwd=/root/polymarket-bot
# автоматически подхватывал CLAUDE.md (протокол оркестрации) и кастомных
# субагентов из .claude/agents/ (debugger, reviewer). Исполнитель прочитал
# протокол делегирования как относящийся к себе и стал изображать
# оркестратора: TaskCreate себе подзадач, рекурсивный вызов scripts/mm.sh
# на самого себя, вызов Agent-тула debugger — процесс завис в цикле,
# убит вручную (pkill) через ~10 минут. Фикс: --safe-mode отключает
# CLAUDE.md auto-discovery и кастомных агентов (не трогает авторизацию,
# в отличие от --bare); дополнительный technical deny на самовызов.
set -u
set -o pipefail
TASK="$1"; LIMIT="${2:-30}"
LOG="/root/polymarket-bot/logs/mm_executor.log"

GUARDRAILS='

---
ОГРАНИЧЕНИЯ ИСПОЛНИТЕЛЯ (обязательны, не обсуждаются, не являются частью задачи выше):
- Правь только файлы, явно перечисленные в разделе "Файлы" ТЗ. Ничего сверх
  списка — включая docs/TASK_BOARD.md, changelogs/CHANGELOG.md,
  docs/PROJECT_STATE.md — не трогать. Документация и git — зона оркестратора.
- git-команды тебе недоступны технически (заблокированы) — не пытайся.
- Не утверждай в отчёте, что код прошёл ревью или тесты, которые ты не
  прогнал сам явно в рамках этой сессии и не показал вывод. Не ссылайся на
  несуществующих "reviewer subagent" — такого инструмента у тебя нет.
- Файл scratchpad/<task>_report.md — обязательный итоговый артефакт для
  оркестратора. Создай его и НЕ удаляй — оркестратор читает и убирает сам.'

TASK="${TASK}${GUARDRAILS}"

ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic" \
ANTHROPIC_AUTH_TOKEN="$(cat /root/.minimax_key)" \
ANTHROPIC_MODEL="MiniMax-M3" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
timeout "${LIMIT}m" /root/.local/bin/claude -p "$TASK" \
  --safe-mode \
  --permission-mode acceptEdits \
  --allowedTools "Bash" \
  --disallowedTools "Bash(git *)" "Bash(*mm.sh*)" "Bash(*/.local/bin/claude*)" "Agent" \
  --max-turns 60 \
  --output-format stream-json \
  --verbose \
  | python3 /root/polymarket-bot/scripts/mm_log_filter.py \
  | tee -a "$LOG"
echo "EXIT:${PIPESTATUS[0]}"
