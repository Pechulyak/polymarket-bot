-- Script to disable paper_trade_notifications trigger for Whale Observation Mode
-- Run this script to SUSPEND notifications:
--   docker exec polymarket-postgres-1 psql -U postgres -d polymarket -f /docker-entrypoint-initdb.d/disable_notifications.sql

-- Drop the notification trigger on paper_trades
DROP TRIGGER IF EXISTS trigger_notify_paper_trade ON paper_trades;

-- Optional: Disable the trigger function (keep for potential re-enable)
-- The function notify_paper_trade() is preserved but not called

-- Verify trigger is dropped
-- SELECT tgname FROM pg_trigger WHERE tgname = 'trigger_notify_paper_trade';
