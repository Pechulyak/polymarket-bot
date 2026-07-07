-- FARM-022: Расширение farming_market_candidates для farm_screen v4.9
-- Добавляет колонки критичные для farmability и дайджест/degredation-мониторинга
-- Миграция идёт в одном коммите с farm_screen.py changes

BEGIN;

-- 1. Наша целевая метрика: доход НАШЕЙ ноги ($/день)
ALTER TABLE farming_market_candidates
    ADD COLUMN IF NOT EXISTS our_daily_usd NUMERIC(20, 8);

-- 2. yield fraction (для сравнения при разном капитале: our_daily / required_capital)
--    est_daily_yield_pct существовала ранее, теперь пересчитывается из our_daily
--    ПЕРЕИСПОЛЬЗУЕМ существующую колонку (foreign key в другие модули — НЕ трогаем)

-- 3. Критичные фильтр-поля (farmability):
ALTER TABLE farming_market_candidates
    ADD COLUMN IF NOT EXISTS fees_enabled BOOLEAN,
    ADD COLUMN IF NOT EXISTS neg_risk BOOLEAN,
    ADD COLUMN IF NOT EXISTS tick NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS moves2c INTEGER,
    ADD COLUMN IF NOT EXISTS dead_book BOOLEAN;

-- 4. gamma_id уже был NOT NULL в схеме (добавлен при создании)
--    Проверяем консистентность: gamma_id должен быть NOT NULL
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'farming_market_candidates'
        AND column_name = 'gamma_id'
        AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE farming_market_candidates
            ALTER COLUMN gamma_id SET NOT NULL;
    END IF;
END
$$;

-- 5. Комментарии для документирования
COMMENT ON COLUMN farming_market_candidates.our_daily_usd IS 'Доход НАШЕЙ ноги OUR_SIZE шер: our_share × pool ($/день). Lead metric v4.9.';
COMMENT ON COLUMN farming_market_candidates.fees_enabled IS 'feesEnabled из Gamma: есть ли rebate program.';
COMMENT ON COLUMN farming_market_candidates.neg_risk IS 'negRisk из Gamma: negative risk market.';
COMMENT ON COLUMN farming_market_candidates.tick IS 'orderPriceMinTickSize из Gamma: ценовой шаг рынка.';
COMMENT ON COLUMN farming_market_candidates.moves2c IS 'Число движений >=2c за 7д из /prices-history: прокси волатильности.';
COMMENT ON COLUMN farming_market_candidates.dead_book IS 'TRUE если книга пуста (book_pts=0): adverse selection максимален, фармить нельзя.';

COMMIT;
