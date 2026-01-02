"""
Hydrate command for VibeManga CLI.

Ensures every series in the library has a valid ID/Metadata.
"""
import click
import logging
from typing import List
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.rule import Rule

from .base import (
    console, 
    get_library_root, 
    run_scan_with_progress, 
    run_model_assignment
)
from ..models import Series
from ..metadata import get_or_create_metadata
from ..cache import save_library_cache
from ..constants import PROGRESS_REFRESH_RATE

logger = logging.getLogger(__name__)

@click.command()
@click.option("--force", is_flag=True, help="Force re-check even if MAL ID exists.")
@click.option("--model-assign", is_flag=True, help="Configure AI models before running.")
def hydrate(force: bool, model_assign: bool) -> None:
    """
    Ensures every series in the library has a valid ID/Metadata.
    Iterates through the library and fetches metadata for any series missing a MAL ID.
    """
    if model_assign:
        run_model_assignment()

    logger.info(f"Hydrate command started (force={force})")
    root_path = get_library_root()
    
    # 1. Scan Library
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library for Hydration...",
        use_cache=True 
    )

    # 2. Identify Candidates
    candidates: List[Series] = []
    
    def check_series(s: Series):
        # We check if mal_id is missing (None or 0). 
        # If 'force' is True, we include it regardless (updates existing).
        if force or not s.metadata.mal_id:
            candidates.append(s)

    for cat in library.categories:
        for sub in cat.sub_categories:
            for s in sub.series:
                check_series(s)
        for s in cat.series:
            check_series(s)

    if not candidates:
        console.print("[green]All series are already hydrated (MAL IDs present).[/green]")
        return

    console.print(f"[cyan]Found {len(candidates)} series needing hydration...[/cyan]")

    # 3. Process Candidates
    progress = Progress(
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[progress.description]{task.description}"),
        console=console
    )
    
    detail_text = Text("", style="dim italic")
    display_group = Group(progress, detail_text)

    # Stats for summary
    stats = {"success": 0, "failed": 0, "skipped": 0}

    with Live(display_group, console=console, refresh_per_second=PROGRESS_REFRESH_RATE):
        task = progress.add_task("[green]Hydrating...", total=len(candidates))
        
        for series in candidates:
            progress.update(task, description=f"[green]Hydrating: {series.name}[/green]")
            
            def update_detail(msg: str):
                detail_text.plain = ""
                detail_text.append("  → ")
                if "[" in msg and "]" in msg:
                    detail_text.append(Text.from_markup(msg))
                else:
                    detail_text.append(msg)

            try:
                # If MAL ID is missing (None or 0), we MUST force update to bypass the local cache check.
                # Otherwise, it just reloads the existing "empty" series.json and does nothing.
                should_force = force or not series.metadata.mal_id

                # Call get_or_create_metadata
                # This automatically attempts Jikan -> AI Supervisor -> AI Fetcher -> Placeholder
                # And saves to series.json
                meta, source = get_or_create_metadata(
                    series.path, 
                    series.name, 
                    force_update=should_force,
                    status_callback=update_detail
                )
                
                # Update In-Memory Object!
                series.metadata = meta
                
                if meta.mal_id:
                    stats["success"] += 1
                    console.print(f"  [green]✓[/green] [white]{series.name}[/white] -> [bold cyan]MAL ID: {meta.mal_id}[/bold cyan] [dim]({source})[/dim]")
                else:
                    # If we got a placeholder back (no MAL ID), it counts as a partial failure/skip
                    stats["skipped"] += 1
                    console.print(f"  [yellow]![/yellow] [white]{series.name}[/white] -> [yellow]No ID Found[/yellow] [dim]({source})[/dim]")
                
            except Exception as e:
                logger.error(f"Error hydrating {series.name}: {e}")
                stats["failed"] += 1
                detail_text.plain = f"  → [red]Error: {e}[/red]"
            
            progress.advance(task)

    # 4. Final Summary
    console.print(Rule("[bold magenta]Hydration Complete[/bold magenta]"))
    console.print(f"Total Processed: {len(candidates)}")
    console.print(f"[green]Successfully Hydrated (ID Found): {stats['success']}[/green]")
    console.print(f"[yellow]Placeholder Created (No ID): {stats['skipped']}[/yellow]")
    if stats['failed'] > 0:
        console.print(f"[red]Errors: {stats['failed']}[/red]")

    # Save cache to persist the in-memory updates we just made
    save_library_cache(library)
    console.print("[dim]Library cache updated.[/dim]")
