"""
Conversations API Module

This module provides API endpoints for conversation management,
migrated from the Django maya-sawa-v2 application.

Endpoints:
- GET /maya-v2/conversations/ - List all conversations
- POST /maya-v2/conversations/ - Create conversation
- GET /maya-v2/conversations/{id}/ - Get single conversation
- PUT /maya-v2/conversations/{id}/ - Update conversation
- DELETE /maya-v2/conversations/{id}/ - Delete conversation
- POST /maya-v2/conversations/{id}/send_message/ - Send message
- GET /maya-v2/conversations/{id}/messages/ - Get messages
- GET /maya-v2/qa/chat-history/{session_id} - Get chat history (v2 style)
- GET /maya-sawa/qa/chat-history/{session_tail} - Legacy chat history

Author: Maya Sawa Team
Version: 0.1.0
"""

import uuid
import logging
from typing import List, Optional, Dict, Any

try:
    from fastapi import APIRouter, Query
    from pydantic import BaseModel, Field
except ImportError as e:
    raise ImportError(f"FastAPI and Pydantic are required but not installed. Please install with: poetry install") from e

from ..databases.conversation_db import get_conversation_db, MessageType
from ..core.services.chat_history import ChatHistoryManager
from ..core.errors.errors import (
    ErrorCode,
    AppException,
    raise_not_found,
    raise_db_unavailable,
)

logger = logging.getLogger(__name__)

# Create routers
router = APIRouter(prefix="/maya-v2", tags=["Conversations"])
legacy_router = APIRouter(tags=["Legacy Chat History"])


# ==================== Request/Response Models ====================

class MessageResponse(BaseModel):
    """Message response model"""
    id: int
    conversation_id: str
    message_type: str
    content: str
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None


class ConversationResponse(BaseModel):
    """Conversation response model"""
    id: str
    user_id: Optional[int] = None
    session_id: str
    conversation_type: str
    status: str
    title: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    messages: Optional[List[MessageResponse]] = None


class ConversationCreate(BaseModel):
    """Conversation creation request"""
    conversation_type: str = Field(default='general')
    title: str = Field(default='')
    session_id: Optional[str] = None


class ConversationUpdate(BaseModel):
    """Conversation update request"""
    title: Optional[str] = None
    status: Optional[str] = None
    conversation_type: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send message request"""
    content: str
    ai_model_id: Optional[int] = None


class SendMessageResponse(BaseModel):
    """Send message response"""
    message: str
    message_id: int


# ==================== Helper Functions ====================

def _ensure_db_available():
    """
    Check if Maya-v2 database is available.
    Raises AppException if not available.
    """
    db = get_conversation_db()
    if not db.is_available():
        raise_db_unavailable("Maya-v2")
    return db


# ==================== Conversation Endpoints ====================

@router.get("/conversations/", response_model=List[ConversationResponse])
async def list_conversations(
    user_id: Optional[int] = Query(None, description="Filter by user ID")
):
    """
    Get all conversations
    
    Returns a list of all conversations, optionally filtered by user.
    """
    db = _ensure_db_available()
    
    try:
        conversations = db.get_all_conversations(user_id=user_id)
        return [ConversationResponse(**c.to_dict()) for c in conversations]
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch conversations: {str(e)}")
        raise AppException(
            ErrorCode.CONVERSATION_CREATE_FAILED,
            message="對話列表獲取失敗",
            message_en="Failed to fetch conversations",
            detail={"error": str(e)}
        )


@router.post("/conversations/", response_model=ConversationResponse, status_code=201)
async def create_conversation(request: ConversationCreate):
    """
    Create a new conversation
    
    Args:
        request: Conversation creation data
        
    Returns:
        The created conversation
    """
    db = _ensure_db_available()
    
    try:
        # Generate session_id if not provided
        session_id = request.session_id or f"qa-{uuid.uuid4().hex[:8]}"
        
        # Check for duplicate session_id
        existing = db.get_conversation_by_session_id(session_id)
        if existing:
            raise AppException(
                ErrorCode.SESSION_ALREADY_EXISTS,
                detail={"session_id": session_id}
            )
        
        conversation = db.create_conversation(
            session_id=session_id,
            conversation_type=request.conversation_type,
            title=request.title or f"Conversation-{session_id}"
        )
        
        return ConversationResponse(**conversation.to_dict())
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to create conversation: {str(e)}")
        raise AppException(
            ErrorCode.CONVERSATION_CREATE_FAILED,
            detail={"error": str(e)}
        )


@router.get("/conversations/{conversation_id}/", response_model=ConversationResponse)
async def get_conversation(conversation_id: str):
    """
    Get single conversation by ID
    
    Args:
        conversation_id: The conversation UUID
        
    Returns:
        The conversation data with messages
    """
    db = _ensure_db_available()
    
    try:
        conversation = db.get_conversation_by_id(conversation_id)
        
        if not conversation:
            raise_not_found("Conversation", conversation_id, ErrorCode.CONVERSATION_NOT_FOUND)
        
        # Get messages
        messages = db.get_messages_by_conversation(conversation_id)
        
        result = conversation.to_dict()
        result['messages'] = [m.to_dict() for m in messages]
        
        return ConversationResponse(**result)
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch conversation: {str(e)}")
        raise AppException(
            ErrorCode.CONVERSATION_CREATE_FAILED,
            message="對話獲取失敗",
            message_en="Failed to fetch conversation",
            detail={"conversation_id": conversation_id, "error": str(e)}
        )


@router.put("/conversations/{conversation_id}/", response_model=ConversationResponse)
async def update_conversation(conversation_id: str, request: ConversationUpdate):
    """
    Update a conversation
    
    Args:
        conversation_id: The conversation UUID
        request: Update data
        
    Returns:
        The updated conversation
    """
    db = _ensure_db_available()
    
    try:
        # Build update kwargs
        update_data = {}
        if request.title is not None:
            update_data['title'] = request.title
        if request.status is not None:
            update_data['status'] = request.status
        if request.conversation_type is not None:
            update_data['conversation_type'] = request.conversation_type
        
        conversation = db.update_conversation(conversation_id, **update_data)
        
        if not conversation:
            raise_not_found("Conversation", conversation_id, ErrorCode.CONVERSATION_NOT_FOUND)
        
        return ConversationResponse(**conversation.to_dict())
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to update conversation: {str(e)}")
        raise AppException(
            ErrorCode.CONVERSATION_UPDATE_FAILED,
            detail={"conversation_id": conversation_id, "error": str(e)}
        )


@router.delete("/conversations/{conversation_id}/")
async def delete_conversation(conversation_id: str):
    """
    Delete a conversation
    
    Args:
        conversation_id: The conversation UUID
        
    Returns:
        Success message
    """
    db = _ensure_db_available()
    
    try:
        success = db.delete_conversation(conversation_id)
        
        if not success:
            raise_not_found("Conversation", conversation_id, ErrorCode.CONVERSATION_NOT_FOUND)
        
        return {"success": True, "message": "Conversation deleted successfully"}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete conversation: {str(e)}")
        raise AppException(
            ErrorCode.CONVERSATION_DELETE_FAILED,
            detail={"conversation_id": conversation_id, "error": str(e)}
        )


@router.post("/conversations/{conversation_id}/send_message/", response_model=SendMessageResponse)
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message to a conversation
    
    This creates a user message and optionally triggers AI processing.
    
    Args:
        conversation_id: The conversation UUID
        request: Message content and optional AI model ID
        
    Returns:
        The created message ID
    """
    db = _ensure_db_available()
    
    try:
        # Verify conversation exists
        conversation = db.get_conversation_by_id(conversation_id)
        if not conversation:
            raise_not_found("Conversation", conversation_id, ErrorCode.CONVERSATION_NOT_FOUND)
        
        # Create user message
        message = db.create_message(
            conversation_id=conversation_id,
            message_type=MessageType.USER.value,
            content=request.content,
            metadata={}
        )
        
        return SendMessageResponse(
            message="Message sent successfully",
            message_id=message.id
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        raise AppException(
            ErrorCode.MESSAGE_SEND_FAILED,
            detail={"conversation_id": conversation_id, "error": str(e)}
        )


@router.get("/conversations/{conversation_id}/messages/", response_model=List[MessageResponse])
async def get_messages(conversation_id: str):
    """
    Get all messages for a conversation
    
    Args:
        conversation_id: The conversation UUID
        
    Returns:
        List of messages
    """
    db = _ensure_db_available()
    
    try:
        # Verify conversation exists
        conversation = db.get_conversation_by_id(conversation_id)
        if not conversation:
            raise_not_found("Conversation", conversation_id, ErrorCode.CONVERSATION_NOT_FOUND)
        
        messages = db.get_messages_by_conversation(conversation_id)
        return [MessageResponse(**m.to_dict()) for m in messages]
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch messages: {str(e)}")
        raise AppException(
            ErrorCode.MESSAGE_FETCH_FAILED,
            detail={"conversation_id": conversation_id, "error": str(e)}
        )


# ==================== Chat History Endpoints ====================

@router.get("/qa/chat-history/{session_id}")
async def chat_history_v2(session_id: str):
    """
    Get chat history from Redis (v2 style)
    
    Args:
        session_id: The session ID
        
    Returns:
        Chat history with metadata and messages
    """
    try:
        chat_history = ChatHistoryManager()
        
        # Get history from Redis
        history = chat_history.get_conversation_history(session_id)
        stats = chat_history.get_conversation_stats(session_id)
        
        return {
            "session_id": session_id,
            "meta": stats,
            "messages": history
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to get chat history: {str(e)}")
        raise AppException(
            ErrorCode.CHAT_HISTORY_FAILED,
            detail={"session_id": session_id, "error": str(e)}
        )


# Legacy endpoint for backward compatibility
@legacy_router.get("/maya-sawa/qa/chat-history/{session_tail}")
async def legacy_chat_history(session_tail: str):
    """
    Legacy chat history endpoint (v1 style)
    
    Maintains backward compatibility with the original path.
    If session_tail doesn't start with 'qa-', it will be prepended.
    
    Args:
        session_tail: The session ID or tail
        
    Returns:
        Chat history with metadata and messages
    """
    try:
        # Normalize session_id
        session_id = session_tail if session_tail.startswith('qa-') else f'qa-{session_tail}'
        
        chat_history = ChatHistoryManager()
        
        # Get history from Redis
        history = chat_history.get_conversation_history(session_id)
        stats = chat_history.get_conversation_stats(session_id)
        
        return {
            "session_id": session_id,
            "meta": stats,
            "messages": history
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to get legacy chat history: {str(e)}")
        raise AppException(
            ErrorCode.CHAT_HISTORY_FAILED,
            detail={"session_id": session_tail, "error": str(e)}
        )
