-- Migration FARM-024: Add sizing columns to farming_active_markets
-- Adds: min_size, inv_center, inv_deadband, max_inv, weight
-- Required for markets.json export (FARM-015-lite)

ALTER TABLE farming_active_markets
  ADD COLUMN IF NOT EXISTS min_size NUMERIC(20,8) NOT NULL DEFAULT 200,
  ADD COLUMN IF NOT EXISTS inv_center NUMERIC(20,8) NOT NULL DEFAULT 200,
  ADD COLUMN IF NOT EXISTS inv_deadband NUMERIC(20,8) NOT NULL DEFAULT 200,
  ADD COLUMN IF NOT EXISTS max_inv NUMERIC(20,8) NOT NULL DEFAULT 400,
  ADD COLUMN IF NOT EXISTS weight NUMERIC(10,4) NOT NULL DEFAULT 1;

-- Update New People 2nd seats (id=1): inv_deadband = 200 (from MARKETS dict)
UPDATE farming_active_markets
SET inv_deadband = 200
WHERE id = 1;

-- Update AI 1530 Arena by Sep30 (id=2): inv_deadband = 100 (from MARKETS dict)
UPDATE farming_active_markets
SET inv_deadband = 100
WHERE id = 2;
