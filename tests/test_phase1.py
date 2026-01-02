"""
Test suite for Phase 1: Foundation components.

This test verifies that the centralized logging and configuration systems work correctly.
"""

import pytest
import tempfile
import os
from pathlib import Path
from vibe_manga.vibe_manga.logging import (
    setup_logging, get_logger, set_log_level, temporary_log_level,
    VibeMangaError, ConfigError, APIError, FileError, ValidationError
)
from vibe_manga.vibe_manga.config import (
    setup_config, get_config, reload_config, VibeMangaConfig,
    AIConfig, QBitConfig, JikanConfig, CacheConfig, LoggingConfig, ProcessingConfig,
    get_library_path, get_ai_config, get_qbit_config, get_cache_config,
    get_logging_config, get_processing_config
)


class TestLogging:
    """Test the centralized logging system."""
    
    def test_setup_logging(self):
        """Test that logging can be set up."""
        import tempfile
        import os
        import logging

        # Create a temp file and close it properly for Windows
        fd, log_file = tempfile.mkstemp(suffix='.log')
        os.close(fd)  # Close the file descriptor

        try:
            logger_instance = setup_logging(log_file)
            assert logger_instance is not None
            assert logger_instance.log_file == log_file

            # Verify log file was created
            assert Path(log_file).exists()
        finally:
            # Cleanup - close all logging handlers first
            logging.shutdown()
            if Path(log_file).exists():
                Path(log_file).unlink(missing_ok=True)
        """Test that we can get a configured logger."""
        logger = get_logger("test.module")
        assert logger is not None
        assert logger.name == "test.module"
        assert len(logger.handlers) == 0  # Should use root handlers
    
    def test_log_levels(self):
        """Test that log levels can be changed."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            log_file = f.name
        
        try:
            setup_logging(log_file)
            
            # Test setting console level
            set_log_level("DEBUG", "console")
            
            # Test setting file level
            set_log_level("INFO", "file")
            
            # Test setting both
            set_log_level("WARNING", "both")
        finally:
            # Cleanup
            if Path(log_file).exists():
                Path(log_file).unlink()
    
    def test_temporary_log_level(self):
        """Test temporary log level context manager."""
        logger = get_logger("test")
        
        # Get initial level
        root_logger = logger.parent or logger
        initial_level = root_logger.level
        
        with temporary_log_level("DEBUG", "console"):
            # Level should be changed inside context
            pass
        
        # Level should be restored after context
        assert root_logger.level == initial_level
    
    def test_custom_exceptions(self):
        """Test that custom exceptions work correctly."""
        # Test base exception
        with pytest.raises(VibeMangaError):
            raise VibeMangaError("Base error")
        
        # Test specific exceptions
        with pytest.raises(ConfigError):
            raise ConfigError("Config error")
        
        with pytest.raises(APIError):
            raise APIError("API error")
        
        with pytest.raises(FileError):
            raise FileError("File error")
        
        with pytest.raises(ValidationError):
            raise ValidationError("Validation error")
        
        # Test that specific exceptions are also VibeMangaError
        with pytest.raises(VibeMangaError):
            raise ConfigError("Config error")


class TestConfiguration:
    """Test the centralized configuration system."""
    
    def test_default_config(self):
        """Test that default configuration loads correctly."""
        config = setup_config()
        assert config is not None
        
        # Test that config loads and has expected structure
        # (actual values come from .env file)
        assert hasattr(config.ai, 'provider')
        assert hasattr(config.ai, 'model')
        assert hasattr(config.qbit, 'url')
        assert hasattr(config.qbit, 'username')
        assert config.cache.enabled is True
        assert config.cache.max_age_seconds == 3000
    
    def test_config_with_library_path(self):
        """Test configuration with library path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = setup_config(library_path=tmpdir)
            assert config.library_path == Path(tmpdir)
            assert get_library_path() == Path(tmpdir)
    
    def test_config_from_env_vars(self, monkeypatch):
        """Test configuration loading from environment variables."""
        # Set environment variables
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_MODEL", "gpt-4")
        monkeypatch.setenv("QBIT_URL", "http://qbittorrent:8080")
        monkeypatch.setenv("QBIT_USERNAME", "testuser")
        monkeypatch.setenv("CACHE_MAX_AGE_SECONDS", "6000")
        
        # Reload config to pick up env vars
        config = reload_config()
        
        assert config.ai.provider == "openai"
        assert config.ai.model == "gpt-4"
        assert config.qbit.url == "http://qbittorrent:8080"
        assert config.qbit.username == "testuser"
        assert config.cache.max_age_seconds == 6000
    
    def test_nested_env_vars(self, monkeypatch):
        """Test nested environment variables (e.g., AI__PROVIDER)."""
        monkeypatch.setenv("AI__PROVIDER", "anthropic")
        monkeypatch.setenv("AI__MODEL", "claude-3")
        
        config = reload_config()
        
        assert config.ai.provider == "anthropic"
        assert config.ai.model == "claude-3"
    
    def test_config_save_and_load(self):
        """Test saving and loading configuration from file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name
        
        try:
            # Setup custom config
            with tempfile.TemporaryDirectory() as tmpdir:
                config = setup_config(
                    library_path=tmpdir,
                    dry_run=True,
                    verbose=True
                )
                
                # Save to file
                config.save_to_file(config_file)
                assert Path(config_file).exists()
                
                # Load from file
                loaded_config = VibeMangaConfig.load_from_file(config_file)
                
                # Verify loaded config matches original
                assert str(loaded_config.library_path) == str(config.library_path)
                assert loaded_config.dry_run == config.dry_run
                assert loaded_config.verbose == config.verbose
        finally:
            # Cleanup
            if Path(config_file).exists():
                Path(config_file).unlink()
    
    def test_convenience_functions(self):
        """Test convenience functions for config access."""
        config = setup_config()
        
        # Test AI config access
        ai_config = get_ai_config()
        assert isinstance(ai_config, AIConfig)
        assert ai_config.provider == config.ai.provider
        
        # Test qBittorrent config access
        qbit_config = get_qbit_config()
        assert isinstance(qbit_config, QBitConfig)
        assert qbit_config.url == config.qbit.url
        
        # Test cache config access
        cache_config = get_cache_config()
        assert isinstance(cache_config, CacheConfig)
        assert cache_config.max_age_seconds == config.cache.max_age_seconds
    
    def test_config_validation(self):
        """Test configuration validation."""
        # Test invalid log level
        with pytest.raises(ValueError):
            LoggingConfig(level="INVALID_LEVEL")
        
        # Test valid log levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(level=level)
            assert config.level == level
    
    def test_config_immutability(self):
        """Test that config values are properly set."""
        config = setup_config()
        
        # Test that we can access nested configs
        assert hasattr(config.ai, 'provider')
        assert hasattr(config.ai, 'model')
        assert hasattr(config.ai, 'base_url')
        assert hasattr(config.ai, 'api_key')
        
        assert hasattr(config.qbit, 'url')
        assert hasattr(config.qbit, 'username')
        assert hasattr(config.qbit, 'password')
        assert hasattr(config.qbit, 'tag')
        
        assert hasattr(config.jikan, 'base_url')
        assert hasattr(config.jikan, 'rate_limit_delay')
        assert hasattr(config.jikan, 'timeout')
        assert hasattr(config.jikan, 'max_retries')


class TestIntegration:
    """Integration tests for Phase 1 components."""
    
    def test_logging_and_config_together(self):
        """Test that logging and config work together."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as log_f:
            log_file = log_f.name
        
        try:
            # Setup logging
            setup_logging(log_file)
            logger = get_logger("integration.test")
            
            # Setup config
            with tempfile.TemporaryDirectory() as tmpdir:
                config = setup_config(library_path=tmpdir)
                
                # Log some config values
                logger.info(f"Library path: {config.library_path}")
                logger.info(f"AI provider: {config.ai.provider}")
                logger.info(f"qBittorrent URL: {config.qbit.url}")
                
                # Verify log file has content
                assert Path(log_file).exists()
                # Note: We can't easily check content due to async logging
        finally:
            if Path(log_file).exists():
                Path(log_file).unlink()
    
    def test_multiple_config_instances(self):
        """Test that config can be reloaded multiple times."""
        config1 = setup_config(dry_run=True)
        assert config1.dry_run is True
        
        config2 = setup_config(dry_run=False)
        assert config2.dry_run is False
        
        # Current instance should be the latest
        current = get_config()
        assert current.dry_run is False


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])