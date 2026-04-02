"""
Одноразовый тест WhaleTradesRepo.
Запуск: python3 tests/test_whale_trades_repo.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from decimal import Decimal
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.db.whale_trades_repo import WhaleTradesRepo

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:Artem15@localhost:5433/polymarket")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

repo = WhaleTradesRepo(session_factory=Session)

# Уникальный tx_hash для теста
test_tx = f"test_repo_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

# Test 1: Валидная запись
result = repo.save_trade(
    wallet_address="0xTEST_REPO_001",
    market_id="test_market_001",
    side="buy",
    size_usd=Decimal("100.50"),
    price=Decimal("0.65"),
    outcome="Yes",
    market_title="Test Market",
    market_category="sports",
    tx_hash=test_tx,
    source="TRIGGER_TEST",
)
assert result == "saved", f"Test 1 FAIL: expected 'saved', got '{result}'"
print("✅ Test 1 PASS: valid trade saved")

# Test 2: Дубликат
result = repo.save_trade(
    wallet_address="0xTEST_REPO_001",
    market_id="test_market_001",
    side="buy",
    size_usd=Decimal("100.50"),
    price=Decimal("0.65"),
    tx_hash=test_tx,
    source="TRIGGER_TEST",
)
assert result == "duplicate", f"Test 2 FAIL: expected 'duplicate', got '{result}'"
print("✅ Test 2 PASS: duplicate detected")

# Test 3: Rejected — size_usd = 0
result = repo.save_trade(
    wallet_address="0xTEST_REPO_001",
    market_id="test_market_002",
    side="buy",
    size_usd=Decimal("0"),
    price=Decimal("0.50"),
    tx_hash=f"{test_tx}_zero",
    source="TRIGGER_TEST",
)
assert result == "rejected", f"Test 3 FAIL: expected 'rejected', got '{result}'"
print("✅ Test 3 PASS: zero size rejected")

# Test 4: Rejected — invalid side
result = repo.save_trade(
    wallet_address="0xTEST_REPO_001",
    market_id="test_market_003",
    side="invalid",
    size_usd=Decimal("50.0"),
    price=Decimal("0.50"),
    tx_hash=f"{test_tx}_badside",
    source="TRIGGER_TEST",
)
assert result == "rejected", f"Test 4 FAIL: expected 'rejected', got '{result}'"
print("✅ Test 4 PASS: invalid side rejected")

# Test 5: market_category missing → should save with 'unknown'
result = repo.save_trade(
    wallet_address="0xTEST_REPO_001",
    market_id="test_market_004",
    side="sell",
    size_usd=Decimal("25.0"),
    price=Decimal("0.30"),
    market_category=None,
    tx_hash=f"{test_tx}_nocat",
    source="TRIGGER_TEST",
)
assert result == "saved", f"Test 5 FAIL: expected 'saved', got '{result}'"
# Проверить что записалось 'unknown'
session = Session()
row = session.execute(
    text("SELECT market_category FROM whale_trades WHERE tx_hash = :tx"),
    {"tx": f"{test_tx}_nocat"}
).fetchone()
session.close()
assert row and row[0] == "unknown", f"Test 5b FAIL: market_category should be 'unknown', got '{row}'"
print("✅ Test 5 PASS: missing category → 'unknown'")

# Test 6: Счётчики
stats = repo.get_stats()
assert stats["saved"] == 2, f"Test 6 FAIL: saved should be 2, got {stats['saved']}"
assert stats["rejected"] == 2, f"Test 6 FAIL: rejected should be 2, got {stats['rejected']}"
assert stats["duplicates"] == 1, f"Test 6 FAIL: duplicates should be 1, got {stats['duplicates']}"
print(f"✅ Test 6 PASS: stats correct: {stats}")

# Test 7: Reset stats
old_stats = repo.reset_stats()
new_stats = repo.get_stats()
assert new_stats == {"saved": 0, "rejected": 0, "duplicates": 0}, f"Test 7 FAIL: stats not reset"
print("✅ Test 7 PASS: stats reset")

# Cleanup: удалить тестовые записи
session = Session()
session.execute(text("DELETE FROM whale_trades WHERE wallet_address = '0xtest_repo_001'"))
session.commit()
session.close()
print("🧹 Cleanup done")

print("\n🎉 ALL TESTS PASSED")
