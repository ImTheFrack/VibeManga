# VibeManga - Project Context

## Overview
VibeManga is a Python-based CLI tool designed to manage, analyze, and organize a large, locally stored manga library. It handles thousands of series and terabytes of data efficiently using parallel processing and metadata-driven organization.

## Tech Stack
- **Language**: Python 3.x
- **CLI Framework**: `click`
- **UI/Visuals**: `rich` (Tables, Trees, Progress Bars)
- **Concurrency**: `concurrent.futures` (ThreadPoolExecutor) for I/O-bound scanning and matching.
- **Config**: `python-dotenv`

## Architecture

### Metadata Source-of-Truth Refactor

VibeManga’s architecture revolves around a four-phase overhaul that elevated metadata above folder names:

1. **Phase 1 – Models & Indexer**
    * `Series.metadata` is now a strongly typed `SeriesMetadata` object populated during scans.
    * `Series.identities` exposes folder name, English & Japanese titles, and synonyms to the rest of the system.
    * `LibraryIndex` builds `mal_id_map` and `title_map` structures so lookups can resolve by MAL ID or normalized synonyms instantly.

2. **Phase 2 – Hydration Pipeline**
    * `scanner.py` rehydrates metadata from `series.json` and the `hydrate` command fills gaps by invoking Jikan + AI fallback.
    * Every series gains a persistent MAL ID, making downstream operations deterministic.

3. **Phase 3 – Matcher Integration**
    * `matcher.py` consumes the `LibraryIndex`, attempting exact MAL ID matches first, then synonym hits, and finally fuzzy scoring across every identity string.
    * This approach matches torrents like “Shingeki no Kyojin” to “Attack on Titan” even if the filesystem disagrees.

4. **Phase 4 – Rename & Standardization**
    * `rename` (and future `organize`) use hydrated metadata to rename folders/files to canonical titles, preventing regressions back to path-based identity.
    * Supports preview (`--simulate`), multilingual preferences, and collision-safe renames.

### Subsystems

**1. Data Models (`models.py`)**
* `Library`, `Category`, `Series`, and `Volume` dataclasses with JSON serialization.
* `Series.metadata` (Source of Truth) and `Series.identities` feed the indexer and matcher.

**2. Scanner (`scanner.py`)**
* Depth-aware traversal (`Root → Main → Sub → Series`).
* Incremental scanning keyed off `mtime`/`size`.
* Metadata hydration hook that reads/writes `series.json` per folder.

**3. Analysis (`analysis.py`)**
* Semantic normalization utilities used by the matcher, deduper, and indexer.
* Volume/Chapter classification and structural duplicate detection.

**4. Indexer (`indexer.py`)**
* `LibraryIndex.build` populates MAL ID and synonym maps from the scanner output.
* `search()` performs normalized lookups for titles and synonyms.

**5. Matcher (`matcher.py`)**
* Normalizes torrent filenames, extracts MAL IDs when present, and resolves to Series objects via the indexer.
* Falls back to broadened fuzzy comparisons only when deterministic steps fail.

**6. Renamer (`renamer.py`)**
* Generates rename plans to align filesystem names with metadata titles.
* Handles `.zip/.rar` → `.cbz/.cbr` normalization and standard volume numbering.

**7. Grabber/qBit Integration (`grabber.py`)**
* Compares scrape results to library state, highlights missing content, and submits torrents to qBittorrent via API.

## Key Conventions

### Regex & Parsing
The project uses complex regex patterns to handle the wide variety of manga naming conventions.
1.  **Verbose Mode**: All complex regexes MUST use `re.VERBOSE` to allow for comments and readability.
2.  **Hex Escaping**: The `#` character is a comment starter in verbose mode. To match a literal hash (e.g., `#1`), you **MUST** use `\x23`.
3.  **Noise Stripping**: We strictly strip years `(2021)`, version tags `[v2]`, and season markers `Season 1` *before* parsing numbers.

### Directory Structure
The logic *heavily* relies on the folder structure being `Category/SubCategory/Series/`. Deviations from this depth may result in data being missed or miscategorized.

## Current Commands
*   `stats`: Scans the library and shows high-level metrics.
*   `tree`: Visualizes the folder hierarchy.
*   `show`: Searches for a specific series and shows detailed stats, gaps, and external updates.
*   `dedupe`: Scans for duplicate files and structural duplicates.
*   `scrape`: Scrapes Nyaa.si for latest releases.
*   `match`: Parsers scraped data and matches against the library using the Indexer.
*   `grab`: Interactively select and add torrents to qBittorrent.
*   `hydrate`: Fetches metadata (MAL ID, Titles) for series missing it.
*   `rename`: Standardizes folder/file names based on metadata.

## Roadmap
See `TODO.md` for active tasks. Next steps involve "Deep Content Analysis" (archive inspection for page counts/corruption).
