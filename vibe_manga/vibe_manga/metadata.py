import json
import logging
import time
import requests
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

from .constants import ROLE_METADATA_FETCHER, ROLE_CONFIG, REMOTE_AI_API_KEY
from .ai_api import call_ai
from .config import get_role_config
from .analysis import semantic_normalize

logger = logging.getLogger(__name__)

# Jikan API constants
JIKAN_BASE_URL = "https://api.jikan.moe/v4"
JIKAN_RATE_LIMIT_DELAY = 1.2  # Increased to 1.2s to be safer

@dataclass
class SeriesMetadata:
    """
    Standardized schema for manga metadata.
    saved to series.json in each series folder.
    """
    title: str = "Unknown"
    authors: List[str] = field(default_factory=list)
    synopsis: str = ""
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    demographics: List[str] = field(default_factory=list)
    status: str = "Unknown" # Completed, Ongoing, Hiatus, Cancelled
    total_volumes: Optional[int] = None
    total_chapters: Optional[int] = None
    release_year: Optional[int] = None
    mal_id: Optional[int] = None
    anilist_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SeriesMetadata':
        # Filter unknown keys to prevent init errors if schema changes
        valid_keys = cls.__annotations__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)

def load_local_metadata(series_path: Path) -> Optional[SeriesMetadata]:
    """Loads metadata from series.json in the series directory."""
    meta_path = series_path / "series.json"
    if not meta_path.exists():
        return None
    
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return SeriesMetadata.from_dict(data)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load metadata from {meta_path}: {e}")
        return None

def save_local_metadata(series_path: Path, metadata: SeriesMetadata) -> bool:
    """Saves metadata to series.json in the series directory."""
    meta_path = series_path / "series.json"
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata.to_dict(), f, indent=4, ensure_ascii=False)
        return True
    except IOError as e:
        logger.error(f"Failed to save metadata to {meta_path}: {e}")
        return False

def fetch_from_jikan(query: str) -> Optional[SeriesMetadata]:
    """
    Searches Jikan (MAL) for manga metadata.
    Returns the first best match or None.
    """
    try:
        time.sleep(JIKAN_RATE_LIMIT_DELAY) # Rate limiting
        
        # Search for the manga
        search_url = f"{JIKAN_BASE_URL}/manga"
        params = {
            "q": query,
            "limit": 10,  # Fetch more to find a better match
            "sfw": "false" # Include mature content since we are a manga library
        }
        
        resp = requests.get(search_url, params=params, timeout=10)
        resp.raise_for_status()
        
        data = resp.json()
        results = data.get("data", [])
        if not results:
            return None
            
        # Try to find the best match semantically
        norm_query = semantic_normalize(query)
        best_match = None
        
        for res in results:
            # Check all possible titles Jikan provides
            candidate_titles = [res.get("title"), res.get("title_english"), res.get("title_japanese")]
            # Also check the 'titles' list if available
            for t_obj in res.get("titles", []):
                candidate_titles.append(t_obj.get("title"))
            
            for cand in candidate_titles:
                if cand and semantic_normalize(cand) == norm_query:
                    best_match = res
                    break
            if best_match:
                break
        
        # Fallback to the first result if no perfect semantic match found
        result = best_match or results[0]
        
        # Parse Jikan format into our schema
        authors = [a["name"] for a in result.get("authors", [])]
        genres = [g["name"] for g in result.get("genres", [])]
        themes = [t["name"] for t in result.get("themes", [])] # Treat themes as tags
        demographics = [d["name"] for d in result.get("demographics", [])]
        
        # Normalize status
        status_map = {
            "Finished": "Completed",
            "Publishing": "Ongoing",
            "On Hiatus": "Hiatus",
            "Discontinued": "Cancelled",
            "Not yet published": "Upcoming"
        }
        raw_status = result.get("status", "Unknown")
        status = status_map.get(raw_status, raw_status)

        return SeriesMetadata(
            title=result.get("title_english") or result.get("title", query),
            authors=authors,
            synopsis=result.get("synopsis", ""),
            genres=genres,
            tags=themes,
            demographics=demographics,
            status=status,
            total_volumes=result.get("volumes"),
            total_chapters=result.get("chapters"),
            release_year=result.get("published", {}).get("prop", {}).get("from", {}).get("year"),
            mal_id=result.get("mal_id")
        )
        
    except Exception as e:
        logger.warning(f"Jikan API failed for '{query}': {e}")
        return None

def fetch_from_ai(query: str) -> Optional[SeriesMetadata]:
    """
    Fallback: Asks AI to hallucinate (smartly) the metadata.
    Uses the configured Metadata Fetcher role.
    """
    config = get_role_config("METADATA")
    provider = config["provider"]
    model = config["model"]
    
    # Fallback to local if remote is requested but no key is set
    if provider == "remote" and not REMOTE_AI_API_KEY:
        logger.warning("Remote AI requested for metadata but no API key found. Falling back to Local AI.")
        provider = "local"
        # We assume local model is set in env or defaults
        model = None 

    prompt = f"Provide detailed metadata for the manga series: '{query}'. If exact numbers are unknown, estimate based on general knowledge or set to null."
    
    result = call_ai(
        user_prompt=prompt,
        system_role=config["role_prompt"],
        provider=provider,
        model=model
    )
    
    if isinstance(result, dict):
        try:
            return SeriesMetadata.from_dict(result)
        except Exception as e:
            logger.error(f"AI returned invalid metadata structure: {e}")
            
    return None

def enrich_with_ai(query: str, current_meta: SeriesMetadata) -> Optional[SeriesMetadata]:
    """
    Uses the Metadata Supervisor role to verify if the Jikan match is correct
    and fill in any missing gaps.
    """
    config = get_role_config("SUPERVISOR")
    provider = config["provider"]
    model = config["model"]

    # Fallback checks
    if provider == "remote" and not REMOTE_AI_API_KEY:
        logger.info("Skipping AI enrichment (no remote key). Using Jikan data as-is.")
        return current_meta

    prompt = f"User Query: {query}\nAPI Metadata: {json.dumps(current_meta.to_dict(), ensure_ascii=False)}"
    
    logger.info(f"Asking AI Supervisor to verify/enrich '{query}'...")
    result = call_ai(
        user_prompt=prompt,
        system_role=config["role_prompt"],
        provider=provider,
        model=model
    )
    
    if isinstance(result, dict):
        is_match = result.get("is_match", False)
        reason = result.get("reason", "No reason")
        
        if not is_match:
            logger.warning(f"AI Supervisor rejected Jikan match for '{query}': {reason}")
            return None # Signal that Jikan data was bad
            
        enriched_data = result.get("metadata")
        if enriched_data:
            try:
                logger.info(f"AI Supervisor approved and enriched '{query}'.")
                new_meta = SeriesMetadata.from_dict(enriched_data)
                
                # PRESERVE IDs from API if AI didn't provide them or set them to null
                if new_meta.mal_id is None:
                    new_meta.mal_id = current_meta.mal_id
                if new_meta.anilist_id is None:
                    new_meta.anilist_id = current_meta.anilist_id
                
                return new_meta
            except Exception as e:
                logger.error(f"Failed to parse enriched metadata: {e}")
    
    return current_meta # Fallback to original if AI fails to parse

def get_or_create_metadata(series_path: Path, series_name: str, force_update: bool = False, trust_jikan: bool = False) -> Tuple[SeriesMetadata, str]:
    """
    Main entry point.
    1. Checks local series.json (unless force_update).
    2. Tries Jikan API.
    3. Verifies/Enriches with AI (Supervisor).
    4. Fallback to AI (Fetcher) if rejected or not found.
    5. Saves result to series.json.
    
    Returns (Metadata, SourceString)
    """
    if not force_update:
        local = load_local_metadata(series_path)
        if local:
            logger.info(f"Using local metadata for '{series_name}'")
            return local, "Local"
            
    # Try Jikan first (Free, Accurate)
    logger.info(f"Fetching metadata for '{series_name}' from Jikan...")
    meta = fetch_from_jikan(series_name)
    source = "Jikan"
    
    if meta:
        logger.info(f"Jikan found a match for '{series_name}': {meta.title}")
        
        # Rule 1: If --trust is enabled and Jikan result is a perfect semantic match, skip AI
        if trust_jikan:
            norm_query = semantic_normalize(series_name)
            norm_jikan = semantic_normalize(meta.title)
            if norm_query == norm_jikan:
                logger.info(f"Trusting Jikan match for '{series_name}' (Perfect Match)")
                save_local_metadata(series_path, meta)
                return meta, "Jikan (Trusted)"

        # Verify and Enrich with AI
        # If verify fails, it returns None, triggering the fallback below
        enriched = enrich_with_ai(series_name, meta)
        if enriched:
            meta = enriched
            source = "AI Supervisor"
        else:
            meta = None # Supervisor rejected Jikan match

    # Fallback to AI if Jikan fails, yields poor results, or was rejected by Supervisor
    if not meta:
        logger.info(f"Jikan failed or was rejected. Asking AI (Fetcher) for '{series_name}'...")
        meta = fetch_from_ai(series_name)
        source = "AI Fetcher"
        
    if meta:
        logger.info(f"Saving metadata for '{series_name}' to {series_path}")
        save_local_metadata(series_path, meta)
        return meta, source
        
    # Return empty metadata if all else fails
    logger.warning(f"Could not find metadata for '{series_name}'. Creating empty placeholder.")
    empty = SeriesMetadata(title=series_name)
    save_local_metadata(series_path, empty)
    return empty, "None"
