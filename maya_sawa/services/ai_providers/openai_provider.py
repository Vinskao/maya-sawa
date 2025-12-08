"""
OpenAI Provider Module

This module implements the OpenAI AI provider.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from typing import Dict, Any, Optional, List

from openai import OpenAI

from .base import BaseAIProvider, AIResponse
from ...core.config import Config

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI AI provider implementation
    
    Supports GPT models through the OpenAI API.
    """
    
    @property
    def provider_name(self) -> str:
        return 'openai'
    
    def get_default_model(self) -> str:
        return Config.OPENAI_DEFAULT_MODEL
    
    def get_available_models(self) -> List[str]:
        return Config.OPENAI_AVAILABLE_MODELS
    
    def is_available(self) -> bool:
        return bool(Config.OPENAI_API_KEY)
    
    def _get_client(self) -> OpenAI:
        """Get or create OpenAI client"""
        if self._client is None:
            kwargs = {'api_key': Config.OPENAI_API_KEY}
            if Config.OPENAI_API_BASE:
                kwargs['base_url'] = Config.OPENAI_API_BASE
            self._client = OpenAI(**kwargs)
        return self._client
    
    async def generate_response(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_message: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """
        Generate a response using OpenAI API
        
        Args:
            prompt: The user's prompt/question
            context: Optional context to include
            system_message: Optional system message
            **kwargs: Additional parameters (temperature, max_tokens, etc.)
            
        Returns:
            AIResponse with the generated content
        """
        try:
            client = self._get_client()
            
            messages = []
            
            # Add system message if provided
            if system_message:
                messages.append({
                    "role": "system",
                    "content": system_message
                })
            
            # Build user message with context
            user_content = prompt
            if context:
                user_content = f"Context:\n{context}\n\nQuestion:\n{prompt}"
            
            messages.append({
                "role": "user",
                "content": user_content
            })
            
            # Get configuration
            model = kwargs.get('model', self.model_id)
            temperature = kwargs.get('temperature', self.get_config_value('temperature', 0.7))
            max_tokens = kwargs.get('max_tokens', self.get_config_value('max_tokens', 1000))
            
            # Make API call
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            content = response.choices[0].message.content
            
            return AIResponse(
                content=content,
                metadata={
                    'model': model,
                    'provider': self.provider_name,
                    'usage': {
                        'prompt_tokens': response.usage.prompt_tokens,
                        'completion_tokens': response.usage.completion_tokens,
                        'total_tokens': response.usage.total_tokens
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise



