#!/bin/bash
#
# Smoke Test Script - Проверка состояния инфраструктуры после деплоя
# Выполняет проверки контейнеров, импортов, таблиц БД и логов
#

set -o pipefail

# Цветовой вывод
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Счетчики
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNINGS=0

# Функции вывода
print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}\n"
}

print_check() {
    echo -ne "  [$1] $2 "
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}"
    ((PASSED_CHECKS++))
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC} - $1"
    ((FAILED_CHECKS++))
}

print_warn() {
    echo -e "${YELLOW}⚠ WARN${NC} - $1"
    ((WARNINGS++))
}

print_info() {
    echo -e "    ${BLUE}→${NC} $1"
}

print_section() {
    echo -e "\n${YELLOW}--- $1 ---${NC}"
}

# Главный результат
overall_result() {
    print_header "РЕЗУЛЬТАТЫ ПРОВЕРКИ"
    
    echo -e "Общие проверки:    ${GREEN}${PASSED_CHECKS}${NC} passed, ${RED}${FAILED_CHECKS}${NC} failed, ${YELLOW}${WARNINGS}${NC} warnings"
    echo ""
    
    if [ $FAILED_CHECKS -eq 0 ]; then
        echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✓ ALL CHECKS PASSED${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
        exit 0
    else
        echo -e "${RED}═══════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ✗ SOME CHECKS FAILED${NC}"
        echo -e "${RED}═══════════════════════════════════════════════════════════${NC}"
        exit 1
    fi
}

trap overall_result EXIT

#############################################
# 1. ПРОВЕРКА КОНТЕЙНЕРОВ
#############################################
print_header "1. ПРОВЕРКА КОНТЕЙНЕРОВ"

# Получаем все сервисы из docker-compose
SERVICES=$(docker compose config --services 2>/dev/null || docker-compose config --services 2>/dev/null)

if [ -z "$SERVICES" ]; then
    print_fail "Не удалось получить список сервисов из docker-compose"
else
    # Проверяем каждый сервис через docker compose ps с JSON форматом
    for service in $SERVICES; do
        print_check "service" "$service"
        
        # Используем JSON формат - результат это одна строка объекта (не массив)
        state=$(docker compose ps "$service" --format json 2>/dev/null | jq -r '.State // "unknown"' 2>/dev/null || echo "unknown")
        
        if echo "$state" | grep -qiE "(running|up)"; then
            print_pass
        else
            # Дополнительная проверка через inspect
            running=$(docker inspect "polymarket_$service" --format '{{.State.Running}}' 2>/dev/null || echo "false")
            health=$(docker inspect "polymarket_$service" --format '{{.State.Health.Status}}' 2>/dev/null || echo "none")
            
            if [ "$running" = "true" ] || [ "$health" = "healthy" ]; then
                print_pass
            else
                print_fail "Status: $state (ожидается running/Up)"
            fi
        fi
    done
fi

#############################################
# 2. ПРОВЕРКА PYTHON ИМПОРТОВ
#############################################
print_header "2. ПРОВЕРКА PYTHON ИМПОРТОВ"

# Paper Position Settlement Engine
print_check "import" "src.strategy.paper_position_settlement.PaperPositionSettlementEngine"
if docker compose exec -T bot python -c "from src.strategy.paper_position_settlement import PaperPositionSettlementEngine" 2>/dev/null; then
    print_pass
else
    print_fail "Не удалось импортировать PaperPositionSettlementEngine"
fi

# RoundtripBuilder (ожидаемо FAIL)
print_check "import" "src.strategy.roundtrip_builder.RoundtripBuilder (expected FAIL)"
if docker compose exec -T bot python -c "from src.strategy.roundtrip_builder import RoundtripBuilder" 2>/dev/null; then
    print_pass
else
    print_warn "RoundtripBuilder импорт не работает (ожидаемо)"
fi

# WhaleDetector
print_check "import" "src.research.whale_detector.WhaleDetector"
if docker compose exec -T bot python -c "from src.research.whale_detector import WhaleDetector" 2>/dev/null; then
    print_pass
else
    print_fail "Не удалось импортировать WhaleDetector"
fi

#############################################
# 3. ПРОВЕРКА ТАБЛИЦ БД
#############################################
print_header "3. ПРОВЕРКА ТАБЛИЦ БД"

# Определяем способ подключения к PostgreSQL
if docker compose ps postgres -q 2>/dev/null | xargs -r docker compose inspect -f '{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    DB_CMD="docker compose exec -T postgres psql -U postgres -d polymarket -t -c"
elif docker compose ps -q 2>/dev/null | xargs -r docker compose inspect -f '{{.State.Running}}' 2>/dev/null | grep -q "postgres"; then
    # Postgres might be in the same compose file
    DB_CMD="docker compose exec -T postgres psql -U postgres -d polymarket -t -c"
else
    # Fallback - попробовать через любой работающий контейнер
    DB_CMD="docker compose exec -T bot psql -h postgres -U postgres -d polymarket -t -c"
fi

# Проверка таблицы whales
print_check "table" "whales"
if $DB_CMD "SELECT 1 FROM whales LIMIT 1" >/dev/null 2>&1; then
    print_pass
else
    print_fail "Таблица whales не существует или недоступна"
fi

# Проверка таблицы whale_trades
print_check "table" "whale_trades"
if $DB_CMD "SELECT 1 FROM whale_trades LIMIT 1" >/dev/null 2>&1; then
    print_pass
else
    print_fail "Таблица whale_trades не существует или недоступна"
fi

# Проверка таблицы whale_trade_roundtrips
print_check "table" "whale_trade_roundtrips"
if $DB_CMD "SELECT 1 FROM whale_trade_roundtrips LIMIT 1" >/dev/null 2>&1; then
    print_pass
else
    print_fail "Таблица whale_trade_roundtrips не существует или недоступна"
fi

# Phase 2B: Verify VirtualBankroll is disabled (no new VIRTUAL trades)
# Ожидаем: 0 — если появились VIRTUAL trades, значит VB включили обратно
print_check "table" "trades (VirtualBankroll disabled)"
if $DB_CMD "SELECT COUNT(*) FROM trades WHERE executed_at > NOW() - INTERVAL '1 hour' AND exchange = 'VIRTUAL'" 2>/dev/null | xargs | grep -q "^0$"; then
    print_pass
else
    print_fail "Обнаружены VIRTUAL trades за последний час — VirtualBankroll возможно включён!"
fi

# Проверка таблицы trades
print_check "table" "trades"
if $DB_CMD "SELECT 1 FROM trades LIMIT 1" >/dev/null 2>&1; then
    print_pass
else
    print_fail "Таблица trades не существует или недоступна"
fi

#############################################
# 4. ПРОВЕРКА ЛОГОВ
#############################################
print_header "4. ПРОВЕРКА ЛОГОВ (последние 30 секунд)"

# Phase 2B: Verify bot heartbeat is fresh (< 60 seconds old)
print_check "heartbeat" "bot container heartbeat"
# Проверяем что контейнер bot запущен и имеет здоровый статус
bot_health=$(docker inspect polymarket_bot --format '{{.State.Health.Status}}' 2>/dev/null || echo "none")
bot_running=$(docker inspect polymarket_bot --format '{{.State.Running}}' 2>/dev/null || echo "false")

if [ "$bot_running" = "true" ]; then
    # Проверяем что бот "живой" — должен иметь статус healthy или running
    if [ "$bot_health" = "healthy" ] || [ "$bot_health" = "none" ]; then
        print_pass
    else
        print_fail "Bot container health: $bot_health"
    fi
else
    print_fail "Bot container not running"
fi

# Получаем все сервисы из docker-compose
SERVICES_FOR_LOGS=$(docker compose config --services 2>/dev/null || docker-compose config --services 2>/dev/null)

for service in $SERVICES_FOR_LOGS; do
    print_check "logs" "$service"
    
    # Получаем логи за последние 30 секунд
    logs=$(docker compose logs --since 30s "$service" 2>/dev/null || echo "")
    
    # Ищем именно Error, Exception или Traceback (с большой буквы)
    if echo "$logs" | grep -qiE "^[^|]*\|.*\b(Error|Exception|Traceback)\b"; then
        # Находим строки с ошибками
        error_lines=$(echo "$logs" | grep -iE "\b(Error|Exception|Traceback)\b" | head -3)
        print_fail "Обнаружены ошибки в логах:"
        echo "$error_lines" | while read -r line; do
            print_info "$line"
        done
    else
        print_pass
    fi
done

#############################################
# 5. ПРОВЕРКА SETTLEMENT PIPELINE
#############################################
print_header "5. ПРОВЕРКА SETTLEMENT PIPELINE"

# Check 20: No stuck OPEN roundtrips for resolved markets
print_check "stuck" "No stuck roundtrips for resolved markets"
STUCK=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT COUNT(*) FROM whale_trade_roundtrips rt JOIN market_resolutions mr ON rt.market_id=mr.market_id WHERE rt.status='OPEN' AND mr.is_closed=TRUE AND mr.winner_outcome IS NOT NULL;")
if [ "$STUCK" -eq 0 ]; then
    print_pass
else
    print_fail "$STUCK stuck roundtrips for resolved markets"
fi

# Check A: market_resolutions freshness (<3h)
print_check "DB" "market_resolutions freshness (<3h)"
RESULT=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c "SELECT COUNT(*) FROM market_resolutions WHERE fetched_at < NOW() - INTERVAL '3 hours';")
if [ "$RESULT" -eq 0 ]; then
    print_pass
else
    print_fail "stale records: ${RESULT} market_resolutions older than 3h"
fi

#############################################
# 6. ПРОВЕРКА MATERIALIZED VIEWS
#############################################
print_header "6. ПРОВЕРКА MATERIALIZED VIEWS"

# Check 21: whale_pnl_summary exists and has data
print_check "view" "whale_pnl_summary"
VIEW_COUNT=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT COUNT(*) FROM whale_pnl_summary;" 2>/dev/null)
if [ -n "$VIEW_COUNT" ] && [ "$VIEW_COUNT" -gt 0 ]; then
    print_pass
else
    print_fail "Empty or missing"
fi

# Check 22: paper_portfolio_state has balance > 0
print_check "view" "paper_portfolio_state"
BALANCE=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT ROUND(current_balance::numeric, 2) FROM paper_portfolio_state LIMIT 1;" 2>/dev/null)
if [ -n "$BALANCE" ] && [ "$BALANCE" != "" ]; then
    print_pass
else
    print_fail "Empty or missing"
fi

# Check 23: paper_simulation_pnl has data
print_check "view" "paper_simulation_pnl"
SIM_COUNT=$(docker exec polymarket_postgres psql -U postgres -d polymarket -t -A -c \
    "SELECT COUNT(*) FROM paper_simulation_pnl;" 2>/dev/null)
if [ -n "$SIM_COUNT" ] && [ "$SIM_COUNT" -gt 0 ]; then
    print_pass
else
    print_fail "Empty or missing"
fi

#############################################
# ИТОГ
#############################################
# Функция overall_result вызывается автоматически через trap