-- FARM-023: thin_book фильтр — dollar depth в пределах max_spread от мида
-- Добавлены колонки: bid_depth_usd, ask_depth_usd, thin_book

ALTER TABLE farming_market_candidates
    ADD COLUMN IF NOT EXISTS bid_depth_usd NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS ask_depth_usd NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS thin_book BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN farming_market_candidates.bid_depth_usd IS 'sum(price*size) по bids с |price-mid| < max_spread';
COMMENT ON COLUMN farming_market_candidates.ask_depth_usd IS 'sum((1-price)*size) по asks с |price-mid| < max_spread';
COMMENT ON COLUMN farming_market_candidates.thin_book IS 'TRUE если min(bid,ask)_depth_usd < THIN_BOOK_MULT * our_size_per_side';
