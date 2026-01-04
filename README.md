# VibeManga

> A powerful Python CLI tool for managing, analyzing, and organizing large manga libraries with parallel processing, intelligent gap detection, and AI-powered automation.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Overview

VibeManga is designed to handle massive manga collections (thousands of series, terabytes of data) with speed and precision. It provides comprehensive statistics, gap detection, duplicate finding, deep content analysis, torrent automation, and AI-powered organization for your locally stored manga library. It employs a **Metadata-First** architecture, using MyAnimeList (Jikan) data as the source of truth for organization and matching.

## Architecture: Metadata Source-of-Truth

VibeManga's architecture revolves around a four-phase overhaul that elevated metadata above folder names:

1. **Phase 1 – Models & Indexer**: `Series.metadata` uses the strongly typed `SeriesMetadata` schema, and the `LibraryIndex` builds MAL ID and synonym lookups for O(1) resolution.
2. **Phase 2 – Hydration Pipeline**: The `hydrate` command scans the filesystem, fetches missing MAL data (via Jikan with AI fallback), and persists it to each `series.json` so every series has a unique identifier.
3. **Phase 3 – Robust Matching**: The matcher consumes the `LibraryIndex`, prioritizing MAL IDs, then synonym-aware searches, and finally fuzzy scoring across every known identity for a series.
4. **Phase 4 – Standardization**: The `rename` and `organize` workflows enforce consistency by renaming folders/files to canonical metadata titles, preventing regression back to path-based identities.

Together these phases deliver deterministic torrent matching, lossless reorganization, and safer automation on live libraries.

## Features

### ✅ Core Features

- **🚀 High-Performance Scanner**: Parallelized directory scanning using ThreadPoolExecutor for I/O-bound operations
- **📊 Library Statistics**: Detailed breakdowns by category, sub-category, and series with rich visualizations
- **🌳 Visual Hierarchy**: Rich tree visualization of your library structure
- **🔍 Series Search**: Fast search with detailed series information
- **📋 Gap Detection**: Intelligent missing volume/chapter detection with support for ranges and complex numbering
- **🔄 Duplicate Finder**: Semantic deduplication and structural duplicate detection
- **📦 Archive Inspection**: Deep analysis of `.cbz` and `.cbr` files (page counting, integrity verification)
- **💾 Smart Caching**: Dual-layer caching (Pickle for speed, JSON for persistence) with incremental scanning
- **🤖 AI-Powered Organization**: Smart categorization using LLMs with multiple providers (Ollama, OpenAI, Anthropic)
- **📚 Metadata Enrichment (Hydration)**: Fetches rich details (MAL ID, synonyms, authors) from Jikan with AI fallback
- **🏷️ Standardization (Rename)**: Renames folders/files to match canonical metadata titles (English or Japanese)
- **🔗 Robust Matching**: Uses a **Library Index** to match torrents by MAL ID, Synonyms, or Expanded Fuzzy Logic
- **⚡ Parallel Transfers**: Multi-threaded copy/move operations with progress tracking
- **🎯 Intelligent Filtering**: Organize library with complex filters (tags, genres, sources)

### 🎯 Key Capabilities

- **Handles Complex Naming**: Regex-based parsing with noise filtering
- **Flexible Structure**: Supports nested sub-groups and complex library hierarchies
- **Real-time Progress**: Live progress bars with transfer speeds and ETA
- **Filesystem Safety**: Automatic sanitization of illegal characters, collision detection
- **Torrent Automation**: Full pipeline from scraping to post-processing
- **AI Integration**: Dual AI provider support (local + remote) with token tracking

## Tech Stack

- **Language**: Python 3.8+
- **CLI Framework**: [`click`](https://click.palletsprojects.com/)
- **UI/Visuals**: [`rich`](https://github.com/Textualize/rich) - Tables, Trees, Progress Bars, Panels
- **Configuration**: [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - Type-safe, validated configuration
- **Data Validation**: [`pydantic`](https://docs.pydantic.dev/) >= 2.0.0
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` for parallel I/O operations
- **Archive Handling**: `zipfile`, [`rarfile`](https://pypi.org/project/rarfile/)
- **AI Integration**: OpenAI-compatible APIs (OpenRouter, Ollama, LocalAI)

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- qBittorrent with Web UI enabled (for torrent automation)
- UnRAR tool (for .cbr support)

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
   Create a `.env` file based on `.env.example`:
   ```env
   # Core Library Path
   LIBRARY_PATH="/path/to/your/manga/library"
   
   # qBittorrent Integration
   QBIT__URL="http://localhost:8080"
   QBIT__USERNAME="admin"
   QBIT__PASSWORD="adminadmin"
   
   # AI Configuration (Remote - for complex tasks)
   AI__PROVIDER="remote"
   AI__BASE_URL="https://openrouter.ai/api/v1"
   AI__API_KEY="sk-or-..."
   AI__MODEL="anthropic/claude-3-haiku"
   
   # AI Configuration (Local - for privacy/bulk tasks)
   AI__PROVIDER="local"
   AI__BASE_URL="http://localhost:11434"
   AI__API_KEY="ollama"
   AI__MODEL="llama3.1"
   ```

4. **Install rarfile support (optional)**
   ```bash
   pip install rarfile
   ```
   (Requires UnRAR tool installed on system)

## Usage

### Quick Start: Full Update Cycle

```bash
# Run complete pipeline: pull completed torrents, refresh metadata, categorize, and replenish queue
python -m vibe_manga.run pullcomplete -v
```

### Organization & Metadata

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

# 3. Organize Library (Move/Copy with filters)
# Move series with specific tags
python -m vibe_manga.run organize --tag "Shounen" --target "Manga/Action" --simulate
# Copy to new location (preserves original)
python -m vibe_manga.run organize --newroot "/path/to/new/library" --auto
```

### Basic Analysis Commands

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

### Torrent Automation Pipeline

```bash
# 1. Scrape Nyaa (Incremental)
python -m vibe_manga.run scrape

# 2. Match Against Library
# Uses ID/Synonym lookup for high precision
python -m vibe_manga.run match --stats

# 3. Grab Torrents
# Interactively select and add to qBittorrent
python -m vibe_manga.run grab "Dandadan"
# Auto-add if contains new volumes
python -m vibe_manga.run grab --auto-add

# 4. Process Completed Downloads
python -m vibe_manga.run pull

# 5. Full Automation Cycle
python -m vibe_manga.run pullcomplete -v
```

### Advanced Options

```bash
# Deep Analysis (Page Counts & Integrity)
python -m vibe_manga.run stats --deep --verify

# Force fresh scan (ignore cache)
python -m vibe_manga.run stats --no-cache

# AI Categorization with explanations
python -m vibe_manga.run categorize --explain --pause

# Metadata fetch with parallel processing
python -m vibe_manga.run metadata --all --parallel 4 -vv
```

### Command Reference

| Command | Description | Key Options |
|---------|-------------|-------------|
| `pullcomplete` | Full automation cycle | `-v`, `--input-file` |
| `hydrate` | Fetch metadata/IDs for series | `--force`, `--model-assign` |
| `rename` | Standardize folders/files | `--simulate`, `--english`, `--japanese`, `--auto` |
| `organize` | Move/Copy with filters | `--tag`, `--genre`, `--source`, `--target`, `--newroot` |
| `stats` | Show library statistics | `--continuity`, `--deep`, `--verify` |
| `tree` | Visualize directory hierarchy | `--depth N`, `--xml` |
| `show` | Show series details | `--showfiles`, `--deep` |
| `scrape` | Scrape Nyaa | `--pages`, `--force` |
| `match` | Match scrape data to library | `--stats`, `--table`, `--no-parallel` |
| `grab` | Add torrents to qBit | `--auto-add`, `--max` |
| `pull` | Process completed torrents | `--simulate`, `--pause`, `-v` |
| `metadata` | Manual metadata fetch | `--force-update`, `--parallel` |
| `categorize`| AI Categorization | `--auto`, `--explain`, `--model-assign` |
| `dedupe` | Find duplicates | `--structural-only`, `--deep` |

## Architecture

### Source of Truth

VibeManga uses a **Metadata-Based Identity** system. A series is defined by its MAL ID (stored in `series.json`), not just its folder name.

- **Indexer**: Builds a fast lookup map of IDs and Synonyms for O(1) resolution
- **Matcher**: Resolves incoming filenames to Series objects using the Indexer
- **Renamer**: Enforces consistency by renaming filesystem artifacts to match Metadata
- **Organizer**: Applies complex filters to restructure library hierarchically

### Configuration Management

Centralized, type-safe configuration using Pydantic Settings:

```python
# Access configuration anywhere
from vibe_manga.config.manager import get_config

config = get_config()
library_path = config.library_path
ai_model = config.ai.model
qbit_url = config.qbit.url
```

Configuration is loaded from:
1. Environment variables (e.g., `LIBRARY_PATH`, `AI__MODEL`)
2. `.env` file (with nested support: `AI__BASE_URL`)
3. Defaults defined in config classes

### Directory Structure

```
Library Root/
├── Main Category/
│   ├── Sub Category/
│   │   ├── Series/
│   │   │   ├── series.json       # Source of Truth (Metadata)
│   │   │   ├── [Series] v01.cbz
│   │   │   ├── [Series] v02.cbz
│   │   │   └── SubGroup/
│   │   │       ├── [Series] c001.cbz
│   │   │       └── [Series] c002.cbz
```

## AI Integration

VibeManga supports dual AI providers:

- **Remote AI** (OpenRouter, OpenAI, Anthropic): For complex reasoning, categorization, metadata consensus
- **Local AI** (Ollama, LocalAI): For privacy-sensitive tasks, bulk processing, cost savings

### AI Roles

Different tasks use specialized AI prompts:
- **MODERATOR**: Validates metadata matches
- **PRACTICAL**: Suggests categories based on content
- **CREATIVE**: Handles ambiguous cases

Configure roles in `vibe_manga_ai_config.json`:
```json
{
  "MODERATOR": {
    "system_prompt": "You validate manga metadata matches...",
    "temperature": 0.3
  }
}
```

### Token Tracking

Monitor AI usage across sessions:
```python
from vibe_manga.ai_api import tracker

usage = tracker.get_summary()
# {"claude-3-haiku": {"prompt": 15000, "completion": 3000}}
```

## Contributing

Contributions are welcome! Please:
- Follow existing code style and patterns
- Add type hints to all functions
- Update documentation for new features
- Add tests for new functionality

## License

[MIT License](LICENSE)
