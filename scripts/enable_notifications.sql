-- Script to re-enable paper_trade_notifications trigger
-- Run this script to RESUME notifications:
--   docker exec polymarket-postgres-1 psql -U postgres -d polymarket -f /docker-entrypoint-initdb.d/enable_notifications.sql

-- Recreate the notification trigger on paper_trades
CREATE TRIGGER trigger_notify_paper_trade
AFTER INSERT ON paper_trades
FOR EACH ROW
EXECUTE FUNCTION notify_paper_trade();

-- Verify trigger is created
-- SELECT tgname, tgrelid::regclass FROM pg_trigger WHERE tgname = 'trigger_notify_paper_trade';
