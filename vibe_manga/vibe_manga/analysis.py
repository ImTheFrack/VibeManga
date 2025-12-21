import re
import logging
import difflib
import zipfile
from typing import List, Tuple, Dict, Set, Optional, Any
from pathlib import Path

from .models import Series, Volume, SubGroup, Library
from .constants import (
    IMAGE_EXTENSIONS,
    SIMILARITY_THRESHOLD,
    MAX_RANGE_SIZE,
    YEAR_RANGE_MIN,
    YEAR_RANGE_MAX,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_GB
)

logger = logging.getLogger(__name__)

try:
    import rarfile
except ImportError:
    rarfile = None
    logger.warning("rarfile library not available - .cbr files will be skipped")

# --- REGEX DEFINITIONS ---

# 1. Volume Patterns
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
CH_REGEX = re.compile(r'''
    \b(?:c|ch\.?|chapter|ep(?:isode)?|\x23) # Prefix: c, ch, ch., chapter, ep, episode, or #
    [\s\._\[]*              # Separator: Optional space, dot, underscore, or bracket
    (?:                     # START ALTERNATIVES
        # OPTION A: Range (e.g. c01-05 or c01-c05)
        (\d+(?:\.\d+)?)\s*[-~]\s*(?:c|ch\.?|chapter|ep(?:isode)?|\x23)?  # Group 1: Start Number
        \s*
        (\d+(?:\.\d+)?)
    |                       # OR
        # OPTION B: Single Number (e.g. c01)
        (\d+(?:\.\d+)?)
    )                       # END ALTERNATIVES
''', re.IGNORECASE | re.VERBOSE)

# 3. Unit Patterns (Explicit 'unit' prefix)
UNIT_REGEX = re.compile(r'''
    \b(?:unit|u)           # Prefix: unit or u
    [\s\._\[]*             # Separator
    (?:
        (\d+(?:\.\d+)?)\s*[-~]\s*(?:unit|u)?
        \s*
        (\d+(?:\.\d+)?)
    |
        (\d+(?:\.\d+)?)
    )
''', re.IGNORECASE | re.VERBOSE)

# 4. Fallback (Raw Numbers)
FALLBACK_NUMBER_REGEX = re.compile(r'\b(\d+(?:\.\d+)?)\b')

# 5. Implicit Ranges (001-099) - Used if no explicit prefixes found
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
    re.compile(r'\bNo\.\s*\d+', re.IGNORECASE),          # No. 8, No. 6
    re.compile(r'\bRanma\s*1\s*2\b', re.IGNORECASE),    # Special case for Ranma 1 2
    re.compile(r'\b5-toubun\b', re.IGNORECASE),          # 5-toubun no Hanayome
    re.compile(r'\b20th\s*Century\s*Boys\b', re.IGNORECASE),
    re.compile(r'\b21st\s*Century\s*Boys\b', re.IGNORECASE),
]

def _parse_regex_matches(matches: List[Tuple]) -> List[float]:
    nums = []
    for m in matches:
        range_start, range_end, single = m[0], m[1], m[2]
        if range_start and range_end:
            try:
                s, e = float(range_start), float(range_end)
                if s.is_integer() and e.is_integer():
                    if s < e and (e - s) < MAX_RANGE_SIZE:
                        nums.extend([float(x) for x in range(int(s), int(e) + 1)])
                    elif s == e:
                        nums.append(s)
            except ValueError: pass
        elif single:
            nums.append(float(single))
    return nums

def classify_unit(name: str) -> Tuple[List[float], List[float], List[float]]:
    clean_name = name
    for pattern in NOISE_PATTERNS:
        clean_name = pattern.sub(" ", clean_name)
    vol_nums, ch_nums, unknown_nums = [], [], []
    vol_nums.extend(_parse_regex_matches(VOL_REGEX.findall(clean_name)))
    ch_nums.extend(_parse_regex_matches(CH_REGEX.findall(clean_name)))
    unknown_nums.extend(_parse_regex_matches(UNIT_REGEX.findall(clean_name)))
    
    if not vol_nums and not ch_nums and not unknown_nums:
        r_matches = IMPLICIT_RANGE_REGEX.findall(clean_name)
        unknown_nums.extend(_parse_regex_matches([(m[0], m[1], None) for m in r_matches]))
        if not unknown_nums:
            for m in FALLBACK_NUMBER_REGEX.findall(clean_name):
                val = float(m)
                if not (YEAR_RANGE_MIN <= val <= YEAR_RANGE_MAX):
                    unknown_nums.append(val)
    logger.debug(f"Classified '{name}' -> v:{vol_nums}, c:{ch_nums}, u:{unknown_nums}")
    return vol_nums, ch_nums, unknown_nums

def extract_number(name: str) -> float:
    v, c, u = classify_unit(name)
    if v: return v[0]
    if c: return c[0]
    if u: return u[0]
    return -1.0

def mask_volume_info(name: str) -> str:
    s = name.lower()
    s = re.sub(r'\bv\d+', '{VOL}', s)
    s = re.sub(r'\bc\d+', '{CH}', s)
    return s.strip()

def _check_sequence_gaps(numbers: List[float], unit_label: str) -> List[str]:
    if not numbers: return []
    sorted_nums = sorted(list(set(int(n) for n in numbers)))
    if not sorted_nums: return []
    gaps = []
    expected = set(range(sorted_nums[0], sorted_nums[-1] + 1))
    missing = sorted(list(expected - set(sorted_nums)))
    if missing:
        ranges = []
        curr_s = curr_e = missing[0]
        for i in range(1, len(missing)):
            if missing[i] == curr_e + 1: curr_e = missing[i]
            else:
                ranges.append((curr_s, curr_e))
                curr_s = curr_e = missing[i]
        ranges.append((curr_s, curr_e))
        for s, e in ranges:
            gaps.append(f"Missing {unit_label} #{s}" if s == e else f"Missing {unit_label} #{s}-{e}")
    return gaps

def format_ranges(numbers: List[float]) -> str:
    if not numbers: return "None"
    # Filter out negative numbers (errors/unknowns)
    valid_nums = sorted(list(set(n for n in numbers if n >= 0)))
    if not valid_nums: return "None"
    
    ranges = []
    curr_s = curr_e = valid_nums[0]
    
    for i in range(1, len(valid_nums)):
        num = valid_nums[i]
        # Sequential check: only for integers. Floats always break a range.
        if num == curr_e + 1 and num.is_integer() and curr_e.is_integer():
            curr_e = num
        else:
            if curr_s == curr_e:
                ranges.append(f"{int(curr_s) if curr_s.is_integer() else curr_s}")
            else:
                ranges.append(f"{int(curr_s) if curr_s.is_integer() else curr_s}-{int(curr_e) if curr_e.is_integer() else curr_e}")
            curr_s = curr_e = num
            
    # Add final range
    if curr_s == curr_e:
        ranges.append(f"{int(curr_s) if curr_s.is_integer() else curr_s}")
    else:
        ranges.append(f"{int(curr_s) if curr_s.is_integer() else curr_s}-{int(curr_e) if curr_e.is_integer() else curr_e}")
        
    return ", ".join(ranges)

def normalize_series_name(name: str) -> str:
    """Normalizes a series name by moving articles to the end (e.g., 'The Ring' -> 'Ring, The')."""
    if not name: return ""
    name = name.strip()
    # Patterns from matcher.py but simplified for general use
    article_pat = r"^(The|A|An|Le|La|Les|Un|Une)\s+(.*)$"
    match = re.match(article_pat, name, re.IGNORECASE)
    if match:
        return f"{match.group(2)}, {match.group(1)}"
    return name

def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string for use as a directory or filename.
    Replaces illegal characters (| : ? * < > " / \\) with full-width equivalents.
    """
    if not name:
        return "Unknown"
    
    replacements = {
        "|": "｜", ":": "：", "?": "？", "*": "＊", 
        "<": "＜", ">": "＞", "\"": "＂", "/": "／", "\\": "＼"
    }
    
    sanitized = name
    for char, rep in replacements.items():
        sanitized = sanitized.replace(char, rep)
        
    # Trim dots and spaces from ends (especially trailing dots cause issues on Windows)
    return sanitized.strip(" .")

def semantic_normalize(name: str) -> str:
    """
    Highly aggressive normalization for semantic matching.
    Strips articles, tags, punctuation, and whitespace.
    """
    if not name: return ""
    # 1. Strip tags [...] (...) {...}
    name = re.sub(r"\[.*?\]|\(.*?\)|\{.*?\}", " ", name)
    # 2. Strip articles
    name = re.sub(r"\b(The|A|An|Le|La|Les|Un|Une)\b", " ", name, flags=re.IGNORECASE)
    
    # 2b. Expand common symbols to alphanumeric equivalents
    name = name.replace("½", "1 2")
    name = name.replace("⅓", "1 3")
    name = name.replace("¼", "1 4")
    # Handle '&' (often 'and' or 'to')
    # If it's Yotsuba&! -> Yotsubato
    name = re.sub(r"(?<=\w)&(?!\w|\s)", "to", name)
    name = name.replace("&", " and ")

    # 3. Strip non-alphanumeric
    name = re.sub(r"[^a-zA-Z0-9]", "", name)
    # 4. Lowercase
    return name.lower()

def find_gaps(series: Series) -> List[str]:
    all_volumes = []
    all_volumes.extend(series.volumes)
    for sg in series.sub_groups: all_volumes.extend(sg.volumes)
    logger.debug(f"Finding gaps for {series.name}, {len(all_volumes)} total volumes found.")
    if not all_volumes: return ["No volumes found."]
    if len(all_volumes) == 1:
        v, c, u = classify_unit(all_volumes[0].name)
        if not v and not c and not u: return []
    vol_nums, ch_nums, unknown_nums = [], [], []
    for vol in all_volumes:
        v, c, u = classify_unit(vol.name)
        vol_nums.extend(v); ch_nums.extend(c); unknown_nums.extend(u)
    vol_gaps = _check_sequence_gaps(vol_nums, "Vol")
    if vol_nums and not vol_gaps: return []
    messages = []
    messages.extend(vol_gaps)
    messages.extend(_check_sequence_gaps(ch_nums, "Ch"))
    if not vol_nums and not ch_nums and unknown_nums:
        messages.extend(_check_sequence_gaps(unknown_nums, "Unit"))
    return messages if messages or (vol_nums or ch_nums or unknown_nums) else []

def find_external_updates(series: Series) -> List[Dict[str, Any]]:
    if not series.external_data or "nyaa_matches" not in series.external_data:
        logger.debug(f"No external data or nyaa_matches for {series.name}")
        return []
        
    logger.debug(f"Checking updates for {series.name} with {len(series.external_data['nyaa_matches'])} matches")
    local_vols, local_chaps = set(), set()
    all_vols = series.volumes + [v for sg in series.sub_groups for v in sg.volumes]
    
    for vol in all_vols:
        v, c, u = classify_unit(vol.name)
        for n in v: local_vols.add(float(n))
        for n in c: local_chaps.add(float(n))
        if not v and not c:
            for n in u: local_chaps.add(float(n))
            
    logger.debug(f"Local vols: {local_vols}, local chaps: {local_chaps}")
    updates = []
    
    for match in series.external_data["nyaa_matches"]:
        m_v_s = match.get("volume_begin")
        m_v_e = match.get("volume_end")
        m_c_s = match.get("chapter_begin")
        m_c_e = match.get("chapter_end")
        
        new_v, new_c = [], []
        
        if m_v_s:
            try:
                s = float(m_v_s)
                e = float(m_v_e) if m_v_e else s
                
                # If it's an integer range, check all integers in between
                if s.is_integer() and e.is_integer():
                    for v_num in range(int(s), int(e) + 1):
                        if float(v_num) not in local_vols:
                            new_v.append(v_num)
                else:
                    # For fractional or single volumes, just check start and end
                    if s not in local_vols: new_v.append(s)
                    if e != s and e not in local_vols: new_v.append(e)
            except (ValueError, TypeError) as ex:
                logger.debug(f"Error parsing volume range {m_v_s}-{m_v_e}: {ex}")
        
        if m_c_s:
            try:
                s = float(m_c_s)
                e = float(m_c_e) if m_c_e else s
                
                if s.is_integer() and e.is_integer():
                    for c_num in range(int(s), int(e) + 1):
                        if float(c_num) not in local_chaps:
                            new_c.append(c_num)
                else:
                    if s not in local_chaps: new_c.append(s)
                    if e != s and e not in local_chaps: new_c.append(e)
            except (ValueError, TypeError) as ex:
                logger.debug(f"Error parsing chapter range {m_c_s}-{m_c_e}: {ex}")
                
        if new_v or new_c:
            logger.debug(f"Found new content in {match.get('name')}: vols={new_v}, chaps={new_c}")
            updates.append({
                "torrent_name": match.get("name"),
                "magnet": match.get("magnet_link"),
                "new_volumes": new_v,
                "new_chapters": new_c,
                "size": match.get("size"),
                "date": match.get("date"),
                "seeders": match.get("seeders")
            })
            
    # Sort by date descending (newest first)
    try:
        updates.sort(key=lambda x: int(x.get("date", 0)), reverse=True)
    except (ValueError, TypeError):
        pass
        
    return updates

def _find_duplicates_in_list(
    volumes: List[Volume],
    context_name: str,
    fuzzy: bool = True
) -> List[str]:
    warnings, num_map = [], {}
    for vol in volumes:
        v, c, u = classify_unit(vol.name)
        nums = v or c or u
        for num in nums:
            if num not in num_map: num_map[num] = []
            if vol not in num_map[num]: num_map[num].append(vol)
    for num, vols in num_map.items():
        if len(vols) > 1:
            dupes = set()
            for i in range(len(vols)):
                for j in range(i + 1, len(vols)):
                    if vols[i].name != vols[j].name:
                        if difflib.SequenceMatcher(None, mask_volume_info(vols[i].name), mask_volume_info(vols[j].name)).ratio() > SIMILARITY_THRESHOLD:
                            dupes.update([vols[i].name, vols[j].name])
            if dupes:
                files_str = ", ".join([f"'{n}'" for n in sorted(list(dupes))])
                warnings.append(f"[{context_name}] Duplicate Vol/Ch #{num}: {files_str}")
    if not fuzzy: return warnings
    for i in range(len(volumes)):
        for j in range(i + 1, len(volumes)):
            v1, v2 = volumes[i], volumes[j]
            v1_v, v1_c, v1_u = classify_unit(v1.name); v2_v, v2_c, v2_u = classify_unit(v2.name)
            if set(v1_v + v1_c + v1_u) & set(v2_v + v2_c + v2_u): continue
            if (v1_v or v1_c or v1_u) and (v2_v or v2_c or v2_u) and not (set(v1_v + v1_c + v1_u) & set(v2_v + v2_c + v2_u)): continue
            if difflib.SequenceMatcher(None, v1.name.lower(), v2.name.lower()).ratio() > SIMILARITY_THRESHOLD:
                warnings.append(f"[{context_name}] Potential Duplicate (Name Match {difflib.SequenceMatcher(None, v1.name.lower(), v2.name.lower()).ratio():.0%}): '{v1.name}' vs '{v2.name}'")
    return warnings

def find_duplicates(series: Series, fuzzy: bool = True) -> List[str]:
    all_w = []
    if series.volumes: all_w.extend(_find_duplicates_in_list(series.volumes, "Root", fuzzy))
    for sg in series.sub_groups:
        if sg.volumes: all_w.extend(_find_duplicates_in_list(sg.volumes, sg.name, fuzzy))
    return all_w

def find_structural_duplicates(
    library: Library,
    query: Optional[str] = None
) -> List[str]:
    entities = []
    for main in library.categories:
        for sub in main.sub_categories:
            for series in sub.series:
                entities.append({"name": series.name, "type": "Series", "location": f"{main.name} -> {sub.name}", "path": str(series.path)})
                for sg in series.sub_groups:
                     entities.append({"name": sg.name, "type": "SubGroup", "location": f"{main.name} -> {sub.name} -> {series.name}", "path": str(sg.path)})
    if query:
        q = query.lower().strip()
        entities = [e for e in entities if q in e['name'].lower()]
    if not entities: return []
    warnings, name_map = [], {}
    for e in entities:
        n = semantic_normalize(e['name'])
        if not n: continue
        if n not in name_map: name_map[n] = []
        name_map[n].append(e)
    for group in name_map.values():
        if len(group) > 1:
            msg = f"[Structure] Duplicate Entity '{group[0]['name']}':"
            for item in group: msg += f"\n  - [{item['type']}] in {item['location']}\n    Path: {item['path']}"
            warnings.append(msg)
    if query:
        keys = list(name_map.keys())
        for i in range(len(keys)):
            for j in range(i+1, len(keys)):
                if difflib.SequenceMatcher(None, keys[i], keys[j]).ratio() > SIMILARITY_THRESHOLD:
                    msg = f"[Structure] Potential Duplicate (Name Match {difflib.SequenceMatcher(None, keys[i], keys[j]).ratio():.0%}):"
                    for item in name_map[keys[i]] + name_map[keys[j]]: msg += f"\n  - [{item['type']}] '{item['name']}' in {item['location']}"
                    warnings.append(msg)
    return warnings

def inspect_archive(file_path: Path, check_integrity: bool = False) -> Tuple[int, bool]:

    ext, page_count, is_corrupt = file_path.suffix.lower(), 0, False

    if ext == '.cbz':

        try:

            with zipfile.ZipFile(file_path, 'r') as z:

                if check_integrity and z.testzip() is not None: is_corrupt = True

                page_count = sum(1 for info in z.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in IMAGE_EXTENSIONS)

        except Exception: is_corrupt = True

    elif ext == '.cbr' and rarfile:

        try:

            with rarfile.RarFile(file_path, 'r') as r:

                if check_integrity:

                    try: r.testrar()

                    except Exception: is_corrupt = True

                page_count = sum(1 for info in r.infolist() if not info.isdir() and Path(info.filename).suffix.lower() in IMAGE_EXTENSIONS)

        except Exception: is_corrupt = True

    return page_count, is_corrupt



def parse_size(size_str: str) -> int:

    """Parses a size string like '1.2 GiB' or '500 MiB' into bytes."""

    if not size_str:

        return 0

    # Match numeric part and unit (K/M/G/T)

    match = re.search(r"([\d.]+)\s*([KMGT]i?B)", size_str.strip(), re.IGNORECASE)

    if not match:

        return 0

    val = float(match.group(1))

    unit = match.group(2).upper()

    multiplier = 1

    if unit.startswith("K"): multiplier = BYTES_PER_KB

    elif unit.startswith("M"): multiplier = BYTES_PER_MB

    elif unit.startswith("G"): multiplier = BYTES_PER_GB

    elif unit.startswith("T"): multiplier = BYTES_PER_GB * 1024

    return int(val * multiplier)



def format_size(bytes_val: float) -> str:

    """Formats a byte value into a human-readable string (MB or GB)."""

    abs_val = abs(bytes_val)

    if abs_val >= BYTES_PER_GB:

        return f"{bytes_val / BYTES_PER_GB:.2f} GB"

    return f"{bytes_val / BYTES_PER_MB:.2f} MB"
