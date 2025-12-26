from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import logging

from ..people import PeopleWeaponManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/people", tags=["People"])

# Lazy load manager
_people_manager = None

def get_people_manager():
    global _people_manager
    if _people_manager is None:
        _people_manager = PeopleWeaponManager()
    return _people_manager

@router.get("/names", response_model=List[str])
async def get_all_people_names():
    """
    Get all people names from the database.
    """
    try:
        manager = get_people_manager()
        names = manager.get_all_names_from_db()
        return names
    except Exception as e:
        logger.error(f"Failed to get people names: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/get-all")
async def get_all_people():
    """
    Get all people data.
    Note: Ideally this should support pagination.
    Current implementation fetches from external API via manager, 
    but we might want to implement DB fetch if we are the source of truth.
    For now, let's just use the manager's fetch_people_data which calls configured API,
    OR if we want to be independent, we should implement get_all_from_db in manager.
    
    Given the user issue, let's implement a DB-based fetch if possible, 
    or just return what we have.
    """
    try:
        # For now, let's proxy or use what's available.
        # But wait, fetch_people_data calls an external API. 
        # If we are the external API, this is a loop.
        
        # Let's implement a simple DB fetch for all people if needed.
        # PeopleWeaponManager doesn't have get_all_from_db yet.
        # But the immediate requirement is names for the "Online Agent" list.
        
        # For full "get-all", let's return a 501 strictly for now, 
        # unless we want to solve that too. 
        # The user specifically mentioned "load out multiple people", which usually implies the list.
        # The list is fetched via /people/names in frontend (QABot).
        
        return {"message": "Not implemented yet, use /people/names for list"}
    except Exception as e:
        logger.error(f"Failed to get all people: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
