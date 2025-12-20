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
