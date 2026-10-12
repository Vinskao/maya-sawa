-- Keep every successful TWD valuation, plus one daily closing point for charting.
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

CREATE TABLE IF NOT EXISTS public.maya_sawa_taiwan_portfolio_daily_history (
    id BIGSERIAL PRIMARY KEY,
    valuation_date TEXT NOT NULL,
    valued_at TIMESTAMPTZ NOT NULL,
    total_assets NUMERIC NOT NULL,
    cash_balance NUMERIC,
    stock_market_value NUMERIC,
    futures_equity NUMERIC,
    total_pnl NUMERIC,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_tw_portfolio_daily_source_date UNIQUE (source, valuation_date)
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_taiwan_portfolio_daily_history_date
    ON public.maya_sawa_taiwan_portfolio_daily_history (valuation_date);
