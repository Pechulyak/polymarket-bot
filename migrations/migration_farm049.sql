-- FARM-049: колонка competitive (Gamma API market-quality metric, 0..1,
-- источник UI-индикатора COMP на сайте Polymarket). Калибровка смысла поля
-- отдельная аналитическая задача (не в этой миграции).
ALTER TABLE farming_market_candidates
    ADD COLUMN IF NOT EXISTS competitive NUMERIC(10,8);