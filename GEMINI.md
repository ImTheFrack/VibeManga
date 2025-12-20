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
*   **Library**: The root container.
*   **Category** (Recursive): Represents both "Main" (e.g., "Action") and "Sub" (e.g., "Adventure") categories.
*   **Series**: The actual manga title (e.g., "Kaiju No. 8").
*   **SubGroup**: Optional sub-folders within a series (e.g., "v01-v10", "Side Stories").
*   **Volume**: The leaf nodes, representing actual files (`.cbz`, `.cbr`, etc.).

### 2. The Scanner (`scanner.py`)
*   **Logic**: The scanner is custom-built to match a specific 4-level directory depth: `Root -> Main Category -> Sub Category -> Series`.
*   **Parallelism**: Directory traversal is split. It first traverses directories to identify all `Series` paths (fast), then submits each `Series` to a `ThreadPoolExecutor` for deep file scanning.
*   **Progress**: It supports a callback system to update the UI in real-time as series complete scanning.

### 3. Analysis Engine (`analysis.py`)
*   **Unit Classification**: Distinguishes between Volumes (`vXX`) and Chapters (`cXX`).
*   **Dual Extraction**: A single file can contribute to both volume and chapter counts (e.g., `v11 c48-51`).
*   **Deduplication**: Uses semantic masking (replacing numbers with `{VOL}`) to distinguish between true duplicates and similar series names (e.g., "Season 1 v01" vs "Season 2 v01").

### 4. CLI Entry Point (`main.py`)
*   Uses `click` for command grouping.
*   Uses `rich.progress` and `rich.live` for a 2-line persistent progress bar (Line 1: Visual Bar, Line 2: Detailed Stats).

### 5. Manga Matcher & Parser (`matcher.py`)
A robust parsing engine designed to normalize messy torrent/file names into structured Manga metadata.

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
The logic *heavily* relies on the folder structure being `Category/SubCategory/Series/`. Deviations from this depth may result in data being missed or miscategorized.

## Current Commands
*   `stats`: Scans the library and shows high-level metrics and category breakdowns.
*   `tree --depth [n]`: Visualizes the folder hierarchy.
*   `find [name]`: Searches for a specific series.
*   `check [name]`: Scans for missing volumes/chapters (gaps).
*   `dedupe [name]`: Scans for duplicate files and structural duplicates.

## Roadmap
See `TODO.md` for active tasks. Next big steps involve "Deep Content Analysis" (archive inspection for page counts/corruption).