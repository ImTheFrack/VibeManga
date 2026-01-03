"""Categorize command for VibeManga CLI.

Automatically sorts series using AI analysis."""

import shutil
import json
import click
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.rule import Rule

from .base import (
    console, 
    get_library_root, 
    run_scan_with_progress, 
    run_model_assignment
)
from ..models import Library, Series
from ..categorizer import suggest_category, get_category_list
from ..analysis import sanitize_filename
from ..config import get_ai_role_config
from ..constants import (
    BYTES_PER_GB,
    PROGRESS_REFRESH_RATE
)
from ..logging import get_logger, log_step, log_substep

logger = get_logger(__name__)

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

def check_newroot_structure(newroot: Path) -> Tuple[bool, List[str]]:
    """
    Analyzes the new root for existing Category/SubCategory structure.
    Returns (True, list_of_categories) if structure is valid.
    Valid structure: More than one first-level folder (excluding Uncategorized)
    with at least 2 second-level folders in each.
    """
    if not newroot.exists():
        return False, []

    main_cats = []
    ignored = {"uncategorized", "__pycache__", ".git", "$recycle.bin", "system volume information"}
    
    # 1. Identify potential Main Categories
    for item in newroot.iterdir():
        if item.is_dir() and item.name.lower() not in ignored and not item.name.startswith("."):
            sub_count = 0
            has_subs = False
            for sub in item.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    sub_count += 1
            
            if sub_count >= 2:
                main_cats.append(item)
    
    # Criteria: More than one first-level folder...
    if len(main_cats) > 1:
        # Collect flattened list "Main/Sub"
        available = []
        for main in main_cats:
            for sub in main.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    available.append(f"{main.name}/{sub.name}")
        return True, available
    
    return False, []

@click.command()
@click.argument("query", required=False)
@click.option("--auto", is_flag=True, help="Automatically move folders without asking.")
@click.option("--simulate", is_flag=True, help="Dry run: show where folders would be moved without moving them.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan.")
@click.option("--model-assign", is_flag=True, help="Configure AI models for specific roles before running.")
@click.option("--pause", is_flag=True, help="Pause before each categorization decision.")
@click.option("--newroot", type=click.Path(), help="Target a NEW root directory. Copies files instead of moving. Detects schema from target.")
def categorize(query: Optional[str], auto: bool, simulate: bool, no_cache: bool, model_assign: bool, pause: bool, newroot: Optional[str]) -> None:
    """
    Automatically sorts series.
    Default: Moves 'Uncategorized' series into the library structure.
    With --newroot: Copies ALL series to the new root, adapting to its schema.
    """
    if model_assign:
        run_model_assignment()
        
    logger.info(f"Categorize command started (query={query}, auto={auto}, simulate={simulate}, no_cache={no_cache}, pause={pause}, newroot={newroot})")
    
    # Display AI Config
    display_ai_council_config()

    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library...",
        use_cache=not no_cache
    )

    # --- Mode Selection & Target Identification ---
    target_series: List[Series] = []
    mode = "move" # 'move' or 'copy'
    dest_root = Path(root_path)
    custom_schema: Optional[List[str]] = None
    use_ai = True
    
    if newroot:
        mode = "copy"
        dest_root = Path(newroot)
        console.print(f"[bold cyan]New Root Mode:[/bold cyan] Targeting {dest_root}")
        
        # 1. Validate / Create New Root
        if not dest_root.exists():
            if not simulate:
                if click.confirm(f"Directory {dest_root} does not exist. Create it?", default=True):
                    dest_root.mkdir(parents=True, exist_ok=True)
                else:
                    return
            else:
                 console.print("[yellow][SIMULATE] Would create directory.[/yellow]")

        # 2. Check Structure
        has_struct, schema = check_newroot_structure(dest_root)
        if has_struct:
            console.print(f"[green]Detected existing structure with {len(schema)} categories.[/green]")
            custom_schema = schema
            use_ai = True
        else:
            console.print("[yellow]No complex structure detected in new root.[/yellow]")
            console.print("[dim]Fallback: Copying all content to 'Uncategorized/Imported'. AI disabled.[/dim]")
            use_ai = False
            
        # 3. Select ALL series (filtered by query)
        for main in library.categories:
            for sub in main.sub_categories:
                for s in sub.series:
                    if not query or query.lower() in s.name.lower():
                        target_series.append(s)
        
        # 4. Check Disk Space
        total_bytes = sum(s.total_size_bytes for s in target_series)
        gb_needed = total_bytes / BYTES_PER_GB
        
        if dest_root.exists():
            try:
                usage = shutil.disk_usage(dest_root)
                free_gb = usage.free / BYTES_PER_GB
                console.print(f"Space Required: {gb_needed:.2f} GB | Available: {free_gb:.2f} GB")
                
                if usage.free < total_bytes:
                    console.print("[bold red]ERROR: Insufficient disk space on target drive.[/bold red]")
                    return
            except Exception:
                pass # Fallback if disk usage fails
    else:
        # Standard Mode: Uncategorized Only
        for main in library.categories:
            if main.name == "Uncategorized":
                for sub in main.sub_categories:
                    for s in sub.series:
                        if not query or query.lower() in s.name.lower():
                            target_series.append(s)
            else:
                 for sub in main.sub_categories:
                     if sub.name.startswith("Pulled-"):
                          for s in sub.series:
                              if not query or query.lower() in s.name.lower():
                                   target_series.append(s)

    if not target_series:
        console.print("[yellow]No matching series found to process.[/yellow]")
        return

    console.print(f"[cyan]Found {len(target_series)} series to process...[/cyan]")
    if simulate:
        console.print("[bold yellow][SIMULATION MODE] No files will be moved/copied.[/bold yellow]\n")

    countcurserries = 1
    for series in target_series:
        log_substep(f"Categorizing: {series.name}")
        console.print(Rule(f"[bold blue][{countcurserries} of {len(target_series)}] Processing: {series.name}[/bold blue]"))
        countcurserries += 1     
        user_feedback = None
        should_process = False
        final_cat_path = None
        
        # --- Fast Path for No-AI Copy ---
        if mode == "copy" and not use_ai:
            final_cat_path = dest_root / "Uncategorized" / "Imported" / series.name
            console.print(f"[dim]Destination set to: {final_cat_path}[/dim]")
            if auto or click.confirm("Proceed with copy?", default=True):
                should_process = True
            else:
                continue
        else:
            # --- AI Logic (Standard Move OR Newroot Copy with Schema) ---
            results = None 
            
            while True: # Interactive Loop for this series
                try:
                    if not results:
                        results = suggest_category(series, library, user_feedback=user_feedback, custom_categories=custom_schema)
                        if not results or not results.get("consensus"):
                            console.print(f"[red]Failed to get AI consensus for {series.name}. Skipping.[/red]")
                            break # Skip this series
                        
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
                    
                    # --- VISUALIZATION (Restored) ---
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

                    log_substep(f"Consensus: {final_cat}/{final_sub} (Conf: {conf:.2f})")

                    console.print(meta_text)
                    if syn_panel: console.print(syn_panel)
                    console.print(council_grid)
                    console.print(cons_panel)
                    # ---------------------

                    # Auto-Delete on Mod Flag (Restored logic)
                    if is_illegal and auto:
                        console.print(Rule("[bold red]AUTO-MODE: ILLEGAL CONTENT DETECTED[/bold red]"))
                        console.print(Panel(json.dumps(mod, indent=2), title="Moderator Full Response", border_style="red"))
                        
                        if mode == "move":
                            console.print(f"[bold red]DELETING {series.name}...[/bold red]")
                            if not simulate:
                                try:
                                    shutil.rmtree(series.path)
                                    console.print("[red]Series deleted.[/red]")
                                except Exception as e:
                                    console.print(f"[red]Failed to delete: {e}[/red]")
                            else:
                                console.print("[yellow][SIMULATE] Would DELETE series.[/yellow]")
                        else:
                            console.print("[bold red]SKIPPING ILLEGAL CONTENT (Copy Mode)[/bold red]")
                        
                        break # Done with this series
                    
                    # Auto-Move/Copy (if no flag)
                    if auto:
                        if pause:
                            console.print("[dim]Paused. Press Enter to continue...[/dim]")
                            click.pause()
                            
                        final_cat_path = dest_root / final_cat / final_sub / series.name
                        should_process = True
                        break

                    # Inner Menu Loop (Display & Choice)
                    action_taken = False
                    while True:
                        console.print("\n[bold]Options:[/bold]")
                        menu_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
                        menu_table.add_column("Key", style="bold cyan")
                        menu_table.add_column("Action")
                        menu_table.add_column("Description", style="dim")
                        
                        op_verb = "Copy" if mode == "copy" else "Move"
                        
                        menu_table.add_row(r"[a]", "Accept", f"{op_verb} to suggestion")
                        menu_table.add_row(r"[b]", "Reject", "Retry with instruction")
                        menu_table.add_row(r"[c]", "Blacklist", "Delete Series (Source)")
                        menu_table.add_row(r"[d]", "Info", "Show full AI analysis")
                        menu_table.add_row(r"[e]", "Manual", "Select category manually")
                        menu_table.add_row(r"[s]", "Skip", "Skip this series")
                        menu_table.add_row(r"[q]", "Quit", "Exit program")
                        console.print(menu_table)
                        
                        choice = click.prompt("Select action", default="a", show_default=True).lower().strip()
                        
                        if choice == 'a': # Accept
                            final_cat_path = dest_root / final_cat / final_sub / series.name
                            should_process = True
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
                            if mode == "copy":
                                console.print("[yellow]Blacklist: Skipping series (Source is PRESERVED in --newroot mode).[/yellow]")
                                action_taken = True
                                break

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
                            # Note: manual_select_category pulls from the source library.
                            # If using newroot with custom schema, we might want to adapt this,
                            # but for now we'll stick to source categories or just let user type.
                            manual = manual_select_category(library)
                            if manual:
                                 m_cat, m_sub = manual
                                 final_cat_path = dest_root / m_cat / m_sub / series.name
                                 should_process = True
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

        # --- Execute Operation (Merged Logic) ---
        if should_process and final_cat_path:
            op_name = "Copying" if mode == "copy" else "Moving"
            
            if simulate:
                console.print(f"[yellow][SIMULATE][/yellow] Would {op_name} to: [dim]{final_cat_path}[/dim]")
                continue

            # Ensure parent exists
            if not final_cat_path.parent.exists():
                final_cat_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                # Conflict Handling logic
                target_exists = final_cat_path.exists()
                if target_exists:
                    console.print(f"[yellow]Target directory exists: {final_cat_path}[/yellow]")
                    console.print("[dim]Attempting to merge contents...[/dim]")
                else:
                    final_cat_path.mkdir(parents=True, exist_ok=True)

                # Iterate and process items
                items = list(series.path.iterdir())
                
                # Show progress for large folders
                with Progress(
                    SpinnerColumn(),
                    TextColumn(f"[progress.description]{{task.description}}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    console=console
                ) as p:
                    task = p.add_task(f"{op_name} files...", total=len(items))
                    
                    moved_count = 0
                    conflict_count = 0

                    for item in items:
                        dest = final_cat_path / item.name
                        if dest.exists():
                            # console.print(f"  [red]Skipping {item.name} (Destination exists)[/red]")
                            conflict_count += 1
                        else:
                            if item.is_dir():
                                if mode == "copy":
                                    shutil.copytree(item, dest)
                                else:
                                    shutil.move(str(item), str(dest))
                            else:
                                if mode == "copy":
                                    shutil.copy2(item, dest)
                                else:
                                    shutil.move(str(item), str(dest))
                            moved_count += 1
                        p.advance(task)
                
                console.print(f"[green]✓ Processed {moved_count} items.[/green]")
                if conflict_count > 0:
                    console.print(f"[yellow]! {conflict_count} items skipped due to conflicts.[/yellow]")

                # Cleanup if Move
                if mode == "move":
                    if not any(series.path.iterdir()):
                        series.path.rmdir()
                        console.print("[dim]Source directory removed.[/dim]")
                    else:
                        console.print("[yellow]Source directory not empty (conflicts remaining). Kept.[/yellow]")
                else:
                    console.print("[green]Copy complete.[/green]")

            except Exception as e:
                console.print(f"[red]Error during {op_name}: {e}[/red]")

    console.print(Rule("[bold magenta]Processing Complete[/bold magenta]"))
