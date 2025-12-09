"""
對話數據庫模組 (Conversation Database)

這個模組管理聊天對話和 AI 模型配置，相當於 Java 的 ChatService + AIModelService。

核心功能：
1. 對話會話管理：創建、更新、刪除聊天會話
2. 消息存儲：保存用戶和 AI 的對話歷史
3. AI 模型配置：管理不同 AI 提供者的模型
4. 異步任務處理：追蹤 AI 響應生成任務

數據庫設計：
- 多表關聯設計 (相當於 JPA @OneToMany)
- Conversation (會話主表)
- Message (消息從表，關聯到會話)
- AIModel (AI 模型配置表)
- ProcessingTask (異步任務表)

Java 開發者對應：
- ConversationDatabase ≡ ChatRepository + AIModelRepository + TaskRepository
- 枚舉類：ConversationStatus, MessageType (相當於 Java enum)
- 關聯關係：Conversation.messages (相當於 JPA @OneToMany)

架構特點：
- UUID 主鍵：使用 UUID 而不是自增 ID (更安全)
- JSON 字段：存儲複雜的模型配置
- 級聯操作：刪除會話時自動刪除消息
- 狀態機：任務處理狀態追蹤

業務流程：
1. 用戶發送消息 → 創建 Conversation + Message
2. 系統分配 AI 模型 → 創建 ProcessingTask
3. AI 生成響應 → 更新 Message + 完成 Task
4. 持續對話 → 在同一 Conversation 下添加新 Message

效能考慮：
- 索引優化：會話 ID、消息時間戳等關鍵字段
- 連接池：自動管理數據庫連接
- 批量操作：支持批量插入消息

作者: Maya Sawa Team
版本: 0.2.0
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from enum import Enum

try:
    from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON, pool
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, relationship
except ImportError as e:
    raise ImportError(f"SQLAlchemy is required but not installed. Please install it with: poetry install") from e
from sqlalchemy.dialects.postgresql import UUID

from ..core.config.config import Config

logger = logging.getLogger(__name__)

# SQLAlchemy Base
Base = declarative_base()


class ConversationStatus(str, Enum):
    ACTIVE = 'active'
    CLOSED = 'closed'
    PENDING = 'pending'


class ConversationType(str, Enum):
    CUSTOMER_SERVICE = 'customer_service'
    KNOWLEDGE_QUERY = 'knowledge_query'
    GENERAL = 'general'


class MessageType(str, Enum):
    USER = 'user'
    AI = 'ai'
    SYSTEM = 'system'


class TaskStatus(str, Enum):
    PENDING = 'pending'
    QUEUED = 'queued'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'


class AIModel(Base):
    """AI 模型配置表"""
    __tablename__ = 'maya_sawa_v2_ai_processing_aimodel'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    provider = Column(String(50), nullable=False)
    model_id = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'provider': self.provider,
            'model_id': self.model_id,
            'is_active': self.is_active,
            'config': self.config or {},
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Conversation(Base):
    """
    對話會話實體 (相當於 JPA @Entity)

    代表一個完整的聊天會話，包含多條消息。

    字段說明：
    - id: UUID 主鍵 (相當於 @Id, 更安全不會暴露記錄數)
    - user_id: 用戶 ID，可空 (匿名用戶)
    - session_id: 會話標識，唯一 (前端用來區分不同聊天)
    - conversation_type: 對話類型 (一般、客服、查詢等)
    - status: 會話狀態 (活躍、關閉、暫停)
    - title: 會話標題
    - created_at/updated_at: 時間戳

    關聯關係 (相當於 JPA @OneToMany)：
    - messages: 關聯的所有消息
    - cascade="all, delete-orphan": 刪除會話時自動刪除所有消息

    業務含義：
    - 一個 Conversation 相當於微信的一個聊天窗口
    - 多個 Message 相當於聊天記錄
    - session_id 相當於聊天室的唯一標識
    """
    __tablename__ = 'maya_sawa_v2_conversations_conversation'

    # UUID 主鍵 (相當於 Java UUID)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 用戶標識 (可空，支援匿名用戶)
    user_id = Column(Integer, nullable=True)  # Can be null for anonymous users

    # 會話唯一標識 (相當於聊天室 ID)
    session_id = Column(String(255), unique=True, nullable=False)

    # 對話類型枚舉
    conversation_type = Column(String(20), default=ConversationType.GENERAL.value)

    # 會話狀態枚舉
    status = Column(String(10), default=ConversationStatus.ACTIVE.value)

    # 會話標題
    title = Column(String(255), default='')

    # 時間戳字段
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 一對多關聯：一個會話包含多條消息 (相當於 JPA @OneToMany)
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    def to_dict(self, include_messages: bool = False) -> Dict[str, Any]:
        """
        序列化為字典 (相當於 Java Bean 的 toString())

        參數：
        - include_messages: 是否包含完整的消息列表
          (默認 false，避免大數據量的序列化)

        返回：
        - 基本信息字典 + 可選的消息列表
        - 日期轉為 ISO 字符串格式
        """
        result = {
            'id': str(self.id),  # UUID 轉字符串
            'user_id': self.user_id,
            'session_id': self.session_id,
            'conversation_type': self.conversation_type,
            'status': self.status,
            'title': self.title,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        # 可選包含消息列表 (相當於懶加載控制)
        if include_messages:
            result['messages'] = [m.to_dict() for m in self.messages]
        return result


class Message(Base):
    """對話消息表"""
    __tablename__ = 'maya_sawa_v2_conversations_message'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('maya_sawa_v2_conversations_conversation.id'), nullable=False)
    message_type = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    extra_data = Column('metadata', JSON, default=dict)  # 'metadata' is reserved in SQLAlchemy, use extra_data as Python attr
    created_at = Column(DateTime, default=datetime.utcnow)
    
    conversation = relationship("Conversation", back_populates="messages")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'conversation_id': str(self.conversation_id),
            'message_type': self.message_type,
            'content': self.content,
            'metadata': self.extra_data or {},  # Return as 'metadata' for API compatibility
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ProcessingTask(Base):
    """AI 處理任務表"""
    __tablename__ = 'maya_sawa_v2_ai_processing_processingtask'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('maya_sawa_v2_conversations_conversation.id'), nullable=False)
    message_id = Column(Integer, ForeignKey('maya_sawa_v2_conversations_message.id'), nullable=False)
    ai_model_id = Column(Integer, ForeignKey('maya_sawa_v2_ai_processing_aimodel.id'), nullable=False)
    status = Column(String(20), default=TaskStatus.PENDING.value)
    result = Column(Text, default='')
    error_message = Column(Text, default='')
    processing_time = Column(Float, nullable=True)
    knowledge_context = Column(Text, default='')
    knowledge_citations = Column(JSON, default=list)
    knowledge_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'conversation_id': str(self.conversation_id),
            'message_id': self.message_id,
            'ai_model_id': self.ai_model_id,
            'status': self.status,
            'result': self.result,
            'error_message': self.error_message,
            'processing_time': self.processing_time,
            'knowledge_context': self.knowledge_context,
            'knowledge_citations': self.knowledge_citations or [],
            'knowledge_used': self.knowledge_used,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class ConversationDatabase:
    """
    對話數據庫管理類
    
    提供對話、消息和 AI 模型的管理功能
    """
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._engine is None:
            self._initialize_engine()
    
    def _initialize_engine(self):
        """Initialize the database engine"""
        db_url = Config.get_maya_v2_db_url()
        if not db_url:
            logger.warning("Conversation database URL not configured")
            return
        
        try:
            self._engine = create_engine(
                db_url,
                poolclass=pool.QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                echo=False
            )
            
            self._session_factory = sessionmaker(bind=self._engine)
            
            # Create tables if they don't exist
            Base.metadata.create_all(self._engine)
            
            logger.info("Conversation database initialized")
        except Exception as e:
            logger.error(f"Failed to initialize conversation database: {str(e)}")
            self._engine = None
            self._session_factory = None
    
    @contextmanager
    def get_session(self):
        """Get a database session as context manager"""
        if self._session_factory is None:
            raise RuntimeError("Conversation database not initialized")
        
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def is_available(self) -> bool:
        """Check if database is available"""
        return self._engine is not None
    
    # AI Model Operations
    
    def get_all_ai_models(self, include_inactive: bool = False) -> List[AIModel]:
        """Get all AI models"""
        with self.get_session() as session:
            query = session.query(AIModel)
            if not include_inactive:
                query = query.filter(AIModel.is_active == True)
            models = query.all()
            return [self._detach_model(m) for m in models]
    
    def get_ai_model_by_id(self, model_id: int) -> Optional[AIModel]:
        """Get AI model by ID"""
        with self.get_session() as session:
            model = session.query(AIModel).filter(AIModel.id == model_id).first()
            return self._detach_model(model) if model else None
    
    def get_ai_model_by_name(self, name: str) -> Optional[AIModel]:
        """Get AI model by name (case-insensitive partial match)"""
        with self.get_session() as session:
            model = session.query(AIModel).filter(
                AIModel.name.ilike(f'%{name}%'),
                AIModel.is_active == True
            ).first()
            return self._detach_model(model) if model else None
    
    def get_ai_model_by_model_id(self, model_id_str: str) -> Optional[AIModel]:
        """Get AI model by model_id string"""
        with self.get_session() as session:
            model = session.query(AIModel).filter(
                AIModel.model_id.ilike(f'%{model_id_str}%'),
                AIModel.is_active == True
            ).first()
            return self._detach_model(model) if model else None
    
    def create_or_update_ai_model(self, name: str, provider: str, model_id: str,
                                   is_active: bool = True, config: dict = None) -> AIModel:
        """Create or update an AI model"""
        with self.get_session() as session:
            existing = session.query(AIModel).filter(AIModel.name == name).first()
            
            if existing:
                existing.provider = provider
                existing.model_id = model_id
                existing.is_active = is_active
                if config:
                    existing.config = config
                session.flush()
                return self._detach_model(existing)
            else:
                model = AIModel(
                    name=name,
                    provider=provider,
                    model_id=model_id,
                    is_active=is_active,
                    config=config or {}
                )
                session.add(model)
                session.flush()
                return self._detach_model(model)
    
    # Conversation Operations
    
    def get_all_conversations(self, user_id: Optional[int] = None) -> List[Conversation]:
        """Get all conversations, optionally filtered by user"""
        with self.get_session() as session:
            query = session.query(Conversation)
            if user_id:
                query = query.filter(Conversation.user_id == user_id)
            conversations = query.order_by(Conversation.created_at.desc()).all()
            return [self._detach_conversation(c) for c in conversations]
    
    def get_conversation_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """Get conversation by ID"""
        with self.get_session() as session:
            conv = session.query(Conversation).filter(
                Conversation.id == uuid.UUID(conversation_id)
            ).first()
            return self._detach_conversation(conv) if conv else None
    
    def get_conversation_by_session_id(self, session_id: str) -> Optional[Conversation]:
        """Get conversation by session ID"""
        with self.get_session() as session:
            conv = session.query(Conversation).filter(
                Conversation.session_id == session_id
            ).first()
            return self._detach_conversation(conv) if conv else None
    
    def create_conversation(self, session_id: str, user_id: Optional[int] = None,
                           conversation_type: str = 'general', title: str = '') -> Conversation:
        """
        創建新對話會話 (相當於 JPA repository.save())

        參數說明：
        - session_id: 會話唯一標識 (前端生成，用來區分不同聊天)
        - user_id: 用戶 ID (可空，支援匿名用戶)
        - conversation_type: 對話類型 (general, customer_service, knowledge_query)
        - title: 會話標題 (可空)

        處理流程：
        1. 創建 Conversation 實例 (相當於 new Conversation())
        2. session.add() 添加到數據庫會話
        3. session.flush() 執行 INSERT 並獲取 UUID 主鍵
        4. _detach_conversation() 分離實例避免懶加載問題

        業務場景：
        - 用戶打開新聊天窗口時調用
        - 系統自動生成 session_id
        - 創建空的會話，等待第一條消息

        返回：
        - 包含自動生成 UUID 的 Conversation 實例
        """
        with self.get_session() as session:
            # 創建實例 (相當於 new Conversation())
            conv = Conversation(
                session_id=session_id,
                user_id=user_id,
                conversation_type=conversation_type,
                title=title
            )
            # 保存到數據庫 (相當於 JPA save())
            session.add(conv)
            # 立即執行 SQL 獲取 UUID
            session.flush()
            # 分離實例避免連接問題
            return self._detach_conversation(conv)
    
    def update_conversation(self, conversation_id: str, **kwargs) -> Optional[Conversation]:
        """Update a conversation"""
        with self.get_session() as session:
            conv = session.query(Conversation).filter(
                Conversation.id == uuid.UUID(conversation_id)
            ).first()
            if conv:
                for key, value in kwargs.items():
                    if hasattr(conv, key):
                        setattr(conv, key, value)
                conv.updated_at = datetime.utcnow()
                session.flush()
                return self._detach_conversation(conv)
            return None
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its messages"""
        with self.get_session() as session:
            conv = session.query(Conversation).filter(
                Conversation.id == uuid.UUID(conversation_id)
            ).first()
            if conv:
                session.delete(conv)
                return True
            return False
    
    # Message Operations
    
    def get_messages_by_conversation(self, conversation_id: str) -> List[Message]:
        """Get all messages for a conversation"""
        with self.get_session() as session:
            messages = session.query(Message).filter(
                Message.conversation_id == uuid.UUID(conversation_id)
            ).order_by(Message.created_at).all()
            return [self._detach_message(m) for m in messages]
    
    def create_message(self, conversation_id: str, message_type: str,
                       content: str, metadata: dict = None) -> Message:
        """
        創建新消息 (相當於在聊天中發送一條消息)

        參數說明：
        - conversation_id: 所屬對話的 UUID 字符串
        - message_type: 消息類型 (user, ai, system)
        - content: 消息內容 (文字)
        - metadata: 額外數據 (JSON 格式，可空)

        處理流程：
        1. 將字符串轉換為 UUID 對象
        2. 創建 Message 實例並關聯到 Conversation
        3. 保存到數據庫 (自動生成自增 ID)
        4. 分離實例返回

        業務場景：
        - 用戶發送消息：type="user", content="你好"
        - AI 回復消息：type="ai", content="你好！"
        - 系統消息：type="system", content="會話開始"

        數據完整性：
        - conversation_id 必須指向存在的 Conversation
        - message_type 必須是枚舉值之一
        - 外鍵約束確保引用完整性

        返回：
        - 包含自動生成 ID 的 Message 實例
        """
        with self.get_session() as session:
            # 字符串轉 UUID (相當於 Java UUID.fromString())
            msg = Message(
                conversation_id=uuid.UUID(conversation_id),  # 外鍵關聯
                message_type=message_type,                   # 枚舉值
                content=content,                             # 消息內容
                extra_data=metadata or {}                    # JSON 元數據
            )
            # 保存到數據庫
            session.add(msg)
            session.flush()
            # 分離並返回
            return self._detach_message(msg)
    
    # Processing Task Operations
    
    def create_processing_task(self, conversation_id: str, message_id: int,
                               ai_model_id: int, knowledge_context: str = '',
                               knowledge_citations: list = None,
                               knowledge_used: bool = False) -> ProcessingTask:
        """Create a new processing task"""
        with self.get_session() as session:
            task = ProcessingTask(
                conversation_id=uuid.UUID(conversation_id),
                message_id=message_id,
                ai_model_id=ai_model_id,
                status=TaskStatus.QUEUED.value,
                knowledge_context=knowledge_context,
                knowledge_citations=knowledge_citations or [],
                knowledge_used=knowledge_used
            )
            session.add(task)
            session.flush()
            return self._detach_task(task)
    
    def get_processing_task(self, task_id: int) -> Optional[ProcessingTask]:
        """Get processing task by ID"""
        with self.get_session() as session:
            task = session.query(ProcessingTask).filter(
                ProcessingTask.id == task_id
            ).first()
            return self._detach_task(task) if task else None
    
    def update_processing_task(self, task_id: int, **kwargs) -> Optional[ProcessingTask]:
        """Update a processing task"""
        with self.get_session() as session:
            task = session.query(ProcessingTask).filter(
                ProcessingTask.id == task_id
            ).first()
            if task:
                for key, value in kwargs.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                session.flush()
                return self._detach_task(task)
            return None
    
    # Detach helpers
    
    def _detach_model(self, model: AIModel) -> AIModel:
        if model is None:
            return None
        return AIModel(
            id=model.id,
            name=model.name,
            provider=model.provider,
            model_id=model.model_id,
            is_active=model.is_active,
            config=model.config,
            created_at=model.created_at
        )
    
    def _detach_conversation(self, conv: Conversation) -> Conversation:
        if conv is None:
            return None
        detached = Conversation(
            id=conv.id,
            user_id=conv.user_id,
            session_id=conv.session_id,
            conversation_type=conv.conversation_type,
            status=conv.status,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at
        )
        return detached
    
    def _detach_message(self, msg: Message) -> Message:
        if msg is None:
            return None
        return Message(
            id=msg.id,
            conversation_id=msg.conversation_id,
            message_type=msg.message_type,
            content=msg.content,
            extra_data=msg.extra_data,
            created_at=msg.created_at
        )
    
    def _detach_task(self, task: ProcessingTask) -> ProcessingTask:
        if task is None:
            return None
        return ProcessingTask(
            id=task.id,
            conversation_id=task.conversation_id,
            message_id=task.message_id,
            ai_model_id=task.ai_model_id,
            status=task.status,
            result=task.result,
            error_message=task.error_message,
            processing_time=task.processing_time,
            knowledge_context=task.knowledge_context,
            knowledge_citations=task.knowledge_citations,
            knowledge_used=task.knowledge_used,
            created_at=task.created_at,
            completed_at=task.completed_at
        )


# Singleton instance getter
def get_conversation_db() -> ConversationDatabase:
    """Get conversation database instance"""
    return ConversationDatabase()


# 向後兼容的別名
MayaV2Database = ConversationDatabase
get_maya_v2_db = get_conversation_db
