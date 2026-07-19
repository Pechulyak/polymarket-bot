-- ACT: добавление deposit-событий (source='csv') в account_activity
-- Обоснование: data-api /activity депозиты не отдаёт; condition_id/slug для
-- депозита не существуют (не привязан к рынку) -> делаем nullable.
-- source разделяет происхождение записи (api-бэкфилл/крон vs ручной csv-импорт).

BEGIN;

ALTER TABLE account_activity
    ADD COLUMN source text NOT NULL DEFAULT 'api';

ALTER TABLE account_activity
    ALTER COLUMN condition_id DROP NOT NULL;

ALTER TABLE account_activity
    ALTER COLUMN slug DROP NOT NULL;

CREATE UNIQUE INDEX idx_activity_unique_deposit
    ON account_activity (account, tx_hash)
    WHERE event_type = 'DEPOSIT';

COMMIT;
-- Применена вручную оператором (confirmed) 2026-07-19, см. changelogs/CHANGELOG.md ACT-004
