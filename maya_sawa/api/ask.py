"""
Ask with Model API Module

This module provides the main Q&A endpoint with multi-model support,
migrated from the Django maya-sawa-v2 application.

Endpoints:
- POST /maya-v2/ask-with-model/ - Ask question with specified model
- GET /maya-v2/task-status/{task_id} - Check async task status

Author: Maya Sawa Team
Version: 0.1.0
"""

import uuid
import logging
from typing import Optional, Dict, Any, List

try:
    from fastapi import APIRouter
    from pydantic import BaseModel, Field
except ImportError as e:
    raise ImportError(f"FastAPI and Pydantic are required but not installed. Please install with: poetry install") from e

from ..core.config.config import Config
from ..databases.conversation_db import get_conversation_db, MessageType, TaskStatus
from ..core.services.chat_history import ChatHistoryManager
from ..databases.qa_vector_db import QAVectorDatabase
from ..services.ai_providers import AIProviderFactory
from ..core.errors.errors import (
    ErrorCode,
    AppException,
    raise_not_found,
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/maya-v2", tags=["Ask with Model"])


# ==================== Request/Response Models ====================

class AskWithModelRequest(BaseModel):
    """Request model for ask-with-model endpoint"""
    question: str = Field(..., description="The question to ask")
    model_name: str = Field(default="gpt-4o-mini", description="AI model name or ID")
    sync: bool = Field(default=True, description="Whether to process synchronously")
    use_knowledge_base: bool = Field(default=True, description="Whether to search knowledge base")


class AIModelInfo(BaseModel):
    """AI model info in response"""
    id: Optional[int] = None
    name: str
    provider: str


class KnowledgeCitation(BaseModel):
    """Knowledge base citation"""
    article_id: Optional[int] = None
    title: str
    file_path: str
    file_date: Optional[str] = None
    source: str
    source_url: str
    provider: str = "Paprika"


class AskWithModelResponse(BaseModel):
    """Response model for ask-with-model endpoint"""
    session_id: str
    conversation_id: str
    question: str
    ai_model: AIModelInfo
    status: str
    ai_response: Optional[str] = None
    knowledge_used: bool = False
    knowledge_citations: List[KnowledgeCitation] = []
    message: str
    task_id: Optional[str] = None


class TaskStatusResponse(BaseModel):
    """Response model for task status"""
    task_id: str
    status: str
    ai_response: Optional[str] = None
    knowledge_used: bool = False
    knowledge_citations: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    completed_at: Optional[str] = None
    conversation_id: Optional[str] = None
    question: Optional[str] = None
    ai_model: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


# ==================== Helper Functions ====================

def _get_ai_model_info(model_name: str) -> tuple:
    """
    Get AI model info by name or ID
    
    Returns tuple of (model_info_dict, provider_name, model_id_str)
    """
    db = get_conversation_db()
    
    if db.is_available():
        # Try to find model by name
        model = db.get_ai_model_by_name(model_name)
        if not model:
            # Try by model_id
            model = db.get_ai_model_by_model_id(model_name)
        
        if model:
            return (
                {'id': model.id, 'name': model.name, 'provider': model.provider},
                model.provider,
                model.model_id
            )
    
    # Fallback to config-based lookup
    providers_config = Config.get_all_providers_config()
    
    for provider, config in providers_config.items():
        if model_name in config['models'] or model_name in config['available_models']:
            return (
                {'id': None, 'name': model_name, 'provider': provider},
                provider,
                model_name
            )
    
    # Default to OpenAI with the given model name
    return (
        {'id': None, 'name': model_name, 'provider': 'openai'},
        'openai',
        model_name
    )


async def _search_knowledge_base(query: str, k: int = 3) -> tuple:
    """
    Search knowledge base for relevant content
    
    Returns tuple of (knowledge_context, knowledge_citations, knowledge_found)
    """
    knowledge_context = ""
    knowledge_citations = []
    knowledge_found = False
    
    try:
        vector_store = QAVectorDatabase()
        
        # Search for relevant documents
        documents = vector_store.similarity_search(query, k=k, threshold=0.3)
        
        if documents:
            knowledge_found = True
            knowledge_context = "\n\n相關知識庫內容：\n"
            
            for i, doc in enumerate(documents[:3]):
                metadata = doc.metadata or {}
                title = metadata.get('title') or '參考文章'
                file_path = metadata.get('file_path') or metadata.get('source', '')
                
                # Remove .md extension if present
                if file_path.endswith('.md'):
                    file_path = file_path[:-3]
                
                # Build source URL
                base_url = Config.PUBLIC_API_BASE_URL
                work_url = f"{base_url}/tymultiverse/work/{file_path}" if file_path else f"{base_url}/tymultiverse/work/"
                
                # Add to context
                content_preview = doc.page_content[:200] if doc.page_content else ''
                knowledge_context += f"{i+1}. {title} ({file_path})\n{content_preview}...\n"
                
                # Add citation
                knowledge_citations.append({
                    'article_id': metadata.get('id'),
                    'title': title,
                    'file_path': file_path,
                    'file_date': metadata.get('file_date'),
                    'source': 'paprika_api',
                    'source_url': work_url,
                    'provider': 'Paprika'
                })
        else:
            knowledge_context = "\n\n注意：無法從知識庫中找到相關的資訊來回答您的問題。以下回答基於模型的訓練資料。"
    
    except Exception as e:
        logger.error(f"Knowledge base search failed: {str(e)}")
        knowledge_context = ""
    
    return knowledge_context, knowledge_citations, knowledge_found


# ==================== API Endpoints ====================

@router.post("/ask-with-model/", response_model=AskWithModelResponse)
async def ask_with_model(request: AskWithModelRequest):
    """
    Ask a question using a specified AI model
    
    This endpoint:
    1. Creates a conversation and message record
    2. Optionally searches knowledge base for context
    3. Generates AI response (sync or async)
    4. Stores response in chat history
    
    Args:
        request: The question and model configuration
        
    Returns:
        The AI response or task ID for async processing
    """
    try:
        # Get AI model info
        model_info, provider_name, model_id = _get_ai_model_info(request.model_name)
        
        # Check if model is available
        try:
            ai_provider = AIProviderFactory.get_provider(provider_name, model_id)
            if not ai_provider.is_available():
                raise AppException(
                    ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                    detail={"provider": provider_name}
                )
        except ValueError as e:
            raise AppException(
                ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(e),
                detail={"provider": provider_name, "model": model_id}
            )
        
        # Generate session ID
        session_id = f"qa-{uuid.uuid4().hex[:8]}"
        
        # Create conversation in database if available
        db = get_conversation_db()
        conversation_id = str(uuid.uuid4())
        message_id = None
        
        if db.is_available():
            try:
                conversation = db.create_conversation(
                    session_id=session_id,
                    conversation_type='general',
                    title=f"QA-{session_id}"
                )
                conversation_id = str(conversation.id)
                
                # Create user message
                user_message = db.create_message(
                    conversation_id=conversation_id,
                    message_type=MessageType.USER.value,
                    content=request.question
                )
                message_id = user_message.id
            except Exception as e:
                logger.warning(f"Failed to create conversation record: {str(e)}")
        
        # Store in Redis chat history
        try:
            chat_history = ChatHistoryManager()
            chat_history.save_conversation(
                user_message=request.question,
                ai_answer="",  # Will be updated after response
                user_id=session_id,
                reference_data={'model': model_info['name']}
            )
        except Exception as e:
            logger.warning(f"Failed to save to Redis: {str(e)}")
        
        # Search knowledge base if enabled
        knowledge_context = ""
        knowledge_citations = []
        knowledge_found = False
        
        if request.use_knowledge_base:
            knowledge_context, knowledge_citations, knowledge_found = await _search_knowledge_base(
                request.question
            )
        
        # Process AI response
        if request.sync:
            # Synchronous processing
            try:
                response = await ai_provider.generate_response(
                    prompt=request.question,
                    context=knowledge_context if knowledge_found else None,
                    system_message="You are a helpful assistant. Answer questions based on the provided context when available."
                )
                
                ai_response = response.content
                
                # Append knowledge context to response if present
                if knowledge_context and knowledge_found:
                    ai_response = f"{ai_response}\n\n{knowledge_context}"
                
                # Save AI response
                if db.is_available() and conversation_id:
                    try:
                        db.create_message(
                            conversation_id=conversation_id,
                            message_type=MessageType.AI.value,
                            content=ai_response,
                            metadata={'model': model_info['name']}
                        )
                    except Exception as e:
                        logger.warning(f"Failed to save AI response: {str(e)}")
                
                # Update Redis
                try:
                    chat_history = ChatHistoryManager()
                    # Re-save with the actual response
                    chat_history.save_conversation(
                        user_message=request.question,
                        ai_answer=ai_response,
                        user_id=session_id,
                        reference_data={'model': model_info['name']}
                    )
                except Exception:
                    pass
                
                return AskWithModelResponse(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    question=request.question,
                    ai_model=AIModelInfo(**model_info),
                    status='completed',
                    ai_response=ai_response,
                    knowledge_used=knowledge_found,
                    knowledge_citations=[KnowledgeCitation(**c) for c in knowledge_citations],
                    message='AI回答已完成'
                )
            
            except Exception as e:
                logger.error(f"AI processing failed: {str(e)}")
                raise AppException(
                    ErrorCode.AI_PROCESSING_FAILED,
                    detail={"model": model_info['name'], "error": str(e)}
                )
        
        else:
            # Asynchronous processing - create task
            task_id = None
            
            if db.is_available() and message_id:
                try:
                    # Get or create AI model in database
                    ai_model_record = db.get_ai_model_by_name(model_info['name'])
                    if not ai_model_record:
                        ai_model_record = db.create_or_update_ai_model(
                            name=model_info['name'],
                            provider=provider_name,
                            model_id=model_id,
                            is_active=True
                        )
                    
                    # Create processing task
                    task = db.create_processing_task(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        ai_model_id=ai_model_record.id,
                        knowledge_context=knowledge_context,
                        knowledge_citations=knowledge_citations,
                        knowledge_used=knowledge_found
                    )
                    task_id = str(task.id)
                    
                    # Queue Celery task
                    try:
                        from ..tasks.ai_tasks import process_ai_response_task
                        celery_result = process_ai_response_task.delay(task.id)
                        task_id = str(celery_result.id)
                    except Exception as e:
                        logger.warning(f"Failed to queue Celery task: {str(e)}")
                        # Fall back to sync processing
                        task_id = str(task.id)
                    
                except Exception as e:
                    logger.error(f"Failed to create async task: {str(e)}")
            
            return AskWithModelResponse(
                session_id=session_id,
                conversation_id=conversation_id,
                question=request.question,
                ai_model=AIModelInfo(**model_info),
                status='queued',
                knowledge_used=knowledge_found,
                knowledge_citations=[KnowledgeCitation(**c) for c in knowledge_citations],
                message='Task has been queued for processing',
                task_id=task_id
            )
    
    except AppException:
        raise
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        raise AppException(
            ErrorCode.INTERNAL_SERVER_ERROR,
            detail={"error": str(e)}
        )


@router.get("/task-status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Check the status of an async processing task
    
    Args:
        task_id: The task ID (Celery task ID or database task ID)
        
    Returns:
        Task status and result if completed
    """
    try:
        # Try to get Celery task status first
        try:
            from ..tasks.ai_tasks import process_ai_response_task
            
            celery_task = process_ai_response_task.AsyncResult(task_id)
            
            response_data = {
                'task_id': task_id,
                'status': celery_task.status
            }
            
            if celery_task.status == 'SUCCESS':
                result = celery_task.result
                if isinstance(result, dict):
                    response_data.update({
                        'ai_response': result.get('response', ''),
                        'knowledge_used': result.get('knowledge_used', False),
                        'knowledge_citations': result.get('knowledge_citations', []),
                        'metadata': result.get('metadata', {}),
                        'completed_at': result.get('completed_at'),
                        'conversation_id': result.get('conversation_id'),
                        'question': result.get('question'),
                        'ai_model': result.get('ai_model')
                    })
                else:
                    response_data['ai_response'] = str(result)
            
            elif celery_task.status == 'FAILURE':
                response_data.update({
                    'error': str(celery_task.result)
                })
            
            elif celery_task.status == 'PENDING':
                response_data['message'] = 'Task is waiting for execution'
            
            elif celery_task.status == 'STARTED':
                response_data['message'] = 'Task is currently being processed'
            
            return TaskStatusResponse(**response_data)
        
        except Exception as celery_error:
            logger.debug(f"Celery task lookup failed: {str(celery_error)}")
        
        # Fall back to database task lookup
        db = get_conversation_db()
        if db.is_available():
            try:
                task = db.get_processing_task(int(task_id))
                if task:
                    return TaskStatusResponse(
                        task_id=task_id,
                        status=task.status,
                        ai_response=task.result if task.status == 'completed' else None,
                        knowledge_used=task.knowledge_used,
                        knowledge_citations=task.knowledge_citations,
                        completed_at=task.completed_at.isoformat() if task.completed_at else None,
                        error=task.error_message if task.status == 'failed' else None
                    )
            except ValueError:
                pass
        
        raise_not_found("Task", task_id, ErrorCode.TASK_NOT_FOUND)
    
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {str(e)}")
        raise AppException(
            ErrorCode.TASK_STATUS_FAILED,
            detail={"task_id": task_id, "error": str(e)}
        )
