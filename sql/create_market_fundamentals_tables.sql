-- Low-frequency FinMind history, shared quota/checkpoint ledger, and latest
-- Shioaji quote snapshots. Safe to apply repeatedly before a Maya rollout.

CREATE TABLE IF NOT EXISTS maya_sawa_market_fundamental_history (
    id BIGSERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    code TEXT NOT NULL,
    period TEXT NOT NULL,
    item TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_market_fundamental_identity UNIQUE (dataset, code, period, item)
);

CREATE TABLE IF NOT EXISTS maya_sawa_finmind_usage (
    id BIGSERIAL PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL,
    dataset TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_maya_sawa_finmind_usage_requested_at
    ON maya_sawa_finmind_usage (requested_at DESC);

CREATE TABLE IF NOT EXISTS maya_sawa_finmind_checkpoint (
    id BIGSERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    code TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    CONSTRAINT uq_finmind_checkpoint_identity UNIQUE (dataset, code)
);

CREATE TABLE IF NOT EXISTS maya_sawa_market_quote_snapshot (
    id BIGSERIAL PRIMARY KEY,
    product_type TEXT NOT NULL,
    code TEXT NOT NULL,
    payload TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_market_quote_snapshot_identity UNIQUE (product_type, code)
);
