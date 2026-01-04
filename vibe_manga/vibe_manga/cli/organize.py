"""
Organize command for VibeManga CLI.

Restructures (Move) or selectively exports (Copy) the manga library based on filters.
"""
import shutil
import click
import logging
import queue
import threading
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

from rich.console import Console
from rich.prompt import Confirm
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table
from rich import box
from rich.rule import Rule

from .base import console, run_scan_with_progress, get_library_root, run_model_assignment
from ..indexer import LibraryIndex
from ..categorizer import suggest_category, get_category_list
from ..models import Series, Library, Category
from ..scanner import scan_library
from ..logging import log_step, log_substep
from ..config import get_ai_role_config
from ..analysis import sanitize_filename

import time

logger = logging.getLogger(__name__)

def manual_select_category(library: Library) -> Optional[Tuple[str, str]]:
    """Interactive manual category selection helper."""
    console.print(Rule("[bold cyan]Manual Categorization[/bold cyan]"))
    
    # 1. Main Category
    mains = [c for c in library.categories if c.name != "Uncategorized"]
    
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Key", style="cyan", width=4)
    table.add_column("Category Name")
    
    opts = {}
    for i, cat in enumerate(mains, 1):
        opts[str(i)] = cat
        table.add_row(str(i), cat.name)
    
    table.add_row("n", "[italic]New Category...[/italic]")
    table.add_row("c", "[italic]Cancel[/italic]")
    
    console.print(table)
    choice = click.prompt("Select Main Category", default="c").lower().strip()
    
    selected_main = None
    selected_main_name = ""
    
    if choice == 'n':
        selected_main_name = click.prompt("Enter NEW Main Category Name")
    elif choice == 'c':
        return None
    elif choice in opts:
        selected_main = opts[choice]
        selected_main_name = selected_main.name
    else:
        console.print("[red]Invalid selection.[/red]")
        return None

    # 2. Sub Category
    subs = []
    if selected_main:
        subs = selected_main.sub_categories
    
    console.print(f"\n[bold cyan]Sub-Categories for '{selected_main_name}'[/bold cyan]")
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Key", style="cyan", width=4)
    table.add_column("Sub-Category Name")
    
    sub_opts = {}
    for i, sub in enumerate(subs, 1):
        sub_opts[str(i)] = sub
        table.add_row(str(i), sub.name)
        
    table.add_row("n", "[italic]New Sub-Category...[/italic]")
    table.add_row("b", "[italic]Back / Cancel[/italic]")
    
    console.print(table)
    sub_choice = click.prompt("Select Sub-Category", default="n").lower().strip()
    
    selected_sub_name = ""
    if sub_choice == 'n':
        selected_sub_name = click.prompt("Enter NEW Sub-Category Name")
    elif sub_choice == 'b':
        return None
    elif sub_choice in sub_opts:
        selected_sub_name = sub_opts[sub_choice].name
    else:
        console.print("[red]Invalid selection.[/red]")
        return None
        
    return selected_main_name, selected_sub_name

def display_ai_council_config() -> None:
    """Displays the active AI model configuration for the categorization council."""
    log_step("AI Council Configuration")
    console.print(Rule("[bold magenta]AI Council Configuration[/bold magenta]"))
    
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Role", style="white bold", width=12)
    table.add_column("Model Assigned", style="yellow")
    table.add_column("Mission Synopsis", style="dim italic")

    # Define roles to show
    council_roles = [
        ("MODERATOR", "Safety & Content Analysis (Flags illegal/adult content)"),
        ("PRACTICAL", "Structural Sorting (Based on Demographics/Genres)"),
        ("CREATIVE", "Vibe Analysis (Based on Synopsis/Themes)"),
        ("CONSENSUS", "Final Decision Maker (Weighs all inputs)")
    ]

    for role, synopsis in council_roles:
        config = get_ai_role_config(role)
        provider = config.get("provider", "unknown")
        model = config.get("model", "unknown")
        
        # Format model string
        model_display = f"[{provider}] {model}"
        
        table.add_row(role.title(), model_display, synopsis)

    console.print(table)
    console.print("")

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

def visualize_ai_decision(results: dict, series_name: str, console_override: Optional[Console] = None):
    """Visualizes the AI categorization decision using Rich panels."""
    if not results: return
    
    printer = console_override or console
    
    # 0. Series Title Panel
    printer.print(Panel(Text(series_name, justify="center", style="bold white"), style="bold blue", box=box.HEAVY))
    
    consensus = results.get("consensus", {})
    final_cat = sanitize_filename(consensus.get("final_category", "Manga"))
    final_sub = sanitize_filename(consensus.get("final_sub_category", "Other"))
    reason = consensus.get("reason", "No reason provided.")
    conf = consensus.get("confidence_score", 0.0)
    
    mod = results.get("moderation", {})
    if not isinstance(mod, dict): mod = {"classification": "UNKNOWN"}
    is_flagged = mod.get("classification", "SAFE") != "SAFE"

    # 1. Metadata Summary
    meta_obj = results.get("metadata")
    meta_text = Text()
    if meta_obj:
        if meta_obj.genres:
            meta_text.append("Genres: ", style="bold blue")
            meta_text.append(", ".join(meta_obj.genres[:4]), style="dim")
            meta_text.append(" | ")
        if meta_obj.demographics:
            meta_text.append("Demo: ", style="bold magenta")
            meta_text.append(", ".join(meta_obj.demographics), style="dim")
            meta_text.append(" | ")
        if meta_obj.release_year:
            meta_text.append(f"Year: {meta_obj.release_year}", style="dim")
    
    # 2. Synopsis
    syn_panel = None
    if meta_obj and meta_obj.synopsis:
            syn = meta_obj.synopsis
            if len(syn) > 180: syn = syn[:177] + "..."
            syn_panel = Panel(Text(syn, style="italic"), title="Synopsis", border_style="dim", box=box.SIMPLE)

    # 3. AI Council Grid
    council_grid = Table.grid(expand=True, padding=(0, 1))
    council_grid.add_column(ratio=1)
    council_grid.add_column(ratio=1)
    council_grid.add_column(ratio=1)
    
    def get_panel(role, data, color):
        if not data: return Panel("N/A", title=role, border_style="dim")
        content = ""
        if role == "Moderator":
            cls = data.get("classification", "?")
            content = f"[bold]{cls}[/bold]\n"
        elif role == "Practical" or role == "Creative":
            cat = data.get("category", "?")
            content = f"[bold]{cat}[/bold]\n"
        
        reason = data.get("reason", "")
        if len(reason) > 80: reason = reason[:77] + "..."
        content += f"[dim]{reason}[/dim]"
        return Panel(content, title=role, border_style=color)

    p_mod = get_panel("Moderator", results.get("moderation"), "red" if is_flagged else "green")
    p_prac = get_panel("Practical", results.get("practical"), "blue")
    p_crea = get_panel("Creative", results.get("creative"), "magenta")
    
    council_grid.add_row(p_mod, p_prac, p_crea)

    # 4. Consensus
    cons_text = f"[bold green]{final_cat}/{final_sub}[/bold green] (Conf: {conf:.2f})"
    cons_reason = f"[dim]{reason}[/dim]"
    cons_panel = Panel(f"{cons_text}\n{cons_reason}", title="Consensus", border_style="yellow")

    printer.print(meta_text)
    if syn_panel: printer.print(syn_panel)
    printer.print(council_grid)
    printer.print(cons_panel)

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
@click.option("--instruct", help="Provide specific instructions/feedback to the Consensus AI (e.g., 'Force all Isekai to Fantasy').")
@click.option("--interactive", is_flag=True, help="Enable interactive mode with manual confirmation and detailed UI.")
def organize(
    model_assign: bool,
    newonly: bool,
    instruct: Optional[str],
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
    interactive: bool,
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
        # LibraryIndex.search() returns Series objects directly.
        #query_matches = {r['series'].path for r in query_results}
        query_matches = {r.path for r in query_results}
        
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
    
    if interactive:
        display_ai_council_config()
        
        for i, series in enumerate(candidates, 1):
            log_substep(f"Categorizing: {series.name}")
            console.print(Rule(f"[bold blue][{i}/{len(candidates)}] Processing: {series.name}[/bold blue]"))
            
            user_feedback = instruct
            should_process = False
            final_cat_path = ""
            
            # --- AI Logic (Interactive) ---
            results = None 
            
            while True: # Interactive Loop for this series
                try:
                    if not results:
                         # Define callbacks for interactive UI
                        status_ctx = console.status(f"[bold blue]Analyzing '{series.name}'...[/bold blue]")
                        
                        def update_status_cb(msg: str):
                            status_ctx.update(msg)

                        def confirm_cb(suggestion: str, reason: str) -> bool:
                            status_ctx.stop()
                            console.print(f"\n[bold yellow]AI suggested a new category:[/bold yellow] [cyan]{suggestion}[/cyan]")
                            console.print(f"[dim]Reason: {reason}[/dim]")
                            res = Confirm.ask("Accept this new category?", default=True)
                            status_ctx.start()
                            return res

                        with status_ctx:
                            restrict_to = target
                            results = suggest_category(
                                series, 
                                library, 
                                user_feedback=user_feedback, 
                                custom_categories=custom_schema if mode == "COPY" else None,
                                restrict_to_main=restrict_to,
                                status_callback=update_status_cb,
                                confirm_callback=confirm_cb
                            )
                        
                        if not results or not results.get("consensus"):
                            console.print(f"[red]Failed to get AI consensus for {series.name}. Skipping.[/red]")
                            break 
                    
                    consensus = results["consensus"]
                    final_cat = sanitize_filename(consensus.get("final_category", "Manga"))
                    final_sub = sanitize_filename(consensus.get("final_sub_category", "Other"))
                    reason = consensus.get("reason", "No reason provided.")
                    conf = consensus.get("confidence_score", 0.0)
                    
                    # Moderation Check
                    mod = results.get("moderation")
                    if not isinstance(mod, dict):
                        mod = {"classification": "SAFE", "reason": "Moderation data missing/invalid"}
                    
                    is_flagged = mod.get("classification", "SAFE") != "SAFE"
                    is_illegal = mod.get("classification") == "ILLEGAL"
                    
                    # --- VISUALIZATION ---
                    visualize_ai_decision(results, series.name)
                    
                    if is_illegal:
                         console.print("[bold red]ILLEGAL CONTENT DETECTED - Skipping/Deleting[/bold red]")
                         # Simplification: Just skip in interactive organize for now, user can choose 'c' to blacklist/delete if they want
                         break

                    # Inner Menu Loop
                    action_taken = False
                    while True:
                        console.print("\n[bold]Options:[/bold]")
                        menu_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
                        menu_table.add_column("Key", style="bold cyan")
                        menu_table.add_column("Action")
                        menu_table.add_column("Description", style="dim")
                        
                        op_verb = "Copy" if mode == "COPY" else "Move"
                        
                        menu_table.add_row(r"[a]", "Accept", f"{op_verb} to suggestion")
                        menu_table.add_row(r"[b]", "Reject", "Retry with instruction")
                        menu_table.add_row(r"[e]", "Manual", "Select category manually")
                        menu_table.add_row(r"[s]", "Skip", "Skip this series")
                        menu_table.add_row(r"[q]", "Quit", "Exit program")
                        console.print(menu_table)
                        
                        choice = click.prompt("Select action", default="a", show_default=True).lower().strip()
                        
                        if choice == 'a': # Accept
                            final_cat_path = f"{final_cat}/{final_sub}"
                            should_process = True
                            action_taken = True
                            break
                        elif choice == 'b': # Reject
                            user_feedback = click.prompt("Enter instruction")
                            results = None 
                            action_taken = False 
                            break
                        elif choice == 'e': # Manual
                            manual = manual_select_category(library)
                            if manual:
                                 m_cat, m_sub = manual
                                 final_cat_path = f"{m_cat}/{m_sub}"
                                 should_process = True
                                 action_taken = True
                                 break
                            else:
                                 continue
                        elif choice == 's': # Skip
                            action_taken = True
                            break
                        elif choice == 'q': # Quit
                            return

                    if action_taken:
                        break

                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    break
            
            # Execute
            if should_process and final_cat_path:
                dest_path = base_dest / final_cat_path / series.name
                
                if dest_path.resolve() == series.path.resolve():
                    console.print(f"[dim]Skipping {series.name}: Source == Dest[/dim]")
                    skipped_count += 1
                    continue

                task = CopyTask(series=series, dest=dest_path, mode=mode)
                
                if simulate:
                    console.print(f"[dim][SIMULATE] {mode} {series.name} -> {dest_path}[/dim]")
                    success_count += 1
                else:
                    # Synchronous transfer
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                        console=console
                    ) as p:
                        task_id = p.add_task(f"{mode}ing...", total=None) # indeterminate
                        success = perform_transfer(task, p, task_id)
                        if success: 
                            success_count += 1
                            console.print(f"[green]✓ {mode} Complete[/green]")
                        else: 
                            fail_count += 1
                            console.print(f"[red]✗ {mode} Failed[/red]")

    else:
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
                    
                    suggestion = suggest_category(
                        series, 
                        library, 
                        custom_categories=custom_schema if mode == "COPY" else None,
                        restrict_to_main=restrict_to,
                        quiet=use_quiet,
                        status_callback=update_ai_status,
                        user_feedback=instruct
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
                    
                    # Visualize decision
                    if explain:
                         visualize_ai_decision(suggestion, series.name, console_override=progress.console)
                    else:
                         progress.console.print(f"[green]AI Selected:[/green] {final_category_path} [dim]for {series.name}[/dim]")

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