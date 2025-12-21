# VibeManga

> A powerful Python CLI tool for managing, analyzing, and organizing large manga libraries with parallel processing and intelligent gap detection.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Overview

VibeManga is designed to handle massive manga collections (thousands of series, terabytes of data) with speed and precision. It provides comprehensive statistics, gap detection, duplicate finding, and deep content analysis for your locally stored manga library.

## Features

### ✅ Core Features

- **🚀 High-Performance Scanner**: Parallelized directory scanning using ThreadPoolExecutor for I/O-bound operations
- **📊 Library Statistics**: Detailed breakdowns by category, sub-category, and series
- **🌳 Visual Hierarchy**: Rich tree visualization of your library structure
- **🔍 Series Search**: Fast search with detailed series information
- **📋 Gap Detection**: Intelligent missing volume/chapter detection with support for:
  - Volume numbering (v01, Vol. 1, Volume 1)
  - Chapter numbering (c01, Ch. 1, Chapter 1, #1)
  - Ranges (v01-05, c10-15)
  - Mixed formats and edge cases
- **🔄 Duplicate Finder**:
  - Semantic deduplication (ignores naming differences)
  - Structural duplicate detection (same series in multiple locations)
  - Fuzzy matching with configurable thresholds
- **📦 Archive Inspection**: Deep analysis of `.cbz` and `.cbr` files
  - Page counting
  - Integrity verification
  - Corruption detection
- **💾 Smart Caching & Persistence**: 
  - Dual-layer caching: Fast `pickle` cache for instant subsequent runs and a persistent `vibe_manga_library.json` for long-term storage.
  - **Local Storage**: All metadata and caches are stored in your running directory (project root), keeping your manga library folders clean.
  - Incremental Scanning: Automatically detects filesystem changes (mtime/size) to only re-scan modified files.
- **🔗 External Data Integration**: Integrates metadata from external sources (like Nyaa torrent links) directly into your library's persistent state.
- **📝 Comprehensive Logging**: Detailed logging to file and console for debugging and monitoring

### 🎯 Key Capabilities

- **Handles Complex Naming**: Regex-based parsing with noise filtering for years, versions, seasons, and more
- **Flexible Structure**: Supports nested sub-groups within series (e.g., "v01-v10", "Side Stories")
- **Real-time Progress**: Live progress bars with time estimates and current status
- **Batch Operations**: Process entire library or filter by query

## Tech Stack

- **Language**: Python 3.8+
- **CLI Framework**: [`click`](https://click.palletsprojects.com/) - Command-line interface creation
- **UI/Visuals**: [`rich`](https://github.com/Textualize/rich) - Beautiful terminal output (Tables, Trees, Progress Bars, Panels)
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` - Parallel I/O operations
- **Archive Handling**:
  - `zipfile` (built-in) - CBZ files
  - [`rarfile`](https://pypi.org/project/rarfile/) (optional) - CBR files
- **Configuration**: [`python-dotenv`](https://pypi.org/project/python-dotenv/) - Environment variable management

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/VibeManga.git
   cd VibeManga
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**

   Create a `.env` file in the project root:
   ```env
   MANGA_LIBRARY_ROOT=/path/to/your/manga/library
   ```

4. **Install rarfile support (optional, for .cbr files)**
   ```bash
   pip install rarfile
   ```

   You'll also need the UnRAR tool:
   - **Windows**: Download from [rarlab.com](https://www.rarlab.com/rar_add.htm)
   - **Linux**: `sudo apt-get install unrar` or `sudo yum install unrar`
   - **macOS**: `brew install unrar`

## Usage

### Basic Commands

```bash
# Show library statistics
python -m vibe_manga.run stats

# Show statistics for a specific category/series
python -m vibe_manga.run stats "Action"
python -m vibe_manga.run stats "One Piece"

# Visualize library structure (depth: 1=Main, 2=Sub, 3=Series, 4=SubGroups)
python -m vibe_manga.run tree --depth 3

# Show details for a specific series (includes gaps and available updates)
python -m vibe_manga.run show "Kaiju"

# Check for missing volumes/chapters across the library or a category
python -m vibe_manga.run stats --continuity
python -m vibe_manga.run stats "Action" --continuity

# Find duplicates
python -m vibe_manga.run dedupe
python -m vibe_manga.run dedupe "Naruto"
```

### Scraping & Matching (New)

VibeManga can scrape Nyaa.si for new releases and intelligently match them against your existing library to find updates.

#### 1. Scrape Nyaa
Fetch the latest English-translated releases. By default, it scrapes incrementally (stops when it hits previously seen entries).
```bash
# Basic scrape (default: 5 pages, incremental)
python -m vibe_manga.run scrape

# Scrape more pages and show a summary
python -m vibe_manga.run scrape --pages 10 --summarize

# Force a full fresh scrape (ignore history)
python -m vibe_manga.run scrape --force
```

#### 2. Match Against Library
Parse the scraped data and compare it with your local library to identify relevant updates. Matches are automatically consolidated by series.
```bash
# Match scraped data and show a high-level performance summary
python -m vibe_manga.run match --stats

# Filter matches for a specific series in your library
python -m vibe_manga.run match "Dandadan"

# Show detailed table of all matches
python -m vibe_manga.run match --table

#### 3. Grab Torrents
Interactively select and add manga torrents to qBittorrent. Features intelligent comparison between scraped releases and your local library.
```bash
# Interactively grab the next available manga
python -m vibe_manga.run grab next

# Search for a specific series to grab
python -m vibe_manga.run grab "Dandadan"

# Show current qBittorrent download status for VibeManga
python -m vibe_manga.run grab --status
```

**Grabber Highlights**:
*   **Gap Highlighting**: Clearly displays `[NEW CONTENT AVAILABLE]` with specific volume/chapter counts.
*   **Size Heuristics**: Automatically flags `[LARGER CONTENT]` (e.g. `+2.5 GB`) or `[SMALLER CONTENT]` to help identify high-quality batches or single-chapter releases.
*   **Smart Navigation**: Index-based group navigation with support for skipping or grabbing.
```

### Advanced Options

#### Deep Analysis (Page Counts)
```bash
# Analyze page counts (slower, opens all archives)
python -m vibe_manga.run stats --deep
python -m vibe_manga.run show "Berserk" --deep --showfiles
```

#### Integrity Verification
```bash
# Verify archive integrity (slowest, tests all files)
python -m vibe_manga.run show "One Piece" --verify
python -m vibe_manga.run stats --verify
```

#### Cache Management
```bash
# Force fresh scan and update the cache
python -m vibe_manga.run stats --no-cache

# Clear cache manually (files are in project root)
rm .vibe_manga_cache.pkl vibe_manga_library.json
```

### Command Reference

| Command | Description | Key Options |
|---------|-------------|-------------|
| `stats [query]` | Show library statistics | `--continuity`, `--deep`, `--verify`, `--no-cache` |
| `tree` | Visualize directory hierarchy | `--depth N`, `--deep`, `--verify`, `--no-cache` |
| `show <name>` | Show series details, gaps, and updates | `--showfiles`, `--deep`, `--verify`, `--no-cache` |
| `dedupe [query]` | Find duplicate files | `--verbose`, `--deep`, `--verify`, `--no-cache` |
| `scrape` | Scrape latest entries from Nyaa | `--pages`, `--force`, `--summarize`, `--output` |
| `match [query]` | Parse & categorize scraped data | `--stats`, `--table`, `--all`, `--no-parallel`, `--no-cache` |
| `grab [name]` | Select and add torrents to qBittorrent | `--status`, `--input-file` |

## Manga Name Matching & Parsing

VibeManga includes a sophisticated parser (`matcher.py`) designed to normalize messy filenames from scrape results (e.g., Nyaa.si) into structured data. It handles complex naming conventions, multi-language titles, and edge cases.

### Core Parsing Logic

1.  **Normalization**:
    *   Unescapes HTML entities and Unicode characters.
    *   Strips metadata tags (`[...]`, `(...)`, `{...}`) and moves them to **Notes**.
    *   Strips common noise strings (e.g., "Official Comic Anthology", "Complete Edition").
    *   Handles "Messy Volumes" (e.g., `v045v4_v086-v087`) by extracting the relevant ranges and removing the noise.

2.  **Volume & Chapter Extraction**:
    *   **Standard**: Detects `v01`, `Vol. 1`, `Ch. 10`, `c05`.
    *   **Parts**: Supports `Part XX` or `Parts 1-6` (e.g., JoJo's Bizarre Adventure).
    *   **Ranges**: Handles `v01-05`, `c100-110`.
    *   **Complex Formats**: Parses `001-005 as v01` (Chapter-to-Volume mapping) and `v01-05 + c06-10` (Mixed formats).
    *   **Recursive Naked Numbers**: Identifies complex chapter ranges at the end of titles (`+ 168.1, 255-271`) by recursively peeling them off.

3.  **Type Classification & Filtering**:
    The parser automatically categorizes entries to filter out non-manga content.

    *   **Manga**: The default assumption.
    *   **Light Novel**: Detected via keywords (`Light Novel`, `LN`, `Web Novel`, `J-Novel`, `SoM Kanzenban`).
    *   **Periodical**: Detected via weekly markers (`Weekly`, `Alpha Manga`).
    *   **Visual Novel**: Detected via keywords (`Visual Novel`, `VN`).
    *   **Audiobook**: Detected via keyword (`Audiobook`).
    *   **Anthology**: Detected via keywords (`Archives A-Z`).
    *   **UNDERSIZED**: Items that look like manga but are too small to be valid (e.g., a "Volume" under 35MB).

### Edge Case Handling

The parser is built on a test suite of real-world edge cases:

*   **Size Validation**: Enforces minimum file sizes (35MB/Volume, 4MB/Chapter). Anything smaller is flagged as `UNDERSIZED`.
*   **Dual-Language Titles**: Splits titles like `English Name | Japanese Name` or `English Name \uAC00\uAC00`.
*   **Inverse Ranges**: Correctly ignores invalid ranges like `77-2` (where start > end).
*   **Year vs Chapter**: Distinguishes between Chapter 2025 (`c2025`) and the Year 2025 (in title).
*   **Kaiju No. 8**: Specifically masks "No. 8" to prevent it from being parsed as Chapter 8.
*   **Part Protection**: Masks "Part XX" in titles (e.g., "Ascendance of a Bookworm - Part 02") so it isn't parsed as a volume number.

## Architecture

### Directory Structure

VibeManga expects a specific 4-level hierarchy:

```
Library Root/
├── Main Category/          # Level 1: e.g., "Action", "Romance"
│   ├── Sub Category/       # Level 2: e.g., "Adventure", "Drama"
│   │   ├── Series/         # Level 3: e.g., "One Piece"
│   │   │   ├── volume.cbz
│   │   │   └── SubGroup/   # Level 4 (optional): e.g., "v01-v10"
│   │   │       └── volume.cbz
```

### Data Models

The project uses Python `dataclasses` to enforce a strict hierarchical structure:

```python
Library
  ├── Category (recursive: Main → Sub)
  │     ├── Series
  │     │     ├── Volume (leaf node: actual files)
  │     │     └── SubGroup
  │     │           └── Volume
```

**Key Models**:
- **`Library`**: Root container for the entire collection
- **`Category`**: Main or Sub categories (recursive structure)
- **`Series`**: Individual manga titles
- **`SubGroup`**: Optional subdirectories within a series
- **`Volume`**: Leaf nodes representing actual files (`.cbz`, `.cbr`, etc.)

### Core Components

#### 1. Scanner (`scanner.py`)
- Custom-built for the specific 4-level directory structure
- **Incremental Scanning**: Compares current file `mtime` and `size` against the persistent state to avoid redundant processing.
- Parallel execution: Identifies series paths first, then scans each in parallel.
- Real-time progress callbacks for UI updates.
- Enrichment system for deep analysis and verification.

#### 2. Analysis Engine (`analysis.py`)
- **Regex Patterns**: Complex verbose regex for volume/chapter extraction.
- **Noise Filtering**: Strips years, versions, seasons before parsing.
- **Dual Extraction**: Single file can contribute to both volume AND chapter counts.
- **Priority Handling**: Ranges prioritized over single numbers.
- **Gap Detection**: Identifies missing sequences with range formatting.
- **Fuzzy Matching**: 95% similarity threshold for duplicate detection.

#### 3. CLI (`main.py`)
- `click`-based command structure with nested groups.
- Rich progress bars with 2-line display (visual bar + detailed stats).
- Integrated matching: The `match` command now integrates results directly into the library state.
- Comprehensive error handling and logging.

#### 4. Grabber (`grabber.py`)
- **Interactive selection**: Refined loop for navigating manga groups.
- **Delta Analysis**: Real-time comparison of scraped torrent metadata against local filesystem state.
- **Heuristic Hints**: Identifies potential quality upgrades or undetected batches via size comparison.

#### 5. Cache & Persistence (`cache.py`)
- **Dual-Layer Persistence**: 
  - Fast `pickle` cache for short-term session speed.
  - Persistent JSON state (`vibe_manga_library.json`) for long-term storage of library data and external metadata.
- **Project-Centric**: Caches are stored in the current working directory, not the manga library path.
- Configurable TTL for the speed cache (default: 50 minutes).
- Automatic state preservation after every matching and scanning operation.

#### 6. Constants (`constants.py`)
- Centralized configuration and magic numbers
- File extensions, thresholds, size calculations
- Easy tuning without code changes

## Recent Improvements (v2.1)

### 🎯 Grab & Acquisition
- **New Grabber Module**: Extracted high-level grab logic into `grabber.py` for better modularity.
- **Intelligent Comparison**: The `grab` command now highlights exactly which volumes/chapters you are missing.
- **Size Delta Hints**: Added `[LARGER CONTENT]` and `[SMALLER CONTENT]` flags with precise byte-math (MB/GB) to assist in selection.
- **Improved Navigation**: Index-based "next" behavior ensures you never get stuck on the same group.

### 📊 Code Consolidation
- **Centralized Utilities**: Unified `parse_size` and `format_size` in `analysis.py` to eliminate duplication across scraper, matcher, and grabber.
- **Optimized Size Calculations**: System-wide use of constant-based conversions.

### 📊 Code Quality
- **Comprehensive Logging**: File + console logging with configurable levels
- **Type Hints**: Full type annotations across entire codebase
- **Constants Extraction**: All magic numbers moved to `constants.py`
- **Improved Error Handling**: Detailed exception logging with stack traces

### 🔧 Developer Experience
- **Better Debugging**: `vibe_manga.log` file for troubleshooting
- **Clear Documentation**: Enhanced docstrings with Args/Returns/Raises
- **Maintainable Code**: Extracted constants, better naming conventions

## Configuration

### Environment Variables

Create a `.env` file:

```env
# Required
MANGA_LIBRARY_ROOT=/path/to/manga/library

# Optional (future use)
# CACHE_TTL=300
# LOG_LEVEL=INFO
```

### Constants

Edit `vibe_manga/constants.py` to customize:

```python
# Similarity threshold for duplicate detection
SIMILARITY_THRESHOLD = 0.95

# Cache expiration (seconds)
DEFAULT_CACHE_MAX_AGE_SECONDS = 300

# Valid file extensions
VALID_MANGA_EXTENSIONS = {'.cbz', '.cbr', '.zip', '.rar', '.pdf', '.epub'}
```

## Roadmap

See [TODO.md](TODO.md) for detailed development plans.

### Planned Features

#### Management & Organization
- [ ] **`open` command**: Open series folder in file explorer (Windows/macOS/Linux)
- [ ] **Bulk operations**: Move, rename, or organize series

#### Export & Analysis
- [ ] **`export` command**: Export library data to CSV/JSON for external analysis
- [ ] **`pick` command**: Random series/volume picker for reading suggestions
- [ ] **Statistics dashboard**: Web-based visualization of library stats

#### Advanced Features
- [ ] **Metadata integration**: Pull info from MangaUpdates, AniList, etc.
- [ ] **Reading progress tracking**: Mark volumes as read/unread
- [ ] **Cover extraction**: Generate thumbnails from archive covers
- [ ] **Format conversion**: Batch convert between CBZ/CBR/PDF

## Development

### Project Structure

```
VibeManga/
├── vibe_manga/
│   ├── vibe_manga/
│   │   ├── __init__.py
│   │   ├── main.py           # CLI entry point
│   │   ├── models.py         # Data models
│   │   ├── scanner.py        # Library scanning
│   │   ├── analysis.py       # Parsing & analysis
│   │   ├── cache.py          # Caching system
│   │   └── constants.py      # Configuration constants
│   └── run.py                # Runner script
├── .env                      # Environment config
├── README.md                 # This file
├── TODO.md                   # Development roadmap
├── GEMINI.md                 # Project context
└── requirements.txt          # Dependencies
```

### Coding Conventions

- **Regex**: Use `re.VERBOSE` for complex patterns with comments
- **Hex Escaping**: Use `\x23` for `#` in verbose regex (avoids comment conflicts)
- **Logging**: Use `logger.info/warning/error`, never `print()`
- **Type Hints**: All functions must have complete type annotations
- **Constants**: Extract magic numbers to `constants.py`

### Running Tests

```bash
# Run on a test library
MANGA_LIBRARY_ROOT=/path/to/test/library python -m vibe_manga.run stats

# Enable debug logging
# Edit main.py: logging.basicConfig(level=logging.DEBUG, ...)
python -m vibe_manga.run stats

# Check log output
tail -f vibe_manga.log
```

## Troubleshooting

### Common Issues

**Issue**: "MANGA_LIBRARY_ROOT is not set"
- **Solution**: Create a `.env` file with your library path

**Issue**: CBR files not scanned
- **Solution**: Install `rarfile` package and UnRAR tool

**Issue**: Slow scanning
- **Solution**: Use caching (`--no-cache` only when needed)

**Issue**: Missing volumes not detected
- **Solution**: Check filename format matches expected patterns (v01, c01, etc.)

**Issue**: Permission errors
- **Solution**: Check file/directory permissions in library

### Debugging

1. Check the log file: `cat vibe_manga.log`
2. Run with fresh cache: `--no-cache`
3. Test on a small library first
4. Verify directory structure matches expected 4-level hierarchy

## Performance

### Benchmarks (Approximate)

| Library Size | First Scan | Cached Scan | Deep Analysis |
|--------------|------------|-------------|---------------|
| 100 series   | ~5-10s     | <1s         | ~30s          |
| 1,000 series | ~30-60s    | <1s         | ~5min         |
| 5,000 series | ~2-5min    | <1s         | ~20min        |

*Note: Times vary based on storage speed, file count, and system resources*

### Optimization Tips

1. **Use caching**: Default 5-minute cache dramatically speeds up repeated commands
2. **Avoid `--deep` unless needed**: Only use for page count analysis
3. **Avoid `--verify` unless debugging**: Integrity checks are very slow
4. **SSD storage**: Significantly faster than HDD for scanning thousands of files
5. **Query filtering**: Use specific queries to limit scope (`stats "Action"` vs `stats`)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Follow existing code style and conventions
4. Add type hints and logging
5. Test with a real manga library
6. Submit a pull request

## License

[MIT License](LICENSE)

## Acknowledgments

- Built with [Rich](https://github.com/Textualize/rich) for beautiful terminal output
- Inspired by the need to manage massive manga collections efficiently
- Thanks to the manga community for feedback and feature requests

## Contact

- **Issues**: [GitHub Issues](https://github.com/yourusername/VibeManga/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/VibeManga/discussions)

---

**VibeManga** - Manage your manga library with style and speed 🚀📚
