# VibeManga - Project Context

## Overview

VibeManga is a Python-based CLI tool designed to manage, analyze, and organize a large, locally stored manga library. It handles thousands of series and terabytes of data efficiently using parallel processing, metadata-driven organization, and AI-powered automation.

## Tech Stack

- **Language**: Python 3.8+
- **CLI Framework**: `click` - Command-line interface with nested commands
- **UI/Visuals**: `rich` - Tables, Trees, Progress Bars, Panels, Syntax Highlighting
- **Configuration**: `pydantic-settings` - Type-safe, validated configuration management
- **Data Validation**: `pydantic` >= 2.0.0 - Runtime type checking and serialization
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` for I/O-bound operations
- **Archive Handling**: `zipfile`, `rarfile` for CBZ/CBR processing
- **AI Integration**: OpenAI-compatible APIs with dual provider support
- **HTTP**: `requests` with retry logic and rate limiting
- **HTML Parsing**: `beautifulsoup4` with `lxml` backend

## Architecture

### Configuration-First Design

VibeManga uses a centralized configuration system (`config.manager.py`) built on Pydantic Settings:

```python
# Configuration hierarchy (highest to lowest priority):
# 1. Environment variables (e.g., AI__MODEL, QBIT__URL)
# 2. .env file (supports nested: AI__BASE_URL="http://localhost:11434")
# 3. Default values in config classes
```

**Key Config Classes:**
- `AIConfig`: Provider, model, base_url, api_key, timeout, max_retries
- `QBitConfig`: qBittorrent Web UI URL, credentials, tags, categories
- `JikanConfig`: MyAnimeList API base_url, rate_limit_delay, timeout, local_repository_path
- `CacheConfig`: enabled, max_age_seconds, file_name
- `LoggingConfig`: level, file_level, console_level, log_file
- `ProcessingConfig`: thread_pool_size, batch_size, timeout
- `AIRoleConfig`: Dynamic role configuration loaded from JSON
- `VibeMangaConfig`: Root container with nested configs and backward compatibility

### Metadata Source-of-Truth Refactor

VibeManga's architecture guarantees that MyAnimeList metadata—not folder names—defines every series:

1. **Phase 1 – Models & Indexer**
    * `Series.metadata` is a strongly typed `SeriesMetadata` object populated during scans
    * `Series.identities` exposes folder name, English & Japanese titles, and synonyms
    * `LibraryIndex` builds `mal_id_map` and `title_map` for O(1) lookups

2. **Phase 2 – Hydration Pipeline**
    * `scanner.py` rehydrates metadata from `series.json`
    * `hydrate` command fills gaps via Jikan + AI fallback
    * Every series gains a persistent MAL ID for deterministic operations

3. **Phase 3 – Matcher Integration**
    * `matcher.py` consumes `LibraryIndex`, attempting exact MAL ID matches first
    * Falls back to synonym-aware search, then fuzzy scoring across all identities
    * Matches torrents like "Shingeki no Kyojin" to "Attack on Titan" reliably

4. **Phase 4 – Rename & Standardization**
    * `rename` aligns filesystem names with metadata titles
    * `organize` restructures entire library based on filters and AI suggestions
    * Prevents regression to path-based identity

### Subsystems

**1. Configuration (`config/manager.py`)**
* Centralized, type-safe configuration using Pydantic Settings
* Environment variable and .env file support with nested delimiters (`__`)
* Backward compatibility for legacy env vars (e.g., `MANGA_LIBRARY_ROOT`)
* Runtime config reload without restart
* `setup_config()`, `get_config()`, `reload_config()` for management
* Convenience accessors: `get_library_path()`, `get_ai_config()`, etc.

**2. Data Models (`models.py`)**
* `SeriesMetadata`: Source of truth with MAL ID, titles, synonyms, authors, genres, tags, demographics, status, totals
* `Volume`: Individual archive files with size, mtime, page_count, corruption status
* `SubGroup`: Nested directories within series (e.g., "v01-v12", "Side Stories")
* `Series`: Container for volumes/subgroups with identity resolution via `identities()` property
* `Category`/`Library`: Hierarchy levels with aggregation methods for totals
* All models support `to_dict()` and `from_dict()` for JSON serialization

**3. Scanner (`scanner.py`)**
* Depth-aware traversal: `Root → Main Category → Sub Category → Series → SubGroup`
* Incremental scanning keyed off `mtime`/`size` with pickle cache
* Metadata hydration hook reads/writes `series.json` per folder
* Parallel volume processing using ThreadPoolExecutor
* `enrich_series()` for deep analysis (page counts, integrity verification)

**4. Indexer (`indexer.py`)**
* `LibraryIndex.build()` populates MAL ID and synonym maps from scanner output
* `search()` performs normalized lookups for titles and synonyms
* O(1) resolution by MAL ID, O(log n) by title with normalization
* Handles identity expansion: English, Japanese, synonyms, and folder names

**5. Matcher (`matcher.py`)**
* Normalizes torrent filenames and extracts MAL IDs when present
* Resolves to Series objects via Indexer with fallback strategies
* Range parsing: "v01-12" → individual volumes
* Consolidation: Groups related entries and propagates matches
* Parallel matching with progress tracking
* Remote identity resolution for scraped data

**6. Renamer (`renamer.py`)**
* Generates rename plans to align filesystem with metadata titles
* Safety levels: 1=Trivial, 2=Safe/Fuzzy, 3=Aggressive
* Handles `.zip/.rar` → `.cbz/.cbr` normalization
* Interactive mode for selective renaming
* Collision detection and resolution

**7. Organizer (`cli/organize.py`)**
* Complex filtering: tags, genres, sources, negation (multiple values supported)
* Move or Copy modes with collision detection
* AI-suggested target categories
* Multi-threaded transfers with progress bars and transfer speeds
* Queue management for large operations (MAX_QUEUE_SIZE = 3)
* `CopyTask` dataclass for transfer operations

**8. Grabber/qBit Integration (`grabber.py`)**
* Compares scrape results to library state
* Highlights missing volumes/chapters
* Submits torrents to qBittorrent via Web API
* Auto-add based on gap detection
* Token tracking: `ai_api.tracker` monitors usage across models
* Post-processing: `pull` command processes completed downloads

**9. AI API (`ai_api.py`)**
* Dual provider support: Remote (OpenRouter) + Local (Ollama/LocalAI)
* Automatic model detection via `/v1/models` endpoint
* Response cleaning: Removes thinking tags (`<think>`, `<thinking>`, `<reasoning>`)
* JSON extraction: Resilient to markdown blocks and preambles
* Token tracking: Global `tracker` instance across session
* Role-based prompts with configuration in `vibe_manga_ai_config.json`
* Special headers for OpenRouter (HTTP-Referer, X-Title)

**10. Categorizer (`categorizer.py`)**
* AI-powered category suggestions based on synopsis and metadata
* Multiple roles: MODERATOR, PRACTICAL, CREATIVE with different prompts
* Batch processing with progress tracking
* Explanation mode shows AI reasoning
* Pause between decisions for manual review

**11. Metadata (`metadata.py`)**
* Jikan API integration with rate limiting and retries
* AI fallback for ambiguous matches
* CSV repository support for offline metadata
* Parallel processing with configurable thread pools
* `series.json` persistence per folder

**12. Logging (`logging.py`)**
* Structured logging with Rich console integration
* Multiple loggers: console, file, structured
* Verbosity levels: WARNING (default), INFO (-v), DEBUG (-vv)
* Clean log mode for INFO level (reduces noise)
* Step logging for pipeline commands
* API call logging for AI requests

**13. CLI Commands (`cli/`)**
* All commands use `@click.command()` with typed parameters
* Consistent option naming: `--simulate`, `--auto`, `--verbose/-v`
* Progress bars via Rich for long-running operations
* Interactive prompts when needed (Confirm, Prompt)
* Common base functions in `cli/base.py`

## Key Conventions

### Regex & Parsing

The project uses complex regex patterns to handle the wide variety of manga naming conventions:

1. **Verbose Mode**: All complex regexes MUST use `re.VERBOSE` for readability
2. **Hex Escaping**: Use `\x23` for literal `#` in verbose mode (not `#`)
3. **Noise Stripping**: Strip years `(2021)`, version tags `[v2]`, season markers `Season 1` BEFORE parsing numbers
4. **Range Validation**: `MAX_RANGE_SIZE = 200` prevents parsing year ranges like 1-2021
5. **Year Filtering**: `YEAR_RANGE_MIN = 1900`, `YEAR_RANGE_MAX = 2150` filters out years from number extraction

### Directory Structure

The logic *heavily* relies on the folder structure being `Category/SubCategory/Series/`. Deviations may result in data being missed or miscategorized.

Expected structure:
```
Library Root/
├── Main Category/          # e.g., "Manga", "Manhwa", "Light Novels"
│   ├── Sub Category/       # e.g., "Action", "Romance", "Seinen"
│   │   ├── Series/         # Series folder with series.json
│   │   │   ├── series.json
│   │   │   ├── [Series] v01.cbz
│   │   │   └── SubGroup/   # Optional: "v01-v12", "Side Stories"
```

### Configuration Management

- **Never access environment variables directly** - Use `config.manager.get_config()`
- **Nested env vars** use `__` delimiter: `AI__BASE_URL`, `QBIT__USERNAME`
- **Backward compatibility** maintained for legacy vars: `MANGA_LIBRARY_ROOT` → `library_path`
- **Type safety** enforced by Pydantic - invalid values raise validation errors
- **Reloading** supported via `reload_config()` - no restart needed

### AI Integration Patterns

- **Dual providers**: Remote for intelligence, Local for privacy/cost
- **Role separation**: Different prompts for different tasks
- **Token tracking**: Monitor usage via `ai_api.tracker`
- **Response cleaning**: Always clean AI responses before JSON extraction
- **Fallback strategy**: Jikan first, then AI, then local CSV

### Error Handling

- **Graceful degradation**: If AI fails, fall back to Jikan; if Jikan fails, use local CSV
- **User feedback**: Rich console messages for all errors, not just stack traces
- **Logging**: Errors go to both console (if verbose) and file
- **Simulation mode**: `--simulate` flag for all destructive operations

## Current Commands

*   `pullcomplete`: Runs full pipeline (pull → stats → metadata → categorize → replenish)
*   `hydrate`: Fetches metadata (MAL ID, Titles) for series missing it
*   `metadata`: Manual metadata fetch with parallel processing
*   `rename`: Standardizes folder/file names based on metadata
*   `organize`: Moves/copies series based on complex filters
*   `stats`: Scans library and shows high-level metrics
*   `tree`: Visualizes folder hierarchy
*   `show`: Searches for series and shows detailed stats, gaps, and external updates
*   `dedupe`: Scans for duplicate files and structural duplicates
*   `scrape`: Scrapes Nyaa.si for latest releases
*   `match`: Parses scraped data and matches against library using Indexer
*   `grab`: Interactively selects and adds torrents to qBittorrent
*   `pull`: Checks qBittorrent for completed downloads and post-processes
*   `categorize`: AI-powered category suggestions with explanations

## Configuration Files

### `.env` File

Primary configuration via environment variables (see `.env.example`):

```env
# Core
LIBRARY_PATH="/path/to/manga"

# qBittorrent
QBIT__URL="http://localhost:8080"
QBIT__USERNAME="admin"
QBIT__PASSWORD="adminadmin"

# AI - Remote
AI__PROVIDER="remote"
AI__BASE_URL="https://openrouter.ai/api/v1"
AI__API_KEY="sk-or-..."
AI__MODEL="anthropic/claude-3-haiku"
AI__TIMEOUT=300
AI__MAX_RETRIES=3

# AI - Local
AI__PROVIDER="local"
AI__BASE_URL="http://localhost:11434"
AI__API_KEY="ollama"
AI__MODEL="llama3.1"

# Cache
CACHE__ENABLED=true
CACHE__MAX_AGE_SECONDS=3000

# Logging
LOG__LEVEL="INFO"
LOG__CONSOLE_LEVEL="WARNING"
LOG__FILE_LEVEL="INFO"
LOG__LOG_FILE="vibe_manga.log"

# Processing
PROCESSING__THREAD_POOL_SIZE=4
PROCESSING__BATCH_SIZE=100
PROCESSING__TIMEOUT=300
```

### `vibe_manga_ai_config.json`

AI role configurations (optional, falls back to `constants.ROLE_CONFIG`):

```json
{
  "MODERATOR": {
    "system_prompt": "You validate manga metadata matches...",
    "temperature": 0.3,
    "provider": "remote",
    "model": "anthropic/claude-3-haiku"
  },
  "PRACTICAL": {
    "system_prompt": "You suggest practical categories...",
    "temperature": 0.5,
    "provider": "local",
    "model": "llama3.1"
  }
}
```

### Cache Files

*   `.vibe_manga_cache_{hash}.pkl`: Pickle cache for fast loading
*   `vibe_manga_library_{hash}.json`: JSON cache for persistence
*   `vibe_manga_resolution_cache.json`: MAL ID resolution cache
*   `vibe_manga_whitelist.json`: Series whitelist for operations

### Log Files

*   `vibe_manga.log`: Main log file (rotation not implemented, monitor size)
*   Console logging: Controlled by `--verbose` flags

## API Integration

### qBittorrent Web API

Requires Web UI enabled with credentials. API client in `qbit_api.py`:

```python
from vibe_manga.qbit_api import QBitAPI

qbit = QBitAPI()  # Uses config automatically
qbit.add_torrent(magnet_link, save_path, tags=["VibeManga"])
```

### Jikan (MyAnimeList) API

Rate-limited, with retry logic and local CSV fallback:

```python
from vibe_manga.metadata import fetch_from_jikan, fetch_from_local_csv

# Try Jikan first, then fall back to local CSV
meta = fetch_from_jikan(query) or fetch_from_local_csv(mal_id)
```

### AI Providers

OpenAI-compatible API abstraction:

```python
from vibe_manga.ai_api import call_ai, get_available_models

# Call with automatic provider selection
response = call_ai(
    user_prompt="Is 'Attack on Titan' the same as 'Shingeki no Kyojin'?",
    system_role=ROLE_CONFIG["MODERATOR"]["system_prompt"],
    provider="remote",
    json_mode=True
)

# List available models
models = get_available_models("local")  # or "remote"
```

## Performance Considerations

### Threading

*   Scanner: ThreadPoolExecutor for volume processing
*   Matcher: Parallel matching with configurable workers
*   Organizer: Multi-threaded transfers (MAX_QUEUE_SIZE = 3)
*   Metadata: Parallel fetching with `--parallel N`

### Caching

*   Pickle cache: Fast loading, but Python version dependent
*   JSON cache: Slower but portable and human-readable
*   Incremental scans: Only process changed files based on mtime/size
*   Resolution cache: MAL ID lookups cached to avoid re-querying

### Memory Usage

*   Large libraries (1000+ series) can use 2-4GB RAM during scan
*   Use `--no-cache` to force fresh scan and clear memory
*   Pickle cache can be large (hundreds of MB) - monitor disk space

## Common Patterns

### Adding New CLI Commands

1. Create file in `cli/` directory
2. Use `@click.command()` decorator
3. Import and add to `main.cli` group
4. Use `cli/base.py` functions for consistency

Example:
```python
# cli/newcommand.py
import click
from .base import console, get_library_root

@click.command()
@click.option("--simulate", is_flag=True)
def newcommand(simulate: bool):
    """Description of what this command does."""
    root = get_library_root()
    console.print(f"Processing {root}")
```

### Accessing Configuration

```python
# Preferred: Use convenience functions
from vibe_manga.config.manager import get_library_path, get_ai_config

library = get_library_path()
ai = get_ai_config()

# Alternative: Get full config
from vibe_manga.config.manager import get_config

config = get_config()
# Access nested: config.ai.model, config.qbit.url
```

### Logging

```python
from vibe_manga.logging import get_logger

logger = get_logger(__name__)
logger.info("Information message")
logger.debug("Debug details")
logger.warning("Warning: %s", details)
```

### Progress Bars

```python
from rich.progress import Progress
from .base import console

with Progress(console=console) as progress:
    task = progress.add_task("[cyan]Processing...", total=100)
    for i in range(100):
        progress.update(task, advance=1)
```

## Troubleshooting

### Common Issues

1. **"Cannot find library"**: Check `LIBRARY_PATH` env var or `.env` file
2. **qBittorrent connection fails**: Verify Web UI is enabled and credentials match
3. **AI API errors**: Check base_url format, API key, and model availability
4. **Pickle cache errors**: Delete `.vibe_manga_cache_*.pkl` to regenerate
5. **Permission errors**: Ensure read/write access to library and temp directories

### Debug Mode

Run with `-vv` for DEBUG logging:
```bash
python -m vibe_manga.run stats -vv
```

Check `vibe_manga.log` for detailed execution traces.

## Roadmap

See `TODO.md` for active tasks. Current focus areas:

* Enhanced AI categorization with confidence scoring
* Improved duplicate detection with content hashing
* Web UI for remote management
* Plugin system for custom metadata sources
* Export formats (MAL, AniList, custom JSON)
* Automatic quality upgrades (replace low-res with high-res)
