# VibeManga

> A powerful Python CLI tool for managing, analyzing, and organizing large manga libraries with parallel processing and intelligent gap detection.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Overview

VibeManga is designed to handle massive manga collections (thousands of series, terabytes of data) with speed and precision. It provides comprehensive statistics, gap detection, duplicate finding, and deep content analysis for your locally stored manga library. It now employs a **Metadata-First** architecture, using MyAnimeList (Jikan) data as the source of truth for organization and matching.

## RECENT UPDATE: Metadata Source-of-Truth Refactor

VibeManga recently completed a four-phase refactor to guarantee that MyAnimeList metadata—not folder names—defines every series in your library:

1. **Phase 1 – Models & Indexing:** `Series.metadata` now uses the strongly typed `SeriesMetadata` schema, and the new `LibraryIndex` builds MAL ID and synonym lookups for O(1) resolution.
2. **Phase 2 – Metadata Hydration:** The `hydrate` command scans the filesystem, fetches missing MAL data (via Jikan with AI fallback), and persists it to each `series.json` so every series has a unique identifier.
3. **Phase 3 – Robust Matching:** The matcher consumes the `LibraryIndex`, prioritizing MAL IDs, then synonym-aware searches, and finally fuzzy scoring across every known identity for a series.
4. **Phase 4 – Standardization:** The `rename` workflow (with `--simulate`, `--english`, `--japanese`, and `--auto` controls) renames folders/files to the canonical metadata titles, preventing regression back to path-based identities.

Together these phases deliver deterministic torrent matching, lossless reorganization, and safer automation on live libraries.

## Features

### ✅ Core Features

- **🚀 High-Performance Scanner**: Parallelized directory scanning using ThreadPoolExecutor for I/O-bound operations
- **📊 Library Statistics**: Detailed breakdowns by category, sub-category, and series
- **🌳 Visual Hierarchy**: Rich tree visualization of your library structure
- **🔍 Series Search**: Fast search with detailed series information
- **📋 Gap Detection**: Intelligent missing volume/chapter detection with support for ranges and complex numbering.
- **🔄 Duplicate Finder**: Semantic deduplication and structural duplicate detection.
- **📦 Archive Inspection**: Deep analysis of `.cbz` and `.cbr` files (Page counting, Integrity verification).
- **💾 Smart Caching**: Dual-layer caching (Pickle for speed, JSON for persistence) with incremental scanning.
- **🤖 AI-Powered Organization**: Smart categorization using LLMs.
- **📚 Metadata Enrichment (Hydration)**:
  - Fetches rich details (MAL ID, synonyms, authors) from Jikan with AI fallback.
  - Saves persistent `series.json` in each folder.
- **🏷️ Standardization (Rename)**:
  - Renames folder names to match the canonical metadata title (English or Japanese).
  - Renames files to match the standard `[Series] [Vol]` convention.
  - Normalizes `.zip/.rar` extensions to `.cbz/.cbr`.
- **🔗 Robust Matching**: Uses a **Library Index** to match torrents by MAL ID, Synonyms, or Expanded Fuzzy Logic (matching "Attack on Titan" to "Shingeki no Kyojin").

### 🎯 Key Capabilities

- **Handles Complex Naming**: Regex-based parsing with noise filtering.
- **Flexible Structure**: Supports nested sub-groups.
- **Real-time Progress**: Live progress bars.
- **Filesystem Safety**: Automatic sanitization of illegal characters.

## Tech Stack

- **Language**: Python 3.8+
- **CLI Framework**: [`click`](https://click.palletsprojects.com/)
- **UI/Visuals**: [`rich`](https://github.com/Textualize/rich)
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor`
- **Archive Handling**: `zipfile`, [`rarfile`](https://pypi.org/project/rarfile/)

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
   Create a `.env` file:
   ```env
   MANGA_LIBRARY_ROOT=/path/to/your/manga/library
   ```

4. **Install rarfile support (optional)**
   ```bash
   pip install rarfile
   ```
   (Requires UnRAR tool installed on system)

## Usage

### Organization & Metadata (New)

```bash
# 1. Hydrate Metadata (Fetch IDs/Titles for all series)
python -m vibe_manga.run hydrate

# 2. Standardize Names (Rename folders/files to match Metadata)
# Preview changes first
python -m vibe_manga.run rename --simulate
# Apply changes
python -m vibe_manga.run rename
# Prefer Japanese titles
python -m vibe_manga.run rename --japanese
```

### Basic Commands

```bash
# Show library statistics
python -m vibe_manga.run stats

# Show statistics for a specific category/series
python -m vibe_manga.run stats "One Piece"

# Visualize library structure
python -m vibe_manga.run tree --depth 3

# Show details for a specific series
python -m vibe_manga.run show "Kaiju"

# Check for missing volumes/chapters
python -m vibe_manga.run stats --continuity

# Find duplicates
python -m vibe_manga.run dedupe
```

### Scraping & Matching

VibeManga can scrape Nyaa.si and intelligently match updates against your library using the **Library Index**.

```bash
# 1. Scrape Nyaa (Incremental)
python -m vibe_manga.run scrape

# 2. Match Against Library
# Uses ID/Synonym lookup for high precision
python -m vibe_manga.run match --stats

# 3. Grab Torrents
# Interactively select and add to qBittorrent
python -m vibe_manga.run grab "Dandadan"
```

### Advanced Options

```bash
# Deep Analysis (Page Counts)
python -m vibe_manga.run stats --deep

# Integrity Verification
python -m vibe_manga.run stats --verify

# Force fresh scan
python -m vibe_manga.run stats --no-cache
```

### Command Reference

| Command | Description | Key Options |
|---------|-------------|-------------|
| `hydrate` | Fetch metadata/IDs for series | `--force` |
| `rename` | Standardize folders/files | `--simulate`, `--english`, `--japanese`, `--auto` |
| `stats` | Show library statistics | `--continuity`, `--deep` |
| `tree` | Visualize directory hierarchy | `--depth N` |
| `show` | Show series details | `--showfiles` |
| `scrape` | Scrape Nyaa | `--pages` |
| `match` | Match scrape data to library | `--stats`, `--table` |
| `grab` | Add torrents to qBit | `--status` |
| `metadata` | Manual metadata fetch | `--force-update` |
| `categorize`| AI Categorization | `--auto` |

## Architecture

### Source of Truth
VibeManga uses a **Metadata-Based Identity** system. A series is defined by its MAL ID (stored in `series.json`), not just its folder name.
- **Indexer**: Builds a fast lookup map of IDs and Synonyms.
- **Matcher**: Resolves incoming filenames to Series objects using the Indexer.
- **Renamer**: Enforces consistency by renaming filesystem artifacts to match the Metadata.

### Directory Structure
```
Library Root/
├── Main Category/
│   ├── Sub Category/
│   │   ├── Series/
│   │   │   ├── series.json       # Source of Truth
│   │   │   ├── [Series] v01.cbz
```

## Contributing

Contributions are welcome! Please follow code style and add type hints.

## License

[MIT License](LICENSE)