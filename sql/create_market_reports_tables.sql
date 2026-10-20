-- Requires the production pgvector extension (vector 0.8.4).
CREATE TABLE IF NOT EXISTS maya_sawa_market_reports (
    id text PRIMARY KEY,
    title text NOT NULL,
    publisher text NOT NULL DEFAULT '',
    published_at date,
    received_at timestamptz NOT NULL,
    uploaded_by text NOT NULL,
    sha256 text NOT NULL UNIQUE,
    page_count integer NOT NULL,
    text text NOT NULL,
    visibility text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'owner')),
    status text NOT NULL DEFAULT 'extracted' CHECK (status IN ('extracted', 'embedded', 'claims_pending', 'ready', 'failed')),
    failure_reason text,
    pdf bytea NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_market_reports_uploaded_by ON maya_sawa_market_reports(uploaded_by);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_market_reports_received_at ON maya_sawa_market_reports(received_at DESC);

CREATE TABLE IF NOT EXISTS maya_sawa_market_report_chunks (
    id text PRIMARY KEY,
    report_id text NOT NULL REFERENCES maya_sawa_market_reports(id) ON DELETE CASCADE,
    page integer NOT NULL,
    seq integer NOT NULL,
    text text NOT NULL,
    embedding vector(1536) NOT NULL,
    UNIQUE (report_id, page, seq)
);
CREATE INDEX IF NOT EXISTS ix_market_report_chunks_embedding_hnsw
    ON maya_sawa_market_report_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_market_report_chunks_report_id ON maya_sawa_market_report_chunks(report_id);

CREATE TABLE IF NOT EXISTS maya_sawa_market_report_claims (
    id text PRIMARY KEY,
    report_id text NOT NULL REFERENCES maya_sawa_market_reports(id) ON DELETE CASCADE,
    page integer NOT NULL,
    segment text NOT NULL,
    codes text[] NOT NULL DEFAULT '{}',
    dimension text NOT NULL,
    direction text NOT NULL,
    claim text NOT NULL,
    evidence text NOT NULL,
    as_of date,
    extracted_by text,
    extracted_at timestamptz,
    CHECK (direction IN ('tailwind', 'neutral', 'headwind')),
    CHECK (dimension IN ('cycle', 'technology', 'delivery', 'macro', 'timing'))
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_market_report_claims_report_id ON maya_sawa_market_report_claims(report_id);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_market_report_claims_codes ON maya_sawa_market_report_claims USING gin(codes);
