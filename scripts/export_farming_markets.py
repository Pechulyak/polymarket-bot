#!/usr/bin/env python3
"""
Export farming_active_markets (status='active') to markets.json
Snapshot for manual delivery to S2.

Usage:
    python scripts/export_farming_markets.py [--out markets.json]

Schema output:
    {"version": 1, "markets": [{name, token, min_size, inv_center,
      inv_deadband, max_inv, weight, gamma_id, condition_id}]}
"""

import argparse
import json
import os
import sys
from pathlib import Path

import subprocess


def fetch_active_markets() -> list[dict]:
    """Fetch active markets from farming_active_markets via docker exec."""
    result = subprocess.run(
        [
            "docker", "exec", "polymarket_postgres",
            "psql", "-U", "postgres", "-d", "polymarket",
            "-t", "-A", "-c",
            """
            SELECT name, token_id, min_size::numeric, inv_center::numeric,
                   inv_deadband::numeric, max_inv::numeric, weight::numeric,
                   gamma_id, condition_id
            FROM farming_active_markets
            WHERE status = 'active'
            ORDER BY id
            """
        ],
        capture_output=True, text=True, check=True
    )
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            parts = line.split("|")
            rows.append(tuple(parts))
    return rows


def validate_markets(rows: list) -> None:
    """Validate markets data. Exit 1 if invalid."""
    if not rows:
        print("ERROR: No active markets found", file=sys.stderr)
        sys.exit(1)

    tokens = set()
    for row in rows:
        name, token, min_size, inv_center, inv_deadband, max_inv, weight, gamma_id, condition_id = row

        # Check token unique
        if token in tokens:
            print(f"ERROR: duplicate token: {token}", file=sys.stderr)
            sys.exit(1)
        tokens.add(token)

        # Check numeric fields > 0
        for field, val in [("min_size", min_size), ("inv_center", inv_center),
                           ("inv_deadband", inv_deadband), ("max_inv", max_inv),
                           ("weight", weight)]:
            try:
                fval = float(val)
            except (ValueError, TypeError):
                print(f"ERROR: {field} must be numeric for market {name}", file=sys.stderr)
                sys.exit(1)
            if fval <= 0:
                print(f"ERROR: {field} must be > 0 for market {name}", file=sys.stderr)
                sys.exit(1)

        # inv_center <= max_inv
        if float(inv_center) > float(max_inv):
            print(f"ERROR: inv_center > max_inv for market {name}", file=sys.stderr)
            sys.exit(1)


def build_json(rows: list) -> dict:
    """Build markets.json structure."""
    markets = []
    for row in rows:
        name, token, min_size, inv_center, inv_deadband, max_inv, weight, gamma_id, condition_id = row
        markets.append({
            "name": name,
            "token": str(token),
            "min_size": float(min_size),
            "inv_center": float(inv_center),
            "inv_deadband": float(inv_deadband),
            "max_inv": float(max_inv),
            "weight": float(weight),
            "gamma_id": int(gamma_id),
            "condition_id": condition_id,
        })
    return {"version": 1, "markets": markets}


def main():
    parser = argparse.ArgumentParser(description="Export farming_active_markets to JSON")
    parser.add_argument("--out", default="-", help="Output file (default: stdout)")
    args = parser.parse_args()

    rows = fetch_active_markets()
    validate_markets(rows)

    output = build_json(rows)
    json_str = json.dumps(output, indent=2, ensure_ascii=False) + "\n"

    if args.out == "-":
        print(json_str)
    else:
        with open(args.out, "w") as f:
            f.write(json_str)
        print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
