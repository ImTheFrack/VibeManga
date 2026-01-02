### 📋 Phase 2, Step 1: CLI Modularization Plan

THIS IS STEP 1, PHASE 2 of the REFACTORING_REPORT.md.

### Scope & Objective

Break down the 2,790-line main.py monolith into 13 focused CLI command modules plus a base module for shared
functionality. Target: Reduce main.py to ~400 lines (85% reduction).

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

### Command Inventory

Based on analysis of main.py, here are the 13 CLI commands to extract:

│ # │  Command   │Line Count│   Primary Function   │          Dependencies          │
├───┼────────────┼──────────┼──────────────────────┼────────────────────────────────┤
│1  │metadata    │~180 lines│Fetch MAL metadata    │scanner, metadata, cache, ai_api│
│2  │hydrate     │~120 lines│Ensure MAL IDs exist  │scanner, metadata, cache        │
│3  │rename      │~270 lines│Standardize names     │scanner, cache, renamer, matcher│
│4  │categorize  │~360 lines│AI-powered sorting    │scanner, cache, categorizer     │
│5  │stats       │~460 lines│Library statistics    │scanner, cache, analysis        │
│6  │tree        │~120 lines│Visualize hierarchy   │scanner, cache                  │
│7  │show        │~200 lines│Display series details│scanner, cache                  │
│8  │dedupe      │~170 lines│Find duplicates       │scanner, cache, analysis        │
│9  │scrape      │~110 lines│Scrape Nyaa.si        │nyaa_scraper                    │
│10 │match       │~30 lines │Match torrents        │matcher                         │
│11 │grab        │~20 lines │Add torrents          │grabber                         │
│12 │pull        │~10 lines │Process downloads     │grabber                         │
│13 │pullcomplete│~70 lines │Full update cycle     │Invokes other commands          │

Total: ~2,120 lines of command logic (plus ~670 lines of shared utilities)

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

### New Directory Structure

vibe_manga/
├── vibe_manga/
│   ├── cli/                      # NEW: CLI command modules
│   │   ├── __init__.py          # CLI group setup
│   │   ├── base.py              # Shared CLI utilities (150 lines)
│   │   ├── metadata.py          # metadata command (~180 lines)
│   │   ├── hydrate.py           # hydrate command (~120 lines)
│   │   ├── rename.py            # rename command (~270 lines)
│   │   ├── categorize.py        # categorize command (~360 lines)
│   │   ├── stats.py             # stats command (~460 lines)
│   │   ├── tree.py              # tree command (~120 lines)
│   │   ├── show.py              # show command (~200 lines)
│   │   ├── dedupe.py            # dedupe command (~170 lines)
│   │   ├── scrape.py            # scrape command (~110 lines)
│   │   ├── match.py             # match command (~30 lines)
│   │   ├── grab.py              # grab command (~20 lines)
│   │   ├── pull.py              # pull command (~10 lines)
│   │   └── pullcomplete.py      # pullcomplete command (~70 lines)
│   │
│   ├── config/                   # ✅ Phase 1 Complete (see PHASE1_SUMMARY.md if needed)
│   ├── logging.py                # ✅ Phase 1 Complete (see PHASE1_SUMMARY.md if needed)
│   │
│   └── main.py                   # REFACTORED: ~400 lines (was 2,790)
│       ├── CLI group import
│       ├── Command module imports
│         └── cli() entry point

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

### Implementation Strategy

## Phase A: Foundation - Create CLI Package Structure

File: vibe_manga/vibe_manga/cli/__init__.py
	"""
	VibeManga CLI Command Package
	
	This package contains all CLI command modules, each focused on a single command.
	Commands are registered in main.py via imports.
	"""
	
	# This file intentionally minimal - commands registered in main.py
	
	File: vibe_manga/vibe_manga/cli/base.py
	"""
	Shared CLI utilities and base functionality.
	
	Extract common patterns from main.py to reduce duplication.
	"""
	from pathlib import Path
	from rich.console import Console
	from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
	from typing import Optional
	
	from ..scanner import scan_library
	from ..cache import get_cached_library, save_library_cache
	from ..models import Library
	
	console = Console()
	
	def get_library_root() -> Path:
		"""Get library root from configuration."""
		from ..config import get_config
		config = get_config()
		return config.library_path
	
	def run_scan_with_progress(
		root_path: Path,
		description: str,
		use_cache: bool = True,
		cache_max_age: int = 300
	) -> Library:
		"""
		Scan library with standardized progress display.
	
		Args:
			root_path: Library root directory
			description: Progress bar description
			use_cache: Whether to use cached results
			cache_max_age: Maximum cache age in seconds
	
		Returns:
			Scanned Library object
		"""
		if use_cache:
			cached = get_cached_library(root_path, max_age=cache_max_age)
			if cached:
				console.print(f"[dim]Using cached library data[/dim]")
				return cached
	
		progress = Progress(
			SpinnerColumn(),
			"[progress.description]{task.description}",
			BarColumn(),
			"[progress.percentage]{task.percentage:>3.0f}%",
			TimeRemainingColumn(),
			console=console,
			refresh_per_second=10
		)
	
		with progress:
			task = progress.add_task(description, total=None)
			library = scan_library(root_path)
			progress.update(task, completed=100)
	
		save_library_cache(library)
		return library
	
	# Add other shared utilities:
	# - create_progress()
	# - display_error()
	# - confirm_action()
	# - parse_query()
	# - etc.

## Phase B: Command Extraction - Extract commands in dependency order (least dependent first)

# Priority 1: Standalone Commands (no complex UI, few dependencies)

A. scrape.py - Easiest
- Lines: ~110
- Dependencies: nyaa_scraper only
- Complexity: Low (simple progress, no table output)
- Strategy: Direct extraction with minimal changes

B. match.py - Very Simple
- Lines: ~30
- Dependencies: matcher
- Complexity: Very Low (thin wrapper)

C. grab.py - Very Simple
- Lines: ~20
- Dependencies: grabber
- Complexity: Very Low (thin wrapper)

D. pull.py - Very Simple
- Lines: ~10
- Dependencies: grabber
- Complexity: Very Low (thin wrapper)

E. pullcomplete.py - Simple Orchestrator
- Lines: ~70
- Dependencies: Invokes other commands via Click context
- Complexity: Low (orchestration only)
- Note: Must be extracted LAST since it depends on other commands

Process for each:
1. Copy function body to new file
2. Add imports (use relative imports: from ..scanner import ...)
3. Add Click decorator
4. Update main.py to import and register
5. Test immediately

# Priority 2: Analysis/Display Commands (moderate UI, standard patterns)

A. tree.py - Standard Display
- Lines: ~120
- Dependencies: scanner, cache, rich.tree
- Complexity: Medium (Tree UI, but straightforward)
- Key patterns: Progress bar, Tree building

B. show.py - Standard Display
- Lines: ~200
- Dependencies: scanner, cache, rich.table
- Complexity: Medium (Table UI, detail view)

C. dedupe.py - Analysis Command
- Lines: ~170
- Dependencies: scanner, cache, analysis
- Complexity: Medium (Table output, filtering)

D. stats.py - Complex Display
- Lines: ~460 (largest)
- Dependencies: scanner, cache, analysis
- Complexity: High (multiple tables, deep analysis option)
- Strategy: Extract LAST in this group due to size

Process for each:
1. Identify shared table/progress patterns → move to base.py
2. Extract command function
3. Refactor to use base.run_scan_with_progress()
4. Test with various options
5. Verify output matches original exactly

# Priority 3: Interactive/AI Commands (complex UI, multiple dependencies)

A. hydrate.py - Metadata Hydration
- Lines: ~120
- Dependencies: scanner, metadata, cache
- Complexity: Medium (progress, parallel processing)
- Note: Similar to metadata but simpler

B. metadata.py - Metadata Enrichment
- Lines: ~180
- Dependencies: scanner, metadata, cache, ai_api
- Complexity: High (parallel threads, table updates, AI usage reporting)
- Key features: ThreadPoolExecutor, live table updates, token tracking

C. rename.py - Interactive Renaming
- Lines: ~270
- Dependencies: scanner, cache, renamer, matcher
- Complexity: High (interactive UI, safety levels, collision detection)
- Key features: Rich interactive UI, vim-style controls, rename planning

D. categorize.py - AI Categorization
- Lines: ~360 (largest)
- Dependencies: scanner, cache, categorizer, ai_api
- Complexity: Very High (AI council, interactive UI, newroot mode)
- Key features: Multi-agent AI, progress tracking, copy/move modes

Process for each:
1. Extract command function
2. Refactor to use shared base.py utilities
3. Extract complex UI logic to helper functions
4. Add comprehensive tests for interactive paths
5. Test both interactive and auto modes

### Testing Strategy
Unit Tests for Each Command

Create test file: tests/cli/test_commands.py

	"""
	Test CLI command modules.
	"""
	import pytest
	from pathlib import Path
	from click.testing import CliRunner
	from vibe_manga.vibe_manga.cli import metadata, hydrate, rename, categorize

	@pytest.fixture
	def runner():
		return CliRunner()

	@pytest.fixture
	def sample_library(tmp_path):
		"""Create minimal sample library structure."""
		# Create test library
		...

	class TestMetadataCommand:
		def test_metadata_query(self, runner, sample_library, monkeypatch):
			"""Test metadata command with query."""
			# Mock dependencies
			monkeypatch.setattr("vibe_manga.vibe_manga.cli.metadata.get_library_root",
							  lambda: sample_library)

			result = runner.invoke(metadata.cli, ["--query", "Test Series"])
			assert result.exit_code == 0
			assert "Processing metadata" in result.output

		def test_metadata_all(self, runner, sample_library, monkeypatch):
			"""Test metadata command with --all flag."""
			monkeypatch.setattr("vibe_manga.vibe_manga.cli.metadata.get_library_root",
							  lambda: sample_library)

			result = runner.invoke(metadata.cli, ["--all"])
			assert result.exit_code == 0
			assert "series to process" in result.output

	# Similar tests for each command...

Test Coverage Goals:
- ✅ Each command: 2-3 basic tests
- ✅ Focus on: exit codes, output contains expected text
- ✅ Mock external dependencies (API calls, file I/O)
- Target: 50% coverage for CLI layer

### Integration Tests

Create: tests/integration/test_cli_workflows.py

	"""
	Integration tests for complete CLI workflows.
	"""
	import pytest
	from pathlib import Path
	from click.testing import CliRunner
	from vibe_manga.vibe_manga.main import cli

	def test_metadata_to_rename_workflow(tmp_path, sample_library):
		"""
		Test complete workflow: scan → metadata → rename
		"""
		runner = CliRunner()

		# Step 1: Run metadata
		result = runner.invoke(cli, [
			"metadata", "--all",
			"--library-path", str(sample_library)
		])
		assert result.exit_code == 0

		# Step 2: Run rename (simulate)
		result = runner.invoke(cli, [
			"rename", "--all", "--simulate",
			"--library-path", str(sample_library)
		])
		assert result.exit_code == 0
		assert "Would rename" in result.output

Integration Test Scenarios:
1. Metadata → Rename workflow
2. Scrape → Match → Grab workflow
3. Pull → Stats → Metadata → Categorize workflow
4. Full pullcomplete cycle

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

###  Verification Checklist

# Before Starting
- [X] All Phase 1 tests passing (14/14)
- [X] Backup current main.py

# After All Commands Extracted
- [ ] main.py reduced to ~400 lines
- [ ] All 13 commands registered in main.py
- [ ] No code duplication in command modules
- [ ] All unit tests passing (target: 30+ tests)
- [ ] All integration tests passing (target: 5-7 scenarios)
- [ ] Manual end-to-end test: Full workflow
- [ ] Code coverage report generated
- [ ] No regression in functionality

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

### Deliverables:
- All 13 command modules extracted
- cli/base.py with shared utilities
- 30+ unit tests, 5+ integration tests
- main.py reduced to ~400 lines
- Documentation updated (GEMINI.MD, TODO.MD, README.MD, etc.)

### NOTES REGARDING RISK MITIGATION

## Risk 1: Command Dependencies
Some commands depend on others (e.g., pullcomplete invokes pull, metadata, categorize)

# Mitigation:
- Extract leaf commands first (no dependencies)
- Extract pullcomplete LAST
- Use Click's ctx.invoke() pattern (already works)
- Test orchestration commands thoroughly

## Risk 2: Shared State
console, logger, config are currently module-level in main.py

# Mitigation:
- Move to cli/base.py as shared instances
- Use lazy initialization pattern
- Ensure thread safety for parallel commands

## Risk 3: Interactive UI Complexity
rename and categorize have complex interactive UIs

# Mitigation:
- Extract UI logic to separate helper functions
- Test interactive paths manually
- Add --auto mode tests for automation
- Keep UI code in command module (not base)

## Performance Regression
Problem: Additional module imports might slow startup

# Mitigation:
- Use lazy imports in command modules
- Profile import times
- Keep base.py lightweight
- Cache imports where possible

### Best Practices -Code Organization
## Good: Clear separation

# vibe_manga/cli/metadata.py
	from ..base import console, run_scan_with_progress, get_library_root
	from ..metadata import get_or_create_metadata
	from ..cache import save_library_cache

	@click.command()
	@click.option(...)
	def metadata(...):
		"""Clear docstring."""
		# Command logic only - no UI framework code mixed in

## Bad: Mixed concerns
	def metadata(...):
		# UI setup
		# Business logic
		# More UI code
		# Error handling
		# More business logic

## Import Strategy
	# Use relative imports for internal modules
	from ..scanner import scan_library
	from ..models import Library
	from ..config import get_config

	# Use absolute imports for external packages
	import click
	from rich.console import Console

	Error Handling
	# Consistent error handling pattern
	try:
		result = some_operation()
	except SpecificError as e:
		logger.error(f"Operation failed: {e}")
		console.print(f"[red]Error: {e}[/red]")
		raise click.Abort()

### Success Metrics

Code Quality
- [ ] main.py: 2,790 → ~400 lines (85% reduction)
- [ ] New CLI modules: 13 files, ~1,800 lines total
- [ ] Code duplication: 25% → 17% (30% reduction)
- [ ] Average function size: 150 lines → 40 lines

### 🔄 Rollback Plan

If critical issues arise:

1. Keep main.py backup during entire Phase 2
2. Feature flag approach: Can toggle between old/new structure
3. Staged rollout: Deploy 3-4 commands at a time
4. Version tagging: Tag releases before each major extraction
5. Quick rollback: Restore main.py from backup if needed

### Detailed Extraction Template

For each command, follow this template:

1. Create Command File

File: vibe_manga/vibe_manga/cli/<command>.py
"""
<Command Name> command for VibeManga CLI.

<Description of what the command does>
"""
import click
from rich.console import Console
from typing import Optional

from ..base import console, run_scan_with_progress, get_library_root
from ..scanner import scan_library
from ..cache import save_library_cache
# ... other imports

@click.command()
@click.option("--option1", help="Description")
@click.option("--option2", is_flag=True, help="Flag description")
def <command>(option1: Optional[str], option2: bool) -> None:
    """
    <Detailed command description>
    """
    # Command implementation
    # Copy from main.py with minimal changes

2. Update main.py

# At top of main.py
from .cli.metadata import metadata
from .cli.hydrate import hydrate
from .cli.rename import rename
# ... import all commands

# Keep CLI group definition
@click.group()
def cli():
    """VibeManga: A CLI for managing your manga collection."""
    pass

# Commands are automatically registered via imports
# No need to manually add to cli group!

3. Add Unit Tests

File: tests/cli/test_<command>.py
"""
Tests for <command> CLI command.
"""
import pytest
from click.testing import CliRunner
from vibe_manga.vibe_manga.cli.<command> import <command>

def test_<command>_help():
    """Test command shows help."""
    runner = CliRunner()
    result = runner.invoke(<command>, ["--help"])
    assert result.exit_code == 0
    assert "Description" in result.output

def test_<command>_basic(runner, sample_library, monkeypatch):
    """Test basic command execution."""
    # Mock dependencies
    monkeypatch.setattr("vibe_manga.vibe_manga.cli.<command>.get_library_root",
                      lambda: sample_library)

    result = runner.invoke(<command>, ["--option"])
    assert result.exit_code == 0

4. Manual Verification

Run these commands for each extracted module:

# 1. Help text
python -m vibe_manga.vibe_manga.main <command> --help

# 2. Dry run (if available)
python -m vibe_manga.vibe_manga.main <command> --simulate

# 3. Real execution (on test data)
python -m vibe_manga.vibe_manga.main <command> [typical arguments]

# 4. Compare output with original main.py
# (Run both versions and diff the output)

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

🎯 Next Steps

Immediate Actions:
1. ✅ Review and approve this plan
2. ✅ Create feature branch: git checkout -b phase2-cli-modularization
3. ✅ Implement cli/ package structure (Step 1.1)
4. ✅ Start with simple commands: scrape, match, grab, pull

Week 1 Deliverables:
- [ ] cli/ package created with base.py
- [ ] 4 simple commands extracted and tested
- [ ] 5-10 unit tests passing
- [ ] main.py reduced by ~500 lines

Success Criteria:
- All existing functionality preserved
- No regression in output or behavior
- Improved code organization
- Foundation for Phase 2, Step 2 (API base classes)

―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――

This plan provides a clear, actionable roadmap for breaking down the monolithic main.py into focused, maintainable
CLI modules while preserving all existing functionality and establishing a foundation for continued refactoring.