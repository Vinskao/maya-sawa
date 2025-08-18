# Maya Sawa Multi-AI Agent Q&A System

## Getting Started

### Running the Server

Use the following command to start the development server:
```bash
poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

## System Architecture

### API to Chain Flow

This diagram illustrates the process from receiving a user's API request to generating a response via the `QAChain`.

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

### QAChain Internal Logic

This diagram shows the internal decision-making process within the `QAChain` when handling a query.

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

### System Architecture (External APIs & Data Stores)

This diagram shows how the internal layers interact with each other and with all external services (databases, OpenAI, and public APIs).

```mermaid
flowchart TD
    subgraph "API Layer"
        APIRouter["FastAPI Router<br/>(maya_sawa/api/qa.py)"]
    end

    subgraph "Q&A Layer"
        QAEngine["QAEngine"]
        QAChain["QAChain"]
    end

    subgraph "Support Layer"
        NameDetector["NameDetector"]
        ProfileManager["ProfileManager"]
        PeopleWeaponManager["PeopleWeaponManager"]
        PersonalityPromptBuilder["PersonalityPromptBuilder"]
        NameAdapter["NameAdapter"]
        VectorStore["PostgresVectorStore"]
        ChatHistoryManager["ChatHistoryManager"]
    end

    subgraph "External Services"
        OpenAIAPI["OpenAI API<br/>Chat & Embeddings"]
        PeopleAPI["People System API<br/>/tymb/people/*"]
        ArticleAPI["Public Article API<br/>/paprika/articles"]
        PostgresDB["PostgreSQL"]
    end

    Client["Client / Frontend"] --> APIRouter
    APIRouter --> QAEngine
    QAEngine --> QAChain
    APIRouter --> VectorStore
    APIRouter --> ChatHistoryManager

    ChatHistoryManager --> PostgresDB

    QAChain --> NameDetector
    QAChain --> ProfileManager
    QAChain --> PeopleWeaponManager
    QAChain --> PersonalityPromptBuilder
    QAChain --> NameAdapter
    QAChain --> VectorStore

    NameDetector --> OpenAIAPI
    QAChain --> OpenAIAPI

    ProfileManager --> PeopleAPI
    PeopleWeaponManager --> PeopleAPI

    VectorStore --> PostgresDB
    VectorStore --> ArticleAPI

    PeopleWeaponManager --> PostgresDB
```

## API Examples

```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
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

