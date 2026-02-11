# Changelog - Testing

## [2026-02-11] - Virtual Bankroll & Paper Trading Testing (Updated)

### Added Tests
- `tests/unit/test_paper_trading.py` - Paper trading simulation, success criteria validation, statistics reporting
- `tests/integration/test_virtual_bankroll_db.py` - Database persistence, schema validation, data consistency
- `tests/integration/test_db_basic_write.py` - Basic trade and bankroll insert tests
- Extended `tests/unit/test_virtual_bankroll.py` with additional coverage (30 tests total)

### Test Results
- **Virtual Bankroll Tests**: 30 tests, all passing
- **Database Integration Tests**: 2 passed, 1 skipped (DB persistence verified)
- **Basic DB Write Tests**: 1 passed, 1 skipped
- **Paper Trading Tests**: 11 passed, 3 skipped
  - Fixed async/sync mock issues
  - Added duration validation to `start()` method
  - Fixed datetime mocking after timeout

### Bug Fixes
- **Exchange Column NOT NULL**: Added `exchange` column to trades INSERT
  - Resolved psycopg2 NOT NULL constraint violation
- **Duration Validation**: Added `duration_hours > 0` check in `PaperTradingRunner.start()`
  - Tests `test_zero_duration` and `test_negative_duration` now pass

### Known Issues
- **test_shutdown_handling**: Skipped - requires proper asyncio.Event mocking
- **Demo mode tests**: Skipped - require argparse integration
- These tests require refactoring of PaperTradingRunner to support testing signals

### Test Environment
- **Database**: PostgreSQL 15 on port 5433
- **Database Name**: `postgres`
- **Dependencies**: SQLAlchemy, psycopg2-binary, pytest-asyncio
- **DB URL**: `postgresql://postgres:password@localhost:5433/postgres`

### Test Execution
```bash
# Run virtual bankroll tests
python -m pytest tests/unit/test_virtual_bankroll.py -v

# Run integration tests
python -m pytest tests/integration/test_virtual_bankroll_db.py tests/integration/test_db_basic_write.py -v
```
