"""
AI Models API Module

This module provides API endpoints for AI model management,
migrated from the Django maya-sawa-v2 application.

Endpoints:
- GET /maya-v2/ai-models/ - List all AI models
- GET /maya-v2/ai-models/{id} - Get single AI model
- GET /maya-v2/available-models/ - Get available models
- GET /maya-v2/ai-providers/ - Get AI provider configurations
- POST /maya-v2/add-model/ - Add/update models from environment

Author: Maya Sawa Team
Version: 0.1.0
"""

import os
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..core.config import Config
from ..databases.maya_v2_db import get_maya_v2_db
from ..core.errors import (
    ErrorCode,
    AppException,
    raise_not_found,
    raise_db_unavailable,
)

logger = logging.getLogger(__name__)

# Create router with maya-v2 prefix
router = APIRouter(prefix="/maya-v2", tags=["AI Models"])


# ==================== Request/Response Models ====================

class AIModelResponse(BaseModel):
    """AI Model response"""
    id: int
    name: str
    provider: str
    model_id: str
    is_active: bool
    config: Dict[str, Any] = {}
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AIProviderConfigResponse(BaseModel):
    """AI Provider configuration response"""
    provider: str
    display_name: str
    models: List[str]
    available_models: List[str]
    default_model: str
    enabled: bool


class AddModelResponse(BaseModel):
    """Response for add-model endpoint"""
    message: str
    models: List[Dict[str, Any]]


# ==================== Helper Functions ====================

def _generate_model_name(provider: str, model_id: str) -> str:
    """Generate display name for a model"""
    name_mapping = {
        'OPENAI': {
            'gpt-4o-mini': 'GPT-4o Mini',
            'gpt-4o': 'GPT-4o',
            'gpt-4.1-nano': 'GPT-4.1 Nano',
            'gpt-3.5-turbo': 'GPT-3.5 Turbo'
        },
        'GEMINI': {
            'gemini-1.5-flash': 'Gemini 1.5 Flash',
            'gemini-1.5-pro': 'Gemini 1.5 Pro'
        },
        'QWEN': {
            'qwen-turbo': 'Qwen Turbo',
            'qwen-plus': 'Qwen Plus'
        }
    }
    return name_mapping.get(provider.upper(), {}).get(model_id, f'{provider} {model_id}')


def _get_models_from_config(include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Get models from configuration when database is not available"""
    models = []
    providers_config = Config.get_all_providers_config()
    
    model_id_counter = 1
    for provider, config in providers_config.items():
        if not config['enabled'] and not include_inactive:
            continue
        
        for model_id in config['models']:
            is_active = model_id in config['available_models']
            if not is_active and not include_inactive:
                continue
            
            models.append({
                'id': model_id_counter,
                'name': _generate_model_name(provider.upper(), model_id),
                'provider': provider,
                'model_id': model_id,
                'is_active': is_active,
                'config': {},
                'created_at': None
            })
            model_id_counter += 1
    
    return models


# ==================== API Endpoints ====================

@router.get("/ai-models/", response_model=List[AIModelResponse])
async def list_ai_models(
    include_inactive: bool = Query(False, description="Include inactive models")
):
    """
    Get all AI models
    
    Returns a list of all AI models, optionally including inactive ones.
    
    Query Parameters:
        include_inactive: Whether to include inactive models (default: false)
    """
    try:
        db = get_maya_v2_db()
        if not db.is_available():
            # If database not available, return models from config
            return _get_models_from_config(include_inactive)
        
        models = db.get_all_ai_models(include_inactive=include_inactive)
        return [AIModelResponse(**m.to_dict()) for m in models]
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch AI models: {str(e)}")
        # Fallback to config-based models
        return _get_models_from_config(include_inactive)


@router.get("/ai-models/{model_id}", response_model=AIModelResponse)
async def get_ai_model(model_id: int):
    """
    Get single AI model by ID
    
    Args:
        model_id: The AI model ID
        
    Returns:
        The AI model data
    """
    db = get_maya_v2_db()
    if not db.is_available():
        raise_db_unavailable("Maya-v2")
    
    try:
        model = db.get_ai_model_by_id(model_id)
        
        if not model:
            raise_not_found("AI Model", model_id, ErrorCode.AI_MODEL_NOT_FOUND)
        
        return AIModelResponse(**model.to_dict())
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch AI model: {str(e)}")
        raise AppException(
            ErrorCode.AI_MODEL_FETCH_FAILED,
            detail={"model_id": model_id, "error": str(e)}
        )


@router.get("/available-models/")
async def available_models():
    """
    Get list of available (active) AI models
    
    Returns models that are currently active and can be used.
    """
    try:
        db = get_maya_v2_db()
        if db.is_available():
            models = db.get_all_ai_models(include_inactive=False)
            return {
                "models": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "provider": m.provider,
                        "model_id": m.model_id,
                        "is_active": m.is_active
                    }
                    for m in models
                ]
            }
        
        # Fallback to config
        return {"models": _get_models_from_config(include_inactive=False)}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to get available models: {str(e)}")
        raise AppException(
            ErrorCode.AI_MODEL_FETCH_FAILED,
            detail={"error": str(e)}
        )


@router.get("/ai-providers/", response_model=List[AIProviderConfigResponse])
async def get_ai_providers():
    """
    Get AI provider configurations
    
    Returns configuration for all AI providers including:
    - Provider name and display name
    - Available models
    - Default model
    - Enabled status
    """
    providers_config = Config.get_all_providers_config()
    
    providers_data = []
    for provider, config in providers_config.items():
        providers_data.append(AIProviderConfigResponse(
            provider=provider,
            display_name=Config.get_provider_display_name(provider),
            models=config['models'],
            available_models=config['available_models'],
            default_model=config['default_model'],
            enabled=config['enabled']
        ))
    
    return providers_data


@router.post("/add-model/", response_model=AddModelResponse)
async def add_model():
    """
    Add or update AI models from environment variables
    
    Reads model configuration from environment variables and
    creates/updates database records accordingly.
    
    Environment variables used:
    - ENABLED_PROVIDERS: Comma-separated list of providers
    - {PROVIDER}_MODELS: All models for provider
    - {PROVIDER}_AVAILABLE_MODELS: Active models for provider
    - {PROVIDER}_DEFAULT_MODEL: Default model for provider
    """
    try:
        db = get_maya_v2_db()
        
        created_count = 0
        updated_count = 0
        models_info = []
        
        enabled_providers = os.getenv('ENABLED_PROVIDERS', 'openai').split(',')
        
        for provider in enabled_providers:
            provider = provider.strip().upper()
            
            models_key = f'{provider}_MODELS'
            available_models_key = f'{provider}_AVAILABLE_MODELS'
            
            all_models = os.getenv(models_key, '').split(',')
            available_models = os.getenv(available_models_key, '').split(',')
            
            if not all_models or all_models == ['']:
                continue
            
            for model_id in all_models:
                model_id = model_id.strip()
                if not model_id:
                    continue
                
                is_available = model_id in available_models
                model_name = _generate_model_name(provider, model_id)
                
                model_data = {
                    'name': model_name,
                    'provider': provider.lower(),
                    'model_id': model_id,
                    'is_active': is_available,
                    'config': {
                        'model': model_id,
                        'max_tokens': 1000,
                        'temperature': 0.7
                    }
                }
                
                if db.is_available():
                    # Use database
                    existing = db.get_ai_model_by_name(model_name)
                    model = db.create_or_update_ai_model(
                        name=model_name,
                        provider=provider.lower(),
                        model_id=model_id,
                        is_active=is_available,
                        config=model_data['config']
                    )
                    
                    action = 'updated' if existing else 'created'
                    if action == 'created':
                        created_count += 1
                    else:
                        updated_count += 1
                    
                    models_info.append({
                        'id': model.id,
                        'name': model.name,
                        'provider': model.provider,
                        'model_id': model.model_id,
                        'is_active': model.is_active,
                        'action': action
                    })
                else:
                    # Just return config-based info
                    models_info.append({
                        'id': None,
                        'name': model_name,
                        'provider': provider.lower(),
                        'model_id': model_id,
                        'is_active': is_available,
                        'action': 'config_only'
                    })
        
        return AddModelResponse(
            message=f'AI models setup complete! Created: {created_count}, Updated: {updated_count}',
            models=models_info
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to add models: {str(e)}")
        raise AppException(
            ErrorCode.AI_MODEL_CREATE_FAILED,
            detail={"error": str(e)}
        )
