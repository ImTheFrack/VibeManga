import os
import re
import json
import logging
import click
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box
from rich.rule import Rule
from rich.panel import Panel
from rich.text import Text

from .qbit_api import QBitAPI
from .constants import (
    QBIT_DEFAULT_TAG, 
    QBIT_DEFAULT_SAVEPATH, 
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_GB
)
from .cache import load_library_state
from .matcher import consolidate_entries
from .analysis import (
    normalize_series_name,
    classify_unit,
    format_ranges,
    parse_size,
    format_size
)

logger = logging.getLogger(__name__)
console = Console()

def process_grab(name: Optional[str], input_file: str, status: bool, root_path: str) -> None: 
    """
    Selects a manga from matched results and adds it to qBittorrent.
    
    Args:
        name: Name of the series to grab, or 'next'.
        input_file: Path to the JSON file with match results.
        status: If True, show current qBittorrent status instead of grabbing.
        root_path: Path to the library root directory.
    """
    qbit = QBitAPI()

    if status:
        torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
        if not torrents:
            console.print("[yellow]No active VibeManga torrents found in qBittorrent.[/yellow]")
            return
            
        table = Table(title="Current VibeManga Downloads", box=box.ROUNDED)
        table.add_column("Name", style="white")
        table.add_column("Status", style="cyan")
        table.add_column("Progress", style="green")
        table.add_column("Library Match", style="magenta")

        # Load library for matching reporting
        library = load_library_state(Path(root_path))
        
        for t in torrents:
            # Try to find what series this matches to in our library
            match_name = "No Match"
            # We use the qbit 'name' to find a match in our library series
            if library:
                norm_t_name = normalize_series_name(t['name']).lower()
                for cat in library.categories:
                    for sub in cat.sub_categories:
                        for s in sub.series:
                            if normalize_series_name(s.name).lower() in norm_t_name:
                                match_name = s.name
                                break
                        if match_name != "No Match": break
                    if match_name != "No Match": break

            table.add_row(
                t['name'],
                t['state'],
                f"{t['progress']*100:.1f}%",
                match_name
            )
        console.print(table)
        return

    if not os.path.exists(input_file):
        console.print(f"[red]Input file {input_file} not found. Run 'match' first.[/red]")
        return

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        console.print(f"[red]Error reading {input_file}: {e}[/red]")
        return

    # Consolidate entries to show all related files for this series
    consolidated = consolidate_entries(data)
    manga_groups = [g for g in consolidated if g.get("type") == "Manga"]

    # Load library to show local content info
    library = load_library_state(Path(root_path))
    series_map = {}
    if library:
        for cat in library.categories:
            for sub in cat.sub_categories:
                for s in sub.series:
                    try:
                        rel = s.path.relative_to(library.path)
                        sid = rel.as_posix()
                    except ValueError:
                        sid = s.name
                    series_map[sid] = s

    if not manga_groups:
        console.print("[yellow]No Manga entries found in match results.[/yellow]")
        return

    # Find starting group
    start_idx = 0
    if name and name != "next":
        q = name.lower()
        found = False
        for i, g in enumerate(manga_groups):
            if any(q in n.lower() for n in g.get("parsed_name", [])):
                start_idx = i
                found = True
                break
        if not found:
            console.print(f"[red]Could not find entry matching '{name}'[/red]")
            # Fall back to first unflagged...
            name = "next"
            
    if not name or name == "next":
        found = False
        for i, g in enumerate(manga_groups):
            group_names = set(g["parsed_name"])
            group_entries = [e for e in data if any(n in group_names for n in e.get("parsed_name", []))]
            if not any(e.get("grab_status") for e in group_entries):
                start_idx = i
                found = True
                break
        if not found:
            console.print("[green]All manga groups have been processed![/green]")
            return

    current_idx = start_idx
    
    while current_idx < len(manga_groups):
        group = manga_groups[current_idx]

        console.print(Rule(style="dim"))
        # Show selection info
        console.print(Panel(f"[bold cyan]Group {current_idx + 1}/{len(manga_groups)}: {', '.join(group['parsed_name'])}[/bold cyan]"))
        
        # List all files in this group
        group_files = []
        group_names = set(group["parsed_name"])
        for e in data:
            if any(n in group_names for n in e.get("parsed_name", [])):
                group_files.append(e)

        match_id = group.get("matched_id")
        local_series = series_map.get(match_id) if match_id else None
        
        if group.get("matched_name"):
            console.print(f"[green]Library Match: {group['matched_name']}[/green]")
            
            if local_series:
                all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
                l_v_nums, l_c_nums = [], []
                for v in all_local_vols:
                    v_n, c_n, u_n = classify_unit(v.name)
                    l_v_nums.extend(v_n); l_c_nums.extend(c_n + u_n)
                
                l_vols = format_ranges(l_v_nums)
                l_chaps = format_ranges(l_c_nums)
                
                size_str = format_size(local_series.total_size_bytes)
                console.print(f"[bold yellow]Local Content: Vols: {l_vols} | Chaps: {l_chaps} | Size: {size_str}[/bold yellow]")

                # Calculate New Content
                l_v_set = set(l_v_nums)
                l_c_set = set(l_c_nums)
                new_v, new_c = set(), set()
                max_torrent_bytes = 0
                
                for f in group_files:
                    t_bytes = parse_size(f.get("size"))
                    if t_bytes > max_torrent_bytes:
                        max_torrent_bytes = t_bytes

                    v_s, v_e = f.get("volume_begin"), f.get("volume_end")
                    if v_s is not None:
                        try:
                            s, e = float(v_s), float(v_e or v_s)
                            if s.is_integer() and e.is_integer():
                                for n in range(int(s), int(e) + 1):
                                    if float(n) not in l_v_set: new_v.add(float(n))
                            else:
                                if s not in l_v_set: new_v.add(s)
                                if e not in l_v_set: new_v.add(e)
                        except (ValueError, TypeError): pass
                    
                    c_s, c_e = f.get("chapter_begin"), f.get("chapter_end")
                    if c_s is not None:
                        try:
                            s, e = float(c_s), float(c_e or c_s)
                            if s.is_integer() and e.is_integer():
                                for n in range(int(s), int(e) + 1):
                                    if float(n) not in l_c_set: new_c.add(float(n))
                            else:
                                if s not in l_c_set: new_c.add(s)
                                if e not in l_c_set: new_c.add(e)
                        except (ValueError, TypeError): pass

                msg_parts = []
                if new_v or new_c:
                    part = "[bold green]NEW CONTENT AVAILABLE:"
                    if new_v:
                        part += f" [{len(new_v)} new vols: {format_ranges(list(new_v))}]"
                    if new_c:
                        part += f" [{len(new_c)} new chaps: {format_ranges(list(new_c))}]"
                    part += "[/bold green]"
                    msg_parts.append(part)
                
                # Size hints
                diff = max_torrent_bytes - local_series.total_size_bytes
                if max_torrent_bytes > local_series.total_size_bytes * 1.1:
                    msg_parts.append(f"[bold cyan]LARGER CONTENT: [+{format_size(diff)}][/bold cyan]")
                elif not new_v and not new_c and max_torrent_bytes < local_series.total_size_bytes * 0.5:
                    # Only show smaller if detection failed for EVERYTHING in the group
                    vols_avail = group.get("consolidated_volumes")
                    chaps_avail = group.get("consolidated_chapters")
                    if not vols_avail and not chaps_avail:
                        msg_parts.append(f"[bold magenta]SMALLER CONTENT: [{format_size(diff)}][/bold magenta]")

                if msg_parts:
                    console.print(" ".join(msg_parts))
        
        vols = ", ".join(group.get("consolidated_volumes", []))
        chaps = ", ".join(group.get("consolidated_chapters", []))
        console.print(f"[dim]Scraped Avail: Vols: {vols if vols else 'None'} | Chapters: {chaps if chaps else 'None'}[/dim]")

        table = Table(title="Available Torrents", box=box.SIMPLE)
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Name", style="white")
        table.add_column("Size", justify="right", style="green")
        table.add_column("Seed", justify="right", style="yellow")
        table.add_column("Status", justify="center")

        for i, f in enumerate(group_files):
            status_val = f.get("grab_status", "-")
            table.add_row(str(i+1), f.get("name"), f.get("size"), str(f.get("seeders")), status_val)
        
        console.print(table)
        
        choice = click.prompt("Enter ID to grab, 's' to skip group, 'n' to next group, or 'q' to quit", default="n")
        
        if choice.lower() == 'q':
            break
        elif choice.lower() == 'n':
            current_idx += 1
            continue
        elif choice.lower() == 's':
            # Flag all in group as skipped
            for f in group_files:
                f["grab_status"] = "skipped"
            console.print("[yellow]Group marked as skipped.[/yellow]")
            
            # Save updated data
            try:
                with open(input_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")
            
            current_idx += 1
            continue
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(group_files):
                selected = group_files[idx]
                magnet = selected.get("magnet_link")
                if not magnet:
                    console.print("[red]No magnet link found for this entry.[/red]")
                else:
                    if qbit.add_torrent([magnet], tag=QBIT_DEFAULT_TAG, savepath=QBIT_DEFAULT_SAVEPATH):
                        console.print(f"[bold green]Successfully added to qBittorrent: {selected.get('name')}[/bold green]")
                        selected["grab_status"] = "grabbed"
                        
                        # Save updated data
                        try:
                            with open(input_file, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                        except Exception as e:
                            console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")
                        
                        current_idx += 1
                    else:
                        console.print("[red]Failed to add torrent to qBittorrent.[/red]")
            else:
                console.print("[red]Invalid ID.[/red]")

    if current_idx >= len(manga_groups):
        console.print("[green]Reached the end of the match list.[/green]")

