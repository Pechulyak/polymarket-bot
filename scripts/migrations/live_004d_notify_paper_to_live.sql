-- LIVE-004 PART D: Notify trigger on paper_trades → live_copy channel
-- Applied to DB via draft migration_live004.sql (2026-06-29)
-- Extracted from draft at HYG cleanup 2026-07-11
-- Channel listener: scripts/copy_paper_to_live.py (git-tracked)
-- Note: current live-executor works in pull-model; this trigger is active but
-- the live_copy daemon (copy_paper_to_live.py) uses polling, not pg_notify listener.

-- ============================================================
-- PART D: NOTIFY TRIGGER on paper_trades
-- ============================================================
-- Существующий PIPE-048 триггер trigger_notify_paper_trade — НЕ затрагивается.
-- Новый триггер trigger_notify_paper_trade_to_live — отдельная строка в pg_trigger.
--
-- Фактические триггеры на paper_trades ДО применения:
--   trigger_notify_paper_trade  (PIPE-048, существующий)
--
-- Триггеры на paper_trades ПОСЛЕ применения:
--   trigger_notify_paper_trade       (PIPE-048, без изменений)
--   trigger_notify_paper_trade_to_live (LIVE-004, новый)

-- Новая функция: шлёт pg_notify('live_copy', NEW.id::text)
-- Канал: 'live_copy' — демон copy_paper_to_live.py слушает этот канал
CREATE OR REPLACE FUNCTION public.notify_paper_trade_to_live()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    PERFORM pg_notify('live_copy', NEW.id::text);
    RETURN NEW;
END;
$function$;

-- Триггер AFTER INSERT ON paper_trades
DROP TRIGGER IF EXISTS trigger_notify_paper_trade_to_live ON paper_trades;

CREATE TRIGGER trigger_notify_paper_trade_to_live
    AFTER INSERT ON paper_trades
    FOR EACH ROW
    EXECUTE FUNCTION notify_paper_trade_to_live();
