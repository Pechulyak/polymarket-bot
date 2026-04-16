-- =============================================================================
-- ANA-501: Whale Alert Monitor thresholds
-- =============================================================================

-- Alert thresholds for daily whale monitoring

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_paper_inactivity_days', 7, 'Days without trades for paper whale to be flagged as inactive')
ON CONFLICT (key) DO NOTHING;

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_tracked_inactivity_days', 14, 'Days without trades for tracked whale to be flagged as inactive')
ON CONFLICT (key) DO NOTHING;

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_skip_rate_threshold', 0.60, 'Skip rate threshold — if (1 - skip_rate) < threshold, flag as problematic')
ON CONFLICT (key) DO NOTHING;

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_wr_min_threshold', 0.48, 'Minimum win rate threshold for 14d rolling window')
ON CONFLICT (key) DO NOTHING;

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_candidate_min_roundtrips', 30, 'Minimum closed roundtrips for whale to become candidate')
ON CONFLICT (key) DO NOTHING;

INSERT INTO strategy_config (key, value, description) VALUES
    ('alert_candidate_min_wr', 0.55, 'Minimum win rate for whale to become candidate')
ON CONFLICT (key) DO NOTHING;
