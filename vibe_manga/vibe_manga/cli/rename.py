"""
Rename command for VibeManga CLI.

Standardizes folder and file names based on metadata.
"""
import click
import logging
from pathlib import Path
from typing import Optional, List
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.live import Live
from rich.console import Group
from rich.rule import Rule

from .base import (
    console, 
    get_library_root, 
    run_scan_with_progress
)
from ..metadata import get_or_create_metadata
from ..cache import save_library_cache
from ..renamer import (
    generate_rename_plan, 
    execute_rename_op,
    add_to_whitelist, 
    generate_rename_op_for_series, 
    load_whitelist
)

logger = logging.getLogger(__name__)

def run_interactive_rename_selection(plan: List, prefer_english: bool = False, prefer_japanese: bool = False) -> Optional[List]:
    """
    Interactive TUI to select rename operations.
    Returns filtered list of operations, or None if aborted.
    """
    # Track selection by Object identity (ID), not the object itself (unhashable) 
    selected_ids = {id(op) for op in plan} 
    cursor_idx = 0
    view_start = 0
    
    # Constants for layout
    DETAIL_HEIGHT = 10
    STATUS_HEIGHT = 3
    HEADER_HEIGHT = 4 # Title + Table Header
    MIN_TABLE_HEIGHT = 5
    
    # Use Live display for smooth rendering (no flickering)
    # screen=True uses alternate screen buffer (restores terminal on exit)
    with Live(console=console, auto_refresh=False, screen=True) as live:
        while True:
            if not plan:
                live.stop()
                console.print("[yellow]All items removed/whitelisted.[/yellow]")
                return []

            # Dynamic Height Calculation
            term_height = console.size.height
            # Deduct fixed heights + extra safety buffer (20) to prevent overflow
            # (Detail=10, Status=3, Header~=4, Buffer=3)
            view_height = max(MIN_TABLE_HEIGHT, term_height - 20)

            # Scroll Logic
            if cursor_idx < view_start:
                view_start = cursor_idx
            elif cursor_idx >= view_start + view_height:
                view_start = cursor_idx - view_height + 1
            
            # Clamp view_start if list shrunk
            if view_start > len(plan) - view_height:
                view_start = max(0, len(plan) - view_height)
                
            view_end = min(view_start + view_height, len(plan))
            
            # 1. Build Table
            table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", expand=True)
            table.add_column("Sel", width=4, justify="center")
            table.add_column("Series Name", ratio=1, no_wrap=True, overflow="ellipsis")
            table.add_column("Target Name", ratio=1, no_wrap=True, overflow="ellipsis")
            
            for i in range(view_start, view_end):
                if i >= len(plan): break
                op = plan[i]
                is_cursor = (i == cursor_idx)
                is_selected = (id(op) in selected_ids)
                
                cursor_char = ">" if is_cursor else " "
                check_char = "[green]●[/green]" if is_selected else "[dim]○[/dim]"
                
                # Highlight row if cursor
                style = "reverse" if is_cursor else ""
                
                # Format Name
                c_name = op.current_name
                t_name = op.target_name
                if c_name != t_name:
                     t_name = f"[yellow]{t_name}[/yellow]"
                
                table.add_row(
                    f"{cursor_char} {check_char}",
                    c_name,
                    t_name,
                    style=style
                )
            
            # Fill empty rows to maintain height stability
            rows_filled = view_end - view_start
            if rows_filled < view_height:
                for _ in range(view_height - rows_filled):
                    table.add_row("", "", "")

            # 2. Build Detail Panel
            current_op = plan[cursor_idx] if plan else None
            detail_content = Text("No Series Selected", style="dim")
            
            if current_op:
                meta = current_op.series.metadata
                
                # Path
                path_str = str(current_op.series.path)
                
                # Genres/Tags
                genres = ", ".join(meta.genres[:5]) if meta.genres else "N/A"
                tags = ", ".join(meta.tags[:5]) if meta.tags else "N/A"
                
                # Synopsis (Truncate to fit ~4 lines)
                synopsis = meta.synopsis or "No synopsis available."
                synopsis = synopsis.replace("\n", " ").strip()
                if len(synopsis) > 300:
                    synopsis = synopsis[:297] + "..."
                
                detail_grid = Table.grid(padding=(0, 2))
                detail_grid.add_column(style="bold cyan", width=10)
                detail_grid.add_column(style="white")
                
                detail_grid.add_row("Path:", f"[dim]{path_str}[/dim]")
                detail_grid.add_row("Genres:", f"[green]{genres}[/green]")
                detail_grid.add_row("Tags:", f"[blue]{tags}[/blue]")
                
                # File Ops Summary
                if current_op.file_ops:
                    all_reasons = set()
                    for f_op in current_op.file_ops:
                        all_reasons.update(f_op.reasons)
                    reason_str = f" ({', '.join(sorted(all_reasons))})" if all_reasons else ""
                    detail_grid.add_row("File Ops:", f"{len(current_op.file_ops)} pending{reason_str}")
                    
                    # Show first 2 file ops as example
                    for f_op in current_op.file_ops[:2]:
                        f_reason = f" ({', '.join(f_op.reasons)})" if f_op.reasons else ""
                        detail_grid.add_row("", f"[dim]{f_op.original_path.name} -> {Path(f_op.new_rel_path).name}{f_reason}[/dim]")
                
                detail_grid.add_row("Synopsis:", f"[italic]{synopsis}[/italic]")
                
                detail_content = detail_grid

            detail_panel = Panel(
                detail_content, 
                title=f"[bold]Details: {current_op.series.name if current_op else 'None'}[/bold]", 
                box=box.ROUNDED, 
                border_style="cyan",
                height=DETAIL_HEIGHT
            )

            # 3. Build Status Panel
            status_text = (
                f"[bold]Selected: {len(selected_ids)}/{len(plan)}[/bold] | "
                f"[dim]↑/↓/j/k Move | Space Toggle | w Whitelist | m Force Meta | a All | n None | Enter Proceed | q Quit[/dim]"
            )
            status_panel = Panel(status_text, box=box.ROUNDED, border_style="blue", height=STATUS_HEIGHT)

            layout = Group(
                Rule("[bold magenta]Interactive Rename Selection[/bold magenta]"),
                table,
                detail_panel,
                status_panel
            )
            
            live.update(layout, refresh=True)
            
            # 4. Input Handling
            try:
                ch = click.getchar()
            except Exception:
                continue

            key = ch
            # Windows Arrow Keys (0x00 or 0xE0 followed by code)
            if ch == '\xe0' or ch == '\x00':
                ch2 = click.getchar()
                if ch2 == 'H': key = 'up'
                elif ch2 == 'P': key = 'down'
            # Unix ANSI sequences (ESC [ A/B)
            elif ch == '\x1b':
                ch2 = click.getchar()
                if ch2 == '[':
                    ch3 = click.getchar()
                    if ch3 == 'A': key = 'up'
                    elif ch3 == 'B': key = 'down'
            
            # Logic
            if key in ['q', 'Q']:
                return None
            elif key in ['\r', '\n', 'p']: # Enter
                # Return strictly the selected objects, preserving original order
                return [op for op in plan if id(op) in selected_ids]
            elif key in ['up', 'k']:
                cursor_idx = max(0, cursor_idx - 1)
            elif key in ['down', 'j']:
                cursor_idx = min(len(plan) - 1, cursor_idx + 1)
            elif key == ' ':
                op = plan[cursor_idx]
                if id(op) in selected_ids:
                    selected_ids.remove(id(op))
                else:
                    selected_ids.add(id(op))
            elif key == 'w':
                # Whitelist Logic
                op = plan[cursor_idx]
                add_to_whitelist(op.current_name)
                
                # Remove from plan and selection
                if id(op) in selected_ids:
                    selected_ids.remove(id(op))
                plan.pop(cursor_idx)
                
                # Adjust cursor
                if cursor_idx >= len(plan):
                     cursor_idx = max(0, len(plan) - 1)
            
            elif key == 'm':
                # Force Metadata Update
                op = plan[cursor_idx]
                
                # Stop live to allow console output/prompt
                live.stop()
                console.print(f"\n[bold blue]Force Updating Metadata for '{op.series.name}'...[/bold blue]")
                
                # Call Metadata (Force=True)
                new_meta, source = get_or_create_metadata(op.series.path, op.series.name, force_update=True)
                console.print(f"[green]Metadata Updated via {source}![/green]")
                console.print(f"Title: {new_meta.title}")
                
                # Regenerate Op
                wl = load_whitelist()
                new_op = generate_rename_op_for_series(op.series, wl, prefer_english=prefer_english, prefer_japanese=prefer_japanese)
                
                if new_op:
                    # Update Plan
                    plan[cursor_idx] = new_op
                    # Update selection if it was selected
                    if id(op) in selected_ids:
                        selected_ids.remove(id(op))
                        selected_ids.add(id(new_op))
                    console.print(f"[cyan]Rename operation updated: {new_op.target_name}[/cyan]")
                else:
                    console.print("[yellow]No rename needed after metadata update (or whitelisted). Removing from plan.[/yellow]")
                    if id(op) in selected_ids:
                        selected_ids.remove(id(op))
                    plan.pop(cursor_idx)
                    if cursor_idx >= len(plan):
                        cursor_idx = max(0, len(plan) - 1)
                
                console.print("[dim]Press any key to resume...[/dim]")
                click.getchar()
                live.start()

            elif key == 'a':
                selected_ids = {id(op) for op in plan}
            elif key == 'n':
                selected_ids.clear()
            elif key == 'i':
                new_sel = set()
                for op in plan:
                    if id(op) not in selected_ids:
                        new_sel.add(id(op))
                selected_ids = new_sel

@click.command()
@click.argument("query", required=False)
@click.option("--english", is_flag=True, help="Prefer English titles (from Metadata).")
@click.option("--japanese", is_flag=True, help="Prefer Japanese titles (from Metadata).")
@click.option("--auto", is_flag=True, help="Skip confirmation prompts.")
@click.option("--simulate", is_flag=True, help="Show preview without applying changes.")
@click.option("--force", is_flag=True, help="Overwrite destinations (dangerous).")
@click.option("--level", type=click.IntRange(1, 3), default=3, help="Safety Level (1=Trivial, 2=Safe/Fuzzy, 3=Aggressive). Default: 3")
@click.option("--interactive", is_flag=True, help="Interactively select items to rename.")
@click.option("--verbose", is_flag=True, help="Show detailed file-level rename reasons.")
def rename(query: Optional[str], english: bool, japanese: bool, auto: bool, simulate: bool, force: bool, level: int, interactive: bool, verbose: bool) -> None:
    """
    Standardizes folder and file names based on metadata.
    Renames the series folder to match the canonical title.
    Renames files inside to match the [Series] [Type] convention.
    Converts .zip/.rar extensions to .cbz/.cbr.
    """
    logger.info(f"Rename command started (query={query}, en={english}, jp={japanese}, auto={auto}, sim={simulate}, level={level})")
    
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning for Renames...",
        use_cache=False # Always fresh scan for file operations
    )

    with console.status("[bold blue]Generating Rename Plan..."):
        full_plan = generate_rename_plan(library, query, prefer_english=english, prefer_japanese=japanese)

    # Filter by level
    plan = [op for op in full_plan if op.safety_level <= level]
    skipped = len(full_plan) - len(plan)

    if not plan:
        console.print("[green]Library is already standardized! No renames needed.[/green]")
        if skipped > 0:
            console.print(f"[dim](Skipped {skipped} operations due to Safety Level limit {level})[/dim]")
        return

    # Interactive Mode
    if interactive and not auto:
        selection = run_interactive_rename_selection(plan, prefer_english=english, prefer_japanese=japanese)
        if selection is None:
            console.print("[yellow]Aborted.[/yellow]")
            return
        plan = selection
        if not plan:
            console.print("[yellow]No items selected (or all whitelisted).[/yellow]")
            return
        # Skip standard table if we just did interactive
        
    else:
        # Standard Preview Table
        table = Table(title=f"Rename Plan ({len(plan)} Series)", box=box.ROUNDED)
        table.add_column("Lvl", style="cyan", width=3)
        table.add_column("Current Name", style="dim")
        table.add_column("Target Name", style="bold green")
        table.add_column("File Ops", justify="right")
        table.add_column("Path", style="dim", max_width=40, overflow="ellipsis")

        for op in plan:
            file_count = len(op.file_ops)
            
            # Aggregate reasons
            all_reasons = set()
            for f_op in op.file_ops:
                all_reasons.update(f_op.reasons)
            
            reason_str = f" [dim]({', '.join(sorted(all_reasons))})[/dim]" if all_reasons else ""
            f_txt = f"{file_count} files{reason_str}" if file_count > 0 else "-"
            
            # Color code level
            lvl_color = "green" if op.safety_level == 1 else "yellow" if op.safety_level == 2 else "red"
            
            table.add_row(
                f"[{lvl_color}]{op.safety_level}[/{lvl_color}]", 
                op.current_name, 
                op.target_name, 
                f_txt, 
                str(op.current_path)
            )

            if verbose and op.file_ops:
                for f_op in op.file_ops:
                    formatted_reasons = []
                    for r in f_op.reasons:
                        if r == "Conflict":
                            formatted_reasons.append("[bold red]Conflict[/bold red]")
                        elif r == "Organize":
                            formatted_reasons.append("[cyan]Organize[/cyan]")
                        else:
                            formatted_reasons.append(r)
                            
                    f_reason = f" [dim]({', '.join(formatted_reasons)})[/dim]" if f_op.reasons else ""
                    
                    # If it's a subtle change, use repr()
                    subtle = any(r in f_op.reasons for r in ["Space", "Unicode", "Misc", "Path", "PathCase"])
                    
                    # Show full path for movement/structure
                    show_full = any(r in f_op.reasons for r in ["Path", "PathCase", "Move", "Organize"])
                    
                    if show_full:
                        try:
                            curr_rel = f_op.original_path.relative_to(op.current_path)
                            curr_display = str(curr_rel)
                        except ValueError:
                            curr_display = f_op.original_path.name
                        target_display = f_op.new_rel_path
                    else:
                        curr_display = f_op.original_path.name
                        target_display = Path(f_op.new_rel_path).name

                    if subtle:
                        curr_display = repr(curr_display)
                        target_display = repr(target_display)

                    table.add_row(
                        "",
                        f"  [dim]L {curr_display}[/dim]",
                        f"  [dim]-> {target_display}{f_reason}[/dim]",
                        "",
                        ""
                    )

        console.print(table)
        
        if skipped > 0:
            console.print(f"[yellow]Note: {skipped} aggressive renames were hidden/skipped by --level {level}[/yellow]")
    
    if simulate:
        console.print("[yellow][SIMULATION] No changes made.[/yellow]")
        return

    # Confirm (Only if NOT interactive, because interactive already had explicit "Proceed")
    if not auto and not interactive:
        if not click.confirm(f"Proceed with renaming {len(plan)} series?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    # Execute
    success_count = 0
    fail_count = 0
    
    with Progress(
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[green]Renaming...", total=len(plan))
        
        for op in plan:
            progress.update(task, description=f"Renaming: {op.current_name} -> {op.target_name}")
            
            # Check collision (unless force)
            if not force and op.target_path.exists() and op.target_path != op.current_path:
                console.print(f"[red]Skipping {op.current_name}: Target exists ({op.target_path})[/red]")
                fail_count += 1
                progress.advance(task)
                continue
                
            msgs = execute_rename_op(op)
            
            # Check for error messages
            errors = [m for m in msgs if "ERROR" in m]
            if errors:
                fail_count += 1
                for e in errors:
                    console.print(f"[red]{e}[/red]")
            else:
                success_count += 1
                
            progress.advance(task)

    console.print(Rule("[bold magenta]Rename Complete[/bold magenta]"))
    console.print(f"[green]Success: {success_count}[/green] | [red]Failed/Skipped: {fail_count}[/red]")
    
    # Save cache (paths changed!)
    save_library_cache(library)
    console.print("[dim]Library cache updated.[/dim]")
