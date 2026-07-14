#!/usr/bin/env python3
"""
ACT-002: Fetch current positions from Polymarket Data API.
Backfill snapshot for funder1 (PechaArt) and funder2 (Justfuuun).
Upsert into account_positions_snapshot with snap_date = today.
ON CONFLICT: update size, cash_pnl, realized_pnl, cur_price, raw_json, ingested_at.
"""

import json
import os
import time
from datetime import date
from urllib.request import urlopen, Request

import psycopg2

# ── Config ──────────────────────────────────────────────────────────────────
API_BASE = "https://data-api.polymarket.com"
WALLET_TO_ACCOUNT = {
    "0x3fc83d2b40f9f243cbcd51a53cfdd7e9a6d366a1": "PechaArt",
    "0x5f032ff0e9376538ac240417ea5863756e1f2634": "Justfuuun",
}

FUNDERS = list(WALLET_TO_ACCOUNT.keys())

DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5433")
DB_NAME = os.getenv("PGDATABASE", "polymarket")
DB_USER = os.getenv("PGUSER", "postgres")
DB_PASS = os.getenv("PGPASSWORD", "")

TODAY = date.today().isoformat()

UPSERT_POSITION = """
INSERT INTO account_positions_snapshot (
    snap_date, account, condition_id, asset, title,
    size, avg_price, initial_value, current_value,
    cash_pnl, realized_pnl, cur_price, redeemable,
    end_date, raw_json
) VALUES (
    %(snap_date)s, %(account)s, %(condition_id)s, %(asset)s, %(title)s,
    %(size)s, %(avg_price)s, %(initial_value)s, %(current_value)s,
    %(cash_pnl)s, %(realized_pnl)s, %(cur_price)s, %(redeemable)s,
    %(end_date)s, %(raw_json)s
)
ON CONFLICT (snap_date, account, condition_id, asset)
DO UPDATE SET
    size         = EXCLUDED.size,
    avg_price    = EXCLUDED.avg_price,
    initial_value= EXCLUDED.initial_value,
    current_value= EXCLUDED.current_value,
    cash_pnl    = EXCLUDED.cash_pnl,
    realized_pnl = EXCLUDED.realized_pnl,
    cur_price   = EXCLUDED.cur_price,
    redeemable   = EXCLUDED.redeemable,
    end_date     = EXCLUDED.end_date,
    raw_json     = EXCLUDED.raw_json,
    ingested_at  = EXCLUDED.ingested_at;
"""


def fetch_positions(wallet: str) -> list:
    """Fetch positions for a wallet."""
    url = f"{API_BASE}/positions?user={wallet}&limit=100"
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def normalize_position(r: dict, account: str, snap_date: str) -> dict:
    """Normalise raw /positions record to DB columns."""
    raw = json.dumps(r)
    end_date_raw = r.get("endDate")
    end_date = end_date_raw if end_date_raw else None

    return {
        "snap_date": snap_date,
        "account": account,
        "condition_id": r["conditionId"],
        "asset": r["asset"],
        "title": r.get("title", ""),
        "size": r["size"],
        "avg_price": r.get("avgPrice"),
        "initial_value": r.get("initialValue"),
        "current_value": r.get("currentValue"),
        "cash_pnl": r["cashPnl"],
        "realized_pnl": r["realizedPnl"],
        "cur_price": r.get("curPrice"),
        "redeemable": r["redeemable"],
        "end_date": end_date,
        "raw_json": raw,
    }


def upsert_positions(conn, records: list, account: str, snap_date: str) -> int:
    """Upsert position records. Returns count of rows affected."""
    upserted = 0
    with conn.cursor() as cur:
        for r in records:
            rec = normalize_position(r, account, snap_date)
            cur.execute(UPSERT_POSITION, rec)
            upserted += cur.rowcount
    conn.commit()
    return upserted


def main():
    total_upserted = 0
    for wallet in FUNDERS:
        account = WALLET_TO_ACCOUNT[wallet]
        print(f"[{account}] Fetching positions ...")
        records = fetch_positions(wallet)
        print(f"[{account}] Got {len(records)} positions, upserting as {TODAY} ...")

        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS
        )
        n = upsert_positions(conn, records, account, TODAY)
        conn.close()
        print(f"[{account}] Upserted {n} rows.")
        total_upserted += n

    print(f"Total upserted: {total_upserted}")


if __name__ == "__main__":
    main()
