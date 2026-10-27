---
title: "embedding-vs-full-text-search"
publishDate: "2025-08-27 02:00:00"
img: /tymultiverse/assets/algorithm.jpg
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: 深入比較Embedding向量搜索與傳統全文檢索的差異，以Maya V2專案為例，展示PostgreSQL驅動混合檢索的實際實現與最佳實踐
level: advance
category: AI
tags:
  - Embedding
  - Full Text Search
  - Vector Search
  - AI Search
  - PostgreSQL
  - GIN Index
  - Hybrid Search
  - Trigram Search
  - Maya V2
  - Synchronous Processing
  - Async I/O
---

# Embedding vs Full-text Search：AI 搜索的兩種武器

## 前言

想像你在搜尋引擎上輸入「Python 程式設計」：

**傳統全文檢索（Full-text Search）：**
- 精確字詞匹配：只找包含 "Python" 和 "程式設計" 這兩個詞的內容
- 結果範例：Python 官方文檔、程式設計入門教程、Python 程式碼範例
- 特點：精確但死板，只能找到包含這些字詞的內容

**AI 嵌入搜索（Embedding Search）：**
- 語義理解：理解 "Python 程式設計" 的真正意思
- 結果範例：不僅包含 Python，還會推薦相關的程式語言如 JavaScript、資料結構、演算法入門、軟體開發最佳實踐
- 特點：智能且靈活，能理解概念關聯和用戶意圖

**關鍵差異：**
- **Full-text Search** = 找包含特定「字詞」的內容
- **Embedding Search** = 找「意義相似」或「相關」的內容

本文將深入探討這兩種搜索技術的原理、應用場景與實作方式！

## 兩種搜索技術的核心差異

### **Full-text Search：精確匹配**
**比喻：** 像在圖書館用「書名」或「關鍵字」找書

**特點：**
- 找包含特定字詞的內容
- 精確匹配，沒有模糊空間
- 適合：精確查詢、過濾條件

**例子：**
```
查詢："machine learning"
結果：只返回包含 "machine" 和 "learning" 的文檔
```

### **Embedding Search：語義理解**
**比喻：** 像用「內容的感覺」找書

**特點：**
- 理解查詢的「意涵」，不是字面意思
- 可以找到「意義相似」的內容
- 適合：智能推薦、自然語言查詢

**例子：**
```
查詢："機器學習"
結果：可能返回包含 "AI"、"深度學習"、"神經網路" 的文檔
```

## 兩種技術的加速引擎

### **Full-text Search 的加速器：GIN Index**

#### **什麼是 GIN Index？**
**比喻：** 像一本超級詳細的「關鍵字索引表」

**核心原理：**
```sql
-- 傳統全文檢索（慢）
SELECT * FROM articles WHERE content ILIKE '%machine learning%';

-- 使用 GIN 索引（快）
CREATE INDEX idx_content_gin ON articles USING GIN (to_tsvector('english', content));
```

#### **GIN 的工作流程**
1. **文檔處理：** 將文檔分解成單詞
2. **建立倒排索引：**
   ```
   "machine" → [文檔1, 文檔5, 文檔23]
   "learning" → [文檔3, 文檔5, 文檔12]
   ```
3. **查詢匹配：** 找同時包含關鍵字的文檔交集

#### 重要概念釐清：全文索引 vs 網路請求的同步處理

**全文索引本身適合同步處理嗎？**

首先，要釐清一個概念：全文索引是後端資料庫或搜尋引擎的內部運算，而同步/非同步則是處理網路請求的模式。它們是兩個不同層次的東西。

**全文索引本身：適合同步處理**。當一個請求到達後端的全文索引服務（例如 PostgreSQL），這個服務會專注地、一步步地執行一系列複雜的運算：分詞、同義詞處理、詞幹提取，然後在倒排索引中尋找結果。這整個過程是阻塞（Blocking）且CPU 密集型的。在一個單一的執行緒中，讓它專心執行完所有步驟，通常是最簡單也最有效率的做法。

**網路請求：不適合同步處理**，特別是在高併發場景下。傳統的同步（阻塞式）I/O 模式，會為每一個網路連線分配一個專用的執行緒。當這個執行緒在等待資料從網路傳輸時，它會被「阻塞住」，無法做其他任何事情。

**「輸入即搜尋」為什麼會產生巨大的請求量？**

這是一個數學問題。假設一個網站有 10 萬個活躍使用者，其中 10% 的使用者正在使用搜尋功能。如果這個功能支援「輸入即搜尋」，每當使用者輸入一個字，就會發送一個請求。

假設一個使用者在搜尋「電動車」這個詞，他輸入的順序是：

電 (發送第 1 個請求) → 動 (發送第 2 個請求) → 車 (發送第 3 個請求)

短短幾秒內，一個使用者就發出了 3 個請求。如果同時有 1 萬個使用者都在做類似的事情，那麼在很短的時間內，你的伺服器可能會收到數萬個甚至十萬個請求。這就是所謂的「請求量瞬間暴增」。

所以，關鍵不在於全文索引是否同步，而在於「處理網路連線」的模式。Netty 提供的非阻塞 I/O，能讓伺服器在等待 A 使用者的網路資料時，可以先去處理 B 使用者的請求。它用極少的執行緒，就能應付大量且頻繁的網路連線，確保伺服器不會因為 I/O 阻塞而癱瘓。

#### PostgreSQL 全文索引 vs GIN 倒排索引的差異

這兩者並不是互斥的，而是上下層的關係：

**PostgreSQL 全文索引：完整的「功能套件」**
- 分詞器（Parser）：負責將句子拆成單詞
- 詞典（Dictionary）：負責處理同義詞、詞幹提取等
- 查詢語言：to_tsquery 和 to_tsvector 等函式
- 負責所有**「文字處理」**的邏輯

**GIN（Generalized Inverted Index）：優化的「索引結構」**
- 這是一種為全文索引優化過的資料結構
- 專門用來高效地儲存和查詢分詞後的結果

**它們的關係就像：**
- PostgreSQL 全文索引 = 圖書館管理員
- GIN 索引 = 圖書館的書架和索引卡片系統

**GIN 的作用是：**
1. 當**「圖書館管理員」**（PostgreSQL 全文索引功能）處理完一本新書（to_tsvector 處理文字）之後
2. 它會將書中的所有關鍵字及其位置，整理成一個清單
3. **「書架和索引卡片系統」**（GIN 索引）會將這些清單以倒排索引的形式，快速且有效地儲存起來
4. 當讀者來詢問「一本關於汽車的書」時，管理員會直接去翻閱索引卡片，找到「汽車」這個詞，並立刻知道它在哪些書架上，而不需要一本一本去找

所以，GIN 倒排索引本身沒有同義詞處理的能力，這個功能屬於PostgreSQL 全文索引。GIN 只是後者用來加速查詢的底層工具。

#### **實際專案實現：Maya V2 專案的 PostgreSQL 驅動全文檢索**

基於 Maya V2 專案（左下角 AI 人像切換到第二版）的實際資訊，讓我們看看這個專案的全文檢索架構實現：

**專案特點：**
- **資料庫級別**：全文檢索核心邏輯發生在 PostgreSQL 內部
- **應用級別**：Python 程式碼只負責發送 SQL 查詢，不處理文字處理邏輯
- **前端級別**：使用 debounce 機制限制請求頻率，避免過度請求

**架構比較：**

| 特性 | 這個專案（PostgreSQL 驅動） | Netty + 獨立搜尋引擎 |
|-----|----------------------------|---------------------|
| **技術棧** | PostgreSQL 資料庫 | Netty + Elasticsearch/Solr |
| **全文檢索核心** | 發生在資料庫內部，使用 pg_trgm + GIN | 發生在獨立搜尋引擎中 |
| **應用程式角色** | 只發送 SQL 查詢 | 負責請求轉發給搜尋引擎 |
| **高併發處理** | 依賴 PostgreSQL 連線池 + 前端 debounce | Netty 非阻塞 I/O |
| **適用場景** | 中小型應用，架構簡單 | 大型應用，搜尋功能複雜 |

**GIN 索引為何高效？**

GIN 索引的高效性來自於其倒排索引的本質：

1. **分治策略**：將複雜字串查詢分解為簡單的 N-gram 查找
   - 查詢「程式設計」→ 拆解為「程式」、「式設」、「設計」等
   - 每個小單位都有獨立的索引

2. **空間效率**：只儲存字元組與位置映射，不需儲存完整字串
   - 索引體積小，記憶體操作更快

3. **查詢速度**：從「全表掃描」轉化為「索引快速查找」
   - 如同圖書館的索引卡片系統，直接找到目標位置

#### Maya V2 的混合檢索架構：Embedding + Trigram

Maya V2 專案實現了一個非常聰明的**混合檢索（Hybrid Search）**架構：

**雙重檢索策略：**

1. **語義檢索（Semantic Search）**：
   ```python
   # 計算查詢向量
   query_vec = self._compute_query_embedding_safe(query.query)

   # 向量相似度搜索
   db_semantic = self._search_db_by_embedding(query_vec, k=8, threshold=0.0)
   ```

2. **字元檢索（Trigram-based）**：
   ```python
   # 全文檢索
   db_trgm = self._search_db_by_trigram(query.query or "", k=12, min_sim=0.1)

   # 加權混合分數
   sim_score = 0.6 * text_score + 0.4 * emb_score
   ```

**為何需要混合檢索？**

| 檢索方式 | 優點 | 缺點 |
|---------|-----|-----|
| **語義檢索** | 理解抽象語義，找到相關內容 | 對精確關鍵字表現較弱 |
| **字元檢索** | 精確匹配、專有名詞處理佳 | 無法理解語義關聯 |
| **混合檢索** | 結合兩者優勢，既精準又全面 | 需要權衡兩種分數 |

**權重設計：**
- 字元匹配權重 0.6（text_score）
- 語義匹配權重 0.4（emb_score）
- 確保精準度與智慧性的最佳平衡

### **Embedding Search 的加速器：IVFFlat Index**

#### **什麼是 IVFFlat Index？**
**比喻：** 像圖書館的智能分區系統

**簡單來說就是：**
- 先把相似的「東西」分門別類放好
- 搜索時不用翻遍所有區域
- 直接去最相關的區域精確查找

#### **IVFFlat 的簡單工作流程**

想像你有一個大型圖書館，想快速找到相關的書籍：

**第一步：整理書架（建立聚類）**
- 把所有書籍按照主題分成不同的「書架區」
- 比如：科技區、文學區、歷史區等
- 每個區塊放相關的書籍

**第二步：貼上標籤（記錄中心點）**
- 每個書架區放一個「主題卡片」，寫著這個區的主要內容
- 比如：科技區的卡片上寫「電腦、程式、科學」

**第三步：快速查找（智能搜索）**
- 當有人找「人工智慧」相關書籍時：
  - 先看看哪個區的主題卡片最接近「人工智慧」
  - 直接去那個區找，不用跑遍整個圖書館
  - 在那個區內仔細找最相關的書籍

#### **實際應用比較**

**傳統全文檢索（Full-text Search）：**
```python
# 精確字詞匹配
query = "machine learning"
results = database.search_text(query)
# 結果：只找包含 "machine" 和 "learning" 的內容
```

**AI向量搜索（Embedding Search）：**
```python
# 語義理解搜索
query_vector = embed_text("機器學習的概念")  # 轉換成向量
results = database.search_vector(query_vector)
# 結果：找到相關的AI、資料科學、演算法等內容
```

**⚡ IVFFlat 的優勢：**
- **速度快**：不用檢查所有資料，只檢查相關群組
- **準確度高**：在小範圍內進行精確比較
- **擴充性好**：資料量增加時效能仍保持良好

## ⚖️ 技術對比：選擇哪種搜索更適合？

### **核心差異比較**

| 特性 | Full-text Search | Embedding Search |
|-----|------------------|------------------|
| **查詢類型** | 精確關鍵字 | 自然語言 |
| **匹配方式** | 字詞匹配 | 語義相似度 |
| **查詢例子** | "machine learning" | "AI 學習的基礎概念" |
| **返回結果** | 包含關鍵字的文檔 | 意義相關的文檔 |
| **處理語言** | 依賴語言規則 | 理解語境和意涵 |
| **擴展性** | 處理大量文檔 | 需要大量計算資源 |

### **什麼情況用哪種？**

#### **用 Full-text Search 當：**
- ✅ 需要精確匹配特定術語
- ✅ 查詢是結構化的關鍵字
- ✅ 關注特定的命名實體
- ✅ 需要布林邏輯查詢（AND/OR/NOT）

#### **用 Embedding Search 當：**
- ✅ 查詢是自然語言
- ✅ 需要理解語義和意涵
- ✅ 想要智能推薦和發現
- ✅ 處理多語言或模糊查詢

## 雙雄合體：現代搜索系統的最佳實踐

### **為什麼需要結合？**

現代應用通常需要同時處理：
- **精確查詢：** 「找包含 'Python' 的文檔」
- **智能理解：** 「找類似 '機器學習入門' 的內容」

### **結合架構**

```sql
-- 建立同時支持兩種搜索的資料表
CREATE TABLE articles (
    id BIGSERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    embedding vector(768),  -- 向量表示
    
    -- 全文檢索欄位
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', title || ' ' || content)
    ) STORED
);

-- 建立雙索引
CREATE INDEX idx_vector ON articles USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_text ON articles USING GIN (search_vector);
```

### **混合搜索流程**

```python
def smart_search(query_text, k=10):
    """
    先用全文檢索縮小範圍，再用向量搜索排序
    """
    # 步驟1：全文檢索獲得候選集
    text_matches = search_by_text(query_text, limit=100)
    
    # 步驟2：在候選集中進行向量相似度計算
    query_vector = embed_text(query_text)
    
    results = []
    for doc in text_matches:
        # 結合文本匹配分數和向量相似度
        text_score = calculate_text_relevance(doc, query_text)
        vector_score = cosine_similarity(query_vector, doc.embedding)
        combined_score = 0.6 * vector_score + 0.4 * text_score
        
        results.append((doc, combined_score))
    
    # 返回最相關的結果
    return sorted(results, key=lambda x: x[1], reverse=True)[:k]
```

### **1️⃣ AI 聊天機器人**
- **Full-text：** 處理用戶的精確問題
- **Embedding：** 理解問題的語義意圖
- **結合效果：** 提供又準確又智能的回答

### **2️⃣ 電商商品搜索**
- **Full-text：** 匹配商品名稱和描述
- **Embedding：** 根據用戶偏好推薦相似商品
- **結合效果：** 提升搜索精準度和用戶體驗

### **3️⃣ 內容管理系統**
- **Full-text：** 快速過濾特定類型內容
- **Embedding：** 發現內容間的隱藏關聯
- **結合效果：** 建立智能的內容發現機制

## 實戰部署指南

### **PostgreSQL 混合搜索設置**

```sql
-- 1. 安裝擴展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 建立混合搜索表
CREATE TABLE content (
    id BIGSERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    embedding vector(768),
    text_search tsvector GENERATED ALWAYS AS (
        to_tsvector('english', title || ' ' || content)
    ) STORED
);

-- 3. 建立雙索引
CREATE INDEX idx_embedding ON content USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_text ON content USING GIN (text_search);
```

### **Python 實現示例**

```python
import psycopg2
from sentence_transformers import SentenceTransformer

class HybridSearch:
    def __init__(self):
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.conn = psycopg2.connect("your_database_url")
    
    def search(self, query, limit=10):
        # 生成查詢向量
        query_vector = self.encoder.encode(query)
        
        with self.conn.cursor() as cur:
            # 混合搜索查詢
            cur.execute("""
                SELECT id, title,
                       1 - (embedding <=> %s::vector) as vector_score,
                       ts_rank(text_search, to_tsquery('english', %s)) as text_score
                FROM content
                WHERE text_search @@ to_tsquery('english', %s)
                ORDER BY (0.7 * vector_score + 0.3 * text_score) DESC
                LIMIT %s
            """, (query_vector.tolist(), query, query, limit))
            
            return cur.fetchall()
```






## 總結：選擇適合你的搜索技術

**Embedding vs Full-text Search** 就像是選擇不同的思考方式：

### **Full-text Search**
- **像傳統圖書館員**：精確、可靠、快速
- **適合**：需要精確結果的應用
- **優勢**：簡單、穩定、高效

### **Embedding Search**
- **像AI助手**：智能、理解、創新
- **適合**：需要智能推薦的應用
- **優勢**：理解語義、發現關聯

### **最佳實踐**
現代應用通常結合兩者：
- 用 Full-text 做初步過濾
- 用 Embedding 做智能排序
- 獲得又快又準的搜索體驗

### **架構設計重點**
- **全文索引**適合同步處理，專注執行CPU密集型運算
- **網路請求**需要非同步處理，應對高併發場景
- **GIN索引**是PostgreSQL全文索引的加速引擎
- **混合檢索**結合字元匹配與語義理解的最佳實踐
- **Maya V2專案**展示PostgreSQL驅動混合檢索的實際實現

現在你不僅知道如何選擇搜索技術，還能看到Maya V2專案的完整實作範例！
