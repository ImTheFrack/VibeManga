"""
Duplicate Resolution Actions for VibeManga.

Executes file operations (merge, delete, move) for duplicate resolution plans.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from rich.progress import Progress, TaskProgressColumn, TextColumn, BarColumn
from rich.console import Group

from .models import Series, Volume
from .dedupe_resolver import ResolutionPlan, ResolutionAction
from .logging import console
from .analysis import sanitize_filename, classify_unit

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of executing an action."""
    success: bool
    message: str
    files_moved: int = 0
    files_deleted: int = 0
    space_freed_mb: float = 0.0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class ActionExecutor:
    """Executes resolution plans with safety checks and progress tracking."""
    
    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.results: List[ActionResult] = []
    
    def execute_plan(self, plan: ResolutionPlan) -> ActionResult:
        """Execute a single resolution plan."""
        logger.info(f"Executing plan: {plan.group_id} - {plan.action.value}")
        
        if plan.action == ResolutionAction.MERGE:
            result = self._execute_merge(plan)
        elif plan.action == ResolutionAction.DELETE:
            result = self._execute_delete(plan)
        elif plan.action == ResolutionAction.PREFER:
            result = self._execute_prefer(plan)
        elif plan.action == ResolutionAction.KEEP_BOTH:
            result = ActionResult(True, "Kept both series (whitelisted or user choice)")
        else:
            result = ActionResult(True, f"Skipped action: {plan.action.value}")
        
        self.results.append(result)
        return result
    
    def execute_plans(self, plans: List[ResolutionPlan]) -> List[ActionResult]:
        """Execute multiple resolution plans with progress tracking."""
        if not plans:
            console.print("[yellow]No resolution plans to execute.[/yellow]")
            return []
        
        console.print(f"\n[bold]Executing {len(plans)} resolution plans...[/bold]")
        if self.simulate:
            console.print("[dim]SIMULATE mode - no changes will be made[/dim]")
        
        results = []
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Executing plans...", total=len(plans))
            
            for i, plan in enumerate(plans, 1):
                progress.update(task, description=f"Plan {i}/{len(plans)}: {plan.action.value}")
                
                result = self.execute_plan(plan)
                results.append(result)
                
                if result.success:
                    progress.console.print(f"[green]✓[/green] {result.message}")
                else:
                    progress.console.print(f"[red]✗[/red] {result.message}")
                    for error in result.errors:
                        progress.console.print(f"  [dim]Error: {error}[/dim]")
                
                progress.advance(task)
        
        return results
    
    def _execute_merge(self, plan: ResolutionPlan) -> ActionResult:
        """Execute a merge action."""
        result = ActionResult(True, f"Merged into {plan.target_path.name}")
        
        try:
            target_path = Path(plan.target_path)
            
            if not target_path.exists():
                return ActionResult(False, f"Target path does not exist: {target_path}")
            
            # Create backup of target metadata
            self._backup_metadata(target_path)
            
            # Move files from sources to target
            for source_path in plan.source_paths:
                source = Path(source_path)
                if not source.exists():
                    result.errors.append(f"Source does not exist: {source}")
                    continue
                
                # Move all files from source to target
                moved = self._move_series_files(source, target_path, plan, result)
                result.files_moved += moved
                
                # After moving, remove empty source directory
                if not self.simulate and source.exists() and not any(source.iterdir()):
                    source.rmdir()
                    logger.info(f"Removed empty directory: {source}")
            
            # Update target metadata
            self._update_target_metadata(target_path, plan)
            
            result.message = f"Merged {result.files_moved} files into {target_path.name}"
            
        except Exception as e:
            logger.error(f"Merge failed: {e}", exc_info=True)
            result.success = False
            result.message = f"Merge failed: {e}"
            result.errors.append(str(e))
        
        return result
    
    def _execute_delete(self, plan: ResolutionPlan) -> ActionResult:
        """Execute a delete action."""
        result = ActionResult(True, "Delete completed")
        
        try:
            total_size = 0
            for file_path in plan.source_paths:
                path = Path(file_path)
                if path.exists():
                    if path.is_file():
                        total_size += path.stat().st_size
                        if not self.simulate:
                            path.unlink()
                        result.files_deleted += 1
                        logger.info(f"Deleted: {path}")
                    else:
                        result.errors.append(f"Not a file: {path}")
                else:
                    result.errors.append(f"File not found: {path}")
            
            result.space_freed_mb = total_size / (1024 * 1024)
            result.message = f"Deleted {result.files_deleted} files ({result.space_freed_mb:.1f} MB freed)"
            
        except Exception as e:
            logger.error(f"Delete failed: {e}", exc_info=True)
            result.success = False
            result.message = f"Delete failed: {e}"
            result.errors.append(str(e))
        
        return result
    
    def _execute_prefer(self, plan: ResolutionPlan) -> ActionResult:
        """Execute a prefer action - delete all but the target series."""
        result = ActionResult(True, "Prefer action completed")
        
        try:
            # The target_path is the series to KEEP
            # The source_paths are series to DELETE
            keep_path = Path(plan.target_path)
            
            console.print(f"\n[green]Keeping:[/green] {keep_path.name}")
            console.print(f"[yellow]Deleting:[/yellow] {len(plan.source_paths)} other series")
            
            total_size = 0
            deleted_series = 0
            
            for source_path in plan.source_paths:
                source = Path(source_path)
                if source.exists() and source.is_dir():
                    series_size = 0
                    file_count = 0
                    
                    # Calculate size and count files
                    for item in source.rglob("*"):
                        if item.is_file():
                            series_size += item.stat().st_size
                            file_count += 1
                    
                    if not self.simulate:
                        # Delete the entire series directory
                        shutil.rmtree(source)
                    
                    total_size += series_size
                    deleted_series += 1
                    result.files_deleted += file_count
                    
                    logger.info(f"Deleted series: {source} ({file_count} files, {series_size / (1024**2):.1f} MB)")
                else:
                    result.errors.append(f"Series not found or not a directory: {source}")
            
            result.space_freed_mb = total_size / (1024 * 1024)
            result.message = f"Kept {keep_path.name}, deleted {deleted_series} series ({result.space_freed_mb:.1f} MB freed, {result.files_deleted} files)"
            
        except Exception as e:
            logger.error(f"Prefer action failed: {e}", exc_info=True)
            result.success = False
            result.message = f"Prefer action failed: {e}"
            result.errors.append(str(e))
        
        return result
    
    def _get_series_name_from_path(self, series_path: Path) -> str:
        """Extract series name from path."""
        return series_path.name
    
    def _detect_series_naming_pattern(self, series_path: Path) -> tuple[str, str, Optional[Path]]:
        """
        Detect the naming pattern of a series.
        
        Returns:
            Tuple of (base_name, unit_format, subgroup_path)
            - base_name: The series name (e.g., "One Piece")
            - unit_format: Format string for units (e.g., "v{:02d}", "c{}")
            - subgroup_path: Path to appropriate subgroup, or None for root
        """
        # Get series name from path
        base_name = self._get_series_name_from_path(series_path)
        
        # Default values
        unit_format = "v{}"  # Default
        subgroup_path = None
        
        # If path doesn't exist, return defaults
        if not series_path.exists():
            return base_name, unit_format, subgroup_path
        
        # Look for existing files to detect pattern
        existing_files = []
        for item in series_path.iterdir():
            if item.is_file() and item.suffix.lower() in ['.cbz', '.cbr', '.zip', '.rar']:
                existing_files.append(item.name)
        
        # If no files in root, check subgroups
        if not existing_files:
            for item in series_path.iterdir():
                if item.is_dir() and item.name not in ['.git', '__pycache__', 'series.json']:
                    # Check if this subgroup has files
                    subgroup_files = []
                    for subitem in item.iterdir():
                        if subitem.is_file() and subitem.suffix.lower() in ['.cbz', '.cbr', '.zip', '.rar']:
                            subgroup_files.append(subitem.name)
                    
                    if subgroup_files:
                        existing_files = subgroup_files
                        subgroup_path = item
                        break
        
        # Analyze existing files to detect pattern
        if existing_files:
            sample_file = existing_files[0]
            
            # Try to extract unit format from sample
            import re
            
            # Look for volume pattern: v01, v02, etc.
            vol_match = re.search(r'v(\d+)', sample_file, re.IGNORECASE)
            if vol_match:
            # Check if it uses leading zeros
                num = vol_match.group(1)
                if len(num) > 1 and num[0] == '0':
                    unit_format = f"v{{:0{len(num)}d}}"
                else:
                    unit_format = "v{}"
            else:
                # Look for chapter pattern: c001, c123, etc.
                chap_match = re.search(r'c(\d+)', sample_file, re.IGNORECASE)
                if chap_match:
                    num = chap_match.group(1)
                    if len(num) > 1 and num[0] == '0':
                        unit_format = f"c{{:0{len(num)}d}}"
                    else:
                        unit_format = "c{}"
                else:
                    # Look for unit pattern: unit001, etc.
                    unit_match = re.search(r'unit(\d+)', sample_file, re.IGNORECASE)
                    if unit_match:
                        num = unit_match.group(1)
                        if len(num) > 1 and num[0] == '0':
                            unit_format = f"unit{{:0{len(num)}d}}"
                        else:
                            unit_format = "unit{}"
        
        return base_name, unit_format, subgroup_path
    
    def _generate_target_filename(self, source_file: Path, target_base_name: str, target_unit_format: str) -> str:
        """
        Generate target filename based on source file and target series pattern.
        
        Args:
            source_file: Source file path
            target_base_name: Target series base name
            target_unit_format: Target series unit format string
            
        Returns:
            Target filename
        """
        # Extract unit numbers from source filename
        v, c, u = classify_unit(source_file.name)
        units = v or c or u
        
        if not units:
            # No unit numbers found, use original name
            logger.warning(f"Could not extract unit numbers from {source_file.name}, using original name")
            return source_file.name
        
        # Use the first unit number
        unit_num = units[0]
        
        # Format the unit number according to target pattern
        try:
            # Extract the numeric part
            import re
            num_match = re.search(r'(\d+(?:\.\d+)?)', str(unit_num))
            if num_match:
                num = float(num_match.group(1))
                # Format with the target pattern
                if "{}" in target_unit_format:
                    # Simple placeholder
                    unit_str = target_unit_format.format(int(num) if num.is_integer() else num)
                else:
                    # Format with leading zeros (e.g., {:02d})
                    unit_str = target_unit_format.format(int(num) if num.is_integer() else num)
            else:
                unit_str = str(unit_num)
        except:
            unit_str = str(unit_num)
        
        # Generate new filename
        ext = source_file.suffix
        target_filename = f"{target_base_name} {unit_str}{ext}"
        
        return target_filename
    
    def _move_series_files(self, source: Path, target: Path, plan: ResolutionPlan, result: ActionResult) -> int:
        """Move files from source to target with conflict resolution and smart renaming."""
        moved = 0
        
        # Detect target series naming pattern
        target_base_name, target_unit_format, target_subgroup = self._detect_series_naming_pattern(target)
        
        # If target has a subgroup pattern, use it
        if target_subgroup:
            target = target_subgroup
            console.print(f"[dim]Using subgroup: {target_subgroup.name}[/dim]")
        
        for item in source.iterdir():
            if item.is_file() and item.suffix.lower() in ['.cbz', '.cbr', '.zip', '.rar']:
                # Generate smart target filename based on target series pattern
                target_filename = self._generate_target_filename(item, target_base_name, target_unit_format)
                target_file = target / target_filename
                
                console.print(f"[dim]  {item.name} -> {target_filename}[/dim]")
                
                # Check for conflicts
                if target_file.exists():
                    conflict_action = plan.conflict_resolution.get(item.name, "skip")
                    
                    if conflict_action == "skip":
                        result.errors.append(f"Skipped (conflict): {item.name}")
                        continue
                    elif conflict_action == "replace":
                        if not self.simulate:
                            target_file.unlink()
                    elif conflict_action == "both":
                        # Rename with suffix
                        stem = target_file.stem
                        suffix = 1
                        while target_file.exists():
                            target_file = target / f"{stem}_dup{suffix}{item.suffix}"
                            suffix += 1
                
                # Move the file
                if not self.simulate:
                    shutil.move(str(item), str(target_file))
                moved += 1
                logger.debug(f"Moved: {item.name} -> {target_file}")
            
            elif item.is_dir() and item.name not in ['.git', '__pycache__']:
                # Recursively move subdirectory files
                sub_target = target / item.name
                if not self.simulate:
                    sub_target.mkdir(exist_ok=True)
                moved += self._move_series_files(item, sub_target, plan, result)
        
        return moved
    
    def _backup_metadata(self, target_path: Path):
        """Create backup of series.json before merge."""
        metadata_file = target_path / "series.json"
        if metadata_file.exists() and not self.simulate:
            backup_file = target_path / "series.json.backup"
            shutil.copy2(metadata_file, backup_file)
            logger.info(f"Backed up metadata: {backup_file}")
    
    def _update_target_metadata(self, target_path: Path, plan: ResolutionPlan):
        """Update target series.json after merge."""
        if self.simulate:
            return
        
        metadata_file = target_path / "series.json"
        
        try:
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {}
            
            # Add merge history
            if 'merge_history' not in metadata:
                metadata['merge_history'] = []
            
            metadata['merge_history'].append({
                'action': 'merge',
                'timestamp': str(Path().stat().st_mtime),
                'sources': [str(p) for p in plan.source_paths],
                'metadata': plan.metadata
            })
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Updated metadata: {metadata_file}")
            
        except Exception as e:
            logger.warning(f"Failed to update metadata: {e}")
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of all execution results."""
        if not self.results:
            return {'total_actions': 0}
        
        total_moved = sum(r.files_moved for r in self.results)
        total_deleted = sum(r.files_deleted for r in self.results)
        total_space_freed = sum(r.space_freed_mb for r in self.results)
        successful = sum(1 for r in self.results if r.success)
        failed = sum(1 for r in self.results if not r.success)
        
        return {
            'total_actions': len(self.results),
            'successful': successful,
            'failed': failed,
            'files_moved': total_moved,
            'files_deleted': total_deleted,
            'space_freed_mb': total_space_freed,
            'simulate': self.simulate
        }
    
    def save_execution_report(self, report_path: Path):
        """Save detailed execution report to JSON."""
        report = {
            'summary': self.get_execution_summary(),
            'actions': [
                {
                    'success': r.success,
                    'message': r.message,
                    'files_moved': r.files_moved,
                    'files_deleted': r.files_deleted,
                    'space_freed_mb': r.space_freed_mb,
                    'errors': r.errors
                }
                for r in self.results
            ]
        }
        
        try:
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"Saved execution report: {report_path}")
        except Exception as e:
            logger.warning(f"Failed to save report: {e}")