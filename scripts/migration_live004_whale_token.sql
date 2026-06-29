-- Migration: LIVE-004
-- Add token_id column to whale_trades
-- 
-- Purpose: propagate asset/token_id from Polymarket API through ingestion pipeline
-- Historical rows: NULL (fail-closed downstream — code that expects token_id 
--                  will skip rows where it's absent)
-- Rollback: DROP COLUMN IF EXISTS token_id;

DO $$
BEGIN
    -- Idempotent: check via information_schema before ALTER
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'whale_trades' 
          AND column_name = 'token_id'
    ) THEN
        ALTER TABLE whale_trades ADD COLUMN token_id text;
        RAISE NOTICE 'Column token_id added to whale_trades';
    ELSE
        RAISE NOTICE 'Column token_id already exists in whale_trades — skipping';
    END IF;
END $$;

-- Verify
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'whale_trades' 
          AND column_name = 'token_id'
    ) THEN
        RAISE NOTICE 'VERIFICATION PASSED: token_id column exists';
    ELSE
        RAISE EXCEPTION 'VERIFICATION FAILED: token_id column not found';
    END IF;
END $$;
