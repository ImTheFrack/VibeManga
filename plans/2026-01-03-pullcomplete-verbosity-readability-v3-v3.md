# Pullcomplete Verbosity Enhancement Plan (Updated for Readability Improvements)

## Objective
Enhance the `pullcomplete` command's verbosity system to provide clear visual hierarchy, colorful highlights for important information (especially new series), and explicit location tracking throughout the post-processing workflow. The goal is to make the output easy to scan and understand at a glance, even when processing many torrents.

## Current Implementation Status

### Completed ✓
- Core `--verbose` flag infrastructure with count support (-v, -vv)
- Centralized logging module with `log_step()`, `log_substep()`, `log_api_call()`
- `temporary_log_level()` context manager for subprocess orchestration
- Pull command integration with centralized logging
- Pullcomplete orchestration using step-based logging
- Basic debug logging throughout grabber.py

### Issues Identified ✗
- **Iteration Separation**: No clear visual boundaries between torrent processing iterations
- **Colorful Highlights**: Limited use of Rich markup for different information types (new series, file moves, etc.)
- **Location Tracking**: File paths and destinations are logged but not prominently highlighted
- **Readability**: Dense output that's hard to scan, especially with multiple torrents

## Implementation Plan

### Phase 1: Enhanced Visual Hierarchy in Pull Processing

- [ ] **Add iteration separators in `grabber.py:process_pull()`**
  - Add `log_step()` call at the start of each torrent iteration (line ~892)
  - Use distinct Rich panel styling with series name prominently displayed
  - Include iteration counter (e.g., "[1/15] Processing: Series Name")
  - Add visual separator (Rule) between iterations for clean log parsing

- [ ] **Implement color-coded status indicators in grabber.py**
  - Create helper function `log_status(message, status_type)` in logging.py
  - Status types: "new_series", "existing_series", "upgrade", "duplicate"
  - Each type gets distinct Rich styling (colors, icons, bold/italic)
  - Replace plain log_substep calls with contextual status logging

- [ ] **Enhance location logging with prominent highlighting**
  - Wrap all path/location logs with `[bold cyan]` or `[bold magenta]` markup
  - Add prefix icons: "📁" for directories, "📄" for files
  - Ensure every file move/copy operation shows BEFORE and AFTER paths
  - Use `log_substep()` for all location changes with consistent formatting

### Phase 2: New Series Detection and Highlighting

- [ ] **Create `log_new_series()` function in logging.py**
  - Dedicated function for new series discovery
  - Uses vibrant green/magenta panel with celebration emoji
  - Logs to file as INFO, console as styled panel
  - Include series name and initial file count

- [ ] **Update grabber.py new series detection (line ~1054)**
  - Replace generic log_substep with `log_new_series()` call
  - Add additional context: file count, total size, first volume numbers
  - Highlight the "Uncategorized" destination path prominently

- [ ] **Add series type indicators throughout processing**
  - Track if series is manga/light novel/single file
  - Display type badge in iteration header
  - Use different icons/emojis for different content types

### Phase 3: File Operation Transparency

- [ ] **Implement `log_file_operation()` helper in logging.py**
  - Parameters: operation (copy/move), source, destination, status
  - Consistent formatting: "{icon} {operation}: {src} → {dst}"
  - Color coding: green=success, yellow=warning, red=error
  - Use in staging, importing, and cleanup steps

- [ ] **Enhance staging step logging (grabber.py ~1081-1106)**
  - Log temp directory path with visual prominence
  - Show progress with current file counter and filename
  - Add summary: "Staged N files to {temp_dir}"
  - Debug mode: list every file copied with full paths

- [ ] **Enhance import step logging (grabber.py ~1207-1241)**
  - Log final destination library path with bold styling
  - Show subfolder structure if created (volumes/chapters separation)
  - Display overwrite warnings with red highlighting
  - Summary: "Imported N files to {library_path}"

### Phase 4: Processing Step Clarity

- [ ] **Add step numbering within each iteration**
  - Number the 8 processing steps clearly: "[Step 4/8] Analyzing content..."
  - Use consistent prefix: "[Step N/8]" for easy scanning
  - Ensure step numbers align with comments in code
  - Log step transitions for debug mode

- [ ] **Create processing summary panel at iteration end**
  - Show what was done: files staged, imported, cleaned up
  - Highlight key outcomes: new volumes added, gaps filled
  - Use Rich table format for multi-line summaries
  - Only shown at INFO level and above

- [ ] **Improve error visibility and confirmation prompts**
  - Errors should use red panels with `[bold red]` text
  - Warnings use yellow/orange styling
  - Confirmation prompts clearly state what's about to happen
  - Add "skipping" messages with dim styling for filtered files

### Phase 5: Pullcomplete Orchestration Enhancements

- [ ] **Add per-step timing information**
  - Track start/end time for each of the 6 main steps
  - Log duration using `log_substep()` after each step
  - Show total execution time in final summary panel
  - Debug mode: log timing for substeps within pull processing

- [ ] **Enhance queue replenishment logging**
  - Current: basic print statements for scrape/match/grab
  - Replace with proper `log_step()` calls
  - Show number of torrents added in replenishment
  - Highlight when queue is full (yellow warning)

- [ ] **Add final summary with statistics**
  - Create comprehensive final panel showing:
    - Torrents processed successfully
    - New series added
    - Files imported
    - Total time taken
    - Any errors/warnings encountered
  - Use Rich table format for multi-column layout

### Phase 6: Advanced Debug Mode Features (-vv)

- [ ] **Implement `log_debug_detail()` for granular tracing**
  - Only active at DEBUG level
  - Shows internal decision logic: why files are skipped, how matching works
  - Include variable values and calculation results
  - Use `[dim]` styling to avoid cluttering main output

- [ ] **Add API call logging with request/response details**
  - Use existing `log_api_call()` but enhance formatting
  - Show qBittorrent API endpoints and response times
  - Mask sensitive data (auth tokens, etc.)
  - Group related API calls visually

- [ ] **Debug file analysis details**
  - Log filename parsing results: extracted volumes, chapters
  - Show fuzzy matching scores and candidate lists
  - Display library index search results
  - Help diagnose why a series didn't match

## Specific Code Locations for Changes

### `vibe_manga/logging.py`
- Add `log_status(message, status_type)` function
- Add `log_new_series(series_name, details)` function  
- Add `log_file_operation(op, src, dst, status)` function
- Add `log_debug_detail(message)` function
- Enhance `log_step()` to support custom styling parameters

### `vibe_manga/grabber.py`
- Line ~892: Add iteration header with `log_step()`
- Line ~919: Enhance path logging with bold cyan styling
- Line ~1054: Replace with `log_new_series()` call
- Line ~1081-1106: Enhance staging logging with file operations
- Line ~1207-1241: Enhance import logging with destinations
- Line ~1335: Add final summary panel

### `vibe_manga/cli/pullcomplete.py`
- Add timing tracking around each step
- Enhance queue replenishment logging (lines ~109-119)
- Create final summary panel with statistics

## Verification Criteria

- [ ] Each torrent iteration has clear visual separation with header panel
- [ ] New series are highlighted with vibrant green/magenta styling and emoji
- [ ] All file paths use consistent `[bold cyan]` or `[bold magenta]` highlighting
- [ ] File operations show source → destination with arrow notation
- [ ] Processing steps within each iteration are numbered (1-8)
- [ ] Each iteration ends with a summary of what was done
- [ ] Pullcomplete shows timing for each of the 6 main steps
- [ ] Final summary panel displays comprehensive statistics
- [ ] Debug mode (-vv) shows internal decision logic without cluttering INFO output
- [ ] No duplicate log entries or handler issues
- [ ] All existing functionality preserved (simulate, pause modes work correctly)

## Alternative Approaches Considered

1. **Direct Rich Console Output**: Bypass logging for visual elements
   - Rejected: Would break centralized logging architecture and file logging

2. **Separate UI Logger**: Create dedicated logger for user-facing output
   - Rejected: Adds complexity, current system can be extended instead

3. **Minimal Changes**: Only add iteration separators
   - Rejected: Doesn't address the core readability issues comprehensively

## Risk Assessment

1. **Performance**: Rich markup processing could slow down batch operations
   - Mitigation: Use lazy string evaluation, only format when log level allows

2. **Log File Clutter**: Rich markup tags in file logs
   - Mitigation: Strip markup tags in file handler or use separate formatting

3. **Visual Overwhelm**: Too many colors/panels could reduce clarity
   - Mitigation: Use consistent, limited color palette; panels only for major steps

4. **Backward Compatibility**: Scripts parsing log output may break
   - Mitigation: Document as breaking change; provide plaintext mode option