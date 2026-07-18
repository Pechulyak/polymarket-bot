-- PIPE-052: Dedup paper_trade_notifications by whale+market+outcome+side+price
--
-- Проблема: notify_paper_trade() вставляет строку в paper_trade_notifications
-- безусловно при каждом INSERT в paper_trades. Кит, набирающий позицию серией
-- мелких сделок по одной и той же цене, получает по алерту на каждую сделку.
-- Подтверждено на живых данных 2026-07-17: кит 0x3da89a55cdd4b5c69f80e5cd3ef1782a3e0480c3,
-- market_id=0x86151b3bf91d33bd9de1f5c4fd8db28a97723b8cb131af7ebb800d06118248fb
-- (Counter-Strike: 3DMAX vs K27 - Map 2 Winner), outcome=Yes, side=buy, price=0.6 —
-- 32 записи в whale_trades, 11 в paper_trades, 11 отправленных (SENT) алертов
-- в paper_trade_notifications.
--
-- Фикс затрагивает только paper_trade_notifications / Telegram-алерты.
-- whale_trades, whale_trade_roundtrips и paper_trades не меняются — они
-- продолжают фиксировать все сделки как есть.

CREATE OR REPLACE FUNCTION notify_paper_trade()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM paper_trade_notifications
        WHERE whale_address = NEW.whale_address
          AND market_id = NEW.market_id
          AND outcome = NEW.outcome
          AND side = NEW.side
          AND price = NEW.price
    ) THEN
        RETURN NEW;
    END IF;

    INSERT INTO paper_trade_notifications (
        paper_trade_id,
        whale_address,
        market_id,
        market_title,
        side,
        price,
        size,
        size_usd,
        kelly_fraction,
        kelly_size,
        source,
        outcome,
        created_at
    ) VALUES (
        NEW.id,
        NEW.whale_address,
        NEW.market_id,
        NEW.market_title,
        NEW.side,
        NEW.price,
        NEW.size,
        NEW.size_usd,
        NEW.kelly_fraction,
        NEW.kelly_size,
        NEW.source,
        NEW.outcome,
        NEW.created_at
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
