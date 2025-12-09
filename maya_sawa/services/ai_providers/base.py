"""
Base AI Provider Module

This module defines the abstract base class for all AI providers
and the factory for creating provider instances.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

from ...core.config.config import Config

logger = logging.getLogger(__name__)


class AIResponse:
    """Standardized AI response object"""
    
    def __init__(self, content: str, metadata: Dict[str, Any] = None):
        self.content = content
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'metadata': self.metadata
        }


class BaseAIProvider(ABC):
    """
    Abstract base class for AI providers
    
    All AI providers (OpenAI, Gemini, Qwen, etc.) must inherit from this class
    and implement the required methods.
    """
    
    def __init__(self, model_id: str = None, config: Dict[str, Any] = None):
        """
        Initialize the AI provider
        
        Args:
            model_id: The model identifier to use
            config: Additional configuration options
        """
        self.model_id = model_id or self.get_default_model()
        self.config = config or {}
        self._client = None
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'gemini')"""
        pass
    
    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model ID for this provider"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Return list of available model IDs"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is properly configured and available"""
        pass
    
    @abstractmethod
    async def generate_response(
        self, 
        prompt: str, 
        context: Optional[str] = None,
        system_message: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """
        Generate a response from the AI model
        
        Args:
            prompt: The user's prompt/question
            context: Optional context to include (e.g., knowledge base content)
            system_message: Optional system message to set behavior
            **kwargs: Additional provider-specific parameters
            
        Returns:
            AIResponse object containing the response content and metadata
        """
        pass
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Get a configuration value with fallback to default"""
        return self.config.get(key, default)


class AIProviderFactory:
    """
    Factory for creating AI provider instances
    
    Uses configuration to determine which providers are available
    and creates the appropriate provider instance.
    """
    
    _providers: Dict[str, type] = {}
    _instances: Dict[str, BaseAIProvider] = {}
    
    @classmethod
    def register_provider(cls, name: str, provider_class: type):
        """Register a provider class"""
        cls._providers[name.lower()] = provider_class
        logger.info(f"Registered AI provider: {name}")
    
    @classmethod
    def get_provider(
        cls, 
        provider_name: str = None, 
        model_id: str = None,
        config: Dict[str, Any] = None
    ) -> BaseAIProvider:
        """
        Get an AI provider instance
        
        Args:
            provider_name: The provider name (e.g., 'openai'). 
                          If None, uses the first enabled provider.
            model_id: Optional specific model ID
            config: Optional additional configuration
            
        Returns:
            An AI provider instance
            
        Raises:
            ValueError: If the provider is not available or not configured
        """
        # If no provider specified, use first enabled
        if provider_name is None:
            enabled = Config.ENABLED_PROVIDERS
            if enabled:
                provider_name = enabled[0]
            else:
                provider_name = 'openai'  # Default fallback
        
        provider_name = provider_name.lower()
        
        # Check if provider is registered
        if provider_name not in cls._providers:
            cls._auto_register_providers()
            
            if provider_name not in cls._providers:
                raise ValueError(f"Unknown AI provider: {provider_name}")
        
        # Create instance key
        instance_key = f"{provider_name}:{model_id or 'default'}"
        
        # Return cached instance or create new one
        if instance_key not in cls._instances:
            provider_class = cls._providers[provider_name]
            cls._instances[instance_key] = provider_class(model_id=model_id, config=config)
        
        return cls._instances[instance_key]
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available (configured) providers"""
        cls._auto_register_providers()
        
        available = []
        for name, provider_class in cls._providers.items():
            try:
                instance = provider_class()
                if instance.is_available():
                    available.append(name)
            except Exception:
                pass
        
        return available
    
    @classmethod
    def _auto_register_providers(cls):
        """Auto-register known providers"""
        if cls._providers:
            return
        
        # Register OpenAI
        try:
            from .openai_provider import OpenAIProvider
            cls.register_provider('openai', OpenAIProvider)
        except ImportError:
            pass
        
        # Register Gemini
        try:
            from .gemini_provider import GeminiProvider
            cls.register_provider('gemini', GeminiProvider)
        except ImportError:
            pass
        
        # Register Qwen
        try:
            from .qwen_provider import QwenProvider
            cls.register_provider('qwen', QwenProvider)
        except ImportError:
            pass
    
    @classmethod
    def clear_cache(cls):
        """Clear cached provider instances"""
        cls._instances.clear()



