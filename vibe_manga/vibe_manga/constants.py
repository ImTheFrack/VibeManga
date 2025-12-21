import os

"""
Constants used throughout the VibeManga application.
"""

# File Extensions
VALID_MANGA_EXTENSIONS = {'.cbz', '.cbr', '.zip', '.rar', '.pdf', '.epub'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.avif'}

# Analysis Thresholds
SIMILARITY_THRESHOLD = 0.95  # Threshold for fuzzy matching duplicate detection
FUZZY_MATCH_THRESHOLD = 95  # Threshold for matching scraped names to library series (0-100)
MAX_RANGE_SIZE = 200  # Maximum allowed range size to avoid parsing year ranges like 1-2021
YEAR_RANGE_MIN = 1900  # Minimum year value to filter out from number extraction
YEAR_RANGE_MAX = 2150  # Maximum year value to filter out from number extraction
MIN_VOL_SIZE_MB = 35
MIN_CHAP_SIZE_MB = 3

# Cache Configuration
DEFAULT_CACHE_MAX_AGE_SECONDS = 3000  # 3000 seconds (50 minutes)
CACHE_FILENAME = ".vibe_manga_cache.pkl"
LIBRARY_STATE_FILENAME = "vibe_manga_library.json"

# Display Configuration
DEFAULT_TREE_DEPTH = 2
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024

# Progress Display
PROGRESS_REFRESH_RATE = 10  # Refresh per second for progress bars
DEEP_ANALYSIS_REFRESH_RATE = 5  # Refresh per second for deep analysis

# Scraper Configuration
NYAA_BASE_URL = "https://nyaa.si"
NYAA_ENGLISH_TRANSLATED_URL_TEMPLATE = f"{NYAA_BASE_URL}/?f=0&c=3_1&q=&p={{page}}"
SCRAPER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
SCRAPER_RATE_LIMIT_PER_SECOND = 3
NYAA_DEFAULT_OUTPUT_FILENAME = "nyaa_scrape_results.json"
SCRAPER_RETRY_COUNT = 3
SCRAPER_RETRY_BACKOFF_FACTOR = 0.5
SCRAPER_TIMEOUT_SECONDS = 15

# qBittorrent API Configuration
QBIT_DEFAULT_TAG = "VibeManga"
QBIT_DEFAULT_CATEGORY = "VibeManga"
QBIT_DEFAULT_SAVEPATH = "VibeManga"
QBIT_DOWNLOAD_ROOT = os.getenv("QBIT_DOWNLOAD_ROOT", "")
PULL_TEMPDIR = os.getenv("PULL_TEMPDIR", "")

# Nyaa.si Scraper Internals
NYAA_DEFAULT_PAGES_TO_SCRAPE = 60
NYAA_TORRENT_TABLE_SELECTOR = "div.table-responsive table.torrent-list tbody tr"
NYAA_MIN_COLUMNS = 8
NYAA_COL_IDX_NAME = 1
NYAA_COL_IDX_LINKS = 2
NYAA_COL_IDX_SIZE = 3
NYAA_COL_IDX_DATE = 4
NYAA_COL_IDX_SEEDERS = 5
NYAA_COL_IDX_LEECHERS = 6
NYAA_COL_IDX_COMPLETED = 7

# AI Configuration
# Remote
REMOTE_AI_BASE_URL = os.getenv("REMOTE_AI_BASE_URL", "https://openrouter.ai/api/v1")
REMOTE_AI_API_KEY = os.getenv("REMOTE_AI_API_KEY", "")
REMOTE_AI_MODEL = os.getenv("REMOTE_AI_MODEL", "anthropic/claude-3-haiku")

# Local
LOCAL_AI_BASE_URL = os.getenv("LOCAL_AI_BASE_URL", "http://localhost:11434/v1")
LOCAL_AI_API_KEY = os.getenv("LOCAL_AI_API_KEY", "ollama")
LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "llama3")

# Global
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))

# Role-Specific Model Overrides (Optional .env configuration)
METADATA_MODEL = os.getenv("METADATA_MODEL", REMOTE_AI_MODEL)
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", REMOTE_AI_MODEL)
MODERATOR_MODEL = os.getenv("MODERATOR_MODEL", LOCAL_AI_MODEL)
PRACTICAL_MODEL = os.getenv("PRACTICAL_MODEL", LOCAL_AI_MODEL)
CREATIVE_MODEL = os.getenv("CREATIVE_MODEL", REMOTE_AI_MODEL)
CONSENSUS_MODEL = os.getenv("CONSENSUS_MODEL", REMOTE_AI_MODEL)

# AI Roles (System Prompts)

ROLE_METADATA_FETCHER = """You are a metadata extraction specialist.
Your goal is to provide accurate details for a given manga series.
Output: Return ONLY a JSON object matching the schema:
{
    "title": "str",
    "authors": ["str"],
    "synopsis": "str",
    "genres": ["str"],
    "tags": ["str"],
    "demographics": ["str"],
    "status": "Completed" | "Ongoing" | "Hiatus" | "Cancelled",
    "total_volumes": int | null,
    "total_chapters": int | null,
    "release_year": int | null,
    "mal_id": int | null,
    "anilist_id": int | null
}"""

ROLE_METADATA_SUPERVISOR = """You are a Metadata Quality Supervisor.
Inputs: 'User Query' (folder name) and 'API Metadata' (from Jikan/MAL).
Tasks:
1. VERIFY: Does the API Metadata match the User Query?
   - Allow fuzzy matches (e.g. "Ranma 1 2" == "Ranma ½").
   - Reject mismatches (e.g. "Naruto" != "Boruto").
2. ENRICH: If it is a match, fill in any missing (null) fields in the metadata using your own knowledge.
   - Do NOT overwrite existing non-null data unless it is clearly wrong.
   - Specifically preserve or correct IDs like mal_id and anilist_id.
Output: Return ONLY a JSON object:
{
    "is_match": true/false,
    "reason": "explanation",
    "metadata": {
        "title": "str",
        "authors": ["str"],
        "synopsis": "str",
        "genres": ["str"],
        "tags": ["str"],
        "demographics": ["str"],
        "status": "Completed" | "Ongoing" | "Hiatus" | "Cancelled",
        "total_volumes": int | null,
        "total_chapters": int | null,
        "release_year": int | null,
        "mal_id": int | null,
        "anilist_id": int | null
    }
}"""

ROLE_MODERATOR = """You are a strict content safety moderator for a US-based manga library.
Your task is to classify content based on the following rules:
1. SAFE: Standard manga (Shonen, Seinen, Shojo, Josei). Includes violence, gore, dark themes, and "Ecchi" (suggestive but not explicit).
2. ADULT: Explicit sexual content (Hentai, Pornography). This MUST be separated from regular mature content.
3. ILLEGAL: Child Pornography (CP), Lolicon/Shotacon (in sexual contexts), or Hate Speech.
Output: Return ONLY a JSON object with keys "classification" (SAFE, ADULT, ILLEGAL) and "reason"."""

ROLE_CATEGORIZER_PRACTICAL = """You are a Pragmatic Librarian.
Your task is to select the single best category for a manga based purely on its official Genre tags, Demographics, and the available folder list.
- Prioritize structural fit: If a "Shonen" folder exists and the manga is "Shonen", suggest it.
- Be rigid: Do not invent new categories unless absolutely necessary.
- Context: You will receive the Series Metadata and the list of Current Categories.
Output: Return ONLY a JSON object: {"category": "Main/Sub", "reason": "brief explanation"}."""

ROLE_CATEGORIZER_CREATIVE = """You are a Creative Literary Analyst.
Your task is to select the single best category for a manga based on its Synopsis, Themes, and Vibe.
- Look beyond the tags: If a manga is technically "Shonen" but feels like a dark "Psychological Thriller", suggest the latter if available.
- Context: You will receive the Series Metadata and the list of Current Categories.
Output: Return ONLY a JSON object: {"category": "Main/Sub", "reason": "brief explanation"}."""

ROLE_CONSENSUS = """You are the Head Librarian.
Your task is to make the final binding decision on where a manga series belongs.
1. Review the input from the 'Pragmatic Librarian' (Structure-focused) and 'Creative Analyst' (Theme-focused).
2. Review the Safety Moderator's flag. IF marked 'ADULT', you MUST place it in an 'Adult' or 'Hentai' category, ignoring other suggestions.
3. Select the best matching category from the provided 'Official Category List'.
4. If neither suggestion fits well, you may propose a new sub-category, but prefer existing ones.
Output: Return ONLY a JSON object: {"final_category": "Main", "final_sub_category": "Sub", "confidence_score": 0.0-1.0, "reason": "final verdict"}."""

# Role Configuration Defaults
# Maps roles to their preferred provider ('remote' or 'local') and model.
# This can be overridden per call, but serves as the system default.
ROLE_CONFIG = {
    "METADATA": {
        "provider": "remote", # Remote needed for accurate knowledge retrieval
        "model": METADATA_MODEL,
        "role_prompt": ROLE_METADATA_FETCHER
    },
    "SUPERVISOR": {
        "provider": "remote", # Needs high logic to verify matches
        "model": SUPERVISOR_MODEL,
        "role_prompt": ROLE_METADATA_SUPERVISOR
    },
    "MODERATOR": {
        "provider": "local",  # Local preferred for privacy/speed
        "model": MODERATOR_MODEL,
        "role_prompt": ROLE_MODERATOR
    },
    "PRACTICAL": {
        "provider": "local", # Logic-based, local is fine
        "model": PRACTICAL_MODEL,
        "role_prompt": ROLE_CATEGORIZER_PRACTICAL
    },
    "CREATIVE": {
        "provider": "remote", # Nuance required
        "model": CREATIVE_MODEL,
        "role_prompt": ROLE_CATEGORIZER_CREATIVE
    },
    "CONSENSUS": {
        "provider": "remote", # High reasoning required
        "model": CONSENSUS_MODEL,
        "role_prompt": ROLE_CONSENSUS
    }
}