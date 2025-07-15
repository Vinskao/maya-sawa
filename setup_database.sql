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

-- ===============================================
-- 新增 people 與 weapon 資料表（供同步腳本使用）
-- ===============================================

-- People table
CREATE TABLE IF NOT EXISTS people (
    name VARCHAR(200) PRIMARY KEY,
    name_original VARCHAR(200),
    code_name VARCHAR(200),
    physic_power INT,
    magic_power INT,
    utility_power INT,
    dob DATE,
    race VARCHAR(100),
    attributes TEXT,
    gender VARCHAR(20),
    ass_size INT,
    boobs_size INT,
    height_cm INT,
    weight_kg INT,
    profession VARCHAR(200),
    combat TEXT,
    favorite_foods TEXT,
    job VARCHAR(200),
    physics TEXT,
    known_as VARCHAR(200),
    personality TEXT,
    interest TEXT,
    likes TEXT,
    dislikes TEXT,
    concubine TEXT,
    faction VARCHAR(200),
    army_id INT,
    army_name VARCHAR(200),
    dept_id INT,
    dept_name VARCHAR(200),
    origin_army_id INT,
    origin_army_name VARCHAR(200),
    gave_birth BOOLEAN,
    email VARCHAR(200),
    age INT,
    proxy TEXT,
    embedding vector(1536),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Weapon table
CREATE TABLE IF NOT EXISTS weapon (
    owner VARCHAR(200) PRIMARY KEY, -- weapon owner (person's name)
    weapon VARCHAR(200),
    attributes TEXT,
    base_damage INT,
    bonus_damage INT,
    bonus_attributes TEXT,
    state_attributes TEXT,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 向量索引
CREATE INDEX IF NOT EXISTS idx_people_embedding ON people 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_weapon_embedding ON weapon 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100); 