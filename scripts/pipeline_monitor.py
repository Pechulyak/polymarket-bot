#!/usr/bin/env python3
"""Pipeline Monitor — проверка здоровья pipeline с Telegram алертами.

Запуск: python3 scripts/pipeline_monitor.py
Cron: */30 * * * * cd /root/polymarket-bot && python3 scripts/pipeline_monitor.py >> logs/pipeline_monitor.log 2>&1
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
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

LAST_OK_FILE = "/tmp/pipeline_monitor_last_ok"

# Container names from docker-compose.yml
CONTAINERS = [
    "polymarket_bot",
    "polymarket_whale_detector",
    "polymarket_roundtrip_builder",
]

# Logs directory
LOGS_DIR = Path("/root/polymarket-bot/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Database helpers
# =============================================================================

def get_db_connection():
    """Create database connection from DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)


def execute_query(query, params=None):
    """Execute a query and return the result."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchone()[0] if params is None else cur.fetchone()
            return cur.rowcount
    finally:
        conn.close()


# =============================================================================
# Check functions
# =============================================================================

def check_whale_trades_24h():
    """Check whale_trades count in last 24 hours."""
    query = """
        SELECT COUNT(*) FROM whale_trades
        WHERE traded_at > NOW() - INTERVAL '24 hours'
    """
    return execute_query(query)


def check_market_category_null_pct():
    """Check percentage of NULL/empty market_category in last 24 hours."""
    query = """
        SELECT COUNT(*) FILTER (WHERE market_category IS NULL OR market_category = '')
        * 100.0 / NULLIF(COUNT(*), 0)
        FROM whale_trades
        WHERE traded_at > NOW() - INTERVAL '24 hours'
    """
    result = execute_query(query)
    return round(result, 2) if result else 0.0


def check_size_usd_zero():
    """Check count of records with size_usd = 0 in last 24 hours."""
    query = """
        SELECT COUNT(*) FROM whale_trades
        WHERE traded_at > NOW() - INTERVAL '24 hours' AND size_usd = 0
    """
    return execute_query(query)


def check_paper_trades_24h():
    """Check paper_trades count in last 24 hours."""
    query = """
        SELECT COUNT(*) FROM paper_trades
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """
    return execute_query(query)


def check_paper_whales_exist():
    """Check if any whales have copy_status = 'paper'."""
    query = """
        SELECT COUNT(*) FROM whales
        WHERE copy_status = 'paper'
    """
    return execute_query(query)


def check_roundtrips_24h():
    """Check roundtrips count in last 24 hours."""
    query = """
        SELECT COUNT(*) FROM whale_trade_roundtrips
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """
    return execute_query(query)


def check_virtual_trades_1h():
    """Phase 2B: Check VIRTUAL trades count in last 1 hour.
    
    Expected: 0 — если появились VIRTUAL trades, значит VB включили обратно без согласования.
    """
    query = """
        SELECT COUNT(*) FROM trades
        WHERE executed_at > NOW() - INTERVAL '1 hour' AND exchange = 'VIRTUAL'
    """
    return execute_query(query)


def check_container_restarts():
    """Check restart count for each container."""
    restart_counts = {}
    for container in CONTAINERS:
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format={{.RestartCount}}", container],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                restart_counts[container] = int(result.stdout.strip())
            else:
                restart_counts[container] = -1  # Error state
        except Exception as e:
            restart_counts[container] = -1  # Error state
    return restart_counts


def check_market_category_unknown_count():
    """Check count of 'unknown' market_category in last 24 hours."""
    query = """
        SELECT COUNT(*) FILTER (WHERE market_category = 'unknown')
        FROM whale_trades
        WHERE traded_at > NOW() - INTERVAL '24 hours'
    """
    result = execute_query(query)
    return result if result else 0


# =============================================================================
# Telegram alerts
# =============================================================================

def send_telegram_message(message: str):
    """Send message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured - skipping alert")
        return False

    # Convert Markdown emojis to HTML-safe format
    # Replace Markdown bold markers (**text**) with HTML <b>text</b>
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


def load_last_ok_time():
    """Load last OK sent time from file."""
    if Path(LAST_OK_FILE).exists():
        with open(LAST_OK_FILE) as f:
            return datetime.fromisoformat(f.read().strip())
    return None


def save_last_ok_time(dt: datetime):
    """Save last OK sent time to file."""
    with open(LAST_OK_FILE, "w") as f:
        f.write(dt.isoformat())


# =============================================================================
# Pipeline health logging
# =============================================================================

def make_json_safe(obj):
    """Convert values to JSON-serializable types."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(item) for item in obj]
    return obj


def log_pipeline_health(status: str, details: dict):
    """Log pipeline health check to database."""
    # Convert to JSON-safe format
    safe_details = make_json_safe(details)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_health_log (
                    id SERIAL PRIMARY KEY,
                    checked_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    status VARCHAR(20) NOT NULL CHECK (status IN ('OK', 'WARNING', 'CRITICAL')),
                    details JSONB
                )
            """)
            cur.execute("""
                INSERT INTO pipeline_health_log (status, details)
                VALUES (%s, %s)
            """, (status, json.dumps(safe_details)))
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Main check function
# =============================================================================

def run_pipeline_checks():
    """Run all pipeline checks and return results dictionary."""
    results = {
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Check 1: whale_trades/24h
    results["whale_trades_24h"] = check_whale_trades_24h()

    # Check 2: market_category NULL %
    results["market_category_null_pct"] = check_market_category_null_pct()

    # Check 3: size_usd = 0
    results["size_usd_zero"] = check_size_usd_zero()

    # Check 4: paper_trades/24h + paper whales exist
    results["paper_trades_24h"] = check_paper_trades_24h()
    results["paper_whales_exist"] = check_paper_whales_exist()

    # Check 5: roundtrips/24h
    results["roundtrips_24h"] = check_roundtrips_24h()

    # Check 6: container restarts
    results["container_restarts"] = check_container_restarts()

    # Check 7: market_category unknown %
    results["market_category_unknown_count"] = check_market_category_unknown_count()

    # Determine status based on results
    status, warnings, criticals = determine_status(results)
    results["status"] = status
    results["warnings"] = warnings
    results["criticals"] = criticals

    return results


def determine_status(results: dict) -> tuple:
    """Determine overall pipeline status based on check results."""
    warnings = []
    criticals = []

    # Check 1: whale_trades/24h (WARNING: < 50, CRITICAL: 0)
    wt_24h = results.get("whale_trades_24h", 0)
    if wt_24h == 0:
        criticals.append(f"whale_trades/24h: 0 (CRITICAL)")
    elif wt_24h < 50:
        warnings.append(f"whale_trades/24h: {wt_24h} (< 50)")

    # Check 2: market_category NULL % (WARNING: > 5%)
    null_pct = results.get("market_category_null_pct", 0)
    if null_pct > 5:
        warnings.append(f"market_category NULL: {null_pct:.1f}% (> 5%)")

    # Check 3: size_usd = 0 (CRITICAL: > 0)
    szero = results.get("size_usd_zero", 0)
    if szero > 0:
        criticals.append(f"size_usd=0 found: {szero} records (CRITICAL)")

    # Check 4: paper_trades/24h (WARNING: 0 when paper whales exist)
    pt_24h = results.get("paper_trades_24h", 0)
    pw_exists = results.get("paper_whales_exist", 0)
    if pw_exists > 0 and pt_24h == 0:
        warnings.append(f"paper_trades/24h: 0 (paper whales: {pw_exists})")

    # Check 5: roundtrips/24h (WARNING: 0 new)
    rt_24h = results.get("roundtrips_24h", 0)
    if rt_24h == 0:
        warnings.append(f"roundtrips/24h: 0 new")

    # Check 6: container restarts (CRITICAL: > 3)
    restarts = results.get("container_restarts", {})
    for container, count in restarts.items():
        if count > 3:
            criticals.append(f"{container} restart_count: {count} (CRITICAL)")

    # Check 7: market_category unknown count — INFO only
    # Ожидаемо 1523+ без категоризации, пока background task не починен
    # Не учитывать при определении статуса
    # unknown_count = results.get("market_category_unknown_count", 0)

    if criticals:
        return "CRITICAL", warnings, criticals
    elif warnings:
        return "WARNING", warnings, criticals
    else:
        return "OK", warnings, criticals


def format_ok_message(results: dict) -> str:
    """Format OK message."""
    restarts = results.get("container_restarts", {})
    container_status = "all healthy"
    for container, count in restarts.items():
        if count > 0:
            container_status = f"{container}: {count} restarts"
            break

    return f"""✅ Pipeline OK | {results['timestamp']}

whale_trades/24h: {results['whale_trades_24h']}
paper_trades/24h: {results['paper_trades_24h']}
roundtrips/24h: {results['roundtrips_24h']}
category_unknown: {results['market_category_unknown_count']}
containers: {container_status}
"""


def format_warning_message(results: dict, warnings: list, criticals: list) -> str:
    """Format WARNING message."""
    lines = ["⚠️ Pipeline WARNING | " + results["timestamp"], ""]

    for w in warnings:
        if "<" in w or "(" in w:
            lines.append("🔴 " + w)
        else:
            lines.append("🟡 " + w)

    lines.append("")
    lines.append("Action needed: check whale-detector logs")

    return "\n".join(lines)


def format_critical_message(results: dict, warnings: list, criticals: list) -> str:
    """Format CRITICAL message."""
    lines = ["🚨 Pipeline CRITICAL | " + results["timestamp"], ""]

    for c in criticals:
        lines.append("🔴 " + c)

    lines.append("")
    lines.append("IMMEDIATE ACTION REQUIRED")

    return "\n".join(lines)


# =============================================================================
# Main entry point
# =============================================================================

def main():
    """Main entry point."""
    print(f"[{datetime.now().isoformat()}] Running pipeline checks...")

    try:
        results = run_pipeline_checks()
        status = results["status"]
        warnings = results.get("warnings", [])
        criticals = results.get("criticals", [])

        # Format message based on status
        if status == "OK":
            message = format_ok_message(results)
        elif status == "WARNING":
            message = format_warning_message(results, warnings, criticals)
        else:
            message = format_critical_message(results, warnings, criticals)

        print(f"Status: {status}")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"  - {w}")
        if criticals:
            print("Critical:")
            for c in criticals:
                print(f"  - {c}")

        # Send logic
        if status == "OK":
            last_ok = load_last_ok_time()
            now = datetime.utcnow()

            if last_ok is None or (now - last_ok).total_seconds() > 6 * 3600:
                success = send_telegram_message(message)
                if success:
                    save_last_ok_time(now)
                    print("OK message sent to Telegram")
                else:
                    print("Failed to send OK message")
            else:
                hours_since_last_ok = (now - last_ok).total_seconds() / 3600
                print(f"OK, skip telegram (last OK sent {hours_since_last_ok:.1f}h ago)")
        else:
            # WARNING/CRITICAL - always send
            success = send_telegram_message(message)
            if success:
                print(f"{status} alert sent to Telegram")
            else:
                print(f"Failed to send {status} alert")

        # Log to database
        log_pipeline_health(status, results)

        # Exit with appropriate code
        if status == "CRITICAL":
            sys.exit(2)
        elif status == "WARNING":
            sys.exit(1)
        else:
            sys.exit(0)

    except Exception as e:
        print(f"Error running pipeline checks: {e}")
        error_message = f"""🚨 Pipeline ERROR | {datetime.utcnow().isoformat()}

Error: {e}

IMMEDIATE ACTION REQUIRED
"""
        send_telegram_message(error_message)
        sys.exit(3)


if __name__ == "__main__":
    main()