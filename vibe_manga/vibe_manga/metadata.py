import json
import logging
import time
import requests
import difflib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple

from .constants import ROLE_CONFIG, REMOTE_AI_API_KEY, AI_MAX_RETRIES
from .ai_api import call_ai
from .config import get_ai_role_config
from .analysis import semantic_normalize
from .models import SeriesMetadata

logger = logging.getLogger(__name__)

# Jikan API constants
JIKAN_BASE_URL = "https://api.jikan.moe/v4"
JIKAN_RATE_LIMIT_DELAY = 1.2  # Increased to 1.2s to be safer

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

def calculate_similarity(query: str, candidate: str) -> float:
    """Calculates similarity ratio between query and candidate."""
    if not query or not candidate:
        return 0.0
    return difflib.SequenceMatcher(None, query, candidate).ratio()

def fetch_from_jikan(query: str, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Searches Jikan (MAL) for manga metadata.
    Returns the best matching result based on similarity score.
    """
    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            if status_callback:
                status_callback("Pulling from Jikan API...")
            time.sleep(JIKAN_RATE_LIMIT_DELAY) # Rate limiting
            
            # Search for the manga
            search_url = f"{JIKAN_BASE_URL}/manga"
            params = {
                "q": query,
                "limit": 15,  # Fetch more to find a better match
                "sfw": "false" # Include mature content since we are a manga library
            }
            
            resp = requests.get(search_url, params=params, timeout=10)
            
            if resp.status_code == 429:
                msg = f"Jikan Rate Limit (429). Retrying (Attempt {attempt+1}/{AI_MAX_RETRIES+1})..."
                logger.debug(msg)
                if status_callback:
                    status_callback(f"[yellow]{msg}[/yellow]")
                time.sleep(2 * (attempt + 1))
                continue
                
            resp.raise_for_status()
            
            data = resp.json()
            results = data.get("data", [])
            if not results:
                return None
                
            norm_query = semantic_normalize(query)
            scored_results = []
            
            for res in results:
                # Collect all possible titles
                candidates = set()
                if res.get("title"): candidates.add(res.get("title"))
                if res.get("title_english"): candidates.add(res.get("title_english"))
                if res.get("title_japanese"): candidates.add(res.get("title_japanese"))
                for t_obj in res.get("titles", []):
                    if t_obj.get("title"): candidates.add(t_obj.get("title"))
                
                # Find best score for this result
                max_score = 0.0
                best_match_title = ""
                
                for cand in candidates:
                    # Score 1: Normalized semantic match (aggressive)
                    norm_cand = semantic_normalize(cand)
                    score_norm = calculate_similarity(norm_query, norm_cand)
                    
                    # Score 2: Raw match (less aggressive, catches specific punctuation/subtitle nuances)
                    # Use lower() to be case insensitive but keep punctuation
                    score_raw = calculate_similarity(query.lower(), cand.lower())
                    
                    score = max(score_norm, score_raw)
                    
                    if score > max_score:
                        max_score = score
                        best_match_title = cand
                        
                scored_results.append((max_score, res, best_match_title))
                
            # Sort by score descending
            scored_results.sort(key=lambda x: x[0], reverse=True)
            
            if not scored_results:
                return None
                
            best_score, best_result, match_title = scored_results[0]
            
            logger.info(f"Jikan Best Match: '{match_title}' (Score: {best_score:.2f}) for query '{query}'")
            if status_callback:
                status_callback(f"Best match: {match_title} ({best_score:.0%})")
                
            # Optional: Threshold check? 
            # If the best score is very low (e.g. < 0.4), maybe return None?
            # For now, we trust the relative ranking, but let Supervisor check it.
            
            result = best_result
            
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

            # Extract titles
            main_title = result.get("title_english") or result.get("title", query)
            t_eng = result.get("title_english")
            t_jp = result.get("title_japanese")
            
            # Synonyms
            syns = []
            for t_obj in result.get("titles", []):
                t_val = t_obj.get("title")
                if t_val and t_val not in [main_title, t_eng, t_jp]:
                    syns.append(t_val)

            return SeriesMetadata(
                title=main_title,
                title_english=t_eng,
                title_japanese=t_jp,
                synonyms=syns,
                authors=authors,
                synopsis=result.get("synopsis", ""),
                genres=genres,
                tags=themes,
                demographics=demographics,
                status=status,
                total_volumes=result.get("volumes"),
                total_chapters=result.get("chapters"),
                release_year=result.get("published", {}).get("prop", {}).get("from", {}).get("year"),
                mal_id=result.get("mal_id"),
                anilist_id=None # Jikan is MAL only
            )
            
        except Exception as e:
            logger.debug(f"Jikan API failed for '{query}' (Attempt {attempt+1}): {e}")
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
            return None
    return None


def fetch_from_ai(query: str, existing_meta: Optional[SeriesMetadata] = None, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Fallback: Asks AI to hallucinate (smartly) the metadata.
    Uses the configured Metadata Fetcher role.
    """
    config = get_ai_role_config("METADATA")
    provider = config["provider"]
    model = config["model"]
    
    # Fallback to local if remote is requested but no key is set
    if provider == "remote" and not REMOTE_AI_API_KEY:
        logger.warning("Remote AI requested for metadata but no API key found. Falling back to Local AI.")
        provider = "local"
        # We assume local model is set in env or defaults
        model = None 

    prompt = f"Provide detailed metadata for the manga series: '{query}'."
    if existing_meta and existing_meta.title != "Unknown":
        prompt += f"\nExisting partial/local metadata (JSON): {json.dumps(existing_meta.to_dict(), ensure_ascii=False)}"
    
    prompt += "\nIf exact numbers are unknown, estimate based on general knowledge or set to null."
    
    if status_callback:
        status_callback(f"Asking AI Fetcher ({provider})...")

    result = call_ai(
        user_prompt=prompt,
        system_role=config["role_prompt"],
        provider=provider,
        model=model,
        status_callback=status_callback
    )
    
    if isinstance(result, dict):
        try:
            return SeriesMetadata.from_dict(result)
        except Exception as e:
            logger.error(f"AI returned invalid metadata structure: {e}")
            
    return None

def enrich_with_ai(query: str, current_meta: SeriesMetadata, existing_meta: Optional[SeriesMetadata] = None, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Uses the Metadata Supervisor role to verify if the Jikan match is correct
    and fill in any missing gaps.
    """
    config = get_ai_role_config("SUPERVISOR")
    provider = config["provider"]
    model = config["model"]

    # Fallback checks
    if provider == "remote" and not REMOTE_AI_API_KEY:
        logger.info("Skipping AI enrichment (no remote key). Using Jikan data as-is.")
        return current_meta

    prompt = f"User Query: {query}\nAPI Metadata (Jikan): {json.dumps(current_meta.to_dict(), ensure_ascii=False)}"
    if existing_meta and existing_meta.title != "Unknown":
        prompt += f"\nLocal/Existing Metadata (JSON): {json.dumps(existing_meta.to_dict(), ensure_ascii=False)}"
    
    logger.info(f"Asking AI Supervisor to verify/enrich '{query}'...")
    if status_callback:
        status_callback(f"Validating against AI Supervisor ({provider})...")

    result = call_ai(
        user_prompt=prompt,
        system_role=config["role_prompt"],
        provider=provider,
        model=model,
        status_callback=status_callback
    )
    
    if isinstance(result, dict):
        is_match = result.get("is_match", False)
        reason = result.get("reason", "No reason")
        
        if not is_match:
            msg = f"AI Supervisor rejected Jikan match: {reason}"
            logger.debug(f"{msg} for '{query}'")
            if status_callback:
                status_callback(f"[red]Rejected: {reason}[/red]")
            return None # Signal that Jikan data was bad
            
        enriched_data = result.get("metadata")
        if enriched_data:
            try:
                logger.info(f"AI Supervisor approved and enriched '{query}'.")
                if status_callback:
                    status_callback("AI Supervisor approved match.")
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

def get_or_create_metadata(
    series_path: Path, 
    series_name: str, 
    force_update: bool = False, 
    trust_jikan: bool = False,
    status_callback: Optional[callable] = None
) -> Tuple[SeriesMetadata, str]:
    """
    Main entry point.
    1. Checks local series.json (unless force_update).
    2. Tries Jikan API.
    3. Verifies/Enriches with AI (Supervisor).
    4. Fallback to AI (Fetcher) if rejected or not found.
    5. Saves result to series.json.
    
    Returns (Metadata, SourceString)
    """
    local = load_local_metadata(series_path)
    
    if not force_update and local:
        logger.info(f"Using local metadata for '{series_name}'")
        if status_callback:
            status_callback("Using local metadata.")
        return local, "Local"
            
    # Try Jikan first (Free, Accurate)
    logger.info(f"Fetching metadata for '{series_name}' from Jikan...")
    meta = fetch_from_jikan(series_name, status_callback=status_callback)
    source = "Jikan"
    
    if meta:
        logger.info(f"Jikan found a match for '{series_name}': {meta.title}")
        
        # Rule 1: If --trust is enabled and Jikan result is a perfect semantic match, skip AI
        if trust_jikan:
            norm_query = semantic_normalize(series_name)
            norm_jikan = semantic_normalize(meta.title)
            if norm_query == norm_jikan:
                logger.info(f"Trusting Jikan match for '{series_name}' (Perfect Match)")
                if status_callback:
                    status_callback("Perfect match found (Trusted).")
                save_local_metadata(series_path, meta)
                return meta, "Jikan (Trusted)"

        # Verify and Enrich with AI
        # If verify fails, it returns None, triggering the fallback below
        enriched = enrich_with_ai(series_name, meta, existing_meta=local, status_callback=status_callback)
        if enriched:
            meta = enriched
            source = "AI Supervisor"
        else:
            meta = None # Supervisor rejected Jikan match

    # Fallback to AI if Jikan fails, yields poor results, or was rejected by Supervisor
    if not meta:
        logger.info(f"Jikan failed or was rejected. Asking AI (Fetcher) for '{series_name}'...")
        if status_callback:
            status_callback("Resolving rejection / fetching from AI...")
        meta = fetch_from_ai(series_name, existing_meta=local, status_callback=status_callback)
        source = "AI Fetcher"
        
    if meta:
        logger.info(f"Saving metadata for '{series_name}' to {series_path}")
        save_local_metadata(series_path, meta)
        return meta, source
        
    # Return empty metadata if all else fails
    logger.warning(f"Could not find metadata for '{series_name}'. Creating empty placeholder.")
    if status_callback:
        status_callback("[yellow]Could not find metadata. Using placeholder.[/yellow]")
    empty = SeriesMetadata(title=series_name)
    save_local_metadata(series_path, empty)
    return empty, "None"