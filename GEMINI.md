# VibeManga - Project Context

## Overview
VibeManga is a Python-based CLI tool designed to manage, analyze, and organize a large, locally stored manga library. It is designed to handle thousands of series and terabytes of data efficiently using parallel processing.

## Tech Stack
- **Language**: Python 3.x
- **CLI Framework**: `click`
- **UI/Visuals**: `rich` (Tables, Trees, Progress Bars)
- **Concurrency**: `concurrent.futures` (ThreadPoolExecutor) for I/O-bound scanning.
- **Config**: `python-dotenv`

## Architecture

### 1. Data Models (`models.py`)
The project enforces a strict hierarchical data structure using Python `dataclasses`:
*   **Library**: The root container. Supports JSON serialization.
*   **Category** (Recursive): Represents both "Main" and "Sub" categories.
*   **Series**: The actual manga title. Includes `external_data` field for storing metadata (e.g. torrent links).
*   **SubGroup**: Optional sub-folders within a series.
*   **Volume**: The leaf nodes. Includes `mtime` and `size_bytes` for change detection.

All models implement `to_dict()` and `from_dict()` for persistent storage in `vibe_manga_library.json`.

### 2. The Scanner (`scanner.py`)
*   **Logic**: Custom 4-level depth scanner: `Root -> Main Category -> Sub Category -> Series`.
*   **Incremental Scanning**: Reuses data from the persistent state if a file's `mtime` and `size` haven't changed.
*   **Parallelism**: Uses `ThreadPoolExecutor` for deep file scanning.
*   **Progress**: Real-time progress bar with detailed statistics.

### 3. Analysis Engine (`analysis.py`)
*   **Unit Classification**: Distinguishes between Volumes (`vXX`) and Chapters (`cXX`).
*   **Dual Extraction**: Single files can contribute to both volume and chapter counts.
*   **Semantic Normalization**: A robust `semantic_normalize` utility that aggressively strips articles ("The", "A"), tags, punctuation, and whitespace for cross-platform title matching.
*   **Deduplication**: Uses semantic normalization and fuzzy matching for finding structural and file-level duplicates.
*   **Utility Layer**: Consolidated `parse_size` and `format_size` functions used system-wide for consistent byte handling.

### 4. Persistence & Caching (`cache.py`)
...
### 5. Manga Matcher & Parser (`matcher.py`)
A robust parsing engine that normalizes filenames into structured metadata.
*   **Integration**: Results from the `match` command (like torrent magnets) are integrated directly into the `Series.external_data` field in the persistent library state.
*   **Dual-Layer Matching**: Checks for existing matches in the output file and library before performing new matches.
*   **Semantic Matching**: Employs `semantic_normalize` to ensure titles like "The 100 Girlfriends" correctly match library entries named "100 Girlfriends, The".
*   **Shared Logic**: Utilizes central size parsing to enforce `UNDERSIZED` filters (Min Vol: 35MB, Min Chap: 4MB).

### 6. Grabber & qBittorrent Integration (`grabber.py`)
Handles the interactive selection and acquisition of manga.
*   **Comparison Logic**: Automatically compares scraped torrent content against local library state.
*   **New Content Detection**: Identifies specifically which volumes or chapters are missing from the local collection.
*   **Size Heuristics**: Flags `LARGER CONTENT` (potential quality upgrade or undetected batches) and `SMALLER CONTENT` based on library-to-torrent size deltas.
*   **Navigation**: Supports index-based navigation through consolidated manga groups.
*   **qBit API**: Direct integration via `qbit_api.py` for headless torrent management.

#### Classification Logic
The matcher assigns a `Type` to each entry:
1.  **Manga**: The target content.
2.  **Light Novel**: Filtered via regex (`light\s*novel`, `ln`, `j-novel`, `web\s*novel`, `som\s*kanzenban`).
3.  **Visual Novel**: Filtered via regex (`visual\s*novel`, `vn`).
4.  **Audiobook**: Filtered via regex.
5.  **Anthology**: Filtered via regex (`archives\s*[a-z]-[a-z]`).
6.  **Periodical**: Weekly magazine releases filtered via (`weekly`, `alpha manga`).
7.  **UNDERSIZED**: A "Manga" entry that fails validation thresholds (Min Vol: 35MB, Min Chap: 4MB).

#### Parsing Rules (Priority Order)
1.  **Tags**: Extracts `[...]`, `(...)`, `{...}` and moves them to `notes`.
2.  **Name Stripping**: Removes specific noise strings ("Special Issue", "Complete Edition", etc.).
3.  **Masking**: Protects specific tokens ("Part XX", "Kaiju No. 8") from number extraction.
4.  **Mapping**: Parses `X as vY` (Chapters mapping to Volumes).
5.  **Messy Volumes**: Detects complex tokens (e.g., `v045v4_v086-v087`) to extract the final semantic range.
6.  **Standard Volumes**: `v01`, `Vol. 1`, `Parts 1-6`.
7.  **Chapters**: `c01`, `Ch. 1`, `Chapter 1`.
8.  **Naked Numbers**: Recursively identifies valid number ranges at the end of the string (e.g. `+ 168.1, 255-271`) as chapters.

#### Edge Cases Handled
*   **Dual Language**: Splits `English | Native` or `English [Native]` titles.
*   **Trailing Noise**: Cleans up separators (`-`, `+`) left behind after extracting numbers.
*   **False Ranges**: Ignores `77-2` (start > end).
*   **Partial Updates**: Handles `v01-05 + c06-10` mixed formats.
*   **Kaiju No. 8**: Specifically prevented from parsing "8" as a chapter.

## Key Conventions

### Regex & Parsing
The project uses complex regex patterns to handle the wide variety of manga naming conventions.
1.  **Verbose Mode**: All complex regexes MUST use `re.VERBOSE` to allow for comments and readability.
2.  **Hex Escaping**: The `#` character is a comment starter in verbose mode. To match a literal hash (e.g., `#1`), you **MUST** use `\x23`. Failing to do so causes syntax errors.
3.  **Noise Stripping**: We strictly strip years `(2021)`, version tags `[v2]`, and season markers `Season 1` *before* parsing numbers.
4.  **Priority**: Ranges (`v01-05`) are prioritized over single numbers (`v01`) in regex groups to prevent partial matches.

### Directory Structure
The logic *heavily* relies on the folder structure being `Category/SubCategory/Series/`. Deviations from this depth may result in data being missed or miscategorized.  Manga is preferred to be stored as a string composed of the following elements:
  a. {Series} A sanitized name, ending with articles (The, An, Le, etc.), e.g. "One Piece" or "Lucky Man, The"
  b. {vXX}: two digits of the volume number prefaced by v, e.g. "v01" v99"
  c. {XXX[.X]): three digits of the chapter number with no preface, e.g. "001", "020.5", "199"}
## Current Commands
*   `stats`: Scans the library and shows high-level metrics, category breakdowns, and optional continuity checks (`--continuity`).
*   `tree --depth [n]`: Visualizes the folder hierarchy.
*   `show [name]`: Searches for a specific series and shows detailed stats, gaps, and external updates.
*   `dedupe [name]`: Scans for duplicate files and structural duplicates.
*   `scrape`: Scrapes Nyaa.si for latest releases.
*   `match`: Integrates scraped data with library metadata.
*   `grab`: Interactively select and add torrents to qBittorrent.

## Roadmap
See `TODO.md` for active tasks. Next big steps involve "Deep Content Analysis" (archive inspection for page counts/corruption).