"""
Тест переключения whale_tracker на WhaleTradesRepo.
Запуск: python3 tests/test_whale_tracker_repo.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.research.whale_tracker import WhaleTracker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/polymarket"
)

# Initialize tracker
tracker = WhaleTracker(database_url=DATABASE_URL)
tracker.set_database(DATABASE_URL)

# Check repo initialized
assert tracker._whale_trades_repo is not None, "FAIL: repo not initialized"
print("✅ Test 1 PASS: repo initialized")

# Find a real whale_id for testing
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
row = session.execute(text(
    "SELECT id, wallet_address FROM whales WHERE copy_status = 'tracked' LIMIT 1"
)).fetchone()
session.close()

if not row:
    print("⚠️ No tracked whales found, skipping functional test")
else:
    whale_id = row[0]
    wallet = row[1]
    print(f"  Using whale_id={whale_id}, wallet={wallet[:10]}...")
    
    import asyncio
    
    async def test_save():
        # Test save through tracker → repo
        result = await tracker.save_whale_trade(
            whale_id=whale_id,
            market_id="test_tracker_repo_001",
            side="buy",
            size_usd=Decimal("50.0"),
            price=Decimal("0.55"),
            market_title="Test Tracker Repo",
            source="TRIGGER_TEST",
            outcome="Yes",
        )
        assert result == True, f"FAIL: expected True, got {result}"
        print("✅ Test 2 PASS: save through tracker → repo")
        
        # Verify in DB
        session = Session()
        row = session.execute(text(
            "SELECT market_category FROM whale_trades WHERE market_id = 'test_tracker_repo_001' ORDER BY id DESC LIMIT 1"
        )).fetchone()
        session.close()
        assert row is not None, "FAIL: record not found in DB"
        assert row[0] == "unknown", f"FAIL: market_category should be 'unknown', got {row[0]}"
        print("✅ Test 3 PASS: record in DB with category='unknown'")
        
        # Check repo stats
        stats = tracker._whale_trades_repo.get_stats()
        assert stats["saved"] >= 1, f"FAIL: saved should be >= 1, got {stats['saved']}"
        print(f"✅ Test 4 PASS: repo stats: {stats}")
    
    asyncio.run(test_save())
    
    # Cleanup
    session = Session()
    session.execute(text("DELETE FROM whale_trades WHERE market_id = 'test_tracker_repo_001'"))
    session.commit()
    session.close()
    print("🧹 Cleanup done")

print("\n🎉 ALL TESTS PASSED")