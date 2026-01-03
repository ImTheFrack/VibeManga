"""
Shared CLI utilities and base functionality.

Extract common patterns from main.py to reduce duplication.
"""
import os
import sys
import click
import logging
import datetime
import concurrent.futures
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.rule import Rule

# Internal imports
from ..scanner import scan_library, enrich_series
from ..models import Library, Category, Series
from ..cache import get_cached_library, save_library_cache, load_library_state
from ..config import get_config, get_ai_role_config
from ..ai_api import get_available_models
from ..constants import (
    BYTES_PER_GB,
    PROGRESS_REFRESH_RATE,
    DEEP_ANALYSIS_REFRESH_RATE,
    ROLE_CONFIG
)
from ..logging import get_logger, log_substep, console

logger = get_logger(__name__)

def get_library_root() -> Path:
    """
    Gets the manga library root path from configuration.

    Returns:
        The library root path as a Path object.

    Raises:
        SystemExit: If library path is not set.
    """
    config = get_config()
    
    # Check new config first, then legacy
    root = config.library_path or config.manga_library_root
    
    # Fallback to direct env var check if config load failed to populate (unlikely with pydantic)
    if not root:
        root_str = os.getenv("MANGA_LIBRARY_ROOT")
        if root_str:
            root = Path(root_str)

    if not root:
        logger.error("MANGA_LIBRARY_ROOT is not set in .env file or config")
        console.print("[red]Error: MANGA_LIBRARY_ROOT is not set in .env file.[/red]")
        sys.exit(1)
        
    return root

def run_scan_with_progress(
    root_path: Path,
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
    # Try to load from cache if enabled
    if use_cache:
        logger.info("Checking for cached library scan...")
        cached_library = get_cached_library(root_path)
        if cached_library:
            logger.info("Using cached library scan")
            console.print("[dim]Using cached scan (run with --no-cache to force refresh)[/dim]")
            return cached_library
        logger.info("No valid cache found, performing fresh scan")

    # Always try to load persistent state if it exists, to preserve external metadata
    # even during a fresh filesystem scan.
    existing_library = load_library_state(root_path)

    # We will track running stats locally for the progress bar
    stats_cache = {"vols": 0, "size": 0}
    
    # Line 1: The visual progress bar
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
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
            
            log_substep(f"Scanned: {series.name}")

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
        TextColumn("{task.description}"),
        console=console
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

def load_ai_config() -> Dict:
    """Helper to load AI config from JSON file (Legacy/Direct approach for Wizard)"""
    import json
    config_path = Path("vibe_manga_ai_config.json")
    if config_path.exists():
        with open(config_path, "r") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_ai_config(config: Dict) -> None:
    """Helper to save AI config to JSON file"""
    import json
    with open("vibe_manga_ai_config.json", "w") as f:
        json.dump(config, f, indent=2)

