"""
Dedupe command for VibeManga CLI.

Finds duplicate volumes and structural duplicates.
"""
import click
import logging
from typing import Optional

from .base import console, get_library_root, run_scan_with_progress, perform_deep_analysis
from ..analysis import find_duplicates, find_structural_duplicates

logger = logging.getLogger(__name__)

@click.command()
@click.argument("query", required=False)
@click.option("--verbose", is_flag=True, help="Show series with no issues found.")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
@click.option("--structural-only", is_flag=True, help="Only check for structural duplicates (folder level).")
def dedupe(query: Optional[str], verbose: bool, deep: bool, verify: bool, no_cache: bool, structural_only: bool) -> None:
    """
    Finds duplicate volumes.
    If QUERY is provided, only matching series are checked.
    Otherwise, the whole library is scanned.
    """
    logger.info(f"Dedupe command started (query={query}, verbose={verbose}, deep={deep}, verify={verify}, no_cache={no_cache}, structural_only={structural_only})")
    root_path = get_library_root()
    scan_desc = f"[bold green]Deduplicating '{query}'..." if query else "[bold green]Deduplicating Library..."
    library = run_scan_with_progress(root_path, scan_desc, use_cache=not no_cache)
    
    # Filter targets for deep analysis first
    if (deep or verify) and not structural_only:
        targets = []
        with console.status("[bold blue]Filtering targets for analysis..."):
            for main_cat in library.categories:
                for sub_cat in main_cat.sub_categories:
                    for series in sub_cat.series:
                        if query and query.lower() not in series.name.lower():
                            continue
                        targets.append(series)
        if targets:
            perform_deep_analysis(targets, deep, verify)

    # 1. Structural Duplicates
    struct_warnings = find_structural_duplicates(library, query)
    if struct_warnings:
        console.print(f"[bold red]Found {len(struct_warnings)} Structural Duplicates:[/bold red]")
        for w in struct_warnings:
            console.print(w)
            console.print("-" * 40)
    elif query:
        console.print(f"[dim]No structural duplicates found for '{query}'[/dim]")
    
    if structural_only:
        return

    # 2. File Duplicates
    found_any = False
    with console.status("[bold blue]Analyzing results..."):
        for main_cat in library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    if query and query.lower() not in series.name.lower():
                        continue
                        
                    found_any = True
                    duplicates = find_duplicates(series, fuzzy=True)
                    
                    if not duplicates:
                        if verbose or query:
                            console.print(f"[green]✓ {series.name}: No file duplicates found[/green]")
                    else:
                        console.print(f"[yellow]! {series.name}: {len(duplicates)} file issues found[/yellow] [dim]({main_cat.name} > {sub_cat.name})[/dim]")
                        for dup in duplicates:
                            console.print(f"  - {dup}")

    if query and not found_any:
        logger.warning(f"No series found matching: {query}")
        console.print(f"[red]No series found matching '{query}'[/red]")

    logger.info("Dedupe command completed")
