"""
Dedupe command for VibeManga CLI - Interactive Duplicate Resolution.

Provides comprehensive duplicate detection and resolution workflow:
1. MAL ID Conflicts - Same MAL ID in different folders
2. Content Duplicates - Same files via hashing/metadata
3. Fuzzy Duplicates - Similar names with AI assistance
"""

import click
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List

from rich.table import Table

from .base import console, get_library_root, run_scan_with_progress, perform_deep_analysis
from ..dedupe_engine import DedupeEngine, DuplicateGroup
from ..dedupe_resolver import DuplicateResolver, ResolutionPlan, ResolutionAction
from ..dedupe_actions import ActionExecutor
from ..logging import get_logger, set_log_level

logger = get_logger(__name__)


@click.command()
@click.argument("query", required=False)
@click.option("--verbose", "-v", count=True, help="Increase verbosity (-v: INFO, -vv: DEBUG).")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts) before deduping.")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow) before deduping.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
@click.option("--structural-only", is_flag=True, help="Only check for structural duplicates (deprecated, use --mode fuzzy).")
@click.option("--mode", "-m", type=click.Choice(['all', 'mal-id', 'content', 'fuzzy'], case_sensitive=False), default='all', help="Detection mode: all, mal-id, content, or fuzzy.")
@click.option("--hashing", is_flag=True, help="Use file hashing for content duplicates (slow but accurate).")
@click.option("--auto", is_flag=True, help="Auto-resolve simple cases (same MAL ID, clear supersets).")
@click.option("--simulate", is_flag=True, help="Preview changes without executing them.")
@click.option("--report", type=click.Path(), help="Save detailed report to JSON file.")
@click.option("--whitelist", type=click.Path(), help="Path to whitelist file (default: vibe_manga_duplicate_whitelist.json).")
def dedupe(
    query: Optional[str],
    verbose: int,
    deep: bool,
    verify: bool,
    no_cache: bool,
    structural_only: bool,
    mode: str,
    hashing: bool,
    auto: bool,
    simulate: bool,
    report: Optional[str],
    whitelist: Optional[str]
) -> None:
    """
    Interactive duplicate detection and resolution for manga library.
    
    If QUERY is provided, only matching series are checked.
    Otherwise, the whole library is scanned.
    
    Detection modes:
    - mal-id: Detect series with same MAL ID (highest confidence)
    - content: Detect duplicate files by size/hash (medium confidence)  
    - fuzzy: Detect series with similar names (lower confidence)
    - all: Run all detection modes (recommended)
    
    During interactive resolution, you can use:
    - [I]nspect: Deep dive into file details and quality
    - [V]erify: Check file integrity and completeness
    - [C]ompare: Show detailed side-by-side comparison
    - [M]erge: Move files from one series to another
    - [D]elete: Remove duplicate series/files
    - [K]eep both: Mark as intentional duplicate (whitelist)
    - [S]kip: Leave unchanged and move to next
    """
    # Set global verbosity based on flag
    log_level = logging.WARNING
    clean_logs = False
    if verbose == 1:
        log_level = logging.INFO
        clean_logs = True
    elif verbose >= 2:
        log_level = logging.DEBUG
        clean_logs = False
        
    set_log_level(log_level, "console", clean=clean_logs)

    if structural_only:
        console.print("[yellow]Warning: --structural-only is deprecated, use --mode fuzzy instead[/yellow]")
        mode = 'fuzzy'
    
    logger.info(f"Dedupe command started (mode={mode}, query={query}, auto={auto}, simulate={simulate})")
    
    # Initialize
    root_path = get_library_root()
    scan_desc = f"[bold green]Scanning library{f' for {query}' if query else ''}...[/bold green]"
    
    # Run scan
    library = run_scan_with_progress(root_path, scan_desc, use_cache=not no_cache)
    
    # Optional deep analysis
    if (deep or verify):
        targets = []
        with console.status("[bold blue]Filtering targets for deep analysis...[/bold blue]"):
            for main_cat in library.categories:
                for sub_cat in main_cat.sub_categories:
                    for series in sub_cat.series:
                        if query and query.lower() not in series.name.lower():
                            continue
                        targets.append(series)
        
        if targets:
            perform_deep_analysis(targets, deep, verify)
    
    # Initialize detection engine
    console.print("\n[bold blue]Initializing duplicate detection...[/bold blue]")
    engine = DedupeEngine(library, use_hashing=hashing)
    
    # Run detection
    console.print(f"[bold]Running {mode} duplicate detection...[/bold]")
    with console.status("[dim]Scanning for duplicates...[/dim]"):
        if mode == 'all':
            all_results = engine.detect_all()
        else:
            all_results = engine.detect_by_mode(mode)
    
    # Filter by query if provided
    if query:
        all_results = _filter_results_by_query(all_results, query)
    
    # Show detection summary
    summary = engine.get_duplicate_summary(all_results)
    _display_detection_summary(summary, all_results, mode)
    
    if summary['total_groups'] == 0:
        console.print("\n[green]✓ No duplicates found![/green]")
        return
    
    # Initialize resolver
    whitelist_path = Path(whitelist) if whitelist else None
    resolver = DuplicateResolver(whitelist_path)
    
    # Process duplicates interactively
    resolution_plans = []
    
    # Process MAL ID conflicts (highest priority)
    if all_results['mal_id_conflicts']:
        console.print("\n[bold red]=== MAL ID Conflicts (Highest Priority) ===[/bold red]")
        for duplicate in all_results['mal_id_conflicts']:
            if auto and _can_auto_resolve_mal_id(duplicate):
                plan = _auto_resolve_mal_id(duplicate)
                if plan:
                    resolution_plans.append(plan)
                    console.print(f"[dim]Auto-resolved MAL ID {duplicate.mal_id}[/dim]")
                    continue
            
            plan = resolver.resolve_mal_id_duplicate(duplicate)
            if plan:
                resolution_plans.append(plan)
    
    # Process content duplicates
    if all_results['content_duplicates']:
        console.print("\n[bold yellow]=== Content Duplicates ===[/bold yellow]")
        for duplicate in all_results['content_duplicates']:
            if auto and len(duplicate.volumes) == 2:
                # Simple case: 2 duplicate files, auto-delete older
                plan = _auto_resolve_content(duplicate)
                if plan:
                    resolution_plans.append(plan)
                    console.print(f"[dim]Auto-resolved content duplicate[/dim]")
                    continue
            
            plan = resolver.resolve_content_duplicate(duplicate)
            if plan:
                resolution_plans.append(plan)
    
    # Process fuzzy duplicates
    if all_results['fuzzy_duplicates']:
        console.print("\n[bold yellow]=== Fuzzy Name Duplicates ===[/bold yellow]")
        for duplicate in all_results['fuzzy_duplicates']:
            plan = resolver.resolve_fuzzy_duplicate(duplicate)
            if plan:
                resolution_plans.append(plan)
    
    # Show resolution summary
    if resolution_plans:
        _display_resolution_summary(resolution_plans)
        
        if not simulate:
            if click.confirm("\nProceed with execution?", default=False):
                executor = ActionExecutor(simulate=simulate)
                results = executor.execute_plans(resolution_plans)
                
                # Show execution summary
                summary = executor.get_execution_summary()
                _display_execution_summary(summary)
                
                # Save report if requested
                if report:
                    executor.save_execution_report(Path(report))
                    console.print(f"[dim]Report saved to: {report}[/dim]")
            else:
                console.print("[yellow]Execution cancelled.[/yellow]")
        else:
            console.print("\n[dim]Simulate mode - no changes made.[/dim]")
            console.print("[dim]Run without --simulate to apply changes.[/dim]")
    else:
        console.print("\n[yellow]No resolution plans created.[/yellow]")
    
    logger.info("Dedupe command completed")


def _filter_results_by_mode(results: Dict, mode: str) -> Dict:
    """Filter detection results by mode."""
    if mode == 'all':
        return results
    
    filtered = {'mal_id_conflicts': [], 'content_duplicates': [], 'fuzzy_duplicates': []}
    
    if mode == 'mal-id':
        filtered['mal_id_conflicts'] = results['mal_id_conflicts']
    elif mode == 'content':
        filtered['content_duplicates'] = results['content_duplicates']
    elif mode == 'fuzzy':
        filtered['fuzzy_duplicates'] = results['fuzzy_duplicates']
    
    return filtered


def _filter_results_by_query(results: Dict, query: str) -> Dict:
    """Filter detection results by query string."""
    query_lower = query.lower()
    filtered = {'mal_id_conflicts': [], 'content_duplicates': [], 'fuzzy_duplicates': []}
    
    # Filter MAL ID conflicts
    for duplicate in results['mal_id_conflicts']:
        if any(query_lower in series.name.lower() for series in duplicate.series):
            filtered['mal_id_conflicts'].append(duplicate)
    
    # Filter content duplicates
    for duplicate in results['content_duplicates']:
        if any(query_lower in vol.path.parent.name.lower() for vol in duplicate.volumes):
            filtered['content_duplicates'].append(duplicate)
    
    # Filter fuzzy duplicates
    for duplicate in results['fuzzy_duplicates']:
        if any(query_lower in series.name.lower() for series in duplicate.items):
            filtered['fuzzy_duplicates'].append(duplicate)
    
    return filtered


def _display_detection_summary(summary: Dict, results: Dict, mode: str):
    """Display duplicate detection summary."""
    table = Table(title="Duplicate Detection Summary")
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right", style="white")
    table.add_column("Details", style="dim")
    
    if summary['mal_id_groups'] > 0:
        table.add_row(
            "MAL ID Conflicts",
            str(summary['mal_id_groups']),
            f"{sum(len(d.series) for d in results['mal_id_conflicts'])} series affected"
        )
    
    if summary['content_groups'] > 0:
        table.add_row(
            "Content Duplicates",
            str(summary['content_groups']),
            f"{summary['total_duplicate_files']} files, {summary['estimated_space_mb']:.1f} MB"
        )
    
    if summary['fuzzy_groups'] > 0:
        table.add_row(
            "Fuzzy Name Duplicates",
            str(summary['fuzzy_groups']),
            f"{summary['total_affected_series']} series affected"
        )
    
    if summary['total_groups'] == 0:
        table.add_row("No duplicates found", "0", "-")
    
    console.print(table)


def _display_resolution_summary(plans: List[ResolutionPlan]):
    """Display detailed resolution plan summary."""
    if not plans:
        console.print("[yellow]No resolution plans to execute.[/yellow]")
        return
    
    console.print(f"\n[bold]Resolution Plans ({len(plans)} total):[/bold]")
    
    # Group by action type
    by_action = {}
    for plan in plans:
        if plan.action not in by_action:
            by_action[plan.action] = []
        by_action[plan.action].append(plan)
    
    # Display each action group
    for action, action_plans in sorted(by_action.items(), key=lambda x: x[0].value):
        console.print(f"\n[bold cyan]{action.value.upper()} ({len(action_plans)} plans):[/bold cyan]")
        
        for i, plan in enumerate(action_plans, 1):
            console.print(f"\n[bold]{i}. {plan.group_id}[/bold]")
            
            if action == ResolutionAction.MERGE:
                console.print(f"   [green]Target:[/green] {plan.target_path}")
                console.print(f"   [yellow]Sources:[/yellow] {len(plan.source_paths)} items")
                for src in plan.source_paths[:3]:  # Show first 3
                    console.print(f"     - {src}")
                if len(plan.source_paths) > 3:
                    console.print(f"     ... and {len(plan.source_paths) - 3} more")
            
            elif action == ResolutionAction.PREFER:
                console.print(f"   [green]Keep:[/green] {plan.target_path}")
                console.print(f"   [red]Delete:[/red] {len(plan.source_paths)} series")
                for src in plan.source_paths[:3]:
                    console.print(f"     - {src}")
                if len(plan.source_paths) > 3:
                    console.print(f"     ... and {len(plan.source_paths) - 3} more")
            
            elif action == ResolutionAction.DELETE:
                console.print(f"   [red]Delete:[/red] {len(plan.source_paths)} files")
                for src in plan.source_paths[:3]:
                    console.print(f"     - {src}")
                if len(plan.source_paths) > 3:
                    console.print(f"     ... and {len(plan.source_paths) - 3} more")
            
            # Show metadata if available
            if plan.metadata:
                console.print(f"   [dim]Metadata:[/dim]")
                for key, value in list(plan.metadata.items())[:3]:  # Show first 3 metadata items
                    if key not in ['source_names', 'delete_names']:  # Skip long lists
                        console.print(f"     {key}: {value}")
    
    # Show action counts summary
    action_counts = {}
    for plan in plans:
        action_counts[plan.action.value] = action_counts.get(plan.action.value, 0) + 1
    
    table = Table(title="Action Summary")
    table.add_column("Action", style="cyan")
    table.add_column("Count", justify="right", style="white")
    
    for action, count in sorted(action_counts.items()):
        table.add_row(action.replace('_', ' ').title(), str(count))
    
    console.print(table)


def _display_execution_summary(summary: Dict):
    """Display execution summary."""
    table = Table(title="Execution Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="white")
    
    table.add_row("Total Actions", str(summary['total_actions']))
    table.add_row("Successful", str(summary['successful']), style="green")
    if summary['failed'] > 0:
        table.add_row("Failed", str(summary['failed']), style="red")
    
    if summary['files_moved'] > 0:
        table.add_row("Files Moved", str(summary['files_moved']))
    
    if summary['files_deleted'] > 0:
        table.add_row("Files Deleted", str(summary['files_deleted']))
    
    if summary['space_freed_mb'] > 0:
        table.add_row("Space Freed", f"{summary['space_freed_mb']:.1f} MB")
    
    if summary['simulate']:
        table.add_row("Mode", "SIMULATE", style="yellow")
    
    console.print(table)


def _can_auto_resolve_mal_id(duplicate) -> bool:
    """Check if MAL ID duplicate can be auto-resolved."""
    # Check if one series is clearly larger (2x volumes and size)
    if len(duplicate.series) != 2:
        return False
    
    s1, s2 = duplicate.series
    vol_ratio = max(s1.total_volume_count, s2.total_volume_count) / max(1, min(s1.total_volume_count, s2.total_volume_count))
    size_ratio = max(s1.total_size_bytes, s2.total_size_bytes) / max(1, min(s1.total_size_bytes, s2.total_size_bytes))
    
    return vol_ratio >= 2 and size_ratio >= 1.5


def _auto_resolve_mal_id(duplicate):
    """Auto-resolve simple MAL ID conflicts."""
    # Select primary (larger series)
    primary = max(duplicate.series, key=lambda s: (s.total_volume_count, s.total_size_bytes))
    sources = [s for s in duplicate.series if s != primary]
    
    return ResolutionPlan(
        group_id=f"mal_auto_{duplicate.mal_id}",
        action=ResolutionAction.MERGE,
        target_path=primary.path,
        source_paths=[s.path for s in sources],
        metadata={'auto_resolved': True, 'mal_id': duplicate.mal_id}
    )


def _auto_resolve_content(duplicate):
    """Auto-resolve simple content duplicates (keep newest)."""
    # Keep newest file
    newest_vol = max(duplicate.volumes, key=lambda v: v.mtime)
    to_delete = [vol.path for vol in duplicate.volumes if vol.path != newest_vol.path]
    
    return ResolutionPlan(
        group_id=f"content_auto_{duplicate.file_hash[:8]}",
        action=ResolutionAction.DELETE,
        source_paths=to_delete,
        metadata={'auto_resolved': True, 'kept_file': str(newest_vol.path)}
    )
