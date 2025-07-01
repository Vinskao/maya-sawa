-- Maya Sawa QA System 資料庫設置腳本

-- 1. 安裝 pgvector 擴展
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 創建 articles 表
CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    file_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding vector(1536)  -- OpenAI 嵌入向量維度
);

-- 3. 創建索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_file_path ON articles(file_path);
CREATE INDEX IF NOT EXISTS idx_articles_file_date ON articles(file_date);

-- 4. 創建向量索引（如果不存在）
CREATE INDEX IF NOT EXISTS idx_articles_embedding ON articles 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 5. 創建相似度搜索函數（可選，現在我們直接使用 SQL）
CREATE OR REPLACE FUNCTION similarity_search(
    query_embedding vector,
    match_threshold float,
    match_count int
)
RETURNS TABLE (
    id int,
    file_path varchar,
    content text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id,
        a.file_path,
        a.content,
        1 - (a.embedding <=> query_embedding) as similarity
    FROM articles a
    WHERE 1 - (a.embedding <=> query_embedding) > match_threshold
    ORDER BY a.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 6. 檢查表結構
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'articles'
ORDER BY ordinal_position;

-- 7. 檢查索引
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'articles'; 