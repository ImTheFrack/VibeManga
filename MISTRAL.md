# VibeManga - Project Documentation

## Overview
VibeManga is a Python-based CLI tool designed to manage, analyze, and organize large, locally stored manga libraries. It efficiently handles thousands of series and terabytes of data using parallel processing and smart caching mechanisms.

## Tech Stack
- **Language**: Python 3.x
- **CLI Framework**: `click` for command-line interface
- **UI/Visuals**: `rich` library for tables, trees, and progress bars
- **Concurrency**: `concurrent.futures` with `ThreadPoolExecutor` for I/O-bound operations
- **Config**: `python-dotenv` for environment management

## Architecture

### 1. Data Models (`models.py`)
The project uses a strict hierarchical data structure implemented with Python `dataclasses`:
- **Library**: Root container with JSON serialization support
- **Category**: Recursive structure representing both main and sub-categories
- **Series**: Individual manga titles with `external_data` field for metadata storage
- **SubGroup**: Optional sub-folders within series
- **Volume**: Leaf nodes containing `mtime` and `size_bytes` for change detection

All models implement `to_dict()` and `from_dict()` methods for persistent storage in `vibe_manga_library.json`.

### 2. Scanner (`scanner.py`)
- **4-Level Depth Scanning**: Root → Main Category → Sub Category → Series
- **Incremental Scanning**: Reuses persistent state data when file metadata (mtime/size) remains unchanged
- **Parallel Processing**: Uses `ThreadPoolExecutor` for efficient deep file scanning
- **Progress Tracking**: Real-time progress bars with detailed statistics

### 3. Analysis Engine (`analysis.py`)
- **Unit Classification**: Distinguishes between Volumes (`vXX`) and Chapters (`cXX`)
- **Dual Extraction**: Single files can contribute to both volume and chapter counts
- **Deduplication**: Uses semantic masking and fuzzy matching to identify duplicates
- **Utility Functions**: Centralized `parse_size` and `format_size` for consistent byte handling

### 4. Persistence & Caching (`cache.py`)
- **Persistent State**: Complete library hierarchy stored in `vibe_manga_library.json`
- **Speed Cache**: High-performance access via `pickle` (`.vibe_manga_cache.pkl`)
- **Data Integrity**: Automatic updates to persistent state when changes are detected

### 5. Manga Matcher & Parser (`matcher.py`)
Robust parsing engine that normalizes filenames into structured metadata:
- **Integration**: Match command results (torrent magnets) stored in `Series.external_data`
- **Dual-Layer Matching**: Checks existing matches before performing new ones
- **Size Validation**: Enforces minimum size thresholds (35MB for volumes, 4MB for chapters)

### 6. Grabber & qBittorrent Integration (`grabber.py`)
Handles interactive manga selection and acquisition:
- **Comparison Logic**: Compares scraped torrent content against local library
- **Content Detection**: Identifies missing volumes/chapters in local collection
- **Size Heuristics**: Flags quality upgrades and size discrepancies
- **Navigation**: Index-based navigation through manga groups
- **qBit API**: Direct integration via `qbit_api.py` for torrent management

#### Classification Logic
The matcher assigns types to entries:
1. **Manga**: Target content
2. **Light Novel**: Filtered by regex patterns
3. **Visual Novel**: Filtered by regex patterns
4. **Audiobook**: Filtered by regex patterns
5. **Anthology**: Filtered by regex patterns
6. **Periodical**: Weekly magazine releases
7. **UNDERSIZED**: Content failing validation thresholds

#### Parsing Rules (Priority Order)
1. **Tags**: Extracts `[...]`, `(...)`, `{...}` to notes field
2. **Name Stripping**: Removes noise strings
3. **Masking**: Protects specific tokens from number extraction
4. **Mapping**: Parses chapter-to-volume mappings
5. **Messy Volumes**: Handles complex volume tokens
6. **Standard Volumes**: Parses standard volume formats
7. **Chapters**: Parses standard chapter formats
8. **Naked Numbers**: Identifies chapter ranges at string ends

#### Edge Cases Handled
- Dual language titles
- Trailing noise cleanup
- False ranges (start > end)
- Partial updates with mixed formats
- Specific title protections (e.g., "Kaiju No. 8")

## Key Conventions

### Regex & Parsing
1. **Verbose Mode**: All complex regexes use `re.VERBOSE` for readability
2. **Hex Escaping**: Use `\x23` for literal `#` characters in verbose mode
3. **Noise Stripping**: Remove years, version tags, season markers before parsing
4. **Priority**: Ranges take precedence over single numbers

### Directory Structure
The system requires strict `Category/SubCategory/Series/` folder structure. Deviations may cause data issues.

## Current Commands
- `stats`: Library scanning with metrics and continuity checks
- `tree --depth [n]`: Folder hierarchy visualization
- `show [name]`: Detailed series statistics and external updates
- `dedupe [name]`: Duplicate file and structural duplicate scanning
- `scrape`: Nyaa.si scraping for latest releases
- `match`: Integration of scraped data with library metadata
- `grab`: Interactive torrent selection and qBittorrent management

## Roadmap
Refer to `TODO.md` for current development tasks. Future focus includes "Deep Content Analysis" for archive inspection, page counts, and corruption detection.