import re
import json
import html
import os
import time
import difflib
import logging
import concurrent.futures
import multiprocessing
from typing import List, Dict, Any, Tuple, Optional, Set
from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.live import Live
from rich.text import Text
from rich.panel import Panel
from rich.columns import Columns
from rich.align import Align
from . import constants as c
from .logging import get_logger, log_step, log_substep
from .scanner import scan_library
from .models import Series, Library
from .indexer import LibraryIndex
from .metadata import fetch_from_jikan, save_local_metadata
from .analysis import (
    find_gaps, 
    find_duplicates, 
    find_structural_duplicates, 
    find_external_updates, 
    format_ranges, 
    
    semantic_normalize,
    classify_unit,
    parse_size
)
from .cache import get_cached_library, save_library_cache, load_resolution_cache, save_resolution_cache

logger = get_logger(__name__) 
console = Console()

# --- CONSTANTS & PATTERNS ---
MIN_VOL_SIZE = c.MIN_VOL_SIZE_MB * c.BYTES_PER_MB
MIN_CHAP_SIZE = c.MIN_CHAP_SIZE_MB * c.BYTES_PER_MB

# Skip Patterns (Regex)
SKIP_INDICATORS = {
    "Light Novel": [r"\blight\s*novels?\b", r"\blns?\b", r"j-novel", r"web\s*novel", r"som\s*kanzenban\s*english"],
    "Visual Novel": [r"\bvisual\s*novels?\b", r"\bvns?\b"],
    "Audiobook": [r"audiobook"],
    "Periodical": [
        r"\bweekly\b.*weeks?\b", 
        r"alpha\s*manga",
        r"manga\s*up!", 
        r"\bweekly\b.*updates",
        r"\bweekly\b.*20\d{2}"
    ], 
    "Unknown": [r"\bc2c\b"],
    "Anthology": [r"archives\s*[a-z]-[a-z]"] # e.g. Archives U-Z
}

# Tags: [...] or (...) or {...}
TAG_PATTERN = r"(\[.*?\]|\(.*?\)|{.*?})"

# Strings to strip from Name
NAME_STRIP_PATTERNS = [
    r"\s*-\s*The\s*Official\s*Comic\s*Anthology\s*-?",
    r"\s*-\s*Official\s*Comic\s*Anthology\s*-?",
    r"\s*-\s*Comic\s*Anthology",
    r"\s*Comic\s*Anthology", 
    r"\s*-\s*The\s*Complete\s*Manga\s*Collection",
    r"\s*-\s*Complete\s*Edition",
    r"\s*-\s*New\s*Edition",
    r"\s*-\s*Special\s*Issue",
    r"\s*-\s*Remastered",
    r"\s*-manuscriptus",
    r"\s*English\b",
    # Specific Edition Stripping (Parens/Brackets/Braces with "Edition")
    r"[\\\\[\(\{].*?Edition[\\\\]\}\]",
    # Generic Trailing Edition (e.g. "- Brilliant Full Color Edition")
    r"\s*-\s*.*?Edition\s*$"
]

# "X as vY + Z" or "X as vY"
AS_PATTERN = r"([\d\.x]+(?:[-\.][\d\.x]+)?)\s+as\s+v?(\d+(?:[-\.]\d+)?)(?:\s*\+\s*(\d+(?:\.\d+)?(?:[-\s]\d+(?:\.\d+)?)?))?"

# Messy Volume Pattern
MESSY_VOL_PATTERN = r"\b(?:v|vol)[0-9][0-9v._-]*\b"

# Explicit Volume
# Added 'parts' (plural) for JoJo support
# Allow whitespace around separator (e.g. "Volumes 1 - 14")
VOL_PATTERN = r"\b(?:v|vol(?:ume)?|parts)\.?\s*(\d+(?:\s*[-\.]\s*\d+)?)\b"

# Explicit Chapter
PREFIXED_CHAPTER_PATTERN = r"\b(?:ch|c|chapter|ep(?:isode)?)\.?\s*(\d+(?:[-\.]\d+)?)(?:\s*(?:-|to)\s*(?:ch|c|chapter|ep(?:isode)?)\.?\s*(\d+(?:[-\.]\d+)?))?"

# Naked Chapter
NAKED_CHAPTER_PATTERN = r"\b#?(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?\s*$"

# Heuristic for detecting "English Name Native Name"
DUAL_LANG_PATTERN = r"^([ -~]{3,})\s+([^\x00-\x7F]+.*)$"

# Articles to move to end of title
ARTICLE_PATTERN = r"^(The|A|An|Le|La|Les|Un|Une)\s+(.*)$"
L_APOSTROPHE_PATTERN = r"^(L')(.+)$"

def _parse_range(start: str, end: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    if not start:
        return None, None
    s = start.replace("#", "")
    if end:
        e = end.replace("#", "")
        return s, e
    if "-" in s:
        parts = re.split(r"\s*-\s*", s)
        if len(parts) >= 2:
            return parts[0], parts[1]
    return s, s

def _get_count(start: Optional[str], end: Optional[str]) -> int:
    """Helper to get count of items in a range string."""
    if not start:
        return 0
    try:
        s = float(start)
        e = float(end) if end else s
        if s.is_integer() and e.is_integer():
            return int(abs(e - s)) + 1
        return 1
    except (ValueError, TypeError):
        return 1

def match_single_entry(entry: Dict[str, Any], library_index: Optional[LibraryIndex], existing_match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Worker function to process a single entry.
    library_index is a LibraryIndex object containing mappings for ID and Titles.
    """
    parsed = parse_entry(entry)
    
    # Restore existing match data if available
    if existing_match:
        if "grab_status" in existing_match:
            parsed["grab_status"] = existing_match["grab_status"]
            
        if existing_match.get("matched_name"):
            parsed["matched_name"] = existing_match["matched_name"]
            parsed["matched_path"] = existing_match.get("matched_path")
            parsed["matched_id"] = existing_match.get("matched_id")
            return parsed

    is_manga = parsed.get("type") == "Manga"
    if not is_manga or not library_index:
        return parsed

    # Matching Logic
    best_series: Optional[Series] = None
    
    # Strategy 1: Direct ID Match (if entry has a known ID)
    # NOTE: Scrapers might not provide this yet, but we support it for future-proofing.
    if parsed.get("mal_id"):
        best_series = library_index.get_by_id(parsed["mal_id"])
        if best_series:
            logger.debug(f"Direct ID match for {parsed['mal_id']}: {best_series.name}")

    # Strategy 2: Synonym/Title Match via Index
    if not best_series:
        for name in parsed.get("parsed_name", []):
            matches = library_index.search(name)
            if matches:
                # If multiple exact title matches, take the first one (ambiguity is rare for full titles)
                best_series = matches[0]
                break
    
    # Strategy 3: Fuzzy Match (Fallback)
    if not best_series:
        # We need to fuzzy match against ALL identities in the index
        # Since LibraryIndex.title_map keys are normalized titles, we can iterate those.
        
        best_ratio = 0.0
        
        for name in parsed.get("parsed_name", []):
            norm_name = semantic_normalize(name)
            if not norm_name: continue
            
            for indexed_norm_title, series_list in library_index.title_map.items():
                ratio = difflib.SequenceMatcher(None, norm_name, indexed_norm_title).ratio() * 100
                
                if ratio > best_ratio:
                    # Enforce number consistency for high-confidence fuzzy matches
                    if ratio >= c.FUZZY_MATCH_THRESHOLD:
                        # Extract numbers from the ALREADY normalized strings
                        nums_a = re.findall(r'\d+', norm_name)
                        nums_b = re.findall(r'\d+', indexed_norm_title)
                        if nums_a != nums_b:
                            continue

                    best_ratio = ratio
                    if ratio >= c.FUZZY_MATCH_THRESHOLD:
                        best_series = series_list[0] # Pick first if multiple
                        
        # If best_ratio was updated but below threshold, best_series remains None

    if best_series:
        parsed["matched_name"] = best_series.name
        parsed["matched_path"] = str(best_series.path)
        # We don't set matched_id here yet (it's set in post-processing usually to path or MAL ID)
        # But let's set it to MAL ID if available, else relative path?
        # The integration logic in process_match usually handles the ID format.
        # We'll just pass the series name for now to fit existing flow.
        
    return parsed

def parse_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw_title = entry.get("name", "")
    title = html.unescape(raw_title)
    size_str = entry.get("size", "0 B")
    
    parsed_names = []
    item_type = "Manga"
    vol_start = None
    vol_end = None
    chap_start = None
    chap_end = None
    notes = []
    
    # 1. Check Skips
    title_lower = title.lower()
    for type_key, patterns in SKIP_INDICATORS.items():
        for pat in patterns:
            if re.search(pat, title_lower):
                item_type = type_key
                if type_key in ["Light Novel", "Periodical", "Unknown", "Audiobook", "Visual Novel", "Anthology"]:
                    parsed_names = [f"SKIPPED: {title}"]
                    entry.update({
                        "parsed_name": parsed_names,
                        "type": item_type,
                        "volume_begin": None, "volume_end": None,
                        "chapter_begin": None, "chapter_end": None, "notes": notes
                    })
                    return entry

    # 1.5 Pre-Cleanup: Handle specific edge cases like (Void) | Completed
    clean_title = title

    # Strip archive extensions (for single-file torrents)
    clean_title = re.sub(r"\.(cbz|cbr|zip|rar|7z|epub|pdf)$", "", clean_title, flags=re.IGNORECASE)

    if "(Void)" in title:
        clean_title = re.sub(r"\(Void\).*?\|.*$", "", clean_title, flags=re.IGNORECASE)

    # 2. Extract Tags
    found_tags = re.findall(TAG_PATTERN, title)
    # clean_title already init above, but we update it here
    tag_content_list = []

    for tag in found_tags:
        content = tag[1:-1].strip()
        # Rescue Chapters/Volumes in parens (e.g. (Chapters 210-220))
        # Unwrap them so they can be parsed by main logic
        if re.match(r"^(?:ch|c|chapter|vol|v|parts)\.?\s*\d", content, re.IGNORECASE):
            clean_title = clean_title.replace(tag, f" {content} ")
            continue

        tag_lower = tag.lower()
        if "j-novel" in tag_lower:
            item_type = "Light Novel"
            parsed_names = [f"SKIPPED: {title}"]
            entry.update({
                "parsed_name": parsed_names,
                "type": item_type,
                "volume_begin": None, "volume_end": None,
                "chapter_begin": None, "chapter_end": None, "notes": notes
            })
            return entry
        tag_content_list.append(content)
        notes.append(tag)
        clean_title = clean_title.replace(tag, " ")

    # 3. Strip Name Patterns
    for pat in sorted(NAME_STRIP_PATTERNS, key=len, reverse=True):
        clean_title = re.sub(pat, " ", clean_title, flags=re.IGNORECASE)

    # 3b. Mask Protections
    part_mask_map = {}
    
    # Mask time-like patterns (e.g. 23:45 or 23꞉45) to prevent them from being parsed as chapters
    time_matches = list(re.finditer(r"\b\d+[:꞉]\d+\b", clean_title))
    for i, tm in enumerate(time_matches):
        placeholder = f"__TIME_{i}__"
        part_mask_map[placeholder] = tm.group(0)
        clean_title = clean_title.replace(tm.group(0), placeholder)

    part_matches = list(re.finditer(r"\bPart\s+(\d+)", clean_title, re.IGNORECASE))
    for i, pm in enumerate(part_matches):
        placeholder = f"__PART_{i}__"
        part_mask_map[placeholder] = pm.group(0)
        clean_title = clean_title.replace(pm.group(0), placeholder)

    kaiju_match = re.search(r"\bNo[\.\s]*8\b", clean_title, re.IGNORECASE)
    kaiju_placeholder = None
    if kaiju_match:
        kaiju_placeholder = "__KAIJU_8__"
        clean_title = clean_title.replace(kaiju_match.group(0), kaiju_placeholder)

    clean_title = re.sub(r"\+Epilogue", "", clean_title, flags=re.IGNORECASE)

    # EDGE CASE: Vinland Saga - Chapters 210-220 V2
    # If we have "Chapter <range> V<num>", strip the V<num> as it is likely a version
    # matching strictly "V" or "v" followed by digits at word boundary
    clean_title = re.sub(r"(?i)(\bChapters?\s+[\d\-\.]+\s+)(v\d+)\b", r"\1", clean_title)

    # 4. Parsing Logic
    
    # --- PROTECTION: Identify earliest prefix to protect preceding title numbers ---
    # We check all possible prefix patterns to find the very first one.
    # Numbers occurring before this index are likely part of the title (e.g. "Persona 5 v01")
    prefix_found = False
    earliest_prefix_idx = len(clean_title)
    
    as_m = re.search(AS_PATTERN, clean_title, re.IGNORECASE)
    if as_m: 
        earliest_prefix_idx = min(earliest_prefix_idx, as_m.start())
        prefix_found = True
    
    messy_m = re.search(MESSY_VOL_PATTERN, clean_title, re.IGNORECASE)
    if messy_m: 
        earliest_prefix_idx = min(earliest_prefix_idx, messy_m.start())
        prefix_found = True
    
    for vm in re.finditer(VOL_PATTERN, clean_title, re.IGNORECASE):
        earliest_prefix_idx = min(earliest_prefix_idx, vm.start())
        prefix_found = True
        
    for cm in re.finditer(PREFIXED_CHAPTER_PATTERN, clean_title, re.IGNORECASE):
        earliest_prefix_idx = min(earliest_prefix_idx, cm.start())
        prefix_found = True

    # Case A: "as vXX + YY"
    as_match = re.search(AS_PATTERN, clean_title, re.IGNORECASE)
    if as_match:
        v_s, v_e = _parse_range(as_match.group(2))
        vol_start, vol_end = v_s, v_e
        if as_match.group(3):
            c_s, c_e = _parse_range(as_match.group(3))
            chap_start, chap_end = c_s, c_e
        clean_title = clean_title.replace(as_match.group(0), " ")
        
    else:
        # Case B: Standard
        
        # 3a. Messy Volume
        found_complex = False
        messy_match = re.search(MESSY_VOL_PATTERN, clean_title, re.IGNORECASE)
        if messy_match:
            token = messy_match.group(0)
            is_complex = "_" in token or token.lower().count("v") > 1
            if is_complex:
                found_complex = True
                parts = re.split(r"[vV_.-]", token)
                nums = []
                for p in parts:
                    if p.isdigit():
                        nums.append(int(p))
                if len(nums) >= 2 and nums[-2] < nums[-1]:
                    vol_start = str(nums[-2])
                    vol_end = str(nums[-1])
                    notes.append(f"Messy Volume: {token}")
                    clean_title = clean_title.replace(token, " ")

        # 3b. Standard Volume
        if not found_complex:
            vol_matches = list(re.finditer(VOL_PATTERN, clean_title, re.IGNORECASE))
            if vol_matches:
                min_v = float('inf')
                max_v = float('-inf')
                start_str = None
                end_str = None
                
                for vm in vol_matches:
                    v_s, v_e = _parse_range(vm.group(1))
                    
                    if v_s:
                        try:
                            # Parse numeric value for comparison
                            # Note: This might strip leading zeros or fail on non-standard formats
                            # but regex guarantees mostly digits.
                            # We treat v_s as the authoritative start for this match.
                            val_s = float(v_s)
                            if val_s < min_v:
                                min_v = val_s
                                start_str = v_s
                            
                            val_e = float(v_e) if v_e else val_s
                            if val_e > max_v:
                                max_v = val_e
                                end_str = v_e
                        except ValueError:
                            # Fallback if float conversion fails (rare)
                            pass
                    
                    clean_title = clean_title.replace(vm.group(0), " ")
                
                if start_str:
                    vol_start = start_str
                    vol_end = end_str

        # 3c. Prefixed Chapters
        chap_match = re.search(PREFIXED_CHAPTER_PATTERN, clean_title, re.IGNORECASE)
        if chap_match:
            if chap_match.group(2):
                c_s = chap_match.group(1)
                c_e = chap_match.group(2)
                chap_start, chap_end = c_s, c_e
            else:
                c_s, c_e = _parse_range(chap_match.group(1))
                chap_start, chap_end = c_s, c_e
            clean_title = clean_title.replace(chap_match.group(0), " ")
        else:
            # 3d. Naked Chapters (Recursive Logic)
            first_naked = True
            while True:
                clean_title = clean_title.strip()
                clean_title = re.sub(r"[\+\,\&]+$", "", clean_title).strip()
                
                naked_match = re.search(NAKED_CHAPTER_PATTERN, clean_title)
                if not naked_match:
                    break
                
                # PROTECTION: If this naked match is BEFORE the first prefixed volume/chapter,
                # it is likely part of the title (e.g. "Persona 5 v01") and should not be stripped.
                if prefix_found and naked_match.start() < earliest_prefix_idx:
                    break

                start_raw = naked_match.group(1)
                end_raw = naked_match.group(2)
                
                is_valid = True
                try:
                    if float(start_raw) > 1900: is_valid = False
                except ValueError: pass
                if is_valid and end_raw:
                    try:
                        if float(start_raw) > float(end_raw): is_valid = False
                    except ValueError: pass
                
                if not is_valid:
                    break 
                
                if first_naked:
                    chap_start = start_raw
                    chap_end = end_raw if end_raw else start_raw
                    first_naked = False
                else:
                    extra = start_raw
                    if end_raw: extra += f"-{end_raw}"
                    notes.append(f"Extra Chapter: {extra}")
                
                clean_title = re.sub(NAKED_CHAPTER_PATTERN, "", clean_title)

    # 5. Restore Masks
    if kaiju_placeholder:
        clean_title = clean_title.replace(kaiju_placeholder, "No. 8")
    for ph, orig in part_mask_map.items():
        clean_title = clean_title.replace(ph, orig)

    # 6. Cleanup Name
    clean_title = clean_title.strip()
    clean_title = re.sub(r"[\+\,\&\-]+", "", clean_title).strip()
    
    # 6b. Replace '&' with 'to'
    # Only apply when '&' is attached to the end of a word as a suffix (e.g. "Yotsuba&!" -> "Yotsubato!")
    # We avoid replacing standalone " & " or infix "A&B" as those are usually just separators.
    clean_title = re.sub(r"(?<=\w)&(?!\w|\s)", "to", clean_title, flags=re.IGNORECASE)
    
    clean_title = re.sub(r"\s+", " ", clean_title)
    
    # 7. Handle Multiple Names
    if "|" in clean_title or "｜" in clean_title:
        # Support both standard and full-width pipes as delimiters
        s_char = "|" if "|" in clean_title else "｜"
        parts = [p.strip() for p in clean_title.split(s_char)]
        parsed_names = [p for p in parts if p]
        
        # Keep the original full title as well to match combined library entries
        # (e.g. if library has "JP | EN" as a single folder name)
        if clean_title not in parsed_names:
            parsed_names.append(clean_title)
    else:
        dual_match = re.match(DUAL_LANG_PATTERN, clean_title)
        if dual_match:
            parsed_names = [dual_match.group(1), dual_match.group(2)]
            # Also keep full title for dual-lang heuristic
            if clean_title not in parsed_names:
                parsed_names.append(clean_title)
        elif clean_title and clean_title != "SKIPPED":
            parsed_names = [clean_title]
        else:
            if tag_content_list:
                parsed_names = [tag_content_list[0]]
            else:
                parsed_names = ["UNKNOWN_NAME"]
    
    # 7b. Move Articles to End (e.g. "The Name" -> "Name, The")
    # Applied to each parsed name individually
    final_names = []
    for name in parsed_names:
        if name.startswith("SKIPPED:"):
            final_names.append(name)
            continue
            
        # Check standard articles
        art_match = re.match(ARTICLE_PATTERN, name, re.IGNORECASE)
        if art_match:
            # Group 1: Article, Group 2: Rest
            # Preserve original casing from the match
            name = f"{art_match.group(2)}, {art_match.group(1)}"
        else:
            # Check L'
            l_match = re.match(L_APOSTROPHE_PATTERN, name, re.IGNORECASE)
            if l_match:
                name = f"{l_match.group(2)}, {l_match.group(1)}"
        
        final_names.append(name)
    parsed_names = final_names

    # Filter out generic status words that might have leaked through
    parsed_names = [
        n for n in parsed_names 
        if n.lower() not in ["completed", "ongoing", "finished"]
    ]
    
    # --- RULE: Size Check for Manga ---
    if item_type == "Manga":
        size_bytes = parse_size(size_str)
        vol_count = _get_count(vol_start, vol_end)
        chap_count = _get_count(chap_start, chap_end)
        
        expected_min = 0
        if vol_count > 0:
            expected_min = vol_count * MIN_VOL_SIZE
        elif chap_count > 0:
            expected_min = chap_count * MIN_CHAP_SIZE
        else:
            expected_min = MIN_VOL_SIZE
        
        if expected_min > 0 and size_bytes > 0:
            if size_bytes < expected_min:
                item_type = "UNDERSIZED"
                parsed_names = [f"SKIPPED: {size_str}: {title}"]

    entry.update({
        "parsed_name": parsed_names,
        "type": item_type,
        "volume_begin": vol_start,
        "volume_end": vol_end,
        "chapter_begin": chap_start,
        "chapter_end": chap_end,
        "notes": notes
    })
    return entry

def consolidate_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Union-Find initialization
    parent = list(range(len(entries)))
    def find(i):
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    name_map = {}
    
    # 1. Build relationships (Ignore punctuation and case)
    for i, entry in enumerate(entries):
        names = entry.get("parsed_name", [])
        if not names: continue
        for name in names:
            name_key = semantic_normalize(name)
            if not name_key: continue
            
            if name_key in name_map:
                union(i, name_map[name_key])
            else:
                name_map[name_key] = i

    # 2. Group by root
    groups = {}
    for i, entry in enumerate(entries):
        root = find(i)
        if root not in groups:
            groups[root] = {
                "parsed_names": set(),
                "type": entry.get("type"),
                "vol_ranges": [],
                "chap_ranges": [],
                "count": 0,
                "matched_names": set(), # Store all unique matches
                "matched_ids": set()
            }
        
        group = groups[root]
        for n in entry.get("parsed_name", []):
            group["parsed_names"].add(n)
            
        if group["type"] != "Manga" and entry.get("type") == "Manga":
            group["type"] = "Manga"
            
        if entry.get("volume_begin"):
            v_s = entry["volume_begin"]
            v_e = entry.get("volume_end", v_s)
            group["vol_ranges"].append((v_s, v_e))
            
        if entry.get("chapter_begin"):
            c_s = entry["chapter_begin"]
            c_e = entry.get("chapter_end", c_s)
            group["chap_ranges"].append((c_s, c_e))
            
        group["count"] += 1

        # Collect matches
        if entry.get("matched_name"):
             group["matched_names"].add(entry.get("matched_name"))
        if entry.get("matched_id"):
             group["matched_ids"].add(entry.get("matched_id"))

    # 3. Format output
    result = []
    for data in groups.values():
        sorted_names = sorted(list(data["parsed_names"]))
        
        # Determine consolidated match status
        final_match_name = None
        matches = list(data["matched_names"])
        if len(matches) == 1:
            final_match_name = matches[0]
        elif len(matches) > 1:
            final_match_name = f"MULTIPLE MATCHES: {', '.join(matches)}"
            
        final_match_id = None
        ids = list(data["matched_ids"])
        if len(ids) == 1:
            final_match_id = ids[0]
        elif len(ids) > 1:
            final_match_id = "MULTIPLE_IDS"
        
        def range_key(r):
            try:
                return float(re.findall(r"[\d.]+", str(r[0]))[0])
            except (ValueError, IndexError):
                return 0.0

        v_sorted = sorted(data["vol_ranges"], key=range_key)
        c_sorted = sorted(data["chap_ranges"], key=range_key)
        
        def fmt_ranges(ranges):
            res = []
            for s, e in ranges:
                if s == e: res.append(str(s))
                else: res.append(f"{s}-{e}")
            return res

        entry = {
            "parsed_name": sorted_names,
            "type": data["type"],
            "consolidated_volumes": fmt_ranges(v_sorted),
            "consolidated_chapters": fmt_ranges(c_sorted),
            "file_count": data["count"],
            "matched_name": final_match_name,
            "matched_id": final_match_id
        }
        result.append(entry)
        
    result.sort(key=lambda x: x["parsed_name"][0] if x["parsed_name"] else "")
    return result

def _propagate_matches(entries: List[Dict[str, Any]]) -> int:
    """
    Groups entries by parsed name and propagates match info within groups.
    Returns number of entries updated.
    """
    # Union-Find initialization
    parent = list(range(len(entries)))
    def find(i):
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    name_map = {}
    
    # 1. Build relationships (Ignore punctuation and case)
    for i, entry in enumerate(entries):
        names = entry.get("parsed_name", [])
        if not names: continue
        for name in names:
            name_key = semantic_normalize(name)
            if not name_key: continue
            
            if name_key in name_map:
                union(i, name_map[name_key])
            else:
                name_map[name_key] = i

    # 2. Gather Match Info per Group
    group_matches = {} # root_idx -> {match_data}
    
    for i, entry in enumerate(entries):
        root = find(i)
        if entry.get("matched_id"):
            if root not in group_matches:
                group_matches[root] = []
            # We store the whole match object to verify consistency
            match_info = {
                "id": entry.get("matched_id"),
                "name": entry.get("matched_name"),
                "path": entry.get("matched_path")
            }
            # Only add if unique to avoid duplicates in list
            if match_info not in group_matches[root]:
                group_matches[root].append(match_info)

    # 3. Propagate
    updated_count = 0
    for i, entry in enumerate(entries):
        # Skip if already matched
        if entry.get("matched_id"):
            continue
            
        root = find(i)
        if root in group_matches:
            matches = group_matches[root]
            # ONLY propagate if there is exactly one consistent match ID for the group
            # If multiple different IDs matched, it's ambiguous, so we do nothing.
            if len(matches) == 1:
                m = matches[0]
                entry["matched_id"] = m["id"]
                entry["matched_name"] = m["name"]
                entry["matched_path"] = m["path"]
                updated_count += 1
                
    return updated_count

def _resolve_remote_identities(data: List[Dict[str, Any]], library_index: LibraryIndex) -> int:
    """
    Attempts to resolve unmatched entries by querying Jikan (MAL) 
    and checking if the returned ID exists in the local library.
    
    Features:
    - Caches results (success and failure) to avoid repeated API calls.
    - Updates local series.json with the new synonym if a match is found.
    """
    if not library_index or not library_index.is_built:
        return 0

    # 1. Group unmatched entries by their Clean Name
    unmatched_groups = {} # name -> list of indices
    
    for i, entry in enumerate(data):
        # Skip if already matched
        if entry.get("matched_id") or entry.get("matched_path"):
            continue
            
        # Skip ignore types
        if entry.get("type") in ["Light Novel", "Visual Novel", "Audiobook", "Periodical", "Anthology", "UNDERSIZED"]:
            continue
            
        names = entry.get("parsed_name", [])
        if not names or any(n.startswith("SKIPPED") for n in names):
            continue
            
        # Use the first parsed name as the query candidate
        candidate = names[0]
        if not candidate: continue
        
        if candidate not in unmatched_groups:
            unmatched_groups[candidate] = []
        unmatched_groups[candidate].append(i)

    if not unmatched_groups:
        return 0

    # Load resolution cache
    res_cache = load_resolution_cache()
    
    # Identify what needs fetching vs what is cached
    to_fetch = []
    
    # Pre-process cache hits
    resolved_count = 0
    resolved_groups = 0
    cache_hits = 0
    
    # We'll collect updates to save at the end
    cache_updated = False
    
    for name, indices in unmatched_groups.items():
        if name in res_cache:
            mal_id = res_cache[name]
            if mal_id: # Cached Success
                 local_series = library_index.get_by_id(mal_id)
                 if local_series:
                    m_path = str(local_series.path)
                    m_name = local_series.name
                    for idx in indices:
                        data[idx]["matched_path"] = m_path
                        data[idx]["matched_name"] = m_name
                        data[idx]["matched_id"] = mal_id
                    resolved_count += len(indices)
                    resolved_groups += 1
                    cache_hits += 1
            else:
                # Cached Failure (None) - Skip
                pass
        else:
            to_fetch.append(name)

    if not to_fetch and cache_hits == 0:
        return 0

    if to_fetch:
        console.print(f"[cyan]Attempting remote resolution for {len(to_fetch)} unmatched groups...[/cyan]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Resolving identities...", total=len(to_fetch))
            
            for name in to_fetch:
                progress.update(task, description=f"Resolving: {name}")
                
                # Fetch from Jikan
                meta = fetch_from_jikan(name)
                
                if meta and meta.mal_id:
                    # Check if this ID exists in our library
                    local_series = library_index.get_by_id(meta.mal_id)
                    
                    if local_series:
                        # MATCH FOUND!
                        m_path = str(local_series.path)
                        m_name = local_series.name
                        
                        # 1. Link items
                        indices = unmatched_groups[name]
                        for idx in indices:
                            data[idx]["matched_path"] = m_path
                            data[idx]["matched_name"] = m_name
                            data[idx]["matched_id"] = meta.mal_id 
                        
                        resolved_count += len(indices)
                        resolved_groups += 1
                        
                        # 2. Update Cache
                        res_cache[name] = meta.mal_id
                        cache_updated = True
                        
                        # 3. LEARN: Update local series.json with this new synonym
                        # This prevents future lookups for this name completely!
                        if name not in local_series.identities:
                            # Verify it's not already in synonyms list (case-sensitive check)
                            if name not in local_series.metadata.synonyms:
                                logger.info(f"Learning new synonym '{name}' for series '{local_series.name}'")
                                local_series.metadata.synonyms.append(name)
                                save_local_metadata(local_series.path, local_series.metadata)
                                # Note: We don't rebuild index here, but next run will catch it locally.
                    else:
                        # Jikan found ID, but we don't have it.
                        # We cache this as "No Match" (None) because strictly speaking, 
                        # we can't link it to anything in our library.
                        # Wait... if we cache it as None, we'll never re-check even if we add the series later!
                        # Better to NOT cache if we just don't have the series?
                        # OR cache the ID, but since get_by_id returns None, it just behaves as "Not in Library".
                        # Storing the ID is better info.
                        res_cache[name] = meta.mal_id
                        cache_updated = True
                else:
                    # Jikan failed or returned no ID. Cache as None to prevent retry.
                    res_cache[name] = None
                    cache_updated = True
                
                progress.advance(task)
                
    if cache_updated:
        save_resolution_cache(res_cache)

    if resolved_count > 0:
        msg = f"Remote Resolution: Matched {resolved_groups} groups ({resolved_count} entries) to library."
        if cache_hits > 0:
            msg += f" (Cached: {cache_hits})"
        log_substep(msg)
    elif cache_hits > 0:
        logger.info(f"Remote Resolution: No new matches (Cached hits: {cache_hits})")
    else:
        logger.info("Remote Resolution: No new matches found.")
            
    return resolved_count

def process_match(input_file: str, output_file: str, show_table: bool, show_all: bool, library: Optional[Library] = None, show_stats: bool = False, query: Optional[str] = None, parallel: bool = True):
    start_time = time.time()
    p = Path(input_file)
    if not p.exists():
        logger.error(f"Input file {input_file} not found.")
        return

    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Error reading {input_file}: {e}")
        return

    # NEW: Build Library Index for Matching
    # This replaces the old list of tuples
    index = LibraryIndex()
    
    # Map to track Series by path for quick updates (needed for final integration)
    series_by_path: Dict[str, Series] = {}
    matched_library_paths: Set[str] = set()
    total_library_series = 0

    if library:
        try:
             # Flatten and filter first if needed, BUT
             # LibraryIndex handles searching, so we can just index everything
             # unless we want to strictly limit the index to a query?
             # If 'query' argument is passed, it means we only want to match AGAINST the query series.
             # So we should filter the library before building the index.
             
             # Flatten library for filtering/tracking
             all_series = []
             for cat in library.categories:
                 for sub in cat.sub_categories:
                     for s in sub.series:
                         all_series.append(s)
                         series_by_path[str(s.path)] = s
             
             # Filter if query provided
             filtered_library = library # Use full library by default
             if query:
                 q_lower = query.lower()
                 filtered_series = [s for s in all_series if q_lower in s.name.lower()]
                 
                 if not filtered_series:
                     logger.warning(f"No series found in library matching '{query}'.")
                     return
                 
                 if len(filtered_series) > 1:
                     names = ", ".join([s.name for s in filtered_series[:5]])
                     if len(filtered_series) > 5: names += "..."
                     logger.warning(f"Multiple matches for '{query}': {names}. Matching against all {len(filtered_series)}.")
                 else:
                     logger.info(f"Targeting series: {filtered_series[0].name}")
                 
                 # Create a temporary library subset for the index
                 # This is a bit hacky but effective to limit scope
                 # We'll just build the index manually from the filtered list?
                 # LibraryIndex expects a Library object usually.
                 # Let's just monkey-patch the build process or manually populate it.
                 # For simplicity, we just use the index manually.
                 
                 index.is_built = True
                 for s in filtered_series:
                     index._index_series(s)
                 
                 total_library_series = len(filtered_series)
             else:
                 # Build full index
                 index.build(library)
                 total_library_series = library.total_series

        except Exception as e:
            logger.warning(f"Could not process library for matching: {e}")

    # PERSISTENCE: Load existing output file to preserve matches
    existing_map = {}
    if Path(output_file).exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                for item in old_data:
                    if "magnet_link" in item:
                        existing_map[item["magnet_link"]] = item
        except Exception as e:
            logger.warning(f"Could not load existing match data from {output_file}: {e}")

    processed_data = []

    # Progress Bar Setup
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    )
    status_text = Text("Preparing...", style="dim")
    display_group = Group(progress, status_text)

    # 1. Matching Logic (Parallel or Serial)
    with Live(display_group, console=console, refresh_per_second=10):
        task_id = progress.add_task("[bold green]Matching Content...", total=len(data))
        
        # Determine number of workers
        num_workers = multiprocessing.cpu_count() if parallel else 1
        if not parallel:
             logger.info("Running in serial mode (--no-parallel)")
        
        # NOTE: LibraryIndex might be large. Passing it to workers via pickle is okay for moderate libraries.
        # If library grows to 100k series, this might need shared memory or database.
        
        if parallel and len(data) > 20: # Only use parallel for non-trivial amounts
            logger.info(f"Parallel matching active (Workers: {num_workers})")
            
            # Optimize payload size for workers
            worker_index = index.to_lightweight()
            
            with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
                # Prepare tasks
                futures = []
                for entry in data:
                    magnet = entry.get("magnet_link")
                    existing = existing_map.get(magnet) if magnet else None
                    # Pass worker_index instead of full index
                    futures.append(executor.submit(match_single_entry, entry, worker_index, existing))
                
                # Process as completed to update progress bar
                for future in concurrent.futures.as_completed(futures):
                    parsed = future.result()
                    processed_data.append(parsed)
                    
                    # Update status
                    pnames = ", ".join(parsed.get('parsed_name', []))
                    if len(pnames) > 80: pnames = pnames[:77] + "..."
                    
                    if parsed.get("matched_name"):
                         status_text.plain = f"Matched: {pnames} -> {parsed['matched_name']}"
                    else:
                         status_text.plain = f"Processed: {pnames}"
                         
                    progress.advance(task_id)
        else:
            # Serial Mode
            for entry in data:
                magnet = entry.get("magnet_link")
                existing = existing_map.get(magnet) if magnet else None
                parsed = match_single_entry(entry, index, existing)
                processed_data.append(parsed)
                
                pnames = ", ".join(parsed.get('parsed_name', []))
                if len(pnames) > 80: pnames = pnames[:77] + "..."
                if parsed.get("matched_name"):
                     status_text.plain = f"Matched: {pnames} -> {parsed['matched_name']}"
                else:
                     status_text.plain = f"Processed: {pnames}"
                progress.advance(task_id)

    # 1.5 Remote Resolution (if library available)
    if library:
        _resolve_remote_identities(processed_data, index)

    # 2. Integration & ID Generation (Main Process Only)
    # After parallel matching, we need to update the real Library object and generate IDs
    for parsed in processed_data:
        mpath = parsed.get("matched_path")
        if not mpath or mpath not in series_by_path:
            continue
            
        matched_series = series_by_path[mpath]
        matched_library_paths.add(mpath)
        
        # Compute ID (Relative Path or MAL ID if preferred)
        # We stick to Relative Path or Name for internal ID to ensure folder consistency
        # unless we want to switch to MAL ID completely?
        # The refactor plan says "Identity Resolution: A Series is defined by its Unique ID (MAL ID)"
        # But for 'matched_id' in the JSON, it's used for deduplication.
        # Let's stick to existing logic (RelPath/Name) for now to avoid breaking Grabber.
        # But we could potentially use matched_series.metadata.mal_id if available?
        
        if library and library.path:
            try:
                rel = matched_series.path.relative_to(library.path)
                parsed["matched_id"] = str(rel).replace("\\", "/")
            except ValueError:
                parsed["matched_id"] = matched_series.name
        else:
            parsed["matched_id"] = matched_series.name

        # Update Series external_data
        if "nyaa_matches" not in matched_series.external_data:
            matched_series.external_data["nyaa_matches"] = []
        
        magnet = parsed.get("magnet_link")
        existing_magnets = {m.get("magnet_link") for m in matched_series.external_data["nyaa_matches"]}
        if magnet and magnet not in existing_magnets:
            matched_series.external_data["nyaa_matches"].append({
                "name": parsed.get("name"),
                "magnet_link": magnet,
                "size": parsed.get("size"),
                "date": parsed.get("date"),
                "seeders": parsed.get("seeders"),
                "leechers": parsed.get("leechers"),
                "completed": parsed.get("completed"),
                "type": parsed.get("type"),
                "volume_begin": parsed.get("volume_begin"),
                "volume_end": parsed.get("volume_end"),
                "chapter_begin": parsed.get("chapter_begin"),
                "chapter_end": parsed.get("chapter_end")
            })

    # Propagate matches to peers in the same group
    propagated = _propagate_matches(processed_data)
    if propagated > 0:
        log_substep(f"Propagated matches to {propagated} related entries.")

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, indent=2)
        logger.info(f"Successfully processed {len(processed_data)} entries. Saved to {output_file}")
        log_substep(f"Saved match results to {output_file}")
    except Exception as e:
        logger.error(f"Error writing to {output_file}: {e}")

    # Save the updated Library state
    if library:
        save_library_cache(library)
        log_substep("Integrated matches into library state.")

    # Prepare Data for Display (Always Consolidate)
    table_data = consolidate_entries(processed_data)

    if show_table:
        title = "Match Summary (Consolidated)"
        table = Table(title=title, show_lines=True)
        table.add_column("#", style="dim", justify="right", width=4)
        table.add_column("Type", style="bold white", width=12)
        table.add_column("Parsed Name(s)", style="green")
        
        table.add_column("Volumes", style="cyan", justify="left")
        table.add_column("Chapters", style="blue", justify="left")
        table.add_column("Files", style="yellow", justify="right")

        display_index = 1
        for entry in table_data:
            is_skipped = entry.get("type") in ["Light Novel", "Periodical", "Unknown", "Audiobook", "Visual Novel", "UNDERSIZED", "Anthology"]
            
            # Filter Logic
            if show_all:
                pass # Show everything
            else:
                if is_skipped: continue # Skip ignored types
                
                # If query is active, ONLY show matches
                if query and not entry.get("matched_name"):
                    continue

            style = "dim" if is_skipped else ""
            names = entry.get("parsed_name", [])
            name_display = "\n".join(names)
            
            # Show Match Info
            if entry.get("matched_name"):
                match_str = f"[bold green]MATCHED: {entry['matched_name']}[/bold green]"
                name_display = f"{match_str}\n{name_display}"

            if name_display.startswith("SKIPPED:") and len(name_display) > 60:
                name_display = name_display[:57] + "..."

            vol_display = "\n".join(entry.get("consolidated_volumes", []))
            chap_display = "\n".join(entry.get("consolidated_chapters", []))
            if len(vol_display) > 200: vol_display = vol_display[:197] + "..."
            if len(chap_display) > 200: chap_display = chap_display[:197] + "..."
            
            table.add_row(
                str(display_index),
                entry.get("type", "?"),
                name_display,
                vol_display,
                chap_display,
                str(entry.get("file_count", 1)),
                style=style
            )
            display_index += 1
        console.print(table)

    if show_stats:
        elapsed = time.time() - start_time
        
        # Stats Calculation
        total_scraped = len(processed_data)
        manga_entries = [e for e in processed_data if e.get("type") == "Manga"]
        
        # Count matched *scraped* items using consolidated data
        matched_scraped_count = sum(1 for e in table_data if e.get("matched_name") and e.get("type") == "Manga")
        total_manga_for_calc = sum(1 for e in table_data if e.get("type") == "Manga")

        match_rate = 0.0
        if total_manga_for_calc > 0:
            match_rate = (matched_scraped_count / total_manga_for_calc) * 100

        # Library Stats
        lib_matched_count = len(matched_library_paths)
        lib_coverage = 0.0
        if total_library_series > 0:
            lib_coverage = (lib_matched_count / total_library_series) * 100
        
        lib_unmatched_count = total_library_series - lib_matched_count

        # Display Panels
        console.print("")
        console.print(Panel(Align("[bold magenta]Matching Performance Summary[/bold magenta]", align="center"), style="magenta"))
        
        def make_stat(val, label, color="white"):
            return Panel(
                Align(f"[bold {color}]{val}[/bold {color}]\n[dim]{label}[/dim]", align="center"),
                expand=True
            )

        cards = [
            make_stat(f"{elapsed:.2f}s", "Duration", "cyan"),
            make_stat(f"{total_scraped}", "Scraped Items", "white"),
            make_stat(f"{total_manga_for_calc}", "Manga Groups", "blue"),
        ]
        console.print(Columns(cards))
        
        cards2 = [
            make_stat(f"{match_rate:.1f}%", f"Match Rate ({matched_scraped_count}/{total_manga_for_calc})", "green"),
            make_stat(f"{lib_coverage:.1f}%", f"Lib Coverage ({lib_matched_count}/{total_library_series})", "yellow"),
            make_stat(f"{lib_unmatched_count}", "Unmatched Series", "red"),
        ]
        console.print(Columns(cards2))
        console.print("")