import re
import logging
import difflib
import zipfile
from typing import List, Tuple, Dict, Set, Optional
from pathlib import Path

from .models import Series, Volume, SubGroup, Library
from .constants import (
    IMAGE_EXTENSIONS,
    SIMILARITY_THRESHOLD,
    MAX_RANGE_SIZE,
    YEAR_RANGE_MIN,
    YEAR_RANGE_MAX
)

logger = logging.getLogger(__name__)

try:
    import rarfile
except ImportError:
    rarfile = None
    logger.warning("rarfile library not available - .cbr files will be skipped")

# --- REGEX DEFINITIONS ---

# 1. Volume Patterns
# Matches: v01, Vol. 1, Volume 1, v01-05, v01-v05, Volume_01
VOL_REGEX = re.compile(r'''
    \b(?:v|vol\.?|volume)   # Prefix: v, vol, vol., or volume
    [\s\._\[]*              # Separator: Optional space, dot, underscore, or bracket
    (?:                     # START ALTERNATIVES
        # OPTION A: Range (e.g. v01-05 or v01-v05)
        (\d+(?:\.\d+)?)\s*[-~]\s*(?:v|vol\.?|volume)?    # Group 1: Start Number
        \s*
        (\d+(?:\.\d+)?)
    |                       # OR
        # OPTION B: Single Number (e.g. v01)
        (\d+(?:\.\d+)?)
    )                       # END ALTERNATIVES
''', re.IGNORECASE | re.VERBOSE)

# 2. Chapter Patterns
# Matches: c01, Ch. 1, Chapter 1, #1, c01-05, c01-c05, Ch_01
# NOTE: \x23 is the hex code for '#', used to avoid re.VERBOSE comment conflicts
CH_REGEX = re.compile(r'''
    \b(?:c|ch\.?|chapter|\x23) # Prefix: c, ch, ch., chapter, or #
    [\s\._\[]*              # Separator: Optional space, dot, underscore, or bracket
    (?:                     # START ALTERNATIVES
        # OPTION A: Range (e.g. c01-05 or c01-c05)
        (\d+(?:\.\d+)?)\s*[-~]\s*(?:c|ch\.?|chapter|\x23)?  # Group 1: Start Number
        \s*
        (\d+(?:\.\d+)?)
    |                       # OR
        # OPTION B: Single Number (e.g. c01)
        (\d+(?:\.\d+)?)
    )                       # END ALTERNATIVES
''', re.IGNORECASE | re.VERBOSE)

# 3. Fallback (Raw Numbers)
FALLBACK_NUMBER_REGEX = re.compile(r'\b(\d+(?:\.\d+)?)\b')

# 4. Implicit Ranges (001-099) - Used if no explicit prefixes found
IMPLICIT_RANGE_REGEX = re.compile(r'\b(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\b')

# Patterns to strip BEFORE parsing numbers
NOISE_PATTERNS = [
    re.compile(r'\(\s*(?:19|20)\d{2}\s*\)'),  # Years in parens: (2021)
    re.compile(r'\[\s*(?:19|20)\d{2}\s*\]'),  # Years in brackets: [2021]
    re.compile(r'\b(?:Season|S)\s*\d+', re.IGNORECASE), # Season 1, S01
    re.compile(r'\b(?:Part|Pt)\s*\d+', re.IGNORECASE),  # Part 1, Pt 1
    re.compile(r'\b(?:Year)\s*\d+', re.IGNORECASE),     # Year 1
    re.compile(r'\d+\s*[-]?\s*year\s*[-]?\s*old', re.IGNORECASE), # Age: 50-Year-Old, 10 year old
    re.compile(r'[\{\[\(]v\d+[\}\]\)]', re.IGNORECASE), # Versioning: {v2}, [v2], (v2)
    re.compile(r'\b(?:Bonus|Extra|Omake)\s*(?:Chapter|Ch|c|\x23)?\s*\d+', re.IGNORECASE), # Bonus Chapter 11
    re.compile(r'\d+%', re.IGNORECASE),                  # Percentages: 100%
    re.compile(r'\d+\s*[:꞉：]\s*\d+', re.IGNORECASE),    # Time-like patterns: 23:45, 10:00 (Standard, Modifier, Fullwidth)
]

def _parse_regex_matches(matches: List[Tuple]) -> List[float]:
    """
    Helper to convert regex matches (single or range) into a flat list of numbers.

    Args:
        matches: List of tuples from regex findall (range_start, range_end, single)

    Returns:
        Flat list of float numbers extracted from the matches
    """
    nums = []
    for m in matches:
        # m is a tuple: (Range Start, Range End, Single)
        range_start, range_end, single = m[0], m[1], m[2]

        if range_start and range_end:  # Range found (e.g., v01-05)
            try:
                s, e = float(range_start), float(range_end)
                if s.is_integer() and e.is_integer():
                    if s < e:
                        # Limit range size to avoid year disasters (1-2021)
                        if (e - s) < MAX_RANGE_SIZE:
                            nums.extend([float(x) for x in range(int(s), int(e) + 1)])
                    elif s == e:
                        # Handle cases like "v01-01" or "c004 - 4TH" (parsed as 4-4)
                        nums.append(s)
            except ValueError:
                pass
        elif single:  # Single number found (e.g., v01)
            nums.append(float(single))
    return nums

def classify_unit(name: str) -> Tuple[List[float], List[float], List[float]]:
    """
    Parses a filename to extract all Volume numbers, Chapter numbers, and Unknown numbers.
    Returns (vol_nums, ch_nums, unknown_nums).
    """
    clean_name = name
    for pattern in NOISE_PATTERNS:
        clean_name = pattern.sub(" ", clean_name)

    vol_nums = []
    ch_nums = []
    unknown_nums = []

    # 1. Find Volumes
    v_matches = VOL_REGEX.findall(clean_name)
    vol_nums.extend(_parse_regex_matches(v_matches))

    # 2. Find Chapters
    c_matches = CH_REGEX.findall(clean_name)
    ch_nums.extend(_parse_regex_matches(c_matches))

    # 3. If NO explicit volumes or chapters found, look for fallbacks
    if not vol_nums and not ch_nums:
        # Check Implicit Ranges (001-099)
        r_matches = IMPLICIT_RANGE_REGEX.findall(clean_name)
        # Format matches to match the expected tuple structure (start, end, None)
        formatted_r = [(m[0], m[1], None) for m in r_matches]
        unknown_nums.extend(_parse_regex_matches(formatted_r))

        # Check Single Numbers
        if not unknown_nums:
            matches = FALLBACK_NUMBER_REGEX.findall(clean_name)
            for m in matches:
                val = float(m)
                if YEAR_RANGE_MIN <= val <= YEAR_RANGE_MAX:
                    continue  # Skip years
                unknown_nums.append(val)

    return vol_nums, ch_nums, unknown_nums

def extract_number(name: str) -> float:
    """Wrapper to keep existing API working (returns first primary number found)."""
    v, c, u = classify_unit(name)
    if v: return v[0]
    if c: return c[0]
    if u: return u[0]
    return -1.0

def mask_volume_info(name: str) -> str:
    """Replaces number info with placeholders."""
    s = name.lower()
    s = re.sub(r'\bv\d+', '{VOL}', s)
    s = re.sub(r'\bc\d+', '{CH}', s)
    return s.strip()

def _check_sequence_gaps(numbers: List[float], unit_label: str) -> List[str]:
    if not numbers:
        return []
    
    # Treat floats (25.1) as integers (25)
    sorted_nums = sorted(list(set(int(n) for n in numbers)))
    if not sorted_nums:
        return []

    gaps = []
    start = sorted_nums[0]
    end = sorted_nums[-1]
    
    expected = set(range(start, end + 1))
    found_set = set(sorted_nums)
    missing = sorted(list(expected - found_set))
    
    if missing:
        ranges = []
        current_start = missing[0]
        current_end = missing[0]
        
        for i in range(1, len(missing)):
            if missing[i] == current_end + 1:
                current_end = missing[i]
            else:
                ranges.append((current_start, current_end))
                current_start = missing[i]
                current_end = missing[i]
        ranges.append((current_start, current_end))
        
        for s, e in ranges:
            if s == e:
                gaps.append(f"Missing {unit_label} #{s}")
            else:
                gaps.append(f"Missing {unit_label} #{s}-{e}")
    return gaps

def find_gaps(series: Series) -> List[str]:
    all_volumes = []
    all_volumes.extend(series.volumes)
    for sg in series.sub_groups:
        all_volumes.extend(sg.volumes)

    if not all_volumes:
        return ["No volumes found."]
    
    # One-shot check
    if len(all_volumes) == 1:
        v, c, u = classify_unit(all_volumes[0].name)
        if not v and not c and not u:
             return [] 

    vol_nums = []
    ch_nums = []
    unknown_nums = []

    for vol in all_volumes:
        v, c, u = classify_unit(vol.name)
        vol_nums.extend(v)
        ch_nums.extend(c)
        unknown_nums.extend(u)

    messages = []
    
    # Check Volumes first
    vol_gaps = _check_sequence_gaps(vol_nums, "Vol")
    
    # CRITICAL LOGIC: If we have volumes and there are NO gaps in the volumes,
    # assume the series is structurally complete. Ignore chapter gaps.
    # This handles cases like "Umi no Misaki v06 ch 44.5-52" where chapter parsing
    # might be messy but the Volume sequence (v01-v15) is perfect.
    if vol_nums and not vol_gaps:
        return []

    messages.extend(vol_gaps)
    messages.extend(_check_sequence_gaps(ch_nums, "Ch"))
    
    if not vol_nums and not ch_nums and unknown_nums:
        messages.extend(_check_sequence_gaps(unknown_nums, "Unit"))

    # If we found files but NO numbers, assume it's a collection of unnumbered
    # volumes/stories (e.g. Movies, Artbooks) and mark it as Complete.
    if not messages and not (vol_nums or ch_nums or unknown_nums):
         return []

    return messages

def _find_duplicates_in_list(
    volumes: List[Volume],
    context_name: str,
    fuzzy: bool = True
) -> List[str]:
    warnings = []
    
    num_map: Dict[float, List[Volume]] = {}
    
    for vol in volumes:
        v, c, u = classify_unit(vol.name)
        nums_to_check = []
        if v: nums_to_check.extend(v)
        elif c: nums_to_check.extend(c)
        elif u: nums_to_check.extend(u)
        
        for num in nums_to_check:
            if num not in num_map:
                num_map[num] = []
            if vol not in num_map[num]:
                num_map[num].append(vol)
            
    for num, vols in num_map.items():
        if len(vols) > 1:
            confirmed_dupes = set()
            for i in range(len(vols)):
                for j in range(i + 1, len(vols)):
                    v1 = vols[i]
                    v2 = vols[j]
                    if v1.name == v2.name: continue
                    m1 = mask_volume_info(v1.name)
                    m2 = mask_volume_info(v2.name)
                    ratio = difflib.SequenceMatcher(None, m1, m2).ratio()
                    if ratio > SIMILARITY_THRESHOLD:
                        confirmed_dupes.add(v1.name)
                        confirmed_dupes.add(v2.name)
            
            if confirmed_dupes:
                files_str = ", ".join([f"'{n}'" for n in sorted(list(confirmed_dupes))])
                warnings.append(f"[{context_name}] Duplicate Vol/Ch #{num}: {files_str}")

    if not fuzzy:
        return warnings

    for i in range(len(volumes)):
        for j in range(i + 1, len(volumes)):
            v1 = volumes[i]
            v2 = volumes[j]
            
            # Check overlap in detected numbers
            v1_v, v1_c, v1_u = classify_unit(v1.name)
            v2_v, v2_c, v2_u = classify_unit(v2.name)
            all1 = set(v1_v + v1_c + v1_u)
            all2 = set(v2_v + v2_c + v2_u)
            
            if all1 & all2: continue # Shared number, checked above
            if all1 and all2 and not (all1 & all2): continue # Disjoint numbers

            ratio = difflib.SequenceMatcher(None, v1.name.lower(), v2.name.lower()).ratio()
            if ratio > SIMILARITY_THRESHOLD:
                warnings.append(f"[{context_name}] Potential Duplicate (Name Match {ratio:.0%}): '{v1.name}' vs '{v2.name}'")
    return warnings

def find_duplicates(series: Series, fuzzy: bool = True) -> List[str]:
    all_warnings = []
    if series.volumes:
        all_warnings.extend(_find_duplicates_in_list(series.volumes, "Root", fuzzy))
    for sg in series.sub_groups:
        if sg.volumes:
            all_warnings.extend(_find_duplicates_in_list(sg.volumes, sg.name, fuzzy))
    return all_warnings

def find_structural_duplicates(
    library: Library,
    query: Optional[str] = None
) -> List[str]:
    entities = []
    for main in library.categories:
        for sub in main.sub_categories:
            for series in sub.series:
                loc = f"{main.name} -> {sub.name}"
                entities.append({"name": series.name, "type": "Series", "location": loc, "path": str(series.path)})
                for sg in series.sub_groups:
                     loc_sg = f"{main.name} -> {sub.name} -> {series.name}"
                     entities.append({"name": sg.name, "type": "SubGroup", "location": loc_sg, "path": str(sg.path)})

    if query:
        query_norm = query.lower().strip()
        entities = [e for e in entities if query_norm in e['name'].lower()]

    if not entities:
        return []

    warnings = []
    name_map = {}
    for e in entities:
        norm = e['name'].lower().strip()
        if norm not in name_map:
            name_map[norm] = []
        name_map[norm].append(e)
        
    for norm, group in name_map.items():
        if len(group) > 1:
            msg = f"[Structure] Duplicate Entity '{group[0]['name']}':"
            for item in group:
                msg += f"\n  - [{item['type']}] in {item['location']}\n    Path: {item['path']}"
            warnings.append(msg)
            
    if query:
        keys = list(name_map.keys())
        for i in range(len(keys)):
            for j in range(i+1, len(keys)):
                k1, k2 = keys[i], keys[j]
                ratio = difflib.SequenceMatcher(None, k1, k2).ratio()
                if ratio > SIMILARITY_THRESHOLD:
                    msg = f"[Structure] Potential Duplicate (Name Match {ratio:.0%}):"
                    for item in name_map[k1] + name_map[k2]:
                         msg += f"\n  - [{item['type']}] '{item['name']}' in {item['location']}"
                    warnings.append(msg)
    return warnings

def inspect_archive(file_path: Path, check_integrity: bool = False) -> Tuple[int, bool]:
    """
    Inspects a .cbz (zip) or .cbr (rar) file.

    Args:
        file_path: Path to the archive file.
        check_integrity: If True, performs integrity check (slower).

    Returns:
        Tuple of (page_count, is_corrupt)
        is_corrupt will only be accurate if check_integrity is True.
    """
    ext = file_path.suffix.lower()
    page_count = 0
    is_corrupt = False

    if ext == '.cbz':
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                # Test integrity only if requested
                if check_integrity:
                    if z.testzip() is not None:
                        is_corrupt = True
                        logger.warning(f"Corrupt CBZ file detected: {file_path}")

                # Listing is fast
                for info in z.infolist():
                    if not info.is_dir():
                        if Path(info.filename).suffix.lower() in IMAGE_EXTENSIONS:
                            page_count += 1
        except (zipfile.BadZipFile, PermissionError, OSError) as e:
            is_corrupt = True
            logger.error(f"Error reading CBZ file {file_path}: {e}")
    elif ext == '.cbr':
        if rarfile is None:
            logger.debug(f"Skipping CBR file (rarfile not installed): {file_path}")
            return 0, False  # Skip if rarfile library is not installed
        try:
            with rarfile.RarFile(file_path, 'r') as r:
                # Test integrity only if requested
                if check_integrity:
                    try:
                        r.testrar()
                    except rarfile.Error:
                        is_corrupt = True
                        logger.warning(f"Corrupt CBR file detected: {file_path}")

                # Listing is fast
                for info in r.infolist():
                    if not info.isdir():
                        if Path(info.filename).suffix.lower() in IMAGE_EXTENSIONS:
                            page_count += 1
        except (rarfile.Error, PermissionError, OSError) as e:
            is_corrupt = True
            logger.error(f"Error reading CBR file {file_path}: {e}")

    return page_count, is_corrupt
                    