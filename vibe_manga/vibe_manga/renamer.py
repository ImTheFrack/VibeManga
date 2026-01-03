import shutil
import logging
import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set

from .models import Series, Library
from .analysis import sanitize_filename, calculate_rename_safety, classify_unit

logger = logging.getLogger(__name__)

WHITELIST_FILE = "vibe_manga_whitelist.json"

def load_whitelist() -> Set[str]:
    """Loads the set of whitelisted series names."""
    if not os.path.exists(WHITELIST_FILE):
        return set()
    try:
        with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data)
    except Exception as e:
        logger.error(f"Failed to load whitelist: {e}")
        return set()

def save_whitelist(whitelist: Set[str]) -> None:
    """Saves the set of whitelisted series names."""
    try:
        with open(WHITELIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(whitelist), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save whitelist: {e}")

def add_to_whitelist(series_name: str) -> None:
    """Adds a single series to the whitelist."""
    wl = load_whitelist()
    wl.add(series_name)
    save_whitelist(wl)

@dataclass
class FileRenameOp:
    original_path: Path
    new_rel_path: str  # Relative to the NEW series root
    
    def get_target_path(self, series_root: Path) -> Path:
        return series_root / self.new_rel_path

@dataclass
class SeriesRenameOp:
    series: Series
    current_name: str
    target_name: str
    current_path: Path
    target_path: Path
    safety_level: int = 3  # Default to aggressive/unsafe
    file_ops: List[FileRenameOp] = field(default_factory=list)

def get_target_name(series: Series, prefer_english: bool, prefer_japanese: bool) -> str:
    """Determines the target name based on metadata and preferences."""
    meta = series.metadata
    
    if prefer_english and meta.title_english:
        return sanitize_filename(meta.title_english)
    if prefer_japanese and meta.title_japanese:
        return sanitize_filename(meta.title_japanese)
    
    # Default to main title (which comes from Jikan 'title' or 'title_english' usually)
    if meta.title and meta.title != "Unknown":
        return sanitize_filename(meta.title)
        
    return sanitize_filename(series.name)

def generate_rename_op_for_series(
    series: Series, 
    whitelist: Set[str], 
    prefer_english: bool = False, 
    prefer_japanese: bool = False
) -> Optional[SeriesRenameOp]:
    """Generates a rename operation for a single series, including reorganization."""
    # Check Whitelist
    if series.name in whitelist:
        return None

    # 1. Determine Target Series Name
    target_name = get_target_name(series, prefer_english, prefer_japanese)
    
    # Check if folder name needs changing
    current_name = series.path.name
    folder_needs_rename = current_name != target_name
    
    # 2. Collect and Analyze all valid comic files
    file_ops = []
    all_files_data = []
    all_v_nums = set()
    all_c_nums = set()
    all_u_nums = set()
    
    for root, _, files in os.walk(series.path):
        for f in files:
            path = Path(root) / f
            # Ignore metadata and system files
            lower_name = f.lower()
            if lower_name in ["series.json", "thumbs.db", ".ds_store", "desktop.ini"]:
                continue

            # Check extension - STRICT ALLOWLIST
            ext = path.suffix.lower()
            if ext not in ['.cbz', '.cbr', '.zip', '.rar']:
                continue

            v, c, u = classify_unit(f)
            all_files_data.append((path, v, c, u))
            all_v_nums.update(v)
            all_c_nums.update(c)
            all_u_nums.update(u)
    
    if not all_files_data and not folder_needs_rename:
        return None

    # 3. Determine Reorganization Requirements
    has_volumes = bool(all_v_nums)
    has_chapters = bool(all_c_nums or all_u_nums)
    use_subfolders = has_volumes and has_chapters
    
    vol_folder = ""
    chap_folder = ""
    
    if use_subfolders:
        min_v = min(all_v_nums)
        max_v = max(all_v_nums)
        def fmt_num(n): return str(int(n)).zfill(2) if n.is_integer() else str(n).zfill(2)
        
        vol_folder = f"{target_name} v{fmt_num(min_v)}-v{fmt_num(max_v)}"
        if min_v == max_v: vol_folder = f"{target_name} v{fmt_num(min_v)}"
        
        chap_start = int(max_v) + 1
        chap_folder = f"{target_name} v{str(chap_start).zfill(2)}+"

    # 4. Generate File Ops
    import re
    prefixes_to_check = [
        sanitize_filename(current_name), 
        current_name,
        sanitize_filename(series.name),
        series.name,
        target_name,
    ]
    prefixes_to_check.sort(key=len, reverse=True)

    for path, v, c, u in all_files_data:
        ext = path.suffix.lower()
        new_ext = ext
        if ext == '.zip': new_ext = '.cbz'
        elif ext == '.rar': new_ext = '.cbr'
        
        fname = path.stem
        clean_fname = fname
        
        for prefix in prefixes_to_check:
            if fname.lower().startswith(prefix.lower()):
                clean_fname = fname[len(prefix):].strip()
                break
        
        # Reconstruct
        if clean_fname:
            new_fname_stem = f"{target_name} {clean_fname}"
        else:
            new_fname_stem = target_name
            
        new_fname_stem = re.sub(r'\s+', ' ', new_fname_stem).strip()
        new_filename = f"{new_fname_stem}{new_ext}"
        
        # Determine target subfolder
        target_sub = ""
        if use_subfolders:
            if v: target_sub = vol_folder
            elif c or u: target_sub = chap_folder
        
        new_rel_path = Path(target_sub) / new_filename
        
        # Check if changed (path or name)
        try:
            current_rel = path.relative_to(series.path)
            if str(current_rel) != str(new_rel_path):
                file_ops.append(FileRenameOp(path, str(new_rel_path)))
        except ValueError:
            continue

    # 5. Return Op if work is needed
    if folder_needs_rename or file_ops:
        safety = calculate_rename_safety(current_name, target_name)
        
        return SeriesRenameOp(
            series=series,
            current_name=current_name,
            target_name=target_name,
            current_path=series.path,
            target_path=series.path.parent / target_name,
            safety_level=safety,
            file_ops=file_ops
        )
    return None

def generate_rename_plan(
    library: Library, 
    query: Optional[str] = None,
    prefer_english: bool = False, 
    prefer_japanese: bool = False
) -> List[SeriesRenameOp]:
    """
    Iterates the library and generates a list of rename operations.
    Skips series with no metadata (unless they just need sanitization).
    """
    plan = []
    whitelist = load_whitelist()
    
    # Flatten series list
    all_series = []
    for cat in library.categories:
        for sub in cat.sub_categories:
            all_series.extend(sub.series)
        all_series.extend(cat.series)
        
    for series in all_series:
        if query and query.lower() not in series.name.lower():
            continue
            
        op = generate_rename_op_for_series(series, whitelist, prefer_english, prefer_japanese)
        if op:
            plan.append(op)
            
    return plan

def execute_rename_op(op: SeriesRenameOp) -> List[str]:
    """
    Executes a single rename operation.
    Returns a list of messages/errors.
    Handles case-insensitive filesystems (Windows) by using temp files if needed.
    """
    msgs = []
    import time
    
    # 1. Rename Folder (if needed)
    final_series_path = op.current_path
    
    # FIX: Use string comparison because Path("A") == Path("a") is True on Windows
    if str(op.current_path) != str(op.target_path):
        # Check collision
        if op.target_path.exists():
            is_case_only = op.current_path.name.lower() == op.target_path.name.lower()
            if not is_case_only:
                return [f"ERROR: Target folder exists: {op.target_path}"]
            
        try:
            # Case-only rename check
            if op.current_path.name.lower() == op.target_path.name.lower():
                temp_path = op.current_path.with_name(f"{op.current_path.name}_TEMP_{os.getpid()}")
                op.current_path.rename(temp_path)
                temp_path.rename(op.target_path)
            else:
                op.current_path.rename(op.target_path)

            final_series_path = op.target_path
            op.series.path = final_series_path
            op.series.name = op.target_name
            msgs.append(f"Renamed folder to: {op.target_name}")
            
            time.sleep(0.05)

        except OSError as e:
            return [f"ERROR moving folder: {e}"]

    # 2. Rename Files
    for f_op in op.file_ops:
        try:
            # Re-base the path
            try:
                rel_path = f_op.original_path.relative_to(op.current_path)
            except ValueError:
                msgs.append(f"ERROR: Could not relate {f_op.original_path} to {op.current_path}")
                continue
            
            current_file_path = final_series_path / rel_path
            target_file_path = f_op.get_target_path(final_series_path)
            
            if str(current_file_path) == str(target_file_path):
                continue

            if not current_file_path.exists():
                logger.warning(f"Source file not found at expected path, skipping: {current_file_path}")
                continue

            # Ensure parent directory exists for renames that move files into subfolders
            if not target_file_path.parent.exists():
                target_file_path.parent.mkdir(parents=True, exist_ok=True)

            if target_file_path.exists():
                is_same_file = False
                try:
                    is_same_file = current_file_path.samefile(target_file_path)
                except OSError:
                    pass 
                
                if is_same_file:
                     # It's the same file node, just accessed via different name (e.g. Case)
                     temp_file = current_file_path.with_name(f"{current_file_path.name}_{os.getpid()}.tmp")
                     current_file_path.rename(temp_file)
                     temp_file.rename(target_file_path)
                else:
                    msgs.append(f"Skipped file {rel_path.name}: Target exists")
                    continue
            else:
                current_file_path.rename(target_file_path)
                
        except Exception as e:
            msgs.append(f"ERROR renaming file {f_op.original_path.name}: {e}")
            
    return msgs
