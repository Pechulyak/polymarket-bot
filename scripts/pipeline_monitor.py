#!/usr/bin/env python3
"""Pipeline Monitor — проверка здоровья pipeline с Telegram алертами.

Запуск: python3 scripts/pipeline_monitor.py
Cron: */30 * * * * cd /root/polymarket-bot && python3 scripts/pipeline_monitor.py >> logs/pipeline_monitor.log 2>&1
"""
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
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

# Heartbeat thresholds
HEARTBEAT_STALE_SECONDS = 120

# INFRA-046 / INFRA-048: live_copy_daemon heartbeat threshold
DAEMON_HEARTBEAT_STALE_SECONDS = 180

# INFRA-047: stuck orders threshold
STUCK_ORDER_SECONDS = 120

# INFRA-051: cron canary heartbeat threshold (file touched by */5 cron)
CRON_HEARTBEAT_STALE_SECONDS = 900

# INFRA-051: canonical crontab reference file (mirrors live `crontab -l`)
CRONTAB_REFERENCE_FILE = "/root/polymarket-bot/docs/crontab.reference"

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


def check_whale_trades_write_freshness():
    """INFRA-039: возраст последней ЗАПИСИ в whale_trades (inserted_at).
    Ловит остановку записи независимо от рыночной активности.
    NULL (нет ни одной новой записи после миграции) → не алертить."""
    age_min = execute_query(
        "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(inserted_at)))/60 FROM whale_trades"
    )
    if age_min is None:
        return {"value": None, "status": "info", "reason": "no inserted_at rows yet"}
    age_min = float(age_min)
    if age_min > 45:
        status = "critical"
    elif age_min > 35:
        status = "warning"
    else:
        status = "ok"
    return {"value": round(age_min, 1), "status": status, "reason": f"write_age={round(age_min,1)}min"}


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


def check_close_sell_last_run_age():
    """Check age of last close_sell START entry from log (not SQL MAX(closed_at)).
    
    Uses _parse_close_sell_log_entries() helper — parses close_sell_cron.log.
    Finds MAX(START_TS) among all entries in file (not filtered by window).
    If log file absent or no START entries → CRITICAL.
    
    Thresholds (after FIX-1 calibration):
    OK: <= 150 minutes
    WARNING: <= 240 minutes
    CRITICAL: > 240 minutes
    """
    entries, err, _, _ = _parse_close_sell_log_entries(window_hours=24)
    if err:
        return None  # File missing — CRITICAL, handled by determine_status
    
    # Find all START entries across entire file (unfiltered for bootstrap)
    # Re-read without window filter to get MAX(START) regardless of age
    if not os.path.exists(LOG_FILE):
        return None
    
    start_entries = []
    with open(LOG_FILE, 'r') as f:
        for line in f:
            m = re.match(_LOG_PATTERN, line)
            if m and m.group(2) == "START":
                ts_str = m.group(1)
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                start_entries.append(ts)
    
    if not start_entries:
        return None  # No START entries ever — CRITICAL
    
    last_start = max(start_entries)
    age_min = (datetime.utcnow() - last_start).total_seconds() / 60
    return round(age_min, 1)


# =============================================================================
# Close-sell log parsing helpers
# =============================================================================

LOG_FILE = "/root/polymarket-bot/logs/close_sell_cron.log"
# Regex: [run_close_sell] 2026-05-19 11:40:21 — START/DONE (exit N)
_LOG_PATTERN = r'\[run_close_sell\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) — (START|DONE)(?: \(exit (\d+)\))?'

RETENTION_LOG_FILE = "/root/polymarket-bot/logs/retention_cron.log"
_RETENTION_LOG_PREFIX = "[run_retention]"


def _parse_close_sell_log_entries(window_hours=24):
    """Parse close_sell log and return list of {ts, type, exit_code} for last window_hours.
    
    Returns (entries, error_msg):
      - entries: list of dicts sorted by ts ascending
      - error_msg: None on success, string on error (file missing etc.)
    
    Bootstrap info: also returns (earliest_ts, latest_ts) for bootstrap guards.
    """
    if not os.path.exists(LOG_FILE):
        return None, f"Log file not found: {LOG_FILE}", None, None
    
    entries = []
    earliest_ts = None
    latest_ts = None
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    
    try:
        with open(LOG_FILE, 'r') as f:
            for line in f:
                m = re.match(_LOG_PATTERN, line)
                if not m:
                    continue
                ts_str, entry_type, exit_code = m.groups()
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                # Filter by window only for DONE entries used in checks
                if ts >= cutoff:
                    entries.append({
                        "ts": ts,
                        "type": entry_type,
                        "exit_code": int(exit_code) if exit_code is not None else None
                    })
    except Exception as e:
        return None, f"Error reading log: {e}", None, None
    
    # Sort by ts ascending
    entries.sort(key=lambda x: x["ts"])
    return entries, None, earliest_ts, latest_ts


def check_close_sell_runs_24h():
    """Count DONE (exit N) entries in last 24h from log.
    
    OK: >= 22 runs
    WARNING: 18-21 runs
    CRITICAL: < 18 runs
    Bootstrap guard: if earliest START in file < 24h ago — INFO (not WARN/CRITICAL)
    If log file absent — CRITICAL
    """
    entries, err, earliest_ts, latest_ts = _parse_close_sell_log_entries(window_hours=24)
    if err:
        # File missing
        return {"value": None, "status": "critical", "reason": err}
    
    done_count = sum(1 for e in entries if e["type"] == "DONE")
    
    # Bootstrap: if earliest START < 24h ago, we're in bootstrap
    now = datetime.utcnow()
    if earliest_ts is not None and (now - earliest_ts).total_seconds() < 86400:
        return {"value": done_count, "status": "info", "reason": "bootstrap"}
    
    if done_count >= 22:
        status = "ok"
    elif done_count >= 18:
        status = "warning"
    else:
        status = "critical"
    
    return {"value": done_count, "status": status}


def check_close_sell_exit_codes_24h():
    """Count DONE entries with non-zero exit code in last 24h.
    
    OK: 0 failures
    CRITICAL: >= 1 failures
    If log file absent — CRITICAL
    """
    entries, err, _, _ = _parse_close_sell_log_entries(window_hours=24)
    if err:
        return {"value": None, "status": "critical", "reason": err}
    
    failures = sum(1 for e in entries if e["type"] == "DONE" and e["exit_code"] != 0)
    return {"value": failures, "status": "critical" if failures > 0 else "ok"}


def check_close_sell_duration_p95_24h():
    """Check close_sell duration based on recent runs.

    Logic: CRITICAL if last run > 1800s OR >=2 of last 5 runs > 1800s.
           WARNING  if last run > 1200s OR >=2 of last 5 runs > 1200s.
           Bootstrap: < 2 runs available → INFO.
    If log file absent → CRITICAL.
    """
    entries, err, _, _ = _parse_close_sell_log_entries(window_hours=24)
    if err:
        return {"value": None, "status": "critical", "reason": err}

    # Build durations list from START→DONE pairs, chronological
    durations = []
    starts = {}
    for e in entries:
        if e["type"] == "START":
            starts[e["ts"]] = e["ts"]
        elif e["type"] == "DONE":
            matching = [s for s in starts if s <= e["ts"]]
            if matching:
                best_start = max(matching)
                dur = (e["ts"] - best_start).total_seconds()
                durations.append(dur)

    if len(durations) < 2:
        return {"value": None, "status": "info",
                "reason": f"only {len(durations)} runs"}

    last = durations[-1]
    last5 = durations[-5:]

    # Track max value that exceeded each threshold (for alert message)
    max_over_1800 = max((d for d in last5 if d > 1800), default=None)
    max_over_1200 = max((d for d in last5 if d > 1200), default=None)

    # Count runs exceeding thresholds
    over_1800 = sum(1 for d in last5 if d > 1800)
    over_1200 = sum(1 for d in last5 if d > 1200)

    # CRITICAL: current run exceeds 1800s OR >=2 of last 5 runs > 1800s
    # WARNING: current run exceeds 1200s OR >=2 of last 5 runs > 1200s
    if last > 1800 or over_1800 >= 2:
        status = "critical"
        alert_value = max_over_1800 if max_over_1800 else last
    elif last > 1200 or over_1200 >= 2:
        status = "warning"
        alert_value = max_over_1200 if max_over_1200 else last
    else:
        status = "ok"
        alert_value = None

    return {"value": round(last, 1), "status": status,
            "alert_value": round(alert_value, 1) if alert_value else None,
            "last5_max": round(max(last5), 1)}


def check_retention_cron_last_run_age():
    """Check age of last retention_cron log entry (START or DONE).

    Log format: [run_retention] 2026-06-04 04:00:01 — START/DONE
    Threshold: 25 hours (retention runs at 04:00 daily, monitor runs every 30 min).
    If file absent or no entries → CRITICAL.
    If file has ERROR in last entry → WARNING (not CRITICAL, unlike close_sell).
    """
    if not os.path.exists(RETENTION_LOG_FILE):
        return None  # CRITICAL — handled by determine_status

    try:
        mtime = os.path.getmtime(RETENTION_LOG_FILE)
        age_seconds = time.time() - mtime
        age_hours = age_seconds / 3600

        if age_hours > 25:
            return round(age_hours, 1)  # ALERT

        # Check last entry for ERROR
        with open(RETENTION_LOG_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                if 'ERROR' in last_line:
                    return None  # WARNING handled separately
        return None  # OK
    except Exception:
        return None  # CRITICAL on error


def check_retention_cron_error():
    """Check for ERROR in last entry of retention_cron.log.

    WARNING if ERROR found, OK otherwise.
    File absent → OK (cron just hasn't run yet, not an error).
    """
    if not os.path.exists(RETENTION_LOG_FILE):
        return False

    try:
        with open(RETENTION_LOG_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                return 'ERROR' in last_line
        return False
    except Exception:
        return False  # Error reading file — skip, don't alert


# =============================================================================
# FARM-022 К2: farm degradation watch
# =============================================================================

CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0"}


def _http_get(url, timeout=10):
    """Simple GET with UA, returns dict or None on error."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _get_clob_market(condition_id):
    """Fetch CLOB /markets/{condition_id}, return (pool, max_spread, end_date_iso, neg_risk)."""
    d = _http_get(f"{CLOB_API}/markets/{condition_id}")
    if not d:
        return None
    rewards = d.get("rewards") or {}
    rates = rewards.get("rates") or []
    pool = sum(float(x.get("rewards_daily_rate", 0)) for x in rates)
    return {
        "pool": pool,
        "max_spread": rewards.get("max_spread"),
        "end_date_iso": d.get("end_date_iso"),
        "neg_risk": d.get("neg_risk"),
    }


def _get_gamma_fees(gamma_id):
    """Fetch Gamma /markets/{gamma_id}, return feesEnabled or None."""
    d = _http_get(f"{GAMMA_API}/markets/{gamma_id}")
    if not d:
        return None
    return d.get("feesEnabled")


def check_farm_degradation(results: dict):
    """
    Edge-triggered degradation watch for farming_active_markets status=active.
    Проверяет: pool=0/снижен>30%, max_spread≠baseline, feesEnabled false→true, days_to_end<14.
    Component в system_state: farm_degradation_{gamma_id}.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, token_id, condition_id, gamma_id, name,
                       pool_baseline, max_spread_baseline, fees_enabled_baseline,
                       neg_risk_baseline, end_date_baseline
                FROM farming_active_markets
                WHERE status = 'active'
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return

    degradation_events = []

    for row in rows:
        (mkt_id, token_id, condition_id, gamma_id, name,
         pool_bl, ms_bl, fees_bl, nr_bl, end_bl) = row

        # CLOB: pool, max_spread, end_date
        clob = _get_clob_market(condition_id)
        if clob is None:
            print(f"[WARN] farm_degradation: CLOB failed for {name}")
            continue

        pool_cur = clob["pool"]
        ms_cur = clob["max_spread"]
        end_date_iso = clob["end_date_iso"]

        # Gamma: feesEnabled
        fees_cur = _get_gamma_fees(gamma_id)
        if fees_cur is None:
            print(f"[WARN] farm_degradation: Gamma failed for {name}")
            continue

        # Compute current degraded conditions set (static names for state)
        # condition_details: name → human-readable detail for alert text
        condition_names = set()
        condition_details = {}

        # pool = 0 or dropped >30% from baseline
        pool_bl_f = float(pool_bl) if pool_bl else 0.0
        if pool_cur == 0:
            condition_names.add("pool_zero")
            condition_details["pool_zero"] = f"pool: {pool_bl_f:.1f} → 0 (zero)"
        elif pool_bl_f > 0 and pool_cur < pool_bl_f * 0.7:
            drop_pct = round((1 - pool_cur / pool_bl_f) * 100)
            condition_names.add("pool_dropped")
            condition_details["pool_dropped"] = f"pool: {pool_bl_f:.1f} → {pool_cur:.1f} (−{drop_pct}%)"

        # max_spread changed
        ms_bl_f = float(ms_bl) if ms_bl else None
        if ms_cur != ms_bl_f:
            condition_names.add("max_spread_changed")
            condition_details["max_spread_changed"] = (
                f"max_spread: {ms_bl_f} → {ms_cur}"
                if ms_bl_f is not None else f"max_spread: none → {ms_cur}"
            )

        # feesEnabled: false→true vs baseline
        if fees_cur is True and fees_bl is False:
            condition_names.add("fees_enabled_true")
            condition_details["fees_enabled_true"] = "feesEnabled: false → true (rebate ON)"

        # days_to_end < 14
        if end_date_iso:
            try:
                end_dt = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
                days_left = (end_dt.date() - datetime.utcnow().date()).days
                if days_left < 14:
                    condition_names.add("days_to_end_low")
                    condition_details["days_to_end_low"] = f"days_to_end: {days_left} (<14)"
            except Exception:
                pass

        # Build current state string (sorted for deterministic comparison)
        current_state = "|".join(sorted(condition_names)) if condition_names else "OK"

        # Read previous state from system_state
        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "SELECT status FROM system_state WHERE component = %s",
                    (f"farm_degradation_{gamma_id}",)
                )
                row2 = cur.fetchone()
                prev_state = row2[0] if row2 else None
                if prev_state is None:
                    prev_state = "INIT"
        finally:
            conn2.close()

        # Edge-triggered: alert only on state change
        if current_state != prev_state:
            if current_state == "OK":
                msg = f"✅ Фарм-деградация восстановлена: {name}"
                send_telegram_message(msg)
            elif prev_state == "INIT":
                msg = f"ℹ️ Фарм-деградация инициализирована: {name} → [{current_state}]"
                send_telegram_message(msg)
            else:
                # Describe what changed (use condition_details for full text)
                prev_set = set(prev_state.split("|")) if prev_state else set()
                changed = condition_names - prev_set
                recovered = prev_set - condition_names
                lines = []
                if changed:
                    lines.append(f"⚠️ {name}:")
                    for c in sorted(changed):
                        detail = condition_details.get(c, c)
                        lines.append(f"  • {detail}")
                if recovered:
                    lines.append(f"✅ Восстановлен: {name}")
                    for c in sorted(recovered):
                        lines.append(f"  • {c}")
                if lines:
                    send_telegram_message("\n".join(lines))

            # Persist new state
            conn3 = get_db_connection()
            try:
                with conn3.cursor() as cur:
                    cur.execute(
                        "INSERT INTO system_state (component, status, heartbeat_at, updated_at) "
                        "VALUES (%s, %s, NOW(), NOW()) "
                        "ON CONFLICT (component) DO UPDATE SET "
                        "status = EXCLUDED.status, heartbeat_at = EXCLUDED.heartbeat_at, updated_at = EXCLUDED.updated_at",
                        (f"farm_degradation_{gamma_id}", current_state)
                    )
                conn3.commit()
            finally:
                conn3.close()

            degradation_events.append({
                "name": name, "gamma_id": gamma_id,
                "prev": prev_state, "current": current_state
            })

    results["farm_degradation"] = {
        "checked": len(rows),
        "events": degradation_events,
    }


def check_retention_deleted_count():
    """Parse last 'Total deleted' count from retention_cron.log.

    Returns integer from RAISE NOTICE 'Total deleted: %' or None if not found.
    """
    if not os.path.exists(RETENTION_LOG_FILE):
        return None

    try:
        with open(RETENTION_LOG_FILE, 'r') as f:
            content = f.read()
        # Look for "Total deleted: N" in the log
        matches = re.findall(r'Total deleted:\s*(\d+)', content)
        if matches:
            return int(matches[-1])  # last occurrence
        return None
    except Exception:
        return None


# =============================================================================
# Live executor heartbeat check (INFRA-046)
# =============================================================================

def check_live_executor_heartbeat():
    """Edge-triggered: only alert on state transitions."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Read age in seconds (DB-side, avoids naive/aware conflict)
            cur.execute("""
                SELECT EXTRACT(EPOCH FROM (now() - heartbeat_at))
                FROM system_state
                WHERE component = 'live_executor'
            """)
            row = cur.fetchone()
            if row is None or row[0] is None:
                current_state = "stale"
                heartbeat_age_sec = None
            else:
                heartbeat_age_sec = round(float(row[0]), 1)
                current_state = "stale" if heartbeat_age_sec > HEARTBEAT_STALE_SECONDS else "ok"

            # Read last alerted state
            cur.execute("""
                SELECT status FROM system_state
                WHERE component = 'live_executor_alert_state'
            """)
            alert_row = cur.fetchone()
            last_alerted = alert_row[0] if alert_row else None

            # First run: missing alert_state → treat as ok (no spurious recovered)
            if last_alerted is None:
                last_alerted = "ok"

            # State transition
            if current_state != last_alerted:
                if current_state == "stale":
                    msg = f"🚨 live_executor heartbeat STALE (age={heartbeat_age_sec}s)"
                    send_telegram_message(msg)
                    new_alert_state = "stale"
                else:
                    send_telegram_message("✅ live_executor recovered")
                    new_alert_state = "ok"

                cur.execute("""
                    INSERT INTO system_state (component, status, heartbeat_at, updated_at)
                    VALUES ('live_executor_alert_state', %s, NOW(), NOW())
                    ON CONFLICT (component) DO UPDATE SET
                        status = EXCLUDED.status,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = EXCLUDED.updated_at
                """, (new_alert_state,))
                conn.commit()
    except Exception as e:
        print(f"[WARN] live_executor heartbeat check failed: {e}")
    finally:
        conn.close()


# =============================================================================
# INFRA-048: watchdog live_copy_daemon (edge-trigger)
# =============================================================================

def check_live_copy_daemon_heartbeat():
    """Edge-triggered: only alert on state transitions."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Read age in seconds (DB-side, avoids naive/aware conflict)
            cur.execute("""
                SELECT EXTRACT(EPOCH FROM (now() - heartbeat_at))
                FROM system_state
                WHERE component = 'live_copy_daemon'
            """)
            row = cur.fetchone()
            if row is None or row[0] is None:
                current_state = "stale"
                heartbeat_age_sec = None
            else:
                heartbeat_age_sec = round(float(row[0]), 1)
                current_state = "stale" if heartbeat_age_sec > DAEMON_HEARTBEAT_STALE_SECONDS else "ok"

            # Read last alerted state
            cur.execute("""
                SELECT status FROM system_state
                WHERE component = 'live_copy_daemon_alert_state'
            """)
            alert_row = cur.fetchone()
            last_alerted = alert_row[0] if alert_row else None

            # First run: missing alert_state → treat as ok (no spurious recovered)
            if last_alerted is None:
                last_alerted = "ok"

            # State transition
            if current_state != last_alerted:
                if current_state == "stale":
                    msg = f"🚨 live_copy_daemon heartbeat STALE (age={heartbeat_age_sec}s)"
                    send_telegram_message(msg)
                    new_alert_state = "stale"
                else:
                    send_telegram_message("✅ live_copy_daemon recovered")
                    new_alert_state = "ok"

                cur.execute("""
                    INSERT INTO system_state (component, status, heartbeat_at, updated_at)
                    VALUES ('live_copy_daemon_alert_state', %s, NOW(), NOW())
                    ON CONFLICT (component) DO UPDATE SET
                        status = EXCLUDED.status,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = EXCLUDED.updated_at
                """, (new_alert_state,))
                conn.commit()
    except Exception as e:
        print(f"[WARN] live_copy_daemon heartbeat check failed: {e}")
    finally:
        conn.close()


# =============================================================================
# INFRA-047: watchdog застрявших ордеров (edge-trigger)
# =============================================================================

def check_stuck_orders():
    """Edge-triggered: only alert on state transitions.
    
    Алертит при переходе clear→stuck, восстановлении stuck→clear.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Найти застрявшие ордера (статусы intent/claimed/submitted, старше порога)
            cur.execute("""
                SELECT id, status, EXTRACT(EPOCH FROM (now() - COALESCE(updated_at, created_at))) AS age_sec
                FROM live_orders
                WHERE status IN ('intent', 'claimed', 'submitted')
                  AND EXTRACT(EPOCH FROM (now() - COALESCE(updated_at, created_at))) > %s
                ORDER BY age_sec DESC
            """, (STUCK_ORDER_SECONDS,))
            rows = cur.fetchall()
            current_state = 'stuck' if rows else 'clear'

            # Прочитать last-alerted из system_state
            cur.execute("""
                SELECT status FROM system_state WHERE component = 'stuck_orders_alert_state'
            """)
            alert_row = cur.fetchone()
            last_alerted = alert_row[0] if alert_row else None
            if last_alerted is None:
                last_alerted = 'clear'

            # Edge-trigger: только при смене состояния
            if current_state != last_alerted:
                if current_state == 'stuck':
                    order_lines = '\n'.join(
                        f"  id={row[0]} status={row[1]} age={round(float(row[2]), 1)}s"
                        for row in rows
                    )
                    msg = f"🚨 {len(rows)} stuck orders (>{STUCK_ORDER_SECONDS}s)\n{order_lines}"
                    send_telegram_message(msg)
                    detail_json = json.dumps([row[0] for row in rows])
                    new_alert_state = 'stuck'
                else:
                    send_telegram_message("✅ stuck orders cleared")
                    new_alert_state = 'clear'
                    detail_json = None

                cur.execute("""
                    INSERT INTO system_state (component, status, detail, heartbeat_at, updated_at)
                    VALUES ('stuck_orders_alert_state', %s, %s, NOW(), NOW())
                    ON CONFLICT (component) DO UPDATE SET
                        status = EXCLUDED.status,
                        detail = EXCLUDED.detail,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = EXCLUDED.updated_at
                """, (new_alert_state, detail_json))
                conn.commit()
    except Exception as e:
        print(f"[WARN] check_stuck_orders failed: {e}")
    finally:
        conn.close()


# =============================================================================
# INFRA-051: cron aliveness — canary heartbeat (file mtime) + crontab drift
# =============================================================================

CRON_HEARTBEAT_FILE = "/root/polymarket-bot/logs/cron_heartbeat"


def check_cron_heartbeat():
    """INFRA-051: edge-triggered — cron canary heartbeat freshness.

    Источник: mtime файла logs/cron_heartbeat (touched by `*/5 * * * *` cron).
    Не БД. Если файла нет — stale (age=None).
    DB используется только для alert-state (cron_heartbeat_alert_state).
    """
    # Read mtime outside DB (file source-of-truth)
    try:
        mtime = os.path.getmtime(CRON_HEARTBEAT_FILE)
        heartbeat_age_sec = round(time.time() - mtime, 1)
    except (FileNotFoundError, OSError):
        heartbeat_age_sec = None

    current_state = "stale" if heartbeat_age_sec is None else (
        "stale" if heartbeat_age_sec > CRON_HEARTBEAT_STALE_SECONDS else "ok"
    )

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Read last alerted state
            cur.execute("""
                SELECT status FROM system_state
                WHERE component = 'cron_heartbeat_alert_state'
            """)
            alert_row = cur.fetchone()
            last_alerted = alert_row[0] if alert_row else None

            # First run: missing alert_state → treat as ok (no spurious recovered)
            if last_alerted is None:
                last_alerted = "ok"

            # Edge-trigger: only alert on state transition
            if current_state != last_alerted:
                if current_state == "stale":
                    age_repr = f"{heartbeat_age_sec}s" if heartbeat_age_sec is not None else "missing"
                    msg = f"🚨 cron heartbeat STALE (age={age_repr}) — */5 touch-строка не отрабатывает (crond целиком мёртв, либо сломана эта запись; сам этот чек требует живого crond, поэтому полная смерть crond не гарантированно поймается)"
                    send_telegram_message(msg)
                    new_alert_state = "stale"
                else:
                    send_telegram_message("✅ cron heartbeat recovered")
                    new_alert_state = "ok"

                cur.execute("""
                    INSERT INTO system_state (component, status, heartbeat_at, updated_at)
                    VALUES ('cron_heartbeat_alert_state', %s, NOW(), NOW())
                    ON CONFLICT (component) DO UPDATE SET
                        status = EXCLUDED.status,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = EXCLUDED.updated_at
                """, (new_alert_state,))
                conn.commit()
    except Exception as e:
        print(f"[WARN] cron heartbeat check failed: {e}")
    finally:
        conn.close()


def check_crontab_drift():
    """INFRA-051: edge-triggered — drift между `crontab -l` и docs/crontab.reference.

    Сравнение построчно: .strip() на каждой строке, отброс пустых строк с обеих сторон.
    Если crontab -l падает (returncode != 0) — drift, в detail пишем stderr.
    Alert-state компонент: crontab_drift_alert_state.
    """
    # 1. Получить живой crontab
    live_lines = []
    crontab_stderr = None
    crontab_ok = True
    try:
        result = subprocess.run(
            ["/usr/bin/crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            crontab_ok = False
            crontab_stderr = result.stderr.strip()[:500]
        else:
            live_lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except Exception as e:
        crontab_ok = False
        crontab_stderr = f"subprocess exception: {type(e).__name__}: {e}"

    # 2. Прочитать reference
    ref_lines = []
    ref_error = None
    try:
        with open(CRONTAB_REFERENCE_FILE, "r") as f:
            ref_lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        ref_error = f"reference file missing: {CRONTAB_REFERENCE_FILE}"
    except Exception as e:
        ref_error = f"reference read error: {type(e).__name__}: {e}"

    # 3. Сравнить
    current_state = "ok"
    diff_text = ""
    detail_payload = None

    if not crontab_ok:
        current_state = "drift"
        diff_text = f"crontab -l failed: {crontab_stderr or 'unknown error'}"
        detail_payload = {"diff": diff_text[:2000]}
    elif ref_error:
        current_state = "drift"
        diff_text = f"reference error: {ref_error}"
        detail_payload = {"diff": diff_text[:2000]}
    elif live_lines != ref_lines:
        current_state = "drift"
        # Unified diff, обрезанный до ~20 строк вывода
        diff_iter = difflib.unified_diff(
            ref_lines,
            live_lines,
            fromfile="docs/crontab.reference",
            tofile="crontab -l",
            lineterm="",
        )
        diff_lines = list(diff_iter)
        diff_text = "\n".join(diff_lines[:20])
        if len(diff_lines) > 20:
            diff_text += f"\n... ({len(diff_lines) - 20} more lines truncated)"
        detail_payload = {"diff": diff_text[:2000]}

    # 4. Edge-trigger
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status FROM system_state
                WHERE component = 'crontab_drift_alert_state'
            """)
            alert_row = cur.fetchone()
            last_alerted = alert_row[0] if alert_row else None

            # First run: missing alert_state → treat as ok
            if last_alerted is None:
                last_alerted = "ok"

            if current_state != last_alerted:
                if current_state == "drift":
                    msg = f"🚨 crontab DRIFT: живой crontab разошёлся с docs/crontab.reference\n{diff_text}"
                    send_telegram_message(msg)
                    new_alert_state = "drift"
                else:
                    send_telegram_message("✅ crontab drift resolved")
                    new_alert_state = "ok"
                    detail_payload = None

                cur.execute("""
                    INSERT INTO system_state (component, status, detail, heartbeat_at, updated_at)
                    VALUES ('crontab_drift_alert_state', %s, %s, NOW(), NOW())
                    ON CONFLICT (component) DO UPDATE SET
                        status = EXCLUDED.status,
                        detail = EXCLUDED.detail,
                        heartbeat_at = EXCLUDED.heartbeat_at,
                        updated_at = EXCLUDED.updated_at
                """, (new_alert_state, json.dumps(detail_payload) if detail_payload else None))
                conn.commit()
    except Exception as e:
        print(f"[WARN] crontab drift check failed: {e}")
    finally:
        conn.close()


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


# =============================================================================
# WARNING cooldown
# =============================================================================

WARNING_COOLDOWN_FILE = "/tmp/pipeline_monitor_warning_cooldown"
WARNING_COOLDOWN_HOURS = 2


def _warning_cooldown_active() -> bool:
    """Return True if WARNING cooldown is active (sent within last 2h)."""
    if not os.path.exists(WARNING_COOLDOWN_FILE):
        return False
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(WARNING_COOLDOWN_FILE))
        return datetime.now() - mtime < timedelta(hours=WARNING_COOLDOWN_HOURS)
    except OSError:
        return False


def _set_warning_cooldown():
    """Touch cooldown file to start 2h cooldown."""
    try:
        open(WARNING_COOLDOWN_FILE, 'w').close()
    except OSError:
        pass


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

    # Check 1B: INFRA-039 whale_trades write freshness (inserted_at)
    results["whale_write_freshness"] = check_whale_trades_write_freshness()

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

    # Check 8: age of last close_sell row (minutes)
    results["close_sell_last_run_age_minutes"] = check_close_sell_last_run_age()

    # Check 9: close_sell runs count in last 24h (from log)
    results["close_sell_runs_24h"] = check_close_sell_runs_24h()

    # Check 10: close_sell exit failures in last 24h (from log)
    results["close_sell_exit_failures_24h"] = check_close_sell_exit_codes_24h()

    # Check 11: close_sell P95 duration in last 24h (from log)
    results["close_sell_duration_p95_seconds"] = check_close_sell_duration_p95_24h()

    # Check 12: retention_cron last run age
    results["retention_cron_last_run_age_hours"] = check_retention_cron_last_run_age()

    # Check 13: retention_cron error in last entry
    results["retention_cron_error"] = check_retention_cron_error()

    # Check 14: retention deleted count from log
    results["retention_deleted"] = check_retention_deleted_count()

    # Check 15: FARM-022 К2 — farm degradation watch (active markets)
    check_farm_degradation(results)

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

    # Check 8: close_sell last run age
    age_min = results.get("close_sell_last_run_age_minutes")
    if age_min is not None:
        if age_min > 240:
            criticals.append(f"close_sell_last_run_age: {age_min:.0f}min (> 240) (CRITICAL)")
        elif age_min > 150:
            warnings.append(f"close_sell_last_run_age: {age_min:.0f}min (> 150)")
    else:
        # No close_sell rows ever — cron never produced results
        criticals.append("close_sell_last_run_age: no rows ever (CRITICAL)")

    # Check 9: close_sell runs 24h (from log)
    runs_result = results.get("close_sell_runs_24h")
    if runs_result:
        if runs_result["status"] == "critical":
            criticals.append(f"close_sell_runs_24h: {runs_result['value']} (< 18) (CRITICAL)")
        elif runs_result["status"] == "warning":
            criticals.append(f"close_sell_runs_24h: {runs_result['value']} (< 22)")
        # info (bootstrap) — skip

    # Check 10: close_sell exit failures 24h (from log)
    failures_result = results.get("close_sell_exit_failures_24h")
    if failures_result:
        if failures_result["status"] == "critical":
            criticals.append(f"close_sell_exit_failures_24h: {failures_result['value']} (CRITICAL)")
        # ok — nothing added

    # Check 11: close_sell duration P95 24h (from log)
    p95_result = results.get("close_sell_duration_p95_seconds")
    if p95_result:
        if p95_result["status"] == "critical":
            # Use alert_value (actual value that exceeded threshold) not last value
            alert_val = p95_result.get('alert_value') or p95_result['value']
            criticals.append(f"close_sell_duration_p95: {alert_val:.0f}s (> 1800) (CRITICAL) — process may be hung, check close_sell_cron.log")
        elif p95_result["status"] == "warning":
            warnings.append(f"close_sell_duration_p95: {p95_result['value']:.0f}s (> 1200) — normal at current table size (~500k rows)")
        # info (bootstrap) — skip

    # Check 12: retention_cron last run age (> 25h → ALERT)
    retention_age = results.get("retention_cron_last_run_age_hours")
    if retention_age is not None and retention_age > 25:
        warnings.append(f"retention_cron: no run in {retention_age:.0f}h (> 25h)")

    # Check 13: retention_cron ERROR in last entry → WARNING
    if results.get("retention_cron_error"):
        warnings.append("retention_cron: ERROR in last entry")

    # Check 14: INFRA-039 whale_trades write freshness (inserted_at)
    wf = results.get("whale_write_freshness")
    if wf and wf["status"] == "critical":
        criticals.append(f"whale_trades запись остановлена: {wf['reason']}")
    elif wf and wf["status"] == "warning":
        warnings.append(f"whale_trades запись отстаёт: {wf['reason']}")
    # status == "info"/"ok" → молчим

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

    retention_deleted = results.get("retention_deleted")
    retention_line = f"retention_deleted/24h: {retention_deleted}\n" if retention_deleted is not None else ""

    return f"""✅ Pipeline OK | {results['timestamp']}

whale_trades/24h: {results['whale_trades_24h']}
paper_trades/24h: {results['paper_trades_24h']}
roundtrips/24h: {results['roundtrips_24h']}
category_unknown: {results['market_category_unknown_count']}
{retention_line}containers: {container_status}
"""


def format_warning_message(results: dict, warnings: list, criticals: list) -> str:
    """Format WARNING message."""
    lines = ["⚠️ Pipeline WARNING | " + results["timestamp"], ""]

    # Add retention_deleted metric as first informational line
    retention_deleted = results.get("retention_deleted")
    if retention_deleted is not None:
        lines.append(f"📊 retention_deleted/24h: {retention_deleted}")

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
        # INFRA-046: live_executor heartbeat — independent, before pipeline checks
        check_live_executor_heartbeat()
        # INFRA-048: watchdog live_copy_daemon
        check_live_copy_daemon_heartbeat()
        # INFRA-047: watchdog застрявших ордеров
        check_stuck_orders()
        # INFRA-051: cron aliveness — canary heartbeat + crontab drift
        check_cron_heartbeat()
        check_crontab_drift()

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
            # CRITICAL - always send
            # WARNING - only if cooldown not active
            if status == "CRITICAL" or not _warning_cooldown_active():
                success = send_telegram_message(message)
                if success:
                    if status == "WARNING":
                        _set_warning_cooldown()
                    print(f"{status} alert sent to Telegram")
                else:
                    print(f"Failed to send {status} alert")
            else:
                print(f"WARNING, skip telegram (cooldown active)")

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