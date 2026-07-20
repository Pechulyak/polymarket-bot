#!/usr/bin/env python3
"""Run tests and verify DB persistence for v0.4.0 testing.

- Runs the remaining unit/integration tests after HYG-017 removal of dead VB files.
- If tests pass, connects to PostgreSQL (via SQLAlchemy) and prints counts
  of records in core tables (paper_trades, whale_trades, whales).
"""

import subprocess
import os
from sqlalchemy import create_engine, text


def run_tests() -> bool:
    cmd = [
        "pytest",
        "-q",
        "tests/",
    ]
    print("Running tests:", " ".join(cmd))
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(result.stdout)
    return result.returncode == 0


def check_db() -> None:
    db_url = os.environ.get(
        "DB_URL", "postgresql://postgres:password@localhost:5433/polymarket_test"
    )
    print(f"Connecting to DB: {db_url}")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        try:
            r1 = conn.execute(text("SELECT COUNT(*) FROM paper_trades;"))
            paper = int(r1.scalar() or 0)
            r2 = conn.execute(text("SELECT COUNT(*) FROM whale_trades;"))
            whale = int(r2.scalar() or 0)
            print(
                f"DB checks: paper_trades={paper}, whale_trades={whale}"
            )
        except Exception as e:
            print(f"DB check failed: {e}")


def main() -> None:
    ok = run_tests()
    if ok:
        check_db()


if __name__ == "__main__":
    main()
