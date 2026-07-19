#!/usr/bin/env python3
"""
FARM-039 — sync farming_active_markets -> /opt/executor/app/markets.json.

Генератор markets.json для S2. Источник истины — таблица farming_active_markets
(status='active'). Скрипт НЕ делает авто-рестарта демона: при изменении файла
он шлёт TG-алерт "⚠️ markets.json изменён — нужен ручной рестарт".

Контракт:
  - атомарная запись (tmp + os.replace) — старый файл не побивается наполовину;
  - sha256-диф: если новый контент совпадает с текущим — алерта нет (не спамим);
  - TG-алерт мягкий: try/except вокруг requests — сетевая ошибка не должна
    валить экспорт;
  - валидация fetched-строк идентична scripts/export_farming_markets.py:
    уникальный token, числовые поля > 0, inv_center <= max_inv. При провале —
    exit(1), существующий markets.json НЕ трогать.

Использование на S2 (cron, ручной запуск):
    python3 /opt/executor/app/farming_markets_sync.py
    # либо с --out для теста:
    python3 /opt/executor/app/farming_markets_sync.py --out /tmp/check.json

Dependencies (S2):
    - PostgreSQL with farming_active_markets table
    - DATABASE_URL env OR CREDENTIALS_DIRECTORY/database_url (systemd
      LoadCredential — тот же паттерн, что в farming/tools/farming_snapshot.py)
    - TELEGRAM_TOKEN, TELEGRAM_CHAT_ID env (для алерта при изменении;
      опционально — если не заданы, алерт просто пропускается с логом)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2


DEFAULT_OUT = "/opt/executor/app/markets.json"


# ─── Logging ─────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    """stdout + ISO-timestamp; тот же формат, что в farming_daemon.py."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─── DB connection (дословно farming/tools/farming_snapshot.py:110-121) ───────
def get_db_connection():
    """Create DB connection using S2 credentials pattern.

    Сначала systemd LoadCredential: $CREDENTIALS_DIRECTORY/database_url.
    Иначе — DATABASE_URL из окружения. Никаких docker exec/psql — мы уже
    внутри S2, прямое psycopg2-соединение."""
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir and os.path.exists(os.path.join(cred_dir, "database_url")):
        with open(os.path.join(cred_dir, "database_url")) as f:
            return psycopg2.connect(f.read().strip())

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)

    raise RuntimeError(
        "No database credentials found (CREDENTIALS_DIRECTORY or DATABASE_URL)"
    )


# ─── Fetch ────────────────────────────────────────────────────────────────────
FETCH_SQL = """
SELECT name, token_id, min_size::numeric, inv_center::numeric,
       inv_deadband::numeric, max_inv::numeric, weight::numeric,
       gamma_id, condition_id
FROM farming_active_markets
WHERE status = 'active'
ORDER BY id
"""


def fetch_active_markets() -> list[dict]:
    """SELECT через psycopg2-курсор -> list[dict] в схеме markets.json.

    numeric-поля приходят как Decimal; приводим к float на этом шаге, чтобы
    дельты с эталонным JSON (export_farming_markets.py) не разъезжались по
    типу. Невалидные строки (token пустой, нечисловые поля) валидируются
    отдельно в validate_markets()."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(FETCH_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    for (name, token_id, min_size, inv_center, inv_deadband, max_inv,
         weight, gamma_id, condition_id) in rows:
        out.append({
            "name": str(name),
            "token": str(token_id),
            "min_size": float(min_size),
            "inv_center": float(inv_center),
            "inv_deadband": float(inv_deadband),
            "max_inv": float(max_inv),
            "weight": float(weight),
            "gamma_id": int(gamma_id),
            "condition_id": str(condition_id),
        })
    return out


# ─── Validation (та же логика, что scripts/export_farming_markets.py) ────────
def validate_markets(rows: list[dict]) -> None:
    """Validate fetched rows. Печатает в stderr и raise ValueError при провале."""
    if not rows:
        raise ValueError("No active markets found in farming_active_markets")

    seen_tokens: set[str] = set()
    numeric_fields = ("min_size", "inv_center", "inv_deadband", "max_inv", "weight")
    for m in rows:
        name = m.get("name")
        token = m.get("token")

        if not token:
            raise ValueError(f"empty token for market {name!r}")
        if token in seen_tokens:
            raise ValueError(f"duplicate token: {token} (market {name!r})")
        seen_tokens.add(token)

        for field in numeric_fields:
            val = m.get(field)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(
                    f"{field} must be numeric for market {name!r}, got {val!r}"
                )
            if val <= 0:
                raise ValueError(
                    f"{field} must be > 0 for market {name!r}, got {val}"
                )

        if float(m["inv_center"]) > float(m["max_inv"]):
            raise ValueError(
                f"inv_center ({m['inv_center']}) > max_inv ({m['max_inv']}) "
                f"for market {name!r}"
            )


# ─── Atomic write + sha256 diff + TG alert ───────────────────────────────────
def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _send_telegram_alert(text: str) -> None:
    """POST в Telegram Bot API. NEVER raise: сетевая ошибка не должна
    валить экспорт — мы же только что успешно записали новый markets.json."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("[sync] TELEGRAM_TOKEN/CHAT_ID не заданы — TG-алерт пропущен")
        return
    try:
        import requests  # local import — нам не нужна requests для самого экспорта
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if resp.status_code >= 400:
            log(f"[sync] TG-алерт не доставлен (HTTP {resp.status_code}): "
                f"{resp.text[:200]}")
        else:
            log(f"[sync] TG-алерт отправлен: {text[:60]}...")
    except Exception as e:
        log(f"[sync] TG-алерт упал (raw, not auto-fixed): {e}")


def write_markets_file(rows: list[dict], out_path: str) -> bool:
    """Записать markets.json атомарно; вернуть True если контент изменился
    (или файла раньше не было). False — контент совпал с существующим.

    Существующий валидный файл НЕ трогаем при провале валидации: эта функция
    предполагает, что вызывающий код уже провалидировал rows.
    """
    payload = {"version": 1, "markets": rows}
    new_json = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    new_hash = _sha256_hex(new_json)

    old_hash = None
    if os.path.exists(out_path):
        try:
            with open(out_path, "r") as f:
                old_json = f.read()
            old_hash = _sha256_hex(old_json)
        except OSError as e:
            log(f"[sync] WARN: не удалось прочитать существующий {out_path}: {e} "
                f"— трактую как 'файл отсутствовал'")
            old_hash = None

    if old_hash == new_hash:
        log(f"[sync] markets.json не изменился (sha256={new_hash[:12]}…, "
            f"{len(rows)} рынков) — без записи и без алерта")
        return False

    # Атомарная запись: tmp в той же директории (pid в имени — на случай
    # пересекающихся запусков), потом os.replace.
    tmp_path = f"{out_path}.{os.getpid()}.tmp"
    with open(tmp_path, "w") as f:
        f.write(new_json)
    os.replace(tmp_path, out_path)

    if old_hash is None:
        log(f"[sync] markets.json создан ({len(rows)} рынков, "
            f"sha256={new_hash[:12]}…) — ранее файла не было")
    else:
        log(f"[sync] markets.json обновлён ({len(rows)} рынков, "
            f"sha256: {old_hash[:12]}… -> {new_hash[:12]}…)")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FARM-039 sync: farming_active_markets -> markets.json"
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUT,
        help=f"путь к markets.json (default: {DEFAULT_OUT})"
    )
    args = parser.parse_args()

    log(f"[sync] старт, --out={args.out}")

    # 1. Тянем из БД. Любая ошибка БД — фатальна (нет смысла идти дальше).
    try:
        rows = fetch_active_markets()
    except Exception as e:
        log(f"[sync] FATAL: ошибка БД: {e}")
        return 1

    log(f"[sync] получено {len(rows)} строк из farming_active_markets")

    # 2. Валидация fetched-данных. При провале — exit(1), существующий файл
    #    НЕ трогаем (не затираем хороший markets.json плохими данными).
    try:
        validate_markets(rows)
    except ValueError as e:
        log(f"[sync] FATAL: валидация провалена: {e}")
        return 1

    # 3. Запись с sha256-дифом. Если изменилось — TG-алерт (never crash).
    try:
        changed = write_markets_file(rows, args.out)
    except OSError as e:
        log(f"[sync] FATAL: ошибка записи {args.out}: {e}")
        return 1

    if changed:
        _send_telegram_alert(
            f"⚠️ markets.json изменён ({len(rows)} рынков) — "
            f"демон работает со старым конфигом, нужен ручной рестарт "
            f"farming-daemon.service"
        )
    # else: write_markets_file уже залогировал "без изменений"

    log("[sync] готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())