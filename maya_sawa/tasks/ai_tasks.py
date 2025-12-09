"""
AI Processing Tasks

This module contains Celery tasks for AI response processing.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from .celery_app import celery_app
from ..core.config.config import Config
from ..databases.conversation_db import get_conversation_db, TaskStatus, MessageType

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run async code in sync context"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, queue='maya_sawa', name='maya_sawa.tasks.ai_tasks.process_ai_response_task')
def process_ai_response_task(self, task_id: int) -> Dict[str, Any]:
    """
    Process AI response asynchronously
    
    This task:
    1. Retrieves the processing task from database
    2. Gets the AI provider and generates response
    3. Updates the task status and saves the response
    
    Args:
        task_id: The ProcessingTask database ID
        
    Returns:
        Dict containing the response and metadata
    """
    import time
    start_time = time.time()
    
    try:
        db = get_conversation_db()
        if not db.is_available():
            raise RuntimeError("Database not available")
        
        # Get processing task
        task = db.get_processing_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Update status to processing
        db.update_processing_task(task_id, status=TaskStatus.PROCESSING.value)
        
        # Get the user message
        messages = db.get_messages_by_conversation(str(task.conversation_id))
        user_message = None
        for msg in messages:
            if msg.id == task.message_id:
                user_message = msg
                break
        
        if not user_message:
            raise ValueError(f"Message {task.message_id} not found")
        
        # Get AI model
        ai_model = db.get_ai_model_by_id(task.ai_model_id)
        if not ai_model:
            raise ValueError(f"AI model {task.ai_model_id} not found")
        
        # Get AI provider
        from ..services.ai_providers import AIProviderFactory
        
        provider = AIProviderFactory.get_provider(
            provider_name=ai_model.provider,
            model_id=ai_model.model_id
        )
        
        # Generate response
        async def generate():
            return await provider.generate_response(
                prompt=user_message.content,
                context=task.knowledge_context if task.knowledge_used else None,
                system_message="You are a helpful assistant. Answer questions based on the provided context when available."
            )
        
        response = _run_async(generate())
        ai_response = response.content
        
        # Append knowledge context if present
        if task.knowledge_context and task.knowledge_used:
            ai_response = f"{ai_response}\n\n{task.knowledge_context}"
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        # Save AI response message
        db.create_message(
            conversation_id=str(task.conversation_id),
            message_type=MessageType.AI.value,
            content=ai_response,
            metadata={
                'model': ai_model.name,
                'provider': ai_model.provider,
                'processing_time': processing_time
            }
        )
        
        # Update task as completed
        db.update_processing_task(
            task_id,
            status=TaskStatus.COMPLETED.value,
            result=ai_response,
            processing_time=processing_time,
            completed_at=datetime.utcnow()
        )
        
        logger.info(f"AI processing completed for task {task_id}")
        
        return {
            'response': ai_response,
            'conversation_id': str(task.conversation_id),
            'question': user_message.content,
            'ai_model': {
                'id': ai_model.id,
                'name': ai_model.name,
                'provider': ai_model.provider
            },
            'processing_time': processing_time,
            'completed_at': datetime.utcnow().isoformat(),
            'knowledge_used': task.knowledge_used,
            'knowledge_citations': task.knowledge_citations,
            'metadata': {
                'task_id': str(task_id),
                'status': 'completed'
            }
        }
    
    except Exception as e:
        logger.error(f"AI processing failed for task {task_id}: {str(e)}")
        
        # Update task as failed
        try:
            db = get_conversation_db()
            if db.is_available():
                db.update_processing_task(
                    task_id,
                    status=TaskStatus.FAILED.value,
                    error_message=str(e)
                )
        except Exception:
            pass
        
        raise e


@celery_app.task(bind=True, queue='maya_sawa', name='maya_sawa.tasks.ai_tasks.sync_articles_task')
def sync_articles_task(self, remote_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Sync articles from remote API asynchronously
    
    Args:
        remote_url: Optional custom URL for article source
        
    Returns:
        Sync statistics
    """
    import httpx
    
    try:
        url = remote_url or f"{Config.PUBLIC_API_BASE_URL}/paprika/articles"
        
        # Fetch articles
        with httpx.Client() as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
        
        if not data.get('success'):
            raise ValueError("Remote API returned error")
        
        articles = data.get('data', [])
        if not articles:
            return {'message': 'No articles to sync', 'count': 0}
        
        # Sync to vector store
        from ..databases.qa_vector_db import QAVectorDatabase
        from ..core.processing.langchain_shim import Document
        
        vector_store = QAVectorDatabase()
        
        documents = []
        for article in articles:
            doc = Document(
                page_content=article.get('content', ''),
                metadata={
                    'source': article.get('file_path', 'unknown'),
                    'id': article.get('id'),
                    'file_date': article.get('file_date')
                }
            )
            documents.append(doc)
        
        if documents:
            vector_store.add_documents(documents)
        
        return {
            'success': True,
            'message': f'Synced {len(articles)} articles',
            'count': len(articles)
        }
    
    except Exception as e:
        logger.error(f"Article sync failed: {str(e)}")
        raise e



