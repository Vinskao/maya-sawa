"""
數據庫模組 (Databases Module)

這就像 Java 的 package 一樣，是數據庫相關類的集合。

目的：
- 統一管理所有數據庫操作
- 提供簡潔的導入接口
- 保持向後兼容性

包含的數據庫模組：
1. QA 向量數據庫 (qa_vector_db.py):
   - 負責文檔的向量嵌入存儲
   - 支持相似度搜索 (就像 Elasticsearch)
   - 對應 Java 的 DocumentRepository + VectorService

2. 文章數據庫 (article_db.py):
   - 文章的 CRUD 操作 (創建、讀取、更新、刪除)
   - 批量處理和同步功能
   - 對應 Java 的 ArticleRepository + ArticleService

3. 對話數據庫 (conversation_db.py):
   - 聊天對話的管理
   - AI 模型配置
   - 異步任務處理
   - 對應 Java 的 ConversationRepository + AIModelService

設計模式：
- 單例模式：每個數據庫類都使用單例確保連接重用
- 工廠模式：通過 get_xxx_db() 函數獲取實例
- 倉儲模式：封裝所有數據庫操作邏輯

使用方式就像 Java：
```java
// Java 風格
ArticleDatabase db = get_article_db();
Article article = db.create_article(...);
```

作者: Maya Sawa Team
版本: 0.2.0
"""

# QA 向量數據庫
from .qa_vector_db import QAVectorDatabase, PostgresVectorStore

# 文章數據庫
from .article_db import (
    get_article_db,
    ArticleDatabase,
    Article,
    # 向後兼容
    get_paprika_db,
    PaprikaDatabase,
)

# 對話數據庫
from .conversation_db import (
    get_conversation_db,
    ConversationDatabase,
    Conversation,
    Message,
    AIModel,
    ProcessingTask,
    ConversationStatus,
    ConversationType,
    MessageType,
    TaskStatus,
    # 向後兼容
    get_maya_v2_db,
    MayaV2Database,
)

__all__ = [
    # QA 向量數據庫
    'QAVectorDatabase',
    'PostgresVectorStore',  # 向後兼容
    
    # 文章數據庫
    'get_article_db',
    'ArticleDatabase',
    'Article',
    'get_paprika_db',  # 向後兼容
    'PaprikaDatabase',  # 向後兼容
    
    # 對話數據庫
    'get_conversation_db',
    'ConversationDatabase',
    'Conversation',
    'Message',
    'AIModel',
    'ProcessingTask',
    'ConversationStatus',
    'ConversationType',
    'MessageType',
    'TaskStatus',
    'get_maya_v2_db',  # 向後兼容
    'MayaV2Database',  # 向後兼容
]
