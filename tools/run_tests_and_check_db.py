#!/usr/bin/env python3
"""Run tests and verify DB persistence for v0.4.0 testing.

- Runs unit tests for VirtualBankroll and PaperTrading and the integration DB test.
- If tests pass, connects to PostgreSQL (via SQLAlchemy) and prints counts
  of records in virtual_trades and virtual_bankroll_history.
"""

import subprocess
import os
from sqlalchemy import create_engine, text


def run_tests() -> bool:
    cmd = [
        "pytest",
        "-q",
        "tests/unit/test_virtual_bankroll.py",
        "tests/unit/test_paper_trading.py",
        "tests/integration/test_virtual_bankroll_db.py",
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
            r1 = conn.execute(text("SELECT COUNT(*) FROM virtual_trades;"))
            trades = int(r1.scalar() or 0)
            r2 = conn.execute(text("SELECT COUNT(*) FROM virtual_bankroll_history;"))
            histories = int(r2.scalar() or 0)
            print(
                f"DB checks: virtual_trades={trades}, virtual_bankroll_history={histories}"
            )
        except Exception as e:
            print(f"DB check failed: {e}")


def main() -> None:
    ok = run_tests()
    if ok:
        check_db()


if __name__ == "__main__":
    main()
