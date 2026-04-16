-- Migration: ANA-502
-- Table: whale_ai_analysis
-- Purpose: Storage for weekly AI analysis results of whales
-- Created: 2026-04-16

CREATE TABLE IF NOT EXISTS whale_ai_analysis (
    id                   SERIAL PRIMARY KEY,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_used           VARCHAR(100) NOT NULL,
    raw_input_json       JSONB NOT NULL,
    raw_output_json      JSONB NOT NULL,
    recommendations_json JSONB,
    red_flags_json       JSONB,
    requires_human_review BOOLEAN NOT NULL DEFAULT TRUE,
    telegram_sent_at     TIMESTAMPTZ NULL,
    error_log            TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_whale_ai_analysis_created_at
    ON whale_ai_analysis (created_at DESC);

COMMENT ON TABLE whale_ai_analysis IS
    'Результаты еженедельного AI-анализа китов. Каждая строка — один прогон скрипта.';
