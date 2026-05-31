-- Platform DB schema (DATABASE_URL / Neon)
-- Run: psql $DATABASE_URL -f src/claude_agent_platform/db/migrations/001_init.sql

CREATE TABLE IF NOT EXISTS platform_users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    department  TEXT,
    entity      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_platform_users_entity ON platform_users(entity);

CREATE TABLE IF NOT EXISTS agent_chats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
    agent_type      TEXT NOT NULL,
    title           TEXT,
    sdk_session_id  TEXT,
    total_input_tokens              BIGINT NOT NULL DEFAULT 0,
    total_output_tokens             BIGINT NOT NULL DEFAULT 0,
    total_cache_read_input_tokens   BIGINT NOT NULL DEFAULT 0,
    total_cache_creation_input_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost_usd                  NUMERIC(12, 6) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_chats_user_agent
    ON agent_chats(user_id, agent_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         UUID NOT NULL REFERENCES agent_chats(id) ON DELETE CASCADE,
    seq             INT NOT NULL,
    sdk_type        TEXT NOT NULL,
    payload         JSONB NOT NULL,
    turn_input_tokens               INT,
    turn_output_tokens              INT,
    turn_cache_read_input_tokens    INT,
    turn_cache_creation_input_tokens INT,
    turn_cost_usd                   NUMERIC(12, 6),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_chat_seq ON agent_messages(chat_id, seq);
