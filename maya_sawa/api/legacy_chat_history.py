"""Legacy chat-history endpoint (v1 style), kept for old clients.

2026-11-19: the Maya v2 API (/maya-v2/*: conversations, AI models, multi-model ask) was removed together with the v2 chat
UI; every question now goes through POST /maya-sawa/qa/query. Only this old read endpoint remains.
"""
import logging

from fastapi import APIRouter

from ..core.errors.errors import AppException, ErrorCode
from ..core.services.chat_history import ChatHistoryManager

logger = logging.getLogger(__name__)
legacy_router = APIRouter(tags=["Legacy Chat History"])


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
