-- Whale Detection DB Truth Queries
-- Use these queries to verify whale detection state from database

-- ============================================================
-- 1. Whale Status Counts (discovered/qualified/ranked)
-- ============================================================
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN status = 'discovered' THEN 1 ELSE 0 END) as discovered,
    SUM(CASE WHEN status = 'qualified' THEN 1 ELSE 0 END) as qualified,
    SUM(CASE WHEN status = 'ranked' THEN 1 ELSE 0 END) as ranked
FROM whales;

-- ============================================================
-- 2. Top Whales by Volume (for ranking)
-- ============================================================
SELECT 
    wallet_address,
    total_trades,
    total_volume_usd,
    win_rate,
    risk_score,
    status,
    trades_last_3_days,
    days_active,
    last_active_at
FROM whales 
ORDER BY total_volume_usd DESC 
LIMIT 10;

-- ============================================================
-- 3. Qualification Analysis (why whales are not qualified)
-- ============================================================
SELECT 
    wallet_address,
    total_trades,
    total_volume_usd,
    win_rate,
    risk_score,
    status,
    trades_last_3_days,
    days_active,
    -- Qualification criteria check
    CASE WHEN total_trades >= 10 THEN 'PASS' ELSE 'FAIL' END as min_trades_check,
    CASE WHEN total_volume_usd >= 500 THEN 'PASS' ELSE 'FAIL' END as min_volume_check,
    CASE WHEN trades_last_3_days >= 3 THEN 'PASS' ELSE 'FAIL' END as activity_check,
    CASE WHEN days_active >= 1 THEN 'PASS' ELSE 'FAIL' END as days_active_check
FROM whales 
ORDER BY total_volume_usd DESC;

-- ============================================================
-- 4. Risk Score Distribution
-- ============================================================
SELECT 
    risk_score,
    COUNT(*) as count,
    AVG(total_volume_usd) as avg_volume
FROM whales 
GROUP BY risk_score 
ORDER BY risk_score;

-- ============================================================
-- 5. Whale Activity Summary
-- ============================================================
SELECT 
    is_active,
    status,
    COUNT(*) as count,
    MAX(last_active_at) as last_active
FROM whales 
GROUP BY is_active, status;

-- ============================================================
-- 6. Qualification Blockers Report
-- ============================================================
-- Shows which qualification gates are blocking whales from being qualified
SELECT 
    'min_trades (10)' as gate,
    COUNT(*) as blocked_count,
    STRING_AGG(LEFT(wallet_address, 10), ', ') as examples
FROM whales 
WHERE total_trades < 10 AND status = 'discovered'
UNION ALL
SELECT 
    'min_volume ($500)' as gate,
    COUNT(*) as blocked_count,
    STRING_AGG(LEFT(wallet_address, 10), ', ') as examples
FROM whales 
WHERE total_volume_usd < 500 AND status = 'discovered'
UNION ALL
SELECT 
    'trades_last_3_days (3)' as gate,
    COUNT(*) as blocked_count,
    STRING_AGG(LEFT(wallet_address, 10), ', ') as examples
FROM whales 
WHERE trades_last_3_days < 3 AND status = 'discovered'
UNION ALL
SELECT 
    'days_active (1)' as gate,
    COUNT(*) as blocked_count,
    STRING_AGG(LEFT(wallet_address, 10), ', ') as examples
FROM whales 
WHERE days_active < 1 AND status = 'discovered';