"""
Configuration Management Module

This module manages configuration settings for the Maya Sawa system,
including automatic synchronization settings and feature flags.

Author: Maya Sawa Team
Version: 0.1.0
"""

import os
from typing import Optional
from pathlib import Path
try:
    from dotenv import load_dotenv
    # Load .env located at project root
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    # dotenv not installed – ignore
    pass

class Config:
    """
    Configuration manager for Maya Sawa system
    """
    
    # Database Configuration
    POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
    
    # Redis Configuration
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    
    # API Configuration
    PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "")
    
    # Vector Search Configuration
    # Default to 3 matches if not set, per product requirement
    ARTICLE_MATCH_COUNT = int(os.getenv("MATCH_COUNT", "3"))
    # Keep threshold configurable as well (optional usage)
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.5"))
    
    # Synchronization Configuration
    ENABLE_AUTO_SYNC_ON_STARTUP = os.getenv("ENABLE_AUTO_SYNC_ON_STARTUP", "false").lower() == "true"
    ENABLE_PERIODIC_SYNC = os.getenv("ENABLE_PERIODIC_SYNC", "false").lower() == "true"  # 默認關閉定期同步
    SYNC_INTERVAL_DAYS = int(os.getenv("SYNC_INTERVAL_DAYS", "3"))
    SYNC_HOUR = int(os.getenv("SYNC_HOUR", "3"))
    SYNC_MINUTE = int(os.getenv("SYNC_MINUTE", "0"))
    
    # People and Weapons Sync Configuration
    ENABLE_PEOPLE_WEAPONS_SYNC = os.getenv("ENABLE_PEOPLE_WEAPONS_SYNC", "false").lower() == "true"
    ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC = os.getenv("ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC", "false").lower() == "true"  # 默認關閉定期同步
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate_required_config(cls) -> list:
        """
        Validate required configuration variables
        
        Returns:
            list: List of missing required configuration variables
        """
        missing_vars = []
        
        if not cls.POSTGRES_CONNECTION_STRING:
            missing_vars.append("POSTGRES_CONNECTION_STRING")
        
        if not cls.OPENAI_API_KEY:
            missing_vars.append("OPENAI_API_KEY")
        
        return missing_vars
    
    @classmethod
    def get_sync_config_summary(cls) -> dict:
        """
        Get a summary of synchronization configuration
        
        Returns:
            dict: Configuration summary
        """
        return {
            "auto_sync_on_startup": cls.ENABLE_AUTO_SYNC_ON_STARTUP,
            "periodic_sync": cls.ENABLE_PERIODIC_SYNC,
            "sync_interval_days": cls.SYNC_INTERVAL_DAYS,
            "sync_time": f"{cls.SYNC_HOUR:02d}:{cls.SYNC_MINUTE:02d}",
            "people_weapons_sync": cls.ENABLE_PEOPLE_WEAPONS_SYNC,
            "people_weapons_periodic_sync": cls.ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC
        } 