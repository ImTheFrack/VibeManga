"""
Centralized configuration management for VibeManga.

This module provides type-safe, validated configuration using Pydantic.
It replaces scattered environment variable access with a single source of truth.
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union
from pydantic import Field, field_validator, ConfigDict, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource


class AIConfig(BaseSettings):
    """Configuration for AI providers (Ollama, OpenAI, etc.)"""
    
    model_config = ConfigDict(
        env_prefix="AI_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    provider: str = Field(default="local", description="AI provider: local, openai, anthropic")
    model: str = Field(default="llama3.1", description="Model name to use")
    base_url: Optional[str] = Field(default=None, description="Base URL for AI API")
    api_key: Optional[str] = Field(default=None, description="API key for AI service")
    timeout: int = Field(default=300, description="API timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum number of retries")


class QBitConfig(BaseSettings):
    """Configuration for qBittorrent integration"""
    
    model_config = ConfigDict(
        env_prefix="QBIT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    url: str = Field(default="http://localhost:8080", description="qBittorrent Web UI URL")
    username: str = Field(default="admin", description="qBittorrent username")
    password: str = Field(default="adminadmin", description="qBittorrent password")
    tag: str = Field(default="VibeManga", description="Default tag for torrents")
    category: str = Field(default="VibeManga", description="Default category for torrents")
    save_path: str = Field(default="VibeManga", description="Default save path")


class JikanConfig(BaseSettings):
    """Configuration for Jikan (MyAnimeList) API"""
    
    model_config = ConfigDict(
        env_prefix="JIKAN_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    base_url: str = Field(default="https://api.jikan.moe/v4", description="Jikan API base URL")
    rate_limit_delay: float = Field(default=1.2, description="Rate limit delay in seconds")
    timeout: int = Field(default=10, description="API timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum number of retries")


class CacheConfig(BaseSettings):
    """Configuration for caching behavior"""
    
    model_config = SettingsConfigDict(
        env_prefix="CACHE_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    enabled: bool = Field(default=True, description="Whether caching is enabled")
    max_age_seconds: int = Field(default=3000, description="Cache max age in seconds")
    file_name: str = Field(default=".vibe_manga_cache.pkl", description="Cache file name")


class LoggingConfig(BaseSettings):
    """Configuration for logging behavior"""
    
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    level: str = Field(default="INFO", description="Default logging level")
    file_level: str = Field(default="INFO", description="File logging level")
    console_level: str = Field(default="WARNING", description="Console logging level")
    log_file: str = Field(default="vibe_manga.log", description="Log file path")
    
    @field_validator('level', 'file_level', 'console_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that log level is one of the allowed values"""
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()


class ProcessingConfig(BaseSettings):
    """Configuration for processing behavior"""
    
    model_config = SettingsConfigDict(
        env_prefix="PROCESSING_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    thread_pool_size: int = Field(default=4, description="Default thread pool size")
    batch_size: int = Field(default=100, description="Batch size for large operations")
    timeout: int = Field(default=300, description="Operation timeout in seconds")


class AIRoleConfig(BaseModel):
    """Configuration for AI roles (used by categorizer)"""
    
    # Dynamic role configuration loaded from JSON
    roles: Dict[str, Any] = Field(default_factory=dict, description="AI role configurations")

    @classmethod
    def load_from_json(cls, path: Union[str, Path] = "vibe_manga_ai_config.json") -> "AIRoleConfig":
        """Load AI role configuration from a JSON file."""
        path = Path(path)
        if not path.exists():
            return cls()
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json
                data = json.load(f)
            # Support both {"roles": {...}} and raw roles dict
            if "roles" in data:
                return cls(roles=data["roles"])
            return cls(roles=data)
        except Exception:
            return cls()


class VibeMangaConfig(BaseSettings):
    """
    Main configuration class for VibeManga.
    
    This class serves as the single source of truth for all configuration.
    It automatically loads from environment variables and .env files.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore"  # Ignore fields that don't belong to this config
    )
    
    # Core settings
    library_path: Optional[Path] = Field(default=None, description="Path to manga library")
    
    # Component configurations
    ai: AIConfig = Field(default_factory=AIConfig, description="AI provider configuration")
    qbit: QBitConfig = Field(default_factory=QBitConfig, description="qBittorrent configuration")
    jikan: JikanConfig = Field(default_factory=JikanConfig, description="Jikan API configuration")
    cache: CacheConfig = Field(default_factory=CacheConfig, description="Cache configuration")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging configuration")
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig, description="Processing configuration")
    ai_roles: AIRoleConfig = Field(default_factory=AIRoleConfig.load_from_json, description="AI role configuration for categorizer")

    
    # Feature flags
    dry_run: bool = Field(default=False, description="Enable dry run mode")
    verbose: bool = Field(default=False, description="Enable verbose output")
    
    # Backward compatibility fields (old-style env vars)
    manga_library_root: Optional[Path] = Field(default=None, description="[Legacy] Manga library root path")
    pull_tempdir: Optional[str] = Field(default=None, description="[Legacy] Pull temp directory")
    remote_ai_base_url: Optional[str] = Field(default=None, description="[Legacy] Remote AI base URL")
    remote_ai_api_key: Optional[str] = Field(default=None, description="[Legacy] Remote AI API key")
    remote_ai_model: Optional[str] = Field(default=None, description="[Legacy] Remote AI model")
    local_ai_base_url: Optional[str] = Field(default=None, description="[Legacy] Local AI base URL")
    local_ai_api_key: Optional[str] = Field(default=None, description="[Legacy] Local AI API key")
    local_ai_model: Optional[str] = Field(default=None, description="[Legacy] Local AI model")
    ai_timeout: Optional[int] = Field(default=None, description="[Legacy] AI timeout")
    
    @classmethod
    def customise_sources(
        cls,
        init_settings: SettingsSourceCallable,
        env_settings: SettingsSourceCallable,
        file_secret_settings: SettingsSourceCallable,
    ) -> tuple[SettingsSourceCallable, ...]:
        """Customize the order of configuration sources"""
        return env_settings, init_settings, file_secret_settings
    
    def save_to_file(self, path: Union[str, Path]) -> None:
        """
        Save configuration to a JSON file.
        
        Args:
            path: Path to save the configuration file
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use model_dump with mode='json' for proper serialization
        config_dict = self.model_dump(mode='json')
        
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> "VibeMangaConfig":
        """
        Load configuration from a JSON file.
        
        Args:
            path: Path to the configuration file
            
        Returns:
            VibeMangaConfig instance
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            import json
            data = json.load(f)
        
        return cls(**data)


# Global configuration instance
_config_instance: Optional[VibeMangaConfig] = None


def setup_config(
    library_path: Optional[Union[str, Path]] = None,
    env_file: Optional[Union[str, Path]] = None,
    **kwargs
) -> VibeMangaConfig:
    """
    Set up the global configuration.
    
    Args:
        library_path: Path to manga library
        env_file: Path to .env file
        **kwargs: Additional configuration overrides
        
    Returns:
        VibeMangaConfig instance
    """
    global _config_instance
    
    config_kwargs = {}
    if library_path:
        config_kwargs["library_path"] = Path(library_path)
    
    # Load from env file if specified
    if env_file:
        config_kwargs["_env_file"] = str(env_file)
    
    # Apply any additional overrides
    config_kwargs.update(kwargs)
    
    _config_instance = VibeMangaConfig(**config_kwargs)
    return _config_instance


def get_config() -> VibeMangaConfig:
    """
    Get the global configuration instance.
    
    Returns:
        VibeMangaConfig instance
        
    Raises:
        RuntimeError: If configuration has not been set up
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = VibeMangaConfig()
    return _config_instance


def reload_config() -> VibeMangaConfig:
    """
    Reload configuration from environment and .env files.
    
    Returns:
        VibeMangaConfig instance
    """
    global _config_instance
    _config_instance = VibeMangaConfig()
    return _config_instance


# Convenience functions for common configuration access
def get_library_path() -> Optional[Path]:
    """Get the configured library path."""
    return get_config().library_path


def get_ai_config() -> AIConfig:
    """Get AI configuration."""
    return get_config().ai


def get_qbit_config() -> QBitConfig:
    """Get qBittorrent configuration."""
    return get_config().qbit


def get_cache_config() -> CacheConfig:
    """Get cache configuration."""
    return get_config().cache


def get_logging_config() -> LoggingConfig:
    """Get logging configuration."""
    return get_config().logging


def get_processing_config() -> ProcessingConfig:
    """Get processing configuration."""
    return get_config().processing


def get_ai_role_config(role_name: str) -> Dict[str, Any]:
    """
    Get configuration for a specific AI role.
    Prioritizes User Config (JSON) > Default Config (constants.py).
    
    Args:
        role_name: Name of the AI role (e.g., MODERATOR, PRACTICAL, CREATIVE)
        
    Returns:
        Merged configuration dictionary
    """
    from ..constants import ROLE_CONFIG
    
    config = get_config()
    user_roles = config.ai_roles.roles if hasattr(config, 'ai_roles') else {}
    
    # Get defaults from constants
    defaults = ROLE_CONFIG.get(role_name, {})
    # Get user config from JSON
    user_config = user_roles.get(role_name, {})
    
    # Merge: User config overrides defaults
    merged = defaults.copy()
    merged.update(user_config)
    
    return merged


__all__ = [
    "AIConfig",
    "QBitConfig",
    "JikanConfig",
    "CacheConfig",
    "LoggingConfig",
    "ProcessingConfig",
    "AIRoleConfig",
    "VibeMangaConfig",
    "setup_config",
    "get_config",
    "reload_config",
    "get_library_path",
    "get_ai_config",
    "get_qbit_config",
    "get_cache_config",
    "get_logging_config",
    "get_processing_config",
    "get_ai_role_config",
]