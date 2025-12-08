"""
Gemini Provider Module

This module implements the Google Gemini AI provider.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from typing import Dict, Any, Optional, List

from .base import BaseAIProvider, AIResponse
from ...core.config import Config

logger = logging.getLogger(__name__)


class GeminiProvider(BaseAIProvider):
    """
    Google Gemini AI provider implementation
    
    Supports Gemini models through the Google Generative AI API.
    """
    
    @property
    def provider_name(self) -> str:
        return 'gemini'
    
    def get_default_model(self) -> str:
        return Config.GEMINI_DEFAULT_MODEL
    
    def get_available_models(self) -> List[str]:
        return Config.GEMINI_AVAILABLE_MODELS
    
    def is_available(self) -> bool:
        return bool(Config.GEMINI_API_KEY) and Config.GEMINI_ENABLED
    
    def _get_client(self):
        """Get or create Gemini client"""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=Config.GEMINI_API_KEY)
                self._client = genai.GenerativeModel(self.model_id)
            except ImportError:
                logger.error("google-generativeai package not installed")
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
        Generate a response using Gemini API
        
        Args:
            prompt: The user's prompt/question
            context: Optional context to include
            system_message: Optional system message
            **kwargs: Additional parameters
            
        Returns:
            AIResponse with the generated content
        """
        try:
            model = self._get_client()
            
            # Build full prompt
            full_prompt = ""
            if system_message:
                full_prompt += f"System: {system_message}\n\n"
            if context:
                full_prompt += f"Context:\n{context}\n\n"
            full_prompt += f"User: {prompt}"
            
            # Generate response
            response = model.generate_content(full_prompt)
            
            content = response.text
            
            return AIResponse(
                content=content,
                metadata={
                    'model': self.model_id,
                    'provider': self.provider_name
                }
            )
            
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            raise



