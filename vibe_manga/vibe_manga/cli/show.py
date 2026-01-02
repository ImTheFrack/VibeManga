"""
Show command for VibeManga CLI.

Finds a specific series and shows its details.
"""
import os
import click
import logging
from typing import Optional
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.padding import Padding
from rich.console import Group
from rich.tree import Tree
from rich.rule import Rule

from .base import console, get_library_root, run_scan_with_progress, perform_deep_analysis
from ..metadata import load_local_metadata
from ..analysis import (
    find_gaps, 
    find_external_updates, 
    semantic_normalize,
    classify_unit,
    format_ranges
)
from ..constants import BYTES_PER_KB, BYTES_PER_MB

logger = logging.getLogger(__name__)

@click.command()
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
            
            if meta.title_english and meta.title_english.lower() != series.name.lower():
                meta_table.add_row("English Title:", meta.title_english)
            if meta.title_japanese:
                meta_table.add_row("Japanese Title:", meta.title_japanese)
            if meta.synonyms:
                meta_table.add_row("Synonyms:", ", ".join(meta.synonyms[:5]))
            if meta.authors:
                meta_table.add_row("Authors:", ", ".join(meta.authors))
            if meta.release_year:
                meta_table.add_row("Year:", str(meta.release_year))
            if meta.status:
                status_color = "green" if meta.status == "Completed" else "yellow"
                meta_table.add_row("Status:", f"[{status_color}]{meta.status}[/{status_color}]")
            if meta.genres:
                meta_table.add_row("Genres:", ", ".join(meta.genres[:8]))
            if meta.tags:
                meta_table.add_row("Tags:", ", ".join(meta.tags[:10]))
            
            # External IDs & Links
            links = []
            if meta.mal_id: 
                links.append(f"MAL: [bold]{meta.mal_id}[/bold] [dim]([link=https://myanimelist.net/manga/{meta.mal_id}]Visit[/link])[/dim]")
            if meta.anilist_id: 
                links.append(f"AniList: [bold]{meta.anilist_id}[/bold] [dim]([link=https://anilist.co/manga/{meta.anilist_id}]Visit[/link])[/dim]")
            
            if links:
                meta_table.add_row("Identifiers:", " | ".join(links))

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
