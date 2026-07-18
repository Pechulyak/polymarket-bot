-- PIPE-051: пересмотр HFT-фильтра
--
-- Проблема: текущий фильтр (peak_trades_per_15min > 20) флагует кандидата
-- по ЕДИНСТВЕННОМУ пику активности за всю 90-дневную историю — один
-- всплеск (ребалансировка/каскад) перевешивает всю остальную нормальную
-- торговлю. Эмпирически (scratchpad/pipe051_burst_analysis_report.md,
-- 13 живых кошельков): дропает 41 из 43 кандидатов, из них большинство —
-- false positive (peak чуть выше 20, но burst_trade_pct < 14%).
--
-- Новая метрика: доля сделок, попавших в "burst-окна" (15-мин интервалы
-- с count > 20), от общего числа сделок за 90 дней. Эмпирический разрыв
-- в данных чистый: 7 явных не-ботов — 0.97-31.25%, 5 явных ботов —
-- 78.73-99.44%. Порог 50% ложится в разрыв с запасом на обе стороны.

ALTER TABLE leaderboard_candidates
    ADD COLUMN burst_trade_pct NUMERIC(5,2);

COMMENT ON COLUMN leaderboard_candidates.burst_trade_pct IS
    'PIPE-051: доля сделок в burst-окнах (15мин, count>20) от total 90d trades. '
    'is_hft_burst = peak_trades_per_15min > 20 AND burst_trade_pct > 50.0';
