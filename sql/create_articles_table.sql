-- Migration script to create missing tables in Neon
-- Targets: Neon PeopleSystem database

CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    file_date TIMESTAMP NOT NULL,
    embedding TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
);

COMMENT ON TABLE articles IS 'Articles migrated from Paprika Laravel application';
