"""
Configuration package for VibeManga.

This package provides centralized, type-safe configuration management.
"""

from .manager import (
    AIConfig,
    QBitConfig,
    JikanConfig,
    CacheConfig,
    LoggingConfig,
    ProcessingConfig,
    AIRoleConfig,
    VibeMangaConfig,
    setup_config,
    get_config,
    reload_config,
    get_library_path,
    get_ai_config,
    get_qbit_config,
    get_cache_config,
    get_logging_config,
    get_processing_config,
    get_ai_role_config,
)

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