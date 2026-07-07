#!/usr/bin/env python3
"""
FARM-022 К3: Farm Screen Digest — отправляет в Telegram топ-5 кандидатов
из последнего сканирования farming_market_candidates с дельтой к предыдущему.

Два последних scan_run_id (по MIN(scanned_at)):
  - если прогон один — дайджест без дельт, пометка «первый прогон»
  - top-5 по our_daily_usd: question, our_daily_usd, дельта, NEW, fees flag
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psycopg2
except ImportError:
    print("psycopg2 not installed")
    sys.exit(1)


# =============================================================================
# Config — read from env, fallback to .env file on host
# =============================================================================

def _parse_env_file():
    """Parse /root/polymarket-bot/.env, return dict of KEY=value (strings)."""
    env_path = Path("/root/polymarket-bot/.env")
    if not env_path.exists():
        return {}
    vals = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals

_env_file = _parse_env_file()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN") or _env_file.get("TELEGRAM_ALERT_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or _env_file.get("TELEGRAM_CHAT_ID")
DATABASE_URL = os.environ.get("DATABASE_URL") or _env_file.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5433/polymarket"
)


# =============================================================================
# DB helpers
# =============================================================================

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# =============================================================================
# Telegram
# =============================================================================

def send_telegram_message(message: str) -> bool:
    """Send message via Telegram bot (HTML parse_mode)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured - skipping")
        return False

    import urllib.request
    import urllib.parse
    import urllib.error

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
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


# =============================================================================
# Digest logic
# =============================================================================

def truncate_question(q: str, max_len: int = 50) -> str:
    """Truncate question to max_len chars, add … if longer."""
    if not q:
        return "(empty)"
    q = q.strip()
    if len(q) > max_len:
        return q[:max_len].rstrip() + "…"
    return q


def build_digest() -> str:
    """Build digest message string."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Two latest scan_runs by MIN(scanned_at)
            cur.execute("""
                SELECT scan_run_id, MIN(scanned_at) as first_scan,
                       COUNT(*) as row_count
                FROM farming_market_candidates
                GROUP BY scan_run_id
                ORDER BY first_scan DESC
                LIMIT 2
            """)
            runs = cur.fetchall()
    finally:
        conn.close()

    if not runs:
        return "📭 Farm Screen: нет данных в farming_market_candidates"

    latest_run_id = runs[0][0]
    prev_run_id = runs[1][0] if len(runs) > 1 else None

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Top-5 of latest run
            cur.execute("""
                SELECT gamma_id, question, our_daily_usd, fees_enabled,
                       neg_risk, tick, moves2c
                FROM farming_market_candidates
                WHERE scan_run_id = %s
                ORDER BY our_daily_usd DESC NULLS LAST
                LIMIT 5
            """, (latest_run_id,))
            latest_rows = cur.fetchall()

            if prev_run_id:
                # Previous run data keyed by gamma_id
                cur.execute("""
                    SELECT gamma_id, our_daily_usd
                    FROM farming_market_candidates
                    WHERE scan_run_id = %s
                """, (prev_run_id,))
                prev_by_gamma = {str(r[0]): r[1] for r in cur.fetchall()}
            else:
                prev_by_gamma = {}
    finally:
        conn.close()

    # Build message
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"🖥 <b>Farm Screen Digest</b> — {timestamp}"]

    if not prev_run_id:
        lines.append("<i>(первый прогон — дельты недоступны)</i>")

    lines.append("")
    lines.append(f"<b>Top-5 by our_daily_usd</b> (run: {latest_run_id[:8]}…)")

    for i, row in enumerate(latest_rows, 1):
        gamma_id, question, our_daily, fees_en, neg_risk, tick, moves2c = row

        q_short = truncate_question(question or "")
        our_val = float(our_daily) if our_daily else 0.0

        fees_flag = "💰" if fees_en else "—"
        neg_flag = "NR" if neg_risk else ""

        # Delta vs previous run
        prev_val = prev_by_gamma.get(str(gamma_id))
        if prev_run_id:
            if prev_val is not None:
                prev_f = float(prev_val)
                delta = our_val - prev_f
                if abs(delta) < 0.001:
                    delta_str = "≈0"
                elif delta > 0:
                    delta_str = f"+{delta:.2f}"
                else:
                    delta_str = f"{delta:.2f}"
                delta_line = f"  ({prev_f:.2f} → {our_val:.2f}, {delta_str})"
            else:
                delta_line = "  <i>(NEW)</i>"
        else:
            delta_line = ""

        flags = " ".join(x for x in [fees_flag, neg_flag] if x)
        lines.append(f"{i}. {q_short}")
        lines.append(f"   our_daily=${our_val:.2f}{delta_line} {flags}")

    msg = "\n".join(lines)
    return msg


def main():
    print("[digest] Building farm screen digest…")
    msg = build_digest()
    print(f"[digest] Message:\n{msg}\n")
    ok = send_telegram_message(msg)
    if ok:
        print("[digest] Telegram OK")
    else:
        print("[digest] Telegram FAILED (or not configured)")


if __name__ == "__main__":
    main()
