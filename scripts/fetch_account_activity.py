#!/usr/bin/env python3
"""
ACT-002: Fetch portfolio activity from Polymarket Data API.
Backfill for funder1 (PechaArt) and funder2 (Justfuuun).
Upsert into account_activity with explicit ON CONFLICT targets + predicates.
Two separate INSERT branches: side IS NOT NULL vs side IS NULL.
"""

import json
import os
import sys
import time
from datetime import datetime
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

# ── SQL: side IS NOT NULL (TRADE, SPLIT, MERGE, CONVERSION) ─────────────────
INSERT_TRADE = """
INSERT INTO account_activity (
    account, proxy_wallet, event_type, condition_id,
    asset, side, size, usdc_size, price,
    outcome_index, title, slug, event_ts, tx_hash, raw_json
) VALUES (
    %(account)s, %(proxy_wallet)s, %(event_type)s, %(condition_id)s,
    %(asset)s, %(side)s, %(size)s, %(usdc_size)s, %(price)s,
    %(outcome_index)s, %(title)s, %(slug)s,
    to_timestamp(%(event_ts)s),
    %(tx_hash)s, %(raw_json)s
)
ON CONFLICT (tx_hash, condition_id, event_type, side, size, price, fill_seq)
    WHERE side IS NOT NULL
DO NOTHING;
"""

# ── SQL: side IS NULL (REDEEM, REWARD) ──────────────────────────────────────
INSERT_REDEEM = """
INSERT INTO account_activity (
    account, proxy_wallet, event_type, condition_id,
    asset, side, size, usdc_size, price,
    outcome_index, title, slug, event_ts, tx_hash, raw_json
) VALUES (
    %(account)s, %(proxy_wallet)s, %(event_type)s, %(condition_id)s,
    %(asset)s, %(side)s, %(size)s, %(usdc_size)s, %(price)s,
    %(outcome_index)s, %(title)s, %(slug)s,
    to_timestamp(%(event_ts)s),
    %(tx_hash)s, %(raw_json)s
)
ON CONFLICT (tx_hash, condition_id, event_type, size, fill_seq)
    WHERE side IS NULL
DO NOTHING;
"""


def fetch_activity(wallet: str) -> list:
    """Fetch all activity records for a wallet via pagination."""
    records = []
    offset = 0
    limit = 100
    while True:
        url = f"{API_BASE}/activity?user={wallet}&limit={limit}&offset={offset}"
        req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
        with urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        if not page:
            break
        records.extend(page)
        offset += limit
        if len(page) < limit:
            break
        time.sleep(0.25)
    return records


def normalize_record(r: dict, account: str) -> dict:
    """
    Normalise raw API record to DB columns.
    - '' → None for asset, side
    - REDEEM/REWARD: price → None
    """
    raw = json.dumps(r)

    side_raw = r.get("side", "")
    side = side_raw if side_raw not in ("", None) else None

    asset_raw = r.get("asset", "")
    asset = asset_raw if asset_raw not in ("", None) else None

    event_type = r.get("type", "")
    price_raw = r.get("price")
    if event_type in ("REDEEM", "REWARD") or price_raw == 0:
        price = None
    else:
        price = price_raw

    return {
        "account": account,
        "proxy_wallet": r["proxyWallet"].lower(),
        "event_type": event_type,
        "condition_id": r["conditionId"],
        "asset": asset,
        "side": side,
        "size": r["size"],
        "usdc_size": r["usdcSize"],
        "price": price,
        "outcome_index": r.get("outcomeIndex"),
        "title": r.get("title", ""),
        "slug": r.get("slug", ""),
        "event_ts": r["timestamp"],
        "tx_hash": r["transactionHash"],
        "raw_json": raw,
    }


def upsert_activity(conn, records: list, account: str) -> tuple[int, list]:
    """
    Insert activity records. Returns (rows_inserted, collapsed_keys).
    collapsed_keys: list of (key_type, key_dict) for records that hit ON CONFLICT.
    """
    inserted = 0
    collapsed = []
    with conn.cursor() as cur:
        for r in records:
            rec = normalize_record(r, account)
            if rec["side"] is not None:
                cur.execute(INSERT_TRADE, rec)
                rowcount = cur.rowcount
                if rowcount == 0:
                    collapsed.append(("trade", {
                        "tx_hash": rec["tx_hash"],
                        "condition_id": rec["condition_id"],
                        "event_type": rec["event_type"],
                        "side": rec["side"],
                        "size": str(rec["size"]),
                        "price": str(rec["price"]),
                    }))
            else:
                cur.execute(INSERT_REDEEM, rec)
                rowcount = cur.rowcount
                if rowcount == 0:
                    collapsed.append(("redeem", {
                        "tx_hash": rec["tx_hash"],
                        "condition_id": rec["condition_id"],
                        "event_type": rec["event_type"],
                        "size": str(rec["size"]),
                    }))
            inserted += rowcount
    conn.commit()
    return inserted, collapsed


def main():
    total_inserted = 0
    for wallet in FUNDERS:
        account = WALLET_TO_ACCOUNT[wallet]
        print(f"[{account}] Fetching activity for {wallet} ...")
        records = fetch_activity(wallet)
        print(f"[{account}] Fetched {len(records)} records, upserting ...")

        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS
        )
        n, collapsed = upsert_activity(conn, records, account)
        conn.close()
        print(f"[{account}] Inserted {n} rows.")
        total_inserted += n

        fetched = len(records)
        collapsed_n = fetched - n
        if collapsed_n > 0:
            print(
                f"[{account}] COLLAPSED: fetched={fetched} inserted={n} collapsed={collapsed_n}",
                file=sys.stderr
            )
            for key_type, key_dict in collapsed:
                print(
                    f"[{account}] COLLAPSED_KEY type={key_type} {key_dict}",
                    file=sys.stderr
                )
        else:
            print(f"[{account}] COLLAPSED: 0", file=sys.stderr)

    print(f"Total inserted: {total_inserted}")


if __name__ == "__main__":
    main()
