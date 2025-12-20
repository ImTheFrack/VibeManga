import os
import logging
import click
import concurrent.futures
from pathlib import Path
from typing import List, Optional, Tuple
from dotenv import load_dotenv
from rich.console import Console
from rich.tree import Tree
from rich.table import Table
from rich import box

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

from .scanner import scan_library, enrich_series
from .models import Library, Category, Series
from .analysis import find_gaps, find_duplicates, find_structural_duplicates, find_external_updates, format_ranges, normalize_series_name
from .cache import get_cached_library, save_library_cache, load_library_state
from .nyaa_scraper import scrape_nyaa, get_latest_timestamp_from_nyaa
from .matcher import process_match
from .constants import (
    DEFAULT_TREE_DEPTH,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_GB,
    PROGRESS_REFRESH_RATE,
    DEEP_ANALYSIS_REFRESH_RATE,
    NYAA_DEFAULT_PAGES_TO_SCRAPE,
    NYAA_DEFAULT_OUTPUT_FILENAME
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('vibe_manga.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

console = Console()

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

@click.group()
def cli():
    """VibeManga: A CLI for managing your manga collection."""
    pass

@cli.command()
@click.argument("query", required=False)
@click.option("--continuity", is_flag=True, help="Check for missing volumes/chapters.")
@click.option("--deep", is_flag=True, help="Perform deep analysis (page counts).")
@click.option("--verify", is_flag=True, help="Verify archive integrity (slow).")
@click.option("--no-cache", is_flag=True, help="Force fresh scan, ignore cache.")
def stats(query: Optional[str], continuity: bool, deep: bool, verify: bool, no_cache: bool) -> None:
    """
    Show statistics.
    If QUERY is provided, shows stats for the matching Category, Sub-Category, or Series.
    The highest-level match takes precedence (Main > Sub > Series).
    """
    logger.info(f"Stats command started (query={query}, continuity={continuity}, deep={deep}, verify={verify}, no_cache={no_cache})")
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
    total_size = 0
    total_pages = 0
    complete_series = 0
    
    # Helper to count complete series
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

    if continuity:
        with console.status("[bold blue]Checking continuity..."):
            all_target_series = get_all_series(targets, target_type)
            for s in all_target_series:
                if not find_gaps(s):
                    complete_series += 1

    for t in targets:
        if target_type == "Library":
            total_series += t.total_series
            total_volumes += t.total_volumes
            total_size += t.total_size_bytes
            total_pages += t.total_pages
        elif target_type == "Series":
            total_series += 1
            total_volumes += t.total_volume_count
            total_size += t.total_size_bytes
            total_pages += t.total_page_count
        else: # Categories
            total_series += t.total_series_count
            total_volumes += t.total_volume_count
            total_size += t.total_size_bytes
            total_pages += t.total_page_count

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

    console.print(Columns(cards))
    console.print("")

    # 5. Breakdown Table
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
        
        for cat in library.categories:
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

    console.print(t)

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
def show(series_name: str, showfiles: bool, deep: bool, verify: bool, no_cache: bool) -> None:
    """Finds a specific series and shows its details, including gaps and updates."""
    logger.info(f"Show command started (series_name={series_name}, showfiles={showfiles}, deep={deep}, verify={verify}, no_cache={no_cache})")
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        f"[bold green]Searching for '{series_name}'...",
        use_cache=not no_cache
    )

    found = []
    found_series_objects = []  # For deep analysis

    norm_query = normalize_series_name(series_name).lower()

    for main_cat in library.categories:
        for sub_cat in main_cat.sub_categories:
            for series in sub_cat.series:
                norm_series = normalize_series_name(series.name).lower()
                if norm_query in norm_series or series_name.lower() in series.name.lower():
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

        console.print(Panel(f"[bold]Result: {series.name}[/bold]", expand=False, border_style="cyan"))
        
        content_elements = []

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
def dedupe(query: Optional[str], verbose: bool, deep: bool, verify: bool, no_cache: bool) -> None:
    """
    Finds duplicate volumes.
    If QUERY is provided, only matching series are checked.
    Otherwise, the whole library is scanned.
    """
    logger.info(f"Dedupe command started (query={query}, verbose={verbose}, deep={deep}, verify={verify}, no_cache={no_cache})")
    root_path = get_library_root()
    scan_desc = f"[bold green]Deduplicating '{query}'..." if query else "[bold green]Deduplicating Library..."
    library = run_scan_with_progress(root_path, scan_desc, use_cache=not no_cache)
    
    # Filter targets for deep analysis first
    if deep or verify:
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

if __name__ == "__main__":
    cli()
