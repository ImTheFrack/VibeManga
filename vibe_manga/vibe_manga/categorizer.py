import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from .models import Library, Category, Series
from .metadata import SeriesMetadata, get_or_create_metadata
from .ai_api import call_ai
from .constants import ROLE_CONFIG
from .config import get_role_config

logger = logging.getLogger(__name__)

def get_ai_categorization(
    series_name: str,
    metadata: SeriesMetadata,
    available_categories: List[str]
) -> Dict[str, Any]:
    """
    Orchestrates the AI categorization flow:
    1. Moderator check
    2. Practical suggestion
    3. Creative suggestion
    4. Consensus decision
    """
    # 1. Moderator
    mod_config = get_role_config("MODERATOR")
    mod_prompt = f"Manga Title: {series_name}\nSynopsis: {metadata.synopsis}\nGenres: {metadata.genres}"
    moderation = call_ai(mod_prompt, mod_config["role_prompt"], provider=mod_config["provider"], model=mod_config["model"])
    
    # 2. Practical
    prac_config = get_role_config("PRACTICAL")
    prac_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
    practical = call_ai(prac_prompt, prac_config["role_prompt"], provider=prac_config["provider"], model=prac_config["model"])
    
    # 3. Creative
    crea_config = get_role_config("CREATIVE")
    crea_prompt = f"Manga: {series_name}\nMetadata: {metadata.to_dict()}\nCategories: {available_categories}"
    creative = call_ai(crea_prompt, crea_config["role_prompt"], provider=crea_config["provider"], model=crea_config["model"])
    
    # 4. Consensus
    cons_config = get_role_config("CONSENSUS")
    cons_prompt = (
        f"Manga: {series_name}\n"
        f"Official Category List: {available_categories}\n"
        f"Moderator View: {moderation}\n"
        f"Pragmatic View: {practical}\n"
        f"Creative View: {creative}"
    )
    consensus = call_ai(cons_prompt, cons_config["role_prompt"], provider=cons_config["provider"], model=cons_config["model"])
    
    return {
        "moderation": moderation,
        "practical": practical,
        "creative": creative,
        "consensus": consensus
    }

def suggest_category(
    series: Series,
    library: Library
) -> Optional[Dict[str, Any]]:
    """
    Fetches metadata and AI suggestions for a single series.
    """
    # Get metadata
    metadata = get_or_create_metadata(series.path, series.name)
    
    # Get flat list of current categories (Main/Sub)
    available = []
    for cat in library.categories:
        if cat.name == "Uncategorized":
            continue
        for sub in cat.sub_categories:
            available.append(f"{cat.name}/{sub.name}")
    
    if not available:
        available = ["Manga/Action", "Manga/Romance", "Manga/Comedy", "Adult/Hentai"]
        
    logger.info(f"Requesting AI categorization for '{series.name}'...")
    results = get_ai_categorization(series.name, metadata, available)
    
    return results
