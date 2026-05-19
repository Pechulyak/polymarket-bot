-- TRD-443 / TASK 1.5 rollback
-- Восстановление: pnl_status для 75 строк — из pg_dump baseline

BEGIN;

-- DROP колонки is_legacy_close
ALTER TABLE whale_trade_roundtrips DROP COLUMN IF EXISTS is_legacy_close;

-- Внимание: rollback для pnl_status='LEGACY_INVALID' не делается в SQL,
-- т.к. оригинальное значение pnl_status неизвестно без baseline-snapshot.
-- Восстановление pnl_status — через baseline dump.

COMMIT;
