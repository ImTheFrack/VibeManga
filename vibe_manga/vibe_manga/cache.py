"""
Caching and persistence functionality for VibeManga library scans.
"""

import hashlib
import logging
import pickle
import json
import time
from pathlib import Path
from typing import Optional

from .models import Library
from .constants import DEFAULT_CACHE_MAX_AGE_SECONDS, CACHE_FILENAME, LIBRARY_STATE_FILENAME

logger = logging.getLogger(__name__)


def get_cache_path(library_root: Path) -> Path:
    """Returns the cache file path based on library root."""
    # Create a safe filename from the library path using stable MD5 hash
    path_str = str(library_root.resolve())
    path_hash = hashlib.md5(path_str.encode()).hexdigest()[-8:]
    filename = f".vibe_manga_cache_{path_hash}.pkl"
    return Path.cwd() / filename


def get_state_path(library_root: Path) -> Path:
    """Returns the persistent state JSON path based on library root."""
    # Create a safe filename from the library path using stable MD5 hash
    path_str = str(library_root.resolve())
    path_hash = hashlib.md5(path_str.encode()).hexdigest()[-8:]
    filename = f"vibe_manga_library_{path_hash}.json"
    return Path.cwd() / filename


def get_cached_library(
    root: Path,
    max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS
) -> Optional[Library]:
    """
    Retrieves a cached library scan if available and fresh.
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
    """
    cache_file = get_cache_path(library.path)

    try:
        logger.info(f"Saving library cache to {cache_file}")
        with open(cache_file, 'wb') as f:
            pickle.dump(library, f)
        logger.debug(f"Cache saved successfully: {library.total_series} series")
        
        # Also save to persistent JSON state
        save_library_state(library)
        
        return True

    except (pickle.PickleError, OSError) as e:
        logger.error(f"Failed to save cache: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving cache: {e}")
        return False


def load_library_state(root: Path) -> Optional[Library]:
    """
    Loads the persistent library state from JSON.
    """
    state_file = get_state_path(root)

    if not state_file.exists():
        logger.debug(f"No persistent state found at {state_file}")
        return None

    try:
        logger.info(f"Loading persistent library state from {state_file}")
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        library = Library.from_dict(data)
        logger.debug(f"Successfully loaded persistent state: {library.total_series} series")
        return library

    except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
        logger.warning(f"Failed to load persistent state: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading state: {e}")
        return None


def save_library_state(library: Library) -> bool:
    """
    Saves the library scan to a persistent JSON state.
    """
    state_file = get_state_path(library.path)

    try:
        logger.info(f"Saving persistent library state to {state_file}")
        data = library.to_dict()
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.debug(f"Persistent state saved successfully")
        return True

    except (TypeError, OSError) as e:
        logger.error(f"Failed to save persistent state: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving state: {e}")
        return False


def clear_cache(library_root: Path) -> bool:
    """
    Clears both cache and persistent state for a given library.
    """
    cache_file = get_cache_path(library_root)
    state_file = get_state_path(library_root)

    cleared = False
    
    if cache_file.exists():
        try:
            cache_file.unlink()
            logger.info(f"Cache cleared: {cache_file}")
            cleared = True
        except OSError as e:
            logger.error(f"Failed to clear cache: {e}")

    if state_file.exists():
        try:
            state_file.unlink()
            logger.info(f"Persistent state cleared: {state_file}")
            cleared = True
        except OSError as e:
            logger.error(f"Failed to clear state: {e}")

    return cleared
