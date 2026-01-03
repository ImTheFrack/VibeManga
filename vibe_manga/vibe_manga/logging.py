"""
Centralized logging and error handling for VibeManga.

This module provides consistent logging configuration and custom exceptions
across the entire application.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Union
from rich.logging import RichHandler
from rich.console import Console
from rich.panel import Panel

# Global console instance for the entire application
console = Console()

class VibeMangaError(Exception):
    """Base exception for all VibeManga-specific errors."""
    pass


class ConfigError(VibeMangaError):
    """Raised when there's a configuration-related error."""
    pass


class APIError(VibeMangaError):
    """Raised when an external API call fails (Jikan, AI, qBittorrent)."""
    pass


class FileError(VibeMangaError):
    """Raised when a file operation fails."""
    pass


class ValidationError(VibeMangaError):
    """Raised when data validation fails."""
    pass


class VibeMangaLogger:
    """
    Centralized logging configuration for VibeManga.
    
    This class provides a single source of truth for all logging configuration,
    ensuring consistent log formats, levels, and handlers across the application.
    """
    
    def __init__(self, log_file: str = "vibe_manga.log"):
        self.log_file = log_file
        self.console = console
        self._setup_root_logger()
    
    def _setup_root_logger(self) -> None:
        """Configure the root logger with file and console handlers."""
        # Create formatters
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # File handler (full detail) - Use UTF-8 to prevent encoding errors on Windows
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(file_formatter)
        
        # Console handler (errors and warnings) - Use RichHandler for better Unicode support
        console_handler = RichHandler(
            console=self.console,
            show_path=False,
            show_time=True,
            show_level=True,
            markup=True,
            keywords=[]
        )
        console_handler.setLevel(logging.WARNING)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # Clear existing handlers to avoid duplicates
        root_logger.handlers = []
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a configured logger instance.
        
        Args:
            name: The logger name (typically __name__)
            
        Returns:
            A configured logger instance
        """
        return logging.getLogger(name)
    
    def set_console_level(self, level: Union[str, int], clean: bool = False) -> None:
        """
        Set the console logging level.
        
        Args:
            level: Logging level (e.g., 'DEBUG', 'INFO', 'WARNING')
            clean: If True, hides time and level for a cleaner UI-like look
        """
        root_logger = logging.getLogger()
        
        # Convert string level to numeric if needed
        numeric_level = level
        if isinstance(level, str):
            numeric_level = getattr(logging, level.upper(), logging.INFO)
            
        # Ensure root logger allows this level
        if numeric_level < root_logger.level:
            root_logger.setLevel(numeric_level)

        for handler in root_logger.handlers:
            if isinstance(handler, RichHandler):
                handler.setLevel(level)
                handler.show_time = not clean
                handler.show_level = not clean
                handler.markup = True # Ensure markup is enabled
                break
    
    def set_file_level(self, level: Union[str, int]) -> None:
        """
        Set the file logging level.
        
        Args:
            level: Logging level (e.g., 'DEBUG', 'INFO', 'WARNING')
        """
        root_logger = logging.getLogger()
        
        # Convert string level to numeric if needed
        numeric_level = level
        if isinstance(level, str):
            numeric_level = getattr(logging, level.upper(), logging.INFO)
            
        # Ensure root logger allows this level
        if numeric_level < root_logger.level:
            root_logger.setLevel(numeric_level)

        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(level)
                break


# Global logger instance
_logger_instance: Optional[VibeMangaLogger] = None


def setup_logging(log_file: str = "vibe_manga.log") -> VibeMangaLogger:
    """
    Set up the global logging configuration.
    
    Args:
        log_file: Path to the log file
        
    Returns:
        The configured VibeMangaLogger instance
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = VibeMangaLogger(log_file)
    return _logger_instance


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.
    
    This should be called in each module as:
        from vibe_manga.logging import get_logger
        logger = get_logger(__name__)
    
    Args:
        name: The logger name (typically __name__)
        
    Returns:
        A configured logger instance
    """
    if _logger_instance is None:
        setup_logging()
    return logging.getLogger(name)


def set_log_level(level: Union[str, int], handler_type: str = "both", clean: bool = False) -> None:
    """
    Set the logging level for console, file, or both handlers.
    
    Args:
        level: Logging level (e.g., 'DEBUG', 'INFO', 'WARNING', 'ERROR')
        handler_type: 'console', 'file', or 'both'
        clean: If True, hides time and level for console handler
    """
    if _logger_instance is None:
        setup_logging()
    
    if handler_type in ("console", "both"):
        _logger_instance.set_console_level(level, clean=clean)
    if handler_type in ("file", "both"):
        _logger_instance.set_file_level(level)


# Convenience function for error handling with context
def log_and_raise_error(exception: VibeMangaError, logger: logging.Logger):
    """
    Log an error and raise the exception.
    
    Args:
        exception: The exception to raise
        logger: The logger to use
    """
    logger.error(str(exception))
    raise exception


# Context manager for temporary log level changes
from contextlib import contextmanager

@contextmanager
def temporary_log_level(level: Union[str, int], handler_type: str = "console"):
    """
    Temporarily change the log level.
    
    Usage:s
        with temporary_log_level("DEBUG"):
            # Debug logging enabled here
            ...
        # Original log level restored
    """
    if _logger_instance is None:
        setup_logging()
    
    # Get current level
    root_logger = logging.getLogger()
    current_level = None
    
    for handler in root_logger.handlers:
        if handler_type == "console" and isinstance(handler, RichHandler):
            current_level = handler.level
            handler.setLevel(level)
            break
        elif handler_type == "file" and isinstance(handler, logging.FileHandler):
            current_level = handler.level
            handler.setLevel(level)
            break
    
    try:
        yield
    finally:
        # Restore original level
        if current_level is not None:
            for handler in root_logger.handlers:
                if handler_type == "console" and isinstance(handler, RichHandler):
                    handler.setLevel(current_level)
                    break
                elif handler_type == "file" and isinstance(handler, logging.FileHandler):
                    handler.setLevel(current_level)
                    break


def log_step(message: str) -> None:
    """
    Log a major step with a visual panel.
    Logs to file as INFO, prints to console as Panel if level <= INFO.
    """
    if _logger_instance is None:
        setup_logging()
    
    # Log to file (always happens if file handler is INFO+, which it is by default)
    file_logger = logging.getLogger("vibe_manga.step")
    file_logger.info(f"STEP: {message}")
    
    # Visual for console
    # Check effective console level
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, RichHandler):
            if handler.level <= logging.INFO:
                _logger_instance.console.print(Panel(message, style="bold magenta"))
            break


def log_substep(message: str) -> None:
    """
    Log a sub-step with indentation.
    """
    if _logger_instance is None:
        setup_logging()
    
    logger = get_logger("vibe_manga.substep")
    # We prefix with "  ->" to show hierarchy in text logs
    # Using [dim] for the arrow to keep it subtle
    logger.info(f"  [bold cyan]->[/bold cyan] {message}")


def log_api_call(url: str, method: str, params: Optional[dict] = None) -> None:
    """
    Log an API call with sensitive data masking.
    Logs at DEBUG level.
    """
    if _logger_instance is None:
        setup_logging()
        
    logger = get_logger("vibe_manga.api")
    
    # Quick check to avoid processing if not debug
    if not logger.isEnabledFor(logging.DEBUG):
        return

    safe_params = "None"
    if params:
        safe_params = params.copy()
        keys_to_mask = ['api_key', 'token', 'password', 'secret', 'key']
        for k in safe_params:
            if isinstance(k, str) and any(m in k.lower() for m in keys_to_mask):
                safe_params[k] = "********"
        safe_params = str(safe_params)
        
    logger.debug(f"API CALL: {method} {url} | Params: {safe_params}")


__all__ = [
    "VibeMangaError",
    "ConfigError",
    "APIError",
    "FileError",
    "ValidationError",
    "VibeMangaLogger",
    "setup_logging",
    "get_logger",
    "set_log_level",
    "log_and_raise_error",
    "temporary_log_level",
    "log_step",
    "log_substep",
    "log_api_call",
]
