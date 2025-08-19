# Maya Sawa Multi-AI Agent Q&A System

一個基於多 AI 代理的智能問答系統，整合了角色扮演、文檔檢索和語義搜索能力。

## AI 能力概述

### 多人格 AI 代理
- **角色扮演系統**：支援多角色對話，每個角色具有獨特的性格和背景設定
- **智能名稱檢測**：自動識別查詢中的人物名稱，提供個性化回應
- **動態人格建構**：根據角色檔案動態生成符合角色特質的對話風格

### 智能文檔檢索與問答
- **向量化搜索**：使用 OpenAI Embeddings 進行語義相似度搜索
- **RAG (Retrieval-Augmented Generation)**：結合檢索和生成，提供準確的基於文檔的回答
- **多語言支援**：支援中文和英文雙語問答，自動翻譯回應
- **頁面內容分析**：提供網頁內容摘要、重點提取、技術分析等功能

### 智能數據同步
- **自動文章同步**：從外部 API 自動同步文章並生成向量嵌入
- **人員武器數據管理**：同步和管理角色、武器等相關數據
- **預計算嵌入支援**：支援使用預計算的向量嵌入，提升同步效率
- **定期同步排程**：可配置的定期數據同步機制

### 對話管理
- **多用戶對話歷史**：支援多用戶獨立的對話記錄管理
- **Redis 快取**：高效的對話歷史存儲和檢索
- **上下文感知**：基於歷史對話提供連貫的回應

## Getting Started


```bash
poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

## System Architecture

```mermaid
graph TD
    A["User Request</br>(/qa/query)"] --> B{FastAPI Router};
    B --> C["qa_chain.get_answer(query)"];
    C --> D{"Detect names in query"};
    D -- "Names found" --> E["Fetch character profiles</br>from DB"];
    E --> F["Create prompt with</br>character profile"];
    F --> G["Invoke LLM"];
    D -- "No names found" --> H["Similarity search</br>in Vector Store"];
    H --> I["Create prompt with</br>document context"];
    I --> G;
    G --> J["Return AI answer"];
    J --> B;
```



```mermaid
graph TD
    A["get_answer(query)"] --> B{"Detect names"};
    B -- "Name(s) found" --> C{"Fetch profiles"};
    C -- "Profile found" --> D["Generate answer from profile"];
    C -- "Profile not found" --> E["Respond 'not found'"];
    B -- "No names found" --> F{"Semantic search for people"};
    F -- "People found" --> G["Generate answer from search results"];
    F -- "No one found" --> H["RAG from documents"];
    D --> I["Return final answer"];
    E --> I;
    G --> I;
    H --> I;
```

```mermaid
flowchart TD
    subgraph "API Layer"
        APIRouter["FastAPI Router<br/>(maya_sawa/api/qa.py)"]
    end

    subgraph "Q&A Layer"
        QAChain["QAChain"]
        PageAnalyzer["PageAnalyzer"]
    end

    subgraph "Support Layer"
        NameDetector["NameDetector"]
        ProfileManager["ProfileManager"]
        PeopleWeaponManager["PeopleWeaponManager"]
        PersonalityPromptBuilder["PersonalityPromptBuilder"]
        NameAdapter["NameAdapter"]
        VectorStore["PostgresVectorStore"]
        ChatHistoryManager["ChatHistoryManager"]
        ConfigManager["ConfigManager"]
        ConnectionPoolManager["ConnectionPoolManager"]
        Scheduler["ArticleSyncScheduler"]
    end

    subgraph "External Services"
        OpenAIAPI["OpenAI API<br/>Chat & Embeddings"]
        PeopleAPI["People System API<br/>/tymb/people/*"]
        ArticleAPI["Public Article API<br/>/paprika/articles"]
        PostgresDB["PostgreSQL"]
        RedisDB["Redis"]
    end

    Client["Client / Frontend"] --> APIRouter
    APIRouter --> QAChain
    APIRouter --> PageAnalyzer
    APIRouter --> VectorStore
    APIRouter --> ChatHistoryManager
    APIRouter --> Scheduler

    ChatHistoryManager --> RedisDB

    QAChain --> NameDetector
    QAChain --> ProfileManager
    QAChain --> PeopleWeaponManager
    QAChain --> PersonalityPromptBuilder
    QAChain --> NameAdapter
    QAChain --> VectorStore

    PageAnalyzer --> QAChain

    NameDetector --> OpenAIAPI
    QAChain --> OpenAIAPI

    ProfileManager --> PeopleAPI
    PeopleWeaponManager --> PeopleAPI

    VectorStore --> PostgresDB
    VectorStore --> ArticleAPI

    PeopleWeaponManager --> PostgresDB

    ConfigManager --> PostgresDB
    ConnectionPoolManager --> PostgresDB
    Scheduler --> ArticleAPI
```

## API Examples

```bash
# Sync articles
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{}'

# Force local embedding
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-articles" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"Who is Sorane?","user_id":"dev","language":"english","name":"Maya","frontend_source":"/tymultiverse"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"誰是Sorane?","user_id":"dev","language":"chinese","name":"Maya","frontend_source":"/tymultiverse"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你認識 Sorane嗎?","user_id":"dev","language":"chinese","name":"Maya","frontend_source":"/tymultiverse"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你是誰?","user_id":"dev","language":"chinese","name":"Maya","frontend_source":"/tymultiverse"}'
```

```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"什麼是Java開發?","user_id":"dev","language":"chinese","name":"Maya","frontend_source":"/tymultiverse"}'

curl -X POST "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"什麼是Java開發?","user_id":"dev","language":"chinese","name":"Maya"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"什麼是Java開發?","user_id":"dev","language":"chinese","name":"Maya"}'
```

```bash
curl -X GET "http://localhost:8000/maya-sawa/qa/chat-history/dev"
```

## Environment Variables

- `OPENAI_API_KEY`: OpenAI API key
- `OPENAI_ORGANIZATION`: OpenAI organization ID
- `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`: PostgreSQL connection
- `REDIS_HOST`, `REDIS_CUSTOM_PORT`, `REDIS_PASSWORD`: Redis connection
- `MATCH_COUNT`: Number of documents to retrieve (default: 3)
- `SIMILARITY_THRESHOLD`: Similarity threshold for document matching (default: 0.5)
- `FORCE_LOCAL_EMBEDDING`: Force local embedding computation, ignore upstream embeddings (default: false)
- `VALIDATE_UPSTREAM_EMBEDDING`: Validate upstream embeddings before use (default: true)
- `ENABLE_AUTO_SYNC_ON_STARTUP`: Auto-sync on application startup (default: false)
- `ENABLE_PERIODIC_SYNC`: Enable periodic article sync (default: false)
- `ENABLE_PEOPLE_WEAPONS_SYNC`: Enable people/weapons data sync (default: false)

## Deployment

```bash
docker build -t papakao/maya-sawa:latest .
```

```bash
poetry install
poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

## Troubleshooting

```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-articles" \
  -H "Content-Type: application/json" \
  -d '{}'
```

