import os
import re

"""
Constants used throughout the VibeManga application.
"""

# File Extensions
VALID_MANGA_EXTENSIONS = {'.cbz', '.cbr', '.zip', '.rar', '.pdf', '.epub'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.avif'}

# Analysis & Metadata
VALID_DEMOGRAPHICS = {'Shounen', 'Seinen', 'Shoujo', 'Josei', 'Shonen'}
CLEAN_WORD_RE = re.compile(r'[^a-z]')

# Common English stop words for synopsis analysis
STOP_WORDS = {
    # Articles & Conjunctions
    'the', 'and', 'to', 'of', 'in', 'is', 'it', 'with', 'for', 'that', 'as', 'on', 'was', 'at', 'by',
    'an', 'be', 'this', 'which', 'from', 'but', 'not', 'or', 'nor', 'yet', 'so', 'if', 'than', 'then',
    'although', 'because', 'since', 'unless', 'until', 'while', 'whether', 'though',
    # Pronouns
    'his', 'her', 'their', 'they', 'she', 'he', 'him', 'them', 'its', 'their', 'theirs', 'himself',
    'herself', 'themselves', 'itself', 'myself', 'yourself', 'ourselves', 'yourselves', 'mine', 'yours',
    'ours', 'who', 'whom', 'whose', 'which', 'what', 'whatever', 'whichever', 'whoever', 'whomever',
    'this', 'that', 'these', 'those', 'each', 'every', 'any', 'all', 'both', 'few', 'many', 'most',
    'other', 'another', 'some', 'such', 'neither', 'either', 'someone', 'anyone', 'everyone', 'nobody',
    'no', 'yes', 'own', 'me', 'us', 'you', 'my', 'our', 'your', 'hes', 'hers',
    # Prepositions & Adverbs
    'about', 'above', 'across', 'after', 'against', 'along', 'amid', 'among', 'around', 'at', 'before',
    'behind', 'below', 'beneath', 'beside', 'besides', 'between', 'beyond', 'by', 'down', 'during',
    'except', 'from', 'inside', 'into', 'like', 'near', 'off', 'onto', 'out', 'outside', 'over', 'past',
    'since', 'through', 'throughout', 'till', 'toward', 'towards', 'under', 'underneath', 'until', 'up',
    'upon', 'within', 'without', 'very', 'now', 'there', 'where', 'when', 'how', 'always', 'never',
    'often', 'sometimes', 'usually', 'already', 'still', 'just', 'even', 'also', 'only', 'well',
    'almost', 'enough', 'quite', 'rather', 'too', 'fairly', 'nearly', 'again', 'further', 'once',
    'here', 'why', 'somewhere', 'anywhere', 'everywhere', 'nowhere'
    # Verbs (Auxiliary/Common)
    'am', 'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did',
    'doing', 'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might', 'must', 'get', 'got',
    'go', 'goes', 'went', 'gone', 'come', 'comes', 'came', 'become', 'becomes', 'became', 'find',
    'finds', 'found', 'take', 'takes', 'took', 'taken', 'make', 'makes', 'made', 'see', 'sees', 'saw',
    'seen', 'know', 'knows', 'knew', 'known', 'think', 'thinks', 'thought', 'want', 'wants', 'wanted',
    'look', 'looks', 'looked', 'use', 'uses', 'used', 'give', 'gives', 'gave', 'given', 'keep', 'keeps',
    # Numbers & Ordinals
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
    'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
    'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety', 'hundred', 'thousand', 'million',
    'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
    # Meta/Manga Specific Noise
    'source', 'mal', 'written', 'rewrite', 'synopsis', 'background', 'manga', 'series', 'chapter',
    'volume', 'publication', 'publishing', 'published', 'author', 'artist', 'illustration', 'illustrated',
    'serialized', 'magazine', 'adapted', 'adaptation', 'anime', 'tv', 'movie', 'film', 'theatrical',
    'version', 'complete', 'edition', 'special', 'additional', 'includes', 'including', 'containing',
    'however', 'story', 'world', 'life', 'years', 'man', 'time', 'day', 'new', 'way', 'back', 'around',
    # Custom
    'more','despite','begins','shes','hes', 'usa','ever,','soon','away','named','begins','begin',
    'kodansha','girls','girl','boys','boy', 'womens','women','women','called','men','man','mens',
    'suddenly','long','short','meets','meet','decides','next','finally','final','eventually',
    'something','everything','everything','anything','nothing'
}

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
# Remote (Default settings for the provider)
REMOTE_AI_BASE_URL = os.getenv("REMOTE_AI_BASE_URL", "https://openrouter.ai/api/v1")
REMOTE_AI_API_KEY = os.getenv("REMOTE_AI_API_KEY", "")
REMOTE_AI_MODEL = os.getenv("REMOTE_AI_MODEL", "google/gemini-flash-1.5")

# Local (Default settings for the provider)
LOCAL_AI_BASE_URL = os.getenv("LOCAL_AI_BASE_URL", "http://localhost:11434/v1")
LOCAL_AI_API_KEY = os.getenv("LOCAL_AI_API_KEY", "ollama")
LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "llama3")

# Global Settings
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))

# AI Role Configuration
# This is the central place to edit AI behavior, providers, and models.
ROLE_CONFIG = {
    "METADATA": {
        "provider": "remote",
        "model": "google/gemini-flash-1.5",
        "role_prompt": (
            "You are a metadata extraction specialist. "
            "Your goal is to provide accurate details for a given manga series. "
            "Output: Return ONLY a JSON object matching the schema:\n"
            "{\n"
            "    \"title\": \"str\",\n"
            "    \"authors\": [\"str\"],\n"
            "    \"synopsis\": \"str\",\n"
            "    \"genres\": [\"str\"],\n"
            "    \"tags\": [\"str\"],\n"
            "    \"demographics\": [\"str\"],\n"
            "    \"status\": \"Completed\" | \"Ongoing\" | \"Hiatus\" | \"Cancelled\",\n"
            "    \"total_volumes\": int | null,\n"
            "    \"total_chapters\": int | null,\n"
            "    \"release_year\": int | null,\n"
            "    \"mal_id\": int | null,\n"
            "    \"anilist_id\": int | null\n"
            "}"
        )
    },
    "SUPERVISOR": {
        "provider": "remote",
        "model": "google/gemini-flash-1.5",
        "role_prompt": (
            "You are a Metadata Quality Supervisor. "
            "Inputs: 'User Query' (folder name) and 'API Metadata' (from Jikan/MAL).\n"
            "Tasks:\n"
            "1. VERIFY: Does the API Metadata match the User Query? Be extremely strict with spinoffs, fanbooks, and subtitles. "
            "If the User Query contains a specific subtitle (e.g., 'Corps Records', 'Gaiden', 'Side Story') that is NOT present in the API Metadata titles, you MUST set is_match=false.\n"
            "2. ENRICH: If is_match=true, fill in missing (null) fields using your own knowledge. "
            "If is_match=false, provide the CORRECT metadata for the User Query in the 'metadata' field, including the correct MAL ID and titles if you know them.\n"
            "Output: Return ONLY a JSON object:\n"
            "{\n"
            "    \"is_match\": true/false,\n"
            "    \"reason\": \"explanation\",\n"
            "    \"metadata\": { ... same schema as METADATA ... }\n"
            "}"
        )
    },
    "MODERATOR": {
        "provider": "local",
        "model": LOCAL_AI_MODEL,
        "role_prompt": (
            "You are a strict content safety moderator for a US-based manga library. Violence, perversion, etc. does not make something ADULT, even if it's for teens or adults. ONLY explicit sexual content qualifies as ADULT. Illegal content MUST be flagged as ILLEGAL. "
            "Classify content as: \n"
            "1. SAFE: Standard manga (includes gore/ecchi).\n"
            "2. ADULT: Explicit Hentai/Pornography.\n"
            "3. ILLEGAL: CP/CSAM/Hate Speech.\n"
            "Output: Return ONLY a JSON object: {\"classification\": \"SAFE|ADULT|ILLEGAL\", \"reason\": \"str\"}."
        )
    },
    "PRACTICAL": {
        "provider": "local",
        "model": LOCAL_AI_MODEL,
        "role_prompt": (
            "You are a Pragmatic Librarian. Suggest the best category based on Genre/Demographics. "
            "Prioritize structural fit. Do not invent categories. "
            "Output: Return ONLY a JSON object: {\"category\": \"Main/Sub\", \"reason\": \"str\"}."
        )
    },
    "CREATIVE": {
        "provider": "remote",
        "model": "openrouter.google/gemini-3-flash-preview",
        "role_prompt": (
            "You are a Creative Literary Analyst. Suggest the best category based on Synopsis/Vibe/Themes. "
            "Look beyond technical tags for the 'soul' of the series. "
            "Output: Return ONLY a JSON object: {\"category\": \"Main/Sub\", \"reason\": \"str\"}."
        )
    },
    "CONSENSUS": {
        "provider": "remote",
        "model": "openrouter.google/gemini-3-flash-preview",
        "role_prompt": (
            "You are the Head Librarian. Reach a final decision based on metadata and agent views. "
            "GUIDELINES:\n"
            "1. **Adult/Ecchi Evaluation:** Strongly scrutinize series with 'Ecchi', 'Smut', or 'Mature' tags, or an 'ADULT' moderator flag.\n"
            "   - If the content's primary focus is sexual, nudity, or heavy fanservice, assign it to an 'Adult', 'Hentai', or 'Ecchi & Mature' category.\n"
            "   - Distinguish this from 'casual fanservice' in standard manga or 'Mature' storytelling (violence/dark themes). If it fits a standard demographic (Shounen/Seinen) despite minor fanservice, prefer the standard category.\n"
            "2. **Balance:** Weigh the Practical (Structure) and Creative (Vibe) suggestions to find the best fit.\n"
            "3. **Structure:** You MUST prioritize the 'Official Category List' provided in the input. Only suggest a NEW category if absolutely necessary.\n"
            "Output: Return ONLY a JSON object: {\"final_category\": \"Main\", \"final_sub_category\": \"Sub\", \"confidence_score\": 0.0-1.0, \"reason\": \"str\"}."
        )
    }
}
