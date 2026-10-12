-- TWD valuations only. valued_at is the source timestamp, not the page-read time.
CREATE TABLE IF NOT EXISTS public.maya_sawa_taiwan_portfolio_history (
    id BIGSERIAL PRIMARY KEY,
    valued_at TIMESTAMPTZ NOT NULL,
    total_assets NUMERIC NOT NULL,
    cash_balance NUMERIC,
    stock_market_value NUMERIC,
    futures_equity NUMERIC,
    total_pnl NUMERIC,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tw_portfolio_source_time UNIQUE (source, valued_at)
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_taiwan_portfolio_history_valued_at
    ON public.maya_sawa_taiwan_portfolio_history (valued_at);
