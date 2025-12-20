import os
import logging
import concurrent.futures
from pathlib import Path
from typing import List, Optional, Dict, Callable

from .models import Library, Category, Series, SubGroup, Volume
from .analysis import inspect_archive
from .constants import VALID_MANGA_EXTENSIONS

logger = logging.getLogger(__name__)

def is_manga_file(path: Path) -> bool:
    """Checks if a file is a valid manga file based on extension."""
    return path.is_file() and path.suffix.lower() in VALID_MANGA_EXTENSIONS

def scan_volume(file_path: Path) -> Volume:
    """Creates a Volume object from a file path."""
    stat = file_path.stat()
    return Volume(
        path=file_path,
        name=file_path.name,
        size_bytes=stat.st_size
    )

def scan_series(series_path: Path) -> Series:
    """Scans a Series directory for volumes and sub-groups."""
    series = Series(name=series_path.name, path=series_path)
    
    # scan content
    try:
        for item in series_path.iterdir():
            if item.name.startswith('.'):
                continue # skip hidden files
            
            if is_manga_file(item):
                series.volumes.append(scan_volume(item))
            elif item.is_dir():
                # This is a SubGroup (e.g. 'v01-v12' or 'Side Story')
                sub_group = SubGroup(name=item.name, path=item)
                # Scan files inside the sub-group
                for sub_item in item.iterdir():
                    if is_manga_file(sub_item):
                        sub_group.volumes.append(scan_volume(sub_item))
                
                # Only add the sub-group if it has content or we want to track empty ones?
                # Let's track it if it exists, stats will show 0 volumes if empty.
                series.sub_groups.append(sub_group)
    except PermissionError as e:
        logger.warning(f"Permission denied accessing {series_path}: {e}")

    return series

def scan_library(
    root_path_str: str,
    progress_callback: Optional[Callable[[int, int, Series], None]] = None
) -> Library:
    """
    Main entry point to scan the library.

    Args:
        root_path_str: Path to the library root.
        progress_callback: Optional callable(current, total, series_obj)
    """
    root = Path(root_path_str)
    library = Library(path=root)
    
    if not root.exists():
        return library

    # We will collect futures here to map them back to the correct sub-category
    # Map[Future, Category]
    future_to_subcat = {}
    
    # Pre-calculate tasks to allow for progress tracking
    # List of (series_path, sub_category_obj)
    series_tasks = []

    # Level 1: Main Categories
    try:
        for main_cat_path in root.iterdir():
            if not main_cat_path.is_dir() or main_cat_path.name.startswith('.'):
                continue
                
            main_cat = Category(name=main_cat_path.name, path=main_cat_path)
            
            # Level 2: Sub Categories
            for sub_cat_path in main_cat_path.iterdir():
                if not sub_cat_path.is_dir() or sub_cat_path.name.startswith('.'):
                    continue
                    
                sub_cat = Category(name=sub_cat_path.name, path=sub_cat_path, parent=main_cat)
                
                # Level 3: Series - Identify them but don't scan yet
                for series_path in sub_cat_path.iterdir():
                    if not series_path.is_dir() or series_path.name.startswith('.'):
                        continue
                    
                    series_tasks.append((series_path, sub_cat))
                
                main_cat.sub_categories.append(sub_cat)
            
            library.categories.append(main_cat)

    except PermissionError as e:
        logger.error(f"Error scanning library structure: {e}")

    total_series = len(series_tasks)
    completed_series = 0

    # Use a ThreadPoolExecutor to parallelize I/O operations
    with concurrent.futures.ThreadPoolExecutor() as executor:
        
        # Submit all tasks
        for series_path, sub_cat in series_tasks:
            future = executor.submit(scan_series, series_path)
            future_to_subcat[future] = sub_cat

        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_subcat):
            sub_cat = future_to_subcat[future]
            try:
                series = future.result()
                sub_cat.series.append(series)
                
                completed_series += 1
                if progress_callback:
                    progress_callback(completed_series, total_series, series)

            except Exception as exc:
                logger.error(f"Error scanning series: {exc}", exc_info=True)

    return library

def enrich_series(series: Series, deep: bool = False, verify: bool = False) -> Series:
    """
    Performs deep analysis/verification on a Series.
    Modifies the series object in-place.
    """
    if not (deep or verify):
        return series
        
    for vol in series.volumes:
        pages, corrupt = inspect_archive(vol.path, check_integrity=verify)
        if deep:
            vol.page_count = pages
        vol.is_corrupt = corrupt
            
    for sg in series.sub_groups:
        for vol in sg.volumes:
            pages, corrupt = inspect_archive(vol.path, check_integrity=verify)
            if deep:
                vol.page_count = pages
            vol.is_corrupt = corrupt
            
    return series
