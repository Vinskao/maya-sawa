-- Public daily exchange history for selected market dashboard instruments.
CREATE TABLE IF NOT EXISTS public.maya_sawa_market_daily_history (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL,
    product_type TEXT NOT NULL CHECK (product_type IN ('stock', 'futures')),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    trading_date DATE NOT NULL,
    values_json TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_market_daily_history_identity
        UNIQUE (source_key, product_type, code, trading_date)
);
CREATE INDEX IF NOT EXISTS ix_market_daily_history_code_date
    ON public.maya_sawa_market_daily_history (code, trading_date DESC);

CREATE TABLE IF NOT EXISTS public.maya_sawa_market_history_coverage (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL,
    code TEXT NOT NULL,
    trading_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'no_data', 'error')),
    record_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    checked_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_market_history_coverage_identity
        UNIQUE (source_key, code, trading_date)
);
CREATE INDEX IF NOT EXISTS ix_market_history_coverage_code_date
    ON public.maya_sawa_market_history_coverage (code, trading_date DESC);
