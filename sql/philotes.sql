-- Enable pgvector extension for vector operations
CREATE EXTENSION IF NOT EXISTS vector;

-- ======================
-- Table: articles
-- ======================
DROP TABLE IF EXISTS articles;

CREATE TABLE articles (
  id BIGSERIAL PRIMARY KEY,
  file_path VARCHAR(500) UNIQUE NOT NULL,
  content TEXT NOT NULL,
  file_date TIMESTAMP NOT NULL,
  created_at TIMESTAMP NULL,
  updated_at TIMESTAMP NULL,
  deleted_at TIMESTAMP NULL,
  embedding vector(1536)
);

-- 索引
CREATE INDEX articles_file_date_index ON articles (file_date);

-- 啟用擴充
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 只對 content 建 trigram 索引（中文友好）
CREATE INDEX IF NOT EXISTS idx_articles_content_trgm
  ON articles USING GIN (content gin_trgm_ops);