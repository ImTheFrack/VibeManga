"""
Stats command for VibeManga CLI.

Displays library statistics, metadata insights, and breakdowns.
"""
import os
import click
import logging
from typing import Optional, List
from collections import Counter
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.align import Align
from rich.rule import Rule
from rich.text import Text
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.console import Group

from .base import console, get_library_root, run_scan_with_progress, perform_deep_analysis
from ..models import Library, Category, Series
from ..metadata import load_local_metadata
from ..analysis import find_gaps, classify_unit
from ..constants import (
    BYTES_PER_GB,
    BYTES_PER_MB,
    VALID_DEMOGRAPHICS,
    CLEAN_WORD_RE,
    STOP_WORDS
)

logger = logging.getLogger(__name__)

@click.command()
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
            t.add_column(label, ratio=ratio_val if (ratio_val := 3) else 3, style=f"bold {color}")
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
        card_grid.add_row("", "") # Spacer row

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
