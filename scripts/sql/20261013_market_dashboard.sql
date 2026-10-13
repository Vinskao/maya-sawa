-- Privacy-safe market dashboard state; never store account position values.
CREATE TABLE IF NOT EXISTS public.maya_sawa_market_dashboard_snapshot (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    positions TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_market_dashboard_snapshot UNIQUE (source, snapshot_at)
);
CREATE INDEX IF NOT EXISTS ix_market_dashboard_snapshot_latest
    ON public.maya_sawa_market_dashboard_snapshot (snapshot_at DESC);

CREATE TABLE IF NOT EXISTS public.maya_sawa_market_dashboard_setting (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    custom_symbols TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ NOT NULL
);
INSERT INTO public.maya_sawa_market_dashboard_setting (id, custom_symbols, updated_at)
VALUES (1, '[]', NOW()) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.maya_sawa_market_candidate (
    id BIGSERIAL PRIMARY KEY,
    product_type TEXT NOT NULL CHECK (product_type IN ('stock', 'futures')),
    code TEXT NOT NULL,
    delivery_month TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    CONSTRAINT uq_market_candidate_identity UNIQUE (product_type, code, delivery_month)
);
CREATE INDEX IF NOT EXISTS ix_market_candidate_expiry
    ON public.maya_sawa_market_candidate (expires_at);

CREATE TABLE IF NOT EXISTS public.maya_sawa_market_candidate_source (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL,
    product_type TEXT NOT NULL CHECK (product_type IN ('stock', 'futures')),
    code TEXT NOT NULL,
    delivery_month TEXT NOT NULL DEFAULT '',
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    CONSTRAINT uq_market_candidate_source_identity UNIQUE (source_key, product_type, code, delivery_month)
);
CREATE INDEX IF NOT EXISTS ix_market_candidate_source_expiry
    ON public.maya_sawa_market_candidate_source (expires_at);
