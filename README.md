# Maya Sawa Multi-AI Agent Q&A System

This is a powerful multi-AI agent Q&A system built with FastAPI, LangChain, and PostgreSQL (using the pgvector extension). It allows you to ask questions about your documents and receive AI-powered answers from different AI personas with distinct personalities and tones.

The system supports dynamic AI character switching, where each AI agent has unique personality traits, power levels, and response styles. Users can interact with different AI agents, each maintaining their own character profile and conversation history.

## Briefing

### Project Architecture & Extensibility

**Core Architecture Design:**

1. **Modular Configuration Management**
   - All rules, prompts, keywords, and constants are centrally managed in JSON files (`rules.json`, `prompts.json`, `keywords.json`, `constants.json`)
   - `ConfigManager` singleton pattern provides global configuration access
   - Supports dynamic configuration updates without service restart

2. **Multi-AI Agent Mode**
   - Supports dynamic switching between different AI character identities
   - Each AI agent maintains unique personality traits, power levels, and response styles
   - Automatic chat history clearing for specific users when switching characters, maintaining multi-user session isolation

3. **Intelligent Query Processing**
   - `NameDetector` automatically identifies character names in queries
   - `ProfileManager` handles character data caching and summarization
   - `PersonalityPromptBuilder` dynamically generates prompts based on AI character personality
   - Supports multi-character comparison and power analysis

4. **Vectorized Search Engine**
   - Uses PostgreSQL + pgvector for semantic search capabilities
   - Supports vectorized storage of articles, people, and weapon data
   - Automatic synchronization with external APIs and embedding generation

5. **External API Integration**
   - People System API (`/tymb/people/*`)
   - Article System API (`/paprika/articles`)
   - Weapon System API (`/tymb/weapons`)
   - Supports scheduled synchronization and real-time queries

**Extensibility Features:**

- **Add New AI Characters**: Simply add character configurations in JSON files without modifying core code
- **Custom Rules**: Easily adjust AI behavior rules, tone control, and image output formats through JSON files
- **Multi-language Support**: Supports Chinese, English, and other languages with easy extension
- **Data Source Expansion**: Easily integrate new external APIs or data sources
- **Deployment Flexibility**: Supports Docker, Kubernetes deployment with complete CI/CD pipeline

## Flow Diagrams

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

### Data Synchronization & Vector Pipeline

This diagram outlines how article, people, and weapon data are synchronized from external APIs, converted into vector embeddings, and stored in PostgreSQL for semantic search.

```mermaid
flowchart TD
    %% ---------------- Article sync ----------------
    subgraph "Article & Embedding Sync"
        RemoteAPI["Remote Article API<br/>/paprika/articles (JSON + embedding)"]
        SyncEndpoint["POST /qa/sync-from-api"]
        VectorStore["PostgresVectorStore.add_articles_from_api"]
        ArticlesTable["articles table (vector)"]
        RemoteAPI --> SyncEndpoint --> VectorStore --> ArticlesTable
    end

    %% ---------------- People & Weapons sync ----------------
    subgraph "People & Weapons Sync"
        PeopleAPI["People System API<br/>/tymb/people/get-all"]
        WeaponsAPI["People System API<br/>/tymb/weapons"]
        CronJob["k8s CronJob / scripts<br/>sync_people_weapons.py"]
        PWManager["PeopleWeaponManager.sync_all_data"]
        EmbeddingGen["OpenAI Embedding\ntext-embedding-ada-002"]
        PeopleTable["people table (vector)"]
        WeaponsTable["weapon table (vector)"]

        PeopleAPI --> PWManager
        WeaponsAPI --> PWManager
        CronJob --> PWManager

        PWManager --> EmbeddingGen
        EmbeddingGen --> PeopleTable
        EmbeddingGen --> WeaponsTable
        PWManager --> PeopleTable
        PWManager --> WeaponsTable
    end

    %% Shared DB
    ArticlesTable & PeopleTable & WeaponsTable --> DB[(PostgreSQL + pgvector)]
```

## Getting Started

<details>
<summary>Click to expand for setup and installation instructions</summary>

### Prerequisites

-   Python 3.12+
-   Poetry (Python package manager)
-   PostgreSQL 13+ with the `pgvector` extension installed
-   An OpenAI API Key

### Installation

1.  **Clone the project:**
    ```bash
    git clone https://github.com/yourusername/maya-sawa.git
    cd maya-sawa
    ```

2.  **Install dependencies with Poetry:**
    ```bash
    poetry install
    ```

3.  **Set up the PostgreSQL database:**

    You need to install the `pgvector` extension and create the necessary tables.

    **Enable `pgvector` extension:**
    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    ```

    **Create tables:**
    Run the SQL scripts in `setup_database.sql` to create the `articles`, `people`, and `weapon` tables.

4.  **Configure environment variables:**
    Copy the example `.env` file and fill in your details.
    ```bash
    cp .env.example .env
    ```
    Edit `.env` with your credentials:
    ```
    OPENAI_API_KEY=sk-your-api-key-here
    POSTGRES_CONNECTION_STRING=postgresql://username:password@localhost:5432/your_database_name
    # ... other variables
    ```

</details>

## Usage

<details>
<summary>Click to expand for usage examples</summary>

### Running the Server

Use the following command to start the development server:
```bash
poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

### API Examples

**Sync data from the API:**
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Ask a question:**
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"Who is sorane?","user_id":"dev","language":"english"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"誰是sorane?","user_id":"dev","language":"chinese"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你認識 sorane嗎?","user_id":"dev","language":"chinese"}'

curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你是誰?","user_id":"dev","language":"chinese"}'
```

**Check chat history:**
```bash
curl -X GET "http://localhost:8000/maya-sawa/qa/chat-history/dev"
```
</details>

