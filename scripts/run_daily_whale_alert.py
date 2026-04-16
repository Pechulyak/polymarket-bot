#!/usr/bin/env python3
"""Daily Whale Alert Monitor — алерты по китам без изменения статуса.

Запуск: python3 scripts/run_daily_whale_alert.py
Cron: 0 8 * * * cd /root/polymarket-bot && python3 scripts/run_daily_whale_alert.py >> logs/daily_whale_alert.log 2>&1
"""
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg2

# Load environment variables from .env file
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

LOGS_DIR = Path("/root/polymarket-bot/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Database helpers
# =============================================================================

def get_db_connection():
    """Create database connection from DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)


def execute_query(query, params=None):
    """Execute a query and return all results."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchall()
            return cur.rowcount
    finally:
        conn.close()


def get_scalar(query, params=None):
    """Execute a query and return single scalar value."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            result = cur.fetchone()
            return result[0] if result else None
    finally:
        conn.close()


# =============================================================================
# Load alert thresholds from strategy_config
# =============================================================================

def load_alert_thresholds():
    """Load all alert_* thresholds from strategy_config."""
    thresholds = {}
    query = """
        SELECT key, value::numeric 
        FROM strategy_config 
        WHERE key LIKE 'alert_%'
    """
    try:
        results = execute_query(query)
        for key, value in results:
            thresholds[key] = float(value)
        print(f"Loaded {len(thresholds)} alert thresholds: {thresholds}")
    except Exception as e:
        print(f"WARNING: Could not load thresholds: {e}")
        # Defaults
        thresholds = {
            'alert_paper_inactivity_days': 7,
            'alert_tracked_inactivity_days': 14,
            'alert_skip_rate_threshold': 0.60,
            'alert_wr_min_threshold': 0.48,
            'alert_candidate_min_roundtrips': 30,
            'alert_candidate_min_wr': 0.55,
        }
        print(f"Using defaults: {thresholds}")
    return thresholds


# =============================================================================
# CHECK 1: Paper whale inactivity
# =============================================================================

def check_paper_inactive(paper_days: int):
    """Find paper whales with no trades in last N days."""
    query = """
        SELECT w.wallet_address, w.last_active_at
        FROM whales w
        WHERE w.copy_status = 'paper'
          AND (w.last_active_at IS NULL 
               OR w.last_active_at < NOW() - INTERVAL '%s days')
        ORDER BY w.last_active_at NULLS FIRST
        LIMIT 20
    """
    return execute_query(query, (paper_days,))


# =============================================================================
# CHECK 2: Tracked whale inactivity
# =============================================================================

def check_tracked_inactive(tracked_days: int):
    """Find tracked whales with no trades in last N days."""
    query = """
        SELECT w.wallet_address, w.last_active_at
        FROM whales w
        WHERE w.copy_status = 'tracked'
          AND (w.last_active_at IS NULL 
               OR w.last_active_at < NOW() - INTERVAL '%s days')
        ORDER BY w.last_active_at NULLS FIRST
        LIMIT 20
    """
    return execute_query(query, (tracked_days,))


# =============================================================================
# CHECK 3: Skip rate (paper whales)
# =============================================================================

def check_skip_rate(skip_threshold: float):
    """Find paper whales with skip_rate > (1 - threshold).
    
    Skip rate = paper_trades / whale_trades ratio.
    Uses GREATEST(reviewed_at, NOW() - 7 days) as lower bound for new whales.
    """
    query = """
        WITH whale_activity AS (
            SELECT 
                w.wallet_address,
                w.reviewed_at,
                COALESCE(wt.trade_count, 0) as whale_trades_7d,
                COALESCE(pt.trade_count, 0) as paper_trades_7d,
                wt.median_trade_size,
                GREATEST(
                    COALESCE(w.reviewed_at, NOW() - INTERVAL '7 days'),
                    NOW() - INTERVAL '7 days'
                ) as window_start
            FROM whales w
            LEFT JOIN (
                SELECT 
                    whale_id, 
                    COUNT(*) as trade_count,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY size_usd) as median_trade_size
                FROM whale_trades
                WHERE traded_at > GREATEST(
                    COALESCE((SELECT reviewed_at FROM whales WHERE id = whale_id), NOW() - INTERVAL '7 days'),
                    NOW() - INTERVAL '7 days'
                )
                GROUP BY whale_id
            ) wt ON wt.whale_id = w.id
            LEFT JOIN (
                SELECT whale_address, COUNT(*) as trade_count
                FROM paper_trades
                WHERE created_at > GREATEST(
                    COALESCE((SELECT reviewed_at FROM whales WHERE wallet_address = paper_trades.whale_address), NOW() - INTERVAL '7 days'),
                    NOW() - INTERVAL '7 days'
                )
                GROUP BY whale_address
            ) pt ON pt.whale_address = w.wallet_address
            WHERE w.copy_status = 'paper'
              AND COALESCE(wt.trade_count, 0) > 0
        )
        SELECT 
            wallet_address, 
            whale_trades_7d, 
            paper_trades_7d,
            median_trade_size,
            (SELECT value::numeric FROM strategy_config WHERE key = 'min_trade_size_usd') as min_trade_size,
            ROUND(EXTRACT(DAYS FROM (NOW() - window_start)))::integer as window_days
        FROM whale_activity
        WHERE paper_trades_7d::float / whale_trades_7d < (1.0 - %s)
        ORDER BY whale_trades_7d DESC
        LIMIT 20
    """
    return execute_query(query, (skip_threshold,))


# =============================================================================
# CHECK 4: Win rate degradation (14d rolling)
# =============================================================================

def check_wr_degradation(wr_min_threshold: float):
    """Find paper whales with win rate below threshold over 14d rolling window."""
    query = """
        SELECT 
            w.wallet_address,
            COALESCE(rt.total, 0) as total_roundtrips,
            COALESCE(rt.wins, 0) as wins,
            CASE 
                WHEN COALESCE(rt.total, 0) > 0 
                THEN COALESCE(rt.wins, 0)::float / COALESCE(rt.total, 0)
                ELSE 0 
            END as win_rate
        FROM whales w
        LEFT JOIN (
            SELECT 
                wallet_address,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE net_pnl_usd > 0) as wins
            FROM whale_trade_roundtrips
            WHERE closed_at > NOW() - INTERVAL '14 days'
              AND status = 'closed'
            GROUP BY wallet_address
        ) rt ON rt.wallet_address = w.wallet_address
        WHERE w.copy_status = 'paper'
          AND COALESCE(rt.total, 0) >= 5  -- minimum sample size
          AND CASE 
                WHEN COALESCE(rt.total, 0) > 0 
                THEN COALESCE(rt.wins, 0)::float / COALESCE(rt.total, 0)
                ELSE 0 
              END < %s
        ORDER BY win_rate ASC
        LIMIT 20
    """
    return execute_query(query, (wr_min_threshold,))


# =============================================================================
# CHECK 5: New candidates
# =============================================================================

def check_new_candidates(min_roundtrips: int, min_wr: float):
    """Find whales that meet candidate criteria.
    
    Criteria:
    - copy_status = 'none' (not yet tracking)
    - >= min_roundtrips closed roundtrips
    - win rate >= min_wr
    """
    query = """
        SELECT 
            w.wallet_address,
            COALESCE(rt.total, 0) as total_roundtrips,
            COALESCE(rt.wins, 0) as wins,
            CASE 
                WHEN COALESCE(rt.total, 0) > 0 
                THEN COALESCE(rt.wins, 0)::float / COALESCE(rt.total, 0)
                ELSE 0 
            END as win_rate
        FROM whales w
        LEFT JOIN (
            SELECT 
                wallet_address,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE net_pnl_usd > 0) as wins
            FROM whale_trade_roundtrips
            WHERE status = 'closed'
            GROUP BY wallet_address
        ) rt ON rt.wallet_address = w.wallet_address
        WHERE w.copy_status = 'none'
          AND COALESCE(rt.total, 0) >= %s
          AND CASE 
                WHEN COALESCE(rt.total, 0) > 0 
                THEN COALESCE(rt.wins, 0)::float / COALESCE(rt.total, 0)
                ELSE 0 
              END >= %s
        ORDER BY rt.total DESC, win_rate DESC
        LIMIT 20
    """
    return execute_query(query, (min_roundtrips, min_wr))


# =============================================================================
# Telegram alerts
# =============================================================================

def send_telegram_message(message: str):
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
        import urllib.request
        import urllib.parse
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


# =============================================================================
# Format alert message
# =============================================================================

def format_alert_message(
    date_str: str,
    paper_inactive: list,
    tracked_inactive: list,
    skip_rate_issues: list,
    wr_degradation: list,
    new_candidates: list
) -> str:
    """Format HTML message for Telegram."""
    lines = []
    lines.append(f"🐋 <b>Whale Monitor Alert</b> — {date_str}")
    lines.append("")
    
    # Paper inactive
    if paper_inactive:
        lines.append(f"⚠️ <b>Paper inactive ({len(paper_inactive)}):</b>")
        for addr, last_active in paper_inactive[:10]:
            addr_short = addr[:10] if addr else "unknown"
            last_str = last_active.strftime("%Y-%m-%d") if last_active else "never"
            lines.append(f"  • 0x{addr_short}... (last: {last_str})")
        if len(paper_inactive) > 10:
            lines.append(f"  ... and {len(paper_inactive) - 10} more")
        lines.append("")
    
    # Tracked inactive
    if tracked_inactive:
        lines.append(f"⚠️ <b>Tracked inactive ({len(tracked_inactive)}):</b>")
        for addr, last_active in tracked_inactive[:10]:
            addr_short = addr[:10] if addr else "unknown"
            last_str = last_active.strftime("%Y-%m-%d") if last_active else "never"
            lines.append(f"  • 0x{addr_short}... (last: {last_str})")
        if len(tracked_inactive) > 10:
            lines.append(f"  ... and {len(tracked_inactive) - 10} more")
        lines.append("")
    
    # Skip rate issues
    if skip_rate_issues:
        lines.append(f"🔴 <b>Skip rate issues ({len(skip_rate_issues)}):</b>")
        for addr, whale_trades, paper_trades, median_size, min_size, window_days in skip_rate_issues[:10]:
            addr_short = addr[:10] if addr else "unknown"
            skip_rate = 1.0 - (paper_trades / whale_trades) if whale_trades > 0 else 1.0
            lines.append(f"  • 0x{addr_short}... — {skip_rate:.1%} skip ({paper_trades}/{whale_trades} followed) [{window_days}d window]")
            lines.append(f"  median trade: ${median_size:.2f} | min_trade_size: ${min_size:.2f}")
            # Add hint if median is less than 10x min_trade_size
            if median_size < min_size * 10:
                lines.append(f"  ℹ️ High skip likely due to small trades filter")
        if len(skip_rate_issues) > 10:
            lines.append(f"  ... and {len(skip_rate_issues) - 10} more")
        lines.append("")
    
    # WR degradation
    if wr_degradation:
        lines.append(f"🔴 <b>WR degradation ({len(wr_degradation)}):</b>")
        for addr, total, wins, wr in wr_degradation[:10]:
            addr_short = addr[:10] if addr else "unknown"
            lines.append(f"  • 0x{addr_short}... — WR {wr:.1%} ({wins}/{total})")
        if len(wr_degradation) > 10:
            lines.append(f"  ... and {len(wr_degradation) - 10} more")
        lines.append("")
    
    # New candidates
    if new_candidates:
        lines.append(f"🟢 <b>New candidates ({len(new_candidates)}):</b>")
        for addr, total, wins, wr in new_candidates[:10]:
            addr_short = addr[:10] if addr else "unknown"
            lines.append(f"  • 0x{addr_short}... — {total} roundtrips, WR {wr:.1%}")
        if len(new_candidates) > 10:
            lines.append(f"  ... and {len(new_candidates) - 10} more")
        lines.append("")
    
    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    """Run daily whale alert checks."""
    print(f"=== Daily Whale Alert Monitor === {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    
    # Load thresholds
    thresholds = load_alert_thresholds()
    
    # Run checks
    print("\nRunning checks...")
    
    # CHECK 1: Paper inactive
    paper_inactive = check_paper_inactive(int(thresholds['alert_paper_inactivity_days']))
    print(f"  Paper inactive: {len(paper_inactive)}")
    
    # CHECK 2: Tracked inactive
    tracked_inactive = check_tracked_inactive(int(thresholds['alert_tracked_inactivity_days']))
    print(f"  Tracked inactive: {len(tracked_inactive)}")
    
    # CHECK 3: Skip rate
    skip_rate_issues = check_skip_rate(thresholds['alert_skip_rate_threshold'])
    print(f"  Skip rate issues: {len(skip_rate_issues)}")
    
    # CHECK 4: WR degradation
    wr_degradation = check_wr_degradation(thresholds['alert_wr_min_threshold'])
    print(f"  WR degradation: {len(wr_degradation)}")
    
    # CHECK 5: New candidates
    new_candidates = check_new_candidates(
        int(thresholds['alert_candidate_min_roundtrips']),
        thresholds['alert_candidate_min_wr']
    )
    print(f"  New candidates: {len(new_candidates)}")
    
    # Check if any alerts triggered
    total_alerts = (len(paper_inactive) + len(tracked_inactive) + 
                   len(skip_rate_issues) + len(wr_degradation) + 
                   len(new_candidates))
    
    if total_alerts == 0:
        print("\nNo alerts triggered - exiting silently")
        return 0
    
    # Format and send message
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    message = format_alert_message(
        date_str,
        paper_inactive,
        tracked_inactive,
        skip_rate_issues,
        wr_degradation,
        new_candidates
    )
    
    print(f"\nTotal alerts: {total_alerts}")
    print("Sending Telegram message...")
    
    success = send_telegram_message(message)
    if success:
        print("Telegram message sent successfully")
    else:
        print("Failed to send Telegram message")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
