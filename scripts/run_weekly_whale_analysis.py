#!/usr/bin/env python3
"""Weekly Whale AI Analysis — анализ китов через OpenRouter AI.

Запуск: python3 scripts/run_weekly_whale_analysis.py
Cron: 0 9 * * 1 cd /root/polymarket-bot && python3 scripts/run_weekly_whale_analysis.py >> logs/weekly_whale_analysis.log 2>&1
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5433/polymarket"
)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

LOGS_DIR = Path("/root/polymarket-bot/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# System prompt for AI analysis
SYSTEM_PROMPT = """You are a quantitative analyst for a whale copy-trading system on Polymarket prediction markets.

You receive weekly performance metrics for tracked whales and must produce structured recommendations.

## MARKET CONTEXT

Sports is the dominant edge category (+$2M total PnL, 59% WR, 13,589 confirmed roundtrips).
Politics and Other have negative expected value despite high win rates — asymmetric loss risk.
Crypto and Weather/Economics are statistically insignificant sample sizes.

## EVALUATION RULES

### Promoting a whale to paper (from none):
- Minimum 30 confirmed roundtrips
- Win rate > 60%
- Positive total PnL
- Active last 7 days (trades_last_7d > 0)
- Dominant category must NOT be Politics or Other

### Downgrading a whale from paper/tracked:
- Win rate 14d drops below 50% for 2 consecutive weeks
- Weekly PnL negative for 3 of last 4 weeks
- Zero activity for 14+ days

### Red flags (requires_human_review = true):
- One-hit wonder: top-3 trades > 90% of total PnL
- Win rate 14d degrades > 5pp vs all-time WR
- Sudden activity spike (trades_7d > 3x historical average)
- New whale in paper < 7 days: skip rate not representative

### Structural filters (NOT bugs):
- skip_ratio = 0 for paper/tracked whales is expected — they use PAPER_TRACK/TRACKED source
- UNAVAILABLE pnl_status means position still OPEN — exclude from PnL calculations
- Sports dominance in portfolio is a feature, not concentration risk

## OUTPUT FORMAT

Respond ONLY with valid JSON. No preamble, no markdown, no explanation outside JSON.

{
  "analysis_date": "<ISO date>",
  "model": "<model name>",
  "recommendations": [
    {
      "wallet_address": "0x...",
      "current_status": "paper|tracked|none",
      "recommended_action": "keep|upgrade|downgrade|watch",
      "recommended_status": "paper|tracked|none",
      "confidence": "high|medium|low",
      "reasoning": "<2-3 sentences max>"
    }
  ],
  "red_flags": [
    {
      "wallet_address": "0x...",
      "flag_type": "<type>",
      "description": "<1 sentence>"
    }
  ],
  "category_insights": [
    {
      "category": "<name>",
      "edge_assessment": "strong|positive|weak|negative",
      "note": "<1 sentence>"
    }
  ],
  "requires_human_review": true,
  "summary": "<3-5 sentences overall assessment>"
}"""

# =============================================================================
# Database helpers
# =============================================================================

def get_db_connection():
    """Create database connection from DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)


def get_config(conn):
    """Read ai_model and ai_provider_url from strategy_config.
    
    String keys (ai_model, ai_provider_url) → value_text column.
    Numeric keys → value column.
    """
    config = {}
    query = """
        SELECT key, value_text
        FROM strategy_config
        WHERE key IN ('ai_model', 'ai_provider_url')
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            for key, value_text in cur.fetchall():
                if value_text is not None:
                    config[key] = value_text
    except Exception as e:
        print(f"ERROR: Failed to read strategy_config: {e}")
        raise
    return config


def collect_metrics(conn):
    """Execute three SQL blocks from weekly_whale_metrics.sql.
    
    Returns dict with keys:
    - paper_tracked_whales: list of whale metrics
    - candidates: list of candidate whales
    - category_edge: list of category assessments
    """
    result = {
        'paper_tracked_whales': [],
        'candidates': [],
        'category_edge': []
    }
    
    # БЛОК 1: Метрики paper/tracked китов
    block1_sql = """
WITH 
weekly_pnl AS (
    SELECT 
        wtr.wallet_address,
        EXTRACT(WEEK FROM NOW() - INTERVAL '1 week') - EXTRACT(WEEK FROM wtr.closed_at) AS weeks_ago,
        SUM(wtr.net_pnl_usd) AS weekly_net_pnl
    FROM whale_trade_roundtrips wtr
    WHERE wtr.pnl_status = 'CONFIRMED'
      AND wtr.closed_at >= NOW() - INTERVAL '28 days'
    GROUP BY wtr.wallet_address, EXTRACT(WEEK FROM NOW() - INTERVAL '1 week') - EXTRACT(WEEK FROM wtr.closed_at)
),
weekly_pnl_pivot AS (
    SELECT 
        wallet_address,
        COALESCE(SUM(CASE WHEN weeks_ago = 0 THEN weekly_net_pnl END), 0) AS pnl_week_1,
        COALESCE(SUM(CASE WHEN weeks_ago = 1 THEN weekly_net_pnl END), 0) AS pnl_week_2,
        COALESCE(SUM(CASE WHEN weeks_ago = 2 THEN weekly_net_pnl END), 0) AS pnl_week_3,
        COALESCE(SUM(CASE WHEN weeks_ago = 3 THEN weekly_net_pnl END), 0) AS pnl_week_4
    FROM weekly_pnl
    GROUP BY wallet_address
),
skip_rate AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE source = 'POLLER') AS poller_count,
        COUNT(*) FILTER (WHERE source = 'TRACKED') AS tracked_count,
        ROUND(
            COUNT(*) FILTER (WHERE source = 'POLLER')::NUMERIC / 
            NULLIF(COUNT(*) FILTER (WHERE source = 'TRACKED'), 0)::NUMERIC, 
            2
        ) AS skip_ratio
    FROM whale_trades
    WHERE traded_at >= NOW() - INTERVAL '7 days'
    GROUP BY wallet_address
),
roundtrip_stats AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED') AS confirmed_roundtrips,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND closed_at >= NOW() - INTERVAL '14 days') AS confirmed_last_14d,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED' AND closed_at >= NOW() - INTERVAL '14 days' AND net_pnl_usd > 0) AS wins_14d,
        COUNT(*) FILTER (WHERE status = 'OPEN') AS open_positions
    FROM whale_trade_roundtrips
    GROUP BY wallet_address
)
SELECT 
    w.wallet_address,
    w.copy_status,
    ROUND(w.win_rate_confirmed::NUMERIC, 4) AS wr_alltime,
    ROUND(
        rs.wins_14d::NUMERIC / NULLIF(rs.confirmed_last_14d, 0),
        4
    ) AS wr_14d_direct,
    ROUND(w.total_pnl_usd::NUMERIC, 2) AS total_pnl_usd,
    COALESCE(w.trades_last_7_days, 0) AS trades_last_7_days,
    ROUND(COALESCE(w.avg_pnl_usd, 0)::NUMERIC, 4) AS avg_pnl_usd,
    rs.confirmed_roundtrips AS closed_roundtrips,
    rs.open_positions,
    ROUND(wp.pnl_week_1::NUMERIC, 2) AS pnl_week_1,
    ROUND(wp.pnl_week_2::NUMERIC, 2) AS pnl_week_2,
    ROUND(wp.pnl_week_3::NUMERIC, 2) AS pnl_week_3,
    ROUND(wp.pnl_week_4::NUMERIC, 2) AS pnl_week_4,
    COALESCE(sr.skip_ratio, 0) AS skip_ratio
FROM whales w
LEFT JOIN roundtrip_stats rs ON rs.wallet_address = w.wallet_address
LEFT JOIN weekly_pnl_pivot wp ON wp.wallet_address = w.wallet_address
LEFT JOIN skip_rate sr ON sr.wallet_address = w.wallet_address
WHERE w.copy_status IN ('paper', 'tracked')
ORDER BY w.total_pnl_usd DESC NULLS LAST
LIMIT 20
"""
    
    # БЛОК 2: Кандидаты из none
    block2_sql = """
WITH 
confirmed_counts AS (
    SELECT 
        wallet_address,
        COUNT(*) FILTER (WHERE pnl_status = 'CONFIRMED') AS confirmed_roundtrips
    FROM whale_trade_roundtrips
    GROUP BY wallet_address
),
dominant_category AS (
    SELECT 
        wallet_address,
        market_category,
        trade_count,
        ROW_NUMBER() OVER (PARTITION BY wallet_address ORDER BY trade_count DESC) AS rn
    FROM (
        SELECT 
            wallet_address,
            market_category,
            COUNT(*) AS trade_count
        FROM whale_trades
        WHERE market_category IS NOT NULL
        GROUP BY wallet_address, market_category
    ) sub
)
SELECT 
    w.wallet_address,
    ROUND(w.total_pnl_usd::NUMERIC, 2) AS total_pnl_usd,
    ROUND(w.win_rate_confirmed::NUMERIC, 4) AS win_rate_confirmed,
    COALESCE(w.trades_last_7_days, 0) AS trades_last_7_days,
    w.days_active_7d,
    w.whale_category,
    dc.market_category AS dominant_category
FROM whales w
JOIN confirmed_counts cc ON cc.wallet_address = w.wallet_address
LEFT JOIN dominant_category dc ON dc.wallet_address = w.wallet_address AND dc.rn = 1
WHERE w.copy_status = 'none'
  AND cc.confirmed_roundtrips >= 30
ORDER BY w.total_pnl_usd DESC NULLS LAST
LIMIT 5
"""
    
    # БЛОК 3: Системный edge по категориям
    block3_sql = """
WITH 
category_stats AS (
    SELECT 
        market_category,
        COUNT(*) AS confirmed_count,
        AVG(net_pnl_usd) AS avg_net_pnl,
        SUM(net_pnl_usd) AS total_net_pnl,
        COUNT(*) FILTER (WHERE net_pnl_usd > 0) AS wins,
        COUNT(*) FILTER (WHERE net_pnl_usd <= 0) AS losses
    FROM whale_trade_roundtrips
    WHERE pnl_status = 'CONFIRMED'
      AND market_category IS NOT NULL
    GROUP BY market_category
),
top_whale_per_category AS (
    SELECT 
        wtr.market_category,
        wtr.wallet_address,
        SUM(wtr.net_pnl_usd) AS whale_total_pnl,
        ROW_NUMBER() OVER (PARTITION BY wtr.market_category ORDER BY SUM(wtr.net_pnl_usd) DESC) AS rn
    FROM whale_trade_roundtrips wtr
    WHERE wtr.pnl_status = 'CONFIRMED'
    GROUP BY wtr.market_category, wtr.wallet_address
)
SELECT 
    cs.market_category,
    cs.confirmed_count,
    ROUND(cs.avg_net_pnl::NUMERIC, 2) AS avg_net_pnl,
    ROUND(cs.total_net_pnl::NUMERIC, 2) AS total_net_pnl,
    ROUND(
        cs.wins::NUMERIC / NULLIF(cs.confirmed_count, 0),
        4
    ) AS win_rate,
    tw.wallet_address AS top_whale_address,
    ROUND(tw.whale_total_pnl::NUMERIC, 2) AS top_whale_pnl
FROM category_stats cs
LEFT JOIN top_whale_per_category tw ON tw.market_category = cs.market_category AND tw.rn = 1
ORDER BY cs.total_net_pnl DESC NULLS LAST
"""
    
    try:
        with conn.cursor() as cur:
            # Block 1: paper/tracked whales
            cur.execute(block1_sql)
            cols = [desc[0] for desc in cur.description]
            result['paper_tracked_whales'] = [dict(zip(cols, row)) for row in cur.fetchall()]
            
            # Block 2: candidates
            cur.execute(block2_sql)
            cols = [desc[0] for desc in cur.description]
            result['candidates'] = [dict(zip(cols, row)) for row in cur.fetchall()]
            
            # Block 3: category edge
            cur.execute(block3_sql)
            cols = [desc[0] for desc in cur.description]
            result['category_edge'] = [dict(zip(cols, row)) for row in cur.fetchall()]
        
        print(f"Collected metrics: {len(result['paper_tracked_whales'])} paper/tracked, "
              f"{len(result['candidates'])} candidates, "
              f"{len(result['category_edge'])} categories")
    except Exception as e:
        print(f"ERROR: Failed to collect metrics: {e}")
        raise
    
    return result


def call_openrouter(metrics_json: str, model: str, provider_url: str) -> str:
    """Call OpenRouter API with metrics JSON.
    
    Returns raw text response from API.
    """
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set in environment")
    
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': metrics_json}
        ]
    }
    
    try:
        req = urllib.request.Request(
            provider_url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status == 200:
                result = json.loads(response.read().decode('utf-8'))
                # Extract content from OpenRouter response format
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
                return json.dumps(result)
            else:
                raise Exception(f"HTTP {response.status}: {response.read().decode('utf-8')}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else "no response"
        raise Exception(f"HTTP {e.code}: {e.reason} - {error_body}")
    except urllib.error.URLError as e:
        raise Exception(f"URL Error: {e.reason}")
    except Exception as e:
        raise Exception(f"OpenRouter call failed: {type(e).__name__}: {e}")


def parse_response(raw: str) -> dict:
    """Extract JSON from OpenRouter response.
    
    If parsing fails, returns {"error": "parse_failed", "raw": raw}.
    """
    try:
        # Try to find JSON in the response
        raw_stripped = raw.strip()
        
        # Handle response wrapped in markdown code blocks
        if raw_stripped.startswith('```json'):
            raw_stripped = raw_stripped[7:]
        if raw_stripped.startswith('```'):
            raw_stripped = raw_stripped[3:]
        if raw_stripped.endswith('```'):
            raw_stripped = raw_stripped[:-3]
        
        raw_stripped = raw_stripped.strip()
        
        return json.loads(raw_stripped)
    except json.JSONDecodeError as e:
        print(f"WARNING: JSON parse failed: {e}")
        return {"error": "parse_failed", "raw": raw[:500]}


def send_telegram(message: str) -> bool:
    """Send message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured - skipping alert")
        return False
    
    # Convert Markdown emojis to HTML-safe format
    message = message.replace("**", "<b>").replace("**", "</b>")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode(),
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                return True
            else:
                print(f"Telegram API error: HTTP {response.status}")
                return False
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else "no response"
        print(f"HTTP Error {e.code} sending Telegram: {e.reason} - {error_body}")
        return False
    except urllib.error.URLError as e:
        print(f"URL Error sending Telegram: {e.reason}")
        return False
    except Exception as e:
        print(f"Failed to send Telegram message: {type(e).__name__}: {e}")
        return False


def format_telegram_message(analysis: dict, metrics: dict) -> str:
    """Format Telegram message with whale analysis."""
    lines = []
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    lines.append(f"🐋 <b>WEEKLY WHALE ANALYSIS</b> — {date_str}")
    lines.append("")
    
    # Active whales section
    whales = analysis.get('whale_statuses', [])
    if whales:
        lines.append("📊 <b>АКТИВНЫЕ КИТЫ:</b>")
        for w in whales[:10]:
            addr_short = w.get('wallet_address', 'unknown')
            if addr_short and len(addr_short) > 10:
                addr_short = addr_short[:10] + "..."
            current = w.get('current_status', 'unknown')
            action = w.get('recommended_action', 'unknown')
            confidence = w.get('confidence', 'unknown')
            lines.append(f"{addr_short}: {current} → {action} ({confidence})")
        lines.append("")
    
    # Red flags
    red_flags = analysis.get('red_flags', [])
    if red_flags:
        lines.append("🚨 <b>RED FLAGS:</b>")
        for rf in red_flags[:5]:
            whale = rf.get('whale_address', 'unknown')
            if whale and len(whale) > 10:
                whale = whale[:10] + "..."
            issue = rf.get('issue', 'unknown')
            severity = rf.get('severity', 'unknown')
            lines.append(f"{whale}: {issue} [{severity}]")
        lines.append("")
    else:
        lines.append("🚨 <b>RED FLAGS:</b> нет")
        lines.append("")
    
    # Category assessment
    categories = analysis.get('category_assessment', [])
    if categories:
        lines.append("📈 <b>КАТЕГОРИИ:</b>")
        for cat in categories[:5]:
            cat_name = cat.get('category', 'unknown')
            edge = cat.get('edge_assessment', 'unknown')
            lines.append(f"{cat_name}: {edge}")
        lines.append("")
    
    # Summary
    summary = analysis.get('summary', 'нет данных')
    lines.append(f"💡 <b>SUMMARY:</b> {summary}")
    lines.append("")
    
    # SQL for confirmed changes
    sql_updates = []
    for w in whales:
        action = w.get('recommended_action', '')
        wallet = w.get('wallet_address', '')
        if action == 'upgrade' and wallet:
            sql_updates.append(f"UPDATE whales SET copy_status='tracked' WHERE wallet_address='{wallet}';")
        elif action == 'downgrade' and wallet:
            sql_updates.append(f"UPDATE whales SET copy_status='none' WHERE wallet_address='{wallet}';")
    
    lines.append("✅ <b>SQL ДЛЯ ПОДТВЕРЖДЁННЫХ ИЗМЕНЕНИЙ:</b>")
    if sql_updates:
        for sql in sql_updates[:10]:
            lines.append(sql)
    else:
        lines.append("изменений нет")
    
    return "\n".join(lines)


def log_error(record_id: int, error_message: str, conn):
    """Log error to whale_ai_analysis.error_log."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE whale_ai_analysis 
                SET error_log = %s, requires_human_review = true
                WHERE id = %s
            """, (error_message, record_id))
        conn.commit()
    except Exception as e:
        print(f"Failed to log error to DB: {e}")


# =============================================================================
# Main
# =============================================================================

def main():
    """Run weekly whale analysis."""
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    print(f"=== Weekly Whale AI Analysis === {ts}")
    
    conn = None
    record_id = None
    
    try:
        # Step 1: Get config
        print("Reading config from strategy_config...")
        conn = get_db_connection()
        config = get_config(conn)
        
        ai_model = config.get('ai_model')
        ai_provider_url = config.get('ai_provider_url')
        
        if not ai_model or not ai_provider_url:
            raise ValueError("ai_model or ai_provider_url not found in strategy_config")
        
        print(f"  Model: {ai_model}")
        print(f"  Provider: {ai_provider_url}")
        
        # Step 2: Collect metrics
        print("Collecting whale metrics...")
        metrics = collect_metrics(conn)
        
        # Step 3: INSERT record (fix row_id for later UPDATE)
        print("Creating analysis record...")
        raw_input = json.dumps(metrics)
        
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO whale_ai_analysis (model_used, raw_input_json, created_at)
                VALUES (%s, %s, NOW())
                RETURNING id
            """, (ai_model, raw_input))
            record_id = cur.fetchone()[0]
        conn.commit()
        print(f"  Record ID: {record_id}")
        
        # Step 4: Call OpenRouter
        print("Calling OpenRouter AI...")
        raw_response = call_openrouter(raw_input, ai_model, ai_provider_url)
        print(f"  Response length: {len(raw_response)} chars")
        
        # Step 5: Parse response
        print("Parsing AI response...")
        parsed = parse_response(raw_response)
        
        if parsed.get('error') == 'parse_failed':
            print(f"  WARNING: Parse failed, raw response truncated: {parsed.get('raw', '')[:100]}")
        
        # Step 6: UPDATE record with output
        print("Updating analysis record...")
        raw_output = json.dumps(parsed)
        recommendations = json.dumps(parsed.get('whale_statuses', []))
        red_flags = json.dumps(parsed.get('red_flags', []))
        
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE whale_ai_analysis 
                SET raw_output_json = %s,
                    recommendations_json = %s,
                    red_flags_json = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (raw_output, recommendations, red_flags, record_id))
        conn.commit()
        
        # Step 7: Format and send Telegram
        print("Formatting Telegram message...")
        message = format_telegram_message(parsed, metrics)
        print(f"  Message length: {len(message)} chars")
        
        print("Sending Telegram...")
        success = send_telegram(message)
        
        if success:
            print("  Telegram sent successfully")
            # Update telegram_sent_at
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE whale_ai_analysis 
                    SET telegram_sent_at = NOW()
                    WHERE id = %s
                """, (record_id,))
            conn.commit()
        else:
            print("  WARNING: Telegram send failed")
        
        print(f"\n=== Analysis complete. Record ID: {record_id} ===")
        return 0
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"ERROR: {error_msg}")
        
        if conn and record_id:
            log_error(record_id, error_msg, conn)
        
        return 1
        
    finally:
        if conn:
            conn.close()
            print("DB connection closed")


if __name__ == "__main__":
    sys.exit(main())