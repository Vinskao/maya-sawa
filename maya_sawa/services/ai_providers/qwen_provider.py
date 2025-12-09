"""
Qwen Provider Module

This module implements the Alibaba Qwen (DashScope) AI provider.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from typing import Dict, Any, Optional, List

from .base import BaseAIProvider, AIResponse
from ...core.config.config import Config

logger = logging.getLogger(__name__)


class QwenProvider(BaseAIProvider):
    """
    Alibaba Qwen AI provider implementation
    
    Supports Qwen models through the DashScope API.
    """
    
    @property
    def provider_name(self) -> str:
        return 'qwen'
    
    def get_default_model(self) -> str:
        return Config.QWEN_DEFAULT_MODEL
    
    def get_available_models(self) -> List[str]:
        return Config.QWEN_AVAILABLE_MODELS
    
    def is_available(self) -> bool:
        return bool(Config.QWEN_API_KEY) and Config.QWEN_ENABLED
    
    def _get_client(self):
        """Initialize DashScope client"""
        if self._client is None:
            try:
                import dashscope
                dashscope.api_key = Config.QWEN_API_KEY
                self._client = dashscope
            except ImportError:
                logger.error("dashscope package not installed")
                raise
        return self._client
    
    async def generate_response(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_message: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """
        Generate a response using DashScope/Qwen API
        
        Args:
            prompt: The user's prompt/question
            context: Optional context to include
            system_message: Optional system message
            **kwargs: Additional parameters
            
        Returns:
            AIResponse with the generated content
        """
        try:
            dashscope = self._get_client()
            from dashscope import Generation
            
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
            
            # Make API call
            response = Generation.call(
                model=self.model_id,
                messages=messages,
                result_format='message'
            )
            
            if response.status_code == 200:
                content = response.output.choices[0].message.content
                
                return AIResponse(
                    content=content,
                    metadata={
                        'model': self.model_id,
                        'provider': self.provider_name,
                        'usage': {
                            'input_tokens': response.usage.input_tokens,
                            'output_tokens': response.usage.output_tokens
                        }
                    }
                )
            else:
                raise Exception(f"Qwen API error: {response.code} - {response.message}")
            
        except Exception as e:
            logger.error(f"Qwen API error: {str(e)}")
            raise



