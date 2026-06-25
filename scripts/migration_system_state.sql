-- INFRA-045: таблица system_state для cross-server heartbeat компонентов

CREATE TABLE IF NOT EXISTS system_state (
    component   text        PRIMARY KEY,
    heartbeat_at timestamptz NOT NULL,
    status      text,
    detail      jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON system_state TO order_executor;