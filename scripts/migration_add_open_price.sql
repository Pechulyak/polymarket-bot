-- Migration: Add open_price and rename price → close_price
-- Date: 2026-03-16
-- Purpose: Separate entry price from exit/settlement price in trades table

BEGIN;

-- Step 1: Add open_price column
ALTER TABLE trades ADD COLUMN IF NOT EXISTS open_price NUMERIC(20, 8);

-- Step 2: Backfill open_price for existing records
-- For OPEN positions: open_price = current price (which is entry price)
-- For CLOSED positions: we need to reconstruct from paper_trades or leave NULL
-- Since we can't reliably reconstruct for closed positions, we'll set open_price = price for open only

UPDATE trades 
SET open_price = price 
WHERE status = 'open' AND open_price IS NULL;

-- Step 3: Rename price to close_price
ALTER TABLE trades RENAME COLUMN price TO close_price;

-- Step 4: Ensure close_price can be NULL for open positions
ALTER TABLE trades ALTER COLUMN close_price DROP NOT NULL;

-- Step 5: Add comment for documentation
COMMENT ON COLUMN trades.open_price IS 'Entry price when position was opened (from paper_trades.price)';
COMMENT ON COLUMN trades.close_price IS 'Exit/settlement price when position was closed (1.0 for winner, 0.0 for loser, or actual sell price)';

COMMIT;

-- Verification query
SELECT 
    status,
    COUNT(*) as count,
    COUNT(open_price) as open_price_filled,
    COUNT(close_price) as close_price_filled
FROM trades 
GROUP BY status;
