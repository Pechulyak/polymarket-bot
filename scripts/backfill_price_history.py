#!/usr/bin/env python3
"""
ACT-007: Backfill UTC daily token prices from the Polymarket CLOB API.

The token universe comes from account_activity.asset.  For each token the
script requests /prices-history with interval=max and fidelity=1440, keeps the
latest timestamp in each UTC calendar day, and prepares an idempotent upsert
into market_price_history.

Use --dry-run to inspect every row that would be written without touching the
market_price_history table.  --limit is a validation/convenience option; the
default processes every distinct non-empty asset.

Examples:
    python3 scripts/backfill_price_history.py --dry-run --limit 5
    python3 scripts/backfill_price_history.py
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras


CLOB_BASE_URL = "https://clob.polymarket.com"
DEFAULT_REQUEST_DELAY = 0.25
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 15
USER_AGENT = "polymarket-bot/act007-price-history-backfill"

DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5433")
DB_NAME = os.getenv("PGDATABASE", "polymarket")
DB_USER = os.getenv("PGUSER", "postgres")
DB_PASS = os.getenv("PGPASSWORD", "postgres")


class HistoryFetchError(RuntimeError):
    """The CLOB history could not be fetched after all retry attempts."""


def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


def fetch_assets(conn, limit=None):
    """Return every distinct non-empty token ID, optionally capped for checks."""
    query = """
        SELECT DISTINCT asset
        FROM account_activity
        WHERE asset IS NOT NULL AND asset != ''
        ORDER BY asset
    """
    params = ()
    if limit is not None:
        query += " LIMIT %s"
        params = (limit,)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [row[0] for row in cur.fetchall()]


def fetch_history(asset, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """Fetch one token's raw history, retrying transient HTTP/network errors."""
    query = urllib.parse.urlencode(
        {"market": asset, "interval": "max", "fidelity": "1440"}
    )
    url = f"{CLOB_BASE_URL}/prices-history?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
            history = payload.get("history") if isinstance(payload, dict) else None
            if history is None:
                raise ValueError("response has no history field")
            if not isinstance(history, list):
                raise ValueError("response history is not a list")
            return history
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                # Back off between retries; the outer loop also rate-limits
                # the next token request even after a successful response.
                time.sleep(0.5 * attempt)

    raise HistoryFetchError(
        f"{type(last_error).__name__}: {last_error} after {retries} attempts"
    )


def daily_last_points(history):
    """Return {UTC date: Decimal price}, keeping the latest point per date.

    The API normally returns integer Unix timestamps and probability prices.
    Malformed points are skipped with a diagnostic.  Out-of-range finite prices
    are retained (so the source response is not silently changed) and reported
    as anomalies for operator review.
    """
    latest_by_date = {}
    diagnostics = []

    for index, point in enumerate(history):
        if not isinstance(point, dict):
            diagnostics.append(f"point {index}: not an object")
            continue

        raw_timestamp = point.get("t")
        raw_price = point.get("p")
        if raw_timestamp is None or raw_price is None:
            diagnostics.append(f"point {index}: missing t or p")
            continue

        try:
            timestamp = float(raw_timestamp)
            point_date = datetime.fromtimestamp(
                timestamp, tz=timezone.utc
            ).date()
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            diagnostics.append(f"point {index}: invalid timestamp {raw_timestamp!r} ({exc})")
            continue

        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, ValueError, TypeError) as exc:
            diagnostics.append(f"point {index}: invalid price {raw_price!r} ({exc})")
            continue

        if not price.is_finite():
            diagnostics.append(f"point {index}: non-finite price {raw_price!r}")
            continue
        if price < 0 or price > 1:
            diagnostics.append(
                f"point {index}: price {price} outside expected [0, 1] range - skipped"
            )
            continue

        previous = latest_by_date.get(point_date)
        # >= deliberately lets the final response item win when timestamps tie.
        if previous is None or timestamp >= previous[0]:
            latest_by_date[point_date] = (timestamp, price)

    return {
        point_date: price
        for point_date, (_, price) in sorted(latest_by_date.items())
    }, diagnostics


def upsert_rows(conn, rows):
    """Write prepared rows using an idempotent asset/date upsert."""
    if not rows:
        return 0

    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO market_price_history (asset, price_date, price)
                VALUES %s
                ON CONFLICT (asset, price_date) DO UPDATE
                SET price = EXCLUDED.price,
                    fetched_at = NOW()
                """,
                rows,
                page_size=1000,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill UTC daily CLOB prices for account_activity assets."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned upserts without writing market_price_history",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="process at most this many assets (useful for validation; default: all)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY,
        help=f"delay between token requests in seconds (default: {DEFAULT_REQUEST_DELAY})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"attempts per API request (default: {DEFAULT_RETRIES})",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.request_delay < 0:
        raise SystemExit("--request-delay must be non-negative")
    if args.retries < 1:
        raise SystemExit("--retries must be at least 1")

    conn = get_conn()
    try:
        assets = fetch_assets(conn, limit=args.limit)
        mode = "dry-run" if args.dry_run else "write"
        print(f"mode={mode} assets_to_backfill={len(assets)}", file=sys.stderr)

        failed_assets = []
        empty_assets = []
        anomaly_count = 0
        total_rows = 0
        written_rows = 0

        for index, asset in enumerate(assets, 1):
            try:
                history = fetch_history(
                    asset,
                    retries=args.retries,
                )
            except HistoryFetchError as exc:
                failed_assets.append(asset)
                print(f"[WARN] asset={asset} fetch failed: {exc}", file=sys.stderr)
                time.sleep(args.request_delay)
                continue

            daily_prices, diagnostics = daily_last_points(history)
            total_rows += len(daily_prices)
            anomaly_count += len(diagnostics)
            for diagnostic in diagnostics:
                print(f"[WARN] asset={asset} {diagnostic}", file=sys.stderr)

            if not daily_prices:
                empty_assets.append(asset)
                print(
                    f"[WARN] asset={asset} history_points={len(history)} daily_points=0",
                    file=sys.stderr,
                )
            else:
                print(
                    f"asset={asset} history_points={len(history)} "
                    f"daily_points={len(daily_prices)}",
                    file=sys.stderr,
                )

            rows = [(asset, point_date, price) for point_date, price in daily_prices.items()]
            if args.dry_run:
                for row_asset, point_date, price in rows:
                    print(
                        f"UPSERT asset={row_asset} price_date={point_date.isoformat()} "
                        f"price={price}"
                    )
            elif rows:
                # Per-asset commit: a failure on token N doesn't lose tokens
                # already written, and memory stays O(1) instead of O(all rows).
                written_rows += upsert_rows(conn, rows)

            if index < len(assets):
                time.sleep(args.request_delay)

        if args.dry_run:
            print(
                f"DRY_RUN_SUMMARY assets={len(assets)} daily_rows={total_rows} "
                f"failed_assets={len(failed_assets)} empty_history={len(empty_assets)} "
                f"anomalies={anomaly_count}",
                file=sys.stderr,
            )
        else:
            print(f"wrote_rows={written_rows}", file=sys.stderr)

        if failed_assets:
            print(f"failed_assets={failed_assets}", file=sys.stderr)
        if empty_assets:
            print(f"empty_history_assets={empty_assets}", file=sys.stderr)

        # A failed fetch is operationally significant even if other assets
        # succeeded; return non-zero so an orchestrator can retry the run.
        return 1 if failed_assets else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
