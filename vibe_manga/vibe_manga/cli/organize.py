"""
Organize command for VibeManga CLI.

Restructures (Move) or selectively exports (Copy) the manga library based on filters.
"""
import shutil
import click
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from rich.console import Console
from rich.prompt import Confirm
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TransferSpeedColumn

from .base import console, run_scan_with_progress, get_library_root, run_model_assignment
from ..indexer import LibraryIndex
from ..categorizer import suggest_category, get_category_list
from ..models import Series, Library, Category
from ..scanner import scan_library

import time

logger = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 3

@dataclass
class CopyTask:
    series: Series
    dest: Path
    mode: str  # "COPY" or "MOVE"

def perform_transfer(task: CopyTask, progress: Progress, task_id_copy: int, queue_size: int = 0) -> bool:
    """Executes the transfer with progress updates."""
    try:
        prefix = f"[Queue: {queue_size}] " if queue_size > 0 else ""
        
        if task.mode == "COPY":
            if task.dest.exists():
                # Skip existing
                return False

            # Collect files for progress bar
            files = [f for f in task.series.path.rglob("*") if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            
            progress.update(
                task_id_copy, 
                total=total_size, 
                completed=0, 
                description=f"{prefix}[cyan]Copying {task.series.name}[/cyan]",
                visible=True
            )
            
            # Create root dest
            task.dest.mkdir(parents=True, exist_ok=True)
            
            copied_size = 0
            for f in files:
                rel = f.relative_to(task.series.path)
                target = task.dest / rel
                
                if not target.parent.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                
                shutil.copy2(f, target)
                
                copied_size += f.stat().st_size
                progress.update(task_id_copy, completed=copied_size)
                
            return True

        elif task.mode == "MOVE":
            # Move is harder to track progress for if cross-device, 
            # but usually fast if same device.
            progress.update(
                task_id_copy, 
                total=None, 
                description=f"{prefix}[cyan]Moving {task.series.name}[/cyan]",
                visible=True
            )
            
            if not task.dest.parent.exists():
                task.dest.parent.mkdir(parents=True, exist_ok=True)
                
            shutil.move(str(task.series.path), str(task.dest))
            return True
            
    except Exception as e:
        logger.error(f"Transfer failed for {task.series.name}: {e}")
        return False

def copy_worker(task_queue: queue.Queue, result_queue: queue.Queue, progress: Progress, task_id_copy: int):
    """Background worker for processing transfers."""
    while True:
        task = task_queue.get()
        if task is None:
            task_queue.task_done()
            break
        
        # Update Description with queue info (approx)
        q_size = task_queue.qsize()
        
        success = perform_transfer(task, progress, task_id_copy, queue_size=q_size)
        
        # Update description again if needed? perform_transfer sets its own description.
        # We can update it here if we want to show queue info inside the bar text.
        
        result_queue.put(success)
        
        # Reset copy bar
        progress.update(task_id_copy, visible=False)
        task_queue.task_done()

@click.command()
@click.argument("query", required=False)
@click.option("--tag", multiple=True, help="Include series with this tag.")
@click.option("--no-tag", multiple=True, help="Exclude series with this tag.")
@click.option("--genre", multiple=True, help="Include series with this genre.")
@click.option("--no-genre", multiple=True, help="Exclude series with this genre.")
@click.option("--source", multiple=True, help="Include series from this Main/Sub category (e.g., 'Manga', 'Manga/Action').")
@click.option("--no-source", multiple=True, help="Exclude series from this Main/Sub category.")
@click.option("--target", help="Target destination. Can be 'Main' (AI picks sub) or 'Main/Sub' (Direct move).")
@click.option("--newroot", type=click.Path(path_type=Path), help="Copy mode: Destination root directory.")
@click.option("--auto", is_flag=True, help="Skip confirmation prompts.")
@click.option("--simulate", is_flag=True, help="Dry run: show what would happen without changes.")
@click.option("--no-cache", is_flag=True, help="Force a fresh scan of the library.")
@click.option("--explain", is_flag=True, help="Show AI explanation for each categorization decision.")
@click.option("--model-assign", is_flag=True, help="Configure AI models for specific roles before running.")
@click.option("--newonly", is_flag=True, help="Skip series that already exist in --newroot destination.")
def organize(
    model_assign: bool,
    newonly: bool,
    query: Optional[str],
    tag: List[str],
    no_tag: List[str],
    genre: List[str],
    no_genre: List[str],
    source: List[str],
    no_source: List[str],
    target: Optional[str],
    newroot: Optional[Path],
    auto: bool,
    simulate: bool,
    no_cache: bool,
    explain: bool,
) -> None:
    """
    Organize series by moving or copying them based on filters and AI suggestions.
    
    Default behavior is MOVE within the current library.
    Use --newroot to COPY to a separate location (export mode).
    """
    if model_assign:
        run_model_assignment()
    
    library_root = get_library_root()
    
    # 1. Setup Phase
    console.print(Panel.fit("VibeManga Organizer", border_style="blue"))
    
    # Determine Mode
    mode = "COPY" if newroot else "MOVE"
    base_dest = newroot if newroot else library_root
    
    if mode == "COPY":
        if not base_dest.exists():
            if not simulate and (auto or Confirm.ask(f"Destination '{base_dest}' does not exist. Create it?")):
                base_dest.mkdir(parents=True, exist_ok=True)
            elif not simulate:
                console.print("[red]Aborted: Destination must exist.[/red]")
                return

    console.print(f"Mode: [bold]{mode}[/bold]")
    console.print(f"Source: [cyan]{library_root}[/cyan]")
    console.print(f"Destination Base: [cyan]{base_dest}[/cyan]")
    if target:
        console.print(f"Target Constraint: [yellow]{target}[/yellow]")
    if newonly:
        console.print(f"New-Only Mode: [yellow]Enabled[/yellow]")
        if mode != "COPY":
            console.print("[red]Error: --newonly can only be used with --newroot[/red]")
            return
    
    # Scan Library
    library = run_scan_with_progress(library_root, "Scanning library...", use_cache=not no_cache)
    
    # Build Index
    index = LibraryIndex()
    index.build(library)
    
    # Build set of existing series names in new root if --newonly is enabled
    existing_series_names: Set[str] = set()
    if newonly and mode == "COPY" and base_dest.exists():
        console.print("[dim]Scanning for existing series in destination...[/dim]")
        dest_library = scan_library(base_dest)
        for category in dest_library.categories:
            for sub in category.sub_categories:
                for series in sub.series:
                    existing_series_names.add(series.name.lower())
        console.print(f"[dim]Found {len(existing_series_names)} existing series in destination.[/dim]")
    
    # Build Custom Schema if copying to new root
    custom_schema: Optional[List[str]] = None
    if mode == "COPY" and base_dest.exists():
        console.print("[dim]Scanning destination for existing structure...[/dim]")
        dest_library = scan_library(base_dest)
        custom_schema = get_category_list(dest_library)
        if custom_schema:
            console.print(f"[dim]Found {len(custom_schema)} existing categories in destination.[/dim]")
    
    # 2. Filter Phase
    candidates: List[Series] = []
    
    # Resolve Query first if present
    query_matches: Optional[Set[str]] = None
    if query:
        query_results = index.search(query)
        # LibraryIndex.search returns list of dicts with 'series' object
        query_matches = {r['series'].path for r in query_results}
        if not query_matches:
            console.print(f"[yellow]No series found matching query '{query}'[/yellow]")
            return

    def check_metadata(series: Series, main_cat: Category, sub_cat: Category) -> bool:
        # If query was provided, series MUST be in query results
        if query_matches is not None and series.path not in query_matches:
            return False
            
        meta = series.metadata
        
        # New-Only Logic: Skip if series already exists in destination
        if newonly and mode == "COPY":
            if series.name.lower() in existing_series_names:
                return False

        # Exclusion Logic (Must NOT match any)
        if no_tag and any(t.lower() in [mt.lower() for mt in meta.tags] for t in no_tag):
            return False
        if no_genre and any(g.lower() in [mg.lower() for mg in meta.genres] for g in no_genre):
            return False
        
        parent_path = f"{main_cat.name}/{sub_cat.name}" # Main/Sub
        if no_source:
             main_name = main_cat.name
             full = parent_path
             if any(s == main_name or s == full for s in no_source):
                 return False

        # Inclusion Logic (Must match AT LEAST ONE if any are set)
        has_inclusion_criteria = bool(tag or genre or source)
        if not has_inclusion_criteria:
            return True # No filters = include all (subject to query) 
            
        match_found = False
        if tag and any(t.lower() in [mt.lower() for mt in meta.tags] for t in tag):
            match_found = True
        if genre and any(g.lower() in [mg.lower() for mg in meta.genres] for g in genre):
            match_found = True
            
        if source:
             main_name = main_cat.name
             full = parent_path
             if any(s == main_name or s == full for s in source):
                 match_found = True
                 
        return match_found

    # Iterate all series to find candidates
    for category in library.categories:
        for sub in category.sub_categories:
            for series in sub.series:
                if check_metadata(series, category, sub):
                    candidates.append(series)

    if not candidates:
        console.print("[yellow]No series matched the provided filters.[/yellow]")
        return

    console.print(f"[green]Found {len(candidates)} candidates.[/green]")
    if not auto and not simulate:
        if not Confirm.ask("Proceed with organization?"):
            return

    # 3. Execution Phase
    success_count = 0
    fail_count = 0
    skipped_count = 0
    
    # Initialize Queues for Background Worker
    task_queue = queue.Queue()
    result_queue = queue.Queue()
    
    # Setup Persistent Progress
    # We use a custom layout if possible, or just standard bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        
        task_id_total = progress.add_task("[bold green]Overall Progress", total=len(candidates))
        task_id_ai = progress.add_task("AI Analysis", total=None, visible=False)
        task_id_copy = progress.add_task("Idle", total=None, visible=False)
        
        # Start Worker Thread if not simulation
        worker_thread = None
        if not simulate:
            worker_thread = threading.Thread(
                target=copy_worker, 
                args=(task_queue, result_queue, progress, task_id_copy),
                daemon=True
            )
            worker_thread.start()

        def update_ai_status(msg: str):
            progress.update(task_id_ai, description=f"[magenta]{msg}", visible=True)

        for series in candidates:
            # Update Main Task
            progress.update(task_id_total, description=f"[bold green]Processing: {series.name}")
            
            # Throttling Logic
            if not simulate:
                while task_queue.qsize() >= MAX_QUEUE_SIZE:
                    update_ai_status(f"Waiting for copy queue ({task_queue.qsize()} items)...")
                    time.sleep(0.5)

            # Determine Target Path
            final_category_path = ""
            
            # Case A: Direct Target (e.g. "Manga/Action")
            if target and "/" in target:
                final_category_path = target
                
            # Case B: AI Assisted
            else:
                restrict_to = target # None or "Manga"
                
                # Use quiet mode if auto is enabled to prevent spinner conflict
                use_quiet = auto 
                
                # If interactive (not auto), we might need to temporarily pause the progress bar?
                # Actually, Rich's progress bar plays nice with console.print/input usually.
                # But 'categorize.py' uses console.status which might fight.
                # However, since we are in a loop inside `with Progress`,
                # any `console.status` inside `suggest_category` (if not quiet) will likely just overwrite the bottom line.
                # It's acceptable for interactive mode.
                
                suggestion = suggest_category(
                    series, 
                    library, 
                    custom_categories=custom_schema if mode == "COPY" else None,
                    restrict_to_main=restrict_to,
                    quiet=use_quiet,
                    status_callback=update_ai_status
                )
                
                # Reset AI Task visibility
                progress.update(task_id_ai, visible=False)
                
                if not suggestion or "consensus" not in suggestion:
                    if not use_quiet:
                        console.print(f"[red]AI failed to categorize {series.name}. Skipping.[/red]")
                    fail_count += 1
                    progress.advance(task_id_total)
                    continue
                    
                cons = suggestion["consensus"]
                final_category_path = f"{cons['final_category']}/{cons['final_sub_category']}"
                
                # Show decision clearly in log
                progress.console.print(f"[green]AI Selected:[/green] {final_category_path} [dim]for {series.name}[/dim]")
                if explain:
                     reason = cons.get("reason", "No reason provided")
                     progress.console.print(f"  [dim]Reason: {reason}[/dim]")

            # Construct full destination path
            dest_path = base_dest / final_category_path / series.name
            
            # Check for same path
            if dest_path.resolve() == series.path.resolve():
                if not auto: console.print(f"[dim]Skipping {series.name}: Source == Dest[/dim]")
                skipped_count += 1
                progress.advance(task_id_total)
                continue

            if simulate:
                console.print(f"[dim][SIMULATE] {mode} {series.name} -> {dest_path}[/dim]")
                success_count += 1
                progress.advance(task_id_total)
                continue

            # Queue Task
            task = CopyTask(series=series, dest=dest_path, mode=mode)
            task_queue.put(task)
            
            # Advance main progress
            progress.advance(task_id_total)

        # End of Loop: Wait for worker to finish
        if not simulate:
            progress.update(task_id_total, description="[bold green]Finalizing transfers...")
            
            # Signal stop
            task_queue.put(None)
            
            # Wait for thread
            worker_thread.join()
            
            # Count results
            while not result_queue.empty():
                if result_queue.get():
                    success_count += 1
                else:
                    fail_count += 1

    console.print(Panel(
        f"Complete!\nSuccess: {success_count}\nFailed: {fail_count}\nSkipped: {skipped_count}", 
        title="Summary", 
        border_style="green"
    ))