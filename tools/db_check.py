#!/usr/bin/env python3
"""Simple DB check against existing polymarket database.

Connects to the public schema on the configured DB and prints basic visibility
into tables and counts. This helps quickly verify environment before running tests
that write into the DB.
"""

import os
from sqlalchemy import create_engine, text


def main() -> None:
    db_url = os.environ.get(
        "DB_URL",
        "postgresql://postgres:password@localhost:5433/polymarket",
    )
    print(f"Connecting to DB: {db_url}")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        # List public tables
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
            )
        ).fetchall()
        table_names = [r[0] for r in rows]
        print("Public tables:", table_names)

        # Check key tables existence
        for t in ["trades", "virtual_trades", "bankroll"]:
            reg = conn.execute(text(f"SELECT to_regclass('public.{t}')")).scalar()
            print(f"{t}: {'exists' if reg else 'missing'}")

        # Sample counts if exist
        for t in ["trades", "virtual_trades", "bankroll"]:
            try:
                cnt = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"{t} count: {cnt}")
            except Exception:
                pass


if __name__ == "__main__":
    main()
