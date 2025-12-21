import os
import re
import json
import logging
import click
import time
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box
from rich.rule import Rule
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm

from .qbit_api import QBitAPI
from .constants import (
    QBIT_DEFAULT_TAG, 
    QBIT_DEFAULT_SAVEPATH, 
    QBIT_DOWNLOAD_ROOT,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_GB,
    PROGRESS_REFRESH_RATE,
    PULL_TEMPDIR
)
from .cache import load_library_state, save_library_cache
from .matcher import consolidate_entries, parse_entry
from .scanner import scan_series
from .models import Category
from .analysis import (
    
    semantic_normalize,
    classify_unit,
    format_ranges,
    parse_size,
    format_size
)

logger = logging.getLogger(__name__)
console = Console()

def get_matched_or_parsed_name(torrent_name: str, library: Optional[Any] = None, match_data: Optional[List[Dict]] = None, series_map: Optional[Dict[str, Any]] = None) -> str:
    """
    Tries to find a library match for a torrent name, 
    falling back to a parsed name if no match is found.
    """
    # 1. Try Match Data (Ground Truth from match command)
    if match_data and series_map:
        for entry in match_data:
            if entry.get("name") == torrent_name:
                mid = entry.get("matched_id")
                if mid and mid in series_map:
                    return f"[green]{series_map[mid].name}[/green]"
                # Even if not in map, maybe we have a matched_name
                mname = entry.get("matched_name")
                if mname:
                    return f"[green]{mname}[/green]"
                break

    # 2. Try Library Fuzzy Match
    if library:
        local_match = find_series_match(torrent_name, library)
        if local_match:
            return f"[green]{local_match.name}[/green]"
    
    # 3. Fallback to Parsing
    parsed = parse_entry({"name": torrent_name})
    parsed_names = parsed.get("parsed_name", [])
    if parsed_names and not any(n.startswith("SKIPPED:") for n in parsed_names):
        return " | ".join(parsed_names)
    
    return f"[dim]{torrent_name}[/dim]"

def find_series_match(torrent_name: str, library: Optional[Any] = None) -> Optional[Any]:
    """Finds the matched Series object in the library for a given torrent name."""
    if not library:
        return None
    
    norm_t_name = semantic_normalize(torrent_name)
    for cat in library.categories:
        for sub in cat.sub_categories:
            for s in sub.series:
                norm_s_name = semantic_normalize(s.name)
                if norm_s_name and norm_s_name in norm_t_name:
                    return s
    return None

def vibe_format_range(numbers: List[float], prefix: str = "", pad: int = 0) -> str:
    """Formats a list of numbers into a consistent string (e.g., v01, 001.5)."""
    if not numbers:
        return ""
    
    # Sort to find range
    nums = sorted(list(set(numbers)))
    start = nums[0]
    end = nums[-1]
    
    def fmt(n):
        # Format as float if it has a decimal, else int
        if n.is_integer():
            s = str(int(n))
        else:
            s = str(n)
            
        if "." in s:
            # Pad the integer part
            base, dec = s.split(".")
            return f"{base.zfill(pad)}.{dec}"
        return s.zfill(pad)

    if start == end:
        return f"{prefix}{fmt(start)}"
    else:
        # Range: v01-05
        return f"{prefix}{fmt(start)}-{fmt(end)}"

def normalize_pull_filenames(pull_dir: Path, series_name: str) -> None:
    """Recursively renames files in pull_dir to match our naming convention."""
    files_to_process = []
    for root, _, files in os.walk(pull_dir):
        for f in files:
            path = Path(root) / f
            # Common archive/manga extensions
            if path.suffix.lower() in [".cbz", ".cbr", ".pdf", ".zip", ".rar", ".7z"]:
                files_to_process.append(path)
                
    if not files_to_process:
        return

    # Sort alphabetically to ensure sequential fallback follows a logical order
    files_to_process.sort()

    fallback_idx = 1
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        refresh_per_second=PROGRESS_REFRESH_RATE
    ) as progress:
        task = progress.add_task(f"Normalizing {len(files_to_process)} filenames...", total=len(files_to_process))
        
        for path in files_to_process:
            v_nums, ch_nums, u_nums = classify_unit(path.name)
            
            # Preferences: Volumes padded to 2, Chapters to 3
            v_str = vibe_format_range(v_nums, prefix="v", pad=2)
            
            # Use ch_nums if present, else u_nums if no v_nums (fallback for naked numbers)
            c_nums = ch_nums
            c_prefix = ""
            if not c_nums and not v_nums and u_nums:
                c_nums = u_nums
                c_prefix = "unit" # Use unit prefix for naked numbers
                
            c_str = vibe_format_range(c_nums, prefix=c_prefix, pad=3)
            
            parts = []
            if v_str: parts.append(v_str)
            if c_str: parts.append(c_str)
            
            # Fallback: If no numbers were detected at all, use a sequential counter
            if not parts:
                parts.append(f"unit{str(fallback_idx).zfill(3)}")
                fallback_idx += 1
                
            # Format: {Series Name} {vXX} {CCC}.[ext]
            new_name = f"{series_name} {' '.join(parts)}{path.suffix}"
            new_path = path.parent / new_name
            
            if path.name != new_name:
                try:
                    if new_path.exists():
                        # If the name we generated already exists (collision), 
                        # add a small suffix to keep it unique
                        collision_idx = 1
                        while new_path.exists():
                            alt_name = f"{series_name} {' '.join(parts)} ({collision_idx}){path.suffix}"
                            new_path = path.parent / alt_name
                            collision_idx += 1
                        path.rename(new_path)
                    else:
                        path.rename(new_path)
                except Exception as e:
                    logger.error(f"Failed to rename {path.name} to {new_name}: {e}")
            
            progress.advance(task)

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
                local_series = find_series_match(t['name'], library)
                if local_series:
                    match_name = local_series.name

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

def process_pull(simulate: bool = False, pause: bool = False, root_path: str = "", input_file: str = "") -> None:
    """
    Checks qBittorrent for completed torrents with the VibeManga tag
    and performs post-processing.
    
    Args:
        simulate: If True, only show what would be done.
        pause: If True, wait for user input between items.
        root_path: Path to the library root.
        input_file: Path to the JSON file with match results to update.
    """
    qbit = QBitAPI()
    console.print(Rule("[bold magenta]Pulling Completed Torrents[/bold magenta]"))
    if simulate:
        console.print("[bold yellow]SIMULATION MODE ACTIVE - No changes will be made.[/bold yellow]")
    
    if not QBIT_DOWNLOAD_ROOT:
        console.print("[yellow]Warning: QBIT_DOWNLOAD_ROOT is not set in .env.[/yellow]")
        console.print("[dim]Please set it to your local download path. Use forward slashes (e.g., Z:/Downloads) to avoid escaping issues.[/dim]\n")

    # Load match results if input_file is provided
    match_data = []
    if input_file and os.path.exists(input_file):
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                match_data = json.load(f)
        except Exception as e:
            console.print(f"[red]Warning: Could not load match results from {input_file}: {e}[/red]")

    with console.status("[bold blue]Connecting to qBittorrent..."):
        torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
    
    if not torrents:
        console.print("[yellow]No VibeManga torrents found in qBittorrent.[/yellow]")
        return

    # Load library for matching reporting
    library = None
    series_map = {}
    if root_path:
        library = load_library_state(Path(root_path))
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

    # Pre-calculate display names and sort keys
    for t in torrents:
        disp = get_matched_or_parsed_name(t["name"], library, match_data=match_data, series_map=series_map)
        t["_display_name"] = disp
        # Create a plain-text version for sorting (remove Rich tags)
        t["_sort_name"] = re.sub(r"\[.*?\]", "", disp).lower()

    # Sort: Non-completed first, then by matched name
    sorted_torrents = sorted(torrents, key=lambda x: (x.get("progress") >= 1.0, x.get("_sort_name")))
    
    completed = [t for t in sorted_torrents if t.get("progress") == 1.0]
    
    # Calculate a sensible max width for the name column based on console width
    # Subtracting ~45 for Size, Progress, Status columns and borders/padding
    name_col_max = max(40, console.width - 45)

    table = Table(title=f"VibeManga Torrents ({len(torrents)})", box=box.ROUNDED)
    table.add_column("Matched/Parsed Name", style="white", no_wrap=True, overflow="ellipsis", max_width=name_col_max)
    table.add_column("Size", justify="right", style="green")
    table.add_column("Progress", justify="right", style="cyan")
    table.add_column("Status", justify="center")

    completed_count = 0
    for t in sorted_torrents:
        size_str = format_size(t.get("size", 0))
        prog = t.get("progress", 0) * 100
        is_done = prog >= 100
        
        status_str = "[bold green]Ready to Pull[/bold green]" if is_done else "[dim]Downloading[/dim]"
        prog_str = f"{prog:.1f}%"
        if is_done:
            prog_str = f"[bold green]{prog_str}[/bold green]"

        display_name = t["_display_name"]
        
        if is_done:
            completed_count += 1
            display_name = f"{completed_count}. {display_name}"
        
        table.add_row(display_name, size_str, prog_str, status_str)
    
    console.print(table)

    if not completed:
        console.print(f"[yellow]Found {len(torrents)} VibeManga torrents, but none are completed (100%).[/yellow]")
        return

    if not click.confirm(f"Proceed with post-processing {len(completed)} completed torrents?"):
        console.print("[yellow]Operation cancelled.[/yellow]")
        return

    for i, t in enumerate(completed):
        display_name = t["_display_name"]
        console.print(f"\n[bold cyan]Processing [{i+1}/{len(completed)}]: {display_name}[/bold cyan]")
        console.print(f"[dim]Torrent: {t['name']}[/dim]")
        
        # Step 1: Stop Torrent
        action_msg = "[1/8] Stopping torrent in qBittorrent..."
        if simulate:
            console.print(f"[yellow]SIMULATE: {action_msg}[/yellow]")
        else:
            with console.status(f"[bold blue]{action_msg}"):
                if qbit.pause_torrents([t["hash"]]):
                    console.print("[green][1/8] ✓ Torrent stopped.[/green]")
                else:
                    console.print("[red][1/8] ✗ Failed to stop torrent.[/red]")
                    if not click.confirm("Continue anyway?"):
                         break

        # Step 2: Identify Location
        raw_path = t.get("content_path")
        if not raw_path:
            save_path = t.get("save_path", "")
            raw_path = os.path.join(save_path, t["name"])
        
        content_path = raw_path
        # Mapping logic: Replace internal qBit prefix with host root
        if QBIT_DOWNLOAD_ROOT:
            # Strip drive letters and leading slashes to ensure a clean join.                                                                                                                                                                                                                                             │
            # Example: /torrents/VibeManga/... -> torrents/VibeManga/...
            clean_path = raw_path.lstrip("/").lstrip("\\")
            if ":" in clean_path:
                clean_path = clean_path.split(":", 1)[1].lstrip("/").lstrip("\\")
            content_path = os.path.join(QBIT_DOWNLOAD_ROOT, clean_path)
            
        action_msg = f"[2/8] Locating files: {content_path}"
        if QBIT_DOWNLOAD_ROOT:
            console.print(f"[dim][2/8] Mapping: {raw_path} -> {content_path}[/dim]")

        if simulate:
            console.print(f"[yellow][2/8] SIMULATE: {action_msg}[/yellow]")
        else:
            if content_path and os.path.exists(content_path):
                console.print(f"[green][2/8] ✓ Found files at: {content_path}[/green]")
            else:
                console.print(f"[red][2/8] ✗ Could not find files at: {content_path}[/red]")
                if not click.confirm("Continue anyway?"):
                    break

        # Step 3: Copy to PULL_TEMPDIR
        if not PULL_TEMPDIR:
            console.print("[red][3/8] ✗ PULL_TEMPDIR is not set in .env. Skipping copy step.[/red]")
        else:
            dest_dir = Path(PULL_TEMPDIR)
            src_path = Path(content_path)
            
            if not simulate:
                if dest_dir.exists() and any(dest_dir.iterdir()):
                    console.print(f"[bold red][3/8] Warning: Temp directory is not empty: {dest_dir}[/bold red]")
                    if Confirm.ask("[3/8] Clear temp directory? [bold red]This is destructive![/bold red]"):
                        with console.status("[bold red][3/8] Clearing temp directory..."):
                            for item in dest_dir.iterdir():
                                try:
                                    if item.is_dir():
                                        shutil.rmtree(item)
                                    else:
                                        item.unlink()
                                except Exception as e:
                                    console.print(f"[red][3/8] Error clearing {item}: {e}[/red]")
                        console.print("[green][3/8] ✓ Temp directory cleared.[/green]")
                    else:
                        console.print("[yellow][3/8] Pull aborted by user.[/yellow]")
                        break

            action_msg = f"[3/8] Copying files to: {dest_dir}"
            if simulate:
                console.print(f"[yellow][3/8] SIMULATE: {action_msg}[/yellow]")
            else:
                try:
                    if not src_path.exists():
                        raise FileNotFoundError(f"[3/8] Source path {src_path} does not exist.")
                    
                    # Gather all files to copy for granular progress
                    files_to_copy = []
                    if src_path.is_dir():
                        for root, _, files in os.walk(src_path):
                            for f in files:
                                file_src = Path(root) / f
                                rel_path = file_src.relative_to(src_path)
                                files_to_copy.append((file_src, dest_dir / rel_path))
                    else:
                        files_to_copy.append((src_path, dest_dir / src_path.name))

                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                        console=console,
                        refresh_per_second=PROGRESS_REFRESH_RATE
                    ) as progress:
                        copy_task = progress.add_task(f"[3/8] Copying {len(files_to_copy)} files...", total=len(files_to_copy))
                        
                        for s, d in files_to_copy:
                            d.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(s, d)
                            progress.update(copy_task, advance=1, description=f"[dim]Copying: {s.name}[/dim]")
                    
                    console.print(f"[green]✓ Successfully copied to: {dest_dir}[/green]")
                except Exception as e:
                    console.print(f"[red][3/8] ✗ Copy failed: {e}[/red]")
                    if not click.confirm("Continue anyway?"):
                        break

        # Step 4: Normalize Filenames
        # Extract the plain series name from the matched/parsed name.
        series_name = re.sub(r"\[.*?\]", "", display_name).strip()
        series_name = re.sub(r"^\d+\.\s+", "", series_name)
        
        # Sanitize for filesystem (especially for Windows where | : ? * are illegal)
        # We replace them with full-width equivalents that are legal and look similar.
        replacements = {"|": "｜", ":": "：", "?": "？", "*": "＊", "<": "＜", ">": "＞", "\"": "＂"}
        for char, rep in replacements.items():
            series_name = series_name.replace(char, rep)
        
        action_msg = f"[4/8] Normalizing filenames for: {series_name}"
        if simulate:
            console.print(f"[yellow][4/8] SIMULATE: {action_msg}[/yellow]")
        else:
            if PULL_TEMPDIR:
                normalize_pull_filenames(Path(PULL_TEMPDIR), series_name)
                console.print(f"[green][4/8] ✓ Filenames normalized.[/green]")
            else:
                console.print("[yellow][4/8] ! Skipping normalization: PULL_TEMPDIR not set.[/yellow]")

        # Step 5: Detect Pulled Content
        local_series = None
        pulled_files = []
        action_msg = "[5/8] Detecting pulled content..."
        if simulate:
            console.print(f"[yellow][5/8] SIMULATE: {action_msg}[/yellow]")
        else:
            pulled_vols, pulled_chaps, pulled_units = [], [], []
            pulled_size = 0
            if PULL_TEMPDIR:
                with console.status(f"[bold blue]{action_msg}"):
                    for root, _, files in os.walk(PULL_TEMPDIR):
                        for f in files:
                            file_path = Path(root) / f
                            pulled_size += file_path.stat().st_size
                            v, c, u = classify_unit(f)
                            pulled_vols.extend(v); pulled_chaps.extend(c); pulled_units.extend(u)
                            pulled_files.append({"path": file_path, "v": v, "c": c, "u": u})
                
                pulled_v_str = format_ranges(pulled_vols)
                pulled_c_str = format_ranges(pulled_chaps)
                pulled_u_str = format_ranges(pulled_units)
                
                console.print(f"[bold green][5/8] Pulled Content:[/bold green] Vols: {pulled_v_str} | Chaps: {pulled_c_str} | Units: {pulled_u_str} ({format_size(pulled_size)})")
                
                # Match to library (Prioritize match_data over fuzzy match)
                local_series = None
                if match_data and series_map:
                    for entry in match_data:
                        if entry.get("name") == t["name"]:
                            mid = entry.get("matched_id")
                            if mid and mid in series_map:
                                local_series = series_map[mid]
                            break
                
                if not local_series:
                    local_series = find_series_match(t['name'], library)

                if local_series:
                    console.print(f"[green][5/8] Matched to Library: {local_series.name}[/green]")
                    all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
                    l_v_nums, l_c_nums = [], []
                    for v in all_local_vols:
                        v_n, c_n, u_n = classify_unit(v.name)
                        l_v_nums.extend(v_n); l_c_nums.extend(c_n + u_n)
                    
                    l_v_set, l_c_set = set(l_v_nums), set(l_c_nums)
                    new_v = sorted(list(set(n for n in pulled_vols if n not in l_v_set)))
                    new_c = sorted(list(set(n for n in pulled_chaps if n not in l_c_set)))
                    
                    if new_v or new_c:
                        console.print(f"[bold yellow][5/8] Fills Gaps:[/bold yellow] Vols: {format_ranges(new_v)} | Chaps: {format_ranges(new_c)}")
                    else:
                        console.print("[yellow][5/8] All pulled content already exists in library (Potential Upgrade).[/yellow]")
                else:
                    console.print("[bold cyan][5/8] NEW SERIES: No match found in library. This will be a new entry.[/bold cyan]")

        # Step 6: Import Files
        action_msg = "Importing files into library..."
        if simulate:
            console.print(f"[yellow][6/8] SIMULATE: {action_msg}[/yellow]")
        else:
            if not library:
                console.print("[red][6/8] ✗ Library root not found. Skipping import.[/red]")
            else:
                target_dir = None
                is_new = False
                if local_series:
                    target_dir = Path(local_series.path)
                else:
                    # New series path logic
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    target_dir = Path(library.path) / "Uncategorized" / f"Pulled-{date_str}" / series_name
                    is_new = True
                
                if target_dir and pulled_files:
                    # Collect all local unit numbers if matched
                    l_v_set, l_c_set = set(), set()
                    if local_series:
                        all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
                        for v in all_local_vols:
                            v_n, c_n, u_n = classify_unit(v.name)
                            l_v_set.update(v_n); l_c_set.update(c_n + u_n)

                    # Pre-calculate files that actually need importing
                    files_to_import = []
                    overwrite_count = 0
                    for file_info in pulled_files:
                        f_path = file_info["path"]
                        v_nums, ch_nums = file_info["v"], file_info["c"]
                        fills_gap = is_new or not (l_v_set or l_c_set) 
                        if not fills_gap:
                            if any(n not in l_v_set for n in v_nums) or any(n not in l_c_set for n in ch_nums):
                                fills_gap = True
                        if fills_gap:
                            files_to_import.append(file_info)
                            if (target_dir / f_path.name).exists():
                                overwrite_count += 1

                    if files_to_import:
                        if pause:
                            console.print(f"\n[bold yellow][6/8] Ready to import {len(files_to_import)} files from {PULL_TEMPDIR} into: {target_dir}[/bold yellow]")
                            if overwrite_count > 0:
                                console.print(f"[bold red]WARNING: {overwrite_count} files already exist in the destination and will be overwritten![/bold red]")
                            
                            res = click.prompt("[6/8] Press Enter to continue, or 'q' to quit", default="", show_default=False)
                            if res.lower() == 'q':
                                console.print("[yellow][6/8] Import aborted by user.[/yellow]")
                                break

                        imported_count = 0
                        for file_info in files_to_import:
                            f_path = file_info["path"]
                            try:
                                if not target_dir.exists():
                                    target_dir.mkdir(parents=True, exist_ok=True)
                                
                                dest_path = target_dir / f_path.name
                                # We'll allow overwrite if the user confirmed the prompt above
                                console.print(f"[dim][6/8] Importing {f_path.name} into {series_name}[/dim]")
                                shutil.copy2(f_path, dest_path)
                                imported_count += 1
                            except Exception as e:
                                console.print(f"[red][6/8] ✗ Failed to import {f_path.name}: {e}[/red]")
                        
                        if imported_count > 0:
                            console.print(f"[green][6/8] ✓ Successfully imported {imported_count} files.[/green]")
                    else:
                        console.print("[yellow][6/8] No Gaps filled, nothing imported.[/yellow]")

        # Step 7: Update Library State
        action_msg = "[7/8] Updating library state..."
        if simulate:
            console.print(f"[yellow][7/8] SIMULATE: {action_msg}[/yellow]")
        else:
            if not library:
                console.print("[red][7/8] ✗ Library object missing. Skipping state update.[/red]")
            else:
                with console.status(f"[bold blue]{action_msg}"):
                    # 1. Re-scan the specific series folder
                    new_series_obj = scan_series(target_dir)
                    
                    if local_series:
                        # Update existing series in library
                        # Find where it is in the hierarchy and replace it
                        found = False
                        for cat in library.categories:
                            for sub in cat.sub_categories:
                                for idx, s in enumerate(sub.series):
                                    if s.path == local_series.path:
                                        # Preserve external_data if we have it
                                        new_series_obj.external_data = s.external_data
                                        sub.series[idx] = new_series_obj
                                        found = True
                                        break
                                if found: break
                            if found: break
                    else:
                        # Handle New Series in hierarchy
                        # Structure: Uncategorized -> Pulled-date -> Series
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        
                        # Find/Create Uncategorized Category
                        uncat = next((c for c in library.categories if c.name == "Uncategorized"), None)
                        if not uncat:
                            uncat = Category(name="Uncategorized", path=library.path / "Uncategorized")
                            library.categories.append(uncat)
                        
                        # Find/Create Pulled-date SubCategory
                        sub_name = f"Pulled-{date_str}"
                        subcat = next((s for s in uncat.sub_categories if s.name == sub_name), None)
                        if not subcat:
                            subcat = Category(name=sub_name, path=uncat.path / sub_name, parent=uncat)
                            uncat.sub_categories.append(subcat)
                        
                        # Add new series to subcategory
                        subcat.series.append(new_series_obj)

                    # 2. Save updated library to disk and cache
                    save_library_cache(library)
                    console.print("[green][7/8] ✓ Library state updated and saved.[/green]")

                    # 3. Verification
                    v_n, c_n, u_n = [], [], []
                    all_vols = new_series_obj.volumes + [v for sg in new_series_obj.sub_groups for v in sg.volumes]
                    for v in all_vols:
                        vn, cn, un = classify_unit(v.name)
                        v_n.extend(vn); c_n.extend(cn); u_n.extend(un)
                    
                    v_str = format_ranges(v_n)
                    c_str = format_ranges(c_n)
                    u_str = format_ranges(u_n)
                    console.print(f"[bold blue][7/8] Final Library Content for {series_name}:[/bold blue] Vols: {v_str} | Chaps: {c_str} | Units: {u_str}")

        # Step 8: Final Cleanup
        action_msg = "[8/8] Final cleanup: Removing torrent and clearing temp dir..."
        if simulate:
            console.print(f"[yellow][8/8] SIMULATE: {action_msg}[/yellow]")
        else:
            if pause:
                console.print(f"\n[bold red][8/8]Ready for final cleanup for: {series_name}[/bold red]")
                console.print(f"[dim] - Will delete torrent and source data: {t['name']}[/dim]")
                console.print(f"[dim] - Will clear temporary pull directory: {PULL_TEMPDIR}[/dim]")
                res = click.prompt("[8/8]Press Enter to execute cleanup, or 'q' to skip cleanup for this item", default="", show_default=False)
                if res.lower() == 'q':
                    console.print("[yellow][8/8]Cleanup skipped by user.[/yellow]")
                    continue

            with console.status(f"[bold blue]{action_msg}"):
                # 1. Remove torrent and data from qBittorrent
                if qbit.delete_torrents([t["hash"]], delete_files=True):
                    console.print("[green][8/8]✓ Torrent and source data removed from qBittorrent.[/green]")
                else:
                    console.print("[red][8/8]✗ Failed to remove torrent from qBittorrent.[/red]")

                # 2. Clear PULL_TEMPDIR
                if PULL_TEMPDIR and os.path.exists(PULL_TEMPDIR):
                    temp_path = Path(PULL_TEMPDIR)
                    for item in temp_path.iterdir():
                        try:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                        except Exception as e:
                            console.print(f"[red][8/8]✗ Failed to clear temp item {item.name}: {e}[/red]")
                    console.print("[green][8/8]✓ Temporary pull directory cleared.[/green]")

                # 3. Update match results
                if match_data:
                    found_entry = False
                    for entry in match_data:
                        # We match by name and the fact that it was previously marked as "grabbed"
                        if entry.get("name") == t["name"] and entry.get("grab_status") == "grabbed":
                            entry["grab_status"] = "pulled"
                            found_entry = True
                            # We don't break because there might be multiple entries for the same torrent 
                            # (though unlikely with name+grabbed filter, but safe)
                    
                    if found_entry:
                        try:
                            with open(input_file, 'w', encoding='utf-8') as f:
                                json.dump(match_data, f, indent=2)
                            console.print(f"[green][8/8]✓ Updated {input_file}: {t['name']} marked as pulled.[/green]")
                        except Exception as e:
                            console.print(f"[red][8/8]✗ Failed to update {input_file}: {e}[/red]")

        console.print(f"[green][8/8]✓ Finished processing {display_name}[/green]")
        
        if (pause or simulate) and i < len(completed) - 1:
            res = click.prompt("Press Enter to continue to the next item, or 'q' to quit", default="", show_default=False)
            if res.lower() == 'q':
                console.print("[yellow]Post-processing aborted by user.[/yellow]")
                break

    console.print(f"\n[bold green]Finished pulling {len(completed)} torrents![/bold green]")

