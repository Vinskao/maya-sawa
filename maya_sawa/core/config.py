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
    # Load environment-specific .env file
    project_root = Path(__file__).resolve().parents[2]
    env_type = os.getenv("ENV_TYPE", "development")  # Default to development
    
    # Try to load environment-specific file first
    env_file = project_root / f".env.{env_type}"
    if env_file.exists():
        load_dotenv(env_file, override=False)
        print(f"Loaded environment configuration from: {env_file}")
    else:
        # Fallback to default .env file
        default_env = project_root / ".env"
        if default_env.exists():
            load_dotenv(default_env, override=False)
            print(f"Loaded default configuration from: {default_env}")
except ImportError:
    # dotenv not installed – ignore
    pass

class Config:
    """
    Configuration manager for Maya Sawa system
    """
    
    # Main Database Configuration (for articles table)
    # Build PostgreSQL connection string from individual parameters
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_DATABASE = os.getenv("DB_DATABASE")
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
    
    # Construct main database connection string
    if all([DB_HOST, DB_DATABASE, DB_USERNAME, DB_PASSWORD]):
        DB_CONNECTION_STRING = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}?sslmode={DB_SSLMODE}"
    else:
        # If individual parameters are not provided, set to None
        DB_CONNECTION_STRING = None
    
    # People Database Configuration (for people and weapon tables)
    PEOPLE_DB_HOST = os.getenv("PEOPLE_DB_HOST")
    PEOPLE_DB_PORT = os.getenv("PEOPLE_DB_PORT", "5432")
    PEOPLE_DB_DATABASE = os.getenv("PEOPLE_DB_DATABASE")
    PEOPLE_DB_USERNAME = os.getenv("PEOPLE_DB_USERNAME")
    PEOPLE_DB_PASSWORD = os.getenv("PEOPLE_DB_PASSWORD")
    PEOPLE_DB_SSLMODE = os.getenv("PEOPLE_DB_SSLMODE", "require")
    
    # Construct people database connection string
    if all([PEOPLE_DB_HOST, PEOPLE_DB_DATABASE, PEOPLE_DB_USERNAME, PEOPLE_DB_PASSWORD]):
        PEOPLE_DB_CONNECTION_STRING = f"postgresql://{PEOPLE_DB_USERNAME}:{PEOPLE_DB_PASSWORD}@{PEOPLE_DB_HOST}:{PEOPLE_DB_PORT}/{PEOPLE_DB_DATABASE}?sslmode={PEOPLE_DB_SSLMODE}"
    else:
        # If individual parameters are not provided, set to None
        PEOPLE_DB_CONNECTION_STRING = None
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
    
    # Redis Configuration
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    
    # API Configuration
    PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "")
    PUBLIC_TYMB_URL = os.getenv("PUBLIC_TYMB_URL", "")
    
    # Vector Search Configuration
    # Default to 3 matches if not set, per product requirement
    ARTICLE_MATCH_COUNT = int(os.getenv("MATCH_COUNT", "3"))
    # Keep threshold configurable as well (optional usage)
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.5"))

    # Embedding Source/Validation Configuration
    # If true, ignore upstream embeddings and always recompute locally
    FORCE_LOCAL_EMBEDDING = os.getenv("FORCE_LOCAL_EMBEDDING", "false").lower() == "true"
    # If true, validate upstream embeddings (e.g., dimension=1536); invalid ones will be recomputed locally
    VALIDATE_UPSTREAM_EMBEDDING = os.getenv("VALIDATE_UPSTREAM_EMBEDDING", "true").lower() == "true"
    
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
        
        # Check for main database configuration (for articles table)
        if not cls.DB_CONNECTION_STRING:
            missing_vars.append("Main database configuration (DB_HOST, DB_DATABASE, DB_USERNAME, DB_PASSWORD)")
        
        # Check for people database configuration (for people and weapon tables)
        if not cls.PEOPLE_DB_CONNECTION_STRING:
            missing_vars.append("People database configuration (PEOPLE_DB_HOST, PEOPLE_DB_DATABASE, PEOPLE_DB_USERNAME, PEOPLE_DB_PASSWORD)")
        
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