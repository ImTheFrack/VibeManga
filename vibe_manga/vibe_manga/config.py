import json
import os
import logging
from typing import Dict, Any, Optional

from .constants import ROLE_CONFIG

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "vibe_manga_ai_config.json"

def load_ai_config() -> Dict[str, Any]:
    """Loads user-defined AI configuration from JSON."""
    if os.path.exists(CONFIG_FILENAME):
        try:
            with open(CONFIG_FILENAME, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load AI config: {e}")
    return {}

def save_ai_config(config: Dict[str, Any]) -> None:
    """Saves user-defined AI configuration to JSON."""
    try:
        with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save AI config: {e}")

def get_role_config(role_name: str) -> Dict[str, Any]:
    """
    Resolves the configuration for a specific role.
    Prioritizes User Config (JSON) > Default Config (constants.py).
    """
    defaults = ROLE_CONFIG.get(role_name, {})
    user_config = load_ai_config().get("roles", {}).get(role_name, {})
    
    # Merge: User config overrides defaults
    merged = defaults.copy()
    merged.update(user_config)
    
    return merged
