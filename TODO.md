# VibeManga Development Roadmap

> **Note**: See [README.md](README.md) for complete project overview, installation, and usage instructions.

## Recently Completed (v2.0)

- [x] **Smart Caching System**: 5-minute TTL with `--no-cache` option
- [x] **Comprehensive Logging**: File and console logging with configurable levels
- [x] **Type Hints**: Full type annotations across entire codebase
- [x] **Constants Extraction**: Magic numbers moved to centralized constants.py
- [x] **Archive Inspection**: Page counting and integrity verification for CBZ/CBR files
- [x] **Enhanced Stats**: Total page counts with `--deep` flag

## Planned Features

### 1. Management & Organization
- [ ] **Open Series (`open`)**: 
    - Command to open a series folder in Windows Explorer/Finder.
- [ ] **Re-Organizer (`organize`)**:
    - Command to reorganize folders with tag, genre, or AI assistance.  See `ORGANIZPLAN.MD` for more.
    - Once implemented, we can get rid of `categorize` command.
### 2. Export & Reporting
- [ ] **Export Data (`export`)**:
    - Export library data to CSV/JSON for external tools (Excel, data analysis, backup)
    - Include series metadata, file paths, statistics
- [ ] **Report Generation**:
    - HTML/PDF reports with charts and graphs
    - Missing volumes report
    - Duplicate files report

### 3. User Experience
- [ ] **Random Picker (`pick`)**:
    - Suggest a random series or volume to read
    - Support filters (category, unread, rating)
- [ ] **Interactive Mode**:
    - Launch interactive TUI (Text User Interface) for browsing
    - Keyboard navigation, quick actions
    - Eventual full web front end?
- [ ] **Configuration File**:
    - YAML/TOML config instead of just .env
    - Per-directory settings
    - Custom naming patterns

### 4. Advanced Features
- [X] **Metadata Integration**:
    - Fetch from MangaUpdates, AniList, MyAnimeList
    - Store series descriptions, ratings, status
    - Four-Phase Refactor (COMPLETED):
        1. ✅ Phase 1: Models & Indexing - Strongly-typed metadata schema with LibraryIndex
        2. ✅ Phase 2: Hydration - Jikan API integration with AI fallback
        3. ✅ Phase 3: Robust Matching - MAL ID → synonym → fuzzy matching cascade
        4. ✅ Phase 4: Standardization - Canonical naming enforcement
- [ ] **Reading Progress**:
    - Track read/unread volumes
    - Last read date and position
    - Reading statistics and history
- [ ] **Cover Management**:
    - Extract and cache cover images
    - Generate thumbnails
    - Display in terminal (using rich/iTerm2)
- [ ] **Format Conversion**:
    - Batch convert CBZ ↔ CBR ↔ PDF
    - Optimize file sizes
    - Rename files to standard format

### 5. Performance & Scalability
- [ ] **Database Backend**:
    - SQLite for faster queries on large libraries
    - Incremental updates (only scan changed directories)
    - Full-text search
- [ ] **Watch Mode**:
    - Monitor library for changes
    - Auto-update cache
    - Notifications for new volumes
- [ ] **Multi-Library Support**:
    - Manage multiple libraries
    - Switch between them
    - Merge statistics

### 6. Quality of Life
- [X] **Bulk Operations**:
    - Move series between categories
    - Rename series/volumes in batch
    - Delete duplicates with confirmation
- [ ] **Validation**:
    - Check for naming convention violations
    - Suggest corrections
    - Auto-fix common issues
- [ ] **Web Interface** (Long-term):
    - Browse library via web browser
    - Mobile-friendly responsive design
    - Online reader integration

### 7. Metadata Management
- [x] **Enrichment Command (`metadata`)**:
    -   **Goal**: Create a local, persistent knowledge base for every series to minimize API usage and enable advanced analysis.
    -   **Action**: Fetch detailed info via Jikan (MAL), AniList, or AI (fallback) and save to `series.json` in the series folder.
    -   **Schema**: Title, Alt Titles, Authors, Synopsis, Genres, Tags, Demographics, Status (Completed, Ongoing, Hiatus, Cancelled), Total Volumes/Chapters, Release Year, MAL/AniList IDs.
-   **Integration Benefits**:
    -   **Smart Categorization**: Uses cached genres/tags for instant, deterministic sorting without external calls.
    -   **Advanced Stats**: Enables breakdown by Demographics (Seinen vs Shonen), Genre distribution, or Publication Status.
    -   **Gap Detection**: Compare local file counts against "Official Total Chapters" to detect incomplete series even if no numbers are skipped.
    -   **Rich Display**: The `show` command will display synopses, ratings, and authors.

### 8. AI Integration & Automation
- [x] **Infrastructure & Configuration**:
    - **Backends**: Support **OpenRouter** (remote) and **Ollama** (local) via OpenAI-compatible APIs.
    - **Config**: Store keys/URLs in `.env`, expose via `constants.py`.
    - **Roles & Models**: Define distinct system prompts (Roles) in `constants.py` (e.g., `ROLE_LIBRARIAN`, `ROLE_MODERATOR`). Allow per-call selection of Model and Role.
    - **Validation**: Strict parsing of AI outputs (JSON/Structured) to ensure validity before acting.
- [x] **Content Safety & Filtering (Critical)**:
    - **Adult Classification**: Distinguish between "Mature" (Gore, Ecchi, Dark Themes) and "Adult" (Pornography/Hentai) based on American sensibilities.
        - *Rule*: Explicit sexual content -> Move to `Adult` category.
    - **Illegal/Harmful Content**:
        - *Rule*: Flag CP, Hateful, or Illegal content for **immediate deletion**.
- [x] **Smart Categorization (`categorize`)**:
    - **Goal**: Automatically sort series from "Uncategorized/Pulled-*" folders into the main library.
    - **Strategy**:
        1. **Metadata Acquisition**: Read local `series.json` (from `metadata` command) or fetch via APIs if missing.
        2. **Contextual Analysis**: 
            - Scan existing library for related series (prequels/sequels).
            - Analyze current folder structure to learn user's taxonomy.
        3. **Sensible Taxonomy**: Avoid lazy tags (e.g., "Isekai" overload). Create balanced, meaningful categories.
        4. **AI Consensus**: Use LLMs to propose the best `Category/SubCategory` path.
    - **Features**:
        - Dry-run mode with `rich` tables showing confidence scores.
        - Interactive confirmation before moving files.
- [ ] **Library Rebalancing (`--rebalance`)**:

## Technical Improvements

### Code Quality
- [ ] Add unit tests (pytest)
- [ ] Add integration tests
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Code coverage reporting
- [ ] Pre-commit hooks (black, flake8, mypy)

### Refactoring
- [x] **Command Modularization**: Break down `main.py` into specific CLI modules (In Progress).
    - [x] Created `cli` package and `base.py`.
    - [x] Extracted `scrape`, `match`, `grab`, `pull`.
    - [ ] Extract remaining commands (`metadata`, `stats`, `categorize`, etc.).
- [x] **Centralized Utilities**: Extract common functionality into shared utility modules to reduce duplication
    - [x] **Standardize Progress Bars**: Moved `run_scan_with_progress` to `cli/base.py`.
    - [ ] **Unified JSON I/O**: Implement `load_json` and `save_json` with standardized error handling (console error printing + logging) to replace repetitive `try-except` blocks in `matcher.py`, `grabber.py`, and `main.py`.
    - [ ] **Series Matching**: Move `find_series_match` (from `grabber.py`) and matching logic from `matcher.py` and `main.py` (show command) into a robust central search function in `analysis.py`.
    - [ ] **Range Formatting**: Merge `vibe_format_range` (from `grabber.py`) into `analysis.format_ranges` to support optional prefixes and padding centrally.
    - [x] **Filename Sanitization**: Extract filename sanitization logic (e.g., replacing `|` with `｜`) from `grabber.py` into a reusable function.
    - [ ] **Consolidation Logic**: Move `consolidate_entries` from `matcher.py` to `analysis.py` to keep all data processing logic in one place.

### Documentation
- [x] Comprehensive README
- [ ] API documentation (Sphinx)
- [ ] Contributing guidelines
- [ ] Example configurations
- [ ] Video tutorials

### Packaging
- [ ] PyPI package distribution
- [ ] Docker container
- [ ] Standalone executables (PyInstaller)
- [ ] Homebrew formula (macOS)
- [ ] AUR package (Arch Linux)

## Version History

### v4.0 (Recent)
- AI Integration (Remote/Local backends)
- Smart Categorization command
- Metadata Enrichment command
- Filename Sanitization utility

### v3.0
- Grabbing functionality
- Pulling functionality
- Parallelization of matching

## Contributing

See [README.md](README.md) for contribution guidelines.

Priority areas for contributions:
1. **Testing**: Unit and integration tests
2. **Documentation**: Examples and tutorials
3. **Features**: Items marked as "Help Wanted" in issues
4. **Bug Fixes**: Check GitHub issues

## Notes

- Maintain backward compatibility where possible
- Follow existing code style and conventions
- All new features must include logging and type hints
- Update README.md when adding user-facing features
- Performance considerations for libraries with 10,000+ series