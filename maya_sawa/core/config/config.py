"""
Configuration Management Module

This module manages configuration settings for the Maya Sawa system,
including automatic synchronization settings and feature flags.

Author: Maya Sawa Team
Version: 0.1.0
"""

import os
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
    OPENAI_MODELS = os.getenv("OPENAI_MODELS", "gpt-4o-mini,gpt-4o,gpt-4.1-nano").split(",")
    OPENAI_AVAILABLE_MODELS = os.getenv("OPENAI_AVAILABLE_MODELS", "gpt-4o-mini,gpt-4.1-nano").split(",")
    OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
    
    # Gemini Configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODELS = os.getenv("GEMINI_MODELS", "gemini-1.5-flash,gemini-1.5-pro").split(",")
    GEMINI_AVAILABLE_MODELS = os.getenv("GEMINI_AVAILABLE_MODELS", "gemini-1.5-flash").split(",")
    GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash")
    GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "false").lower() == "true"
    
    # Qwen (DashScope) Configuration
    QWEN_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    QWEN_MODELS = os.getenv("QWEN_MODELS", "qwen-turbo,qwen-plus").split(",")
    QWEN_AVAILABLE_MODELS = os.getenv("QWEN_AVAILABLE_MODELS", "qwen-turbo").split(",")
    QWEN_DEFAULT_MODEL = os.getenv("QWEN_DEFAULT_MODEL", "qwen-turbo")
    QWEN_ENABLED = os.getenv("QWEN_ENABLED", "false").lower() == "true"
    
    # Enabled AI Providers
    ENABLED_PROVIDERS = os.getenv("ENABLED_PROVIDERS", "openai").split(",")
    
    # Redis Configuration
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    
    # Celery Configuration
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or os.getenv("RABBITMQ_URL") or f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_CUSTOM_PORT', 6379)}/0"
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND") or f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_CUSTOM_PORT', 6379)}/1"
    
    # Paprika Database Configuration (for articles from Laravel app)
    PAPRIKA_DB_TYPE = os.getenv("PAPRIKA_DB_TYPE", "sqlite")  # sqlite or postgresql
    PAPRIKA_DB_PATH = os.getenv("PAPRIKA_DB_PATH", "")  # For SQLite
    PAPRIKA_DB_HOST = os.getenv("PAPRIKA_DB_HOST")
    PAPRIKA_DB_PORT = os.getenv("PAPRIKA_DB_PORT", "5432")
    PAPRIKA_DB_DATABASE = os.getenv("PAPRIKA_DB_DATABASE")
    PAPRIKA_DB_USERNAME = os.getenv("PAPRIKA_DB_USERNAME")
    PAPRIKA_DB_PASSWORD = os.getenv("PAPRIKA_DB_PASSWORD")
    PAPRIKA_DB_SSLMODE = os.getenv("PAPRIKA_DB_SSLMODE", "disable")
    
    # Construct paprika database connection string
    @classmethod
    def get_paprika_db_url(cls) -> str:
        """Get paprika database connection URL"""
        if cls.PAPRIKA_DB_TYPE == "sqlite":
            if cls.PAPRIKA_DB_PATH:
                return f"sqlite:///{cls.PAPRIKA_DB_PATH}"
            return "sqlite:///paprika.db"
        elif cls.PAPRIKA_DB_TYPE == "postgresql":
            if all([cls.PAPRIKA_DB_HOST, cls.PAPRIKA_DB_DATABASE, cls.PAPRIKA_DB_USERNAME, cls.PAPRIKA_DB_PASSWORD]):
                return f"postgresql://{cls.PAPRIKA_DB_USERNAME}:{cls.PAPRIKA_DB_PASSWORD}@{cls.PAPRIKA_DB_HOST}:{cls.PAPRIKA_DB_PORT}/{cls.PAPRIKA_DB_DATABASE}?sslmode={cls.PAPRIKA_DB_SSLMODE}"
        return ""
    
    # Maya-v2 Database Configuration (for conversations from Django app)
    MAYA_V2_DB_HOST = os.getenv("MAYA_V2_DB_HOST") or os.getenv("DB_HOST")
    MAYA_V2_DB_PORT = os.getenv("MAYA_V2_DB_PORT", "5432")
    MAYA_V2_DB_DATABASE = os.getenv("MAYA_V2_DB_DATABASE")
    MAYA_V2_DB_USERNAME = os.getenv("MAYA_V2_DB_USERNAME") or os.getenv("DB_USERNAME")
    MAYA_V2_DB_PASSWORD = os.getenv("MAYA_V2_DB_PASSWORD") or os.getenv("DB_PASSWORD")
    MAYA_V2_DB_SSLMODE = os.getenv("MAYA_V2_DB_SSLMODE", "require")
    
    @classmethod
    def get_maya_v2_db_url(cls) -> str:
        """Get maya-v2 database connection URL"""
        if all([cls.MAYA_V2_DB_HOST, cls.MAYA_V2_DB_DATABASE, cls.MAYA_V2_DB_USERNAME, cls.MAYA_V2_DB_PASSWORD]):
            return f"postgresql://{cls.MAYA_V2_DB_USERNAME}:{cls.MAYA_V2_DB_PASSWORD}@{cls.MAYA_V2_DB_HOST}:{cls.MAYA_V2_DB_PORT}/{cls.MAYA_V2_DB_DATABASE}?sslmode={cls.MAYA_V2_DB_SSLMODE}"
        return ""
    
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

    # Voyeur Configuration
    # MongoDB settings
    MONGODB_URI = os.getenv("MONGODB_URI")
    MONGODB_DB = os.getenv("MONGODB_DB", "palais")
    MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "tyf_visits")
    
    # Redis Queue for Voyeur
    REDIS_QUEUE_VOYEUR = os.getenv("REDIS_QUEUE_VOYEUR", "voyeur_queue")
    
    # WebSocket settings for Voyeur
    WEBSOCKET_TYMB = os.getenv("WEBSOCKET_TYMB", "ws://localhost:8080/tymb/")
    WEBSOCKET_HOST = os.getenv("WEBSOCKET_HOST")
    WEBSOCKET_PORT = os.getenv("WEBSOCKET_PORT")
    WEBSOCKET_PATH = os.getenv("WEBSOCKET_PATH")
    
    @classmethod
    def get_voyeur_websocket_url(cls) -> str:
        """Get WebSocket URL for Voyeur metrics"""
        if cls.WEBSOCKET_TYMB:
            return cls.WEBSOCKET_TYMB.rstrip('/') + '/metrics'
        if all([cls.WEBSOCKET_HOST, cls.WEBSOCKET_PATH]):
            protocol = 'wss' if cls.WEBSOCKET_PORT == '443' else 'ws'
            port_str = f":{cls.WEBSOCKET_PORT}" if cls.WEBSOCKET_PORT else ""
            return f"{protocol}://{cls.WEBSOCKET_HOST}{port_str}{cls.WEBSOCKET_PATH}"
        return ""
    
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
    
    @classmethod
    def get_all_providers_config(cls) -> dict:
        """
        Get configuration for all AI providers
        
        Returns:
            dict: AI providers configuration
        """
        providers = {}
        
        # OpenAI
        providers['openai'] = {
            'enabled': 'openai' in cls.ENABLED_PROVIDERS,
            'models': cls.OPENAI_MODELS,
            'available_models': cls.OPENAI_AVAILABLE_MODELS,
            'default_model': cls.OPENAI_DEFAULT_MODEL,
            'api_key_set': bool(cls.OPENAI_API_KEY)
        }
        
        # Gemini
        providers['gemini'] = {
            'enabled': cls.GEMINI_ENABLED and 'gemini' in cls.ENABLED_PROVIDERS,
            'models': cls.GEMINI_MODELS,
            'available_models': cls.GEMINI_AVAILABLE_MODELS,
            'default_model': cls.GEMINI_DEFAULT_MODEL,
            'api_key_set': bool(cls.GEMINI_API_KEY)
        }
        
        # Qwen
        providers['qwen'] = {
            'enabled': cls.QWEN_ENABLED and 'qwen' in cls.ENABLED_PROVIDERS,
            'models': cls.QWEN_MODELS,
            'available_models': cls.QWEN_AVAILABLE_MODELS,
            'default_model': cls.QWEN_DEFAULT_MODEL,
            'api_key_set': bool(cls.QWEN_API_KEY)
        }
        
        return providers
    
    @classmethod
    def get_provider_display_name(cls, provider: str) -> str:
        """Get display name for AI provider"""
        display_names = {
            'openai': 'OpenAI',
            'gemini': 'Google Gemini',
            'qwen': 'Alibaba Qwen'
        }
        return display_names.get(provider.lower(), provider.upper()) 