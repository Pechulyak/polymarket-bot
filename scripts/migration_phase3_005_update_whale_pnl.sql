-- PHASE3-005: SQL функция для full recompute P&L китов
-- Заменяет инкрементальный Python-метод _update_whales_pnl()

CREATE OR REPLACE FUNCTION update_whale_pnl_from_roundtrips(p_wallet_address VARCHAR DEFAULT NULL)
RETURNS TABLE(updated_count INT) AS $$
DECLARE
    v_updated INT := 0;
BEGIN
    UPDATE whales w
    SET 
        win_count = sub.wins,
        loss_count = sub.losses,
        total_roundtrips = sub.total,
        total_pnl_usd = sub.total_pnl,
        avg_pnl_usd = sub.avg_pnl,
        win_rate_confirmed = CASE 
            WHEN sub.total > 0 THEN sub.wins::DECIMAL / sub.total 
            ELSE 0 
        END,
        last_pnl_updated = NOW()
    FROM (
        SELECT 
            wallet_address,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE net_pnl_usd > 0) as wins,
            COUNT(*) FILTER (WHERE net_pnl_usd <= 0) as losses,
            COALESCE(SUM(net_pnl_usd), 0) as total_pnl,
            COALESCE(AVG(net_pnl_usd), 0) as avg_pnl
        FROM whale_trade_roundtrips
        WHERE status = 'CLOSED'
        GROUP BY wallet_address
    ) sub
    WHERE w.wallet_address = sub.wallet_address
      AND (p_wallet_address IS NULL OR w.wallet_address = p_wallet_address);
    
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN QUERY SELECT v_updated;
END;
$$ LANGUAGE plpgsql;