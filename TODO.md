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
- [ ] **Configuration File**:
    - YAML/TOML config instead of just .env
    - Per-directory settings
    - Custom naming patterns

### 4. Advanced Features
- [ ] **Metadata Integration**:
    - Fetch from MangaUpdates, AniList, MyAnimeList
    - Store series descriptions, ratings, status
    - Auto-match series by name
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
- [ ] **Bulk Operations**:
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

## Technical Improvements

### Code Quality
- [ ] Add unit tests (pytest)
- [ ] Add integration tests
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Code coverage reporting
- [ ] Pre-commit hooks (black, flake8, mypy)

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

### v2.0 (Current)
- Smart caching with TTL
- Comprehensive logging system
- Full type hints coverage
- Constants extraction
- Performance optimizations

### v1.0 (Initial Release)
- Core scanning functionality
- Stats, tree, show, dedupe, scrape, match commands
- Archive inspection and verification
- Gap detection algorithm
- Duplicate finder with fuzzy matching

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