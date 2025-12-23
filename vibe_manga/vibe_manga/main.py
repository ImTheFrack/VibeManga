import os
import logging
import click
import concurrent.futures
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from collections import Counter
from dotenv import load_dotenv, find_dotenv

# Load environment variables immediately
load_dotenv(find_dotenv())

from rich.console import Console
from rich.tree import Tree
from rich.table import Table
from rich import box

from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.padding import Padding
from rich.rule import Rule
from rich.panel import Panel
from rich.columns import Columns
from rich.align import Align
import datetime
import json
import time

from .scanner import scan_library, enrich_series
from .models import Library, Category, Series
from .analysis import (
    find_gaps, 
    find_duplicates, 
    find_structural_duplicates, 
    find_external_updates, 
    format_ranges, 
    semantic_normalize,
    classify_unit,
    sanitize_filename
)
from .metadata import get_or_create_metadata, load_local_metadata
from .cache import get_cached_library, save_library_cache, load_library_state
from .nyaa_scraper import scrape_nyaa, get_latest_timestamp_from_nyaa
from .matcher import process_match, consolidate_entries
from .grabber import process_grab, process_pull
from .categorizer import suggest_category, get_category_list
from .qbit_api import QBitAPI
from .constants import (
    QBIT_DEFAULT_TAG,
    DEFAULT_TREE_DEPTH,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_GB,
    PROGRESS_REFRESH_RATE,
    DEEP_ANALYSIS_REFRESH_RATE,
    NYAA_DEFAULT_PAGES_TO_SCRAPE,
    NYAA_DEFAULT_OUTPUT_FILENAME,
    ROLE_CONFIG,
    VALID_DEMOGRAPHICS,
    CLEAN_WORD_RE,
    STOP_WORDS
)
from .ai_api import get_available_models, tracker
from .config import load_ai_config, save_ai_config, get_role_config

# Initialize Rich Console
console = Console()

# Configure logging
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# File Handler (Full Detail) - Use UTF-8 to prevent encoding errors on Windows
file_handler = logging.FileHandler('vibe_manga.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_formatter)

# Stream Handler (Console - Errors and Warnings) - Use RichHandler for better Unicode support
stream_handler = RichHandler(console=console, show_path=False, keywords=[])
stream_handler.setLevel(logging.WARNING)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
# Clear existing handlers to avoid duplicates
root_logger.handlers = []
root_logger.addHandler(file_handler)
root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)

def select_model_interactive(models: List[str], default: Optional[str] = None) -> str:
    """
    Interactive paginated selector for large model lists.
    """
    # Create a local copy to filter
    all_models = sorted(models)
    display_pool = all_models
    filter_query = ""
    page_size = 15
    current_page = 0
    
    while True:
        total_pages = max(1, (len(display_pool) + page_size - 1) // page_size)
        if current_page >= total_pages: current_page = 0
        if current_page < 0: current_page = total_pages - 1
        
        # Get page slice
        start_idx = current_page * page_size
        end_idx = start_idx + page_size
        page_items = display_pool[start_idx:end_idx]
        
        # Render
        console.print("") # Spacer
        table = Table(
            title=f"Select Model (Page {current_page + 1}/{total_pages})", 
            box=box.ROUNDED,
            caption=f"[dim]Total: {len(display_pool)} models | Filter: '{filter_query}'[/dim]"
        )
        table.add_column("ID", justify="right", style="cyan", width=4)
        table.add_column("Model Name", style="white")
        
        for i, model in enumerate(page_items):
            # ID corresponds to the index in the CURRENT filtered list (1-based)
            display_idx = start_idx + i + 1
            marker = " [green](Current)[/green]" if model == default else ""
            table.add_row(str(display_idx), f"{model}{marker}")
            
        console.print(table)
        
        # Prompt
        options = []
        if total_pages > 1: options.extend(["[n]ext", "[p]rev"])
        options.extend(["[f]ilter", "[c]lear filter", "or Enter ID"])
        
        prompt_text = ", ".join(options)
        val = click.prompt(prompt_text, default="n" if total_pages > 1 else "")
        val_clean = val.lower().strip()
        
        # Navigation
        if val_clean == 'n':
            current_page += 1
        elif val_clean == 'p':
            current_page -= 1
        elif val_clean == 'f':
            filter_query = click.prompt("Enter filter text", default="")
            display_pool = [m for m in all_models if filter_query.lower() in m.lower()]
            current_page = 0
        elif val_clean == 'c':
            filter_query = ""
            display_pool = all_models
            current_page = 0
        elif val_clean.isdigit():
            # Selection by ID
            sel_idx = int(val_clean) - 1
            if 0 <= sel_idx < len(display_pool):
                return display_pool[sel_idx]
            else:
                console.print(f"[red]Invalid ID: {val_clean}. Must be between 1 and {len(display_pool)}[/red]")
                click.pause()
        else:
            # Manual entry or exact match
            if val in all_models:
                return val
            if click.confirm(f"Use manual model name '{val}'?"):
                return val

def run_model_assignment() -> None:
    """
    Interactive wizard to assign AI models to specific roles.
    Saves choices to vibe_manga_ai_config.json.
    """
    console.print(Rule("[bold magenta]AI Model Assignment Wizard[/bold magenta]"))
    
    # Fetch available models
    with console.status("[bold blue]Fetching available models..."):
        remote_models = get_available_models("remote")
        local_models = get_available_models("local")
    
    console.print(f"[green]Found {len(remote_models)} Remote models and {len(local_models)} Local models.[/green]")
    if not remote_models:
        console.print("[dim]Note: Remote discovery returned 0 models. Check your API key or Base URL.[/dim]")
    if not local_models:
        console.print("[dim]Note: Local discovery returned 0 models. If using Open WebUI (port 3000), ensure you have an API Key set in .env[/dim]")
    console.print("")
    
    current_config = load_ai_config()
    role_settings = current_config.get("roles", {})
    
    for role_name in ROLE_CONFIG.keys():
        console.print(Panel(f"[bold cyan]Configuring Role: {role_name}[/bold cyan]"))
        
        # Determine current setting
        defaults = ROLE_CONFIG[role_name]
        current = role_settings.get(role_name, {})
        curr_prov = current.get("provider", defaults["provider"])
        curr_mod = current.get("model", defaults["model"])
        
        console.print(f"Current: [yellow]{curr_prov}[/yellow] / [yellow]{curr_mod}[/yellow]")
        
        if not click.confirm(f"Change model for {role_name}?", default=False):
            continue
            
        # Select Provider
        prov_choice = click.prompt(
            "Select Provider", 
            type=click.Choice(["remote", "local"], case_sensitive=False),
            default=curr_prov
        )
        
        # Select Model
        available = remote_models if prov_choice == "remote" else local_models
        
        if not available:
            console.print(f"[red]No models found for {prov_choice}. Using manual entry.[/red]")
            mod_choice = click.prompt("Enter Model Name", default=curr_mod)
        else:
            mod_choice = select_model_interactive(available, default=curr_mod)
        
        role_settings[role_name] = {
            "provider": prov_choice,
            "model": mod_choice
        }
        console.print(f"[green]✓ Set {role_name} to {prov_choice} / {mod_choice}[/green]\n")

    # Save
    current_config["roles"] = role_settings
    save_ai_config(current_config)
    console.print("[bold green]Configuration saved successfully![/bold green]")

def get_library_root() -> str:
    """
    Gets the manga library root path from environment variables.

    Returns:
        The library root path string.

    Raises:
        SystemExit: If MANGA_LIBRARY_ROOT is not set.
    """
    root = os.getenv("MANGA_LIBRARY_ROOT")
    if not root:
        logger.error("MANGA_LIBRARY_ROOT is not set in .env file")
        console.print("[red]Error: MANGA_LIBRARY_ROOT is not set in .env file.[/red]")
        exit(1)
    return root

def run_scan_with_progress(
    root_path: str,
    description: str,
    use_cache: bool = True
) -> Library:
    """
    Runs a library scan with a rich progress bar and optional caching.

    Args:
        root_path: Path to the library root directory.
        description: Description text to show in progress bar.
        use_cache: If True, attempts to use cached scan results (default: True).

    Returns:
        Library object with scanned data.
    """
    root_path_obj = Path(root_path)

    # Try to load from cache if enabled
    if use_cache:
        logger.info("Checking for cached library scan...")
        cached_library = get_cached_library(root_path_obj)
        if cached_library:
            logger.info("Using cached library scan")
            console.print("[dim]Using cached scan (run with --no-cache to force refresh)[/dim]")
            return cached_library
        logger.info("No valid cache found, performing fresh scan")

    # Always try to load persistent state if it exists, to preserve external metadata
    # even during a fresh filesystem scan.
    existing_library = load_library_state(root_path_obj)

    # We will track running stats locally for the progress bar
    stats_cache = {"vols": 0, "size": 0}
    
    # Line 1: The visual progress bar
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    )
    
    # Line 2: The detailed stats
    status_text = Text("", style="dim")
    
    # Group them together
    display_group = Group(progress, status_text)

    with Live(display_group, console=console, refresh_per_second=PROGRESS_REFRESH_RATE):
        task_id = progress.add_task(description, total=None)

        def update_progress(current: int, total: int, series: Series) -> None:
            # Update total if we haven't yet (first callback)
            if progress.tasks[task_id].total is None:
                 progress.update(task_id, total=total)

            stats_cache["vols"] += series.total_volume_count
            stats_cache["size"] += series.total_size_bytes

            progress.update(task_id, completed=current)

            # Format Line 2
            task = progress.tasks[task_id]
            time_remaining = "-"
            if task.time_remaining is not None:
                time_remaining = str(datetime.timedelta(seconds=int(task.time_remaining)))

            gb = stats_cache["size"] / BYTES_PER_GB

            line2_str = f"{time_remaining} | {gb:.2f} GB | Vols: {stats_cache['vols']} | {series.name}"
            status_text.plain = line2_str

        logger.info(f"Starting library scan: {root_path}")
        library = scan_library(root_path, progress_callback=update_progress, existing_library=existing_library)
        logger.info(f"Scan complete: {library.total_series} series, {library.total_volumes} volumes")

        # Save to cache so subsequent runs are fast
        logger.info("Saving scan results to cache")
        save_library_cache(library)

        return library

def perform_deep_analysis(
    targets: List,
    deep: bool,
    verify: bool
) -> None:
    """
    Runs deep analysis (page counts) and/or verification (integrity check)
    on the targeted items. Updates them in-place.

    Args:
        targets: List of Library, Category, or Series objects to analyze.
        deep: If True, performs deep analysis (page counts).
        verify: If True, performs integrity verification.
    """
    if not (deep or verify):
        return

    # Flatten targets into a list of Series
    series_list: List[Series] = []

    def collect_series(item) -> None:
        if isinstance(item, Series):
            series_list.append(item)
        elif isinstance(item, Category):
            for s in item.series:
                collect_series(s)
            for sub in item.sub_categories:
                collect_series(sub)
        elif isinstance(item, Library):
            for cat in item.categories:
                collect_series(cat)

    for t in targets:
        collect_series(t)

    # Dedup based on path (Series is unhashable)
    unique_map = {}
    for s in series_list:
        if s.path not in unique_map:
            unique_map[s.path] = s
    series_list = list(unique_map.values())

    if not series_list:
        logger.debug("No series to analyze")
        return

    action_name = "Verifying" if verify else "Analyzing"
    logger.info(f"{action_name} {len(series_list)} series...")
    
    # Progress Bar for Deep Scan
    progress = Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]{action_name} Content..."),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.description}")
    )

    with Live(progress, console=console, refresh_per_second=DEEP_ANALYSIS_REFRESH_RATE):
        task_id = progress.add_task("", total=len(series_list))

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_series = {
                executor.submit(enrich_series, s, deep=deep, verify=verify): s
                for s in series_list
            }

            completed = 0
            for future in concurrent.futures.as_completed(future_to_series):
                series = future_to_series[future]
                completed += 1
                try:
                    future.result()  # Propagate exceptions if any
                except Exception as e:
                    logger.error(f"Error analyzing {series.name}: {e}", exc_info=True)
                    console.print(f"[red]Error analyzing {series.name}: {e}[/red]")

                progress.update(task_id, completed=completed, description=f"[dim]{series.name}[/dim]")

    logger.info(f"Deep analysis complete: {completed} series processed")

def select_category_manual(library: Library) -> Tuple[str, str]:
    """Interactive selector for manual categorization."""
    categories = get_category_list(library)
    categories.sort()
    
    console.print("\n[bold cyan]Available Categories:[/bold cyan]")
    
    current_page = 0
    page_size = 20
    display_pool = categories
    
    while True:
        total_pages = max(1, (len(display_pool) + page_size - 1) // page_size)
        if current_page >= total_pages: current_page = 0
        if current_page < 0: current_page = total_pages - 1
        
        start_idx = current_page * page_size
        end_idx = start_idx + page_size
        page_items = display_pool[start_idx:end_idx]
        
        table = Table(title=f"Select Category (Page {current_page+1}/{total_pages})", box=box.SIMPLE)
        table.add_column("ID", justify="right", style="cyan", width=4)
        table.add_column("Category/Sub", style="white")
        
        for i, cat in enumerate(page_items):
            display_idx = start_idx + i + 1
            table.add_row(str(display_idx), cat)
            
        console.print(table)
        console.print("[dim]Options: [n]ext, [p]rev, [f]ilter, [c]lear filter, [m]anual entry, or Enter ID[/dim]")
        
        val = click.prompt("Selection", default="n" if total_pages > 1 else "").lower().strip()
        
        if val == 'n': current_page += 1
        elif val == 'p': current_page -= 1
        elif val == 'f':
            filter_query = click.prompt("Filter", default="")
            display_pool = [c for c in categories if filter_query.lower() in c.lower()]
            current_page = 0
        elif val == 'c':
            filter_query = ""
            display_pool = categories
            current_page = 0
        elif val == 'm':
            # Fully manual entry
            raw = click.prompt("Enter Category/SubCategory (e.g. Manga/Action)")
            parts = raw.split('/')
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
            else:
                return raw.strip(), "Other"
        elif val.isdigit():
            idx = int(val) - 1
            if 0 <= idx < len(display_pool):
                selected = display_pool[idx]
                parts = selected.split('/')
                return parts[0], parts[1]

@click.group()
def cli():
    """VibeManga: A CLI for managing your manga collection."""
    pass

@cli.command()
@click.argument("query", required=False)
@click.option("--force-update", is_flag=True, help="Force re-download of metadata from Jikan/AI.")
@click.option("--trust", "trust_jikan", is_flag=True, help="Trust Jikan if name is perfect match (skips AI Supervisor).")
@click.option("--all", "process_all", is_flag=True, help="Process all series in the library.")
@click.option("--model-assign", is_flag=True, help="Configure AI models for specific roles before running.")
def metadata(query: Optional[str], force_update: bool, trust_jikan: bool, process_all: bool, model_assign: bool) -> None:
    """
    Fetches and saves metadata (genres, authors, status) for series.
    Creates a 'series.json' file in each series directory.
    """
    if model_assign:
        run_model_assignment()
        if not query and not process_all:
             return

    logger.info(f"Metadata command started (query={query}, force={force_update}, all={process_all}, trust={trust_jikan})")
    
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
        
        for series in targets:
            progress.update(task, description=f"[green]Fetching: {series.name}[/green]")
            detail_text.plain = "  → Starting..."
            
            def update_detail(msg: str):
                detail_text.plain = ""
                detail_text.append("  → ")
                if "[" in msg and "]" in msg:
                    detail_text.append(Text.from_markup(msg))
                else:
                    detail_text.append(msg)

            try:
                meta, source = get_or_create_metadata(
                    series.path, 
                    series.name, 
                    force_update=force_update, 
                    trust_jikan=trust_jikan,
                    status_callback=update_detail
                )
                
                # Update status with source
                color = "green" if "Trusted" in source or "Local" in source else "cyan" if "Jikan" in source else "magenta"
                detail_text.plain = ""
                detail_text.append(Text.from_markup(f"  → [{color}]Completed via {source}[/{color}]"))

                # Add to summary table (limit rows if too many)
                if len(targets) <= 20 or force_update:
                    genres = ", ".join((meta.genres or [])[:3])
                    authors = ", ".join((meta.authors or [])[:2])
                    status_color = "green" if meta.status == "Completed" else "yellow"
                    table.add_row(
                        series.name,
                        f"[{status_color}]{meta.status}[/{status_color}]",
                        source,
                        genres,
                        authors
                    )
            except Exception as e:
                logger.error(f"Error fetching metadata for {series.name}: {e}")
                detail_text.plain = ""
                detail_text.append(Text.from_markup("  → [red]Error occurred[/red]"))
            
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

@cli.command()
@click.argument("query", required=False)
@click.option("--auto", is_flag=True, help="Automatically move folders without asking.")
@click.option("--simulate", is_flag=True, help="Dry run: show where folders would be moved without moving them.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan.")
@click.option("--model-assign", is_flag=True, help="Configure AI models for specific roles before running.")
@click.option("--pause", is_flag=True, help="Pause before each categorization decision.")
def categorize(query: Optional[str], auto: bool, simulate: bool, no_cache: bool, model_assign: bool, pause: bool) -> None:
    """
    Automatically sorts series from 'Uncategorized' folders into the main library using AI.
    """
    if model_assign:
        run_model_assignment()
        # Categorize can run without query, so we don't necessarily return
        # But if no query/auto is provided, default categorize behavior is to scan anyway.
        
    logger.info(f"Categorize command started (query={query}, auto={auto}, simulate={simulate}, no_cache={no_cache}, pause={pause})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning for Uncategorized Series...",
        use_cache=not no_cache
    )

    # 1. Find Uncategorized Series
    uncategorized_series: List[Tuple[Category, Category, Series]] = []
    
    for main in library.categories:
        if main.name == "Uncategorized":
            for sub in main.sub_categories:
                for s in sub.series:
                    if not query or query.lower() in s.name.lower():
                        uncategorized_series.append((main, sub, s))
        else:
             for sub in main.sub_categories:
                 if sub.name.startswith("Pulled-"):
                      for s in sub.series:
                          if not query or query.lower() in s.name.lower():
                               uncategorized_series.append((main, sub, s))

    if not uncategorized_series:
        console.print("[yellow]No series found in 'Uncategorized' or 'Pulled-*' folders.[/yellow]")
        return

    console.print(f"[cyan]Found {len(uncategorized_series)} series to categorize...[/cyan]")
    if simulate:
        console.print("[bold yellow][SIMULATION MODE] No folders will be moved.[/bold yellow]\n")

    import shutil
    countcurserries = 1
    for main, sub, series in uncategorized_series:
        console.print(Rule(f"[bold blue][{countcurserries} of {len(uncategorized_series)}] Categorizing: {series.name}[/bold blue]"))
        countcurserries += 1     
        user_feedback = None
        should_move = False
        final_cat_path = None
        
        results = None # Result cache
        
        while True: # Interactive Loop for this series
            try:
                if not results:
                    results = suggest_category(series, library, user_feedback=user_feedback)
                    if not results or not results.get("consensus"):
                        console.print(f"[red]Failed to get AI consensus for {series.name}. Skipping.[/red]")
                        break # Skip this series
                    
                consensus = results["consensus"]
                final_cat = sanitize_filename(consensus.get("final_category", "Manga"))
                final_sub = sanitize_filename(consensus.get("final_sub_category", "Other"))
                reason = consensus.get("reason", "No reason provided.")
                conf = consensus.get("confidence_score", 0.0)
                
                # Moderation Check
                mod = results.get("moderation", {})
                is_flagged = mod.get("classification") != "SAFE"
                is_illegal = mod.get("classification") == "ILLEGAL"
                
                # --- VISUALIZATION ---
                meta_obj = results.get("metadata")
                
                # 1. Metadata Summary
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
                
                # Helpers for panels
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

                console.print(meta_text)
                if syn_panel: console.print(syn_panel)
                console.print(council_grid)
                console.print(cons_panel)
                # ---------------------

                # Auto-Delete on Mod Flag (Handle before menu loop)
                if is_illegal and auto:
                    console.print(Rule("[bold red]AUTO-MODE: ILLEGAL CONTENT DETECTED[/bold red]"))
                    console.print(Panel(json.dumps(mod, indent=2), title="Moderator Full Response", border_style="red"))
                    console.print(f"[bold red]DELETING {series.name}...[/bold red]")
                    
                    if not simulate:
                        try:
                            shutil.rmtree(series.path)
                            console.print("[red]Series deleted.[/red]")
                        except Exception as e:
                            console.print(f"[red]Failed to delete: {e}[/red]")
                    else:
                        console.print("[yellow][SIMULATE] Would DELETE series.[/yellow]")
                    break # Done with this series
                
                # Auto-Move (if no flag)
                if auto:
                    if pause:
                        console.print("[dim]Paused. Press Enter to continue...[/dim]")
                        click.pause()
                        
                    final_cat_path = Path(root_path) / final_cat / final_sub / series.name
                    should_move = True
                    break

                # Inner Menu Loop (Display & Choice)
                action_taken = False
                while True:
                    # Improved Menu with Table
                    console.print("\n[bold]Options:[/bold]")
                    menu_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
                    menu_table.add_column("Key", style="bold cyan")
                    menu_table.add_column("Action")
                    menu_table.add_column("Description", style="dim")
                    
                    menu_table.add_row(r"\[a]", "Accept", "Move to suggestion")
                    menu_table.add_row(r"\[b]", "Reject", "Retry with instruction")
                    menu_table.add_row(r"\[c]", "Blacklist", "Delete Series")
                    menu_table.add_row(r"\[d]", "Info", "Show full AI analysis")
                    menu_table.add_row(r"\[e]", "Manual", "Select category manually")
                    menu_table.add_row(r"\[s]", "Skip", "Skip this series")
                    menu_table.add_row(r"\[q]", "Quit", "Exit program")
                    console.print(menu_table)
                    
                    choice = click.prompt("Select action", default="a", show_default=True).lower().strip()
                    
                    if choice == 'a': # Accept
                        final_cat_path = Path(root_path) / final_cat / final_sub / series.name
                        should_move = True
                        action_taken = True
                        break
                        
                    elif choice == 'b': # Reject
                        fb = click.prompt("Enter instruction for AI (e.g., 'It's actually a Shoujo')")
                        if is_flagged:
                            fb += " (Override moderation constraints)"
                        user_feedback = fb
                        console.print("[yellow]Retrying with feedback...[/yellow]")
                        results = None # Force re-fetch
                        action_taken = False # Break inner, loop outer
                        break
                        
                    elif choice == 'c': # Blacklist / Delete
                        if click.confirm(f"Are you sure you want to PERMANENTLY DELETE '{series.name}'?", default=False):
                            if not simulate:
                                try:
                                    shutil.rmtree(series.path)
                                    console.print("[red]Series deleted.[/red]")
                                except Exception as e:
                                    console.print(f"[red]Failed to delete: {e}[/red]")
                            else:
                                console.print("[yellow][SIMULATE] Would DELETE series.[/yellow]")
                            action_taken = True
                            break # Done with this series
                        else:
                            continue # Re-loop inner menu
                            
                    elif choice == 'd': # Info
                        console.print(Rule("[bold]AI Analysis Details[/bold]"))
                        console.print(Panel(json.dumps(mod, indent=2), title="Moderator", border_style="red" if is_flagged else "green"))
                        console.print(Panel(json.dumps(results.get("practical"), indent=2), title="Practical", border_style="blue"))
                        console.print(Panel(json.dumps(results.get("creative"), indent=2), title="Creative", border_style="magenta"))
                        console.print(Panel(json.dumps(consensus, indent=2), title="Consensus", border_style="yellow"))
                        click.pause()
                        continue # Re-loop inner menu (results valid)
                        
                    elif choice == 'e': # Manual
                        manual = manual_select_category(library)
                        if manual:
                             m_cat, m_sub = manual
                             final_cat_path = Path(root_path) / m_cat / m_sub / series.name
                             should_move = True
                             action_taken = True
                             break
                        else:
                             continue # Re-loop inner
                        
                    elif choice == 's': # Skip
                        console.print("[yellow]Skipped.[/yellow]")
                        action_taken = True
                        break
                        
                    elif choice == 'q': # Quit
                        console.print("[yellow]Quitting...[/yellow]")
                        return

                if action_taken:
                    break
                # If not action_taken, we loop outer (re-fetching AI if results=None)

            except Exception as e:
                logger.error(f"Error during categorization of {series.name}: {e}", exc_info=True)
                console.print(f"[red]Error: {e}[/red]")
                break

        # Perform Move if accepted
        if should_move and final_cat_path:
            if simulate:
                console.print(f"[yellow][SIMULATE][/yellow] Would move to: [dim]{final_cat_path}[/dim]")
                continue

            if final_cat_path.exists():
                console.print(f"[yellow]Target directory exists: {final_cat_path}[/yellow]")
                console.print("[dim]Attempting to merge contents...[/dim]")
                
                moved_count = 0
                conflict_count = 0
                
                try:
                    for item in series.path.iterdir():
                        dest = final_cat_path / item.name
                        if dest.exists():
                            console.print(f"  [red]Skipping {item.name} (Destination exists)[/red]")
                            conflict_count += 1
                        else:
                            shutil.move(str(item), str(dest))
                            moved_count += 1
                    
                    console.print(f"[green]✓ Merged {moved_count} items.[/green]")
                    if conflict_count > 0:
                        console.print(f"[yellow]! {conflict_count} items skipped due to conflicts.[/yellow]")
                    
                    # Check if source is empty and remove if so
                    if not any(series.path.iterdir()):
                        series.path.rmdir()
                        console.print("[dim]Source directory removed.[/dim]")
                    else:
                        console.print("[yellow]Source directory not empty (conflicts remaining). Kept.[/yellow]")
                        
                except Exception as e:
                    console.print(f"[red]Error during merge: {e}[/red]")

            else:
                console.print(f"[dim]Moving to: {final_cat_path}[/dim]")
                final_cat_path.parent.mkdir(parents=True, exist_ok=True)
                series.path.rename(final_cat_path)
                console.print("[green]✓ Move successful.[/green]")

    console.print(Rule("[bold magenta]Categorization Complete[/bold magenta]"))

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

@cli.command()
@click.argument("query", required=False)
@click.option("--continuity", is_flag=True, help="Check for missing volumes/chapters.")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
@click.option("--no-metadata", is_flag=True, help="Suppress metadata insights from series.json.")
def stats(query: Optional[str], continuity: bool, deep: bool, verify: bool, no_cache: bool, no_metadata: bool) -> None:
    """
    Show statistics.
    If QUERY is provided, shows stats for the matching Category, Sub-Category, or Series.
    The highest-level match takes precedence (Main > Sub > Series).
    """
    logger.info(f"Stats command started (query={query}, continuity={continuity}, deep={deep}, verify={verify}, no_cache={no_cache}, no_meta={no_metadata})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library Structure...",
        use_cache=not no_cache
    )
    
    # 1. Identify Targets
    targets = []
    target_type = "Library" # Library, Main, Sub, Series
    
    if not query:
        targets = [library]
        target_type = "Library"
    else:
        q = query.lower().strip()
        
        # Level 1: Main Categories
        matches = [c for c in library.categories if q in c.name.lower()]
        if matches:
            targets = matches
            target_type = "Main Category"
        
        # Level 2: Sub Categories
        if not targets:
            matches = []
            for main in library.categories:
                for sub in main.sub_categories:
                    if q in sub.name.lower():
                        matches.append(sub)
            if matches:
                targets = matches
                target_type = "Sub Category"
        
        # Level 3: Series
        if not targets:
            matches = []
            for main in library.categories:
                for sub in main.sub_categories:
                    for series in sub.series:
                        if q in series.name.lower():
                            matches.append(series)
            if matches:
                targets = matches
                target_type = "Series"
    
    if not targets:
        logger.warning(f"No matches found for query: {query}")
        console.print(f"[red]No statistics found for '{query}'[/red]")
        return
        
    # 2. Perform Deep Analysis if requested
    if deep or verify:
        perform_deep_analysis(targets, deep, verify)

    # 3. Aggregation
    total_series = 0
    total_volumes = 0
    total_chapters = 0
    total_units = 0
    total_size = 0
    total_pages = 0
    complete_series = 0
    
    # Metadata Aggregators
    genres_counter = Counter()
    authors_counter = Counter()
    status_counter = Counter()
    tags_counter = Counter()
    demographics_counter = Counter()
    years_counter = Counter()
    synopsis_words_counter = Counter()
    metadata_count = 0

    # Helper to count complete series and collect metadata
    def get_all_series(t_list, t_type):
        all_s = []
        for t in t_list:
            if t_type == "Library":
                for cat in t.categories:
                    for sub in cat.sub_categories:
                        all_s.extend(sub.series)
            elif t_type == "Main Category":
                for sub in t.sub_categories:
                    all_s.extend(sub.series)
            elif t_type == "Sub Category":
                all_s.extend(t.series)
            elif t_type == "Series":
                all_s.append(t)
        return all_s

    all_target_series = get_all_series(targets, target_type)

    if continuity:
        with console.status("[bold blue]Checking continuity..."):
            for s in all_target_series:
                if not find_gaps(s):
                    complete_series += 1

    if not no_metadata:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("[bold blue]Aggregating metadata insights...", total=len(all_target_series))
            for s in all_target_series:
                meta = load_local_metadata(s.path)
                if meta:
                    metadata_count += 1
                    for g in meta.genres: genres_counter[g] += 1
                    for a in meta.authors: authors_counter[a] += 1
                    for t in meta.tags: tags_counter[t] += 1
                    for d in meta.demographics: 
                        if d in VALID_DEMOGRAPHICS:
                            # Standardize Shonen
                            label = "Shonen" if d == "Shounen" else d
                            demographics_counter[label] += 1
                    if meta.release_year: years_counter[meta.release_year] += 1
                    if meta.status: status_counter[meta.status] += 1
                    
                    if meta.synopsis:
                        # Simple word tokenization and cleaning
                        words = meta.synopsis.lower().split()
                        for w in words:
                            cleaned = CLEAN_WORD_RE.sub('', w)
                            if cleaned and len(cleaned) > 2 and cleaned not in STOP_WORDS:
                                synopsis_words_counter[cleaned] += 1
                progress.advance(task)

    from .analysis import classify_unit
    for t in all_target_series:
        total_series += 1
        total_volumes += t.total_volume_count
        total_size += t.total_size_bytes
        total_pages += t.total_page_count
        
        # Aggregate chapters and units
        all_vols = t.volumes + [v for sg in t.sub_groups for v in sg.volumes]
        for v in all_vols:
            v_nums, c_nums, u_nums = classify_unit(v.name)
            if c_nums: total_chapters += len(c_nums)
            if u_nums: total_units += len(u_nums)

    total_gb = total_size / BYTES_PER_GB
    logger.info(f"Stats aggregated: {total_series} series, {total_volumes} volumes, {total_gb:.2f} GB")

    # 4. Display Header & Cards
    title_str = f"Stats: [cyan]{query}[/cyan]" if query else "Library Stats"
    console.print(Rule(f"[bold magenta]{title_str}[/bold magenta]"))
    
    if len(targets) == 1 and hasattr(targets[0], 'path'):
         try:
            rel = targets[0].path.relative_to(root_path)
            path_str = f"ROOT{os.sep}{rel}"
         except (ValueError, AttributeError):
            path_str = str(targets[0].path)
         console.print(Align(f"[dim]{path_str}[/dim]", align="center"))
    elif query:
         console.print(Align(f"[dim]Aggregated from {len(targets)} matches[/dim]", align="center"))
    else:
         console.print(Align(f"[dim]{library.path}[/dim]", align="center"))
         
    console.print("")

    def make_stat_panel(value, label, color="white"):
        return Panel(
            Align(f"[bold {color}]{value}[/bold {color}]\n[dim]{label}[/dim]", align="center"),
            border_style=f"dim {color}",
            expand=True
        )

    # Adjust cards based on what we are showing
    cards = []
    if target_type != "Series":
        cards.append(make_stat_panel(str(total_series), "Total Series", "cyan"))
        
    cards.append(make_stat_panel(str(total_volumes), "Total Volumes", "green"))
    cards.append(make_stat_panel(f"{total_chapters:,}", "Total Chapters", "magenta"))
    cards.append(make_stat_panel(str(total_units), "Total Units", "dim"))

    if deep:
        cards.append(make_stat_panel(f"{total_pages:,}", "Total Pages", "blue"))
    cards.append(make_stat_panel(f"{total_gb:.2f} GB", "Total Size", "yellow"))
    
    if target_type == "Library":
        cards.append(make_stat_panel(str(library.total_categories), "Categories", "magenta"))
    elif target_type == "Main Category":
        sub_count = sum(len(t.sub_categories) for t in targets)
        cards.append(make_stat_panel(str(sub_count), "Sub Categories", "magenta"))
    
    if continuity and total_series > 0:
        percent = (complete_series / total_series) * 100
        color = "green" if percent == 100 else "yellow" if percent > 80 else "red"
        cards.append(make_stat_panel(f"{percent:.1f}%", "Continuity", color))

    # Cards removed from here, will be printed next to Breakdown Table
    console.print("")

        # Metadata Insights Section
    if not no_metadata and metadata_count > 0:
        console.print(Rule("[bold cyan]Metadata Insights[/bold cyan]", style="dim cyan"))
        
        from rich.bar import Bar

        # Manual mapping for much darker versions of standard colors to ensure 
        # strong visual contrast for bar segregation.
        DIM_MAP = {
            "cyan": "#004d4d",    # Dark Cyan
            "magenta": "#4d004d", # Dark Magenta
            "yellow": "#4d4d00",  # Dark Yellow
            "blue": "#00004d",    # Dark Blue
            "green": "#003300",   # Dark Green
            "white": "#444444"    # Dark Gray
        }

        def make_insight_table(title: str, counter: Counter, label: str, color: str, limit: int = 10, offset: int = 0):
            # Header and Columns use the theme color consistently
            t = Table(title=title, box=box.SIMPLE, header_style=f"bold {color}", expand=True)
            t.add_column(label, ratio=3, style=f"bold {color}")
            t.add_column("Count", justify="right", style=color, ratio=1)
            t.add_column("Dist.", ratio=3) 
            
            # Get all common items and slice
            all_items = counter.most_common(offset + limit)
            items = all_items[offset:offset + limit]
            
            max_val = max(counter.values()) if counter else 1
            dim_color = DIM_MAP.get(color, color)

            for i, (name, count) in enumerate(items):
                # Alternate bar color for segregation, but keep text color stable
                bar_color = color if i % 2 == 0 else dim_color
                t.add_row(
                    str(name), 
                    str(count), 
                    Bar(max_val, 0, count, color=bar_color)
                )
            return t

        # Group as requested: Genres/Authors, Status/Demographics, Tags 1-10/Tags 11-20
        insight_tables = [
            make_insight_table("Top Genres", genres_counter, "Genre", "cyan"),
            make_insight_table("Top Authors", authors_counter, "Author", "magenta"),
            make_insight_table("Status Dist.", status_counter, "Status", "yellow"),
            make_insight_table("Demographics", demographics_counter, "Type", "blue"),
            make_insight_table("Top Tags (1-10)", tags_counter, "Tag", "green"),
            make_insight_table("Top Tags (11-20)", tags_counter, "Tag", "green", offset=10)
        ]

        # Print in pairs (2 columns per row) using a container table to force 2-column layout
        container = Table.grid(expand=True)
        container.add_column(ratio=1)
        container.add_column(ratio=1)

        for i in range(0, len(insight_tables), 2):
            pair = insight_tables[i:i+2]
            if len(pair) == 2:
                container.add_row(pair[0], pair[1])
            else:
                container.add_row(pair[0], "")
            container.add_row("", "") # Spacer row

        console.print(container)

        # Row 3: Synopsis Keyword Analysis
        if synopsis_words_counter:
            top_words = synopsis_words_counter.most_common(50)
            word_columns = []
            
            # Use 5 columns for the top 50 keywords
            num_cols = 5
            per_col = (len(top_words) + num_cols - 1) // num_cols
            
            for i in range(0, len(top_words), per_col):
                chunk = top_words[i:i+per_col]
                t = Table(box=None, show_header=False)
                t.add_column("W", style="italic white")
                t.add_column("C", style="dim", justify="right")
                for w, c in chunk:
                    t.add_row(w, str(c))
                word_columns.append(t)
            
            console.print(Panel(
                Columns(word_columns, padding=(0, 2), expand=True), 
                title="[bold]Top 50 Narrative Keywords[/bold]", 
                border_style="dim"
            ))

    # 5. Breakdown Table & Side Cards
    table_title = f"Breakdown ({target_type})"
    t = Table(title=table_title, box=box.SIMPLE_HEAD, show_lines=False, header_style="bold cyan")
    
    if target_type == "Library":
        # Show Main Categories
        t.add_column("Main Category", style="white bold")
        t.add_column("Subs", justify="right", style="dim")
        t.add_column("Series", justify="right", style="cyan")
        t.add_column("Volumes", justify="right", style="green")
        if continuity:
            t.add_column("Cont.", justify="right")
        if deep:
            t.add_column("Pages", justify="right", style="blue")
        t.add_column("Size (GB)", justify="right", style="yellow")
        
        # Sort by total size (descending)
        sorted_cats = sorted(library.categories, key=lambda c: c.total_size_bytes, reverse=True)

        for cat in sorted_cats:
            cat_gb = cat.total_size_bytes / BYTES_PER_GB
            row = [cat.name, str(len(cat.sub_categories)), str(cat.total_series_count), str(cat.total_volume_count)]
            if continuity:
                cat_series = []
                for sub in cat.sub_categories: cat_series.extend(sub.series)
                comp = sum(1 for s in cat_series if not find_gaps(s))
                total = len(cat_series)
                perc = (comp / total * 100) if total > 0 else 0
                color = "green" if perc == 100 else "yellow" if perc > 80 else "red"
                row.append(f"[{color}]{perc:.0f}%[/{color}]")
            if deep:
                row.append(f"{cat.total_page_count:,}")
            row.append(f"{cat_gb:.2f}")
            t.add_row(*row)

    elif target_type == "Main Category":
        # Show Sub Categories
        t.add_column("Sub Category", style="white bold")
        t.add_column("Parent", style="dim")
        t.add_column("Series", justify="right", style="cyan")
        t.add_column("Volumes", justify="right", style="green")
        if continuity:
            t.add_column("Cont.", justify="right")
        if deep:
            t.add_column("Pages", justify="right", style="blue")
        t.add_column("Size (GB)", justify="right", style="yellow")
        
        for main in targets:
            for sub in main.sub_categories:
                cat_gb = sub.total_size_bytes / BYTES_PER_GB
                row = [sub.name, main.name, str(sub.total_series_count), str(sub.total_volume_count)]
                if continuity:
                    comp = sum(1 for s in sub.series if not find_gaps(s))
                    total = len(sub.series)
                    perc = (comp / total * 100) if total > 0 else 0
                    color = "green" if perc == 100 else "yellow" if perc > 80 else "red"
                    row.append(f"[{color}]{perc:.0f}%[/{color}]")
                if deep:
                    row.append(f"{sub.total_page_count:,}")
                row.append(f"{cat_gb:.2f}")
                t.add_row(*row)

    elif target_type == "Sub Category":
        # Show Series
        t.add_column("Series", style="white bold")
        t.add_column("Location", style="dim")
        t.add_column("Volumes", justify="right", style="green")
        if continuity:
            t.add_column("Cont.", justify="center")
        if deep:
            t.add_column("Pages", justify="right", style="blue")
        t.add_column("Size (MB)", justify="right", style="yellow")
        
        for sub in targets:
            parent_name = sub.parent.name if sub.parent else "?"
            for series in sub.series:
                s_mb = series.total_size_bytes / BYTES_PER_MB
                row = [series.name, f"{parent_name} > {sub.name}", str(series.total_volume_count)]
                if continuity:
                    gaps = find_gaps(series)
                    row.append("[green]✓[/green]" if not gaps else "[red]✗[/red]")
                if deep:
                    row.append(f"{series.total_page_count:,}")
                row.append(f"{s_mb:.2f}")
                t.add_row(*row)

    elif target_type == "Series":
        # Show Contents (SubGroups or Volumes)
        t.add_column("Name", style="white bold")
        t.add_column("Type", style="dim")
        if continuity:
             t.add_column("Cont.", justify="center")
        if deep:
            t.add_column("Pages", justify="right", style="blue")
        t.add_column("Size (MB)", justify="right", style="yellow")
        
        for series in targets:
            # Show SubGroups first
            for sg in series.sub_groups:
                 sg_mb = sg.total_size_bytes / BYTES_PER_MB
                 row = [sg.name, "Sub-Group"]
                 if continuity:
                      # We don't have a direct find_gaps for SubGroup yet, but we can fake it
                      # or just show '-'
                      row.append("-")
                 if deep:
                     row.append(f"{sg.total_page_count:,}")
                 row.append(f"{sg_mb:.2f}")
                 t.add_row(*row)

            if not series.sub_groups:
                vol_mb = sum(v.size_bytes for v in series.volumes) / BYTES_PER_MB
                row = [f"{len(series.volumes)} Volumes", "Files"]
                if continuity:
                     gaps = find_gaps(series)
                     row.append("[green]✓[/green]" if not gaps else "[red]✗[/red]")
                if deep:
                    row.append(f"{series.total_page_count:,}")
                row.append(f"{vol_mb:.2f}")
                t.add_row(*row)
            else:
                 if series.volumes:
                     vol_mb = sum(v.size_bytes for v in series.volumes) / BYTES_PER_MB
                     vol_pages = sum(v.page_count for v in series.volumes if v.page_count)
                     row = [f"{len(series.volumes)} Extra Volumes", "Files"]
                     if continuity:
                          row.append("-")
                     if deep:
                         row.append(f"{vol_pages:,}")
                     row.append(f"{vol_mb:.2f}")
                     t.add_row(*row)

    # Reorganize cards into a 3x2 (or similar) grid for the side panel
    card_grid = Table.grid(padding=(0, 1))
    card_grid.add_column(ratio=1)
    card_grid.add_column(ratio=1)
    
    # Fill grid rows (2 panels per row)
    for i in range(0, len(cards), 2):
        row_items = cards[i:i+2]
        if len(row_items) == 2:
            card_grid.add_row(row_items[0], row_items[1])
        else:
            card_grid.add_row(row_items[0], "")

    # Side panel content (Grid + Footnote)
    side_content = [card_grid]
    if not no_metadata and metadata_count > 0:
        side_content.append(Text("")) # Spacer
        side_content.append(Align(f"[dim]Insights: {metadata_count}/{total_series} series with series.json[/dim]", align="right"))

    # Final side-by-side layout: [Breakdown Table] [Card Grid + Footnote]
    final_layout = Table.grid(expand=True, padding=(0, 2))
    final_layout.add_column(ratio=3) # Table gets more space
    final_layout.add_column(ratio=2) # Cards get enough space for 2-column grid
    final_layout.add_row(t, Group(*side_content))

    console.print(final_layout)

@cli.command()
@click.option("--depth", default=DEFAULT_TREE_DEPTH, help="How deep to show the tree (1=Main, 2=Sub, 3=Series, 4=SubGroups).")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
def tree(depth: int, deep: bool, verify: bool, no_cache: bool) -> None:
    """Visualizes the library structure."""
    logger.info(f"Tree command started (depth={depth}, deep={deep}, verify={verify}, no_cache={no_cache})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Building Tree...",
        use_cache=not no_cache
    )

    if deep or verify:
        # For tree, we analyze everything in the library since there is no query filter
        perform_deep_analysis([library], deep, verify)

    root_tree = Tree(f":open_file_folder: [bold]{library.path.name}[/bold]")

    for main_cat in library.categories:
        main_node = root_tree.add(f":file_folder: [yellow]{main_cat.name}[/yellow]")
        
        if depth >= 2:
            for sub_cat in main_cat.sub_categories:
                sub_node = main_node.add(f":file_folder: [cyan]{sub_cat.name}[/cyan] ({sub_cat.total_series_count} series)")
                
                if depth >= 3:
                    for series in sub_cat.series:
                        series_info = f"{series.name}"
                        if series.is_complex:
                            series_info += f" [dim]({len(series.sub_groups)} sub-groups)[/dim]"
                        else:
                            series_info += f" [dim]({len(series.volumes)} vols)[/dim]"
                            
                        series_node = sub_node.add(f":book: {series_info}")
                        
                        if depth >= 4:
                            for sg in series.sub_groups:
                                series_node.add(f":file_folder: [dim]{sg.name}[/dim] ({len(sg.volumes)} vols)")

    console.print(root_tree)

@cli.command()
@click.argument("series_name")
@click.option("--showfiles", is_flag=True, help="Show individual files in the tree view.")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
@click.option("--no-metadata", is_flag=True, help="Suppress display of metadata from series.json.")
def show(series_name: str, showfiles: bool, deep: bool, verify: bool, no_cache: bool, no_metadata: bool) -> None:
    """Finds a specific series and shows its details, including gaps and updates."""
    logger.info(f"Show command started (series_name={series_name}, showfiles={showfiles}, deep={deep}, verify={verify}, no_cache={no_cache}, no_meta={no_metadata})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        f"[bold green]Searching for '{series_name}'...",
        use_cache=not no_cache
    )

    found = []
    found_series_objects = []  # For deep analysis

    norm_query = semantic_normalize(series_name)

    for main_cat in library.categories:
        for sub_cat in main_cat.sub_categories:
            for series in sub_cat.series:
                norm_series = semantic_normalize(series.name)
                if norm_query and norm_query in norm_series:
                    found.append((main_cat, sub_cat, series))
                    found_series_objects.append(series)
                elif series_name.lower() in series.name.lower():
                    # Fallback to simple lower case substring
                    found.append((main_cat, sub_cat, series))
                    found_series_objects.append(series)

    if not found:
        logger.warning(f"No series found matching: {series_name}")
        console.print(f"[red]No series found matching '{series_name}'[/red]")
        return

    logger.info(f"Found {len(found)} matching series")
        
    if deep or verify:
        perform_deep_analysis(found_series_objects, deep, verify)

    for i, (main, sub, series) in enumerate(found):
        # Small gap between results
        if i > 0:
            console.print("")

        # Attempt to load metadata
        meta = None
        if not no_metadata:
            meta = load_local_metadata(series.path)

        title_text = f"[bold]Result: {series.name}[/bold]"
        if meta and meta.title != "Unknown" and meta.title.lower() != series.name.lower():
            title_text += f" [dim]({meta.title})[/dim]"

        console.print(Panel(title_text, expand=False, border_style="cyan"))
        
        content_elements = []

        # Metadata Summary (Top Panel)
        if meta:
            meta_table = Table.grid(padding=(0, 2))
            meta_table.add_column(style="bold cyan")
            meta_table.add_column()
            
            if meta.authors:
                meta_table.add_row("Authors:", ", ".join(meta.authors))
            if meta.release_year:
                meta_table.add_row("Year:", str(meta.release_year))
            if meta.status:
                status_color = "green" if meta.status == "Completed" else "yellow"
                meta_table.add_row("Status:", f"[{status_color}]{meta.status}[/{status_color}]")
            if meta.genres:
                meta_table.add_row("Genres:", ", ".join(meta.genres[:5]))
            
            # External Links
            links = []
            if meta.mal_id: links.append(f"[blue][link=https://myanimelist.net/manga/{meta.mal_id}]MAL[/link][/blue]")
            if meta.anilist_id: links.append(f"[blue][link=https://anilist.co/manga/{meta.anilist_id}]AniList[/link][/blue]")
            if links:
                meta_table.add_row("Links:", " | ".join(links))

            content_elements.append(meta_table)
            
            if meta.synopsis:
                # Truncate synopsis if it's too long
                syn = meta.synopsis
                if len(syn) > 400:
                    syn = syn[:397] + "..."
                content_elements.append(Padding(Text(syn, style="dim italic", justify="left"), (1, 0, 1, 0)))
            
            content_elements.append(Rule(style="dim"))

        # Technical Details Table
        table = Table(box=box.ROUNDED)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")
        
        # Display simplified path
        try:
            rel_path = series.path.relative_to(root_path)
            display_path = f"ROOT{os.sep}{rel_path}"
        except ValueError:
            display_path = str(series.path)
            
        table.add_row("Path", display_path)
        table.add_row("Category", f"{main.name} -> {sub.name}")
        table.add_row("Direct Volumes", str(len(series.volumes)))

        if series.sub_groups:
            sub_groups_str = "\n".join([f"{sg.name} ({len(sg.volumes)} vols)" for sg in series.sub_groups])
            table.add_row("Sub Groups", sub_groups_str)

        # Show Ranges
        from .analysis import classify_unit
        all_vols = series.volumes + [v for sg in series.sub_groups for v in sg.volumes]
        v_nums, c_nums = [], []
        for v in all_vols:
            v_n, c_n, u_n = classify_unit(v.name)
            v_nums.extend(v_n); c_nums.extend(c_n + u_n)
            
        table.add_row("Volumes", format_ranges(v_nums))
        table.add_row("Chapters", format_ranges(c_nums))

        total_size_mb = series.total_size_bytes / BYTES_PER_MB
        table.add_row("Total Size", f"{total_size_mb:.2f} MB")
        
        if deep:
            table.add_row("Total Pages", f"{series.total_page_count:,}")
        
        content_elements.append(table)

        # 1. Run Check Logic
        gaps = find_gaps(series)
        status_text = Text()
        if not gaps:
            status_text.append("✓ Status: Complete (No gaps found)", style="green")
        else:
            status_text.append("✗ Status: Gaps Detected", style="red")
            for gap in gaps:
                status_text.append(f"\n  - {gap}", style="default")
        
        content_elements.append(status_text)

        # 1b. Check for External Updates
        updates = find_external_updates(series)
        if updates:
            content_elements.append(Text("\n🚀 Available Updates (Nyaa):", style="bold yellow"))
            for up in updates[:3]: # Show top 3
                new_str = ""
                if up["new_volumes"]:
                    new_str += f"Vols: {format_ranges(up['new_volumes'])} "
                if up["new_chapters"]:
                    new_str += f"Ch: {format_ranges(up['new_chapters'])}"
                
                content_elements.append(Text(f"  - {up['torrent_name']}", style="white"))
                content_elements.append(Text(f"    New Content: {new_str} | Size: {up['size']} | Seeders: {up['seeders']}", style="dim"))
            
            if len(updates) > 3:
                content_elements.append(Text(f"  ... and {len(updates)-3} more updates available.", style="dim"))

        # 2. Show File Tree
        # Auto-show files if gaps are found so user can debug
        should_show_files = showfiles or bool(gaps)
        
        # Only show tree if we have sub-groups OR we are showing files
        if should_show_files or series.sub_groups:
            content_elements.append(Text("")) # Spacer
            series_tree = Tree(f":open_file_folder: [bold]{series.name}[/bold]")
            
            # Sort volumes for display
            if should_show_files:
                sorted_vols = sorted(series.volumes, key=lambda v: v.name)
                for vol in sorted_vols:
                    info = f"[dim]({vol.size_bytes // BYTES_PER_KB} KB"
                    if deep:
                        info += f", {vol.page_count} p"
                        if vol.is_corrupt:
                            info += ", [bold red]CORRUPT[/bold red]"
                    info += ")[/dim]"
                    series_tree.add(f":page_facing_up: {vol.name} {info}")

            # Sort sub-groups
            sorted_sub = sorted(series.sub_groups, key=lambda sg: sg.name)
            for sg in sorted_sub:
                sg_node = series_tree.add(f":file_folder: {sg.name}")
                if should_show_files:
                    for vol in sorted(sg.volumes, key=lambda v: v.name):
                        info = f"[dim]({vol.size_bytes // BYTES_PER_KB} KB"
                        if deep:
                            info += f", {vol.page_count} p"
                            if vol.is_corrupt:
                                info += ", [bold red]CORRUPT[/bold red]"
                        info += ")[/dim]"
                        sg_node.add(f":page_facing_up: {vol.name} {info}")
            
            content_elements.append(series_tree)
            
        console.print(Padding(Group(*content_elements), (0, 0, 1, 2)))

@cli.command()
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


@cli.command()
@click.option("--pages", default=NYAA_DEFAULT_PAGES_TO_SCRAPE, help="Number of pages to scrape.")
@click.option("--output", default=NYAA_DEFAULT_OUTPUT_FILENAME, help="Output file to save JSON results.")
@click.option("--user-agent", help="Override the default User-Agent for scraping.")
@click.option("--force", is_flag=True, help="Force a full rescrape, ignoring existing data.")
@click.option("--summarize", is_flag=True, help="Display a summary of the scraped data.")
def scrape(pages: int, output: str, user_agent: Optional[str], force: bool, summarize: bool) -> None:
    """Scrapes nyaa.si for the latest English-translated literature."""
    logger.info(f"Scrape command started (pages={pages}, output={output}, force={force}, summarize={summarize})")

    existing_data = []
    latest_known_timestamp = None
    perform_scrape = True

    # 1. Load existing data & Check incremental
    if os.path.exists(output):
        try:
            with open(output, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            if existing_data:
                # Assuming data is list of dicts with 'date' field
                latest_known_timestamp = max(int(entry.get('date', 0)) for entry in existing_data)
                
                if not force:
                    date_str = datetime.datetime.fromtimestamp(latest_known_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    console.print(f"[dim]Incremental scrape active. Stopping at timestamp: {latest_known_timestamp} ({date_str})[/dim]")
                    
                    # Quick check against live site
                    latest_live_timestamp = get_latest_timestamp_from_nyaa(user_agent=user_agent)
                    if latest_live_timestamp and latest_live_timestamp <= latest_known_timestamp:
                        console.print("[green]The Nyaa index has not been updated since the last scrape. Use --force to override.[/green]")
                        perform_scrape = False
                        
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Could not parse existing file '{output}': {e}. Starting fresh.")
            console.print(f"[yellow]Warning: Could not parse '{output}'. Starting fresh scrape.[/yellow]")
            # If parse failed, treat as if no existing data
            existing_data = []

    # 2. Perform Scrape (if needed)
    if perform_scrape:
        new_results = scrape_nyaa(
            pages=pages,
            user_agent=user_agent,
            stop_at_timestamp=latest_known_timestamp if not force else None
        )

        if new_results:
            # Merge results: New + Old
            combined_data = new_results + existing_data
            
            # Ensure uniqueness
            unique_data = {v['magnet_link']: v for v in combined_data}.values()
            # Sort by date descending
            final_list = sorted(unique_data, key=lambda x: int(x.get('date', 0)), reverse=True)

            # Save
            try:
                with open(output, 'w', encoding='utf-8') as f:
                    json.dump(final_list, f, indent=2)
                
                logger.info(f"Successfully saved {len(final_list)} results ({len(new_results)} new) to {output}")
                console.print(f"[green]✓ Saved {len(final_list)} total entries ({len(new_results)} new) to {output}[/green]")
                
                # Update in-memory data for summary
                existing_data = final_list
                
            except IOError as e:
                logger.error(f"Error writing to output file {output}: {e}", exc_info=True)
                console.print(f"[red]Error: Could not write to file {output}.[/red]")
                
            logger.info(f"Scrape command completed. Found {len(new_results)} new entries.")
        else:
            if not existing_data and perform_scrape:
                 console.print("[yellow]Scraping completed with no results.[/yellow]")
            elif perform_scrape:
                 console.print("[green]No new entries found. Library is up to date.[/green]")

    # 3. Summarize
    if summarize:
        if not existing_data:
            console.print("[yellow]No data to summarize.[/yellow]")
        else:
            table = Table(title=f"Scrape Summary: {output}", box=box.SIMPLE)
            table.add_column("Date", style="cyan", no_wrap=True)
            table.add_column("Name", style="white")
            table.add_column("Size", style="green", justify="right")

            # Show top 50 or so to avoid flooding, or maybe all? 
            # User asked for "a list", let's cap it at reasonable amount or show all if piped.
            # Rich handles large tables decently, but let's stick to showing everything 
            # since the user might want to grep it. 
            # But "nicely formatted" implies visual.
            # Let's show everything but let rich handle pagination if it was interactive, 
            # but here we just dump the table.
            
            for entry in existing_data:
                try:
                    ts = int(entry.get('date', 0))
                    date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    date_str = "Unknown"
                
                table.add_row(
                    date_str,
                    entry.get('name', 'Unknown'),
                    entry.get('size', '?')
                )
            
            console.print(table)

@cli.command()
@click.argument("query", required=False)
@click.option("--input-file", default=NYAA_DEFAULT_OUTPUT_FILENAME, help="Input JSON file (default: nyaa_scrape_results.json)")
@click.option("--output-file", default="nyaa_match_results.json", help="Output JSON file.")
@click.option("--table", is_flag=True, help="Show the results table.")
@click.option("--all", "show_all", is_flag=True, help="Show all entries, including skipped ones.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan for matching logic.")
@click.option("--stats", is_flag=True, help="Show a visually compelling summary of match statistics.")
@click.option("--no-parallel", is_flag=True, help="Disable parallel matching (slower).")
def match(query: Optional[str], input_file: str, output_file: str, table: bool, show_all: bool, no_cache: bool, stats: bool, no_parallel: bool) -> None:
    """
    Parses scraped data to extract manga info.
    If QUERY is provided, only matches against library series matching that name.
    """
    logger.info(f"Match command started (query={query}, input={input_file}, output={output_file}, table={table}, show_all={show_all}, no_cache={no_cache}, stats={stats}, no_parallel={no_parallel})")
    
    # Run scan with progress for better UX
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library for Matching...",
        use_cache=not no_cache
    )
    
    process_match(input_file, output_file, table, show_all, library=library, show_stats=stats, query=query, parallel=not no_parallel)

@cli.command()
@click.argument("name", required=False)
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON.")
@click.option("--status", is_flag=True, help="Show current qBittorrent downloads for VibeManga.")
@click.option("--auto-add", is_flag=True, help="Automatically add torrents if they contain new volumes.")
@click.option("--auto-add-only", is_flag=True, help="Same as auto-add, but skips items that don't match criteria instead of prompting.")
@click.option("--max", "max_downloads", type=int, help="Limit the number of auto-added items.")
def grab(name: Optional[str], input_file: str, status: bool, auto_add: bool, auto_add_only: bool, max_downloads: Optional[int]) -> None:
    """
    Selects a manga from matched results and adds it to qBittorrent.
    
    NAME can be a parsed name from the JSON or 'next' to get the first unflagged entry.
    """
    root_path = get_library_root()
    process_grab(name, input_file, status, root_path, auto_add=auto_add, auto_add_only=auto_add_only, max_downloads=max_downloads)

@cli.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.option("--simulate", is_flag=True, help="Show what would be done without making changes.")
@click.option("--pause", is_flag=True, help="Pause between post-processing items.")
def pull(input_file: str, simulate: bool, pause: bool) -> None:
    """
    Checks for completed torrents in qBittorrent and post-processes them.
    """
    root_path = get_library_root()
    process_pull(simulate=simulate, pause=pause, root_path=root_path, input_file=input_file)

@cli.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.pass_context
def pullcomplete(ctx, input_file: str) -> None:
    """
    Runs a full update cycle: pull -> stats -> metadata -> categorize.
    Then checks download queue and replenishes if < 150 active torrents.
    """
    console.print(Rule("[bold magenta]Starting Full Update Cycle[/bold magenta]"))
    
    # 1. Pull
    console.print("\n[bold cyan]Step 1/6: Pulling Completed Torrents[/bold cyan]")
    ctx.invoke(pull, input_file=input_file, simulate=False, pause=False)
    
    # 2. Refresh Cache (Silent Scan)
    console.print("\n[bold cyan]Step 2/6: Refreshing Library Cache[/bold cyan]")
    root = get_library_root()
    # We run the scan directly to update cache without printing the full stats report
    run_scan_with_progress(root, "[bold green]Refreshing Cache...[/bold green]", use_cache=False)
    
    # 3. Metadata
    console.print("\n[bold cyan]Step 3/6: Updating Metadata[/bold cyan]")
    ctx.invoke(metadata, query=None, force_update=False, trust_jikan=False, process_all=True, model_assign=False)
    
    # 4. Categorize
    console.print("\n[bold cyan]Step 4/6: Auto-Categorizing[/bold cyan]")
    ctx.invoke(categorize, query=None, auto=True, simulate=False, no_cache=True, model_assign=False, pause=False)
    
    # 5. Replenish
    console.print("\n[bold cyan]Step 5/6: Checking Download Queue[/bold cyan]")
    try:
        qbit = QBitAPI()
        torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
        count = len(torrents)
        LIMIT = 150
        
        if count < LIMIT:
            needed = LIMIT - count
            console.print(f"[green]Queue has {count} items. Replenishing up to {LIMIT} (Need {needed})...[/green]")
            
            # a. Scrape
            console.print("[dim]Running Scrape...[/dim]")
            ctx.invoke(scrape, pages=NYAA_DEFAULT_PAGES_TO_SCRAPE, output=NYAA_DEFAULT_OUTPUT_FILENAME, user_agent=None, force=False, summarize=False)
            
            # b. Match
            console.print("[dim]Running Match...[/dim]")
            ctx.invoke(match, query=None, input_file=NYAA_DEFAULT_OUTPUT_FILENAME, output_file=input_file, table=False, show_all=False, no_cache=True, stats=False, no_parallel=False)
            
            # c. Grab
            console.print(f"[dim]Running Grab (Auto-Add Max {needed})...[/dim]")
            ctx.invoke(grab, name=None, input_file=input_file, status=False, auto_add=False, auto_add_only=True, max_downloads=needed)
            
        else:
            console.print(f"[yellow]Queue is full ({count} >= {LIMIT}). Skipping replenishment.[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error during replenishment step: {e}[/red]")
        logger.error(f"Replenish failed: {e}", exc_info=True)

    # 6. Final Stats
    console.print("\n[bold cyan]Step 6/6: Final Library Statistics[/bold cyan]")
    # We use no_cache=True to ensure we see the result of any moves done by Categorize
    ctx.invoke(stats, query=None, continuity=False, deep=False, verify=False, no_cache=True, no_metadata=False)

    console.print(Rule("[bold green]Full Update Cycle Complete[/bold green]"))

if __name__ == "__main__":
    cli()
