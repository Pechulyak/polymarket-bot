-- ACT-008: account_activity.trade_role — реальная роль (maker/taker) по каждой
-- TRADE-строке, определённая сопоставлением с on-chain событием OrderFilled
-- (CTFExchange и NegRiskCTFExchange — см. scripts/backfill_trade_role.py).
-- Заменяет универсальную оценку "всегда как если бы taker" на подтверждённую
-- роль: MAKER = комиссия $0 (TRD-448), TAKER = комиссия по формуле TRD-448,
-- NULL = не сопоставлено (редкий multi-leg случай, ~0.7% строк) — откат на
-- прежнюю оценочную формулу в build_account_daily_ledger.py.

BEGIN;

ALTER TABLE account_activity ADD COLUMN IF NOT EXISTS trade_role TEXT;
COMMENT ON COLUMN account_activity.trade_role IS 'ACT-008: MAKER | TAKER | NULL (не сопоставлено с on-chain), определено сопоставлением с событием OrderFilled по сумме/цене/стороне сделки.';

COMMIT;
