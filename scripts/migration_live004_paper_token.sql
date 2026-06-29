-- Migration: LIVE-004_paper_token
-- Adds token_id column to paper_trades table (nullable, idempotent)
-- Date: 2026-06-29
-- Author: Roo (auto-generated)

ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS token_id text;

-- Verify the column was added
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'paper_trades' AND column_name = 'token_id'
    ) THEN
        RAISE NOTICE 'Column token_id successfully added to paper_trades';
    ELSE
        RAISE WARNING 'Column token_id may not have been added - please verify';
    END IF;
END $$;
