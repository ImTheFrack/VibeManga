"""
Metadata command for VibeManga CLI.

Fetches and saves metadata (genres, authors, status) for series.
"""
import click
import logging
import concurrent.futures
from typing import Optional
from threading import Lock
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.live import Live
from rich.console import Group
from rich.text import Text

from .base import (
    console, 
    get_library_root, 
    run_scan_with_progress, 
    run_model_assignment
)
from ..models import Series
from ..metadata import get_or_create_metadata
from ..ai_api import tracker
from ..constants import PROGRESS_REFRESH_RATE

logger = logging.getLogger(__name__)

@click.command()
@click.argument("query", required=False)
@click.option("--force-update", is_flag=True, help="Force re-download of metadata from Jikan/AI.")
@click.option("--trust", "trust_jikan", is_flag=True, help="Trust Jikan if name is perfect match (skips AI Supervisor).")
@click.option("--all", "process_all", is_flag=True, help="Process all series in the library.")
@click.option("--model-assign", is_flag=True, help="Configure AI models for specific roles before running.")
@click.option("--parallel", type=click.IntRange(1, 10), default=1, help="Number of parallel threads to use (Default: 1).")
def metadata(query: Optional[str], force_update: bool, trust_jikan: bool, process_all: bool, model_assign: bool, parallel: int) -> None:
    """
    Fetches and saves metadata (genres, authors, status) for series.
    Creates a 'series.json' file in each series directory.
    """
    if model_assign:
        run_model_assignment()
        if not query and not process_all:
             return

    logger.info(f"Metadata command started (query={query}, force={force_update}, all={process_all}, trust={trust_jikan}, parallel={parallel})")
    
    if not query and not process_all:
        console.print("[yellow]Please provide a series name query or use --all to process the entire library.[/yellow]")
        return

    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library for Metadata...",
        use_cache=True # Metadata doesn't need fresh file scan usually
    )

    # Filter Targets
    targets = []
    
    def collect_targets(cat):
        for s in cat.series:
            if process_all or (query and query.lower() in s.name.lower()):
                targets.append(s)
        for sub in cat.sub_categories:
            collect_targets(sub)

    for main in library.categories:
        collect_targets(main)

    if not targets:
        console.print(f"[red]No series found matching '{query or 'ALL'}'[/red]")
        return

    console.print(f"[cyan]Found {len(targets)} series to process...[/cyan]")
    
    table = Table(title="Updated Metadata", box=box.ROUNDED)
    table.add_column("Series", style="white bold")
    table.add_column("Status", justify="center")
    table.add_column("Source", justify="center", style="dim")
    table.add_column("Genres/Tags", style="dim")
    table.add_column("Authors", style="cyan")
    
    table_lock = Lock()

    # Progress Layout
    progress = Progress(
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[progress.description]{task.description}"),
        console=console
    )
    
    detail_text = Text("", style="dim italic")
    display_group = Group(progress, detail_text)

    with Live(display_group, console=console, refresh_per_second=PROGRESS_REFRESH_RATE):
        task = progress.add_task("[green]Processing metadata...", total=len(targets))
        
        def process_one_series(series: Series) -> None:
            """Helper function for processing a single series."""
            # Define callback: Only use if running single-threaded to avoid UI race conditions
            # If parallel > 1, we rely on the main loop to update general status
            local_callback = None
            
            if parallel == 1:
                progress.update(task, description=f"[green]Fetching: {series.name}[/green]")
                
                def update_detail(msg: str):
                    detail_text.plain = ""
                    detail_text.append("  → ")
                    if "[" in msg and "]" in msg:
                        detail_text.append(Text.from_markup(msg))
                    else:
                        detail_text.append(msg)
                local_callback = update_detail
            
            try:
                meta, source = get_or_create_metadata(
                    series.path, 
                    series.name, 
                    force_update=force_update, 
                    trust_jikan=trust_jikan,
                    status_callback=local_callback
                )
                
                # Update status with source (Thread-safe lock for Table)
                color = "green" if "Trusted" in source or "Local" in source else "cyan" if "Jikan" in source else "magenta"
                
                # Add to summary table (limit rows if too many)
                if len(targets) <= 20 or force_update:
                    genres = ", ".join((meta.genres or [])[:3])
                    authors = ", ".join((meta.authors or [])[:2])
                    status_color = "green" if meta.status == "Completed" else "yellow"
                    
                    with table_lock:
                        table.add_row(
                            series.name,
                            f"[{status_color}]{meta.status}[/{status_color}]",
                            source,
                            genres,
                            authors
                        )
                return f"  → [{color}]Completed {series.name} via {source}[/{color}]"

            except Exception as e:
                logger.error(f"Error fetching metadata for {series.name}: {e}")
                return f"  → [red]Error processing {series.name}[/red]"

        # Parallel Execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_series = {executor.submit(process_one_series, s): s for s in targets}
            
            for future in concurrent.futures.as_completed(future_to_series):
                series = future_to_series[future]
                try:
                    result_msg = future.result()
                    # Update detail text safely in main thread
                    if result_msg and parallel > 1:
                        detail_text.plain = ""
                        detail_text.append(Text.from_markup(result_msg))
                    elif parallel == 1 and result_msg:
                        # For single thread, just show final status briefly
                        detail_text.plain = ""
                        detail_text.append(Text.from_markup(result_msg))
                        
                except Exception as exc:
                    logger.error(f"Thread exception for {series.name}: {exc}")
                
                progress.advance(task)

    if table.row_count > 0:
        console.print(table)
    
    # Final AI Report
    usage = tracker.get_summary()
    if usage:
        console.print("")
        report = Table(title="AI Usage Summary", box=box.SIMPLE_HEAD)
        report.add_column("Model", style="cyan")
        report.add_column("Input Tokens", justify="right")
        report.add_column("Output Tokens", justify="right")
        report.add_column("Total", justify="right", style="bold white")
        
        for model, counts in usage.items():
            report.add_row(
                model,
                str(counts["prompt"]),
                str(counts["completion"]),
                str(counts["prompt"] + counts["completion"])
            )
        console.print(report)

    console.print(f"[green]Metadata update complete for {len(targets)} series![/green]")
