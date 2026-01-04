import os
import re
import json
import logging
import click
import time
import shutil
import difflib
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

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
    PULL_TEMPDIR,
    FUZZY_MATCH_THRESHOLD,
    SERIES_ALIASES
)
from .indexer import LibraryIndex
from .logging import get_logger, log_substep, temporary_log_level, console
from .cache import load_library_state, save_library_cache
from .matcher import consolidate_entries, parse_entry
from .metadata import fetch_from_jikan
from .scanner import scan_series
from .models import Category, Library, Series
from .analysis import (
    
    semantic_normalize,
    strip_volume_info,
    classify_unit,
    format_ranges,
    parse_size,
    format_size,
    sanitize_filename
)

logger = get_logger(__name__)

# Simple cache for LibraryIndex to avoid rebuilding it multiple times in a single command run
_index_cache = {}

def find_series_match(text: str, library: Library) -> Optional[Series]:
    """
    Finds a series in the library that matches the given text.
    Uses LibraryIndex for efficient matching.
    """
    lib_id = id(library)
    if lib_id not in _index_cache:
        index = LibraryIndex()
        index.build(library)
        _index_cache[lib_id] = index
    
    index = _index_cache[lib_id]
    candidates = generate_search_candidates(text)
    
    logger.debug(f"Searching for '{text}' with candidates: {candidates}")
    
    # 1. Exact/Synonym Search (Now includes SERIES_ALIASES via LibraryIndex)
    for cand in candidates:
        matches = index.search(cand)
        if matches:
            logger.debug(f"Found exact/synonym match: {matches[0].name} for candidate: {cand}")
            return matches[0]
            
    # 2. Fuzzy fallback - try ALL candidates
    thresh = FUZZY_MATCH_THRESHOLD / 100.0 if FUZZY_MATCH_THRESHOLD > 1.0 else FUZZY_MATCH_THRESHOLD
    for cand in candidates:
        matches = index.fuzzy_search(cand, threshold=thresh)
        if matches:
            logger.debug(f"Found fuzzy match: {matches[0].name} for candidate: {cand}")
            return matches[0]
            
        # Try with normalized punctuation
        normalized_cand = re.sub(r'[,\'꞉:]', '', cand).lower()
        if normalized_cand != cand.lower():
            matches = index.fuzzy_search(normalized_cand, threshold=thresh - 0.05)
            if matches:
                logger.debug(f"Found fuzzy match (punc-normalized): {matches[0].name} for candidate: {cand}")
                return matches[0]
            
    logger.warning(f"No match found for '{text}' - candidates tried: {candidates}")
    return None

def generate_search_candidates(text: str) -> List[str]:
    """
    Generates potential series title candidates from a raw filename/title.
    Replicates the logic from the old find_series_match to ensure robust matching.
    """
    raw_pieces = [text]
    
    # Split original text by common separators BEFORE stripping
    # Split by common separators (BEFORE stripping)
    for sep in ["|", "｜", " / ", " - "]:
        if sep in text:
            raw_pieces.extend([p.strip() for p in text.split(sep.strip()) if p.strip()])
    
    candidates = []
    
    # Extract bracketed content (often contains the title in some groups)
    # [Oshi no Ko] -> Oshi no Ko
    bracketed = re.findall(r'\[(.*?)\]|\((.*?)\)', text)
    for b in bracketed:
        content = b[0] or b[1]
        if content and len(content) > 3: # Ignore short tags
            candidates.append(content.strip())
            # Also try without "The" prefix if it exists
            if content.lower().startswith("the "):
                candidates.append(content[4:].strip())

    # Process all pieces through strip_volume_info
    for piece in raw_pieces:
        clean = strip_volume_info(piece)
        if clean:
            candidates.append(clean)
            
            # Add "The" variations
            if clean.lower().startswith("the "):
                candidates.append(clean[4:].strip())
            elif not clean.lower().startswith("the") and " the " not in clean.lower():
                # Only add "The " prefix if it doesn't seem to have one and isn't a skip word
                candidates.append(f"The {clean}")

            # Sub-split the cleaned version too, just in case
            for sub_sep in [":", "꞉", "!", " - "]:
                if sub_sep in clean:
                    candidates.extend([p.strip() for p in clean.split(sub_sep) if p.strip()])

    # Dedup and clean
    return sorted(list(set(c for c in candidates if c.strip())), key=len, reverse=True)

def get_matched_or_parsed_name(torrent_name: str, library_index: Optional[LibraryIndex] = None, match_data: Optional[List[Dict]] = None, series_map: Optional[Dict[str, Any]] = None) -> str:
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
                break

    # 2. Try Library Index Match (Exact/Synonym with Candidates)
    if library_index:
        candidates = generate_search_candidates(torrent_name)
        for cand in candidates:
            matches = library_index.search(cand)
            if matches:
                return f"[green]{matches[0].name}[/green]"
    
    # 3. Fallback to Parsing
    parsed = parse_entry({"name": torrent_name})
    parsed_names = parsed.get("parsed_name", [])
    if parsed_names and not any(n.startswith("SKIPPED:") for n in parsed_names):
        unique_names = []
        sorted_candidates = sorted(list(set(parsed_names)), key=len, reverse=True)
        
        for candidate in sorted_candidates:
            is_substring = False
            for selected in unique_names:
                if candidate in selected:
                    is_substring = True
                    break
            
            if not is_substring:
                unique_names.append(candidate)
                
        return " | ".join(unique_names)
    
    return f"[dim]{torrent_name}[/dim]"

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

def generate_transfer_plan(source_root: Path, series_name: str) -> List[Dict]:
    """
    Scans source_root for files, generates normalized names, and returns a plan.
    Does NOT move or rename files.
    """
    files_to_process = []
    
    if source_root.is_file():
        # Handle single-file torrents
        if source_root.suffix.lower() in [".cbz", ".cbr", ".pdf", ".zip", ".rar", ".7z", ".epub"]:
            files_to_process.append(source_root)
    else:
        # Walk and collect
        for root, _, files in os.walk(source_root):
            for f in files:
                path = Path(root) / f
                # Common archive/manga extensions
                if path.suffix.lower() in [".cbz", ".cbr", ".pdf", ".zip", ".rar", ".7z", ".epub"]:
                    files_to_process.append(path)
    
    if not files_to_process:
        return []

    files_to_process.sort() # Alphabetical sort for consistency
    
    plan = []
    seen_names = set()
    fallback_idx = 1
    
    for path in files_to_process:
        v_nums, ch_nums, u_nums = classify_unit(path.name)
        
        # Preferences: Volumes padded to 2, Chapters to 3
        v_str = vibe_format_range(v_nums, prefix="v", pad=2)
        
        c_nums = ch_nums
        c_prefix = ""
        if not c_nums and not v_nums and u_nums:
            c_nums = u_nums
            c_prefix = "c"
            
        c_str = vibe_format_range(c_nums, prefix=c_prefix, pad=3)
        
        parts = []
        if v_str: parts.append(v_str)
        if c_str: parts.append(c_str)
        
        if not parts:
            parts.append(f"unit{str(fallback_idx).zfill(3)}")
            fallback_idx += 1
            
        base_name = f"{series_name} {' '.join(parts)}"
        ext = path.suffix
        new_name = f"{base_name}{ext}"
        
        # Collision handling (logical)
        collision_idx = 1
        while new_name in seen_names:
            new_name = f"{base_name} ({collision_idx}){ext}"
            collision_idx += 1
            
        seen_names.add(new_name)
        
        plan.append({
            "src": path,
            "dst_name": new_name,
            "v": v_nums,
            "c": c_nums, # Using the raw detected ones for analysis
            "u": u_nums,
            "size": path.stat().st_size,
            "skip": False # Default to keep, will be updated in analysis step
        })
        
    return plan

def process_grab(name: Optional[str], input_file: str, status: bool, root_path: str, auto_add: bool = False, auto_add_only: bool = False, max_downloads: Optional[int] = None) -> None: 
    """
    Selects a manga from matched results and adds it to qBittorrent.
    
    Args:
        name: Name of the series to grab, or 'next'.
        input_file: Path to the JSON file with match results.
        status: If True, show current qBittorrent status instead of grabbing.
        root_path: Path to the library root directory.
        auto_add: If True, automatically grab new volumes without prompting.
        auto_add_only: If True, same as auto_add but skips non-matching groups instead of prompting.
        max_downloads: Maximum number of items to auto-add before stopping.
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
        # Terminal statuses always cause a group to be skipped in all 'next' modes
        terminal_statuses = ["grabbed", "skipped", "pulled", "blacklisted"]
        
        for i, g in enumerate(manga_groups):
            group_names = set(g["parsed_name"])
            group_entries = [e for e in data if any(n in group_names for n in e.get("parsed_name", []))]
            
            # A group is "processed" if any of its entries have a terminal or relevant skip status
            is_processed = False
            for e in group_entries:
                status_val = e.get("grab_status")
                if status_val in terminal_statuses:
                    is_processed = True
                    break
                # skipautoadd: Skip if in any auto-add mode (prompting or only)
                if (auto_add or auto_add_only) and status_val == "skipautoadd":
                    is_processed = True
                    break
                # skipautoaddonly: Skip only if in auto-add-only mode
                if auto_add_only and status_val == "skipautoaddonly":
                    is_processed = True
                    break
            
            if not is_processed:
                start_idx = i
                found = True
                break
        if not found:
            console.print("[green]All manga groups have been processed![/green]")
            return

    current_idx = start_idx
    total_added_count = 0
    groups_processed = 0
    groups_skipped = 0
    
    with console.status("[bold blue]Initializing grab process...[/bold blue]") as status:
        while current_idx < len(manga_groups):
            group = manga_groups[current_idx]

            # Identify group files
            group_files = []
            group_names = set(group["parsed_name"])
            for e in data:
                if any(n in group_names for n in e.get("parsed_name", [])):
                    group_files.append(e)

            match_id = group.get("matched_id")
            local_series = series_map.get(match_id) if match_id else None

            # Fallback: Try real-time matching if not found (using robust clean name logic)
            if not local_series and library:
                for clean_name in group.get("parsed_name", []):
                    # Try exact/fuzzy match with the clean name
                    found = find_series_match(clean_name, library)
                    if found:
                        local_series = found
                        # Update matched_name for display
                        group['matched_name'] = found.name
                        break

            # Pre-calculate content analysis for auto-skip
            l_v_nums, l_c_nums = [], []
            l_v_set, l_c_set = set(), set()
            new_v, new_c = set(), set()
            max_torrent_bytes = 0
        
            if local_series:
                all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
                for v in all_local_vols:
                    v_n, c_n, u_n = classify_unit(v.name)
                    l_v_nums.extend(v_n); l_c_nums.extend(c_n + u_n)
                
                l_v_set = set(l_v_nums)
                l_c_set = set(l_c_nums)
                
                # Define statuses to skip for content analysis
                skip_content = ["grabbed", "skipped", "pulled", "blacklisted", "skipautoadd"]
                if auto_add_only:
                    skip_content.append("skipautoaddonly")

                for f in group_files:
                    # Skip already processed files from content analysis
                    if f.get("grab_status") in skip_content:
                        continue

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

                # Auto-skip if no new content
                if not new_v and not new_c:
                    # Update status with transient message (no permanent output)
                    status.update(f"[dim]Processing Group {current_idx + 1}/{len(manga_groups)}: {', '.join(group['parsed_name'])} (No new content - skipping)[/dim]")
                    groups_skipped += 1
                    for f in group_files:
                        if not f.get("grab_status"):
                            f["grab_status"] = "skipped"
                    
                    try:
                        with open(input_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except Exception as e:
                        console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")
                    
                    current_idx += 1
                    continue

            # Auto-Add Logic
            if auto_add or auto_add_only:
                if max_downloads is not None and total_added_count >= max_downloads:
                    console.print(f"\n[yellow]Max downloads limit ({max_downloads}) reached. Stopping.[/yellow]")
                    return

                def is_jxl(f):
                    n = f.get("name", "").lower()
                    return "jxl" in n or "jpeg-xl" in n or "jpegxl" in n
                
                def is_completed(f):
                    return "completed" in f.get("name", "").lower()

                # Sort: Prefer Non-JXL (True > False), then Seeders
                sorted_group_files = sorted(
                    group_files, 
                    key=lambda x: (not is_jxl(x), int(x.get("seeders", 0))), 
                    reverse=True
                )
            
                files_to_auto_add = []
                volumes_handled_in_group = set()
                added_via_completed = False

                for f in sorted_group_files:
                    # Skip files that are terminal or already skipped for auto-add in this mode
                    skip_eval = ["grabbed", "skipped", "pulled", "blacklisted", "skipautoadd"]
                    if auto_add_only:
                        skip_eval.append("skipautoaddonly")
                        
                    if f.get("grab_status") in skip_eval:
                        continue

                    # Explicitly skip JXL/JPEG-XL formats for auto-add
                    if is_jxl(f):
                        continue

                    v_nums, _, _ = classify_unit(f.get("name", ""))
                    
                    # Criterion 1: New Volumes
                    if v_nums:
                        # Criteria: Must have volumes not in local library
                        new_vols_in_file = [v for v in v_nums if v not in l_v_set]
                        
                        if not local_series or new_vols_in_file:
                            # For new series, all volumes are "new"
                            v_to_check = v_nums if not local_series else new_vols_in_file
                            
                            # Check if this torrent provides any volumes we haven't already decided to grab in this group
                            if any(v not in volumes_handled_in_group for v in v_to_check):
                                grabbing_str = format_ranges(v_to_check)
                                if not local_series:
                                    reason = f"New series, grabbing volumes {grabbing_str}"
                                else:
                                    local_str = format_ranges(list(l_v_set))
                                    if len(local_str) > 30: local_str = local_str[:27] + "..."
                                    reason = f"Existing volumes {local_str}, grabbing {grabbing_str}"
                                
                                files_to_auto_add.append((f, reason))
                                volumes_handled_in_group.update(v_to_check)
                                continue # Move to next file
                
                    # Criterion 2: New Series + "Completed" tag (Handles Chapter-only series)
                    if not local_series and is_completed(f) and not added_via_completed:
                        # Check if we already grabbed a 'completed' set (or volumes) to avoid duplicates
                        # If it's a chapter-only series, volumes_handled_in_group will be empty.
                        files_to_auto_add.append((f, "New completed series"))
                        added_via_completed = True
            
                if files_to_auto_add:
                    # Print permanent message for additions
                    console.print(f"\n[bold blue]Auto-Adding {len(files_to_auto_add)} torrent(s) for: {', '.join(group['parsed_name'])}[/bold blue]")
                    added_count = 0
                    for f, reason in files_to_auto_add:
                        if max_downloads is not None and total_added_count >= max_downloads:
                            console.print(f"[yellow]Max downloads limit ({max_downloads}) reached. Stopping.[/yellow]")
                            return

                        magnet = f.get("magnet_link")
                        if magnet:
                            if qbit.add_torrent([magnet], tag=QBIT_DEFAULT_TAG, savepath=QBIT_DEFAULT_SAVEPATH):
                                console.print(f"[green]✓ Added: {f.get('name')}[/green] [dim]({reason})[/dim]")
                                f["grab_status"] = "grabbed"
                                added_count += 1
                                total_added_count += 1
                            else:
                                console.print(f"[red] - Failed to add: {f.get('name')}[/red]")
                    
                    if added_count > 0:
                        try:
                            with open(input_file, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                        except Exception as e:
                            console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")
                        
                        current_idx += 1
                        continue
        
                if auto_add_only:
                    # Update status with transient message (no permanent output)
                    status.update(f"[dim]Processing Group {current_idx + 1}/{len(manga_groups)}: {', '.join(group['parsed_name'])} (Auto-add criteria not met - skipping)[/dim]")
                    
                    # Mark unflagged files as skipautoaddonly so they are skipped in future --auto-add-only runs
                    for f in group_files:
                        if not f.get("grab_status"):
                            f["grab_status"] = "skipautoaddonly"
                    
                    try:
                        with open(input_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except Exception as e:
                        console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")

                    groups_skipped += 1
                    current_idx += 1
                    continue

            # Exit status context before interactive mode
            # This ensures the interactive prompt appears correctly
            status.stop()

            console.print(Rule(style="dim"))
            # Show selection info
            console.print(Panel(f"[bold cyan]Group {current_idx + 1}/{len(manga_groups)}: {', '.join(group['parsed_name'])}[/bold cyan]"))
            
            if group.get("matched_name"):
                console.print(f"[green]Library Match: {group['matched_name']}[/green]")
                
                if local_series:
                    # Use pre-calculated values
                    l_vols = format_ranges(l_v_nums)
                    l_chaps = format_ranges(l_c_nums)
                    size_str = format_size(local_series.total_size_bytes)
                    console.print(f"[bold yellow]Local Content: Vols: {l_vols} | Chaps: {l_chaps} | Size: {size_str}[/bold yellow]")

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
            
            choice = click.prompt("Enter ID(s) to grab (e.g. 1,2,3 or 'all'), 's' to skip, 'n' to next, or 'q' to quit", default="n")
            choice_clean = choice.lower().strip()
            
            if choice_clean == 'q':
                break
            elif choice_clean == 'n':
                # If we are in any auto-add mode, mark as skipautoadd to avoid re-prompting/re-evaluating next time
                if auto_add or auto_add_only:
                    for f in group_files:
                        if not f.get("grab_status"):
                            f["grab_status"] = "skipautoadd"
                    
                    try:
                        with open(input_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except Exception as e:
                        console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")

                current_idx += 1
                continue
            elif choice_clean == 's':
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
                
            # Parse IDs
            selected_indices = []
            if choice_clean == 'all':
                selected_indices = list(range(len(group_files)))
            else:
                # Handle both single digits and comma-separated
                parts = choice_clean.split(",")
                for p in parts:
                    p = p.strip()
                    if p.isdigit():
                        selected_indices.append(int(p) - 1)
            
            if selected_indices:
                added_any = False
                for idx in selected_indices:
                    if 0 <= idx < len(group_files):
                        selected = group_files[idx]
                        
                        # Skip if already grabbed
                        if selected.get("grab_status") == "grabbed":
                            console.print(f"[dim]ID {idx+1} already grabbed, skipping.[/dim]")
                            continue

                        magnet = selected.get("magnet_link")
                        if not magnet:
                            console.print(f"[red]No magnet link found for ID {idx+1}.[/red]")
                            continue
                        
                        if qbit.add_torrent([magnet], tag=QBIT_DEFAULT_TAG, savepath=QBIT_DEFAULT_SAVEPATH):
                            console.print(f"[bold green]Successfully added to qBittorrent: {selected.get('name')}[/bold green]")
                            selected["grab_status"] = "grabbed"
                            added_any = True
                        else:
                            console.print(f"[red]Failed to add torrent ID {idx+1} to qBittorrent.[/red]")
                    else:
                        console.print(f"[red]Invalid ID: {idx+1}[/red]")
                
                if added_any:
                    # Save updated data
                    try:
                        with open(input_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except Exception as e:
                        console.print(f"[red]Error saving updates to {input_file}: {e}[/red]")
                    
                    current_idx += 1
            else:
                console.print("[red]Invalid input. Use IDs (e.g. 1,2), 'all', 's', 'n', or 'q'.[/red]")

        # Print final summary
        if groups_processed > 0 or groups_skipped > 0:
            console.print(f"\n[bold green]Processing complete![/bold green]")
            console.print(f"[dim]Total groups processed: {groups_processed + groups_skipped}[/dim]")
            if groups_skipped > 0:
                console.print(f"[dim]Groups skipped (no new content): {groups_skipped}[/dim]")
            if total_added_count > 0:
                console.print(f"[bold green]Torrents added: {total_added_count}[/bold green]")
        elif current_idx >= len(manga_groups):
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
    
    logger.info("Pulling Completed Torrents")
    if simulate:
        logger.warning("SIMULATION MODE ACTIVE - No changes will be made.")
    
    if not QBIT_DOWNLOAD_ROOT:
        logger.warning("QBIT_DOWNLOAD_ROOT is not set in .env. Please set it to your local download path.")

    # Load match results
    match_data = []
    if input_file and os.path.exists(input_file):
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                match_data = json.load(f)
        except Exception as e:
            logger.error(f"Could not load match results from {input_file}: {e}")

    # Use status for connecting as it's a blocking op
    with console.status("[bold blue]Connecting to qBittorrent..."):
        torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
    
    if not torrents:
        logger.warning("No VibeManga torrents found in qBittorrent.")
        return

    # Load library
    library = None
    library_index = None
    series_map = {}
    if root_path:
        library = load_library_state(Path(root_path))
        if library:
            # Build Index for fast lookups
            log_substep("Building Library Index for fast matching...")
            library_index = LibraryIndex()
            library_index.build(library)
            
            for cat in library.categories:
                for sub in cat.sub_categories:
                    for s in sub.series:
                        try:
                            rel = s.path.relative_to(library.path)
                            sid = rel.as_posix()
                        except ValueError:
                            sid = s.name
                        series_map[sid] = s

    # Pre-calculate display names
    log_substep(f"Analyzing {len(torrents)} torrents...")
    for t in torrents:
        disp = get_matched_or_parsed_name(t["name"], library_index, match_data=match_data, series_map=series_map)
        t["_display_name"] = disp
        t["_sort_name"] = re.sub(r"\[.*?\]", "", disp).lower()

    # Sort
    sorted_torrents = sorted(torrents, key=lambda x: (x.get("progress") >= 1.0, x.get("_sort_name")))
    completed = [t for t in sorted_torrents if t.get("progress") == 1.0]
    
    # Table is visual, keep console.print
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
        logger.info(f"Found {len(torrents)} VibeManga torrents, but none are completed (100%).")
        return

    if not simulate and not pause:
        pass

    if not click.confirm(f"Proceed with post-processing {len(completed)} completed torrents?"):
        console.print("[yellow]Operation cancelled.[/yellow]")
        return

    for i, t in enumerate(completed):
        display_name = t["_display_name"]
        logger.info(f"Processing [{i+1}/{len(completed)}]: {t['_sort_name']}")
        
        # Step 1: Stop Torrent
        if simulate:
            logger.info("[SIMULATE] Stopping torrent...")
        else:
            if qbit.pause_torrents([t["hash"]]):
                log_substep("Torrent stopped")
            else:
                logger.error("Failed to stop torrent")
                if not click.confirm("Continue anyway?"): break

        # Step 2: Identify Location
        raw_path = t.get("content_path") or os.path.join(t.get("save_path", ""), t["name"])
        content_path = raw_path
        if QBIT_DOWNLOAD_ROOT:
            clean_path = raw_path.lstrip("/").lstrip("\\")
            if ":" in clean_path:
                clean_path = clean_path.split(":", 1)[1].lstrip("/").lstrip("\\")
            content_path = os.path.join(QBIT_DOWNLOAD_ROOT, clean_path)
            
        if simulate:
            logger.info(f"[SIMULATE] Locating files at {content_path}")
        else:
            if content_path and os.path.exists(content_path):
                log_substep(f"Found files at: {content_path}")
            else:
                logger.error(f"Could not find files at: {content_path}")
                if not click.confirm("Continue anyway?"): break

        # Step 3: Calculate Names
        # Don't strip brackets here anymore, strip_volume_info and semantic_normalize handle it better,
        # and it might be the actual title (e.g. [Oshi no Ko]).
        series_name = re.sub(r"^\d+\.\s+", "", display_name).strip()
        series_name = sanitize_filename(series_name)
        
        if simulate:
            logger.info(f"[SIMULATE] Analyzing content for: {series_name}")
        
        transfer_plan = []
        if os.path.exists(content_path):
             transfer_plan = generate_transfer_plan(Path(content_path), series_name)
        
        if not transfer_plan:
            logger.error(f"No valid files found in {content_path}")
            continue

        log_substep(f"Identified {len(transfer_plan)} potential files")
        for item in transfer_plan:
             logger.debug(f"[dim]Found File: {item['src'].name} -> {item['dst_name']} (v:{item['v']} c:{item['c']} u:{item['u']})[/dim]")
        
        # Log a summary of what was found
        total_v = len(set(n for item in transfer_plan for n in item['v']))
        total_c = len(set(n for item in transfer_plan for n in item['c'] + item['u']))
        logger.info(f"Torrent contains: [bold cyan]{total_v} volumes[/bold cyan] and [bold cyan]{total_c} chapters/units[/bold cyan]")

        # Step 4: Analyze (Filter Plan)
        local_series = None
        if match_data and series_map:
            for entry in match_data:
                if entry.get("name") == t["name"]:
                    mid = entry.get("matched_id")
                    if mid and mid in series_map:
                        local_series = series_map[mid]
                    break
        
        if not local_series and library_index:
            # Robust candidate generation from multiple sources
            # 1. From our calculated series_name
            candidates = generate_search_candidates(series_name)
            
            # 2. From the raw torrent name (if different)
            if t['name'] != series_name:
                raw_candidates = generate_search_candidates(t['name'])
                for rc in raw_candidates:
                    if rc not in candidates: candidates.append(rc)
            
            # 3. From the display name (if different)
            if display_name != series_name and display_name != t['name']:
                disp_candidates = generate_search_candidates(display_name)
                for dc in disp_candidates:
                    if dc not in candidates: candidates.append(dc)
            
            for cand in candidates:
                matches = library_index.search(cand)
                if matches: 
                    local_series = matches[0]
                    break
            
            # If no exact match, try fuzzy search on the best candidate (usually the first one)
            if not local_series and candidates:
                # Use project-wide threshold (usually 0.9 or 90)
                # LibraryIndex.fuzzy_search expects float 0.0-1.0
                thresh = FUZZY_MATCH_THRESHOLD / 100.0 if FUZZY_MATCH_THRESHOLD > 1.0 else FUZZY_MATCH_THRESHOLD
                fuzzy_matches = library_index.fuzzy_search(candidates[0], threshold=thresh)
                if fuzzy_matches:
                    local_series = fuzzy_matches[0]

        action_msg = "[4/8] Filtering content against library..."
        pulled_vols = []
        pulled_chaps = []
        pulled_units = []
        for item in transfer_plan:
            pulled_vols.extend(item['v'])
            pulled_chaps.extend(item['c'])
            pulled_units.extend(item['u'])
            
        log_substep(f"Scraped Content: Vols: {format_ranges(pulled_vols)} | Chaps: {format_ranges(pulled_chaps)}")

        if local_series:
            log_substep(f"Matched to Library: {local_series.name}")
            
            # Fix filenames if series_name was generic/incorrect
            sanitized_local_name = sanitize_filename(local_series.name)
            if sanitized_local_name != series_name:
                for item in transfer_plan:
                    if item['dst_name'].startswith(series_name):
                         item['dst_name'] = sanitized_local_name + item['dst_name'][len(series_name):]
                
                # Update series_name for subsequent steps (folder naming)
                series_name = sanitized_local_name

            all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
            l_v_nums, l_c_nums = [], []
            for v in all_local_vols:
                v_n, c_n, u_n = classify_unit(v.name)
                l_v_nums.extend(v_n); l_c_nums.extend(c_n + u_n)
            
            l_v_set, l_c_set = set(l_v_nums), set(l_c_nums)
            new_v = sorted(list(set(n for n in pulled_vols if n not in l_v_set)))
            new_c = sorted(list(set(n for n in pulled_chaps if n not in l_c_set)))
            
            if new_v or new_c:
                msg = "Fills Gaps:"
                if new_v: msg += f" [bold green]Vols: {format_ranges(new_v)}[/bold green]"
                if new_c: msg += f" [bold green]Chaps: {format_ranges(new_c)}[/bold green]"
                logger.info(msg)
                log_substep(f"Fills Gaps: Vols: {format_ranges(new_v)} | Chaps: {format_ranges(new_c)}")
            else:
                logger.info("All pulled content already exists in library (Potential Upgrade/Duplicate).")
                
            skipped_count = 0
            for item in transfer_plan:
                is_redundant = True
                if item['v']:
                    if any(n not in l_v_set for n in item['v']): is_redundant = False
                elif item['c']:
                    if any(n not in l_c_set for n in item['c']): is_redundant = False
                elif item['u']:
                     if any(n not in l_c_set for n in item['u']): is_redundant = False
                else:
                    is_redundant = False
                    
                if is_redundant:
                    item['skip'] = True
                    skipped_count += 1
                    
            if skipped_count > 0:
                log_substep(f"Marking {skipped_count} redundant files to skip copying.")
        else:
            log_substep("NEW SERIES: No match found in library. All files will be copied.")

        # Step 5: Stage (Copy)
        files_to_stage = [item for item in transfer_plan if not item['skip']]
        
        if not files_to_stage:
             logger.info("No files need to be copied (All redundant).")
        
        if not PULL_TEMPDIR:
             logger.error("PULL_TEMPDIR is not set. Cannot stage files.")
        else:
            dest_dir = Path(PULL_TEMPDIR)
            if not simulate:
                if dest_dir.exists() and any(dest_dir.iterdir()):
                    logger.warning(f"Temp directory is not empty: {dest_dir}")
                    if Confirm.ask("Clear temp directory? This is destructive!"):
                        for item in dest_dir.iterdir():
                            try:
                                if item.is_dir(): shutil.rmtree(item)
                                else: item.unlink()
                            except Exception as e:
                                logger.error(f"Error clearing {item}: {e}")
                        log_substep("Temp directory cleared")
                    else:
                        logger.warning("Pull aborted by user.")
                        break
            
            if simulate:
                logger.info(f"[SIMULATE] Staging {len(files_to_stage)} files to: {dest_dir}")
            else:
                 try:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                        console=console,
                        refresh_per_second=PROGRESS_REFRESH_RATE
                    ) as progress:
                        copy_task = progress.add_task(f"Copying {len(files_to_stage)} files...", total=len(files_to_stage))
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        for item in files_to_stage:
                            s = item['src']
                            d = dest_dir / item['dst_name']
                            logger.debug(f"Staging: [dim]{s}[/dim] -> [bold cyan]{d.name}[/bold cyan]")
                            shutil.copy2(s, d)
                            progress.update(copy_task, advance=1, description=f"[dim]Copying: {item['dst_name']}[/dim]")
                    
                    logger.info(f"Successfully staged {len(files_to_stage)} files to [bold cyan]{dest_dir}[/bold cyan]")
                    log_substep(f"Successfully staged {len(files_to_stage)} files.")
                 except Exception as e:
                    logger.error(f"Copy failed: {e}")
                    if not click.confirm("Continue anyway?"): break

        # Step 6: Import Files
        if simulate:
            logger.info("[SIMULATE] Importing files into library...")
        else:
            if not library:
                logger.error("Library root not found. Skipping import.")
            else:
                target_dir = Path(local_series.path) if local_series else Path(library.path) / "Uncategorized" / f"Pulled-{datetime.now().strftime('%Y-%m-%d')}" / series_name
                
                files_to_import = []
                overwrite_count = 0
                if files_to_stage and PULL_TEMPDIR:
                     for item in files_to_stage:
                         staged_path = Path(PULL_TEMPDIR) / item['dst_name']
                         if not staged_path.exists(): continue
                         files_to_import.append({
                             "path": staged_path,
                             "v": item['v'], "c": item['c'], "u": item['u']
                         })
                         if (target_dir / item['dst_name']).exists(): overwrite_count += 1

                if files_to_import:
                        if pause:
                            console.print(f"\n[bold yellow]Ready to import {len(files_to_import)} files from {PULL_TEMPDIR} into: {target_dir}[/bold yellow]")
                            if overwrite_count > 0:
                                console.print(f"[bold red]WARNING: {overwrite_count} files already exist in the destination and will be overwritten![/bold red]")
                            
                            res = click.prompt("Press Enter to continue, or 'q' to quit", default="", show_default=False)
                            if res.lower() == 'q': break

                        use_subfolders = False 
                        l_v_set, l_c_set = set(), set()
                        if local_series:
                            all_local_vols = local_series.volumes + [v for sg in local_series.sub_groups for v in sg.volumes]
                            for v in all_local_vols:
                                v_n, c_n, u_n = classify_unit(v.name)
                                l_v_set.update(v_n); l_c_set.update(c_n + u_n)
                        
                        all_vols_set = set(l_v_set)
                        all_chaps_set = set(l_c_set)
                        for f in files_to_import:
                            all_vols_set.update(f['v']); all_chaps_set.update(f['c']); all_chaps_set.update(f['u'])
                        
                        has_volumes = bool(all_vols_set)
                        has_chapters = bool(all_chaps_set)

                        target_vol_path = target_dir
                        target_chap_path = target_dir

                        if all_vols_set:
                            min_v = min(all_vols_set)
                            max_v = max(all_vols_set)
                            def fmt_num(n): return str(int(n)).zfill(2) if n.is_integer() else str(n).zfill(2)

                            vol_folder_name = f"{series_name} v{fmt_num(min_v)}-v{fmt_num(max_v)}"
                            if min_v == max_v: vol_folder_name = f"{series_name} v{fmt_num(min_v)}"
                                
                            chap_start = int(max_v) + 1
                            chap_folder_name = f"{series_name} v{str(chap_start).zfill(2)}+"
                            
                            existing_vol_dir = None
                            existing_chap_dir = None
                            s_name_esc = re.escape(series_name)
                            vol_pat = re.compile(rf"^{s_name_esc} v(\d+)(?:-v(\d+))?$", re.IGNORECASE)
                            chap_pat = re.compile(rf"^{s_name_esc} v(\d+)\+$", re.IGNORECASE)

                            if target_dir.exists():
                                for item in target_dir.iterdir():
                                    if item.is_dir():
                                        if vol_pat.match(item.name): existing_vol_dir = item; use_subfolders = True
                                        elif chap_pat.match(item.name): existing_chap_dir = item; use_subfolders = True
                            
                            if not use_subfolders and has_volumes and has_chapters:
                                use_subfolders = True
                            
                            if use_subfolders:
                                target_vol_path = target_dir / vol_folder_name
                                target_chap_path = target_dir / chap_folder_name
                                
                                if existing_vol_dir and existing_vol_dir.name != vol_folder_name:
                                    try:
                                        existing_vol_dir.rename(target_vol_path)
                                    except Exception as e:
                                        logger.error(f"Failed to rename volume folder: {e}")
                                        target_vol_path = existing_vol_dir
                                
                                if existing_chap_dir and existing_chap_dir.name != chap_folder_name:
                                    try:
                                        existing_chap_dir.rename(target_chap_path)
                                    except Exception as e:
                                        logger.error(f"Failed to rename chapter folder: {e}")
                                        target_chap_path = existing_chap_dir

                                # Move loose files from root to subfolders if we're now using subfolders
                                if target_dir.exists():
                                    if not target_vol_path.exists(): target_vol_path.mkdir(parents=True, exist_ok=True)
                                    if not target_chap_path.exists(): target_chap_path.mkdir(parents=True, exist_ok=True)
                                    
                                    for item in target_dir.iterdir():
                                        if item.is_file() and item.suffix.lower() in ['.cbz', '.cbr', '.zip', '.rar', '.pdf', '.epub']:
                                            v_nums, c_nums, u_nums = classify_unit(item.name)
                                            dest = None
                                            if v_nums: dest = target_vol_path / item.name
                                            elif c_nums or u_nums: dest = target_chap_path / item.name
                                            
                                            if dest and dest != item:
                                                try:
                                                    shutil.move(str(item), str(dest))
                                                    log_substep(f"Organized existing file {item.name} into subfolder")
                                                except Exception as e:
                                                    logger.error(f"Failed to organize existing file {item.name}: {e}")

                        imported_count = 0
                        for file_info in files_to_import:
                            f_path = file_info["path"]
                            dest_folder = target_dir 
                            if use_subfolders:
                                if file_info['v']: dest_folder = target_vol_path
                                elif file_info['c'] or file_info['u']: dest_folder = target_chap_path
                            
                            try:
                                if not dest_folder.exists(): dest_folder.mkdir(parents=True, exist_ok=True)
                                dest_path = dest_folder / f_path.name
                                logger.debug(f"Importing: [dim]{f_path.name}[/dim] -> [bold green]{dest_folder.name}[/bold green]")
                                shutil.copy2(f_path, dest_path)
                                imported_count += 1
                            except Exception as e:
                                logger.error(f"Failed to import {f_path.name}: {e}")
                        
                        if imported_count > 0:
                            logger.info(f"Successfully imported {imported_count} files into [bold green]{target_dir}[/bold green]")
                            log_substep(f"Successfully imported {imported_count} files.")
                else:
                    logger.info("No files to import.")

        # Step 7: Update Library State
        if simulate:
            logger.info("[SIMULATE] Updating library state...")
        else:
            if not library:
                logger.error("Library object missing. Skipping state update.")
            else:
                with console.status("[bold blue]Updating library state..."):
                    new_series_obj = scan_series(target_dir)
                    if local_series:
                        found = False
                        for cat in library.categories:
                            for sub in cat.sub_categories:
                                for idx, s in enumerate(sub.series):
                                    if s.path == local_series.path:
                                        new_series_obj.external_data = s.external_data
                                        sub.series[idx] = new_series_obj
                                        found = True
                                        break
                                if found: break
                            if found: break
                    else:
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        uncat = next((c for c in library.categories if c.name == "Uncategorized"), None)
                        if not uncat:
                            uncat = Category(name="Uncategorized", path=library.path / "Uncategorized")
                            library.categories.append(uncat)
                        sub_name = f"Pulled-{date_str}"
                        subcat = next((s for s in uncat.sub_categories if s.name == sub_name), None)
                        if not subcat:
                            subcat = Category(name=sub_name, path=uncat.path / sub_name, parent=uncat)
                            uncat.sub_categories.append(subcat)
                        subcat.series.append(new_series_obj)

                    save_library_cache(library)
                    log_substep("Library state updated and saved.")

                    v_n, c_n, u_n = [], [], []
                    all_vols = new_series_obj.volumes + [v for sg in new_series_obj.sub_groups for v in sg.volumes]
                    for v in all_vols:
                        vn, cn, un = classify_unit(v.name)
                        v_n.extend(vn); c_n.extend(cn); u_n.extend(un)
                    
                    log_substep(f"Final Library Content for {series_name}: Vols: {format_ranges(v_n)} | Chaps: {format_ranges(c_n)}")

        # Step 8: Final Cleanup
        if simulate:
            logger.info("[SIMULATE] Final cleanup...")
        else:
            if pause:
                console.print(f"\n[bold red]Ready for final cleanup for: {series_name}[/bold red]")
                res = click.prompt("Press Enter to execute cleanup, or 'q' to skip", default="", show_default=False)
                if res.lower() == 'q': continue

            with console.status("[bold blue]Final cleanup..."):
                if qbit.delete_torrents([t["hash"]], delete_files=True):
                    log_substep("Torrent removed from qBittorrent")
                else:
                    logger.error("Failed to remove torrent from qBittorrent")

                if PULL_TEMPDIR and os.path.exists(PULL_TEMPDIR):
                    for item in Path(PULL_TEMPDIR).iterdir():
                        try:
                            if item.is_dir(): shutil.rmtree(item)
                            else: item.unlink()
                        except Exception as e:
                            logger.error(f"Failed to clear temp item {item.name}: {e}")
                    log_substep("Temporary pull directory cleared")

                if match_data:
                    found_entry = False
                    for entry in match_data:
                        if entry.get("name") == t["name"] and entry.get("grab_status") == "grabbed":
                            entry["grab_status"] = "pulled"
                            found_entry = True
                    
                    if found_entry:
                        try:
                            with open(input_file, 'w', encoding='utf-8') as f:
                                json.dump(match_data, f, indent=2)
                            log_substep(f"Updated {input_file}: {t['name']} marked as pulled.")
                        except Exception as e:
                            logger.error(f"Failed to update {input_file}: {e}")

        logger.info(f"Finished processing {display_name}")
        
        if (pause or simulate) and i < len(completed) - 1:
            res = click.prompt("Press Enter to continue to the next item, or 'q' to quit", default="", show_default=False)
            if res.lower() == 'q':
                logger.info("Post-processing aborted by user.")
                break

    logger.info(f"Finished pulling {len(completed)} torrents!")

