# Pullcomplete Verbosity Enhancement Plan (Revised for Centralized Logging)

## Objective
Enhance the `pullcomplete` command with a clean, hierarchical verbosity system that integrates seamlessly with the existing centralized logging infrastructure in `vibe_manga.logging`, providing visibility into each step of the full update cycle without creating information overload.

## Implementation Plan

### Phase 1: Core Infrastructure (Centralized Logging Integration)

- [ ] **Add `--verbose` flag to pullcomplete command**
  - Add click option with count=True to support multiple levels (-v, -vv)
  - Map verbosity levels to logging levels: 0=WARNING (default), 1=INFO, 2=DEBUG
  - Use `vibe_manga.logging.set_log_level()` to control console output
  - Pass verbosity context to all sub-command invocations using `temporary_log_level()`

- [ ] **Extend vibe_manga.logging module with verbose utilities**
  - Add `log_step()` function that uses Rich panels for major step announcements
  - Add `log_substep()` function for indented sub-step details
  - Add `log_api_call()` function for API request/response logging with sanitization
  - All functions must use the existing `get_logger()` infrastructure
  - Ensure all verbose output goes through the centralized `RichHandler`

- [ ] **Create verbosity context manager in logging.py**
  - Extend `temporary_log_level()` to support verbosity level mapping
  - Add `verbose_context()` that automatically adjusts both console and file logging
  - Ensure context manager restores original levels even on exceptions

### Phase 2: Step 1 - Pull Command Verbosity (via Centralized Logging)

- [ ] **Enhance pull command to use centralized logging**
  - Import `from vibe_manga.logging import get_logger, log_substep`
  - Replace print statements with `logger.info()` and `log_substep()` calls
  - Show torrents being processed with names and statuses via logging
  - Display post-processing actions (file moves, renames) using `log_substep()`
  - Log completion summary with counts via `logger.info()`
  - In debug mode: use `log_api_call()` for qBittorrent API requests (with key masking)

- [ ] **Update process_pull() in grabber.py to use centralized logger**
  - Import `from vibe_manga.logging import get_logger`
  - Add verbosity parameter
  - Use `with temporary_log_level():` for sub-operation logging
  - All logging goes through centralized system (file + console)

### Phase 3: Step 2 - Cache Refresh Verbosity

- [ ] **Enhance cache refresh step with centralized logging**
  - Use `log_step()` to announce cache refresh
  - Show number of series found using `logger.info()`
  - Display incremental progress with series names via `log_substep()`
  - Log cache hit/miss information through centralized logger
  - Show time taken using `logger.info()` with timing context

- [ ] **Update run_scan_with_progress() in base.py**
  - Add verbosity parameter
  - Use `log_substep()` for series name updates in verbose mode
  - Log directory traversal details using `logger.debug()`
  - Show cache save/load operations via `logger.info()`

### Phase 4: Step 3 - Metadata Update Verbosity

- [ ] **Enhance metadata command to respect centralized logging**
  - Ensure metadata.py already uses `get_logger()` from vibe_manga.logging
  - Show number of series being processed via `logger.info()`
  - Display per-series metadata source using `log_substep()`
  - Log AI model usage and token counts via `logger.info()`
  - Use `temporary_log_level()` when invoking metadata subprocess

- [ ] **Verify metadata.py integration**
  - Confirm it imports `from vibe_manga.logging import get_logger`
  - Ensure all console output uses Rich through centralized handler
  - Add `verbose` parameter to metadata command options

### Phase 5: Step 4 - Categorize Verbosity

- [ ] **Enhance categorize command with centralized logging**
  - Use `log_step()` for AI council configuration display
  - Show series being categorized with `log_substep()`
  - Display AI council decisions via Rich panels through logger
  - Log file move/copy operations using `log_substep()`
  - Show moderation flags via `logger.warning()`

- [ ] **Update categorize.py to use centralized logger**
  - Import from vibe_manga.logging
  - Replace direct console.print with logging when appropriate
  - Use `temporary_log_level()` for sub-operations

### Phase 6: Step 5 - Replenish Queue Verbosity

- [ ] **Enhance queue replenishment with centralized logging**
  - Use `log_step()` to announce replenishment check
  - Show current queue count vs limit via `logger.info()`
  - Display needed torrents calculation
  - Log each sub-step (scrape, match, grab) with `log_substep()`

- [ ] **Enhance scrape, match, grab subprocesses**
  - Each must use `with temporary_log_level(level):` when invoked
  - Pass verbosity level through ctx.invoke()
  - All use centralized logging infrastructure
  - Show API requests via `log_api_call()` in debug mode

### Phase 7: Step 6 - Final Stats Verbosity

- [ ] **Enhance final stats with centralized logging**
  - Use `log_step()` for final stats announcement
  - Show detailed statistics via `logger.info()`
  - Display category breakdowns using Rich tables through logger
  - Log verification checks if enabled

### Phase 8: Integration and Polish (Centralized Logging)

- [ ] **Create unified verbosity orchestration**
  - Use `with temporary_log_level()` in pullcomplete for each step
  - Ensure all subprocess calls respect parent verbosity
  - Create summary panel using `log_step()` at completion

- [ ] **Add timing information via centralized logger**
  - Use `logger.info()` with timing context for each step
  - Display total execution time via `log_step()`
  - Log performance metrics using `logger.debug()`

- [ ] **Security considerations for centralized logging**
  - Ensure `log_api_call()` sanitizes sensitive data (API keys, tokens)
  - Mask credentials in debug output
  - Add warnings when debug mode is enabled

## Verification Criteria

- [ ] Default behavior unchanged (console shows WARNING+, file shows INFO+)
- [ ] `-v` maps to INFO level, shows sub-step details via centralized logger
- [ ] `-vv` maps to DEBUG level, shows API calls via `log_api_call()`
- [ ] All output flows through `vibe_manga.logging.RichHandler`
- [ ] Log file contains full verbose output at appropriate levels
- [ ] No duplicate log entries (handlers properly managed)
- [ ] API keys and sensitive data masked in debug output
- [ ] All existing tests pass with logging changes

## Potential Risks and Mitigations

1. **Logging Performance**: Verbose logging could slow down processing
   - Mitigation: Use existing logger's efficient formatting, lazy evaluation for debug

2. **Handler Duplication**: Multiple imports could create duplicate handlers
   - Mitigation: Centralized setup in vibe_manga.logging ensures single handler instance

3. **Sensitive Data Exposure**: Debug mode might log credentials
   - Mitigation: `log_api_call()` must sanitize all sensitive data, use regex masking

4. **Backward Compatibility**: Existing direct logger usage might break
   - Mitigation: Maintain compatibility layer, ensure get_logger() returns standard logger

## Explicit Centralized Logging Integration Points

### In pullcomplete.py:
```python
from vibe_manga.logging import get_logger, set_log_level, temporary_log_level

logger = get_logger(__name__)

@click.option("-v", "--verbose", count=True)
def pullcomplete(ctx, verbose):
    if verbose:
        set_log_level(logging.DEBUG if verbose >= 2 else logging.INFO, "console")
```

### In each sub-command (pull.py, metadata.py, etc.):
```python
from vibe_manga.logging import get_logger, log_substep

logger = get_logger(__name__)

# Use logger instead of print/console.print for verbose output
logger.info("Processing torrent")
log_substep(f"Moved {filename} to {destination}")
```

### For subprocess calls:
```python
from vibe_manga.logging import temporary_log_level

with temporary_log_level(logging.DEBUG if verbose >= 2 else logging.INFO):
    ctx.invoke(metadata, ...)
```

## Alternative Approaches (with centralized logging considerations)

1. **Direct Rich Output**: Bypass centralized logger for visual elements
   - Pros: More control over Rich formatting
   - Cons: Bypasses file logging, inconsistent with centralized approach
   - Decision: Use centralized logger for everything, extend it with Rich support

2. **Separate Verbose Logger**: Create new logger instance for verbose output
   - Pros: Isolated from main logging
   - Cons: Duplicates infrastructure, doesn't integrate with existing system
   - Decision: Extend existing VibeMangaLogger with verbose capabilities

3. **Mix Logging and Direct Output**: Use logging for file, direct Rich for console
   - Pros: Maximum flexibility
   - Cons: Inconsistent, harder to maintain
   - Decision: All output through centralized system