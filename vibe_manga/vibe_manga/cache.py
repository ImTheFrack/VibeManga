"""
Caching functionality for VibeManga library scans.
"""

import logging
import pickle
import time
from pathlib import Path
from typing import Optional

from .models import Library
from .constants import DEFAULT_CACHE_MAX_AGE_SECONDS, CACHE_FILENAME

logger = logging.getLogger(__name__)


def get_cache_path(library_root: Path) -> Path:
    """Returns the cache file path for a given library root."""
    return library_root / CACHE_FILENAME


def get_cached_library(
    root: Path,
    max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS
) -> Optional[Library]:
    """
    Retrieves a cached library scan if available and fresh.

    Args:
        root: The library root path.
        max_age_seconds: Maximum age of cache in seconds (default: 300 = 5 minutes).

    Returns:
        Cached Library object if valid, None otherwise.
    """
    cache_file = get_cache_path(root)

    if not cache_file.exists():
        logger.debug(f"No cache file found at {cache_file}")
        return None

    try:
        cache_age = time.time() - cache_file.stat().st_mtime

        if cache_age > max_age_seconds:
            logger.info(f"Cache is stale ({cache_age:.1f}s old, max {max_age_seconds}s)")
            return None

        logger.info(f"Loading cached library scan ({cache_age:.1f}s old)")
        with open(cache_file, 'rb') as f:
            library = pickle.load(f)

        logger.debug(f"Successfully loaded cache: {library.total_series} series")
        return library

    except (pickle.PickleError, EOFError, FileNotFoundError) as e:
        logger.warning(f"Failed to load cache: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading cache: {e}")
        return None


def save_library_cache(library: Library) -> bool:
    """
    Saves a library scan to the cache.

    Args:
        library: The Library object to cache.

    Returns:
        True if successful, False otherwise.
    """
    cache_file = get_cache_path(library.path)

    try:
        logger.info(f"Saving library cache to {cache_file}")
        with open(cache_file, 'wb') as f:
            pickle.dump(library, f)
        logger.debug(f"Cache saved successfully: {library.total_series} series")
        return True

    except (pickle.PickleError, OSError) as e:
        logger.error(f"Failed to save cache: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving cache: {e}")
        return False


def clear_cache(library_root: Path) -> bool:
    """
    Clears the cache for a given library.

    Args:
        library_root: The library root path.

    Returns:
        True if cache was cleared, False if no cache existed or error occurred.
    """
    cache_file = get_cache_path(library_root)

    if not cache_file.exists():
        logger.debug("No cache file to clear")
        return False

    try:
        cache_file.unlink()
        logger.info(f"Cache cleared: {cache_file}")
        return True
    except OSError as e:
        logger.error(f"Failed to clear cache: {e}")
        return False
