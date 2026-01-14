import json
import logging
import time
import requests
import difflib
import csv
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple

from .constants import ROLE_CONFIG, REMOTE_AI_API_KEY, AI_MAX_RETRIES
from .ai_api import call_ai
from .config import get_ai_role_config, get_config
from .analysis import semantic_normalize
from .models import SeriesMetadata
from .cache import load_resolution_cache, save_resolution_cache
from .logging import get_logger, log_api_call

logger = get_logger(__name__)

# Jikan API constants
JIKAN_BASE_URL = "https://api.jikan.moe/v4"
JIKAN_RATE_LIMIT_DELAY = 1.2  # Increased to 1.2s to be safer

class RateLimiter:
    """Thread-safe rate limiter."""
    def __init__(self, interval: float):
        self.interval = interval
        self.last_call = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call = time.time()

jikan_limiter = RateLimiter(JIKAN_RATE_LIMIT_DELAY)
anilist_limiter = RateLimiter(get_config().anilist.rate_limit_delay)

def sanitize_search_query(query: str) -> str:
    """
    Normalizes a search query for API compatibility.
    Converts full-width characters to half-width equivalents.
    """
    if not query: return ""
    
    replacements = {
        "：": ":",
        "　": " ",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]"
    }
    
    sanitized = query
    for char, rep in replacements.items():
        sanitized = sanitized.replace(char, rep)
        
    return sanitized.strip()

def _parse_csv_list(text: str) -> List[str]:
    """Parses a string representation of a list from the CSV (e.g., "['Action', 'Comedy']")."""
    if not text or text == "[]":
        return []
    try:
        # Simple/safe parsing for the expected format
        cleaned = text.strip("[]").replace("'", "").replace('"', "")
        return [x.strip() for x in cleaned.split(",")]
    except Exception:
        return []

def get_jikan_csv_path() -> Optional[Path]:
    """Resolves the path to the local Jikan CSV repository."""
    # Check config first
    cfg_path = get_config().jikan.local_repository_path
    if cfg_path and cfg_path.exists():
        return cfg_path
    
    # Fallback to default location in project root/env
    default_path = Path("manga.csv")
    if default_path.exists():
        return default_path
        
    return None

def fetch_from_local_csv(mal_id: int) -> Optional[SeriesMetadata]:
    """Attempts to find a MAL ID in the local CSV repository."""
    csv_path = get_jikan_csv_path()
    if not csv_path:
        return None
        
    try:
        # Optimization: Scanning a large CSV line by line is slow but memory efficient.
        # Ideally we'd index this, but for now we scan.
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if int(row['id']) == mal_id:
                        return _parse_csv_row(row)
                except (ValueError, KeyError):
                    continue
    except Exception as e:
        logger.warning(f"Error reading local Jikan CSV: {e}")
        
    return None

def _parse_csv_row(row: Dict[str, str]) -> SeriesMetadata:
    """Parses a CSV row into SeriesMetadata."""
    
    # Status Normalization
    status_map = {
        "Finished": "Completed",
        "Publishing": "Ongoing",
        "On Hiatus": "Hiatus",
        "Discontinued": "Cancelled",
        "Not yet published": "Upcoming"
    }
    raw_status = row.get("status", "Unknown")
    status = status_map.get(raw_status, raw_status)

    # Date parsing for year
    year = None
    pub_date = row.get("publishing_date", "")
    if pub_date:
        # Format usually "Oct 4, 2002 to ?" or "2002 to ?"
        import re
        m = re.search(r'\d{4}', pub_date)
        if m:
            year = int(m.group(0))

    return SeriesMetadata(
        title=row.get("title_name") or row.get("english_name") or "Unknown",
        title_english=row.get("english_name"),
        title_japanese=row.get("japanese_name"),
        synonyms=_parse_csv_list(row.get("synonymns", "")),
        authors=_parse_csv_list(row.get("authors", "")),
        synopsis=row.get("description", ""),
        genres=_parse_csv_list(row.get("genres", "")),
        tags=_parse_csv_list(row.get("themes", "")),
        demographics=[row.get("demographic")] if row.get("demographic") else [],
        status=status,
        total_volumes=int(float(row["volumes"])) if row.get("volumes") and row["volumes"] != "Unknown" else None,
        total_chapters=int(float(row["chapters"])) if row.get("chapters") and row["chapters"] != "Unknown" else None,
        release_year=year,
        mal_id=int(row["id"]),
        anilist_id=None
    )

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

def fetch_by_id_from_jikan(mal_id: int, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """Fetches metadata for a specific MAL ID from Jikan."""
    
    # 1. Try Local CSV Repository
    local_meta = fetch_from_local_csv(mal_id)
    if local_meta:
        logger.info(f"Local CSV Hit for MAL ID {mal_id}")
        if status_callback:
            status_callback(f"Found in local CSV repository.")
        return local_meta

    # 2. Fallback to API
    url = f"{JIKAN_BASE_URL}/manga/{mal_id}"
    log_api_call(url, "GET", params={"id": mal_id})

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            if status_callback:
                status_callback(f"Fetching ID {mal_id} from Jikan...")
            
            jikan_limiter.wait()
            
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 429:
                msg = f"Jikan Rate Limit (429). Retrying (Attempt {attempt+1}/{AI_MAX_RETRIES+1})..."
                logger.debug(msg)
                if status_callback:
                    status_callback(f"[yellow]{msg}[/yellow]")
                time.sleep(2 * (attempt + 1))
                continue
                
            resp.raise_for_status()
            
            data = resp.json().get("data")
            if not data:
                return None
                
            return _parse_jikan_result(data, query=f"ID:{mal_id}")
            
        except Exception as e:
            logger.error(f"Failed to fetch MAL ID {mal_id} (Attempt {attempt+1}): {e}")
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
            return None
    return None

def _parse_jikan_result(result: Dict[str, Any], query: str = "") -> SeriesMetadata:
    """Parses a Jikan API result dict into SeriesMetadata."""
    authors = [a["name"] for a in result.get("authors", [])]
    genres = [g["name"] for g in result.get("genres", [])]
    themes = [t["name"] for t in result.get("themes", [])] # Treat themes as tags
    demographics = [d["name"] for d in result.get("demographics", [])]
    
    status_map = {
        "Finished": "Completed",
        "Publishing": "Ongoing",
        "On Hiatus": "Hiatus",
        "Discontinued": "Cancelled",
        "Not yet published": "Upcoming"
    }
    raw_status = result.get("status", "Unknown")
    status = status_map.get(raw_status, raw_status)

    main_title = result.get("title_english") or result.get("title", query)
    t_eng = result.get("title_english")
    t_jp = result.get("title_japanese")
    
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
        anilist_id=None
    )

def fetch_from_jikan(query: str, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Searches Jikan (MAL) for manga metadata.
    Checks local resolution cache first.
    Returns the best matching result based on similarity score.
    """
    # 1. Check Resolution Cache
    cache = load_resolution_cache()
    if query in cache:
        mal_id = cache[query]
        if mal_id:
            logger.info(f"Resolution Cache Hit: '{query}' -> MAL ID {mal_id}")
            return fetch_by_id_from_jikan(mal_id, status_callback)
        else:
            logger.info(f"Resolution Cache Hit (Negative): '{query}' is known to have no match.")
            if status_callback:
                status_callback("[dim]Skipping (Cached Failure)[/dim]")
            return None

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            if status_callback:
                status_callback("Pulling from Jikan API...")
            
            jikan_limiter.wait() # Rate limiting with thread safety
            
            # Search for the manga
            search_url = f"{JIKAN_BASE_URL}/manga"
            params = {
                "q": sanitize_search_query(query),
                "limit": 15,  # Fetch more to find a better match
                "sfw": "false" # Include mature content since we are a manga library
            }
            log_api_call(search_url, "GET", params=params)
            
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

            # Update Resolution Cache with success
            try:
                cache = load_resolution_cache()
                cache[query] = best_result.get("mal_id")
                save_resolution_cache(cache)
            except Exception as e:
                logger.warning(f"Failed to update resolution cache: {e}")
            
            return _parse_jikan_result(best_result, query)
            
        except Exception as e:
            logger.debug(f"Jikan API failed for '{query}' (Attempt {attempt+1}): {e}")
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
            
            # If we exhausted attempts, cache failure? 
            # No, maybe network was down. Only cache explicit "No Results".
            return None
    
    # If loop finishes without return (e.g. no results found in ANY attempt or empty lists)
    # We should cache this failure so we don't try again.
    try:
        cache = load_resolution_cache()
        cache[query] = None
        save_resolution_cache(cache)
    except Exception as e:
        logger.warning(f"Failed to update resolution cache: {e}")

    return None


def fetch_from_anilist_by_mal_id(mal_id: int, current_meta: SeriesMetadata, status_callback: Optional[callable] = None) -> SeriesMetadata:
    """
    Enriches existing metadata with data from AniList using the MAL ID.
    Fetches: Tags, Banner/Cover Images, Scores, Popularity, Adult Status.
    """
    if not mal_id:
        return current_meta
        
    query = """
    query ($idMal: Int) {
      Media (idMal: $idMal, type: MANGA) {
        id
        coverImage {
          large
          extraLarge
        }
        bannerImage
        averageScore
        popularity
        isAdult
        tags {
          name
          rank
          isMediaSpoiler
        }
      }
    }
    """
    
    url = get_config().anilist.base_url
    
    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            if status_callback:
                status_callback(f"Enriching from AniList (MAL ID: {mal_id})...")
            
            anilist_limiter.wait()
            
            resp = requests.post(url, json={'query': query, 'variables': {'idMal': mal_id}}, timeout=10)
            
            if resp.status_code == 429:
                msg = f"AniList Rate Limit (429). Retrying..."
                if status_callback: status_callback(f"[yellow]{msg}[/yellow]")
                time.sleep(get_config().anilist.rate_limit_delay * (attempt + 2))
                continue
                
            if resp.status_code == 404:
                # Not found on AniList, just return what we have
                return current_meta

            resp.raise_for_status()
            data = resp.json()
            media = data.get("data", {}).get("Media")
            
            if not media:
                return current_meta

            # Merge Data
            # 1. Tags (Append new ones, filter spoilers/low rank if desired, but for now just names)
            new_tags = [t["name"] for t in media.get("tags", []) if not t.get("isMediaSpoiler")]
            # Union with existing tags
            combined_tags = list(set(current_meta.tags + new_tags))
            
            # 2. Images
            cover = media.get("coverImage", {}).get("extraLarge") or media.get("coverImage", {}).get("large")
            
            # 3. Update Metadata
            current_meta.anilist_id = media.get("id")
            current_meta.tags = combined_tags
            current_meta.cover_image = cover
            current_meta.banner_image = media.get("bannerImage")
            current_meta.average_score = media.get("averageScore")
            current_meta.popularity = media.get("popularity")
            current_meta.is_adult = media.get("isAdult", False)
            
            logger.info(f"Enriched '{current_meta.title}' via AniList (ID: {media.get('id')})")
            if status_callback:
                status_callback("Enriched via AniList.")
            
            return current_meta
            
        except Exception as e:
            logger.warning(f"AniList enrichment failed for MAL ID {mal_id}: {e}")
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
            return current_meta # Fail gracefully, return original
            
    return current_meta


def fetch_from_anilist_search(query: str, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Searches AniList for a manga series by name.
    Returns the best match metadata or None.
    """
    gql = """
    query ($search: String) {
      Page(page: 1, perPage: 5) {
        media(search: $search, type: MANGA, sort: SEARCH_MATCH) {
          id
          idMal
          title {
            romaji
            english
            native
          }
          status
          description
          genres
          tags { name rank isMediaSpoiler }
          coverImage { large extraLarge }
          bannerImage
          averageScore
          popularity
          isAdult
          volumes
          chapters
          startDate { year }
        }
      }
    }
    """
    
    url = get_config().anilist.base_url
    
    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            if status_callback:
                status_callback(f"Searching AniList for '{query}'...")
            
            anilist_limiter.wait()
            
            clean_query = sanitize_search_query(query)
            resp = requests.post(url, json={'query': gql, 'variables': {'search': clean_query}}, timeout=10)
            
            if resp.status_code == 429:
                time.sleep(get_config().anilist.rate_limit_delay * (attempt + 2))
                continue
                
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("Page", {}).get("media", [])
            
            if not results:
                return None

            # Score results
            norm_query = semantic_normalize(query)
            best_score = 0.0
            best_media = None
            
            for media in results:
                # Check all titles
                titles = [
                    media["title"].get("romaji"),
                    media["title"].get("english"),
                    media["title"].get("native")
                ]
                titles = [t for t in titles if t]
                
                local_max = 0.0
                for t in titles:
                    score_norm = calculate_similarity(norm_query, semantic_normalize(t))
                    score_raw = calculate_similarity(query.lower(), t.lower())
                    local_max = max(local_max, score_norm, score_raw)
                
                if local_max > best_score:
                    best_score = local_max
                    best_media = media
            
            if best_media and best_score > 0.4: # Reasonable threshold
                logger.info(f"AniList Search Match: '{best_media['title']['romaji']}' ({best_score:.2f})")
                return _parse_anilist_media(best_media)
                
            return None
            
        except Exception as e:
            logger.warning(f"AniList search failed for '{query}': {e}")
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
            return None
    return None


def scan_relations_for_better_match(mal_id: int, original_query: str, status_callback: Optional[callable] = None) -> Optional[SeriesMetadata]:
    """
    Checks the relations of a given MAL ID to see if a spin-off/sequel 
    matches the original query better than the current ID.
    """
    if not mal_id:
        return None
        
    gql = """
    query ($idMal: Int) {
      Media (idMal: $idMal, type: MANGA) {
        title { romaji english }
        relations {
          edges {
            relationType
            node {
              id
              idMal
              type
              format
              title { romaji english native }
              status
              tags { name }
              coverImage { large extraLarge }
              bannerImage
              averageScore
              popularity
              isAdult
            }
          }
        }
      }
    }
    """
    
    url = get_config().anilist.base_url
    
    try:
        anilist_limiter.wait()
        resp = requests.post(url, json={'query': gql, 'variables': {'idMal': mal_id}}, timeout=10)
        
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        media = data.get("data", {}).get("Media")
        if not media or not media.get("relations"):
            return None
            
        # Calculate score of the CURRENT match (Parent)
        parent_titles = [media["title"]["romaji"], media["title"]["english"]]
        parent_titles = [t for t in parent_titles if t]
        
        norm_query = semantic_normalize(original_query)
        parent_score = 0.0
        for t in parent_titles:
            parent_score = max(parent_score, calculate_similarity(norm_query, semantic_normalize(t)))
            
        logger.debug(f"Relation Scan: Parent '{parent_titles[0]}' score: {parent_score:.2f}")

        best_relation = None
        best_rel_score = parent_score
        
        # Scan children
        for edge in media["relations"]["edges"]:
            node = edge["node"]
            if node["type"] != "MANGA" or not node["idMal"]:
                continue
                
            titles = [node["title"]["romaji"], node["title"]["english"], node["title"]["native"]]
            titles = [t for t in titles if t]
            
            node_max = 0.0
            for t in titles:
                 node_max = max(node_max, calculate_similarity(norm_query, semantic_normalize(t)))
            
            # If this relation is a significantly better match
            if node_max > best_rel_score + 0.05: # 5% improvement threshold to switch
                best_rel_score = node_max
                best_relation = node
                logger.info(f"Found better relation match: '{titles[0]}' ({node_max:.2f}) > Parent ({parent_score:.2f})")

        if best_relation:
            if status_callback:
                status_callback(f"Switched to better relation: {best_relation['title']['romaji']}")
            return _parse_anilist_media(best_relation)

    except Exception as e:
        logger.warning(f"Relation scan failed: {e}")
        
    return None

def _parse_anilist_media(media: Dict[str, Any]) -> SeriesMetadata:
    """Helper to convert AniList JSON to SeriesMetadata"""
    title_romaji = media["title"].get("romaji", "Unknown")
    title_english = media["title"].get("english")
    title_native = media["title"].get("native")
    
    # Prefer English if available and not absurdly long, else Romaji
    main_title = title_english if title_english else title_romaji
    
    tags = [t["name"] for t in media.get("tags", []) if not t.get("isMediaSpoiler")]
    
    # Status map
    status_map = {
        "FINISHED": "Completed",
        "RELEASING": "Ongoing",
        "HIATUS": "Hiatus",
        "CANCELLED": "Cancelled",
        "NOT_YET_RELEASED": "Upcoming"
    }
    
    return SeriesMetadata(
        title=main_title,
        title_english=title_english,
        title_japanese=title_native,
        synonyms=media.get("synonyms", []), # AniList search result might lack this in simple query
        authors=[], # Authors are nested in staff connections, complex to fetch in simple query
        synopsis=media.get("description", "").replace("<br>", "\n"),
        genres=media.get("genres", []),
        tags=tags,
        status=status_map.get(media.get("status"), "Unknown"),
        total_volumes=media.get("volumes"),
        total_chapters=media.get("chapters"),
        release_year=media.get("startDate", {}).get("year"),
        mal_id=media.get("idMal"),
        anilist_id=media.get("id"),
        cover_image=media.get("coverImage", {}).get("extraLarge") or media.get("coverImage", {}).get("large"),
        banner_image=media.get("bannerImage"),
        average_score=media.get("averageScore"),
        popularity=media.get("popularity"),
        is_adult=media.get("isAdult", False)
    )

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
    Main entry point for series metadata acquisition.
    1. Checks local series.json (returns if not force_update).
    2. Tries Jikan API.
    3. Verifies/Enriches with AI (Supervisor), using local data as context.
    4. Fallback to AI (Fetcher) if rejected/not found, using local data as context.
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
    
    # AniList Fallback & Refinement
    if meta:
        # Check if a spin-off is a better match
        better_match = scan_relations_for_better_match(meta.mal_id, series_name, status_callback)
        if better_match:
            meta = better_match
            source = "Jikan -> AniList Relation"
    else:
        # Jikan failed, try AniList Search
        meta = fetch_from_anilist_search(series_name, status_callback)
        if meta:
            source = "AniList Search"
            # Check relations for AniList result too
            better_match = scan_relations_for_better_match(meta.mal_id, series_name, status_callback)
            if better_match:
                meta = better_match
                source = "AniList Search -> Relation"

    if meta:
        logger.info(f"Found match: '{meta.title}' via {source}")
        
        # --- AUTO-TRUST PROTOCOL ---
        # If the query and the result are a semantic match, we skip the expensive AI Supervisor.
        # Now that we have AniList for tags/images, AI enrichment is less critical for known series.
        
        norm_query = semantic_normalize(series_name)
        norm_result = semantic_normalize(meta.title)
        
        logger.debug(f"Auto-Trust Check: Query='{series_name}' ({norm_query}) vs Result='{meta.title}' ({norm_result})")
        
        # Check synonyms AND alternate titles for auto-trust
        is_synonym_match = False
        if norm_query != norm_result:
            candidates = set(meta.synonyms)
            if meta.title_english: candidates.add(meta.title_english)
            if meta.title_japanese: candidates.add(meta.title_japanese)
            
            for cand in candidates:
                norm_cand = semantic_normalize(cand)
                if norm_cand == norm_query:
                    logger.debug(f"Auto-Trust Alternate Match: '{cand}' ({norm_cand})")
                    is_synonym_match = True
                    break
        
        # TRUST IF: Explicitly trusted via flag OR Perfect Name Match OR Synonym Match
        if trust_jikan or norm_query == norm_result or is_synonym_match:
            trust_reason = "Flag" if trust_jikan else "Name Match" if norm_query == norm_result else "Synonym Match"
            logger.info(f"Auto-Trusting match for '{series_name}' ({trust_reason}) - Skipping AI.")
            
            if status_callback:
                status_callback(f"Match confirmed ({trust_reason}).")
            
            # Enrich with AniList before saving (Critical since we skipped AI)
            if meta.mal_id:
                meta = fetch_from_anilist_by_mal_id(meta.mal_id, meta, status_callback)

            save_local_metadata(series_path, meta)
            return meta, f"{source} (Auto-Trusted)"

        # Verify and Enrich with AI (Only for ambiguous matches)
        # If verify fails, it returns None, triggering the fallback below
        enriched = enrich_with_ai(series_name, meta, existing_meta=local, status_callback=status_callback)
        if enriched:
            meta = enriched
            source = "AI Supervisor"
            
            # Enrich with AniList after AI verification (if MAL ID persisted)
            if meta.mal_id:
                meta = fetch_from_anilist_by_mal_id(meta.mal_id, meta, status_callback)
                source += " + AniList"
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