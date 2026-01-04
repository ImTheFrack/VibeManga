"""
Duplicate Resolution System for VibeManga.

Provides interactive workflow for resolving duplicate manga series and files.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable

from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.text import Text
from rich.columns import Columns
from rich import box

from .models import Series, Volume
from .dedupe_engine import MALIDDuplicate, ContentDuplicate, DuplicateGroup
from .analysis import format_ranges, classify_unit
from .logging import console

logger = logging.getLogger(__name__)


class ResolutionAction(Enum):
    """Possible actions for resolving duplicates."""
    MERGE = "merge"
    KEEP_BOTH = "keep_both"
    DELETE = "delete"
    COMPARE = "compare"
    SKIP = "skip"
    WHITELIST = "whitelist"
    INSPECT = "inspect"  # New: Deep analysis
    VERIFY = "verify"    # New: Integrity check
    PREFER = "prefer"    # New: Keep one, delete others
    SUMMARIZE = "summarize"  # New: Re-show summary


@dataclass
class ResolutionPlan:
    """Represents a plan to resolve a duplicate group."""
    group_id: str
    action: ResolutionAction
    target_path: Optional[Path] = None
    source_paths: List[Path] = field(default_factory=list)
    conflict_resolution: Dict[str, str] = field(default_factory=dict)  # filename -> action
    metadata: Dict[str, Any] = field(default_factory=dict)


class DuplicateResolver:
    """Interactive resolver for duplicate groups."""
    
    def __init__(self, whitelist_path: Optional[Path] = None):
        self.whitelist_path = whitelist_path or Path("vibe_manga_duplicate_whitelist.json")
        self.whitelist = self._load_whitelist()
        self.resolution_plans: List[ResolutionPlan] = []
        self._summary_shown: Dict[str, bool] = {}  # Track which summaries have been shown
    
    def resolve_mal_id_duplicate(self, duplicate: MALIDDuplicate) -> Optional[ResolutionPlan]:
        """Interactively resolve a MAL ID conflict."""
        # Create unique key for this duplicate group
        group_key = f"mal_{duplicate.mal_id}"
        
        # Display comprehensive series information (only once)
        if not self._summary_shown.get(group_key, False):
            self._display_mal_id_conflict_header(duplicate)
            self._display_series_comparison(duplicate.series)
            self._display_file_comparison(duplicate.series)
            self._summary_shown[group_key] = True
        
        # Check whitelist
        if self._is_whitelisted(duplicate.mal_id):
            console.print("\n[dim]This conflict is whitelisted (keep both).[/dim]")
            return ResolutionPlan(
                group_id=group_key,
                action=ResolutionAction.KEEP_BOTH,
                metadata={'mal_id': duplicate.mal_id, 'reason': 'whitelisted'}
            )
        
        # Prompt for action with new options
        action = self._prompt_mal_id_action(duplicate)
        
        if action == ResolutionAction.SKIP:
            return None
        
        if action == ResolutionAction.KEEP_BOTH:
            if Confirm.ask("Add to whitelist to always keep both?"):
                self._add_to_whitelist(duplicate.mal_id)
            return ResolutionPlan(
                group_id=group_key,
                action=ResolutionAction.KEEP_BOTH,
                metadata={'mal_id': duplicate.mal_id}
            )
        
        if action == ResolutionAction.MERGE:
            return self._plan_merge(duplicate)
        
        if action == ResolutionAction.PREFER:
            return self._plan_prefer(duplicate)
        
        if action == ResolutionAction.COMPARE:
            self._show_detailed_comparison(duplicate.series)
            return self.resolve_mal_id_duplicate(duplicate)  # Recurse after comparison
        
        if action == ResolutionAction.INSPECT:
            self._deep_inspection(duplicate.series)
            return self.resolve_mal_id_duplicate(duplicate)  # Recurse after inspection
        
        if action == ResolutionAction.VERIFY:
            self._verify_integrity(duplicate.series)
            return self.resolve_mal_id_duplicate(duplicate)  # Recurse after verification
        
        if action == ResolutionAction.SUMMARIZE:
            # Re-show the summary
            self._summary_shown[group_key] = False
            return self.resolve_mal_id_duplicate(duplicate)
        
        return None
    
    def resolve_content_duplicate(self, duplicate: ContentDuplicate) -> Optional[ResolutionPlan]:
        """Interactively resolve content duplicates."""
        console.print(f"\n[bold yellow]Content Duplicate Detected:[/bold yellow] {len(duplicate.volumes)} files")
        console.print(f"Size: {duplicate.file_size / (1024*1024):.1f} MB, Pages: {duplicate.page_count or 'Unknown'}")
        
        # Group by series
        series_groups = {}
        for vol in duplicate.volumes:
            series_path = vol.path.parent
            if series_path not in series_groups:
                series_groups[series_path] = []
            series_groups[series_path].append(vol)
        
        # Show affected series
        console.print("\nAffected series:")
        for series_path, volumes in series_groups.items():
            console.print(f"  - {series_path.name}: {len(volumes)} files")
        
        # Check if this is within the same series (different subgroups)
        if len(series_groups) == 1:
            console.print("\n[yellow]All duplicates are within the same series.[/yellow]")
            action = Prompt.ask(
                "Action",
                choices=["merge", "delete", "skip"],
                default="merge"
            )
            if action == "merge":
                return self._plan_content_merge(duplicate)
            elif action == "delete":
                return self._plan_content_delete(duplicate)
        else:
            # Cross-series duplicates
            console.print("\n[red]Cross-series duplicates detected![/red]")
            action = Prompt.ask(
                "Action",
                choices=["compare", "delete", "skip"],
                default="compare"
            )
            if action == "compare":
                self._show_content_comparison(duplicate)
                return self.resolve_content_duplicate(duplicate)
            elif action == "delete":
                return self._plan_content_delete(duplicate)
        
        return None
    
    def resolve_fuzzy_duplicate(self, duplicate: DuplicateGroup) -> Optional[ResolutionPlan]:
        """Interactively resolve fuzzy name duplicates."""
        console.print(f"\n[bold yellow]Fuzzy Duplicate Detected:[/bold yellow] Confidence {duplicate.confidence:.1%}")
        
        # Display series information
        self._display_series_comparison(duplicate.items)
        
        # Check if they have MAL IDs
        mal_ids = {s.metadata.mal_id for s in duplicate.items if s.metadata.mal_id}
        if len(mal_ids) > 1:
            console.print("\n[red]Series have different MAL IDs - likely different series![/red]")
            if not Confirm.ask("Proceed anyway?"):
                return None
        
        action = Prompt.ask(
            "Action",
            choices=["merge", "keep_both", "compare", "skip"],
            default="compare"
        )
        
        if action == "skip":
            return None
        
        if action == "compare":
            self._show_detailed_comparison(duplicate.items)
            return self.resolve_fuzzy_duplicate(duplicate)
        
        if action == "merge":
            return self._plan_fuzzy_merge(duplicate)
        
        if action == "keep_both":
            return ResolutionPlan(
                group_id=duplicate.group_id,
                action=ResolutionAction.KEEP_BOTH,
                metadata={'confidence': duplicate.confidence}
            )
        
        return None
    
    def _display_mal_id_conflict_header(self, duplicate: MALIDDuplicate):
        """Display header information for MAL ID conflict."""
        console.print(f"\n[bold red]{'=' * 70}[/bold red]")
        console.print(f"[bold red]MAL ID CONFLICT DETECTED: {duplicate.mal_id}[/bold red]")
        console.print(f"[bold red]{'=' * 70}[/bold red]")
        
        # Show conflict severity
        series_count = len(duplicate.series)
        total_volumes = sum(s.total_volume_count for s in duplicate.series)
        total_size = sum(s.total_size_bytes for s in duplicate.series)
        
        info_panel = Panel(
            Group(
                Text(f"Series Count: {series_count}", style="bold"),
                Text(f"Total Volumes: {total_volumes}"),
                Text(f"Total Size: {total_size / (1024**3):.2f} GB"),
                Text(f"Potential Savings: {(total_size - max(s.total_size_bytes for s in duplicate.series)) / (1024**3):.2f} GB", style="green"),
            ),
            title="Conflict Summary",
            border_style="red"
        )
        console.print(info_panel)
    
    def _get_all_volumes(self, series: Series) -> List[Volume]:
        """Get all volumes including those in subgroups."""
        all_volumes = list(series.volumes)  # Root volumes
        
        # Add volumes from subgroups
        for subgroup in series.sub_groups:
            all_volumes.extend(subgroup.volumes)
        
        return all_volumes
    
    def _get_mal_id(self, series: Series) -> Optional[str]:
        """Get MAL ID from series metadata."""
        if hasattr(series, 'metadata') and series.metadata:
            return getattr(series.metadata, 'mal_id', None)
        return None
    
    def _display_series_comparison(self, series_list: List[Series]):
        """Display a comprehensive comparison table of series."""
        console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
        console.print(f"[bold cyan]SERIES COMPARISON[/bold cyan]")
        console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")
        
        # Create detailed table
        table = Table(title="Series Details", box=box.HEAVY, show_lines=True)
        table.add_column("Property", style="cyan", no_wrap=True)
        
        for i, series in enumerate(series_list):
            style = "green" if i == 0 else "yellow" if i == 1 else "white"
            table.add_column(f"Series {i+1}\n{series.name}", style=style, justify="left")
        
        # Basic Information
        table.add_section()
        table.add_row("[bold]BASIC INFO[/bold]", *["" for _ in series_list])
        table.add_row("Name", *[s.name for s in series_list])
        table.add_row("Full Path", *[str(s.path) for s in series_list])
        table.add_row("Category", *[s.path.parent.parent.name for s in series_list])
        table.add_row("Subcategory", *[s.path.parent.name for s in series_list])
        
        # MAL ID and Metadata
        mal_ids = []
        metadata_titles = []
        for s in series_list:
            mal_id = self._get_mal_id(s)
            mal_ids.append(str(mal_id) if mal_id else "None")
            
            if hasattr(s, 'metadata') and s.metadata:
                metadata_titles.append(s.metadata.title if s.metadata.title != "Unknown" else "N/A")
            else:
                metadata_titles.append("No metadata")
        
        table.add_section()
        table.add_row("[bold]METADATA[/bold]", *["" for _ in series_list])
        table.add_row("MAL ID", *mal_ids)
        table.add_row("Meta Title", *metadata_titles)
        
        # File Statistics
        vol_counts = [str(s.total_volume_count) for s in series_list]
        sizes = [f"{s.total_size_bytes / (1024**3):.2f} GB" for s in series_list]
        
        page_counts = []
        for s in series_list:
            if hasattr(s, 'total_page_count') and s.total_page_count > 0:
                page_counts.append(str(s.total_page_count))
            else:
                page_counts.append("Unknown")
        
        table.add_section()
        table.add_row("[bold]FILE STATISTICS[/bold]", *["" for _ in series_list])
        table.add_row("Volume Count", *vol_counts)
        table.add_row("Total Size", *sizes)
        table.add_row("Page Count", *page_counts)
        
        # Date Information
        date_added = []
        for s in series_list:
            if hasattr(s, 'date_added') and s.date_added:
                date_added.append(s.date_added.strftime("%Y-%m-%d"))
            else:
                date_added.append("Unknown")
        
        table.add_section()
        table.add_row("[bold]TIMESTAMPS[/bold]", *["" for _ in series_list])
        table.add_row("Date Added", *date_added)
        
        console.print(table)
    
    def _display_file_comparison(self, series_list: List[Series]):
        """Display detailed file comparison between series using unit numbers."""
        console.print(f"\n[bold cyan]{'=' * 70}[/bold cyan]")
        console.print(f"[bold cyan]FILE COMPARISON (by unit numbers)[/bold cyan]")
        console.print(f"[bold cyan]{'=' * 70}[/bold cyan]")
        
        # Collect all unit numbers from all series
        all_units = set()
        series_units = {}
        unit_to_files = {}  # Map unit numbers to actual filenames
        
        for series in series_list:
            units = set()
            for vol in self._get_all_volumes(series):
                # Extract unit numbers (volume/chapter/unit) from filename
                v, c, u = classify_unit(vol.name)
                vol_units = v or c or u
                
                for unit_num in vol_units:
                    all_units.add(unit_num)
                    units.add(unit_num)
                    # Store mapping from unit to filename for display
                    if unit_num not in unit_to_files:
                        unit_to_files[unit_num] = {}
                    unit_to_files[unit_num][series.name] = vol.name
            
            series_units[series.name] = units
        
        # Show volumes present in each series (by unit number)
        table = Table(title="Volume/Chapter Presence Comparison", box=box.ROUNDED)
        table.add_column("Unit", style="cyan", justify="right")
        for i, series in enumerate(series_list):
            table.add_column(f"Series {i+1}\n{series.name}", justify="center")
        table.add_column("Example Filename", style="dim")
        
        # Sort units numerically
        def unit_sort_key(unit):
            try:
                # Try to extract number from unit string (e.g., "v01" -> 1, "c123" -> 123)
                import re
                match = re.search(r'(\d+)', str(unit))
                return int(match.group(1)) if match else 0
            except:
                return 0
        
        sorted_units = sorted(all_units, key=unit_sort_key)
        
        for unit_num in sorted_units:
            row = [str(unit_num)]
            for series in series_list:
                if unit_num in series_units[series.name]:
                    row.append("✓")
                else:
                    row.append("✗")
            
            # Show example filename from first series that has this unit
            example_file = ""
            for series in series_list:
                if unit_num in unit_to_files and series.name in unit_to_files[unit_num]:
                    example_file = unit_to_files[unit_num][series.name]
                    break
            row.append(example_file)
            
            table.add_row(*row)
        
        console.print(table)
        
        # Show differences summary
        console.print(f"\n[bold]Differences Summary:[/bold]")
        for i, series in enumerate(series_list):
            other_units = set()
            for j, other_series in enumerate(series_list):
                if i != j:
                    other_units.update(series_units[other_series.name])
            
            unique_units = series_units[series.name] - other_units
            missing_units = other_units - series_units[series.name]
            
            console.print(f"\n[bold]Series {i+1}: {series.name}[/bold]")
            if unique_units:
                console.print(f"  [green]Unique: {len(unique_units)} units[/green] - {format_ranges(sorted(unique_units))}")
            if missing_units:
                console.print(f"  [yellow]Missing: {len(missing_units)} units[/yellow] - {format_ranges(sorted(missing_units))}")
            if not unique_units and not missing_units:
                console.print(f"  [dim]No differences[/dim]")
        
        # Show potential merge conflicts
        if len(series_list) == 2:
            series1_name = series_list[0].name
            series2_name = series_list[1].name
            
            common_units = series_units[series1_name] & series_units[series2_name]
            if common_units:
                console.print(f"\n[bold yellow]Potential Conflicts:[/bold yellow]")
                console.print(f"Both series have {len(common_units)} units with the same numbers")
                console.print(f"These will need to be resolved during merge (keep/replace/both)")
                console.print(f"Units: {format_ranges(sorted(common_units))}")
    
    def _deep_inspection(self, series_list: List[Series]):
        """Perform deep inspection of series files."""
        console.print(f"\n[bold magenta]{'=' * 70}[/bold magenta]")
        console.print(f"[bold magenta]DEEP FILE INSPECTION[/bold magenta]")
        console.print(f"[bold magenta]{'=' * 70}[/bold magenta]")
        
        for i, series in enumerate(series_list):
            console.print(f"\n[bold]Series {i+1}: {series.name}[/bold]")
            console.print(f"Path: {series.path}")
            
            all_volumes = self._get_all_volumes(series)
            if not all_volumes:
                console.print("  [dim]No volumes found[/dim]")
                continue
            
            # Analyze all volumes (including subgroups)
            total_files = len(all_volumes)
            total_size = 0
            total_pages = 0
            corrupted_files = []
            
            with console.status(f"[dim]Inspecting {total_files} files...[/dim]"):
                for vol in all_volumes:
                    try:
                        if vol.path.exists():
                            size = vol.path.stat().st_size
                            total_size += size
                            
                            # Try to open zip to check integrity
                            import zipfile
                            try:
                                with zipfile.ZipFile(vol.path, 'r') as zf:
                                    # Test zip integrity
                                    result = zf.testzip()
                                    if result is not None:
                                        corrupted_files.append((vol.name, f"Corrupted file: {result}"))
                            except zipfile.BadZipFile:
                                corrupted_files.append((vol.name, "Not a valid zip file"))
                            except Exception as e:
                                corrupted_files.append((vol.name, f"Error: {str(e)}"))
                        else:
                            corrupted_files.append((vol.name, "File not found"))
                    except Exception as e:
                        corrupted_files.append((vol.name, f"Error: {str(e)}"))
            
            # Display results
            console.print(f"  Files inspected: {total_files}")
            console.print(f"  Total size: {total_size / (1024**2):.1f} MB")
            console.print(f"  Average size: {total_size / total_files / 1024:.1f} KB" if total_files > 0 else "  Average size: N/A")
            
            if corrupted_files:
                console.print(f"  [red]Corrupted files: {len(corrupted_files)}[/red]")
                for name, reason in corrupted_files[:5]:  # Show first 5
                    console.print(f"    [red]- {name}: {reason}[/red]")
                if len(corrupted_files) > 5:
                    console.print(f"    [red]... and {len(corrupted_files) - 5} more[/red]")
            else:
                console.print(f"  [green]All files OK![/green]")
    
    def _verify_integrity(self, series_list: List[Series]):
        """Verify file integrity and generate checksums."""
        console.print(f"\n[bold blue]{'=' * 70}[/bold blue]")
        console.print(f"[bold blue]FILE INTEGRITY VERIFICATION[/bold blue]")
        console.print(f"[bold blue]{'=' * 70}[/bold blue]")
        
        import hashlib
        
        for i, series in enumerate(series_list):
            console.print(f"\n[bold]Series {i+1}: {series.name}[/bold]")
            
            all_volumes = self._get_all_volumes(series)
            if not all_volumes:
                console.print("  [dim]No volumes found[/dim]")
                continue
            
            table = Table(title=f"File Integrity - {series.name}")
            table.add_column("File", style="cyan")
            table.add_column("Size", style="white")
            table.add_column("Checksum", style="dim")
            table.add_column("Status", style="green")
            
            for vol in sorted(all_volumes, key=lambda v: v.name):
                try:
                    if vol.path.exists():
                        size = vol.path.stat().st_size
                        
                        # Calculate MD5 checksum
                        md5_hash = hashlib.md5()
                        with open(vol.path, "rb") as f:
                            for chunk in iter(lambda: f.read(4096), b""):
                                md5_hash.update(chunk)
                        checksum = md5_hash.hexdigest()[:8]
                        
                        table.add_row(
                            vol.name,
                            f"{size / 1024:.0f} KB",
                            checksum,
                            "✓ OK"
                        )
                    else:
                        table.add_row(
                            vol.name,
                            "N/A",
                            "N/A",
                            "✗ Missing"
                        )
                except Exception as e:
                    table.add_row(
                        vol.name,
                        "Error",
                        "Error",
                        f"✗ {str(e)[:20]}"
                    )
            
            console.print(table)
    
    def _prompt_mal_id_action(self, duplicate: MALIDDuplicate) -> ResolutionAction:
        """Prompt user for action on MAL ID conflict."""
        console.print(f"\n[bold yellow]How would you like to resolve this?[/bold yellow]")
        
        # Determine best recommendation
        volumes = [s.total_volume_count for s in duplicate.series]
        sizes = [s.total_size_bytes for s in duplicate.series]
        
        if max(volumes) > min(volumes) * 1.5:
            rec = "prefer"
            console.print("[dim]Recommendation: PREFER (significant size difference - choose which to keep)[/dim]")
        elif max(sizes) > min(sizes) * 2:
            rec = "prefer"
            console.print("[dim]Recommendation: PREFER (significant volume difference - choose which to keep)[/dim]")
        else:
            rec = "compare"
            console.print("[dim]Recommendation: COMPARE (similar size, manual review suggested)[/dim]")
        
        choices = ["merge", "prefer", "keep_both", "compare", "inspect", "verify", "summarize", "skip"]
        default = rec
        
        choice = Prompt.ask("Action", choices=choices, default=default)
        
        return ResolutionAction(choice)
    
    def _plan_merge(self, duplicate: MALIDDuplicate) -> ResolutionPlan:
        """Create a merge plan for MAL ID duplicates."""
        # Select primary (largest series)
        primary_idx = max(range(len(duplicate.series)), key=lambda i: (duplicate.series[i].total_volume_count, duplicate.series[i].total_size_bytes))
        primary = duplicate.series[primary_idx]
        
        # Others become sources
        sources = [s for i, s in enumerate(duplicate.series) if i != primary_idx]
        
        console.print(f"\n[green]Primary series selected:[/green] {primary.name}")
        console.print(f"Target: {primary.path}")
        console.print(f"Sources to merge: {len(sources)}")
        
        # Preview conflicts
        conflicts = self._preview_merge_conflicts(primary, sources)
        if conflicts:
            console.print(f"\n[yellow]Potential conflicts: {len(conflicts)}[/yellow]")
            if Confirm.ask("Review conflicts?", default=True):
                self._review_conflicts(conflicts)
        
        return ResolutionPlan(
            group_id=f"mal_merge_{duplicate.mal_id}",
            action=ResolutionAction.MERGE,
            target_path=primary.path,
            source_paths=[s.path for s in sources],
            metadata={
                'mal_id': duplicate.mal_id,
                'primary_name': primary.name,
                'source_names': [s.name for s in sources]
            }
        )
    
    def _plan_prefer(self, duplicate: MALIDDuplicate) -> ResolutionPlan:
        """Create a prefer plan - let user choose which series to keep."""
        console.print(f"\n[bold yellow]PREFER Action: Choose which series to keep[/bold yellow]")
        console.print("The other series will be deleted.")
        
        # Display series options
        for i, series in enumerate(duplicate.series):
            console.print(f"\n[{i+1}] {series.name}")
            console.print(f"    Path: {series.path}")
            console.print(f"    Volumes: {series.total_volume_count}")
            console.print(f"    Size: {series.total_size_bytes / (1024**3):.2f} GB")
        
        # Get user choice
        choice = IntPrompt.ask(
            "\nWhich series would you like to KEEP?",
            choices=[str(i+1) for i in range(len(duplicate.series))],
            default="1"
        )
        
        keep_idx = int(choice) - 1
        keep_series = duplicate.series[keep_idx]
        delete_series = [s for i, s in enumerate(duplicate.series) if i != keep_idx]
        
        console.print(f"\n[green]Will KEEP:[/green] {keep_series.name}")
        console.print(f"[red]Will DELETE:[/red] {len(delete_series)} series")
        
        return ResolutionPlan(
            group_id=f"mal_prefer_{duplicate.mal_id}",
            action=ResolutionAction.PREFER,
            target_path=keep_series.path,
            source_paths=[s.path for s in delete_series],
            metadata={
                'mal_id': duplicate.mal_id,
                'keep_name': keep_series.name,
                'delete_names': [s.name for s in delete_series]
            }
        )
    
    def _preview_merge_conflicts(self, primary: Series, sources: List[Series]) -> List[Dict[str, Any]]:
        """Preview potential conflicts in a merge."""
        conflicts = []
        
        # Get primary's volume numbers
        primary_vols = set()
        for vol in primary.volumes:
            v, c, u = classify_unit(vol.name)
            primary_vols.update(v or c or u)
        
        for source in sources:
            for vol in source.volumes:
                v, c, u = classify_unit(vol.name)
                vol_nums = v or c or u
                
                # Check for number overlap
                if any(num in primary_vols for num in vol_nums):
                    conflicts.append({
                        'source': source.name,
                        'volume': vol.name,
                        'numbers': vol_nums
                    })
        
        return conflicts
    
    def _review_conflicts(self, conflicts: List[Dict[str, Any]]):
        """Interactive conflict review."""
        console.print("\n[bold]Conflict Review[/bold]")
        
        for i, conflict in enumerate(conflicts[:10], 1):  # Show max 10
            console.print(f"\n{i}. {conflict['source']} -> {conflict['volume']}")
            console.print(f"   Numbers: {conflict['numbers']}")
            
            if i >= 10 and len(conflicts) > 10:
                console.print(f"\n... and {len(conflicts) - 10} more conflicts")
                break
    
    def _show_detailed_comparison(self, series_list: List[Series]):
        """Show detailed side-by-side comparison."""
        for i, series in enumerate(series_list):
            console.print(f"\n[bold]Series {i+1}: {series.name}[/bold]")
            console.print(f"Path: {series.path}")
            
            # Show volumes
            if series.volumes:
                console.print(f"\n[cyan]Root Volumes ({len(series.volumes)}):[/cyan]")
                for vol in sorted(series.volumes, key=lambda v: v.name)[:5]:
                    console.print(f"  - {vol.name}")
                if len(series.volumes) > 5:
                    console.print(f"  ... and {len(series.volumes) - 5} more")
            
            # Show subgroups
            if series.sub_groups:
                console.print(f"\n[cyan]SubGroups ({len(series.sub_groups)}):[/cyan]")
                for sg in series.sub_groups:
                    console.print(f"  - {sg.name}: {len(sg.volumes)} volumes")
            
            # Metadata
            if series.metadata and series.metadata.title != "Unknown":
                console.print(f"\n[cyan]Metadata:[/cyan]")
                console.print(f"  Title: {series.metadata.title}")
                if series.metadata.authors:
                    console.print(f"  Authors: {', '.join(series.metadata.authors)}")
                if series.metadata.genres:
                    console.print(f"  Genres: {', '.join(series.metadata.genres)}")
    
    def _show_content_comparison(self, duplicate: ContentDuplicate):
        """Show detailed content comparison."""
        table = Table(title="Content Duplicate Details")
        table.add_column("Series", style="cyan")
        table.add_column("File", style="white")
        table.add_column("Modified", style="dim")
        table.add_column("Size", style="yellow")
        
        for vol in duplicate.volumes:
            mtime = Path(vol.path).stat().st_mtime if vol.path.exists() else 0
            from datetime import datetime
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d') if mtime else "Unknown"
            
            table.add_row(
                vol.path.parent.name,
                vol.name,
                mtime_str,
                f"{vol.size_bytes / (1024*1024):.1f} MB"
            )
        
        console.print(table)
    
    def _plan_content_merge(self, duplicate: ContentDuplicate) -> ResolutionPlan:
        """Create merge plan for content duplicates."""
        # Group by series
        series_groups = {}
        for vol in duplicate.volumes:
            series_path = vol.path.parent
            if series_path not in series_groups:
                series_groups[series_path] = []
            series_groups[series_path].append(vol)
        
        # Select primary (series with most volumes)
        primary_path = max(series_groups.keys(), key=lambda p: len(series_groups[p]))
        
        # Create plan
        source_volumes = []
        for path, volumes in series_groups.items():
            if path != primary_path:
                source_volumes.extend(volumes)
        
        return ResolutionPlan(
            group_id=f"content_merge_{duplicate.file_hash[:8]}",
            action=ResolutionAction.MERGE,
            target_path=primary_path,
            source_paths=[vol.path for vol in source_volumes],
            metadata={
                'file_hash': duplicate.file_hash,
                'file_size': duplicate.file_size,
                'volume_count': len(duplicate.volumes)
            }
        )
    
    def _plan_content_delete(self, duplicate: ContentDuplicate) -> ResolutionPlan:
        """Create delete plan for content duplicates."""
        # Keep the newest file, delete others
        newest_vol = max(duplicate.volumes, key=lambda v: v.mtime)
        
        to_delete = [vol.path for vol in duplicate.volumes if vol.path != newest_vol.path]
        
        console.print(f"\n[green]Keeping:[/green] {newest_vol.path.name}")
        console.print(f"[red]Deleting:[/red] {len(to_delete)} older duplicates")
        
        return ResolutionPlan(
            group_id=f"content_delete_{duplicate.file_hash[:8]}",
            action=ResolutionAction.DELETE,
            source_paths=to_delete,
            metadata={
                'file_hash': duplicate.file_hash,
                'kept_file': str(newest_vol.path)
            }
        )
    
    def _plan_fuzzy_merge(self, duplicate: DuplicateGroup) -> ResolutionPlan:
        """Create merge plan for fuzzy duplicates."""
        # Select primary (largest series or one with MAL ID)
        primary = max(duplicate.items, key=lambda s: (s.metadata.mal_id is not None, s.total_volume_count))
        sources = [s for s in duplicate.items if s != primary]
        
        console.print(f"\n[green]Primary:[/green] {primary.name} ({primary.path})")
        console.print(f"[yellow]Sources:[/yellow] {len(sources)} series to merge")
        
        return ResolutionPlan(
            group_id=duplicate.group_id,
            action=ResolutionAction.MERGE,
            target_path=primary.path,
            source_paths=[s.path for s in sources],
            metadata={
                'confidence': duplicate.confidence,
                'primary_name': primary.name,
                'source_names': [s.name for s in sources]
            }
        )
    
    def _load_whitelist(self) -> List[int]:
        """Load whitelist of MAL IDs to keep as duplicates."""
        if self.whitelist_path.exists():
            try:
                data = json.loads(self.whitelist_path.read_text())
                return data.get('mal_ids', [])
            except Exception as e:
                logger.warning(f"Failed to load whitelist: {e}")
        return []
    
    def _save_whitelist(self):
        """Save whitelist to disk."""
        try:
            data = {'mal_ids': self.whitelist}
            self.whitelist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save whitelist: {e}")
    
    def _is_whitelisted(self, mal_id: int) -> bool:
        """Check if a MAL ID is whitelisted."""
        return mal_id in self.whitelist
    
    def _add_to_whitelist(self, mal_id: int):
        """Add a MAL ID to the whitelist."""
        if mal_id not in self.whitelist:
            self.whitelist.append(mal_id)
            self._save_whitelist()
            console.print(f"[green]Added MAL ID {mal_id} to whitelist[/green]")
    
    def get_resolution_summary(self) -> Dict[str, Any]:
        """Get summary of all resolution plans."""
        if not self.resolution_plans:
            return {'total_plans': 0}
        
        action_counts = {}
        for plan in self.resolution_plans:
            action_counts[plan.action.value] = action_counts.get(plan.action.value, 0) + 1
        
        return {
            'total_plans': len(self.resolution_plans),
            'action_counts': action_counts,
            'estimated_space_savings_mb': sum(
                p.metadata.get('file_size', 0) / (1024 * 1024) 
                for p in self.resolution_plans 
                if p.action == ResolutionAction.DELETE
            )
        }