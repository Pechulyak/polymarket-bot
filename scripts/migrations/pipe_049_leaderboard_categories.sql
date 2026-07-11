-- PIPE-049: Category-based leaderboard fetch
-- Adds category tracking to leaderboard_candidates.
-- best_category — категория с максимальным pnl кандидата среди категорий, где он попал в топ-N.
-- categories    — CSV-список всех категорий с попаданием в топ-N (формат: "POLITICS:1,TECH:5").

ALTER TABLE leaderboard_candidates
    ADD COLUMN IF NOT EXISTS best_category VARCHAR(32),
    ADD COLUMN IF NOT EXISTS categories    TEXT;

COMMENT ON COLUMN leaderboard_candidates.best_category IS
    'Категория leaderboard с максимальным pnl кандидата (PIPE-049)';
COMMENT ON COLUMN leaderboard_candidates.categories IS
    'CSV: CATEGORY:rank пар для всех категорий, где кандидат в топ-N (PIPE-049)';
