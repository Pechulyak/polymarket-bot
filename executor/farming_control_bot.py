#!/usr/bin/env python3
"""
FARM-019: Telegram Control Bot for farming-daemon
Variant A - shared chat, alert bot token reused for control.

IMPORTANT: This bot uses long-polling getUpdates with the same token as farming-daemon.
Only ONE process can use getUpdates at a time per token.
If a second listener is added - it will conflict and steal updates from this bot.
"""

import os
import sys
import json
import time
import logging
import subprocess
import threading
import html
from datetime import datetime, timedelta, timezone

import requests

# ─── Timezone ────────────────────────────────────────────────────────────────
UTC_PLUS_3 = timezone(timedelta(hours=3))
LOG_TS_FMT = "%Y-%m-%d %H:%M:%S %Z"


def _convert_log_ts(ts_str: str) -> str:
    """Convert naive daemon log timestamp [YYYY-MM-DD HH:MM:SS] from UTC to UTC+3 HH:MM:SS +03."""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc).astimezone(UTC_PLUS_3)
        return dt.strftime("%H:%M:%S +03")
    except ValueError:
        return ts_str  # fallback: return as-is


def _escape_and_convert_log(line: str) -> str:
    """Escape HTML and convert any [YYYY-MM-DD HH:MM:SS] timestamps to UTC+3 format."""
    escaped = html.escape(line)
    # Find and convert timestamp pattern [YYYY-MM-DD HH:MM:SS]
    import re
    def replacer(m):
        return _convert_log_ts(m.group(1))
    return re.sub(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", replacer, escaped)


# ─── Configuration ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Whitelist: only process commands from this chat_id
ALLOWED_CHAT_ID = TELEGRAM_CHAT_ID

LOG_FILE = "/opt/executor/logs/farming_control_bot.log"
FARMING_STATE_FILE = "/opt/executor/app/farming_state.json"
FARMING_DAEMON_LOG = "/opt/executor/logs/farming_daemon.log"
FARMING_DAEMON_UNIT = "farming-daemon.service"

CONFIRM_TIMEOUT_SEC = 60

# ─── Market Definitions (mirrors farming_daemon.py MARKETS) ──────────────────
MARKETS = [
    {
        "name": "New People 2nd seats",
        "token": "16812776081734673413618925676070790303458587814000834940389189903201996256784",
    },
    {
        "name": "Phillies NL East",
        "token": "39412648633128959688152763881401048225314774593465497054882544514059472489266",
    },
    {
        "name": "AI 1530 Arena by Sep30",
        "token": "54893086053865884845869248787484771799795088600261085229269223835220342300136",
    },
]

TOKEN_TO_NAME = {m["token"]: m["name"] for m in MARKETS}

# ─── Logging Setup ────────────────────────────────────────────────────────────
logger = logging.getLogger("farming_control_bot")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(fh)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(ch)


# ─── Pending Confirmations ────────────────────────────────────────────────────
class PendingConfirm:
    def __init__(self, command: str, issued_at: datetime):
        self.command = command
        self.issued_at = issued_at


_pending_confirm: PendingConfirm | None = None
_pending_lock = threading.Lock()


def set_pending(command: str) -> None:
    global _pending_confirm
    with _pending_lock:
        _pending_confirm = PendingConfirm(command, datetime.now())


def get_pending() -> tuple[str | None, bool]:  # (command, expired)
    """Returns (command, is_expired). Lock must be held by caller."""
    if _pending_confirm is None:
        return None, False
    age = (datetime.now() - _pending_confirm.issued_at).total_seconds()
    return _pending_confirm.command, age > CONFIRM_TIMEOUT_SEC


def clear_pending() -> None:
    global _pending_confirm
    with _pending_lock:
        _pending_confirm = None


# ─── Telegram API Helpers ────────────────────────────────────────────────────
def tg_request(method: str, data: dict | None = None, retries: int = 3) -> dict | None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                logger.error("Telegram API error: %s", result)
                return None
            return result.get("result")
        except requests.RequestException as e:
            logger.warning("Telegram API attempt %d/%d failed: %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    logger.error("Telegram API all retries exhausted for method=%s", method)
    return None


def send_message(text: str, chat_id: str | int) -> bool:
    result = tg_request("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    if result is not None:
        return True
    # Fallback: retry without parse_mode on 400 (malformed HTML)
    logger.warning("sendMessage with HTML failed, retrying as plain text")
    result = tg_request("sendMessage", {"chat_id": chat_id, "text": text})
    return result is not None


# ─── Daemon Control ──────────────────────────────────────────────────────────
def is_daemon_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", FARMING_DAEMON_UNIT],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "active"
    except subprocess.TimeoutExpired:
        logger.error("systemctl is-active timed out")
        return False
    except Exception as e:
        logger.error("systemctl is-active failed: %s", e)
        return False


def daemon_stop() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "stop", FARMING_DAEMON_UNIT],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, "Daemon stopped successfully"
        return False, f"Failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, f"Error: {e}"


def daemon_start() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "start", FARMING_DAEMON_UNIT],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, "Daemon started successfully"
        return False, f"Failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, f"Error: {e}"


# ─── Status Report ────────────────────────────────────────────────────────────
def get_last_market_log(token: str, name: str, n: int = 300) -> str:
    """Return the last log line mentioning this market (by token or name)."""
    try:
        with open(FARMING_DAEMON_LOG, "r") as f:
            lines = f.readlines()
        # Search from end, find last line mentioning this token or name
        for line in reversed(lines[-n:]):
            stripped = line.strip()
            if not stripped:
                continue
            if token in stripped or name in stripped:
                return _escape_and_convert_log(stripped)
        return "&lt;no recent log for this market&gt;"
    except FileNotFoundError:
        return "&lt;log file not found&gt;"
    except Exception as e:
        return html.escape(f"&lt;log error: {e}&gt;")


def build_status_report() -> str:
    """Per-market status with last log line per market, pause info, alerts."""
    active = is_daemon_active()
    status_icon = "🟢" if active else "🔴"
    lines = [f"{status_icon} <b>farming-daemon</b>: {'ACTIVE' if active else 'INACTIVE'}"]

    # Load state
    try:
        with open(FARMING_STATE_FILE) as f:
            state = json.load(f)
    except FileNotFoundError:
        lines.append("")
        lines.append("&lt;state file not found&gt;")
        return "\n".join(lines)
    except Exception as e:
        lines.append("")
        lines.append(html.escape(f"&lt;state read error: {e}&gt;"))
        return "\n".join(lines)

    alerts = state.get("_alerts", {})

    lines.append("")
    lines.append("<b>Markets:</b>")

    for mkt in MARKETS:
        token = mkt["token"]
        name = mkt["name"]
        mstate = state.get(token, {})
        pause_until = mstate.get("pause_until", 0)
        last_ts = mstate.get("last_ts", 0)
        is_paused = pause_until > time.time()

        # Pause status
        if is_paused:
            remaining = int(pause_until - time.time())
            # Convert pause_until to UTC+3 HH:MM:SS
            pause_dt = datetime.fromtimestamp(pause_until, tz=timezone.utc).astimezone(UTC_PLUS_3)
            pause_ts = pause_dt.strftime("%H:%M:%S +03")
            pause_str = f"⏸ PAUSED (expires {pause_ts}, ~{(remaining // 60)}m {remaining % 60}s)"
        elif last_ts == 0:
            pause_str = "○ idle (no activity)"
        else:
            pause_str = "▶ active"

        # Last log line for this market
        last_log = get_last_market_log(token, name)

        lines.append(f"  <b>{html.escape(name)}</b>  {pause_str}")

        if last_ts > 0:
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).astimezone(UTC_PLUS_3)
            last_ts_str = last_dt.strftime("last:%H:%M:%S +03")
        else:
            last_ts_str = "last: never"
        lines.append(f"    {last_ts_str}  {last_log}")

    lines.append("")
    lines.append("<b>Alerts:</b>")

    active_raw = [(k, v) for k, v in alerts.items() if v is True]

    # Separate stale (unknown token) from current markets
    stale_alerts = []
    current_alerts_by_market: dict[str, list[str]] = {}

    for key in active_raw:
        alert_key = key[0]  # key is (key, True) tuple, alert_key = key[0]
        if ":" in alert_key:
            alert_type, token_candidate = alert_key.rsplit(":", 1)
            # Check if it's a known token
            if token_candidate in TOKEN_TO_NAME:
                mkt_name = TOKEN_TO_NAME[token_candidate]
                if mkt_name not in current_alerts_by_market:
                    current_alerts_by_market[mkt_name] = []
                current_alerts_by_market[mkt_name].append(alert_type)
            else:
                stale_alerts.append(alert_key)
        else:
            stale_alerts.append(alert_key)

    if current_alerts_by_market:
        for mkt_name, alert_types in sorted(current_alerts_by_market.items()):
            unique_types = sorted(set(alert_types))
            types_str = ", ".join(unique_types)
            lines.append(f"  <b>{html.escape(mkt_name)}</b>: {types_str}")
    else:
        lines.append("  none")

    if stale_alerts:
        lines.append(f"  stale: {len(stale_alerts)}")

    return "\n".join(lines)


# ─── Command Dispatcher ───────────────────────────────────────────────────────
def handle_command(text: str, chat_id: str | int) -> str | None:
    text = text.strip()
    global _pending_confirm

    if text == "/status":
        return build_status_report()

    elif text == "/stop":
        with _pending_lock:
            pending_cmd, expired = get_pending()
            if pending_cmd == "stop":
                if expired:
                    clear_pending()
                    return "❌ Previous /stop confirmation expired. Use /stop again."
                # still valid
                return "⏳ /stop already pending. Send /confirm_stop within 60s or /stop to reset timer."
            if pending_cmd is not None:
                return f"⚠️ A different operation is pending: {pending_cmd}. Wait for timeout."
        set_pending("stop")
        return (
            "⚠️ <b>Confirm stop?</b>\n"
            "This will STOP the farming daemon.\n"
            "Send /confirm_stop within 60 seconds to proceed."
        )

    elif text == "/confirm_stop":
        with _pending_lock:
            pending_cmd, expired = get_pending()
            if pending_cmd != "stop":
                return "❌ No pending /stop. Use /stop first."
            if expired:
                clear_pending()
                return "❌ Confirmation expired. Use /stop again."
        clear_pending()
        success, msg = daemon_stop()
        icon = "✅" if success else "❌"
        return f"{icon} <b>/stop</b>: {msg}"

    elif text == "/start":
        with _pending_lock:
            pending_cmd, expired = get_pending()
            if pending_cmd == "start":
                if expired:
                    clear_pending()
                    return "❌ Previous /start confirmation expired. Use /start again."
                return "⏳ /start already pending. Send /confirm_start within 60s or /start to reset timer."
            if pending_cmd is not None:
                return f"⚠️ A different operation is pending: {pending_cmd}. Wait for timeout."
        set_pending("start")
        return (
            "⚠️ <b>Confirm start?</b>\n"
            "This will START the farming daemon.\n"
            "Send /confirm_start within 60 seconds to proceed."
        )

    elif text == "/confirm_start":
        with _pending_lock:
            pending_cmd, expired = get_pending()
            if pending_cmd != "start":
                return "❌ No pending /start. Use /start first."
            if expired:
                clear_pending()
                return "❌ Confirmation expired. Use /start again."
        clear_pending()
        success, msg = daemon_start()
        icon = "✅" if success else "❌"
        return f"{icon} <b>/start</b>: {msg}"

    elif text in ("/cancel", "/no"):
        with _pending_lock:
            pending_cmd, _ = get_pending()
            if pending_cmd is None:
                return "Nothing to cancel."
            clear_pending()
            return f"✅ Cancelled pending <b>{pending_cmd}</b>."
    else:
        return None  # unknown command, ignore


# ─── Main Polling Loop ───────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    logger.info("Starting farming-control-bot (token prefix: %s..., chat_id: %s)",
                TELEGRAM_TOKEN[:10], TELEGRAM_CHAT_ID)

    offset = 0

    while True:
        try:
            updates = tg_request("getUpdates", {"offset": offset, "timeout": 30})
            if updates is None:
                logger.warning("getUpdates returned None, retrying in 5s")
                time.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                # Whitelist enforcement - ignore messages from other chats
                if chat_id != ALLOWED_CHAT_ID:
                    logger.debug("Ignored message from unauthorized chat_id=%s", chat_id)
                    continue

                if not text:
                    continue

                logger.info("Command from %s: %s", chat_id, text)
                response = handle_command(text, chat_id)

                if response:
                    if not send_message(response, chat_id):
                        logger.error("Failed to send response to chat_id=%s", chat_id)
                    else:
                        logger.info("Response sent to %s", chat_id)

            # Clean up expired pending confirmations periodically
            with _pending_lock:
                _, expired = get_pending()
                if expired:
                    logger.info("Pending confirmation expired, clearing")
                    clear_pending()

        except Exception as e:
            logger.error("Main loop exception: %s", e, exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
